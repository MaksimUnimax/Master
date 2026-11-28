"""Verify profit interface, live results, modes, calculator transfer and local commands."""
from playwright.sync_api import expect
from unittest.mock import patch
from test_podmasterye_independent_ui import IndependentUI
from platform_core import guest_selector

class ProfitV26UI(IndependentUI):
    def open_profit(self):
        p=self.page;p.goto("/kalkulyator-pribyli/")
        if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
        expect(p.locator('#calc-form')).to_be_visible()
        expect(p.locator('[data-profit-mode="units"]')).to_have_attribute("aria-pressed","true")
    def row(self,name):
        return self.page.locator("#calc-result tbody tr").filter(has=self.page.get_by_role("cell",name=name,exact=True))
    def test_example_costs_modes_retain_and_reload(self):
        self.open_profit();p=self.page
        expect(p.locator("#profit-main-value")).to_have_text("—")
        p.locator("#profit-example").click()
        expect(self.row("Прибыль по введённым данным")).to_contain_text("17000.00 ₽")
        expect(p.locator("#profit-main-value")).to_have_text("17\u202f000,00 ₽")
        expect(self.row("Минимальный объём продаж")).to_contain_text("23 шт.")
        expect(self.row("Минимальная цена при заданном объёме")).to_contain_text("311.12 ₽")
        expect(self.row("Прибыль на штуку")).to_contain_text("170.00 ₽")
        p.locator('[name=taxes]').fill("1000")
        expect(self.row("Прибыль по введённым данным")).to_contain_text("16000.00 ₽")
        p.locator('[name=commission_percent]').fill("100")
        expect(self.row("Прибыль по введённым данным")).to_contain_text("-29000.00 ₽")
        expect(p.locator("#profit-summary")).to_have_attribute("data-sign","negative")
        expect(self.row("Минимальный объём продаж")).to_contain_text("—")
        p.locator('[name=commission_percent]').fill("101")
        expect(p.locator("#calc-status")).to_contain_text("Слишком большое значение")
        expect(p.locator("#profit-main-value")).to_have_text("—")
        p.locator('[name=commission_percent]').fill("10")
        p.locator('[data-profit-mode=period]').click()
        p.locator('[name=revenue]').fill("10000");p.locator('[name=cost]').fill("4000");p.locator('[name=expenses]').fill("1000")
        expect(self.row("Прибыль по введённым данным")).to_contain_text("5000.00 ₽")
        p.reload();expect(p.locator('[data-profit-mode=period]')).to_have_attribute("aria-pressed","true")
        expect(self.row("Прибыль по введённым данным")).to_contain_text("5000.00 ₽")
        p.locator('[data-profit-mode=units]').click()
        expect(p.locator('[name=taxes]')).to_have_value("1000")
        expect(self.row("Прибыль по введённым данным")).to_contain_text("16000.00 ₽")
    def test_transfer_real_cost_and_chat(self):
        p=self.page;p.goto("/kalkulyator")
        if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
        p.locator('[name=product_name]').fill("Контроль")
        r=p.locator("#calc-rows .calc-line").first
        for k,v in [("name","Бусины"),("pack_quantity","400"),("price","800"),("quantity","20")]:r.locator('[name='+k+']').fill(v)
        p.locator('[name=minutes]').fill("30");p.locator('[name=hourly_rate]').fill("300")
        expect(p.locator("#calc-result tbody tr").filter(has_text="Полная себестоимость")).to_contain_text("190.00 ₽")
        p.locator('.pm-calc-tabs a[data-public-panel=profit]').click()
        expect(p.locator("#profit-import-cost")).to_be_visible()
        p.locator("#profit-import-cost").click();expect(p.locator('[name=unit_cost]')).to_have_value("190.00")
        with patch.object(guest_selector,"classify",side_effect=AssertionError("unexpected model")):
            for i,(message,field,value) in enumerate([("Количество продаж: 10","units","10"),("Цена за штуку: 500","unit_price","500.00"),("Комиссия: 10%","commission_percent","10"),("Доставка за штуку: 20","delivery_unit","20.00")]):
                expect(p.locator("#guest-input")).to_be_enabled();p.locator("#guest-input").fill(message);p.locator("#guest-input").press("Enter")
                expect(p.locator("#guest-messages .message.user")).to_have_count(i+1)
                expect(p.locator("#guest-input")).to_be_enabled()
                self.assertEqual(p.locator("#guest-quota,#guest-limit").count(),0)
                expect(p.locator('[name='+field+']')).to_have_value(value)
            expect(self.row("Прибыль по введённым данным")).to_contain_text("2400.00 ₽")
        p.locator('nav a[data-public-panel=about]').click()
        expect(p.locator("#public-info-content h1")).to_have_text("Мастерская — программа учёта производства и себестоимости")
        p.locator('nav a[data-public-panel=profit]').click()
        expect(self.row("Прибыль по введённым данным")).to_contain_text("2400.00 ₽")
    def test_responsive_themes_and_example(self):
        self.open_profit();p=self.page;p.locator("#profit-example").click()
        expect(p.locator("#profit-main-value")).to_have_text("17\u202f000,00 ₽")
        for width in (1440,1100,960,390,320):
            for shade in ("light","dark"):
                p.set_viewport_size({"width":width,"height":900})
                p.evaluate("(v)=>window.PMTheme.set(v)",shade)
                for selector in ("#profit-summary","#calc-form","#calc-result"):
                    b=p.locator(selector).bounding_box()
                    self.assertIsNotNone(b);self.assertGreaterEqual(b["x"],-1);self.assertLessEqual(b["x"]+b["width"],width+1)
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),width+1)
                if width in (1440,390):
                    p.locator("#public-info-content").evaluate("e=>e.scrollTop=0")
                    p.screenshot(path=str(self.evidence/f"profit-v26-{width}-{shade}.png"),animations="disabled")
