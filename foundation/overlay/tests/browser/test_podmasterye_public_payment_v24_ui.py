"""Guest payment quote, disabled checkout, and login handoff without real payment."""
import re
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI
from platform_core import coins,checkout

class PublicPaymentV24UI(IndependentUI):
    def test_guest_payment_form_without_authorization(self):
        p=self.page;requests=[]
        p.on("request",lambda r:requests.append(urlsplit(r.url).path))
        with self.app.state.identity._write() as db:coins.set_sale_pricing(db,"30")
        p.goto("/payment")
        if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
        form=p.locator("#public-payment-form")
        count=form.locator("input[name=coins]")
        total=form.locator("output")
        submit=form.locator("button")
        expect(form).to_be_visible()
        expect(count).to_have_value("100")
        expect(total).to_have_text("130,00 ₽")
        expect(submit).to_be_disabled()
        expect(p.locator("#public-info-content")).not_to_contain_text("за 1 монету")
        expect(p.locator("#public-info-content")).not_to_contain_text("Стоимость монет")
        self.assertEqual(p.locator(".pm-payment-method").all_text_contents(),["СБП","Банковские карты","ЮMoney","SberPay","T-Pay"])
        count.fill("250");expect(total).to_have_text(re.compile(r"325,00\s*₽"))
        expect(submit).to_be_disabled()
        count.fill("0");expect(total).to_have_text("—")
        expect(submit).to_be_disabled()
        count.fill("1.5");expect(total).to_have_text("—")
        count.fill("8000001");expect(total).to_have_text("—")
        count.fill("250");expect(total).to_have_text(re.compile(r"325,00\s*₽"))
        p.locator('nav a[data-public-panel="contacts"]').click()
        p.locator('nav a[data-public-panel="payment"]').click()
        expect(count).to_have_value("250");expect(total).to_have_text(re.compile(r"325,00\s*₽"))
        self.assertNotIn("/api/coins/checkout",requests)
        self.assertFalse(any("yookassa" in x for x in requests))
        self.assertFalse(self.errors,self.errors)

    def test_enabled_quote_handoff_preserves_quantity_without_charge(self):
        p=self.page
        requests=[]
        p.on("request",lambda r:requests.append(urlsplit(r.url).path))
        # Only configuration capability is simulated, never a provider call.
        with patch.object(checkout,"merchant",return_value=("fixture","fixture")):
            p.goto("/payment")
            if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
            form=p.locator("#public-payment-form")
            expect(form.locator("button")).to_be_enabled()
            form.locator("input").fill("375")
            expect(form.locator("output")).not_to_have_text("—")
            expect(form.locator("button")).to_be_enabled()
            form.locator("button").click()
            expect(p.locator("#public-info-content h1")).to_have_text("Вход")
            self.assertEqual(p.evaluate("sessionStorage.getItem('podmasterye-public-checkout-count')"),"375")
            self.assertNotIn("/api/coins/checkout",requests)
            self.assertFalse(self.errors,self.errors)
