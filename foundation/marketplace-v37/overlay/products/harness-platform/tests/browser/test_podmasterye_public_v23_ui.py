"""Browser acceptance of single menu control, bounded public requests and independent scroll."""
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI
from urllib.parse import urlsplit
from time import monotonic,sleep
from platform_core import coins

class PublicV23UI(IndependentUI):
    def test_single_menu_and_fast_public_transport(self):
        p=self.page;requests=[]
        p.on("request",lambda r:requests.append((r.method,urlsplit(r.url).path)))
        p.goto("/")
        expect(p.locator("#guest-form button")).to_be_enabled()
        if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
        self.assertEqual([x for x in requests if x[1].startswith("/guest/")],[("POST","/guest/session")])
        nav=p.locator("#public-menu");toggle=p.locator("#public-menu-toggle")
        expect(nav).to_be_visible();expect(toggle).to_have_attribute("aria-label","Свернуть меню")
        self.assertEqual(p.locator("#public-menu-close").count(),0)
        toggle.click();expect(nav).not_to_be_visible()
        expect(toggle).to_have_attribute("aria-label","Развернуть меню")
        toggle.click();expect(nav).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded","true")
        info=p.locator("#public-info-content");header=p.locator("#public-info-pane .pm-work-header")
        top=header.bounding_box()["y"]
        self.assertGreater(info.evaluate("e=>e.scrollHeight-e.clientHeight"),100)
        # Wait for the re-opened navigation layout to settle and for this
        # actual scroll surface to receive the pointer before sending a wheel.
        info.hover()
        p.mouse.wheel(0,700)
        deadline=monotonic()+15
        while info.evaluate("e=>e.scrollTop")<=100 and monotonic()<deadline:sleep(.05)
        self.assertGreater(info.evaluate("e=>e.scrollTop"),100)
        self.assertAlmostEqual(header.bounding_box()["y"],top,delta=1)
        self.assertEqual(p.locator("#public-info-pane").evaluate("e=>e.scrollTop"),0)
        self.assertEqual(p.locator("#guest-messages").evaluate("e=>e.scrollTop"),0)
        info.evaluate("e=>e.scrollTop=0")
        start=len(requests)
        for key,title in (("contacts","Контакты и реквизиты"),("about","Мастерская — программа учёта производства и себестоимости"),("contacts","Контакты и реквизиты"),("about","Мастерская — программа учёта производства и себестоимости")):
            nav.locator('a[data-public-panel="'+key+'"]').click();expect(info.locator("h1")).to_have_text(title)
        self.assertEqual(requests[start:],[("GET","/contacts")])
        with self.app.state.identity._write() as db:coins.set_sale_pricing(db,"30")
        nav.locator('a[data-public-panel="payment"]').click();expect(info).to_contain_text("130,00 ₽")
        nav.locator('a[data-public-panel="about"]').click()
        with self.app.state.identity._write() as db:coins.set_sale_pricing(db,"40")
        nav.locator('a[data-public-panel="payment"]').click();expect(info).to_contain_text("140,00 ₽")
        before=len(requests)
        p.locator("#guest-input").fill("Сколько стоит монета?")
        p.locator("#guest-input").press("Enter")
        expect(p.locator("#guest-messages .message.user")).to_have_count(1)
        expect(p.locator("#guest-messages")).to_contain_text("1,40")
        recent=[x for x in requests[before:] if x[1].startswith("/guest/")]
        self.assertEqual(len(recent),1,recent);self.assertEqual(recent[0][0],"POST")
        self.assertTrue(recent[0][1].endswith("/turns"))
        p.reload();expect(p.locator("#guest-messages .message.user")).to_have_count(1)
        expect(p.locator("#guest-messages")).to_contain_text("1,40")
        self.assertFalse(self.errors)
