"""Visual route/state acceptance. Uses only synthetic accounts and local mail."""
import base64
import time
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.twofactor.hotp import HOTP
from playwright.sync_api import expect
from platform_core.access_web import step_page,STEPS
from platform_core.access_bootstrap import assign
import test_podmasterye_independent_ui as previous

class LayoutUI(previous.IndependentUI):
    def shot(self,label,selector=None):
        p=self.page
        expect(p.locator('html')).to_have_attribute("data-theme",p.evaluate("localStorage.getItem('pm-theme')") or "light")
        if selector:expect(p.locator(selector)).to_be_visible()
        width=p.viewport_size["width"]
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),width+1,label)
        if selector:
            b=p.locator(selector).bounding_box()
            self.assertIsNotNone(b)
            self.assertGreaterEqual(b["x"],-1,label)
            self.assertLessEqual(b["x"]+b["width"],width+1,label)
        p.screenshot(path=str(self.evidence/(label+".png")),animations="disabled")
    def set_mode(self,mode,width):
        self.page.set_viewport_size({"width":width,"height":900 if width>800 else 844})
        self.page.evaluate("(mode)=>window.PMTheme.set(mode)",mode)
    def card(self,label):
        p=self.page
        for width,mode in ((1440,"light"),(1440,"dark"),(390,"light"),(390,"dark"),(320,"dark")):
            self.set_mode(mode,width)
            expect(p.locator(".pm-auth-card")).to_be_visible()
            b=p.locator(".pm-auth-card").bounding_box()
            self.assertLessEqual(b["width"],425)
            self.assertAlmostEqual(b["x"]+b["width"]/2,width/2,delta=3)
            for field in p.locator(".pm-auth-card input:not([type=checkbox]):visible, .pm-auth-card form button:visible").all():
                f=field.bounding_box()
                self.assertGreaterEqual(f["x"],b["x"]+10)
                self.assertLessEqual(f["x"]+f["width"],b["x"]+b["width"]-10+1)
                self.assertGreaterEqual(f["height"],40)
            self.shot(f"{label}-{width}-{mode}",".pm-auth-card")
    def test_layout_public(self):
        p=self.page
        for path,label,selector in (("/","home",".landing"),("/kalkulyator","calculator",".calc-page"),("/calculator","calculator-alias",".calc-page"),("/faq","faq",".calc-page"),("/privacy","privacy",".calc-page")):
            self.assertEqual(p.goto(path).status,200)
            if p.locator("#cookie-choice").is_visible():p.locator("#cookie-decline").click()
            for width,mode in ((1440,"light"),(1440,"dark"),(390,"light"),(390,"dark"),(320,"dark")):
                self.set_mode(mode,width);self.shot(f"{label}-{width}-{mode}",selector)
        p.goto("/login");self.card("login")
        p.goto("/register");self.card("register")
        r=p.goto("/nonexistent-page");self.assertEqual(r.status,404);self.card("not-found")
        r=p.goto("/admin/statistics");self.assertEqual(r.status,401);self.card("admin-unauth")
        # The actual payment route displays a same-origin return document before redirecting.
        # Pause only the redirect script in the browser to inspect this intermediate screen.
        p.route("**/ui-assets/project/payment-return.js",lambda route:route.fulfill(status=200,content_type="text/javascript",body=""))
        self.assertEqual(p.goto("/payment/return").status,200);self.card("payment-return")
        p.unroute("**/ui-assets/project/payment-return.js")
        p.goto("/payment/return");expect(p).to_have_url(self.origin+"/?account=wallet&resume=1")
    def test_layout_auth_states(self):
        p=self.page
        # These are isolated presentation fixtures, not manufactured sessions or credentials.
        for stage in [*STEPS,None]:
            detail={"stage":stage,"setup_key":"EXAMPLEKEYFORLAYOUTONLY000000000000"} if stage else None
            for invalid in (False,True):
                result=step_page(None,detail,error="Проверьте введённые данные." if invalid else "",status=400 if invalid else 200)
                path="/__layout_fixture"
                def respond(route):
                    route.fulfill(status=result.status_code,headers=dict(result.headers),body=result.body)
                p.route("**"+path,respond)
                p.goto(path);self.card("verify-"+str(stage)+("-error" if invalid else ""))
                p.unroute("**"+path)
        # Actual registration, invalid and valid one-time code, and logout, on synthetic mail.
        self.set_mode("dark",1440)
        p.goto("/register");name="visual_"+uuid4().hex[:10];address=name+"@example.test"
        p.get_by_label("Логин",exact=True).fill(name);p.get_by_label("Почта",exact=True).fill(address);p.get_by_label("Пароль",exact=True).fill(previous.P)
        p.get_by_role("button",name="Создать аккаунт",exact=True).click()
        expect(p.get_by_role("heading",name="Проверьте почту")).to_be_visible();self.card("actual-email")
        code=self.inbox[address];bad="000000" if code!="000000" else "111111"
        p.get_by_label("Код из письма",exact=True).fill(bad);p.get_by_role("button",name="Продолжить").click()
        expect(p.get_by_role("alert")).to_be_visible();self.card("actual-email-error")
        p.get_by_label("Код из письма",exact=True).fill(code);p.get_by_role("button",name="Продолжить").click();self.ready()
        self.set_mode("light",1440);p.get_by_role("button",name="Выйти",exact=True).click()
        expect(p).to_have_url(self.origin+"/login")
        expect(p.locator(".pm-auth-card")).to_be_visible()
        p.wait_for_load_state("domcontentloaded");self.card("actual-logout")
    def test_layout_admin_enrollment_and_statistics(self):
        p=self.page
        # Create a synthetic admin and exercise the normal email+TOTP enrollment.
        login="admin_visual_"+uuid4().hex[:10];address=login+"@example.test"
        store=self.app.state.identity;store.create_account(login,previous.P);store.set_admin(login,True)
        with store._write() as db:assign(db,login,address)
        p.goto("/login");p.get_by_label("Логин",exact=True).fill(login);p.get_by_label("Пароль",exact=True).fill(previous.P)
        p.get_by_role("button",name="Войти",exact=True).click()
        expect(p.get_by_role("heading",name="Проверьте почту")).to_be_visible()
        self.card("admin-email")
        p.get_by_label("Код из письма",exact=True).fill(self.inbox[address]);p.get_by_role("button",name="Продолжить").click()
        expect(p.get_by_role("heading",name="Подключите приложение")).to_be_visible()
        self.card("admin-setup")
        # Never use real credentials; the key is issued to this temporary test account.
        seed=p.locator(".auth-key").inner_text()
        code=HOTP(base64.b32decode(seed),6,SHA1()).generate(int(time.time())//30).decode()
        p.get_by_label("Код из приложения",exact=True).fill(code);p.get_by_role("button",name="Продолжить").click()
        self.ready();self.set_mode("light",1440)
        self.nav("admin")
        for width,mode in ((1440,"light"),(1440,"dark"),(390,"dark")):
            self.set_mode(mode,width);self.shot(f"admin-panel-{width}-{mode}",'[data-panel=admin]')
        self.assertEqual(p.goto("/admin/statistics").status,200)
        expect(p.get_by_role("heading",name="Статистика",exact=True)).to_be_visible()
        for width,mode in ((1440,"light"),(1440,"dark"),(390,"light"),(390,"dark"),(320,"dark")):
            self.set_mode(mode,width);self.shot(f"admin-stats-{width}-{mode}",".pm-admin-main")
        self.set_mode("light",1440)
        p.get_by_label("Поиск по логину").fill("nonexistent-fixture")
        p.get_by_role("button",name="Показать",exact=True).click();expect(p.locator(".stats-table").first).to_contain_text("Пользователи не найдены")
        self.assertFalse(p.get_by_role("button",name="Удалить выбранные").count())
    def test_layout_all_member_tabs_and_checkout(self):
        self.sign_in();p=self.page
        # Populate with the same deterministic demonstration data used in the product.
        self.nav("settings");p.locator("#workshop-demo").click();expect(p.locator("#workshop-caption")).to_contain_text("Демонстрационная");self.ready()
        self.set_mode("light",1440)
        sections=p.locator("nav button[data-page]").evaluate_all("els=>els.map(e=>e.dataset.page)")
        self.assertEqual(len(sections),18)
        for sec in sections:
            self.set_mode("light",1440);self.nav(sec);self.shot("member-"+sec+"-1440-light",'[data-panel="'+sec+'"]')
            self.set_mode("dark",1440);self.shot("member-"+sec+"-1440-dark",'[data-panel="'+sec+'"]')
            self.set_mode("dark",390);self.shot("member-"+sec+"-390-dark",'[data-panel="'+sec+'"]')
            self.set_mode("light",390);self.shot("member-"+sec+"-390-light",'[data-panel="'+sec+'"]')
        self.set_mode("dark",1440);self.nav("wallet");p.locator('[data-panel=wallet] [data-buy-coins]').click()
        dlg=p.locator("dialog.octo-checkout");expect(dlg).to_be_visible()
        expect(dlg.locator("output")).not_to_have_text("—")
        for width,mode in ((1440,"light"),(1440,"dark"),(390,"light"),(390,"dark"),(320,"dark")):
            self.set_mode(mode,width);self.shot(f"checkout-{width}-{mode}","dialog.octo-checkout")
        expect(dlg.get_by_role("button",name="Перейти к оплате")).to_be_disabled()
        dlg.get_by_role("button",name="Закрыть окно").click();expect(dlg).not_to_be_visible()
        # Verify permission-error presentation for a normal account.
        self.assertEqual(p.goto("/admin/statistics").status,403);self.card("admin-forbidden")
