"""Connection discovery contract, migration and scope isolation."""
import asyncio
import sqlite3
import unittest
from unittest.mock import patch
import httpx
from tests import test_podmasterye_market_links as base
from platform_core import podmasterye_yandex_market as ym, podmasterye_market_links as links
from tests.fixtures.market_dual import finish_fixture_job

MARKET=base.MARKET
SECRET="fixture-yandex-market-key"

def campaign(cid,bid=12):
    return {"id":cid,"business":{"id":bid,"name":"Учебный кабинет"},"domain":"Магазин "+str(cid),"placementType":"FBS","apiAvailability":"AVAILABLE"}

def auth():
    return {"status":"OK","result":{"apiKey":{"authScopes":["ALL_METHODS_READ_ONLY"],"name":"fixture"}}}

class Probe(unittest.IsolatedAsyncioTestCase):
    async def test_paging(self):
        calls=[]
        def respond(req):
            self.assertEqual(req.url.host,"api.partner.market.yandex.ru")
            self.assertEqual(req.headers["Api-Key"],SECRET)
            self.assertNotIn(SECRET,str(req.url))
            calls.append((req.method,req.url.path,dict(req.url.params)))
            if req.url.path.endswith("/auth/token"):return httpx.Response(200,json=auth())
            if "pageToken" not in req.url.params:return httpx.Response(200,json={"campaigns":[campaign(1)],"paging":{"nextPageToken":"second"}})
            return httpx.Response(200,json={"campaigns":[campaign(2)],"paging":{}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            checks,details=await ym.probe(c,{"api_key":SECRET})
        self.assertEqual(checks,{"Токен":"verified","Список магазинов":"verified"})
        self.assertTrue(details["complete"])
        self.assertEqual([x["campaignId"] for x in details["campaigns"]],[1,2])
        self.assertEqual(calls,[("POST","/v2/auth/token",{}),("GET","/v2/campaigns",{"limit":"100"}),("GET","/v2/campaigns",{"limit":"100","pageToken":"second"})])
    async def test_failures_and_incomplete(self):
        for status in (401,403,429,500,302):
            with self.subTest(status=status):
                calls=[]
                def respond(req):
                    calls.append(req.url.path)
                    return httpx.Response(status,headers={"Location":"https://example.org"},json={"error":SECRET})
                async with httpx.AsyncClient(transport=httpx.MockTransport(respond),follow_redirects=True) as c:
                    checks,details=await ym.probe(c,{"api_key":SECRET})
                self.assertEqual(len(calls),1)
                self.assertNotEqual(checks["Токен"],"verified")
                self.assertNotIn(SECRET,str(details))
        for broken in ({"campaigns":[campaign(1)],"paging":{"nextPageToken":"loop"}},{"campaigns":[{"id":1}]},{"campaigns":None},{"status":"ERROR"}):
            def respond(req):
                return httpx.Response(200,json=auth() if req.url.path.endswith("/auth/token") else broken)
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
                checks,details=await ym.probe(c,{"api_key":SECRET})
            self.assertFalse(details["complete"]);self.assertEqual(details["campaigns"],[])
            self.assertNotEqual(checks["Список магазинов"],"verified")
    async def test_empty_and_no_credential_echo(self):
        for shops in ([],[{"id":1,"business":{"id":2,"name":SECRET},"domain":SECRET}]):
            def respond(req):
                return httpx.Response(200,json=auth() if req.url.path.endswith("/auth/token") else {"campaigns":shops})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
                checks,details=await ym.probe(c,{"api_key":SECRET})
            self.assertTrue(details["complete"])
            self.assertNotIn(SECRET,str(details))
    async def test_second_page_failure(self):
        def respond(req):
            if req.url.path.endswith("/auth/token"):return httpx.Response(200,json=auth())
            if "pageToken" in req.url.params:return httpx.Response(429)
            return httpx.Response(200,json={"campaigns":[campaign(1)],"paging":{"nextPageToken":"next"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            checks,details=await ym.probe(c,{"api_key":SECRET})
        self.assertEqual(checks["Список магазинов"],"rate_limited")
        self.assertFalse(details["complete"]);self.assertEqual(details["campaigns"],[])

class YandexAPI(unittest.TestCase):
    setUp=base.Integrations.setUp
    h=base.Integrations.h
    def test_connection_lifecycle(self):
        self.assertIn("yandex_market",self.c.get(MARKET,headers=self.h()).json()["providers"])
        r=self.c.post(MARKET,headers=self.h(),json={"provider":"yandex_market","name":"Яндекс","fields":{"api_key":SECRET}})
        self.assertEqual(r.status_code,200,r.text);url=MARKET+"/"+r.json()["id"]
        self.assertEqual(r.json()["status"],"saved");self.assertNotIn(SECRET,r.text)
        for fields in ({},{"api_key":""},{"token":SECRET},{"api_key":"secret key"},{"api_key":SECRET,"url":"https://example.org"}):
            self.assertEqual(self.c.post(MARKET,headers=self.h(),json={"provider":"yandex_market","name":"bad","fields":fields}).status_code,400)
        self.assertEqual(self.c.get(MARKET,headers=self.h("other")).json()["connections"],[])
        self.assertEqual(self.c.post(url+"/check",headers=self.h("other"),json={}).status_code,404)
        self.assertEqual(self.c.post(url+"/keys",headers=self.h("other"),json={"version":1,"fields":{"api_key":"foreign"}}).status_code,404)
        with self.app.state.identity._lock:
            self.assertNotIn(SECRET.encode(),self.app.state.identity._db.execute("SELECT encrypted FROM pm_market_connections").fetchone()[0])
        with patch.object(self.app.state.http,"request",side_effect=AssertionError("Interactive verification must only enqueue")):
            r=self.c.post(url+"/check",headers=self.h(),json={})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["state"],"collecting")
        done,events=finish_fixture_job(self,r.json()["job_id"])
        self.assertEqual(done["state"],"ready")
        self.assertEqual([e["path"] for e in events],["/v2/auth/token","/v2/campaigns"])
        r=self.c.get(MARKET,headers=self.h());self.assertNotIn(SECRET,r.text)
        self.assertTrue(r.json()["connections"][0]["details"]["complete"])
        self.assertEqual(r.json()["connections"][0]["details"]["campaigns"][0]["businessId"],12)
        r=self.c.post(url+"/keys",headers=self.h(),json={"version":1,"fields":{"api_key":"new-fixture-market-key"}})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["status"],"saved")
        self.assertEqual(r.json()["details"],{});self.assertEqual(r.json()["version"],2)
        self.assertEqual(self.c.post(url+"/remove",headers=self.h(),json={"version":1}).status_code,409)
        self.assertEqual(self.c.post(url+"/remove",headers=self.h(),json={"version":2}).status_code,200)
    def test_migration_preserves_old_ciphertext(self):
        for provider,fields in [("ozon",{"client_id":"1","api_key":"fixture-ozon"}),("wb",{"token":"fixture-wb"})]:
            r=self.c.post(MARKET,headers=self.h(),json={"provider":provider,"name":provider,"fields":fields})
            self.assertEqual(r.status_code,200,r.text)
        store=self.app.state.identity
        cols="id,workspace,provider,name,encrypted,version,checks,checked"
        with store._lock:
            old=store._db.execute("SELECT "+cols+" FROM pm_market_connections ORDER BY id").fetchall()
        # Reproduce the real v32 schema, before either YM or quantity queue
        # foreign keys existed. Downgrading one table in a current schema is
        # intentionally rejected by the fail-closed migration guard.
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE TABLE workspaces(workspace_id TEXT PRIMARY KEY)")
            db.executemany("INSERT INTO workspaces VALUES(?)",[(w,) for w in {r[1] for r in old}])
            db.execute(links.SCHEMA.replace(",'yandex_market'","").replace(", details TEXT NOT NULL DEFAULT '{}'",""))
            db.executemany("INSERT INTO pm_market_connections("+cols+") VALUES(?,?,?,?,?,?,?,?)",old)
            links.init(db);links.init(db)
            self.assertEqual(old,db.execute("SELECT "+cols+" FROM pm_market_connections ORDER BY id").fetchall())
            self.assertEqual(db.execute("pragma foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("SELECT DISTINCT details FROM pm_market_connections").fetchall(),[("{}",)])
            for cid,w,p,name,encrypted,version,checks,checked in old:
                self.assertTrue(self.app.state.market_links.unpack(w,cid,p,encrypted))
            db.execute("CREATE TABLE future_dependency(cid TEXT REFERENCES pm_market_connections(id))")
            self.assertIn("future_dependency",[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")])
        self.assertEqual(len(self.c.get(MARKET,headers=self.h()).json()["connections"]),2)
        self.assertEqual(self.c.post(MARKET,headers=self.h(),json={"provider":"yandex_market","name":"new","fields":{"api_key":SECRET}}).status_code,200)
