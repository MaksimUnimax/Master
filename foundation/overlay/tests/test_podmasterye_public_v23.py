"""Regression of the faster public transport: old API shapes and scope stay intact."""
from tests import test_podmasterye_public_v22 as previous
from platform_core import coins,guest_selector
from unittest.mock import patch

class PublicV23(previous.PublicV22):
    def test_combined_guest_snapshot_and_replay(self):
        h={"Origin":"https://master.example","Accept":"application/json"}
        with patch.object(guest_selector,"classify",side_effect=AssertionError("unexpected paid request")):
            r=self.c.post("/guest/session?state=1",headers=h)
            self.assertEqual(r.status_code,200,r.text)
            data=r.json();chat=data["chat"];base="/guest/chats/"+chat
            self.assertEqual(data["quota"]["remaining"],12)
            self.assertEqual(data["turns"],[])
            self.assertEqual(self.c.post("/guest/session",headers=h).json(),{"chat":chat})
            body={"request_id":"one","text":"Сколько стоит монета?"}
            for _ in range(2):
                r=self.c.post(base+"/turns?state=1",headers=h,data=body)
                self.assertEqual(r.status_code,200,r.text);state=r.json()
                self.assertTrue(state.pop("accepted"))
                self.assertEqual(state["quota"]["remaining"],11)
                self.assertEqual(len(state["turns"]),1)
                self.assertEqual(state,self.c.get(base+"/events").json())
            self.assertEqual(self.c.post("/guest/session?state=1",headers=h).json(),{"chat":chat,**state})
            self.assertEqual(self.c.post(base+"/turns",headers=h,data=body).json(),{"accepted":True})

    def test_guest_snapshot_is_read_only_and_foreign_scope_is_denied(self):
        h={"Origin":"https://master.example","Accept":"application/json"}
        data=self.c.post("/guest/session?state=1",headers=h).json()
        chat=data["chat"];cookie=self.c.cookies.get("__Host-podmaster_guest")
        stmts=[]
        with self.identity._lock:self.identity._db.set_trace_callback(stmts.append)
        try:
            r=self.c.get("/guest/chats/"+chat+"/events");self.assertEqual(r.status_code,200)
        finally:
            with self.identity._lock:self.identity._db.set_trace_callback(None)
        self.assertFalse(any(s.upper().startswith(("BEGIN IMMEDIATE","INSERT ","UPDATE ","DELETE ")) for s in stmts),stmts)
        self.c.cookies.clear()
        other=self.c.post("/guest/session?state=1",headers=h).json()
        self.assertNotEqual(chat,other["chat"])
        self.assertEqual(other["turns"],[])
        self.assertEqual(self.c.get("/guest/chats/"+chat+"/events").status_code,404)
        self.assertEqual(self.c.post("/guest/session?state=1",headers={"Origin":"https://evil.example"}).status_code,403)
        self.c.cookies.clear()
        self.c.cookies.set("__Host-podmaster_guest",cookie,domain="master.example",path="/")
        self.assertEqual(self.c.post("/guest/session?state=1",headers=h).json()["chat"],chat)

    def test_fragment_transport_and_fresh_payment(self):
        h={"X-PM-Panel":"1","Accept":"application/json"}
        for path,key in [("/","about"),("/about/","about"),("/contacts","contacts"),("/support","support"),("/privacy","privacy"),("/payment","payment"),("/faq","faq"),("/login","login"),("/register","register")]:
            with self.subTest(path=path):
                full=self.c.get(path);part=self.c.get(path,headers=h)
                self.assertEqual(part.status_code,200,part.text)
                self.assertIn("application/json",part.headers["content-type"])
                self.assertEqual(part.headers["cache-control"],"no-store")
                self.assertIn("X-PM-Panel",part.headers["vary"])
                data=part.json()
                self.assertEqual(data["key"],key)
                self.assertFalse(data["member"])
                self.assertIn(data["html"],full.text)
                self.assertNotIn("<script",data["html"])
                self.assertNotIn('id="guest-form"',data["html"])
                self.assertLess(len(part.content),len(full.content))
                self.assertNotIn('id="public-menu-close"',full.text)
                self.assertEqual(full.text.count('id="public-menu-toggle"'),1)
        with self.identity._write() as db:coins.set_sale_pricing(db,"30")
        self.assertIn("130,00 ₽",self.c.get("/payment",headers=h).json()["html"])
        with self.identity._write() as db:coins.set_sale_pricing(db,"40")
        self.assertIn("140,00 ₽",self.c.get("/payment",headers=h).json()["html"])
