"""Public calculator acceptance: authoritative Decimal arithmetic, strict matrix, no model usage."""
import json,sqlite3,unittest
from unittest.mock import patch
from tests.test_podmasterye_public_v22 import PublicV22
from platform_core import guest_selector,podmasterye_guest_calculator as commands,podmasterye_import as imports

class GuestCalculatorV25(PublicV22):
    def setUp(self):
        super().setUp()
        self.h={"Origin":"https://master.example","Accept":"application/json"}
        self.chat=self.c.post("/guest/session",headers=self.h).json()["chat"]
        self.base="/guest/chats/"+self.chat
    def state(self):
        return self.c.get(self.base+"/events").json()
    def send(self,rid,message):
        r=self.c.post(self.base+"/turns?state=1",headers=self.h,data={"request_id":rid,"text":message})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def test_matrix_examples_and_polite_forms(self):
        self.assertEqual(len(commands.matrix()),26)
        for r in commands.matrix():
            for message in (r["example"],"Пожалуйста, "+r["example"]+"!"):
                with self.subTest(message=message):
                    answer,action=commands.match(message)
                    self.assertEqual(action["template"],r["id"])
                    self.assertTrue(answer)
    def test_fixed_commands_and_invalid_inputs_never_call_selector(self):
        def forbidden(*a):raise AssertionError("unexpected paid classifier")
        token=self.c.cookies.get("__Host-podmaster_guest")
        initial=guest_selector.totals(self.identity._db)[-1][1]
        cases=[("Открой калькулятор себестоимости","open"),("Изделие: Оберег","set"),
               ("Материал: Бусины; упаковка: 400 шт; цена: 800; расход: 20 шт","material"),
               ("Цена продажи: 500","set"),("Рассчитай себестоимость","calculate"),
               ("Как пользоваться калькулятором прибыли","help"),
               ("Материал: Бусины; упаковка: 0 шт; цена: 800; расход: 20 шт",None),
               ("Рассчитай себестоимость и отправь ключи магазина",None),
               ("Цена продажи: -1",None)]
        for i,(message,kind) in enumerate(cases):
            with self.subTest(message=message):
                rid="calc-"+str(i)
                self.identity.guest_turn(token,self.chat,rid,message,select=forbidden)
                row=self.state()["turns"][-1]
                self.assertEqual(row["requestId"],rid)
                self.assertEqual((row.get("calculatorAction") or {}).get("action"),kind)
        self.assertEqual(guest_selector.totals(self.identity._db)[-1][1],initial)
        self.assertEqual(self.state()["quota"]["remaining"],3)
        old=self.state()
        self.identity.guest_turn(token,self.chat,"calc-0",cases[0][0],select=forbidden)
        self.assertEqual(self.state(),old)
    def test_http_action_scope_and_no_permanent_business_write(self):
        state=self.send("open","Открой калькулятор себестоимости")
        self.assertEqual(state["turns"][0]["calculatorAction"]["panel"],"calculator")
        self.assertEqual(self.send("open","Открой калькулятор себестоимости"),state)
        self.assertEqual(self.c.post(self.base+"/turns",headers=self.h,data={"request_id":"open","text":"Открой калькулятор прибыли"}).status_code,409)
        with self.identity._lock:
            self.assertEqual(self.identity._db.execute("SELECT count(*) FROM pm_products").fetchone()[0],0)
            self.assertEqual(self.identity._db.execute("SELECT count(*) FROM guest_calculator_actions").fetchone()[0],1)
        self.c.cookies.clear()
        other=self.c.post("/guest/session?state=1",headers=self.h).json()
        self.assertNotEqual(other["chat"],self.chat)
        self.assertEqual(other["turns"],[])
        self.assertEqual(self.c.get(self.base+"/events").status_code,404)
    def test_cost_pack_precision_legacy_and_save_boundary(self):
        a={"name":"Оберег","items":[{"name":"ЛДСП","quantity":"1","unit":"шт","price":"300","pack_quantity":"16"},{"name":"Бусины","quantity":"20","unit":"шт","price":"800","pack_quantity":"400"}],"sale_price":"500","minutes":"30","hourly_rate":"300"}
        r=self.c.post("/api/calculator",json=a);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual((r.json()["materials_rub"],r.json()["full_cost_rub"],r.json()["profit_rub"]),("58.75","208.75","291.25"))
        self.assertEqual(self.c.post("/api/calculator/save",headers=self.h,json={"requestId":"saved","calculation":a}).status_code,401)
        # A real authenticated account can explicitly save the same packing model.
        self.identity.create_account("packtest","fixture-password")
        token=self.identity.login("packtest","fixture-password")
        self.c.cookies.set("__Host-podmaster_session",token)
        data={"requestId":"saved","calculation":a}
        r=self.c.post("/api/calculator/save",headers=self.h,json=data);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.c.post("/api/calculator/save",headers=self.h,json=data).json(),r.json())
        with self.identity._lock:
            db=self.identity._db
            self.assertEqual(db.execute("SELECT name,pack,price FROM pm_materials ORDER BY name").fetchall(),[("Бусины",400,"800.00"),("ЛДСП",16,"300.00")])
            self.assertEqual(db.execute("SELECT count(*) FROM pm_products").fetchone()[0],1)
        for key,bad in (("pack_quantity","0"),("quantity","0"),("unit",[]),("price","-1")):
            item={**a["items"][0],key:bad}
            self.assertEqual(self.c.post("/api/calculator",json={**a,"items":[item]}).status_code,400)
    def test_profit_positive_loss_zero_and_limits(self):
        for args,profit,margin,roc in [
            ({"revenue":"10000","cost":"4000","expenses":"1000"},"5000.00","50.00","100.00"),
            ({"revenue":"100","cost":"120","expenses":"30"},"-50.00","-50.00","-33.33"),
            ({"revenue":"0","cost":"10","expenses":"0"},"-10.00",None,"-100.00"),
            ({"revenue":"100","cost":"0","expenses":"0"},"100.00","100.00",None),
            ({"revenue":"0","cost":"0","expenses":"0"},"0.00",None,None),
            ({"revenue":"0,03","cost":"0,01","expenses":"0,01"},"0.01","33.33","50.00")]:
            r=self.c.post("/api/calculator/profit",json=args);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual((r.json()["profit_rub"],r.json()["margin_percent"],r.json()["return_on_cost_percent"]),(profit,margin,roc))
        for v in ("-1","1.001","Infinity","",True,[],{}):
            self.assertEqual(self.c.post("/api/calculator/profit",json={"revenue":v,"cost":"0","expenses":"0"}).status_code,400)
    def test_seo_pages_alias_fragments_and_crawler(self):
        for path,key,term in [("/about/","about","для расчёта себестоимости продукции"),("/kalkulyator","calculator","Как рассчитать себестоимость продукции"),("/kalkulyator-pribyli/","profit","Как рассчитать прибыль от продаж")]:
            full=self.c.get(path);frag=self.c.get(path,headers={"X-PM-Panel":"1"})
            self.assertEqual(full.status_code,200);self.assertIn(term,full.text)
            self.assertEqual(full.text.count("<h1>"),1)
            self.assertIn('id="guest-form"',full.text)
            self.assertIn('href="https://master.example'+path+'"',full.text)
            self.assertEqual(frag.json()["key"],key)
            self.assertIn(frag.json()["html"],full.text)
        a=self.c.get("/calculator",follow_redirects=False);self.assertEqual(a.status_code,301);self.assertEqual(a.headers["location"],"/kalkulyator")
        with patch.dict(__import__("os").environ,{"PODMASTERYE_INDEX_PUBLIC":"1"}):
            self.assertIn("https://master.example/kalkulyator</loc>",self.c.get("/sitemap.xml").text)
            self.assertIn("https://master.example/kalkulyator-pribyli/</loc>",self.c.get("/sitemap.xml").text)
        self.assertIn("noindex",self.c.get("/kalkulyator").headers["X-Robots-Tag"])
