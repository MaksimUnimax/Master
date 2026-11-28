"""Seasonal forecast uses dated sales, current recipes and carried stock, not AI."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch,AsyncMock
from tests.test_podmasterye_accounting import Accounting
from platform_core import podmasterye_book as book,podmasterye_seasonal as seasonal,podmasterye_yandex_market as ym

class Seasonal(unittest.TestCase):
    setUp=Accounting.setUp
    actor=Accounting.actor
    call=Accounting.call
    prepare=Accounting.prepare
    commit=Accounting.commit
    op=Accounting.op
    report=Accounting.report
    recipe=Accounting.recipe

    def request(self,action,body,h=None,status=200):
        r=self.call("/api/accounting/seasonal/"+action,body,h)
        self.assertEqual(r.status_code,status,r.text)
        return r.json()
    def plan(self,**kw):
        return self.request("plan",{"source":"ledger","history_from":"2025-05","history_to":"2025-06","target_from":"2027-05",**kw})

    def test_history_recipe_and_inventory_carry(self):
        ids=self.recipe(pack=100,usage=3,price="100")
        m,p=ids["material_id"],ids["product_id"]
        self.op("opening",material=m,quantity=1000,total="1000",day="2025-05-01")
        self.op("manufacture",product=p,quantity=120,day="2025-05-02")
        self.op("sale",product=p,quantity=100,unit_price="10",paid_amount="1000",day="2025-05-03")
        self.op("sale",product=p,quantity=50,unit_price="10",paid_amount="500",auto_produce=True,day="2025-06-01")
        may=self.report(start="2025-05-01",end="2025-05-31")
        self.assertEqual(may["consumption"][0]["quantity"],300)
        self.assertEqual(may["actual_consumption"][0]["production_quantity"],360)
        june=self.report(start="2025-06-01",end="2025-06-30")
        self.assertEqual(june["consumption"][0]["quantity"],150)
        self.assertEqual(june["actual_consumption"][0]["production_quantity"],90)
        self.recipe(pack=100,usage=4,price="100")
        self.op("manufacture",product=p,quantity=10,day=self.day)
        self.op("writeoff",material=m,quantity=440,day=self.day)
        before=self.report()
        self.assertEqual(before["materials"][0]["quantity"],70)
        result=self.plan()
        self.assertTrue(result["complete"])
        self.assertTrue(result["stockComplete"])
        self.assertEqual([x["targetMonth"] for x in result["months"]],["2027-05","2027-06"])
        self.assertEqual([x["products"][0]["forecastSales"] for x in result["months"]],[100,50])
        self.assertEqual([x["products"][0]["produce"] for x in result["months"]],[90,50])
        self.assertEqual([x["materials"][0]["need"] for x in result["months"]],[360,200])
        self.assertEqual([x["materials"][0]["opening"] for x in result["months"]],[70,10])
        self.assertEqual([x["materials"][0]["buyPacks"] for x in result["months"]],[3,2])
        self.assertEqual(result["totals"][0]["buyQuantity"],500)
        self.assertEqual(result["totals"][0]["need"],560)
        self.assertEqual(result["totals"][0]["closing"],10)
        self.assertEqual(result["totals"][0]["costRub"],"500.00")
        self.assertEqual(self.report()["materials"],before["materials"])
        self.assertEqual(self.report()["products"],before["products"])
        self.assertEqual(self.report()["event_count"],before["event_count"])

    def test_return_does_not_restore_raw_material(self):
        ids=self.recipe(pack=100,usage=3,price="100")
        m,p=ids["material_id"],ids["product_id"]
        self.op("opening",material=m,quantity=100,total="100",day="2025-05-01")
        sale=self.op("sale",product=p,quantity=10,unit_price="10",paid_amount="100",auto_produce=True,day="2025-05-02")
        self.op("return",sale=sale["id"],quantity=2,refund="20",restock=False,day="2025-05-03")
        report=self.report(start="2025-05-01",end="2025-05-31")
        self.assertEqual(report["consumption"][0]["quantity"],24)
        self.assertEqual(report["actual_consumption"][0]["production_quantity"],30)
        self.assertEqual(report["materials"][0]["quantity"],70)
        self.op("writeoff",material=m,quantity=5,day="2025-05-04")
        report=self.report(start="2025-05-01",end="2025-05-31")
        self.assertEqual(report["actual_consumption"][0]["writeoff_quantity"],5)
        self.assertEqual(report["actual_consumption"][0]["production_quantity"],30)

    def setup_market(self):
        secret="fixture-ym-seasonal"
        r=self.call("/api/integrations/marketplaces",{"provider":"yandex_market","name":"Учебный Маркет","fields":{"api_key":secret}})
        self.assertEqual(r.status_code,200,r.text);cid=r.json()["id"]
        shop={"campaignId":123,"businessId":12,"name":"Учебный","placementType":"FBS","apiAvailability":"AVAILABLE"}
        r=self.call("/api/integrations/marketplaces/"+cid+"/check",{})
        self.assertEqual(r.status_code,200,r.text)
        # Verification is now an asynchronous durable job. These domain tests
        # seed an explicitly isolated, verified legacy snapshot; provider/queue
        # execution is covered by the adapter integration suite, not this fake.
        with self.app.state.identity._write() as db:
            db.execute("UPDATE pm_market_connections SET checks=?,checked=1,details=? WHERE id=?",
                (json.dumps({"Токен":"verified","Список магазинов":"verified"}),
                 json.dumps({"complete":True,"scopes":["ALL_METHODS_READ_ONLY"],"campaigns":[shop]}),cid))
        return cid,"ym:"+cid+":123"
    def snapshot(self,cid,month,delivered=100,returned=0,no_data=False,state="ready"):
        products=[] if no_data else [{"sku":"SKU-A","name":"Оберег","delivered":delivered,"returned":returned,"net":delivered-returned,"unredeemed":0}]
        d={"kind":"realization","month":month,"collected":1,"products":products,"totals":{"delivered":delivered,"returned":returned,"net":delivered-returned,"unredeemed":0},"rows":[]}
        if no_data:d["noData"]=True
        with self.app.state.identity._write() as db:
            db.execute("INSERT INTO pm_ym_realization VALUES(?,1,123,?,?,NULL,1,1,?,NULL)",(cid,month,state,json.dumps(d)))
    def test_market_missing_month_mapping_and_no_double_count(self):
        ids=self.recipe(pack=100,usage=4,price="100")
        m,p=ids["material_id"],ids["product_id"]
        self.op("opening",material=m,quantity=50,total="50",day=self.day)
        cid,source=self.setup_market()
        self.snapshot(cid,"2025-05",100,10)
        h=self.request("history",{"source":source,"a":"2025-05","b":"2025-06"})
        self.assertFalse(h["complete"])
        self.assertEqual(h["products"][0]["net"],90)
        self.assertEqual(h["months"][1]["state"],"not_collected")
        self.assertIsNone(h["products"][0]["productId"])
        forecast=self.plan(source=source)
        self.assertFalse(forecast["complete"]);self.assertEqual(forecast["months"],[])
        self.snapshot(cid,"2025-06",20,0)
        self.assertFalse(self.plan(source=source)["complete"])
        self.request("map",{"source":source,"sku":"SKU-A","product":p})
        r=self.plan(source=source)
        self.assertTrue(r["complete"])
        self.assertEqual([x["products"][0]["forecastSales"] for x in r["months"]],[90,20])
        self.assertEqual(r["totals"][0]["need"],440)
        self.assertEqual(r["totals"][0]["buyPacks"],4)
        self.assertEqual(self.plan(source=source,metric="delivered")["totals"][0]["need"],480)
        self.assertEqual(self.report()["summary"]["sales_quantity"],0)
        self.assertEqual(self.report()["materials"][0]["quantity"],50)
        self.request("history",{"source":source,"a":"2025-05","b":"2025-06"},self.other,404)
        self.request("map",{"source":source,"sku":"SKU-A","product":p},self.other,404)
        self.request("map",{"source":source,"sku":"unknown","product":p},status=400)
        self.request("map",{"source":source,"sku":"SKU-A","product":"foreign"},status=400)

    def test_no_data_and_unknown_stock(self):
        ids=self.recipe(pack=100,usage=4,price="100");cid,source=self.setup_market()
        self.snapshot(cid,"2025-05",5,0);self.snapshot(cid,"2025-06",0,0,no_data=True)
        self.request("map",{"source":source,"sku":"SKU-A","product":ids["product_id"]})
        self.assertFalse(self.plan(source=source)["complete"])
        d=self.plan(source=source,accept_no_data=True)
        self.assertTrue(d["complete"]);self.assertFalse(d["stockComplete"])
        self.assertEqual(d["totals"][0]["buyPacks"],1)
        self.assertEqual(d["totals"][0]["need"],20)
        self.assertEqual(d["months"][1]["materials"],[])
        r=self.call("/api/integrations/marketplaces/"+cid+"/keys",{"version":1,"fields":{"api_key":"new-fixture-secret"}})
        self.assertEqual(r.status_code,200)
        self.request("history",{"source":source,"a":"2025-05","b":"2025-06"},status=409)
    def test_full_year_seasonality_and_rounded_packs(self):
        ids=self.recipe(pack=100,usage=4,price="100")
        self.op("opening",material=ids["material_id"],quantity=40,total="40",day=self.day)
        cid,source=self.setup_market()
        for m in range(1,13):self.snapshot(cid,f"2025-{m:02d}",100 if m==5 else 10)
        self.request("map",{"source":source,"sku":"SKU-A","product":ids["product_id"]})
        r=self.plan(source=source,history_from="2025-01",history_to="2025-12",target_from="2027-01")
        self.assertTrue(r["complete"])
        self.assertEqual(len(r["months"]),12)
        self.assertEqual(r["months"][4]["products"][0]["forecastSales"],100)
        self.assertEqual(r["totals"][0]["need"],840)
        self.assertEqual(r["totals"][0]["buyPacks"],8)
        self.assertEqual(r["totals"][0]["closing"],0)
        self.assertEqual(self.report()["materials"][0]["quantity"],40)
        self.assertEqual(self.report()["summary"]["sales_quantity"],0)
    def test_empty_ledger_is_not_confirmed_zero(self):
        d=self.plan()
        self.assertFalse(d["complete"])
        self.assertEqual(len(d["problems"]),2)
        d=self.plan(accept_empty_ledger=True)
        self.assertTrue(d["complete"])
        self.assertEqual(d["totals"],[])
        self.assertTrue(any("предположение" in v for v in d["warnings"]))
    def test_range_rules(self):
        self.assertEqual(len(seasonal.months("2025-01","2025-12")),12)
        for a,b in (("2025-01","2026-01"),("2025-06","2025-05"),("2025-00","2025-06")):
            with self.assertRaises(ValueError):seasonal.months(a,b)
        d=self.plan(history_from=self.day[:7],history_to=self.day[:7])
        self.assertFalse(d["complete"])
        self.assertEqual(d["coverage"][0]["state"],"partial_month")
        self.request("plan",{"source":"ledger","history_from":"2025-05","history_to":"2025-05","target_from":"2025-05"},status=400)
