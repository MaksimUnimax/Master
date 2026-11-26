"""Independent interface acceptance with isolated accounts and synthetic mail.
No paid model, no external store, no production database.
Each test opens a fresh browser context and owns its fixtures.
"""
import io
import os
import socket
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from urllib.parse import urlencode

import uvicorn
from PIL import Image
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect
from platform_core.chat_api import create_app
from platform_core.guest_registration import RegistrationStore
from platform_core.account_access import AccountAccess
from platform_core import podmasterye_book as book
from tests.auth_fixture import email_opted_out

P="fixture-browser-password"

class IndependentUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix="pm-ui-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)
        cls.db=cls.root/"book.sqlite3"
        cls.inbox={}
        from cryptography.fernet import Fernet
        key=cls.root/"auth.key";key.write_bytes(Fernet.generate_key())
        cls.env=patch.dict(os.environ,{"HARNESS_OFFLINE_MODEL":"0","HARNESS_USAGE_JOURNAL":str(cls.root/"usage.jsonl")})
        cls.env.start();cls.addClassCleanup(cls.env.stop)
        os.environ.pop("HARNESS_MODEL_GATEWAY_URL",None)
        original=AccountAccess.__init__
        def configured(access,store,*args,**kwargs):
            original(access,store,mail=cls.inbox.__setitem__,keyfile=key)
        fixture=patch.object(AccountAccess,"__init__",configured)
        fixture.start();cls.addClassCleanup(fixture.stop)
        cls.app=create_app(cls.db,cls.root/"chats")
        sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(64)
        cls.origin="http://127.0.0.1:"+str(sock.getsockname()[1])
        cls.server=uvicorn.Server(uvicorn.Config(cls.app,log_level="warning",access_log=False))
        cls.thread=threading.Thread(target=cls.server.run,kwargs={"sockets":[sock]},daemon=True);cls.thread.start()
        def stop():
            cls.server.should_exit=True;cls.thread.join(timeout=10);sock.close()
        cls.addClassCleanup(stop)
        deadline=time.monotonic()+10
        while not cls.server.started:
            if time.monotonic()>deadline:raise RuntimeError("Server failed")
            time.sleep(.05)
        cls.pw=sync_playwright().start();cls.addClassCleanup(cls.pw.stop)
        cls.browser=cls.pw.chromium.launch(headless=True,args=["--no-sandbox"])
        cls.addClassCleanup(cls.browser.close)
        cls.evidence=Path(os.environ.get("PODMASTER_BROWSER_EVIDENCE",str(cls.root)))
        cls.evidence.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.login="ui_"+uuid4().hex[:14]
        self.recovery=self.app.state.identity.create_account(self.login,P)
        email_opted_out(self.app.state.identity,self.login)
        self.ctx=self.browser.new_context(base_url=self.origin,accept_downloads=True,viewport={"width":1440,"height":1000},locale="ru-RU",permissions=["clipboard-read","clipboard-write"])
        self.addCleanup(self.ctx.close)
        self.page=self.ctx.new_page();self.page.set_default_timeout(4500)
        self.errors=[];self.page.on("pageerror",lambda e:self.errors.append(str(e)))
        self.page.on("dialog",lambda d:d.accept())
        self.day=book.today()
    def tearDown(self):
        if not self.page.is_closed():
            self.page.screenshot(path=str(self.evidence/(self._testMethodName+".png")),animations="disabled")
        self.assertEqual(self.errors,[])
        self.assertFalse((self.root/"usage.jsonl").exists(),"Model usage was recorded")
    def sign_in(self,login=None,password=P):
        p=self.page;p.goto("/login")
        p.get_by_label("Логин",exact=True).fill(login or self.login)
        p.get_by_label("Пароль",exact=True).fill(password)
        p.get_by_role("button",name="Войти",exact=True).click()
        self.ready()
    def ready(self):
        expect(self.page.locator("body")).to_have_attribute("data-mode","member")
        expect(self.page.locator("#assistant-form button")).to_be_enabled(timeout=10000)
    def nav(self,section):
        p=self.page
        with p.expect_response(lambda r:"/api/accounting?" in r.url and r.request.method=="GET") as got:
            p.locator('nav button[data-page="'+section+'"]').click()
        self.assertEqual(got.value.status,200)
        expect(p.locator('[data-panel="'+section+'"]')).to_be_visible()
        return got.value.json()
    def call(self,path,data=None,*,headers=None,expected=200,workshop=True):
        if workshop and path.startswith(("/api/accounting","/api/production","/api/integrations")):
            wid=self.page.locator("#workshop-select").input_value()
            path+=("&" if "?" in path else "?")+urlencode({"workshop":wid})
        request_headers={"Origin":self.origin,**(headers or {})}
        res=self.ctx.request.get(path,headers=request_headers) if data is None else self.ctx.request.post(path,data=data,headers=request_headers)
        self.assertEqual(res.status,expected,res.text()[:300] if res.status!=expected else "")
        return res.json()
    def op(self,op,**args):
        d=self.call("/api/accounting/preview",{"operation":op,"arguments":args})
        return self.call("/api/accounting/commit",{"requestId":uuid4().hex,"operation":op,"arguments":d["arguments"],"revision":d["revision"]})
    def report(self):return self.call("/api/accounting")
    def seed(self):
        m=self.op("material",name="Бусины",category="Фурнитура",unit="шт",pack=400,pack_price="800",initial_quantity=100,initial_total="200")["id"]
        n=self.op("material",name="Воск",category="Свечи",unit="г",pack=1000,pack_price="500",initial_quantity=1000,initial_total="500")["id"]
        a=self.op("product",name="Браслет",category="Украшения",sale_price="300",minutes=30)["id"]
        b=self.op("product",name="Свеча",category="Свечи",sale_price="200",minutes=20)["id"]
        c=self.op("product",name="Без продаж",category="Прочее")["id"]
        self.op("recipe_line",product=a,material=m,usage=10);self.op("recipe_line",product=b,material=n,usage=100)
        return m,n,a,b,c
    def fill(self,values):
        dlg=self.page.locator("#book-dialog")
        for name,val in values.items():
            e=dlg.locator('[name="'+name+'"]')
            if isinstance(val,bool):e.set_checked(val)
            elif e.evaluate("e=>e.tagName")=="SELECT":
                e.select_option(value=str(val))
            else:e.fill(str(val))
        return dlg
    def confirm(self,expected=None):
        dlg=self.page.locator("#book-dialog")
        dlg.locator("#book-check").click()
        expect(dlg.locator("#book-confirm")).to_be_enabled()
        if expected:expect(dlg.locator("#book-preview")).to_contain_text(expected)
        with self.page.expect_response(lambda r:r.request.method=="POST" and ("/api/accounting/commit" in r.url or "/api/accounting/correction/commit" in r.url)) as got:
            dlg.locator("#book-confirm").click()
        self.assertEqual(got.value.status,200,got.value.text())
        expect(dlg).not_to_be_visible()
        expect(self.page.locator("#book-check")).to_be_enabled()
        return got.value.json()
    def open_op(self,section,op,values):
        self.nav(section);self.page.locator('[data-panel="'+section+'"] [data-book-op="'+op+'"]').click()
        return self.fill(values)
    def ask(self,phrase):
        p=self.page;p.locator("#assistant-form textarea").fill(phrase)
        with p.expect_response(lambda r:r.request.method=="POST" and "/turns" in r.url) as got:
            p.locator("#assistant-form button").click()
        self.assertEqual(got.value.status,200,got.value.text())
        expect(p.locator("#assistant-status")).to_have_text("")
        return got.value.json()
    def metric(self,section,key,value):
        expect(self.page.locator('[data-panel="'+section+'"] [data-metric="'+key+'"] strong')).to_have_text(value)
    def rows(self,selector):
        return self.page.locator(selector+" tbody tr").all_text_contents()

    def test_01_public_navigation_cookie_choices(self):
        p=self.page;p.goto("/")
        expect(p.get_by_role("heading",name="С чего начнём?")).to_be_visible()
        expect(p.locator("#cookie-choice")).to_be_visible()
        p.locator("#cookie-decline").click();expect(p.locator("#cookie-choice")).not_to_be_visible()
        p.reload();expect(p.locator("#cookie-choice")).not_to_be_visible()
        self.assertEqual(p.evaluate("localStorage.getItem('pm-cookie-choice')"),"necessary")
        p.get_by_role("link",name="Частые вопросы",exact=True).click();expect(p.get_by_role("heading",name="Частые вопросы")).to_be_visible()
        p.locator("details").first.locator("summary").click();expect(p.locator("details").first.locator("p")).to_be_visible()
        p.goto("/privacy");expect(p.get_by_role("heading",name="Данные и cookie")).to_be_visible()
        p.evaluate("localStorage.removeItem('pm-cookie-choice')");p.goto("/")
        p.locator("#cookie-accept").click();p.reload()
        self.assertEqual(p.evaluate("localStorage.getItem('pm-cookie-choice')"),"acknowledged")
        p.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),390)
        expect(p.get_by_role("button",name="Войти",exact=True)).to_be_visible()

    def test_02_calculator_validation_live_recalculation(self):
        p=self.page;p.goto("/kalkulyator")
        p.locator("#cookie-decline").click()
        p.get_by_role("button",name="Рассчитать",exact=True).click();expect(p.locator("#calc-save")).to_be_disabled()
        p.locator('[name="product_name"]').fill("Контроль")
        row=p.locator("#calc-rows .calc-line").first
        row.locator('[name="name"]').fill("Бусины")
        row.locator('[name="quantity"]').fill("2")
        row.locator('[name="price"]').fill("100")
        p.locator("#calc-add").click()
        row2=p.locator("#calc-rows .calc-line").nth(1)
        row2.locator('[name="name"]').fill("Нить");row2.locator('[name="quantity"]').fill("0.5");row2.locator('[name="unit"]').select_option("м");row2.locator('[name="price"]').fill("200")
        p.locator('[name="sale_price"]').fill("1000");p.locator('[name="minutes"]').fill("120");p.locator('[name="hourly_rate"]').fill("150")
        expect(p.locator("#calc-result tbody tr").filter(has_text="Прибыль после учёта труда")).to_contain_text("400.00 ₽")
        expect(p.locator("#calc-result tbody tr").filter(has_text="Материальная маржа")).to_contain_text("70.00%")
        expect(p.locator("#calc-result tbody tr").filter(has_text="Доход в час")).to_contain_text("350.00 ₽")
        p.locator('[name="sale_price"]').fill("900")
        expect(p.locator("#calc-result tbody tr").filter(has_text="Прибыль после учёта труда")).to_contain_text("300.00 ₽")
        row2.get_by_role("button",name="×",exact=True).click()
        expect(p.locator("#calc-result tbody tr").filter(has_text="Материалы")).to_contain_text("200.00 ₽")
        row.locator('[name="quantity"]').fill("0")
        expect(p.locator("#calc-save")).to_be_disabled()
        expect(p.locator("#calc-status")).to_contain_text("Количество")
        expect(p.locator("#calc-result")).to_be_empty()

    def test_03_calculator_guest_to_account_save(self):
        p=self.page;p.goto("/kalkulyator");p.locator("#cookie-decline").click()
        p.locator('[name="product_name"]').fill("Из калькулятора")
        r=p.locator("#calc-rows .calc-line").first
        r.locator('[name="name"]').fill("Сырьё");r.locator('[name="quantity"]').fill("2");r.locator('[name="price"]').fill("10")
        p.locator('[name="sale_price"]').fill("100")
        expect(p.locator("#calc-save")).to_be_enabled();p.locator("#calc-save").click()
        expect(p.get_by_label("Логин",exact=True)).to_be_visible()
        p.get_by_label("Логин",exact=True).fill(self.login);p.get_by_label("Пароль",exact=True).fill(P);p.get_by_role("button",name="Войти",exact=True).click()
        self.ready();expect(p.locator("#calc-pending")).to_be_visible()
        p.locator("#calc-accept").click();expect(p.locator("#calc-pending")).not_to_be_visible()
        self.nav("products");expect(p.locator("#products")).to_contain_text("Из калькулятора")
        p.reload();self.ready();self.nav("products")
        self.assertEqual(len(self.report()["products"]),1)

    def test_04_registration_codes_logout_and_invalid_login(self):
        p=self.page;p.goto("/");p.locator("#cookie-decline").click()
        p.get_by_role("button",name="Создать аккаунт",exact=True).click()
        name="new_"+uuid4().hex[:12];address=name+"@example.test"
        p.get_by_label("Логин",exact=True).fill(name);p.get_by_label("Почта",exact=True).fill(address);p.get_by_label("Пароль",exact=True).fill(P)
        p.get_by_role("button",name="Создать аккаунт",exact=True).click()
        expect(p.get_by_role("heading",name="Проверьте почту")).to_be_visible()
        code=self.inbox[address];bad="000000" if code!="000000" else "111111"
        p.get_by_label("Код из письма",exact=True).fill(bad);p.get_by_role("button",name="Продолжить").click()
        expect(p.get_by_role("alert")).to_be_visible()
        p.get_by_label("Код из письма",exact=True).fill(code);p.get_by_role("button",name="Продолжить").click()
        self.ready()
        p.get_by_role("button",name="Выйти",exact=True).click();expect(p.get_by_role("button",name="Войти",exact=True)).to_be_visible()
        p.goto("/app/");expect(p.get_by_role("button",name="Войти",exact=True)).to_be_visible()
        p.get_by_label("Логин",exact=True).fill(name);p.get_by_label("Пароль",exact=True).fill("incorrect-password");p.get_by_role("button",name="Войти",exact=True).click()
        expect(p.get_by_role("alert")).to_be_visible()
        p.get_by_label("Логин",exact=True).fill(name);p.get_by_label("Пароль",exact=True).fill(P);p.get_by_role("button",name="Войти",exact=True).click()
        expect(p.get_by_role("heading",name="Проверьте почту")).to_be_visible()
        p.get_by_label("Код из письма",exact=True).fill(self.inbox[address]);p.get_by_role("button",name="Продолжить").click()
        self.ready()

    def test_05_all_tabs_empty_and_responsive(self):
        self.sign_in();p=self.page
        sections=p.locator("nav button[data-page]").evaluate_all("els=>els.map(x=>x.dataset.page)")
        self.assertEqual(len(sections),18)
        for sec in sections:
            with self.subTest(section=sec):
                self.nav(sec)
                self.assertEqual(p.locator("[data-panel]:visible").count(),1)
                self.assertEqual(p.locator("nav button.active").get_attribute("data-page"),sec)
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),1440)
        self.nav("summary");p.set_viewport_size({"width":390,"height":844})
        for sec in ["products","sales","finance","settings","tasks"]:
            p.locator("#toggle-nav").click();p.locator('nav button[data-page="'+sec+'"]').click()
            expect(p.locator('[data-panel="'+sec+'"]')).to_be_visible()
            expect(p.locator("nav")).not_to_be_visible()
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),390)
        p.locator("#toggle-helper").click();expect(p.locator("aside")).to_be_visible();p.locator("#close-helper").click()

    def test_06_themes_colors_and_workshop_restore(self):
        self.sign_in();p=self.page
        original=p.locator("#workshop-select").input_value()
        self.nav("settings")
        form=p.locator("#workshop-settings")
        colors={}
        for color in ("green","blue","amber","violet","gray"):
            form.locator('[name="color"]').select_option(color)
            with p.expect_response(lambda r:"/api/workshops/change" in r.url and r.request.method=="POST") as got:
                form.get_by_role("button",name="Сохранить",exact=True).click()
            self.assertEqual(got.value.status,200)
            self.assertEqual(got.value.json()["color"],color)
            expect(p.locator("#workshop-status")).to_have_text("Настройки сохранены.")
            expect(form.get_by_role("button",name="Сохранить",exact=True)).to_be_enabled()
            expect(p.locator("html")).to_have_attribute("data-workshop-color",color)
            expect(form.locator("[name=color]")).to_have_value(color)
            colors[color]=p.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
        self.assertEqual(len(set(colors.values())),5)
        p.locator("#theme-select").select_option("dark");expect(p.locator("html")).to_have_attribute("data-theme","dark")
        p.reload();self.ready();self.nav("settings")
        expect(p.locator("#theme-select")).to_have_value("dark")
        expect(p.locator("#workshop-settings [name=color]")).to_have_value("gray")
        p.emulate_media(color_scheme="light");p.locator("#theme-select").select_option("system");expect(p.locator("html")).to_have_attribute("data-theme","light")
        p.emulate_media(color_scheme="dark");expect(p.locator("html")).to_have_attribute("data-theme","dark")
        p.locator("#theme-select").select_option("light")
        p.locator("#workshop-create [name=name]").fill("Вторая мастерская");p.locator("#workshop-create button:not([type=button])").click()
        self.ready();expect(p.locator("#workshop-caption")).to_have_text("Вторая мастерская")
        second=p.locator("#workshop-select").input_value()
        p.locator("#workshop-select").select_option(original);self.ready();self.nav("settings")
        row=p.locator("#workshop-list tbody tr").filter(has_text="Вторая мастерская")
        row.get_by_role("button",name="В архив",exact=True).click()
        expect(row).to_contain_text("архив");expect(p.locator('#workshop-select option[value="'+second+'"]')).to_have_count(0)
        row.get_by_role("button",name="Восстановить",exact=True).click()
        expect(row.get_by_role("button",name="Открыть",exact=True)).to_be_visible()
        expect(p.locator('#workshop-select option[value="'+second+'"]')).to_have_count(1)
        p.locator("#workshop-select").select_option(second);self.ready();expect(p.locator("#workshop-caption")).to_have_text("Вторая мастерская")

    def test_07_category_sales_purchase_filters(self):
        self.sign_in();m,n,a,b,_=self.seed();p=self.page
        self.op("purchase",material=m,quantity=1,purchase_unit="base",total="2",supplier="Первый")
        self.op("purchase",material=n,quantity=1,purchase_unit="base",total="1",supplier="Второй")
        self.op("sale",product=a,quantity=1,unit_price="300",paid_amount="300",channel="Розница",auto_produce=True)
        self.op("sale",product=b,quantity=1,unit_price="200",paid_amount="200",channel="Выставка",auto_produce=True)
        self.nav("sales")
        p.locator("#catalog-category").select_option("Украшения")
        expect(p.locator("#sales-current")).to_contain_text("Браслет");expect(p.locator("#sales-current")).not_to_contain_text("Свеча")
        p.locator("#catalog-category").select_option("Фурнитура");expect(p.locator("#sales-current")).to_have_text("Нет записей")
        p.locator("#catalog-category").select_option("")
        p.locator("#sales-channel-filter").fill("Выставка");expect(p.locator("#sales-current")).not_to_contain_text("Браслет")
        p.locator("#sales-channel-filter").fill("")
        p.locator('[data-panel=sales] [data-book-op=sale]').click()
        p.locator("#book-category").select_option("Украшения")
        expect(p.locator('#book-fields [name=product] option')).to_have_count(2)
        expect(p.locator('#book-fields [name=product] option').nth(1)).to_have_text("Браслет")
        expect(p.locator('#book-category option[value="Фурнитура"]')).to_have_count(0)
        p.locator("#book-category").select_option("");expect(p.locator('#book-fields [name=product] option')).to_have_count(4)
        p.locator("#book-close").click()
        self.nav("purchases")
        p.locator("#catalog-category").select_option("Свечи")
        expect(p.locator('[data-event-table=purchases]')).to_contain_text("Воск")
        expect(p.locator('[data-event-table=purchases]')).not_to_contain_text("Бусины")
        p.locator('[data-panel=purchases] [data-book-op=purchase]').click()
        p.locator("#book-category").select_option("Фурнитура")
        expect(p.locator('#book-fields [name=material] option')).to_have_count(2)
        expect(p.locator('#book-fields [name=material] option').nth(1)).to_contain_text("Бусины")
        p.locator("#book-close").click()
        expect(p.locator('#supplier-suggestions option[value="Первый"]')).to_have_count(1)

    def test_08_catalog_views_and_material_autofill(self):
        self.sign_in();m,n,a,b,_=self.seed();p=self.page
        self.op("purchase",material=m,quantity=100,purchase_unit="base",total="600")
        self.nav("products");p.locator("#product-view").select_option("cards")
        expect(p.locator("#products .catalog-cards article")).to_have_count(3)
        p.locator("#catalog-category").select_option("Украшения");expect(p.locator("#products .catalog-cards article")).to_have_count(1)
        p.locator("#catalog-filter").fill("не существует");expect(p.locator("#products")).to_have_text("Нет записей")
        p.locator("#catalog-filter").fill("");p.locator("#catalog-category").select_option("")
        p.reload();self.ready();self.nav("products");expect(p.locator("#product-view")).to_have_value("cards")
        f=p.locator("#recipe-form")
        f.locator('[name=product]').fill("Браслет");f.locator('[name=material]').fill("Бусины");f.locator('[name=usage_quantity]').click()
        expect(f.locator('[name=unit]')).to_have_value("шт");expect(f.locator('[name=pack_quantity]')).to_have_value("400")
        expect(f.locator('[name=pack_price]')).to_have_value("800.00")
        expect(p.locator("#recipe-status")).to_contain_text("4.000000")
        f.locator('[name=usage_quantity]').fill("12")
        f.get_by_role("button",name="Сохранить",exact=True).click();expect(p.locator("#recipe-status")).to_have_text("Сохранено.")
        data=self.report();item=next(x for x in data["products"] if x["id"]==a)
        self.assertEqual(item["estimated_material_cost_rub"],"48.00")
        self.nav("materials");p.locator("#material-view").select_option("cards");expect(p.locator("#materials .catalog-cards article")).to_have_count(2)
        p.reload();self.ready();self.nav("materials");expect(p.locator("#material-view")).to_have_value("cards")

    def test_09_product_card_photo_edit_and_archive(self):
        self.sign_in();m,n,a,b,c=self.seed();p=self.page
        self.nav("products")
        row=p.locator("#products tbody tr").filter(has_text="Браслет");row.get_by_role("button",name="Карточка",exact=True).click()
        expect(p.locator("#product-detail-title")).to_have_text("Браслет")
        expect(p.locator("#product-detail-body")).to_contain_text("20.00")
        img=io.BytesIO();Image.new("RGB",(32,24),"green").save(img,"PNG")
        p.locator("#product-photo-form input").set_input_files({"name":"sample.png","mimeType":"image/png","buffer":img.getvalue()})
        p.locator("#product-photo-form").get_by_role("button",name="Загрузить фото").click()
        expect(p.locator("#product-detail-body img")).to_be_visible();self.assertTrue(p.locator("#product-detail-body img").evaluate("e=>e.complete&&e.naturalWidth>0"))
        p.locator("#product-photo-delete").click();expect(p.locator("#product-detail-body img")).to_have_count(0)
        p.locator("#product-edit").click();self.fill({"name":"Браслет новый","sale_price":"350"});self.confirm()
        expect(p.locator("#products")).to_contain_text("Браслет новый")
        for id in (b,c):p.locator('input[data-catalog-kind="product"][value="'+id+'"]').check()
        p.locator("#bulk-products").click();self.confirm("Обработано объектов: 2")
        expect(p.locator("#products tbody tr")).to_have_count(1)
        p.locator("#show-archived").check();expect(p.locator("#products tbody tr")).to_have_count(3)
        row=p.locator("#products tbody tr").filter(has_text="Свеча")
        row.get_by_role("button",name="Восстановить",exact=True).click();self.confirm()
        p.locator("#show-archived").uncheck();expect(p.locator("#products tbody tr")).to_have_count(2)

    def test_10_finance_charts_distribution_rank_and_periods(self):
        self.sign_in();p=self.page
        m=self.op("material",name="Нить",unit="шт",pack=100,pack_price="200")["id"]
        a=self.op("product",name="Высокая маржа")["id"];b=self.op("product",name="Низкая маржа")["id"]
        self.op("recipe_line",product=a,material=m,usage=1);self.op("recipe_line",product=b,material=m,usage=20)
        prev=(self.day.replace(day=1)-timedelta(days=1)).isoformat()
        self.op("opening",material=m,quantity=100,total="200",day=prev)
        self.op("sale",product=a,quantity=2,unit_price="100",paid_amount="200",auto_produce=True,day=prev)
        self.op("sale",product=b,quantity=1,unit_price="30",paid_amount="30",auto_produce=True)
        self.op("expense",category="Реклама",total="6")
        d=self.nav("finance")
        self.metric("finance","revenue","230.00 ₽");self.metric("finance","net_profit","180.00 ₽")
        rows=p.locator("#finance-chart .bar-line").all_text_contents()
        self.assertEqual(len(rows),4);self.assertTrue(any("196.00" in r for r in rows));self.assertTrue(any("-16.00" in r for r in rows))
        neg=p.locator("#finance-chart .bar-fill.negative");expect(neg).to_have_count(1)
        self.assertGreater(float(neg.evaluate("e=>e.style.width.replace('%','')")),0)
        distribution=p.locator("#distribution-table tbody tr td:nth-child(2)").all_text_contents()
        self.assertEqual(sum(Decimal(x) for x in distribution),Decimal("230"))
        self.assertIn("Высокая маржа",self.rows("#finance-products")[0]);self.assertIn("Низкая маржа",self.rows("#finance-products")[1])
        p.locator("#period-preset").select_option("previous")
        self.metric("finance","revenue","200.00 ₽");expect(p.locator("#finance-chart .bar-line")).to_have_count(2)
        p.locator("#period-preset").select_option("month")
        self.metric("finance","revenue","30.00 ₽")
        p.locator("#period-preset").select_option("year");expect(p.locator("#period-from")).to_have_value(self.day.replace(month=1,day=1).isoformat())
        p.locator("#period-clear").click();self.metric("finance","revenue","230.00 ₽")
        expect(p.locator("#period-preset")).to_have_value("all")

    def test_11_task_filters_all_categories_reminders(self):
        self.sign_in();p=self.page
        categories=["Заказ","Закупка","Звонок","Доставка","Изготовление","Маркетплейс","Личное","Прочее"]
        for i,c in enumerate(categories):
            self.open_op("tasks","task",{"name":"Задача "+str(i),"due":(self.day+timedelta(days=2)).isoformat(),"remind_days":2,"task_category":c,"priority":"Высокая"});self.confirm()
        expect(p.locator("#tasks-list tbody tr")).to_have_count(8)
        expect(p.locator("#tasks-reminders tbody tr")).to_have_count(8)
        row=p.locator("#tasks-list tbody tr").filter(has_text="Задача 0");row.get_by_role("button",name="Выполнено",exact=True).click();self.confirm()
        expect(p.locator("#tasks-list tbody tr")).to_have_count(7)
        p.locator("#task-filter").select_option("done");expect(p.locator("#tasks-list tbody tr")).to_have_count(1)
        row.get_by_role("button",name="Возобновить",exact=True).click();self.confirm()
        expect(p.locator("#tasks-list")).to_have_text("Нет записей")
        p.locator("#task-filter").select_option("active");row.get_by_role("button",name="В архив",exact=True).click();self.confirm()
        p.locator("#task-filter").select_option("archived");expect(row).to_be_visible()
        row.get_by_role("button",name="Возобновить",exact=True).click();self.confirm()
        p.locator("#task-filter").select_option("all");expect(p.locator("#tasks-list tbody tr")).to_have_count(8)

    def test_12_local_integration_clipboard_rotation_and_mapping(self):
        self.sign_in();p=self.page
        m,n,a,b,c=self.seed();self.nav("integrations")
        p.locator("#source-create [name=name]").fill("Учебный источник")
        p.locator("#source-create [name=auto_produce]").check();p.locator("#source-create button:not([type=button])").click()
        expect(p.locator("#source-key-box")).to_be_visible();key=p.locator("#source-key").inner_text()
        p.locator("#source-copy").click();expect(p.locator("#source-status")).to_have_text("Ключ скопирован.")
        self.assertTrue(p.evaluate("(k)=>navigator.clipboard.readText().then(s=>s===k)",key))
        p.locator("#source-hide").click();expect(p.locator("#source-key")).to_be_empty()
        card=p.locator("#sources-list .settings-card").first
        card.get_by_role("button",name="Копировать адрес API").click();expect(p.locator("#source-status")).to_have_text("Адрес скопирован.")
        self.assertEqual(p.evaluate("navigator.clipboard.readText()"),self.origin+"/api/hook/order")
        order={"order_ref":"order-fixture","date":self.day.isoformat(),"shop_name":"Учебный источник","items":[{"offer_id":"sku1","name":"Браслет","price":"300","qty":1}]}
        h={"Authorization":"Bearer "+key}
        self.call("/api/hook/order",order,headers=h,workshop=False)
        self.call("/api/hook/order",order,headers=h,workshop=False)
        self.nav("summary");self.nav("integrations")
        row=card.locator("tbody tr").filter(has_text="sku1")
        row.locator("select").select_option(a);row.get_by_role("button",name="Связать",exact=True).click()
        expect(card).to_contain_text("Учтён");self.assertEqual(self.report()["summary"]["revenue"],"300.00")
        ret={"event_id":"return-1","order_ref":"order-fixture","line":0,"kind":"return","date":self.day.isoformat(),"quantity":1,"refund":"300","restock":True}
        self.call("/api/hook/event",ret,headers=h,workshop=False)
        self.call("/api/hook/event",ret,headers=h,workshop=False)
        self.assertEqual(self.report()["summary"]["revenue"],"0.00")
        card.get_by_role("button",name="Перевыпустить ключ").click();expect(p.locator("#source-key-box")).to_be_visible()
        new=p.locator("#source-key").inner_text();self.assertNotEqual(new,key)
        self.call("/api/hook/order",order,headers=h,expected=401,workshop=False)
        p.locator("#source-hide").click();card.get_by_role("button",name="Отключить",exact=True).click()
        expect(card).to_contain_text("отключён")
        self.call("/api/hook/order",order,headers={"Authorization":"Bearer "+new},expected=401,workshop=False)
        card.get_by_role("button",name="Включить",exact=True).click();expect(card).to_contain_text("подключён")

    def test_13_exports_and_template_downloads(self):
        self.sign_in();p=self.page;m,n,a,b,c=self.seed()
        self.op("expense",category="Прочее",total="12.34",note="=1+1")
        self.nav("materials")
        with p.expect_download() as dl:p.get_by_role("link",name="Скачать шаблон CSV").click()
        self.assertIn("name",dl.value.path().read_text(encoding="utf-8-sig"))
        self.nav("finance")
        for label,kind in [("Выгрузить весь учёт XLSX","xlsx"),("Журнал CSV","csv"),("Весь учёт CSV (ZIP)","zip")]:
            with p.expect_download() as dl:p.get_by_role("link",name=label,exact=True).click()
            path=dl.value.path()
            if kind=="xlsx":
                wb=load_workbook(io.BytesIO(path.read_bytes()));self.assertEqual(len(wb.sheetnames),19);self.assertIn("Бусины",str(list(wb["Сырьё"].values)))
            elif kind=="csv":self.assertIn("12.34",path.read_text(encoding="utf-8-sig"))
            else:
                with zipfile.ZipFile(path) as z:self.assertEqual(len(z.namelist()),19)

    def test_14_assistant_highlight_and_navigation(self):
        self.sign_in();p=self.page;m,n,a,b,c=self.seed()
        self.op("sale",product=a,quantity=1,unit_price="300",paid_amount="300",auto_produce=True)
        self.op("sale_fee",sale=self.report()["sales"][0]["id"],total="30",category="Комиссия")
        for phrase,section,key,value in [
            ("покажи чистую прибыль за этот месяц","finance","net_profit","250.00 ₽"),
            ("сколько изделий продано","sales","sales_quantity","1"),
            ("сколько удержаний по продажам","sales","sale_fees","30.00 ₽"),
            ("стоимость незавершенного производства","stock","wip_inventory_rub","0.00 ₽"),
            ("остаточная стоимость оборудования","assets","equipment_book_rub","0.00 ₽")]:
            with self.subTest(phrase=phrase):
                ans=self.ask(phrase);self.assertEqual(ans["route"],"local")
                expect(p.locator('[data-panel="'+section+'"]')).to_be_visible()
                self.metric(section,key,value)
                expect(p.locator('[data-panel="'+section+'"] [data-metric="'+key+'"]')).to_have_class("metric highlight")
        self.ask("сколько бусин осталось");expect(p.locator("#stock-raw")).to_contain_text("90 шт")
        expect(p.locator("#stock-raw")).not_to_contain_text("Воск")
        self.ask("открой материалы");expect(p.locator('[data-panel="materials"]')).to_be_visible()
        self.ask("добавить оборудование");expect(p.locator("#book-dialog")).to_be_visible();p.locator("#book-close").click()
        expect(p.locator("#balance-label")).to_contain_text("10 монет")
        self.assertEqual(p.locator(".receipt").count(),0)
