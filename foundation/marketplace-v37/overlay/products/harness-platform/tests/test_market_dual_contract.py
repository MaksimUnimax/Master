"""DUAL contract evidence on isolated stores; these are not live API checks."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

from starlette.testclient import TestClient
from platform_core.chat_api import create_app
from platform_core.identity import IdentityStore
from platform_core import market_quantity as quantity
from platform_core import podmasterye_market_operations as operations
from platform_core import podmasterye_workshops as workshops
from tests.test_podmasterye_market_analytics import order, proof, ASOF, START

ORIGIN="https://podmaster.example"
PASSWORD="fixture-market-dual-password"
API="/api/integrations/marketplaces"

class MarketDual(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db=self.root/"stage.sqlite3"
        from platform_core import podmasterye_market_analytics as analytics, podmasterye_book as book
        report_clock=analytics._report_clock(book.today())
        self.enterContext(patch.object(analytics,"_report_clock",return_value=report_clock))
        self.enterContext(patch.dict(os.environ,{"HARNESS_OFFLINE_MODEL":"1","PODMASTERYE_MARKET_WORKER":"0","HARNESS_USAGE_JOURNAL":str(self.root/"usage.jsonl")}))
        with IdentityStore(self.db) as identity:
            for login in ("owner","other"):identity.create_account(login,PASSWORD)
        self.app=create_app(self.db,self.root/"chats")
        self.client=self.enterContext(TestClient(self.app,base_url=ORIGIN))
        self.tokens={name:self.app.state.identity.login(name,PASSWORD) for name in ("owner","other")}
        self.chats={name:self.client.post("/api/chats",headers=self.headers(name),json={}).json()["chatId"] for name in self.tokens}
        self.scopes={name:self.app.state.identity.resolve_chat(token,self.chats[name]) for name,token in self.tokens.items()}
        with self.app.state.identity._write() as db:
            self.workshops={name:workshops.chat_workspace(db,scope) for name,scope in self.scopes.items()}
            # An isolated zero-credit fixture proves local operations do not
            # depend on a model reserve. No production records are touched.
            db.execute("DELETE FROM coin_grants")
        self.http=self.enterContext(patch.object(self.app.state.http,"request",new_callable=AsyncMock,side_effect=AssertionError("Local operation attempted provider HTTP")))

    def headers(self,name="owner"):
        return {"Authorization":"Bearer "+self.tokens[name]}

    def call(self,operation,args=None,rid="operation",name="owner",channel="ui"):
        return self.client.post(API+"/operations",headers=self.headers(name),json={"operation":operation,"arguments":args or {},"requestId":rid,"channel":channel})

    def turn(self,text,rid="turn",name="owner"):
        return self.client.post("/api/chats/"+self.chats[name]+"/turns",headers=self.headers(name),json={"requestId":rid,"text":text})

    def connection(self):
        body={"action":"create","requestId":"connection","provider":"ozon","name":"Fixture Ozon","fields":{"client_id":"12345","api_key":"secret-fixture-never-model"}}
        response=self.client.post(API+"/connection",headers=self.headers(),json=body)
        self.assertEqual(response.status_code,200,response.text)
        first=response.json();again=self.client.post(API+"/connection",headers=self.headers(),json=body)
        self.assertEqual(again.json(),first)
        return first

    def verified(self):
        connection=self.connection();w=self.workshops["owner"]
        with self.app.state.identity._write() as db:
            sid=quantity.bind_verified(db,w,connection["id"],connection["version"],"ozon","fixture-seller",{"seller_id":"fixture-seller"})
        return connection,sid

    def fixture_catalog(self,count=1):
        connection,sid=self.verified();w=self.workshops["owner"]
        seed=self.client.post("/api/production/recipe",headers=self.headers(),json={"requestId":"recipe","recipe":{"material":"Бусины","product":"Браслет","pack_quantity":100,"usage_quantity":9,"pack_price":"100"}})
        self.assertEqual(seed.status_code,200,seed.text);product=seed.json()["product_id"]
        with self.app.state.identity._write() as db:
            with quantity.local(db,w,"ozon",True) as local:
                for i in range(count):
                    sku=str(i+100)
                    local.execute("INSERT INTO quantity_catalog VALUES(?,?,?,?,?)",(sid,sku,json.dumps({"sku":sku,"name":"Fixture "+sku,"category_id":"c"}),time.time(),"fixture-catalog"))
                    data=order(str(i),store=sid,sku=sku,product=None,units=100,losses=20,days=60)
                    local.execute("INSERT INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?)",(sid,"OZ-03",data["natural_key"],data["ordered_at"],data["ordered_at"],time.time(),json.dumps(data),"fixture-orders",1))
                for c in proof(store=sid):
                    local.execute("INSERT INTO quantity_coverage VALUES(?,?,?,?,?,?,?)",(sid,c["source_id"],c["from"],c["to"],json.dumps(c),time.time(),"fixture-proof"))
        return connection,sid,product

    def assert_zero_model(self):
        self.assertEqual(self.http.await_count,0)
        self.assertFalse((self.root/"usage.jsonl").exists())
        with self.app.state.identity._lock:
            db=self.app.state.identity._db
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],0)
        wallet=self.client.get("/api/wallet",headers=self.headers()).json()
        self.assertEqual(wallet["available"],"0")

    def test_registry_is_typed_and_has_both_surfaces(self):
        self.assertTrue(operations.validate_registry())
        expected={"market_sales","market_loss_rates","market_sync_status","market_sync_request","market_sync_control","market_catalog","market_mapping","market_connection","market_export"}
        self.assertEqual(set(operations.REGISTRY),expected)
        for item in operations.declarations():
            self.assertEqual(item["kind"],"user_operation")
            self.assertTrue(all(item["bindings"][k] for k in ("ui","local_matrix","mcp")))
            self.assertFalse(item["input_schema"]["additionalProperties"])
            self.assertTrue(item["output_schema"]["required"])
            self.assertTrue(item["output_schema"]["properties"])
            self.assertTrue(item["progress_policy"]["local_operation"])
        raw=json.dumps(operations.declarations())
        for internal in ("api-seller.ozon.ru","/v1/report","Authorization","database_path","api_key","encrypted"):
            self.assertNotIn(internal,raw)
        bad=self.call("market_sync_request",{"source":"ozon","url":"https://untrusted.example"})
        self.assertEqual(bad.status_code,400)
        self.assertEqual(self.call("market_sales",{"from":"2026-13-01","to":"2026-13-30"},rid="invalid-date").status_code,400)
        self.assert_zero_model()

    def test_malformed_local_result_is_not_success_and_queue_write_rolls_back(self):
        from platform_core import podmasterye_market_analytics as analytics
        broken={"status":"ready","rows":None,"debug":"private-malformed-response-fixture"}
        with patch.object(analytics,"sales",return_value=broken):
            response=self.call("market_sales",{"from":"2026-09-01","to":"2026-09-02"},"bad-local-report")
        self.assertEqual(response.status_code,502,response.text)
        self.assertNotIn("private-malformed-response-fixture",response.text)
        self.assertIn("не соответствует контракту",response.text)

        self.verified()
        with self.app.state.identity._lock:
            before=[self.app.state.identity._db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                    for table in ("market_data_tasks","market_data_groups")]
        original=quantity.market_sync_request
        def malformed(*args,**kwargs):
            result=original(*args,**kwargs);result.pop("progress");return result
        with patch.object(quantity,"market_sync_request",side_effect=malformed):
            response=self.call("market_sync_request",{"source":"ozon","from":"2026-09-01","to":"2026-09-02"},"bad-queue-result")
        self.assertEqual(response.status_code,502,response.text)
        with self.app.state.identity._lock:
            after=[self.app.state.identity._db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                   for table in ("market_data_tasks","market_data_groups")]
        self.assertEqual(after,before)
        self.assert_zero_model()

    def test_secure_inline_card_has_no_key_and_local_zero_balance(self):
        self.connection()
        card=self.turn("подключить wildberries","connect-card")
        self.assertEqual(card.status_code,200,card.text)
        self.assertEqual(card.json()["route"],"local")
        self.assertEqual(card.json()["marketCard"]["provider"],"wb")
        self.assertEqual(card.json().get("ui"),{})
        listing=self.turn("подключения маркетплейсов","list-card")
        self.assertEqual(listing.status_code,200,listing.text)
        history=self.client.get("/api/chats/"+self.chats["owner"]+"/messages",headers=self.headers()).text
        self.assertNotIn("secret-fixture-never-model",history)
        self.assertNotIn("secret-fixture-never-model",listing.text)
        self.assertEqual(self.call("market_connection",name="other").json()["marketCard"]["connections"],[])
        self.assert_zero_model()

    def test_ui_chat_queue_handoff_deduplicates_and_preserves_retry(self):
        self.verified()
        args={"source":"ozon","from":"2026-09-01","to":"2026-09-02"}
        ui=self.call("market_sync_request",args,"ui-start")
        self.assertEqual(ui.status_code,200,ui.text)
        chat=self.turn("обнови историю ozon с 2026-09-01 по 2026-09-02","chat-start")
        self.assertEqual(chat.status_code,200,chat.text)
        self.assertEqual(chat.json()["route"],"local")
        self.assertEqual(ui.json()["job_ids"],chat.json()["marketResult"]["result"]["job_ids"])
        self.assertEqual(ui.json()["job_id"],chat.json()["marketResult"]["result"]["job_id"])
        jid=ui.json()["job_ids"][0];due=time.time()+900
        with self.app.state.identity._write() as db:
            db.execute("UPDATE market_data_tasks SET state='deferred',due=?,checkpoint=? WHERE id=?",(due,json.dumps({"report_id":"fixture-existing-report","stage":"poll","page":3}),jid))
        stopped=self.turn("останови сбор "+jid,"chat-stop")
        self.assertEqual(stopped.status_code,200,stopped.text)
        self.assertEqual(stopped.json()["marketResult"]["result"]["state"],"stopped")
        resumed=self.call("market_sync_control",{"job_id":jid,"action":"resume"},"ui-resume")
        self.assertEqual(resumed.status_code,200,resumed.text)
        self.assertEqual(resumed.json()["next_retry_at"],due)
        self.assertEqual(resumed.json()["report_id"],"fixture-existing-report")
        replay=self.call("market_sync_control",{"job_id":jid,"action":"resume"},"ui-resume",channel="chat")
        self.assertEqual(replay.json(),resumed.json())
        self.assertEqual(self.call("market_sync_status",{"job_id":jid},"foreign",name="other").status_code,404)
        # A user-visible collection is one durable group, including all pages
        # and provider templates. A channel handoff controls the entire group.
        gid=ui.json()["job_id"]
        stopped=self.turn("останови сбор "+gid,"chat-stop-group")
        self.assertEqual(stopped.status_code,200,stopped.text)
        group=stopped.json()["marketResult"]["result"]
        self.assertEqual(group["state"],"stopped")
        self.assertTrue(group["jobs"])
        self.assertTrue(all(job["state"]=="stopped" for job in group["jobs"]))
        resumed_group=self.call("market_sync_control",{"job_id":gid,"action":"resume"},"ui-resume-group")
        self.assertEqual(resumed_group.status_code,200,resumed_group.text)
        self.assertEqual(resumed_group.json()["job_id"],gid)
        retry_job=next(job for job in resumed_group.json()["jobs"] if job["id"]==jid)
        self.assertEqual((retry_job["next_retry_at"],retry_job["report_id"]),(due,"fixture-existing-report"))
        self.assertEqual(self.call("market_sync_control",{"job_id":gid,"action":"cancel"},"foreign-group",name="other").status_code,404)
        with self.app.state.identity._write() as db:
            db.execute("UPDATE market_data_tasks SET state='uncertain',inflight=? WHERE id=?",(json.dumps({"generate":True}),jid))
        blocked=self.call("market_sync_control",{"job_id":gid,"action":"resume"},"blocked-resume")
        self.assertEqual(blocked.status_code,200,blocked.text)
        compact=operations.model_projection("market_sync_control",blocked.json())
        self.assertEqual(compact["blocked_count"],1)
        self.assertIn("повторное создание запрещено",compact["problems"][0])
        self.assertNotIn("jobs",compact)
        self.assertNotIn("blocked_jobs",compact)
        self.assertIn("Действие недоступно",compact["text"])
        self.assert_zero_model()

    def test_quantities_match_ui_chat_and_export_full_pages(self):
        _,sid,_=self.fixture_catalog(105)
        args={"source":"ozon","from":"2026-09-29","to":"2026-09-29","group_by":"product","limit":30}
        ui=self.call("market_sales",args,"sales-ui")
        self.assertEqual(ui.status_code,200,ui.text)
        chat=self.turn("продажи ozon с 2026-09-29 по 2026-09-29","sales-chat")
        self.assertEqual(chat.status_code,200,chat.text)
        result=chat.json()["marketResult"]["result"]
        self.assertEqual(ui.json(),result)
        self.assertEqual(result["total"],105)
        self.assertEqual(result["totals"]["net"],8400)
        self.assertEqual(len(result["rows"]),30)
        exported=self.client.post(API+"/export",headers=self.headers(),json={"operation":"market_sales","arguments":args})
        self.assertEqual(exported.status_code,200,exported.text[:200])
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            full=json.loads(archive.read("report.json"))
            self.assertEqual(len(full["rows"]),105)
            self.assertEqual(full["totals"],result["totals"])
            self.assertEqual(full["source"],"ozon")
            self.assertIn("SHA256SUMS.txt",archive.namelist())
            self.assertNotIn(b"secret-fixture-never-model",b"".join(archive.read(n) for n in archive.namelist()))
        self.assert_zero_model()

    def test_catalog_search_export_and_ambiguous_sku_after_public_page(self):
        connection,sid,product=self.fixture_catalog(105)
        filtered=self.call("market_catalog",{"source":"ozon","search":"Fixture 204"},"search")
        self.assertEqual(filtered.status_code,200,filtered.text)
        self.assertEqual((filtered.json()["total"],filtered.json()["rows"][0]["sku"]),(1,"204"))
        exported=self.client.post(API+"/export",headers=self.headers(),json={"operation":"market_catalog","arguments":{"source":"ozon","limit":30}})
        self.assertEqual(exported.status_code,200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            full=json.loads(archive.read("report.json"))
            self.assertEqual((full["total"],len(full["rows"])),(105,105))
            self.assertFalse(full["has_more"])
        # The same SKU in a second store follows a full first store page.
        # Never silently pick whichever store the first page happened to show.
        other_connection=self.client.post(API+"/connection",headers=self.headers(),json={"action":"create","requestId":"second-connection","provider":"ozon","name":"Second fixture Ozon","fields":{"client_id":"54321","api_key":"second-fixture-key"}})
        self.assertEqual(other_connection.status_code,200,other_connection.text)
        with self.app.state.identity._write() as db:
            other=quantity.bind_verified(db,self.workshops["owner"],other_connection.json()["id"],other_connection.json()["version"],"ozon","second-fixture-seller",{"seller_id":"second-fixture-seller"})
            with quantity.local(db,self.workshops["owner"],"ozon",True) as local:
                local.execute("INSERT INTO quantity_catalog VALUES(?,?,?,?,?)",(other,"100",json.dumps({"sku":"100","name":"Second store"}),time.time(),"fixture-second-catalog"))
        broad=self.call("market_mapping",{"source":"ozon","sku":"100","product":product},"ambiguous")
        self.assertEqual(broad.status_code,400,broad.text)
        exact=self.call("market_mapping",{"source":sid,"sku":"100","product":product},"exact-store")
        self.assertEqual(exact.status_code,200,exact.text)
        self.assertEqual(exact.json()["marketDraft"]["arguments"]["source"],sid)
        self.assert_zero_model()

    def test_accounting_export_contains_events_beyond_first_page(self):
        from platform_core import podmasterye_book as book
        with self.app.state.identity._write() as db:
            w=self.workshops["owner"]
            for i in range(103):
                args={"category":"Прочее","total":"1","note":"export row "+str(i)}
                book.execute(db,w,"export-expense-"+str(i),"expense",args)
            page=book.report(db,w,view="journal")
            self.assertEqual((len(page["events"]),page["event_count"]),(100,103))
        result=self.client.post(API+"/export",headers=self.headers(),json={"operation":"accounting_report","arguments":{"view":"journal","limit":30}})
        self.assertEqual(result.status_code,200,result.text[:150])
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            full=json.loads(archive.read("report.json"))
            self.assertEqual((len(full["events"]),full["event_count"]),(103,103))
            self.assertEqual(len({event["id"] for event in full["events"]}),103)
        self.assert_zero_model()

    def test_mapping_confirmation_revision_replay_and_owner(self):
        _,sid,product=self.fixture_catalog()
        args={"source":sid,"sku":"100","product":product}
        prepared=self.call("market_mapping",args,"mapping-prepare").json()["marketDraft"]
        payload={"arguments":prepared["arguments"],"revision":prepared["revision"],"requestId":"mapping-confirm"}
        foreign=self.client.post(API+"/mapping-confirm",headers=self.headers("other"),json=payload)
        self.assertEqual(foreign.status_code,404)
        before=self.call("market_catalog",{"source":sid},"catalog-before").json()
        self.assertIsNone(before["rows"][0]["product_id"])
        saved=self.client.post(API+"/mapping-confirm",headers=self.headers(),json=payload)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.client.post(API+"/mapping-confirm",headers=self.headers(),json=payload).json(),saved.json())
        stale=self.call("market_mapping",{"source":sid,"sku":"100","product":None},"unmap-prepare").json()["marketDraft"]
        with self.app.state.identity._write() as db:
            quantity.map_product(db,self.workshops["owner"],sid,"100",None)
            quantity.map_product(db,self.workshops["owner"],sid,"100",product)
        conflict=self.client.post(API+"/mapping-confirm",headers=self.headers(),json={"arguments":stale["arguments"],"revision":stale["revision"],"requestId":"stale-confirm"})
        self.assertEqual(conflict.status_code,409,conflict.text)
        self.assert_zero_model()

    def test_exports_preserve_unknown_and_escape_spreadsheet_injection(self):
        value={"status":"partial","rows":[{"sku":"=HYPERLINK(\"https://invalid\")","net":None}],"total":1}
        with zipfile.ZipFile(io.BytesIO(operations.export_archive(value))) as archive:
            self.assertEqual(json.loads(archive.read("report.json"))["rows"][0]["net"],None)
            csv=archive.read("rows.csv").decode("utf-8-sig")
            self.assertIn("'=HYPERLINK",csv)
            self.assertIn("не подтверждено",csv)

