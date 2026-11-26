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


    def workshop(self,action,args,h=None,rid=None):
        return self.call("/api/workshops/change",{"requestId":rid or uuid4().hex,"action":action,"arguments":args},h)

    def test_multiple_workshops_and_demo_isolation(self):
        self.seed()
        root=self.client.get("/api/workshops",headers=self.h).json()["default"]
        r=self.workshop("create",{"name":"Вторая","hourly_rate":"450"},rid="new-workshop")
        self.assertEqual(r.status_code,200,r.text);w=r.json()["id"]
        self.assertEqual(self.workshop("create",{"name":"Вторая","hourly_rate":"450"},rid="new-workshop").json()["id"],w)
        self.assertEqual(self.report(workshop=w)["materials"],[])
        self.assertEqual(len(self.report(workshop=root)["materials"]),1)
        self.assertEqual(self.client.get("/api/accounting",headers=self.other,params={"workshop":w}).status_code,400)
        ch=self.call("/api/workshops/chat",{"workshop":w}).json()["chatId"]
        turn=self.call("/api/chats/"+ch+"/turns",{"requestId":"w-recipe","text":"На изделие Свеча уходит 2 шт материала Нить, упаковка 10 шт стоит 100 рублей"})
        # Explicit recipe API is the deterministic fallback for an unmatched phrase.
        r=self.call("/api/production/recipe?workshop="+w,{"requestId":"w-manual","recipe":{"material":"Нить","product":"Свеча","pack_quantity":10,"usage_quantity":2,"pack_price":"100","unit":"шт"}})
        self.assertEqual(r.status_code,200,r.text)
        r=self.call("/api/chats/"+ch+"/turns",{"requestId":"w-report","text":"сколько нити осталось"})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["workshop"],w)
        self.assertEqual(self.report(workshop=w)["materials"][0]["name"],"Нить")
        self.assertEqual(self.report()["materials"][0]["name"],"Бусины")
        self.assertEqual(self.client.get("/api/wallet/balance",headers=self.h).json()["available"],"10")
        self.assertEqual(self.workshop("archive",{"id":w},self.other).status_code,400)
        self.assertEqual(self.workshop("archive",{"id":w}).status_code,200)
        self.assertEqual(self.client.get("/api/accounting",headers=self.h,params={"workshop":w}).status_code,409)
        self.assertEqual(self.workshop("restore",{"id":w}).status_code,200)
        self.assertEqual(len(self.report(workshop=w)["materials"]),1)
        demo=self.workshop("demo",{});self.assertEqual(demo.status_code,200,demo.text)
        data=self.report(workshop=demo.json()["id"])
        self.assertEqual(data["summary"]["revenue"],"1500.00")
        self.assertEqual(data["summary"]["net_profit"],"1000.00")
        self.assertEqual(self.report()["summary"]["revenue"],"0.00")

    def test_tasks_create_edit_complete_archive(self):
        t=self.op("task",name="Купить воск",description="Склад",due=self.day,priority="Высокая",task_category="Закупка")
        self.assertEqual(self.report()["tasks"][0]["status"],"active")
        self.op("task",task_id=t["id"],name="Купить воск и фитили",priority="Обычная",task_category="Закупка")
        self.assertEqual(self.report()["tasks"][0]["name"],"Купить воск и фитили")
        self.op("task_state",task_id=t["id"],task_status="done")
        self.assertEqual(self.report()["tasks"][0]["status"],"done")
        self.op("task_state",task_id=t["id"],task_status="archived")
        self.assertEqual(self.report()["tasks"][0]["status"],"archived")
        self.prepare("task_state",{"task_id":t["id"],"task_status":"done"},self.other,expect=400)

    def test_worker_payments_and_reversal(self):
        w=self.op("worker",name="Мастер",position="Сборка")
        p=self.op("worker_payment",worker_id=w["id"],total="250.25")
        d=self.report()
        self.assertEqual(d["workers"][0]["payments_rub"],"250.25")
        self.assertEqual(d["summary"]["net_profit"],"-250.25")
        self.assertEqual(d["summary"]["cashflow"],"-250.25")
        self.op("reverse",event=p["id"],reason="Ошибка")
        self.assertEqual(self.report()["workers"][0]["payments_rub"],"0.00")
        self.op("worker",worker_id=w["id"],name="Мастер",archived=True)
        self.prepare("worker_payment",{"worker_id":w["id"],"total":"1"},expect=409)

    def test_recipe_versions_archive_and_restore(self):
        ids=self.recipe();m=ids["material_id"];p=ids["product_id"]
        self.prepare("material_archive",{"material":m,"archived":True},expect=409)
        self.op("recipe_line",product=p,material=m,usage=12)
        with sqlite3.connect(self.db) as db:
            snapshots=[json.loads(x[0]) for x in db.execute("SELECT snapshot FROM pm_recipe_versions WHERE product=? ORDER BY seq",(p,))]
        self.assertEqual(snapshots[-1][0]["usage"],12)
        self.assertEqual(snapshots[-2][0]["usage"],10)
        self.op("product_archive",product=p,archived=True)
        self.op("material_archive",material=m,archived=True)
        self.prepare("product_archive",{"product":p,"archived":False},expect=409)
        self.op("material_archive",material=m,archived=False)
        self.op("product_archive",product=p,archived=False)
        self.op("recipe_line",product=p,material=m,usage=0)
        self.assertFalse(self.report()["products"][0]["recipe"])

    def test_unit_economics_labor_and_channel_tariff(self):
        m=self.op("material",name="Нить",unit="шт",pack=10,pack_price="100")
        p=self.op("product",name="Сумка",sale_price="1000",minutes=30)
        self.op("recipe_line",product=p["id"],material=m["id"],usage=5)
        root=self.client.get("/api/workshops",headers=self.h).json()["default"]
        r=self.workshop("update",{"id":root,"hourly_rate":"300"});self.assertEqual(r.status_code,200,r.text)
        self.op("channel_rates",channel="Витрина",commission="20",fixed_fee="100")
        self.op("opening",material=m["id"],quantity=100,total="1000")
        self.op("sale",product=p["id"],quantity=1,unit_price="1000",paid_amount="1000",channel="Витрина",auto_produce=True)
        d=self.report(target_profit="200")
        row=next(r for r in d["unit_economics"] if r["channel"]=="Витрина")
        self.assertEqual(row["quantity_90d"],1)
        self.assertEqual(row["planned_material_cost_rub"],"50.00")
        self.assertEqual(row["planned_full_cost_rub"],"200.00")
        self.assertEqual(row["recommended_price_rub"],"625.00")
        self.assertEqual(row["planned_profit_rub"],"500.00")

    def test_import_csv_and_xlsx_atomic_and_idempotent(self):
        import base64
        from openpyxl import Workbook
        csv="name;unit;pack;pack_price;initial_quantity;initial_total\nВоск;г;1000;500;1000;500\n"
        def b64(x):return base64.b64encode(x).decode()
        def preview(name,data):
            return self.call("/api/materials/import/preview",{"filename":name,"content":b64(data)})
        r=preview("materials.csv",csv.encode());self.assertEqual(r.status_code,200,r.text);d=r.json()
        self.assertEqual(self.report()["materials"],[])
        args={"requestId":"import-csv","rows":d["rows"],"revision":d["revision"]}
        r=self.call("/api/materials/import/commit",args);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.call("/api/materials/import/commit",args).json(),r.json())
        self.assertEqual(self.report()["materials"][0]["quantity"],1000)
        self.assertEqual(preview("same.csv",csv.encode()).status_code,409)
        wb=Workbook();ws=wb.active;ws.append(["name","unit","pack","pack_price"]);ws.append(["Нить","шт",100,"250"]);buf=io.BytesIO();wb.save(buf)
        r=preview("materials.xlsx",buf.getvalue());self.assertEqual(r.status_code,200,r.text);d=r.json()
        self.op("expense",category="Прочее",total="1")
        self.assertEqual(self.call("/api/materials/import/commit",{"requestId":"stale-import","rows":d["rows"],"revision":d["revision"]}).status_code,409)
        r=preview("materials.xlsx",buf.getvalue());d=r.json()
        self.assertEqual(self.call("/api/materials/import/commit",{"requestId":"fresh-import","rows":d["rows"],"revision":d["revision"]}).status_code,200)
        self.assertEqual(len(self.report()["materials"]),2)
        ws["D2"]="=1+1";buf=io.BytesIO();wb.save(buf)
        self.assertEqual(preview("bad.xlsx",buf.getvalue()).status_code,400)

    def test_public_calculator_and_save(self):
        a={"name":"Свеча","items":[{"name":"Воск","quantity":"0.25","unit":"кг","price":"500"}],"sale_price":"400","minutes":"30","hourly_rate":"200"}
        r=self.client.post("/api/calculator",json=a);self.assertEqual(r.status_code,200,r.text)
        d=r.json();self.assertEqual((d["materials_rub"],d["labor_rub"],d["profit_rub"]),("125.00","100.00","175.00"))
        args={"requestId":"calc-save","calculation":a}
        r=self.call("/api/calculator/save",args);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.call("/api/calculator/save",args).json(),r.json())
        d=self.report();self.assertEqual(d["products"][0]["estimated_material_cost_rub"],"125.00")
        self.assertEqual(d["materials"][0]["quantity"],0)

    def test_external_order_mapping_retry_returns_and_key_rotation(self):
        ids=self.seed(qty=100,value="200")
        def change(action,**args):return self.call("/api/integrations/change",{"action":action,"arguments":args})
        s=change("create",name="Магазин 1",auto_produce=True)
        self.assertEqual(s.status_code,200,s.text);src=s.json();h={"Authorization":"Bearer "+src["apiKey"]}
        p={"order_ref":"order-1","date":self.day,"shop_name":"Shop","items":[{"offer_id":"sku","name":"Браслет","qty":2,"price":"100"}]}
        r=self.call("/api/hook/order",p,h);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["status"],"pending_mapping")
        self.assertEqual(self.report()["summary"]["revenue"],"0.00")
        r=change("map",id=src["id"],offer="sku",product=ids["product_id"]);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.report()["summary"]["revenue"],"200.00")
        r=self.call("/api/hook/order",p,h);self.assertEqual(r.json()["status"],"posted")
        self.assertEqual(self.report()["summary"]["revenue"],"200.00")
        self.assertEqual(self.call("/api/hook/order",{**p,"shop_name":"changed"},h).status_code,409)
        event={"event_id":"ret-1","order_ref":"order-1","line":0,"kind":"return","date":self.day,"quantity":1,"refund":"100","restock":True}
        r=self.call("/api/hook/event",event,h);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.call("/api/hook/event",event,h).json(),r.json())
        self.assertEqual(self.report()["summary"]["revenue"],"100.00")
        self.assertEqual(self.report()["materials"][0]["quantity"],80)
        s2=change("create",name="Магазин 2",auto_produce=True).json();h2={"Authorization":"Bearer "+s2["apiKey"]}
        self.assertEqual(self.call("/api/hook/order",p,h2).json()["status"],"pending_mapping")
        self.assertEqual(change("map",id=s2["id"],offer="sku",product=ids["product_id"]).status_code,200)
        self.assertEqual(self.report()["summary"]["revenue"],"300.00")
        rotated=change("rotate",id=src["id"]).json()
        self.assertEqual(self.call("/api/hook/order",p,h).status_code,401)
        self.assertEqual(self.call("/api/hook/order",p,{"Authorization":"Bearer "+rotated["apiKey"]}).status_code,200)
        self.assertEqual(self.call("/api/integrations/change",{"action":"disable","arguments":{"id":src["id"]}},self.other).status_code,400)
        self.assertEqual(change("disable",id=src["id"]).status_code,200)
        self.assertEqual(self.call("/api/hook/order",p,{"Authorization":"Bearer "+rotated["apiKey"]}).status_code,401)
        self.assertEqual(self.client.get("/api/integration-docs").status_code,200)
