"""Integration contract tests without external services or real credentials."""
import hashlib,hmac,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from urllib.parse import parse_qs,urlsplit
import httpx
from starlette.testclient import TestClient
from platform_core.chat_api import create_app
from platform_core.identity import IdentityStore
from platform_core import telegram_api
from tests.fixtures.market_dual import finish_fixture_job

ORIGIN="https://podmaster.example"
P="fixture-password-123"
MARKET="/api/integrations/marketplaces"
TG="/api/integrations/telegram"
CONFIG="/api/admin/podmasterye/telegram-config"

class Integrations(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db=self.root/"stage.sqlite3";self.path=self.root/"telegram.json"
        self.enterContext(patch.dict(os.environ,{"HARNESS_TELEGRAM_CONFIG_FILE":str(self.path),"HARNESS_OFFLINE_MODEL":"1","PODMASTERYE_MARKET_WORKER":"0","HARNESS_USAGE_JOURNAL":str(self.root/"usage.jsonl")}))
        with IdentityStore(self.db) as s:
            for n in ("admin","owner","other"):s.create_account(n,P)
            s.set_admin("admin",True)
        self.app=create_app(self.db,self.root/"chats")
        self.c=self.enterContext(TestClient(self.app,base_url=ORIGIN))
        self.tokens={n:self.app.state.identity.login(n,P) for n in ("admin","owner","other")}
    def h(self,n="owner"):return {"Authorization":"Bearer "+self.tokens[n]}
    def login(self,n="owner"):
        self.c.cookies.set("__Host-podmaster_session",self.tokens[n])
        return {"Origin":ORIGIN}
    def test_market_credentials_scope_and_read_only_checks(self):
        oz={"client_id":"12345","api_key":"fixture-seller-key","performance_id":"5678","performance_secret":"fixture-performance-secret"}
        r=self.c.post(MARKET,headers=self.h(),json={"provider":"ozon","name":"Магазин","fields":oz})
        self.assertEqual(r.status_code,200,r.text);a=r.json();cid=a["id"];u=MARKET+"/"+cid
        self.assertEqual(a["status"],"saved");self.assertEqual(set(a["configuredFields"]),set(oz))
        self.assertNotIn(oz["api_key"],r.text)
        self.assertEqual(self.c.get(MARKET,headers=self.h("other")).json()["connections"],[])
        self.assertEqual(self.c.post(u+"/check",headers=self.h("other"),json={}).status_code,404)
        self.assertEqual(self.c.post(u+"/keys",headers=self.h("other"),json={"version":1,"fields":oz}).status_code,404)
        with self.app.state.identity._lock:
            b=self.app.state.identity._db.execute("SELECT encrypted FROM pm_market_connections").fetchone()[0]
        self.assertNotIn(oz["api_key"].encode(),b)
        self.assertEqual(self.root.joinpath("market-connections.key").stat().st_mode&0o777,0o600)
        self.assertEqual(a["state"],"collecting");self.assertTrue(a["job_id"])
        with patch.object(self.app.state.http,"request",new_callable=AsyncMock,side_effect=AssertionError("Interactive check made direct provider HTTP")) as direct:
            r=self.c.post(u+"/check",headers=self.h(),json={})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual((r.json()["job_id"],r.json()["state"]),(a["job_id"],"collecting"))
            self.assertEqual(direct.await_count,0)
        done,events=finish_fixture_job(self,a["job_id"])
        self.assertEqual(done["state"],"ready")
        current=self.c.get(MARKET,headers=self.h()).json()["connections"][0]
        self.assertEqual(current["checks"],{"Seller":"verified"})
        self.assertEqual(current["status"],"verified")
        # Advertising credentials retained during migration are not used by the
        # material accounting collector, and a new read never calls advertising.
        self.assertEqual([(e["template"],e["method"],e["path"]) for e in events],[("OZ-01","POST","/v1/roles")])
        with patch.object(self.app.state.http,"request",new_callable=AsyncMock,side_effect=AssertionError("Save made direct provider HTTP")) as direct:
            wb=self.c.post(MARKET,headers=self.h(),json={"provider":"wb","name":"WB","fields":{"token":"fixture-wb-token"}})
            self.assertEqual(wb.status_code,200,wb.text)
            w=self.c.post(MARKET+"/"+wb.json()["id"]+"/check",headers=self.h(),json={})
            self.assertEqual(w.status_code,200,w.text);self.assertEqual(w.json()["state"],"collecting")
            self.assertEqual(direct.await_count,0)
        denied,events=finish_fixture_job(self,w.json()["job_id"],fault=lambda e:{"status_code":403,"headers":{},"payload":{}})
        self.assertEqual(denied["state"],"denied")
        self.assertEqual(len(events),1)
        self.assertNotIn("fixture-wb-token",json.dumps(denied))
        r=self.c.post(u+"/keys",headers=self.h(),json={"version":1,"fields":{"client_id":"12345","api_key":"new-fixture-key"}})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["version"],2)
        self.assertEqual(r.json()["status"],"saved")
        self.assertEqual((r.json()["job_id"],r.json()["state"]),(a["job_id"],"collecting"))
        rotated,_=finish_fixture_job(self,r.json()["job_id"])
        self.assertEqual(rotated["state"],"ready")
        self.assertEqual(self.c.post(u+"/remove",headers=self.h(),json={"version":1}).status_code,409)
        self.assertEqual(self.c.post(u+"/remove",headers=self.h(),json={"version":2}).status_code,200)
        self.assertFalse((self.root/"usage.jsonl").exists())
    def test_market_invalid_and_workshop_scope(self):
        for provider,fields in [("ozon",{"api_key":"abc"}),("wb",{"token":""}),("wordstat",{"token":"x"}),("ozon",{"url":"https://example.test"})]:
            r=self.c.post(MARKET,headers=self.h(),json={"provider":provider,"name":"X","fields":fields})
            self.assertEqual(r.status_code,400,r.text)
        self.assertEqual(self.c.get(MARKET+"?workshop=unknown",headers=self.h()).status_code,400)
        self.assertEqual(self.c.get(MARKET).status_code,401)
    def test_telegram_widget_consent_and_disconnect(self):
        fields={"auth_mode":"widget","bot_token":"123456789:fixture-token-not-real-123456789","bot_username":"example_fixture_bot"}
        self.assertEqual(self.c.post(CONFIG,headers=self.h(),json=fields).status_code,403)
        r=self.c.post(CONFIG,headers=self.h("admin"),json=fields)
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn(fields["bot_token"],r.text)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertTrue(telegram_api.Config.load())
        self.assertEqual(self.c.get(TG,headers=self.h()).json(),{"configured":True,"linked":False,"hasBinding":False})
        h=self.login()
        r=self.c.post(TG+"/connect",headers=h,json={});self.assertEqual(r.status_code,200,r.text)
        state=parse_qs(urlsplit(r.json()["url"]).query)["state"][0]
        page=self.c.get(r.json()["url"]);self.assertEqual(page.status_code,200)
        self.assertIn('data-telegram-login="example_fixture_bot"',page.text)
        user={"id":1234567,"auth_date":int(time.time()),"first_name":"Fixture"}
        data="\n".join(f"{k}={user[k]}" for k in sorted(user))
        user["hash"]=hmac.new(hashlib.sha256(fields["bot_token"].encode()).digest(),data.encode(),hashlib.sha256).hexdigest()
        payload={"state":state,"user":user}
        with patch.object(telegram_api,"send",new_callable=AsyncMock,return_value=1) as send:
            self.assertEqual(self.c.post("/api/telegram/complete",headers=self.login("other"),json=payload).status_code,409)
            self.assertEqual(self.c.post("/api/telegram/complete",headers=self.login(),json={"state":state,"user":{**user,"hash":"0"*64}}).status_code,400)
            r=self.c.post("/api/telegram/complete",headers=h,json=payload);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(send.await_count,1)
            self.assertTrue(self.c.get(TG,headers=self.h()).json()["linked"])
            self.assertEqual(self.c.post("/api/telegram/complete",headers=h,json=payload).status_code,409)
            r=self.c.post(TG,headers=self.h(),json={"action":"test"});self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(send.await_count,2)
            self.assertEqual(self.c.post(TG+"/disconnect",headers=h,json={}).status_code,200)
            self.assertFalse(self.c.get(TG,headers=self.h()).json()["linked"])
            next_link=self.c.post(TG+"/connect",headers=h,json={})
            self.assertEqual(next_link.status_code,200)
            next_state=parse_qs(urlsplit(next_link.json()["url"]).query)["state"][0]
            self.assertEqual(self.c.post(TG,headers=self.h(),json={"action":"disconnect"}).status_code,200)
            self.assertEqual(self.c.post("/api/telegram/complete",headers=h,json={**payload,"state":next_state}).status_code,409)

        self.assertFalse((self.root/"usage.jsonl").exists())
