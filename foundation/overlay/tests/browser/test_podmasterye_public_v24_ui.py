"""Guest helper menu entry exists visually only while the helper is collapsed."""
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI
from urllib.parse import urlsplit

class PublicV24UI(IndependentUI):
    def test_helper_restore_menu_visibility(self):
        p=self.page
        p.goto("/")
        expect(p.locator("#guest-form button")).to_be_enabled(timeout=20000)
        if p.locator("#cookie-decline").is_visible():
            p.locator("#cookie-decline").click()
        chat=p.locator("#public-chat-pane")
        info=p.locator("#public-info-pane")
        nav=p.locator("#public-menu")
        helper=nav.locator("[data-public-chat]")
        toggle=p.locator("#public-menu-toggle")
        expect(chat).to_be_visible()
        expect(nav).to_be_visible()
        expect(helper).not_to_be_visible()
        field=p.locator("#guest-input")
        field.fill("Сколько стоит монета?")
        field.press("Enter")
        expect(p.locator("#guest-quota")).to_contain_text("11 из 12",timeout=20000)
        field.fill("Черновик сообщения")
        requests=[]
        p.on("request",lambda r:requests.append(urlsplit(r.url).path))
        for width in (1440,1100):
            p.set_viewport_size({"width":width,"height":900})
            for shade in ("light","dark"):
                p.evaluate("(s)=>window.PMTheme.set(s)",shade)
                expect(helper).not_to_be_visible()
                p.locator("#public-open-info").click()
                expect(chat).not_to_be_visible()
                expect(info).to_be_visible()
                expect(helper).to_be_visible()
                helper.click()
                expect(chat).to_be_visible()
                expect(info).to_be_visible()
                expect(helper).not_to_be_visible()
                expect(field).to_have_value("Черновик сообщения")
                expect(p.locator("#guest-quota")).to_contain_text("11 из 12")
                p.locator("#public-open-info").click()
                expect(helper).to_be_visible()
                p.locator("#public-open-chat").click()
                expect(helper).not_to_be_visible()
                p.locator("#public-open-chat").click()
                expect(info).not_to_be_visible()
                expect(helper).not_to_be_visible()
                p.locator("#public-open-info").click()
                expect(info).to_be_visible()
                toggle.click()
                expect(nav).not_to_be_visible()
                toggle.click()
                expect(nav).to_be_visible()
                expect(helper).not_to_be_visible()
        for width in (960,390,320):
            p.set_viewport_size({"width":width,"height":844})
            # On compact screens the information surface initially owns the viewport.
            if chat.is_visible():
                p.locator("#public-open-info").click()
            expect(info).to_be_visible()
            expect(chat).not_to_be_visible()
            if not nav.is_visible():toggle.click()
            expect(helper).to_be_visible()
            helper.click()
            expect(chat).to_be_visible()
            expect(nav).not_to_be_visible()
            toggle.click()
            expect(nav).to_be_visible()
            expect(helper).not_to_be_visible()
            expect(field).to_have_value("Черновик сообщения")
            p.locator("#public-open-info").click()
            expect(info).to_be_visible()
            expect(chat).not_to_be_visible()
            expect(helper).to_be_visible()
            toggle.click()
        self.assertEqual(requests,[])
        self.assertFalse(self.errors,self.errors)
