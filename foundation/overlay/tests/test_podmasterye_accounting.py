"""Accounting integration checks on the isolated application, no provider calls."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from starlette.testclient import TestClient
from openpyxl import load_workbook
from platform_core.chat_api import create_app
from platform_core.identity import IdentityStore
from platform_core import podmasterye_book as book, podmasterye_matrix as matrix

P="fixture-accounting-password"
ORIGIN="https://podmaster.example"

class Accounting(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db=self.tmp/"book.sqlite3"
        with IdentityStore(self.db) as store:
            store.create_account("owner",P);store.create_account("other",P)
        self.enterContext(patch.dict(os.environ,{"HARNESS_OFFLINE_MODEL":"0","HARNESS_USAGE_JOURNAL":str(self.tmp/"usage.jsonl")}))
        os.environ.pop("HARNESS_MODEL_GATEWAY_URL",None)
        self.app=create_app(self.db,self.tmp/"chats")
        self.client=self.enterContext(TestClient(self.app,base_url=ORIGIN))
        self.h=self.actor("owner");self.other=self.actor("other")
        self.day=book.today().isoformat();self.yesterday=(book.today()-timedelta(days=1)).isoformat()
    def actor(self,name):
        return {"Authorization":"Bearer "+self.app.state.identity.login(name,P)}
    def call(self,url,body,h=None):
        return self.client.post(url,headers=h or self.h,json=body)
    def prepare(self,op,args,h=None,expect=200):
        r=self.call("/api/accounting/preview",{"operation":op,"arguments":args},h)
        self.assertEqual(r.status_code,expect,r.text)
        return r.json()
    def commit(self,draft,rid=None,h=None,expect=200):
        r=self.call("/api/accounting/commit",{"requestId":rid or uuid4().hex,"operation":draft["operation"],"arguments":draft["arguments"],"revision":draft["revision"]},h)
        self.assertEqual(r.status_code,expect,r.text)
        return r.json()
    def op(self,op,**args):
        return self.commit(self.prepare(op,args))
    def report(self,h=None,**q):
        r=self.client.get("/api/accounting",headers=h or self.h,params=q)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def recipe(self,material="Бусины",product="Браслет",pack=400,usage=10,price="800",unit="шт"):
        r=self.call("/api/production/recipe",{"requestId":uuid4().hex,"recipe":{"material":material,"product":product,"pack_quantity":pack,"usage_quantity":usage,"pack_price":price,"unit":unit}})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def seed(self,qty=100,value="200.00",usage=10):
        ids=self.recipe(usage=usage)
        self.op("opening",material=ids["material_id"],quantity=qty,total=value,day=self.day)
        return ids
    def test_moving_average_and_fifo_control(self):
        ids=self.seed();m=ids["material_id"];p=ids["product_id"]
        self.op("purchase",material=m,quantity=100,purchase_unit="base",total="600",supplier="Тест",day=self.day)
        d=self.report();self.assertEqual((d["materials"][0]["quantity"],d["materials"][0]["value_rub"]),(200,"800.00"))
        batch=self.op("manufacture",product=p,quantity=3,day=self.day)
        self.assertEqual(batch["cost_rub"],"120.00")
        self.op("purchase",material=m,quantity=30,purchase_unit="base",total="320",day=self.day)
        d=self.report();self.assertEqual((d["materials"][0]["quantity"],d["materials"][0]["value_rub"],d["products"][0]["value_rub"]),(200,"1000.00","120.00"))
        s=self.op("sale",product=p,quantity=4,unit_price="300",paid_amount="1200",channel="Розница",auto_produce=True,day=self.day)
        self.assertEqual(s["cogs_rub"],"170.00")
        d=self.report();v=d["summary"]
        self.assertEqual((v["revenue"],v["cogs"],v["gross_profit"],v["net_profit"],v["cashflow"]),("1200.00","170.00","1030.00","1030.00","280.00"))
        self.assertEqual((d["materials"][0]["quantity"],d["products"][0]["quantity"],v["inventory_rub"]),(190,0,"950.00"))
        self.assertEqual(d["by_channel"][0]["name"],"Розница")
        self.assertEqual(d["monthly"][0]["cogs"],"170.00")
    def test_pack_purchase_and_forecast(self):
        ids=self.recipe(usage=40)
        self.op("purchase",material=ids["material_id"],quantity=14,purchase_unit="pack",total="11200",day=self.day)
        self.op("writeoff",material=ids["material_id"],quantity=120,day=self.day)
        self.op("sale",product=ids["product_id"],quantity=120,unit_price="300",paid_amount="36000",auto_produce=True,day=self.day)
        d=self.report(horizon=30,lead=5,safety=0)
        self.assertEqual(d["materials"][0]["quantity"],680)
        plan=d["planning"][0]
        self.assertEqual((plan["sold_equivalent_units"],plan["sold_equivalent_packs"],plan["buy_packs"],plan["daily_forecast"]),(4800,"12.000",11,"160.000"))
        self.assertTrue(plan["order_now"]);self.assertEqual(plan["order_day"],self.day)
        self.assertEqual(self.report(horizon=30,lead=5,safety=3)["planning"][0]["buy_packs"],12)
    def test_payment_and_return_good_and_damaged(self):
        ids=self.seed();p=ids["product_id"]
        self.op("manufacture",product=p,quantity=4,day=self.day)
        s=self.op("sale",product=p,quantity=4,unit_price="100",paid_amount="100",day=self.day)
        self.assertEqual(s["due_rub"],"300.00")
        self.op("payment",sale=s["id"],amount="300",day=self.day)
        self.assertEqual(self.report()["summary"]["cashflow"],"400.00")
        self.op("return",sale=s["id"],quantity=1,refund="100",restock=True,day=self.day)
        self.op("return",sale=s["id"],quantity=1,refund="100",restock=False,day=self.day)
        d=self.report();v=d["summary"]
        self.assertEqual((v["revenue"],v["cogs"],v["cashflow"],v["current_receivables_rub"]),("200.00","60.00","200.00","0.00"))
        self.assertEqual((d["products"][0]["quantity"],d["products"][0]["value_rub"],d["materials"][0]["quantity"]),(1,"20.00",60))
        self.prepare("return",{"sale":s["id"],"quantity":3,"refund":"0","restock":False,"day":self.day},expect=409)
        self.prepare("payment",{"sale":s["id"],"amount":"1","day":self.day},expect=409)
    def test_unpaid_sale_and_partial_payment(self):
        ids=self.seed()
        s=self.op("sale",product=ids["product_id"],quantity=2,unit_price="100",paid_amount="0",auto_produce=True,day=self.day)
        self.assertEqual(self.report()["summary"]["cashflow"],"0.00")
        self.op("payment",sale=s["id"],amount="70",day=self.day)
        d=self.report()["summary"]
        self.assertEqual((d["revenue"],d["cashflow"],d["current_receivables_rub"]),("200.00","70.00","130.00"))
    def test_no_double_consumption_and_stock_bound(self):
        ids=self.seed(qty=20,value="40")
        self.op("manufacture",product=ids["product_id"],quantity=2,day=self.day)
        self.op("sale",product=ids["product_id"],quantity=1,unit_price="100",paid_amount="100",day=self.day)
        self.assertEqual(self.report()["materials"][0]["quantity"],0)
        self.prepare("sale",{"product":ids["product_id"],"quantity":2,"unit_price":"100","auto_produce":True},expect=409)
        self.assertEqual(self.report()["products"][0]["quantity"],1)
    def test_atomic_preview_and_stale_revision(self):
        ids=self.seed();m=ids["material_id"]
        draft=self.prepare("purchase",{"material":m,"quantity":1,"purchase_unit":"pack","total":"800"})
        self.assertEqual(self.report()["materials"][0]["quantity"],100)
        self.op("expense",category="Реклама",total="1")
        self.commit(draft,expect=409)
        self.assertEqual(self.report()["materials"][0]["quantity"],100)
        self.assertEqual(self.report()["summary"]["purchases"],"0.00")
    def test_idempotent_commit_and_conflict(self):
        ids=self.seed()
        draft=self.prepare("purchase",{"material":ids["material_id"],"quantity":1,"purchase_unit":"pack","total":"800"})
        a=self.commit(draft,"repeat");b=self.commit(draft,"repeat")
        self.assertEqual(a,b);self.assertEqual(self.report()["materials"][0]["quantity"],500)
        changed={**draft,"arguments":{**draft["arguments"],"total":"801"}}
        self.commit(changed,"repeat",expect=409)
        self.assertEqual(self.report()["summary"]["purchases"],"800.00")
    def test_reversal_preserves_audit_and_dependency(self):
        ids=self.seed();m=ids["material_id"]
        w=self.op("writeoff",material=m,quantity=5)
        self.assertEqual(self.report()["summary"]["net_profit"],"-10.00")
        self.assertEqual(self.report()["summary"]["cashflow"],"0.00")
        self.op("reverse",event=w["id"],reason="Ошибочный ввод")
        d=self.report();self.assertEqual((d["materials"][0]["quantity"],d["summary"]["net_profit"]),(100,"0.00"))
        self.assertTrue(next(x for x in d["events"] if x["id"]==w["id"])["reversed"])
        self.prepare("reverse",{"event":w["id"],"reason":"Повтор"},expect=409)
        buy=self.op("purchase",material=m,quantity=1,purchase_unit="pack",total="800")
        self.op("manufacture",product=ids["product_id"],quantity=1)
        self.prepare("reverse",{"event":buy["id"],"reason":"Поздняя правка"},expect=409)
    def test_multi_material_failure_is_atomic(self):
        ids=self.seed();self.recipe(material="Нить",product="Браслет",pack=100,usage=2,price="100")
        before=self.report()
        self.prepare("manufacture",{"product":ids["product_id"],"quantity":1},expect=409)
        after=self.report()
        self.assertEqual(before["materials"],after["materials"])
        self.assertEqual(before["event_count"],after["event_count"])
    def test_exact_kopeck_conservation(self):
        ids=self.recipe(pack=3,usage=1,price="0.01")
        self.op("purchase",material=ids["material_id"],quantity=1,purchase_unit="pack",total="0.01")
        self.op("manufacture",product=ids["product_id"],quantity=3)
        for _ in range(3):self.op("sale",product=ids["product_id"],quantity=1,unit_price="1",paid_amount="1")
        d=self.report();self.assertEqual(d["summary"]["cogs"],"0.01");self.assertEqual(d["summary"]["inventory_rub"],"0.00")
    def test_date_period_and_no_backdated_stock(self):
        ids=self.seed()
        self.prepare("purchase",{"material":ids["material_id"],"quantity":1,"purchase_unit":"base","total":"1","day":self.yesterday},expect=409)
        self.op("expense",category="Аренда",total="15",day=self.yesterday)
        self.op("expense",category="Реклама",total="20",day=self.day)
        old=self.report(start=self.yesterday,end=self.yesterday);now=self.report(start=self.day,end=self.day)
        self.assertEqual((old["summary"]["expenses"],now["summary"]["expenses"]),("15.00","20.00"))
        self.assertEqual(self.report(event_group="expenses")["event_count"],2)
        self.assertEqual(self.report(event_group="stock")["event_count"],1)
    def test_other_workspace_cannot_read_or_commit(self):
        ids=self.seed();m=ids["material_id"]
        self.assertEqual(self.report(self.other)["materials"],[])
        self.prepare("purchase",{"material":m,"quantity":1,"purchase_unit":"base","total":"1"},self.other,expect=400)
        draft=self.prepare("expense",{"category":"Прочее","total":"1"})
        self.commit(draft,h=self.other,expect=409)
        self.assertEqual(self.report(self.other)["summary"]["expenses"],"0.00")
        self.assertEqual(self.client.get("/api/accounting").status_code,401)
    def test_catalog_and_units(self):
        material=self.op("material",name="Воск",unit="г",pack=1000,pack_price="500",category="Свечи")
        product=self.op("product",name="Свеча",category="Свечи",sale_price="100",minutes=30)
        ids=self.recipe(material="Воск",product="Свеча",pack=1000,usage=150,price="500",unit="г")
        self.assertEqual(material["id"],ids["material_id"]);self.assertEqual(product["id"],ids["product_id"])
        self.op("purchase",material=material["id"],quantity=1,purchase_unit="pack",total="500")
        self.op("manufacture",product=product["id"],quantity=2,extra="25")
        d=self.report();self.assertEqual(d["materials"][0]["unit"],"г")
        self.assertEqual(d["products"][0]["value_rub"],"175.00")
        self.assertEqual(d["summary"]["cashflow"],"-525.00")
        self.prepare("material",{"entity_id":material["id"],"name":"Воск","unit":"шт","pack":1000},expect=409)
    def test_every_matrix_entry_has_zero_model_route(self):
        c=self.call("/api/chats",{}).json()["chatId"]
        for item in matrix.ITEMS:
            if not item["aliases"]:continue
            r=self.call("/api/chats/"+c+"/turns",{"requestId":uuid4().hex,"text":item["aliases"][0]})
            self.assertEqual(r.status_code,200,(item["id"],r.text))
            self.assertEqual(r.json()["route"],"local")
            self.assertEqual(r.json()["matrixId"],item["id"])
        self.assertEqual(self.client.get("/api/wallet/balance",headers=self.h).json()["available"],"10")
        self.assertFalse((self.tmp/"usage.jsonl").exists())
    def test_matrix_draft_does_not_write_and_reads_report(self):
        self.seed();c=self.call("/api/chats",{}).json()["chatId"]
        r=self.call("/api/chats/"+c+"/turns",{"requestId":"natural","text":"закупка Бусины 2 упаковки за 1600"})
        self.assertEqual(r.status_code,200,r.text);a=r.json()["accountingDraft"]
        self.assertEqual(a["arguments"]["quantity"],2);self.assertEqual(a["operation"],"purchase")
        self.assertEqual(self.report()["materials"][0]["quantity"],100)
        self.commit(self.prepare(a["operation"],a["arguments"]))
        self.assertEqual(self.report()["materials"][0]["quantity"],900)
        r=self.call("/api/chats/"+c+"/turns",{"requestId":"report","text":"покажи прибыль за этот месяц"})
        self.assertEqual(r.json()["ui"]["highlight"],"net_profit")
        self.assertIn("0.00",r.json()["text"])
        self.assertFalse((self.tmp/"usage.jsonl").exists())
    def test_exports(self):
        self.op("expense",category="Прочее",total="12.34",note="=1+1")
        r=self.client.get("/api/accounting/export/csv",headers=self.h);self.assertEqual(r.status_code,200)
        self.assertIn("12.34",r.text);self.assertIn("'=1+1",r.text)
        r=self.client.get("/api/accounting/export/xlsx",headers=self.h);self.assertEqual(r.status_code,200)
        wb=load_workbook(io.BytesIO(r.content));self.assertEqual(wb.sheetnames,["Журнал","Сырьё","Готовые изделия","Рецептуры","Партии","Продажи","По месяцам"])
        self.assertEqual(wb["Журнал"]["E2"].data_type,"s")
        self.assertEqual(self.client.get("/api/accounting/export/xlsx").status_code,401)
    def test_invalid_values_no_mutation(self):
        ids=self.seed()
        for a in ({"quantity":0,"total":"10"},{"quantity":True,"total":"10"},{"quantity":1,"total":"-1"},{"quantity":1,"total":"1.001"}):
            self.prepare("purchase",{"material":ids["material_id"],"purchase_unit":"base",**a},expect=400)
        self.assertEqual(self.report()["summary"]["purchases"],"0.00")

    def test_specific_material_reports_and_rename(self):
        ids=self.recipe(usage=40);m=ids["material_id"]
        self.op("purchase",material=m,quantity=2,purchase_unit="pack",total="1600")
        self.op("sale",product=ids["product_id"],quantity=10,unit_price="100",auto_produce=True)
        c=self.call("/api/chats",{}).json()["chatId"]
        for text,mid,needle in (("сколько бусин осталось","A-R13","400"),("сколько упаковок бусин ушло за месяц","A-R14","1.000"),("сколько бусин нужно купить","A-R15","упаковок")):
            r=self.call("/api/chats/"+c+"/turns",{"requestId":uuid4().hex,"text":text})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["matrixId"],mid);self.assertIn(needle,r.json()["text"])
        self.prepare("material",{"name":"Бусины","unit":"шт","pack":400},expect=409)
        self.op("material",entity_id=m,name="Бусины белые",unit="шт",pack=400,pack_price="800",category="Фурнитура")
        d=self.report();self.assertEqual(len(d["materials"]),1);self.assertEqual(d["materials"][0]["name"],"Бусины белые");self.assertEqual(d["materials"][0]["quantity"],400)
