"""Guest calculator interaction through the real public shell and native APIs."""
from playwright.sync_api import expect
from unittest.mock import patch
from urllib.parse import urlsplit
from test_podmasterye_independent_ui import IndependentUI
from platform_core import guest_selector

class GuestCalculatorV25UI(IndependentUI):
    def send(self,text,count):
        p=self.page
        p.locator("#guest-input").fill(text)
        p.locator("#guest-input").press("Enter")
        expect(p.locator("#guest-messages .message.user")).to_have_count(count)
        expect(p.locator("#guest-input")).to_be_enabled()
        self.assertEqual(p.locator("#guest-quota,#guest-limit").count(),0)
    def test_matrix_fills_calculator_and_preserves_chat(self):
        p=self.page;requests=[]
        p.on("request",lambda r:requests.append(urlsplit(r.url).path))
        with patch.object(guest_selector,"classify",side_effect=AssertionError("Unexpected provider call")):
            p.goto("/")
            if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
            expect(p.locator("#guest-input")).to_be_enabled()
            p.evaluate("window.__chatNode=document.getElementById('guest-messages')")
            self.send("Открой калькулятор себестоимости",1)
            expect(p.locator("#calc-form")).to_be_visible()
            self.assertEqual(urlsplit(p.url).path,"/kalkulyator")
            expect(p.locator("#public-chat-pane")).to_be_visible()
            self.send("Изделие: Браслет",2)
            expect(p.locator('[name=product_name]')).to_have_value("Браслет")
            self.send("Материал: Бусины; упаковка: 400 шт; цена: 800; расход: 20 шт",3)
            row=p.locator("#calc-rows .calc-line").first
            expect(row.locator('[name=pack_quantity]')).to_have_value("400")
            expect(row.locator('[name=quantity]')).to_have_value("20")
            expect(p.locator("#calc-result tbody tr").filter(has_text="Материалы")).to_contain_text("40.00 ₽")
            self.send("Цена продажи: 500",4)
            self.send("Время: 30 мин",5)
            self.send("Стоимость часа: 300",6)
            self.send("Рассчитай себестоимость",7)
            expect(p.locator("#calc-result tbody tr").filter(has_text="Прибыль после учёта труда")).to_contain_text("310.00 ₽")
            expect(p.locator("#calc-save")).to_be_enabled()
            p.locator('nav a[data-public-panel="about"]').click()
            expect(p.locator("#public-info-content h1")).to_have_text("Мастерская — программа учёта производства и себестоимости")
            p.locator('nav a[data-public-panel="calculator"]').click()
            expect(row.locator('[name=quantity]')).to_have_value("20")
            self.assertTrue(p.evaluate("window.__chatNode===document.getElementById('guest-messages')"))
            self.send("Материал: Бусины; упаковка: 400 шт; цена: 800; расход: 30 шт",8)
            expect(p.locator("#calc-rows .calc-line")).to_have_count(1)
            expect(row.locator('[name=quantity]')).to_have_value("30")
            expect(p.locator("#calc-result tbody tr").filter(has_text="Материалы")).to_contain_text("60.00 ₽")
            p.reload();expect(p.locator("#guest-messages .message.user")).to_have_count(8)
            expect(row.locator('[name=quantity]')).to_have_value("30")
            # Reload/history must not reapply older commands over a manual edit.
            row.locator('[name=quantity]').fill("25")
            expect(p.locator("#calc-result tbody tr").filter(has_text="Материалы")).to_contain_text("50.00 ₽")
            p.reload();expect(row.locator('[name=quantity]')).to_have_value("25")
            self.send("Удали материал: Бусины",9)
            expect(p.locator("#calc-rows .calc-line")).to_have_count(0)
            self.send("Открой калькулятор прибыли",10)
            expect(p.locator("#public-info-content h1")).to_have_text("Калькулятор прибыли")
            self.send("Выручка: 10000",11)
            expect(p.locator('[name=revenue]')).to_have_value("10000.00")
            self.send("Себестоимость продаж: 4000",12)
            expect(p.locator('[name=cost]')).to_have_value("4000.00")
            expect(p.locator("#guest-input")).to_be_enabled()
            self.send("Прочие расходы: 1000",13)
            expect(p.locator('[name=expenses]')).to_have_value("1000.00")
            p.locator('[name=expenses]').fill("1000")
            expect(p.locator("#calc-result tbody tr").filter(has_text="Прибыль по введённым данным")).to_contain_text("5000.00 ₽")
            expect(p.locator("#calc-result tbody tr").filter(has_text="Маржа")).to_contain_text("50.00%")
            self.assertNotIn("/api/calculator/save",requests)
        self.assertFalse(self.errors)
    def test_layout_and_command_help_mobile(self):
        p=self.page
        p.goto("/kalkulyator")
        if p.locator("#cookie-decline").is_visible():p.locator("#cookie-decline").click()
        for width in (1440,1100,960,390,320):
            for shade in ("light","dark"):
                p.set_viewport_size({"width":width,"height":900})
                p.evaluate("(v)=>window.PMTheme.set(v)",shade)
                expect(p.locator("#calc-form")).to_be_visible()
                b=p.locator("#calc-form").bounding_box()
                self.assertGreaterEqual(b["x"],-1)
                self.assertLessEqual(b["x"]+b["width"],width+1)
                self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),width+1)
                if width in (1440,390):p.screenshot(path=str(self.evidence/f"guest-calc-{width}-{shade}.png"),animations="disabled")
        p.locator(".pm-calc-commands summary").click()
        p.locator('[data-calc-command="Открой калькулятор себестоимости"]').click()
        expect(p.locator("#guest-input")).to_be_visible()
        expect(p.locator("#guest-input")).to_have_value("Открой калькулятор себестоимости")
        p.locator("#guest-input").press("Enter")
        expect(p.locator("#calc-form")).to_be_visible()
        expect(p.locator("#guest-messages .message.user")).to_have_count(1)
        self.assertEqual(p.locator("#guest-quota,#guest-limit").count(),0)
