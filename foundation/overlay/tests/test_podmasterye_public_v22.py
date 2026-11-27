"""Public UI and SEO contract; isolated accounts, no provider or payment traffic."""
import os,tempfile,unittest,re
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from platform_core.chat_api import create_app
from platform_core import coins, guest_selector, checkout
from platform_core.podmasterye_public_pages import PAGES,INDEXABLE
from xml.etree import ElementTree

class PublicV22(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ,{"HARNESS_PROVIDER_KEYS_DIR":str(self.root/"keys"),"YOOKASSA_PAYMENTS_ENABLED":"0","PODMASTERYE_PUBLIC_ORIGIN":"https://master.example","PODMASTERYE_INDEX_PUBLIC":"0","HARNESS_OFFLINE_MODEL":"1"}))
        self.c=self.enterContext(TestClient(create_app(self.root/"stage.sqlite3",self.root/"chats"),base_url="https://master.example"))
        self.identity=self.c.app.state.identity
    def test_public_routes_and_legal_information(self):
        for path in ["/",*(PAGES[k][0] for k in INDEXABLE)]:
            with self.subTest(path=path):
                r=self.c.get(path);self.assertEqual(r.status_code,200,r.text)
                self.assertIn('data-mode="public"',r.text)
                self.assertIn('id="guest-form"',r.text)
                self.assertIn('name="description"',r.text)
                self.assertEqual(r.text.count("<h1>"),1)
                self.assertIn("ИП Ягофаров Максим Ринатович",r.text)
                self.assertIn("741705866660",r.text)
                self.assertIn("320745600093211",r.text)
                self.assertIn("OpenScripts@yandex.com",r.text)
                self.assertNotIn("id=\"attach-file\"",r.text)
                self.assertNotIn("id=\"attachment-picker\"",r.text)
                self.assertIn("noindex",r.headers["X-Robots-Tag"])
        self.assertIn("support@octoport.ru",self.c.get("/support").text)
        self.assertIn("support@octoport.ru",self.c.get("/contacts").text)
        self.assertIn('href="https://master.example/about/"',self.c.get("/").text)
        self.assertIn("Disallow: /\n",self.c.get("/robots.txt").text)
        for key in ("login","register"):
            r=self.c.get(PAGES[key][0]);self.assertEqual(r.status_code,200)
            self.assertIn('data-panel-key="'+key+'"',r.text);self.assertIn("noindex",r.headers["X-Robots-Tag"])
        self.assertEqual(self.c.get("/app/",follow_redirects=False).status_code,303)
        self.assertEqual(self.c.get("/admin/statistics").status_code,401)
        self.assertEqual(self.c.get("/assets/podmasterye-public.js").status_code,200)
        self.assertEqual(self.c.get("/assets/podmasterye-public.css").status_code,200)
    def test_indexing_explicit_opt_in_and_sitemap(self):
        with patch.dict(os.environ,{"PODMASTERYE_INDEX_PUBLIC":"1"}):
            for key in INDEXABLE:
                r=self.c.get(PAGES[key][0]);self.assertEqual(r.headers["X-Robots-Tag"],"index, follow")
            self.assertIn("noindex",self.c.get("/login").headers["X-Robots-Tag"])
            r=self.c.get("/robots.txt");self.assertIn("Sitemap: https://master.example/sitemap.xml",r.text)
            self.assertIn("Disallow: /admin",r.text)
            xml=ElementTree.fromstring(self.c.get("/sitemap.xml").content)
            urls={n.text for n in xml.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
            self.assertEqual(urls,{"https://master.example"+PAGES[k][0] for k in INDEXABLE})
        with patch.dict(os.environ,{"PODMASTERYE_INDEX_PUBLIC":"1","PODMASTERYE_PUBLIC_ORIGIN":"https://attacker.example/path"}):
            self.assertIn("noindex",self.c.get("/about/").headers["X-Robots-Tag"])
            self.assertEqual(self.c.get("/robots.txt").text,"User-agent: *\nDisallow: /\n")
    def test_payment_matches_quote_and_no_checkout(self):
        with self.identity._write() as db:
            coins.set_sale_pricing(db,"30")
            coins.set_signup_bonus(db,"21")
        r=self.c.get("/payment");self.assertIn("1,30 ₽",r.text);self.assertIn("130,00 ₽",r.text)
        self.assertIn("21 монет",r.text);self.assertIn("Приём платежей сейчас отключён",r.text)
        faq=self.c.get("/faq").text
        self.assertIn("1,30 ₽",faq);self.assertNotIn("{sale_price}",faq);self.assertNotIn("{checkout_steps}",faq)
        self.assertEqual(self.c.get("/api/coins/quote?coins=100").json(),{"total":"130.00","enabled":False})
        self.assertEqual(self.c.post("/api/coins/checkout",headers={"Origin":"https://master.example"},json={}).status_code,401)
    def test_guest_continuity_and_authorized_public_pages(self):
        headers={"Origin":"https://master.example","Accept":"application/json"}
        with patch.object(guest_selector,"classify",side_effect=AssertionError("unexpected live model")):
            chat=self.c.post("/guest/session",headers=headers).json()["chat"]
            path=f"/guest/chats/{chat}"
            self.assertEqual(self.c.post(path+"/turns",headers=headers,data={"request_id":"one","text":"Сколько стоит монета?"}).status_code,200)
            for key in INDEXABLE:self.assertEqual(self.c.get(PAGES[key][0]).status_code,200)
            self.assertEqual(self.c.post("/guest/session",headers=headers).json()["chat"],chat)
            self.assertEqual(self.c.get(path+"/events").json()["quota"]["remaining"],11)
        self.identity.create_account("publictest","local-fixture-password")
        token=self.identity.login("publictest","local-fixture-password")
        self.c.cookies.set("__Host-podmaster_session",token)
        r=self.c.get("/about/");self.assertIn("Вы вошли в аккаунт",r.text);self.assertNotIn('id="guest-form"',r.text)
        r=self.c.get("/app/");self.assertEqual(r.status_code,200);self.assertIn('data-mode="member"',r.text);self.assertIn("noindex",r.headers["X-Robots-Tag"])
