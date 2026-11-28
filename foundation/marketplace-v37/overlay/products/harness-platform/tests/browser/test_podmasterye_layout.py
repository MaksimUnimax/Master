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
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),width+1,label)
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
            self.assertLessEqual(b["width"],385 if p.locator('body[data-mode="public"]').count() else 340.5)
            if p.locator('body[data-mode="public"]').count():
                pane=p.locator("#public-info-pane").bounding_box()
                self.assertGreaterEqual(b["x"],pane["x"]-1)
                self.assertLessEqual(b["x"]+b["width"],pane["x"]+pane["width"]+1)
            else:self.assertAlmostEqual(b["x"]+b["width"]/2,width/2,delta=3)
            for field in p.locator(".pm-auth-card input:not([type=checkbox]):visible, .pm-auth-card form button:visible").all():
                f=field.bounding_box()
                self.assertGreaterEqual(f["x"],b["x"]+8)
                self.assertLessEqual(f["x"]+f["width"],b["x"]+b["width"]-8+1)
                self.assertGreaterEqual(f["height"],32)
            self.shot(f"{label}-{width}-{mode}",".pm-auth-card")
    def test_layout_public(self):
        p=self.page
        for path,label,selector in (("/","home","#public-info-pane"),("/kalkulyator","calculator",".calc-page"),("/calculator","calculator-alias",".calc-page"),("/faq","faq","#public-info-pane"),("/privacy","privacy","#public-info-pane")):
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
        self.assertEqual(p.goto("/admin/matrix").status,200)
        expect(p.locator("#matrix-status")).to_contain_text("agent-first-v15")
        f=p.locator("#matrix-edit-form")
        f.locator("[name=id]").select_option("A-R01")
        f.locator("[name=aliases]").fill("покажи хозяйственный итог")
        f.locator("[name=negatives]").fill("до налога")
        f.get_by_role("button",name="Сохранить изменения").click()
        expect(p.locator("#matrix-status")).to_contain_text("изменения сохранены")
        p.goto("/app/");self.ready()
        r=self.ask("покажи хозяйственный итог")
        self.assertEqual(r["matrixId"],"A-R01")
        r=self.ask("а за вчера")
        self.assertEqual(r["filterReason"],"view_context")
        self.assertEqual(p.goto("/admin/matrix").status,200)
        expect(p.locator("#matrix-stats")).to_contain_text("Без LLM")
        expect(p.locator("#matrix-status")).to_contain_text("agent-first-v15")
        f.locator("[name=id]").select_option("A-R01")
        expect(f.locator("[name=aliases]")).to_have_value("покажи хозяйственный итог")
        p.locator("#matrix-reset").click()
        f.get_by_role("button",name="Сохранить изменения").click()
        expect(p.locator("#matrix-status")).to_contain_text("изменения сохранены")
        for path in ("","keys","models","telegram","coins","usage","matrix","statistics","visits"):
            url="/admin"+("/"+path if path else "")
            self.assertEqual(p.goto(url).status,200,url)
            expect(p.locator(".pm-admin-sidebar nav a[aria-current=page]")).to_have_attribute("href",url)
            self.assertNotIn("OpenRouter",p.locator("body").inner_text())
            self.assertEqual(p.evaluate("getComputedStyle(document.documentElement).zoom"),"0.8")
            for width in (1440,1920):
                p.set_viewport_size({"width":width,"height":900})
                rect=p.evaluate("""()=>{const nav=document.querySelector('.pm-admin-sidebar').getBoundingClientRect();const main=document.querySelector('.pm-admin-main').getBoundingClientRect();const h=document.querySelector('.pm-admin-main h1').getBoundingClientRect();return {navRight:nav.right,mainLeft:main.left,hLeft:h.left,hTop:h.top,mainWidth:main.width}}""")
                self.assertAlmostEqual(rect["mainLeft"],rect["navRight"],delta=2,msg=(url,rect))
                self.assertGreaterEqual(rect["hLeft"]-rect["navRight"],12)
                self.assertLessEqual(rect["hLeft"]-rect["navRight"],17)
                self.assertLessEqual(rect["hTop"],45)
                maximum=1320 if path in ("usage","matrix","statistics") else 1060 if path=="visits" else 740
                self.assertLessEqual(rect["mainWidth"],maximum*.8+2)
            for width,mode in ((1440,"light"),(1440,"dark"),(390,"dark"),(320,"light")):
                self.set_mode(mode,width);self.shot("admin-"+(path or "overview")+"-"+str(width)+"-"+mode,".pm-admin-main")
            self.set_mode("light",1440)
        self.assertEqual(p.goto("/admin").status,200)
        expect(p.locator("#balance-deepseek-status")).to_contain_text("API-ключ не настроен")
        expect(p.locator("#guest-coverage")).not_to_have_text("")
        self.assertEqual(p.goto("/admin/keys").status,200)
        expect(p.locator("#ai-provider-status")).to_contain_text("не добавлен")
        self.assertEqual(p.goto("/admin/visits").status,200)
        expect(p.locator(".pm-admin-main")).to_contain_text("Счётчик не подключён")
        self.assertEqual(p.goto("/admin/statistics").status,200)
        expect(p.get_by_role("heading",name="Статистика",exact=True)).to_be_visible()
        for width,mode in ((1440,"light"),(1440,"dark"),(390,"light"),(390,"dark"),(320,"dark")):
            self.set_mode(mode,width);self.shot(f"admin-stats-{width}-{mode}",".pm-admin-main")
        self.set_mode("light",1440)
        p.get_by_label("Поиск по логину").fill("nonexistent-fixture")
        p.get_by_role("button",name="Показать",exact=True).click();expect(p.locator(".stats-table").first).to_contain_text("Пользователи не найдены")
        self.assertFalse(p.get_by_role("button",name="Удалить выбранные").count())
    def test_layout_all_member_tabs_and_checkout(self):
        from unittest.mock import patch
        import os
        self.enterContext(patch.dict(os.environ,{"PODMASTERYE_MULTI_WORKSHOP":"1"}))
        self.sign_in();p=self.page
        # Populate with the same deterministic demonstration data used in the product.
        self.nav("settings");p.locator("#workshop-demo").click();expect(p.locator("#workshop-caption")).to_contain_text("Демонстрационная");self.ready()
        self.set_mode("light",1440)
        sections=p.locator("nav button[data-page]").evaluate_all("els=>els.map(e=>e.dataset.page)")
        self.assertEqual(len(sections),18)
        for sec in sections:
            self.set_mode("light",1440);self.nav(sec);self.shot("member-"+sec+"-1440-light",'[data-panel="'+sec+'"]')
            self.set_mode("dark",1440);self.shot("member-"+sec+"-1440-dark",'[data-panel="'+sec+'"]')
            self.set_mode("dark",390)
            if not p.locator(".layout>nav").is_visible():
                p.locator("#toggle-nav").click()
            p.locator('nav button[data-page="'+sec+'"]').click()
            expect(p.locator(".layout>nav")).to_be_visible()
            self.shot("member-"+sec+"-390-dark",'[data-panel="'+sec+'"]')
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

    def test_layout_assistant_first(self):
        self.sign_in();p=self.page
        helper=p.locator("#assistant-pane");work=p.locator("#work-pane");nav=p.locator(".layout>nav")
        for width in (1440,1200,1024,961):
            self.set_mode("light",width)
            expect(helper).to_be_visible();expect(work).to_be_visible()
            self.assertEqual(p.evaluate("getComputedStyle(document.documentElement).zoom"),"0.8")
            self.assertAlmostEqual(p.locator(".layout").bounding_box()["y"]+p.locator(".layout").bounding_box()["height"],p.viewport_size["height"],delta=2)
            h=helper.bounding_box();w=work.bounding_box();n=nav.bounding_box()
            self.assertLessEqual(n["x"]+n["width"],h["x"]+1)
            self.assertLessEqual(h["x"]+h["width"],w["x"]+1)
            self.assertGreater(h["width"],w["width"])
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),width+1)
        self.set_mode("light",1440)
        expect(helper.get_by_role("heading",name="С чего начнём?")).to_be_visible()
        self.shot("assistant-first-desktop")
        result=self.ask("покажи чистую прибыль за этот месяц")
        self.assertEqual(result["route"],"local")
        expect(p.locator('[data-panel="finance"]')).to_be_visible()
        expect(p.locator('[data-panel="finance"] [data-metric="net_profit"]')).to_have_class("metric highlight")
        expect(helper).to_be_visible()
        history=p.locator("#messages").inner_text()
        width_before=work.bounding_box()["width"]
        expect(p.locator("#close-helper")).to_have_text("Свернуть")
        p.locator("#close-helper").click();expect(helper).not_to_be_visible()
        self.assertGreater(work.bounding_box()["width"],width_before+250)
        expect(p.locator("#toggle-helper")).to_have_attribute("aria-expanded","false")
        self.shot("assistant-first-collapsed")
        p.reload();self.ready();expect(helper).not_to_be_visible()
        expect(p.locator("#expand-work")).to_have_text("Помощник")
        p.locator("#expand-work").click();expect(helper).to_be_visible();expect(work).to_be_visible()
        expect(p.locator("#expand-work")).to_have_text("Свернуть")
        expect(p.locator("#messages")).to_have_text(history, use_inner_text=True)
        p.locator("#toggle-nav").click();expect(nav).not_to_be_visible()
        p.locator("#toggle-helper").click();expect(helper).not_to_be_visible()
        self.assertAlmostEqual(work.bounding_box()["width"],1440,delta=2)
        p.locator("#toggle-helper").click();expect(helper).to_be_visible()
        p.locator("#toggle-nav").click();expect(nav).to_be_visible()
        p.locator("#assistant-form textarea").fill("Черновик для проверки")
        expect(p.locator("#expand-work")).to_have_text("Свернуть")
        p.locator("#expand-work").click();expect(helper).to_be_visible();expect(work).not_to_be_visible()
        expect(p.locator("#close-helper")).to_have_text("Мастерская")
        expect(p.locator("#assistant-form textarea")).to_have_value("Черновик для проверки")
        p.reload();self.ready();expect(helper).to_be_visible();expect(work).not_to_be_visible()
        p.locator("#close-helper").click();expect(helper).to_be_visible();expect(work).to_be_visible()
        p.locator("#close-nav").click();expect(nav).not_to_be_visible();expect(helper).to_be_visible();expect(work).to_be_visible()
        p.locator("#toggle-nav").click();expect(nav).to_be_visible()
        # A fresh narrow-screen opening gives priority to the assistant.
        for width in (960,820,390,320):
            self.set_mode("dark",width);p.reload();self.ready()
            expect(helper).to_be_visible();expect(work).not_to_be_visible()
            self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),width+1)
            self.shot("assistant-first-mobile-"+str(width),"#assistant-pane")
            before=helper.bounding_box()
            p.locator("#toggle-nav").click();expect(nav).to_be_visible()
            n=nav.bounding_box();h=helper.bounding_box()
            self.assertGreater(h["x"],before["x"]+10)
            self.assertLessEqual(n["x"]+n["width"],h["x"]+1)
            p.locator('nav button[data-page="materials"]').click()
            expect(work).to_be_visible();expect(helper).not_to_be_visible();expect(nav).to_be_visible()
            n=nav.bounding_box();w=work.bounding_box()
            self.assertLessEqual(n["x"]+n["width"],w["x"]+1)
            expect(p.locator('[data-panel="materials"]')).to_be_visible()
            p.locator("#expand-work").click();expect(helper).to_be_visible()
            expect(p.locator("#messages")).to_contain_text("покажи чистую прибыль")
            self.ask("открой склад")
            expect(work).to_be_visible();expect(p.locator('[data-panel="stock"]')).to_be_visible()
            p.locator("#toggle-helper").click();expect(helper).to_be_visible()
            expect(p.locator("#messages")).to_contain_text("открой склад")
            p.locator("#close-helper").click();expect(work).to_be_visible()
            self.shot("work-first-mobile-"+str(width),"#work-pane")
        self.set_mode("light",1440);p.locator("#toggle-helper").click();expect(helper).to_be_visible();expect(work).to_be_visible()
        expect(p.locator("#balance-label")).to_have_text("Баланс: 10,00 монет")
