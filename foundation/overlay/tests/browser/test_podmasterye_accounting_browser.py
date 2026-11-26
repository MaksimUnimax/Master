"""Browser acceptance on loopback only. No production credentials or provider calls."""
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import uvicorn
from playwright.sync_api import sync_playwright, expect
from platform_core.chat_api import create_app
from platform_core.guest_registration import RegistrationStore
from platform_core.account_access import AccountAccess
from tests.auth_fixture import email_opted_out

P="fixture-browser-password"
class AccountingBrowser(unittest.TestCase):
    def test_accounting_workflow(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ,{"HARNESS_OFFLINE_MODEL":"0","HARNESS_USAGE_JOURNAL":str(root/"usage.jsonl")}))
        os.environ.pop("HARNESS_MODEL_GATEWAY_URL",None)
        db=root/"test.sqlite3"
        with RegistrationStore(db) as store:
            AccountAccess(store)
            store.create_account("owner",P);email_opted_out(store,"owner")
            store.create_account("administrator",P);store.set_admin("administrator",True)
            token=store.login("administrator",P)
        sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(64)
        origin="http://127.0.0.1:"+str(sock.getsockname()[1])
        app=create_app(db,root/"chats")
        server=uvicorn.Server(uvicorn.Config(app,log_level="warning",access_log=False))
        thread=threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True);thread.start()
        def stop():
            server.should_exit=True;thread.join(timeout=10);sock.close()
        self.addCleanup(stop)
        deadline=time.monotonic()+10
        while not server.started:
            self.assertLess(time.monotonic(),deadline);time.sleep(.05)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            ctx=browser.new_context(accept_downloads=True,viewport={"width":1440,"height":1000},locale="ru-RU")
            page=ctx.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(origin+"/login")
            page.get_by_label("Логин",exact=True).fill("owner")
            page.get_by_label("Пароль",exact=True).fill(P)
            page.get_by_role("button",name="Войти",exact=True).click()
            expect(page.locator("body")).to_have_attribute("data-mode","member")
            expect(page.locator("#assistant-form button")).to_be_enabled()
            expect(page.locator("#balance-label")).to_contain_text("10 монет")
            def ask(text):
                page.locator("#assistant-form textarea").fill(text)
                with page.expect_response(lambda r:"/turns" in r.url and r.request.method=="POST") as got:
                    page.locator("#assistant-form button").click()
                self.assertEqual(got.value.status,200,got.value.text())
                expect(page.locator("#assistant-status")).to_have_text("")
                return got.value.json()
            def nav(section):
                with page.expect_response(lambda r:"/api/accounting?" in r.url) as got:
                    page.locator('nav button[data-page="'+section+'"]').click()
                self.assertEqual(got.value.status,200)
                expect(page.locator('[data-panel="'+section+'"]')).to_be_visible()
            def write(section,op,values,expect_summary):
                nav(section)
                page.locator('[data-book-op="'+op+'"]').click()
                dlg=page.locator("#book-dialog")
                expect(dlg).to_be_visible()
                for name,value in values.items():
                    el=dlg.locator('[name="'+name+'"]')
                    if isinstance(value,bool):el.set_checked(value)
                    elif name in ("material","product","sale","category","purchase_unit","entity_id","unit"):
                        if value=="__first__":el.select_option(index=1)
                        else:el.select_option(value=str(value))
                    else:el.fill(str(value))
                dlg.locator("#book-check").click()
                expect(dlg.locator("#book-preview")).to_contain_text(expect_summary)
                expect(dlg.locator("#book-confirm")).to_be_enabled()
                with page.expect_response(lambda r:"/api/accounting/commit" in r.url) as got:
                    dlg.locator("#book-confirm").click()
                self.assertEqual(got.value.status,200,got.value.text())
                expect(dlg).not_to_be_visible()
                expect(page.locator("#accounting-status")).to_contain_text(expect_summary)
                return got.value.json()
            answer=ask("Добавь бусины пачками по 400 штук, на браслет уходит 40 штук, упаковка стоит 800 рублей")
            self.assertEqual(answer["route"],"local")
            expect(page.locator("#products")).to_contain_text("браслет")
            write("purchases","purchase",{"material":"__first__","quantity":2,"total":"1600","supplier":"Тест"},"1600.00")
            write("manufacture","manufacture",{"product":"__first__","quantity":3},"240.00")
            sale=write("sales","sale",{"product":"__first__","quantity":4,"unit_price":"300","paid_amount":"1200","auto_produce":True},"320.00")
            write("expenses","expense",{"category":"Реклама","total":"100"},"100.00")
            a=ask("покажи чистую прибыль за этот месяц")
            self.assertIn("780.00",a["text"])
            expect(page.locator('[data-panel="finance"] [data-metric="net_profit"]')).to_contain_text("780.00")
            expect(page.locator('[data-panel="finance"] [data-metric="net_profit"]')).to_have_class("metric highlight")
            a=ask("сколько бусин осталось")
            self.assertIn("640",a["text"])
            expect(page.locator("#stock-raw")).to_contain_text("640 шт")
            expect(page.locator("#catalog-filter")).to_have_value("бусины")
            page.locator("#catalog-filter").fill("")
            nav("sales")
            page.locator("#sales-current").get_by_role("button",name="Возврат",exact=True).click()
            dlg=page.locator("#book-dialog")
            dlg.locator('[name="quantity"]').fill("1")
            dlg.locator('[name="refund"]').fill("300")
            dlg.locator('[name="restock"]').check()
            dlg.locator("#book-check").click();expect(dlg.locator("#book-preview")).to_contain_text("300.00")
            dlg.locator("#book-confirm").click();expect(dlg).not_to_be_visible()
            nav("finance")
            expect(page.locator('[data-panel="finance"] [data-metric="net_profit"]')).to_contain_text("560.00")
            with page.expect_download() as download:page.get_by_role("link",name="Выгрузить весь учёт XLSX").click()
            self.assertEqual(download.value.suggested_filename,"podmasterye-accounting.xlsx")
            self.assertTrue(download.value.path().stat().st_size>0)
            self.assertEqual(page.locator(".receipt").count(),0)
            expect(page.locator("#balance-label")).to_contain_text("10 монет")
            out=os.getenv("PODMASTER_BROWSER_EVIDENCE")
            if out:page.screenshot(path=str(Path(out)/"accounting-finance.png"),full_page=True)
            admin_ctx=browser.new_context();admin_ctx.add_cookies([{"name":"podmaster_local_session","value":token,"url":origin,"httpOnly":True,"sameSite":"Strict"}])
            admin=admin_ctx.new_page();admin.on("pageerror",lambda e:errors.append(str(e)))
            admin.goto(origin+"/app/")
            expect(admin.locator("body")).to_have_attribute("data-admin","1")
            expect(admin.locator("#assistant-form button")).to_be_enabled()
            admin.locator("#assistant-form textarea").fill("как считается прибыль")
            admin.locator("#assistant-form button").click()
            expect(admin.locator(".receipt").last).to_contain_text("0 ₽")
            self.assertFalse((root/"usage.jsonl").exists())
            self.assertEqual(errors,[])
            admin_ctx.close();ctx.close()
