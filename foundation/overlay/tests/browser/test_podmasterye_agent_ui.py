"""Browser acceptance of the agent form flow with the native local gateway."""
import os,socket,subprocess,tempfile,threading,time,selectors,unittest
from pathlib import Path
from unittest.mock import patch
import uvicorn
from playwright.sync_api import sync_playwright,expect
from platform_core.chat_api import create_app
from platform_core.guest_registration import RegistrationStore
from platform_core.account_access import AccountAccess
from platform_core.operation_grants import initialize_grants
from tests.auth_fixture import email_opted_out

class AgentUI(unittest.TestCase):
    def test_partial_form_and_followup(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        db=root/"test.sqlite3";journal=root/"usage.jsonl"
        self.enterContext(patch.dict(os.environ,{"HARNESS_RUB_PER_USD":"80","HARNESS_USAGE_JOURNAL":str(journal),"HARNESS_CHAT_MODEL":"deepseek-flash","HARNESS_OFFLINE_MODEL":"0"}))
        password="fixture-browser-password"
        with RegistrationStore(db) as store:
            AccountAccess(store);store.create_account("fixture-owner",password);email_opted_out(store,"fixture-owner")
        initialize_grants(db)
        gw=subprocess.Popen(["node",str(Path(__file__).resolve().parents[1]/"podmasterye_gateway.mjs"),str(db),str(journal)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        def stop_gateway():
            gw.stdin.close()
            try:gw.wait(timeout=5)
            except subprocess.TimeoutExpired:gw.kill();gw.wait()
            gw.stdout.close()
        self.addCleanup(stop_gateway)
        with selectors.DefaultSelector() as ready:
            ready.register(gw.stdout,selectors.EVENT_READ);self.assertTrue(ready.select(8))
        os.environ["HARNESS_MODEL_GATEWAY_URL"]=gw.stdout.readline().strip()
        sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(64)
        origin="http://127.0.0.1:"+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(create_app(db,root/"chats"),log_level="warning",access_log=False))
        thread=threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True);thread.start()
        def stop_server():
            server.should_exit=True;thread.join(timeout=10);sock.close()
        self.addCleanup(stop_server)
        deadline=time.monotonic()+10
        while not server.started:
            self.assertLess(time.monotonic(),deadline);time.sleep(.05)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            page=browser.new_page(viewport={"width":1440,"height":1000})
            errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(origin+"/login");page.get_by_label("Логин",exact=True).fill("fixture-owner")
            page.get_by_label("Пароль",exact=True).fill(password);page.get_by_role("button",name="Войти",exact=True).click()
            expect(page.locator("#assistant-form button")).to_be_enabled(timeout=10000)
            def ask(text):
                page.locator("#assistant-form textarea").fill(text)
                with page.expect_response(lambda r:"/turns" in r.url and r.request.method=="POST",timeout=45000) as got:
                    page.locator("#assistant-form button").click()
                self.assertEqual(got.value.status,200,got.value.text())
                expect(page.locator("#assistant-status")).to_have_text("",timeout=15000)
                return got.value.json()
            ask("Добавь бусины пачками по 400 штук, на браслет уходит 40 штук, упаковка стоит 800 рублей")
            page.locator("#recipe-form").get_by_role("button",name="Сохранить",exact=True).click()
            expect(page.locator("#recipe-status")).to_have_text("Сохранено.")
            first=ask("Тест частичной закупки: подготовь форму")
            expect(page.locator("#book-dialog")).to_be_visible()
            expect(page.locator('#book-fields [name=quantity]')).to_have_value("2")
            expect(page.locator('#book-fields [name=total]')).to_have_value("")
            expect(page.locator("#book-confirm")).to_be_disabled()
            page.locator("#book-assist").click()
            expect(page.locator("#book-dialog")).not_to_be_visible()
            second=ask("Тест дополнения закупки")
            expect(page.locator("#book-dialog")).to_be_visible()
            expect(page.locator('#book-fields [name=quantity]')).to_have_value("2")
            expect(page.locator('#book-fields [name=total]')).to_have_value("1600.00")
            expect(page.locator("#book-confirm")).to_be_enabled()
            page.locator("#book-confirm").click()
            expect(page.locator("#book-dialog")).not_to_be_visible()
            ask("Тест заполнения мастерской")
            expect(page.locator('#workshop-create [name=name]')).to_have_value("Новая мастерская")
            expect(page.locator('#workshop-create [name=description]')).to_have_value("Проверка")
            self.assertFalse(errors,errors)
            self.assertTrue(journal.exists())
            browser.close()
