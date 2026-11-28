"""Isolated real SQLite projections into the existing material/seasonal core."""
import calendar
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from tests import test_podmasterye_accounting as accounting_tests
from tests.test_podmasterye_market_analytics import order,proof,ASOF,START
from platform_core import podmasterye_book as book, podmasterye_seasonal as seasonal, market_quantity as quantity
from platform_core import podmasterye_market_analytics as analytics
from platform_core.identity import _principal


class MarketplacePlanning(unittest.TestCase):
    actor=accounting_tests.Accounting.actor
    call=accounting_tests.Accounting.call
    prepare=accounting_tests.Accounting.prepare
    commit=accounting_tests.Accounting.commit
    op=accounting_tests.Accounting.op
    report=accounting_tests.Accounting.report
    recipe=accounting_tests.Accounting.recipe

    def setUp(self):
        self.enterContext(patch.dict(os.environ,{"PODMASTERYE_MARKET_WORKER":"0"}))
        self.enterContext(patch.object(book,"today",return_value=ASOF))
        accounting_tests.Accounting.setUp(self)
        self.store=self.app.state.identity
        self.token=self.h["Authorization"].split(" ",1)[1]
        self.workspace=_principal(self.store._db,self.token)[1]

    def add_store(self,provider,rows,coverage,mappings,*,workspace=None):
        w=workspace or self.workspace;cid=uuid4().hex;sid=uuid4().hex
        observed=int(datetime(ASOF.year,ASOF.month,ASOF.day,tzinfo=timezone.utc).timestamp())
        with self.store._write() as db:
            db.execute("INSERT INTO pm_market_connections(id,workspace,provider,name,encrypted,checked) VALUES(?,?,?,?,?,1)",(cid,w,provider,cid,b"fixture-never-read"))
            db.execute("INSERT INTO market_data_stores(id,workspace,provider,seller,verified) VALUES(?,?,?,?,1)",(sid,w,provider,cid))
            db.execute("INSERT INTO market_data_links VALUES(?,?,1)",(cid,sid))
            with quantity.local(db,w,provider,create=True) as dest:
                for raw in rows:
                    r={**deepcopy(raw),"provider":provider,"store_id":sid}
                    start=r.get("ordered_at") or r.get("interval_from") or r.get("event_date")
                    end=r.get("interval_to") or start
                    source=r.get("source_id") or {"ozon":"OZ-03","wb":"WB-03","yandex_market":"YM-05"}[provider]
                    dest.execute("INSERT INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?)",(sid,source,r["natural_key"],start,end,observed,json.dumps(r),"fixture-receipt",1))
                for raw in coverage:
                    c={**raw,"provider":provider,"store_id":sid}
                    dest.execute("INSERT INTO quantity_coverage VALUES(?,?,?,?,?,?,?)",(sid,c["source_id"],c["from"],c["to"],json.dumps(c),observed,"fixture-receipt"))
                for sku,pid in mappings.items():
                    dest.execute("INSERT INTO quantity_catalog VALUES(?,?,?,?,?)",(sid,sku,json.dumps({"sku":sku,"name":"Артикул","category_id":"category-a"}),1,"fixture-receipt"))
                    db.execute("INSERT INTO market_quantity_links(workspace,store,sku,product) VALUES(?,?,?,?)",(w,sid,sku,pid))
        return sid

    @staticmethod
    def realization(provider,sku,*,delivered=100,returned=20,day="2025-05-15"):
        source={"ozon":"OZ-03","wb":"WB-04","yandex_market":"YM-05"}[provider]
        row={"sku":sku,"natural_key":"realization-"+sku,"quantity_basis":"calendar_event","event_date":day,
             "delivered_qty":delivered,"physical_return_qty":returned,"physical_returns_known":True,"complete":True,"source_id":source}
        cov={"source_id":source,"role":"realization","quantity_basis":"calendar_event","from":day[:7]+"-01",
             "to":day[:7]+"-"+str(calendar.monthrange(int(day[:4]),int(day[5:7]))[1]),"state":"ready","complete":True}
        return row,cov

    def test_three_marketplaces_use_same_recipe_quality_and_carried_stock(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        self.op("opening",material=mid,quantity=100,total="100")
        self.op("quality_policy",return_defect_percent="25",production_scrap_percent="10")
        for provider in ("ozon","wb","yandex_market"):
            if provider=="ozon":
                r=order(provider=provider,units=100,losses=20,ordered_at="2025-05-15")
                cov=proof(provider,start=ASOF.replace(year=2025,month=5,day=1))
            else:
                r,c=self.realization(provider,"100");cov=[c]
            self.add_store(provider,[r],cov,{"100":pid})
        before=self.report()
        with self.store._lock:
            plan=seasonal.plan(self.store._db,self.workspace,source="all_marketplaces",history_from="2025-05",history_to="2025-05",target_from="2027-05")
        self.assertTrue(plan["complete"],plan)
        product=plan["months"][0]["products"][0]
        self.assertEqual((product["forecastSales"],product["replacementDemand"],product["produce"]),(240,255,255))
        material=plan["totals"][0]
        self.assertEqual((material["nominalNeed"],material["need"],material["buyPacks"]),(2295,2550,25))
        self.assertEqual(self.report()["materials"],before["materials"])
        self.assertEqual(self.report()["summary"],before["summary"])
        self.assertEqual(self.report()["event_count"],before["event_count"])
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM market_data_events").fetchone()[0],0)

    def test_immature_sales_short_forecast_and_quality_share_local_data(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        self.op("opening",material=mid,quantity=100,total="100")
        self.op("quality_policy",return_defect_percent="25",production_scrap_percent="10")
        mature=order(units=1000,losses=200)
        fresh=order("fresh",units=100,losses=5,days=5,delivered_qty=40,physical_return_qty=5,terminal=False)
        self.add_store("ozon",[mature,fresh],proof(),{"100":pid})
        before=self.report()
        with self.store._lock:
            result=book.report(self.store._db,self.workspace,source="all_marketplaces",view="planning",horizon=30,lead=0,safety=0)
        self.assertTrue(result["planning_complete"],result)
        p=result["planning"][0]
        self.assertEqual((p["nominal_production_need"],p["gross_production_need"],p["buy_packs"]),("765","850",8))
        self.assertEqual(result["market_sales"]["totals"]["net"],35)
        self.assertEqual(result["market_sales"]["totals"]["estimated_net"],80)
        self.assertEqual(self.report()["summary"],before["summary"])
        self.assertEqual(self.report()["actual_consumption"],before["actual_consumption"])

    def test_unknown_return_split_blocks_defect_plan_but_not_zero_defect(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        self.op("opening",material=mid,quantity=1,total="1")
        self.op("writeoff",material=mid,quantity=1)
        row=order(provider="wb",units=100,losses=20,quantity_basis="funnel_interval",interval_from="2025-05-01",interval_to="2025-05-31",
                  delivered_qty=None,physical_return_qty=None,physical_returns_known=False,source_id="WB-03")
        row.pop("ordered_at")
        self.add_store("wb",[row],proof("wb",basis="funnel_interval",start=ASOF.replace(year=2025,month=5,day=1),end=ASOF.replace(year=2025,month=5,day=31))[:1],{"100":pid})
        args=dict(source="wb",history_from="2025-05",history_to="2025-05",target_from="2027-05")
        with self.store._lock:result=seasonal.plan(self.store._db,self.workspace,**args)
        self.assertTrue(result["complete"],result)
        self.assertEqual(result["totals"][0]["need"],720)
        self.op("quality_policy",return_defect_percent="25")
        with self.store._lock:result=seasonal.plan(self.store._db,self.workspace,**args)
        self.assertFalse(result["complete"])
        self.assertEqual(result["totals"],[])
        self.assertTrue(any("возврат" in p["reason"] for p in result["problems"]))

    def test_data_isolation_mapping_and_no_implicit_ledger_addition(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        self.op("opening",material=mid,quantity=1000,total="1000",day="2025-05-01")
        self.op("sale",product=pid,quantity=10,unit_price="10",paid_amount="100",auto_produce=True,day="2025-05-15")
        row,cov=self.realization("yandex_market","100",delivered=10,returned=0)
        sid=self.add_store("yandex_market",[row],[cov],{"100":pid})
        with self.store._lock:
            d=analytics.sales(self.store._db,self.workspace,from_="2025-05-01",to="2025-05-31")
        self.assertEqual(d["totals"]["net"],10)
        other_token=self.other["Authorization"].split(" ",1)[1]
        other=analytics.read(self.store,other_token,action="sales",from_="2025-05-01",to="2025-05-31")
        self.assertIsNone(other["totals"]["net"])
        with self.store._write() as db:
            seasonal.map_product(db,self.workspace,sid,"100",None)
        with self.store._lock:
            result=seasonal.plan(self.store._db,self.workspace,source=sid,history_from="2025-05",history_to="2025-05",target_from="2027-05")
        self.assertFalse(result["complete"])
        self.assertTrue(any("Не сопоставлен" in p["reason"] for p in result["problems"]))

    def test_calendar_excess_returns_never_create_stock_for_next_month(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        self.op("opening",material=mid,quantity=1,total="1")
        self.op("writeoff",material=mid,quantity=1)
        may,mc=self.realization("yandex_market","100",delivered=10,returned=20)
        june,jc=self.realization("yandex_market","100",delivered=10,returned=0,day="2025-06-15")
        june["natural_key"]+="-june"
        sid=self.add_store("yandex_market",[may,june],[mc,jc],{"100":pid})
        with self.store._lock:
            result=seasonal.plan(self.store._db,self.workspace,source=sid,history_from="2025-05",history_to="2025-06",target_from="2027-05")
        self.assertTrue(result["complete"],result)
        self.assertEqual(result["months"][0]["products"],[])
        self.assertEqual(result["months"][1]["products"][0]["produce"],10)
        self.assertEqual(result["totals"][0]["need"],90)

    def test_short_forecast_does_not_hide_archived_recipe_material(self):
        ids=self.recipe(pack=100,usage=9,price="100");pid,mid=ids["product_id"],ids["material_id"]
        row,cov=self.realization("yandex_market","100",delivered=10,returned=0,day="2026-11-15")
        self.add_store("yandex_market",[row],[cov],{"100":pid})
        with self.store._write() as db:
            db.execute("UPDATE pm_materials SET archived=1 WHERE workspace=? AND id=?",(self.workspace,mid))
        with self.store._lock:
            result=book.report(self.store._db,self.workspace,source="all_marketplaces",view="planning")
        self.assertFalse(result["planning_complete"])
        self.assertEqual(result["planning"],[])
        self.assertTrue(any("недоступные материалы" in p["reason"] for p in result["planning_problems"]))

    def test_calendar_wb_return_cannot_be_used_as_physical_defect_base(self):
        from tests.fixtures import market_quantity_cases as cases
        ids=self.recipe(pack=100,usage=9,price="100");pid=ids["product_id"]
        sequence=cases.success_sequence("WB-04",cases.context_for("WB-04",**{"from":"2025-05-01","to":"2025-05-31"}))
        rows=[r for step in sequence for r in step["outcome"].get("rows",[])]
        cov={**sequence[-1]["outcome"]["coverage"],"source_id":"WB-04","role":"realization","state":"ready"}
        self.add_store("wb",rows,[cov],{"101":pid})
        args=dict(source="wb",history_from="2025-05",history_to="2025-05",target_from="2027-05")
        with self.store._lock:plain=seasonal.plan(self.store._db,self.workspace,**args)
        self.assertFalse(plain["complete"],plain)
        self.assertEqual(plain["totals"],[])
        self.op("quality_policy",return_defect_percent="25")
        with self.store._lock:
            defect=seasonal.plan(self.store._db,self.workspace,**args)
            delivered=seasonal.plan(self.store._db,self.workspace,**args,metric="delivered")
        self.assertFalse(defect["complete"])
        self.assertEqual(defect["totals"],[])
        self.assertTrue(delivered["complete"],delivered)
        self.assertEqual(delivered["totals"][0]["need"],27)
        recent=cases.success_sequence("WB-04",cases.context_for("WB-04",**{"from":(ASOF-timedelta(days=29)).isoformat(),"to":ASOF.isoformat()}))
        recent_rows=[r for step in recent for r in step["outcome"].get("rows",[])]
        sid=self.add_store("wb",recent_rows,[{**recent[-1]["outcome"]["coverage"],"source_id":"WB-04","role":"realization","state":"ready"}],{"101":pid})
        self.op("quality_policy",return_defect_percent=None)
        with self.store._lock:short=book.report(self.store._db,self.workspace,source=sid,view="planning")
        self.assertFalse(short["planning_complete"])
        self.assertTrue(any("Календарный возврат" in p["reason"] for p in short["planning_problems"]))

    def test_internal_full_book_export_preserves_all_events_and_totals(self):
        # Real writes exceed the public page size; a full export must not silently
        # omit the remainder or derive its totals from just the first page.
        for i in range(103):self.op("expense",category="Прочее",total="1",note="export row "+str(i))
        with self.store._lock:
            public=book.report(self.store._db,self.workspace,view="journal")
            full=book.report(self.store._db,self.workspace,view="journal",_unpaginated=True)
        self.assertEqual((len(public["events"]),public["event_count"]),(100,103))
        self.assertEqual(len(full["events"]),103)
        self.assertEqual(len({row["id"] for row in full["events"]}),103)
        self.assertEqual(full["events"][:100],public["events"])


if __name__=="__main__":unittest.main()
