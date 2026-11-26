import os,sqlite3,subprocess,selectors,tempfile,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from cryptography.fernet import Fernet
from platform_core.chat_api import create_app
from platform_core.identity import IdentityStore
from platform_core.operation_grants import initialize_grants
from platform_core import coins
from tests.auth_fixture import email_opted_out

ORIGIN="https://podmaster.example"
P="fixture-password-123"
EXAMPLE="Добавь бусины пачками по 400 штук, на браслет уходит 40 штук, упаковка стоит 800 рублей"
class Foundation(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db=self.root/"test.sqlite3";self.journal=self.root/"usage.jsonl"
        self.env=self.enterContext(patch.dict(os.environ,{"HARNESS_RUB_PER_USD":"80","HARNESS_USAGE_JOURNAL":str(self.journal)}))
        with IdentityStore(self.db) as s:
            for name in ("buyer","other","admin","unpaid"):s.create_account(name,P)
            s.set_admin("admin",True);s.set_paid("unpaid",False)
        initialize_grants(self.db)
        self.gateway=subprocess.Popen(["node",str(Path(__file__).with_name("podmasterye_gateway.mjs")),str(self.db),str(self.journal)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        def stop():
            self.gateway.stdin.close()
            try:self.gateway.wait(timeout=5)
            except subprocess.TimeoutExpired:self.gateway.kill();self.gateway.wait()
            self.gateway.stdout.close()
        self.addCleanup(stop)
        with selectors.DefaultSelector() as ready:
            ready.register(self.gateway.stdout,selectors.EVENT_READ)
            self.assertTrue(ready.select(8),"gateway startup")
        url=self.gateway.stdout.readline().strip();self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.enterContext(patch.dict(os.environ,{"HARNESS_MODEL_GATEWAY_URL":url,"HARNESS_CHAT_MODEL":"deepseek-flash","HARNESS_OFFLINE_MODEL":"0"}))
        self.app=create_app(self.db,self.root/"chats")
        self.c=self.enterContext(TestClient(self.app,base_url=ORIGIN))
    def actor(self,name):
        token=self.app.state.identity.login(name,P);h={"Authorization":"Bearer "+token}
        chat=self.c.post("/api/chats",headers=h,json={}).json()["chatId"]
        return h,chat
    def turn(self,h,chat,rid,text):
        return self.c.post(f"/api/chats/{chat}/turns",headers=h,json={"requestId":rid,"text":text})
    def wallet(self,h):return self.c.get("/api/wallet",headers=h).json()
    def test_local_create_replay_and_isolation(self):
        h,c=self.actor("buyer");other,oc=self.actor("other")
        for _ in range(2):
            r=self.turn(h,c,"same",EXAMPLE);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["recipe"]["material_cost_rub"],"80.00");self.assertNotIn("modelCost",r.json())
        self.assertEqual(self.turn(h,c,"same","другой текст").status_code,409)
        self.assertEqual(self.turn(other,c,"foreign",EXAMPLE).status_code,404)
        self.assertEqual(self.c.get("/api/production",headers=other).json()["materials"],[])
        d=self.c.get("/api/production",headers=h).json();self.assertEqual((len(d["materials"]),len(d["products"])),(1,1))
        self.assertEqual(self.wallet(h)["available"],"10");self.assertFalse(self.journal.exists())
        self.assertEqual(len(self.c.get(f"/api/chats/{c}/messages",headers=h).json()),2)
    def test_manual_and_unknown_price(self):
        h,c=self.actor("buyer")
        a=dict(product="Колье",material="Бусины",pack_quantity=400,usage_quantity=40)
        body={"requestId":"ui-1","recipe":a}
        for _ in range(2):
            r=self.c.post("/api/production/recipe",headers=h,json=body);self.assertEqual(r.status_code,200);self.assertIsNone(r.json()["material_cost_rub"])
        self.assertEqual(self.c.post("/api/production/recipe",headers=h,json={"requestId":"ui-1","recipe":{**a,"pack_price":"800"}}).status_code,409)
        self.assertEqual(self.c.post("/api/production/recipe",headers=h,json={"requestId":"ui-2","recipe":{**a,"pack_price":"800"}}).json()["material_cost_rub"],"80.00")
        self.assertEqual(self.c.post("/api/production/recipe",headers=h,json={"requestId":"ui-3","recipe":{**a,"usage_quantity":0}}).status_code,400)
        self.assertFalse(self.journal.exists())
    def test_real_harness_mcp_draft_charge_and_replay(self):
        h,c=self.actor("buyer")
        for _ in range(2):
            r=self.turn(h,c,"draft1","Свободная формулировка: подготовьте расчёт.")
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["draft"]["material_cost_rub"],"80.00")
            self.assertNotIn("modelCost",r.json());self.assertNotIn("operationId",r.json())
        self.assertEqual(self.c.get("/api/production",headers=h).json()["products"],[])
        w=self.wallet(h);self.assertEqual(w["available"],"9.99856");self.assertEqual(w["reserved"],"0");self.assertEqual(len(w["charges"]),1);self.assertNotIn("meter",w["charges"][0])
        draft=r.json()["draft"];a={k:draft[k] for k in ("product","material","pack_quantity","usage_quantity","pack_price")}
        self.assertEqual(self.c.post("/api/production/recipe",headers=h,json={"requestId":"confirm","recipe":a}).status_code,200)
        self.assertEqual(self.c.get("/api/production",headers=h).json()["products"][0]["material_cost_rub"],"80.00")
        self.assertEqual(self.wallet(h)["available"],"9.99856")
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],2)
    def test_admin_costs_and_roles(self):
        h,c=self.actor("admin");u,uc=self.actor("unpaid")
        r=self.turn(h,c,"local","как считается себестоимость")
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["modelCost"]["rub"],"0")
        r=self.turn(h,c,"model","Ответьте свободным текстом.")
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["modelCost"]["rub"],"0.00072")
        self.assertEqual(self.turn(u,uc,"unpaid","Ответьте свободным текстом.").status_code,402)
        self.assertEqual(self.turn(u,uc,"free","как считается себестоимость").status_code,200)
        self.assertEqual(self.wallet(u)["available"],"10")
        self.assertEqual(self.c.get("/api/admin/accounts/admin/wallet",headers=u).status_code,403)
        self.assertEqual(self.c.get("/api/admin/coin-pricing",headers=u).status_code,403)
        self.assertEqual(self.c.get("/api/admin/accounts/admin/wallet",headers=h).status_code,200)
        self.app.state.identity.set_admin("admin",False)
        self.assertEqual(self.c.get(f"/api/chats/{c}/messages",headers=h).status_code,401)
        fresh,fc=self.actor("admin")
        hist=self.c.get(f"/api/chats/{c}/messages",headers=fresh).json()
        self.assertFalse(any("modelCost" in m or "modelUsage" in m or "operationId" in m for m in hist))
    def test_guest_and_disabled_live_payments(self):
        self.assertEqual(self.c.get("/").status_code,200)
        self.assertEqual(self.c.get("/api/production").status_code,401)
        self.assertEqual(self.c.get("/api/coins/quote?coins=100").json(),{"total":"120.00","enabled":False})
        g=self.c.post("/guest/session",headers={"origin":ORIGIN}).json()["chat"]
        r=self.c.post(f"/guest/chats/{g}/turns",headers={"origin":ORIGIN,"accept":"application/json"},data={"request_id":"g1","text":"Сколько стоит 100 монет"})
        self.assertEqual(r.status_code,200,r.text)
        hist=self.c.get(f"/guest/chats/{g}/events").json()["turns"];self.assertIn("120",hist[0]["answer"])
        self.assertEqual(self.c.get("/api/plugins").status_code,404)
    def test_email_registration(self):
        svc=self.app.state.account_access;sent=[];svc.mail=lambda address,code:sent.append((address,code))
        svc.keyfile=self.root/"auth.key";svc.keyfile.write_bytes(Fernet.generate_key())
        g=self.c.post("/guest/session",headers={"origin":ORIGIN}).json()["chat"]
        self.assertEqual(self.c.post(f"/guest/chats/{g}/turns",headers={"origin":ORIGIN,"accept":"application/json"},data={"text":"Сколько стоят 100 монет?","request_id":"guest-before-registration"}).status_code,200)
        r=self.c.post("/register",headers={"origin":ORIGIN,"accept":"application/json"},data={"login":"new-master","email":"new@example.test","password":P},follow_redirects=False)
        self.assertEqual(r.status_code,202,r.text);self.assertEqual(len(sent),1)
        r=self.c.post("/auth/verify",headers={"origin":ORIGIN,"accept":"application/json"},data={"value":sent[0][1]},follow_redirects=False)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.c.get("/api/wallet/balance").json()["available"],"10")
        self.assertIn("__Host-podmaster_session",self.c.cookies)
        self.assertEqual(self.c.get("/api/production").status_code,200)
        self.assertIn("guest-before-registration",self.c.get(f"/api/chats/{g}/messages").text)
        page=self.c.get("/app/")
        self.assertEqual(page.status_code,200)
        self.assertIn("Изделия и рецептуры",page.text)
        self.assertNotIn('data-page="admin"',page.text)
        self.assertEqual(self.c.post("/logout",headers={"origin":ORIGIN},follow_redirects=False).status_code,303)
        self.assertEqual(self.c.get("/api/production").status_code,401)
    def test_uncertain_provider_attempt_is_not_replayed(self):
        h,c=self.actor("buyer")
        for _ in range(2):
            r=self.turn(h,c,"unknown","uncertain fixture");self.assertEqual(r.status_code,409,r.text)
        self.assertGreater(Decimal(self.wallet(h)["reserved"]),0)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],1)

    def test_native_accounting_draft_and_report(self):
        h,c=self.actor("buyer")
        r=self.turn(h,c,"seed",EXAMPLE)
        self.assertEqual(r.status_code,200,r.text)
        r=self.turn(h,c,"purchase","Тест свободной закупки: оформите покупку материала.")
        self.assertEqual(r.status_code,200,r.text)
        draft=r.json()["accountingDraft"]
        self.assertEqual(draft["operation"],"purchase")
        self.assertEqual(draft["preview"]["value_rub"],"800.00")
        before=self.c.get("/api/accounting",headers=h).json()
        self.assertEqual(before["materials"][0]["quantity"],0)
        data={"requestId":"confirm-purchase","operation":draft["operation"],"arguments":draft["arguments"],"revision":draft["revision"]}
        a=self.c.post("/api/accounting/commit",headers=h,json=data)
        b=self.c.post("/api/accounting/commit",headers=h,json=data)
        self.assertEqual(a.status_code,200,a.text);self.assertEqual(a.json(),b.json())
        self.assertEqual(self.c.get("/api/accounting",headers=h).json()["materials"][0]["quantity"],400)
        self.assertEqual(self.wallet(h)["available"],"9.99856")
        r=self.turn(h,c,"report","Тест свободного отчёта: сверьте показатели.")
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.wallet(h)["available"],"9.99712")
        self.assertNotIn("modelCost",r.json())
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],4)

    def test_agent_partial_fill_context_and_separate_meter(self):
        h,c=self.actor("admin")
        self.assertEqual(self.turn(h,c,"seed",EXAMPLE).status_code,200)
        r=self.turn(h,c,"partial","Тест частичной закупки")
        self.assertEqual(r.status_code,200,r.text)
        draft=r.json()["accountingDraft"]
        self.assertIn("Общая сумма, ₽",draft["missing"])
        self.assertNotIn("revision",draft)
        ctx={"form":"book.purchase","arguments":draft["arguments"]}
        args={"requestId":"continuation","text":"Тест дополнения закупки","formContext":ctx}
        r=self.c.post(f"/api/chats/{c}/turns",headers=h,json=args)
        self.assertEqual(r.status_code,200,r.text)
        d=r.json()["accountingDraft"]
        self.assertEqual(d["arguments"]["quantity"],2)
        self.assertEqual(d["preview"]["value_rub"],"1600.00")
        self.assertEqual(self.c.get("/api/accounting",headers=h).json()["materials"][0]["quantity"],0)
        self.assertEqual(self.c.post(f"/api/chats/{c}/turns",headers=h,json=args).json(),r.json())
        invalid={**args,"formContext":{"form":"book.purchase","arguments":{"quantity":3}}}
        self.assertEqual(self.c.post(f"/api/chats/{c}/turns",headers=h,json=invalid).status_code,409)
        r=self.turn(h,c,"workshop","Тест заполнения мастерской")
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["formDraft"]["arguments"]["name"],"Новая мастерская")
        d=self.c.get("/api/admin/podmasterye/usage",headers=h)
        self.assertEqual(d.status_code,200,d.text)
        self.assertEqual(d.json()["periods"]["all"]["attempts"],6)
        self.assertEqual(d.json()["periods"]["all"]["input"],60)
        self.assertEqual(d.json()["periods"]["all"]["output"],30)
        self.assertEqual(d.json()["periods"]["all"]["rub"],"0.00432")
        u,uc=self.actor("buyer")
        self.assertEqual(self.c.get("/api/admin/podmasterye/usage",headers=u).status_code,403)
        self.assertEqual(self.c.post("/api/admin/provider-keys/openrouter",headers=h,json={"key":"local-fixture-only"}).status_code,400)
        self.assertEqual(set(self.c.get("/api/admin/provider-keys",headers=h).json()),{"deepseek"})
        self.assertEqual(self.c.get("/api/integrations/telegram",headers=h).json()["linked"],False)
        self.assertEqual(self.c.post("/api/integrations/telegram",headers=h,json={"action":"test"}).status_code,409)

    def test_agent_rejects_non_business_and_foreign_fields(self):
        h,c=self.actor("buyer");other,oc=self.actor("other")
        self.assertEqual(self.turn(other,oc,"seed",EXAMPLE).status_code,200)
        material=self.c.get("/api/production",headers=other).json()["materials"][0]["id"]
        for context in [
            {"form":"login","arguments":{"password":"fixture"}},
            {"form":"book.purchase","arguments":{"material":material}},
            {"form":"recipe","arguments":{"secret":"fixture"}},
            {"form":"book.purchase","arguments":{"quantity":-1}},
        ]:
            r=self.c.post(f"/api/chats/{c}/turns",headers=h,json={"requestId":"invalid","text":"заполни","formContext":context})
            self.assertEqual(r.status_code,400,r.text)
        self.assertFalse(self.journal.exists())
