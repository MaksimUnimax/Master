"""Browser checks for integration setup; external requests are mocked."""
from unittest.mock import patch,AsyncMock
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI
from platform_core import integrations

class MarketUI(IndependentUI):
    def test_market_forms(self):
        self.sign_in();p=self.page;self.nav("integrations")
        f=p.locator("#market-add")
        expect(f.locator("[name=client_id]")).to_be_visible()
        expect(f.locator("[name=performance_secret]")).to_have_attribute("type","password")
        for k,v in {"name":"Учебный Ozon","client_id":"12345","api_key":"seller-fixture","performance_id":"5678","performance_secret":"advert-fixture"}.items():
            f.locator("[name="+k+"]").fill(v)
        f.get_by_role("button",name="Сохранить подключение").click()
        c=p.locator("#market-list .settings-card").filter(has_text="Учебный Ozon")
        expect(c).to_be_visible();expect(c).to_contain_text("Ключи сохранены, связь не проверена")
        self.assertNotIn("seller-fixture",c.inner_text())
        with patch.object(integrations,"probe",new_callable=AsyncMock,return_value={"Seller":"verified","Performance":"denied"}):
            c.get_by_role("button",name="Проверить связь").click()
            expect(c).to_contain_text("Подтверждена часть доступов")
            expect(c).to_contain_text("Performance: Отказ в доступе")
        c.get_by_role("button",name="Изменить ключи").click()
        e=c.locator("form")
        expect(e.locator("[name=api_key]")).to_have_value("")
        e.locator("[name=client_id]").fill("12345");e.locator("[name=api_key]").fill("new-fixture-key")
        e.get_by_role("button",name="Сохранить новые ключи").click()
        expect(c).to_contain_text("Ключи сохранены, связь не проверена")
        f.locator("[name=provider]").select_option("wb")
        expect(f.locator("[name=client_id]")).to_have_count(0)
        expect(f.locator("[name=token]")).to_have_attribute("type","password")
        f.locator("[name=name]").fill("Учебный WB");f.locator("[name=token]").fill("wb-fixture")
        f.get_by_role("button",name="Сохранить подключение").click()
        wb=p.locator("#market-list .settings-card").filter(has_text="Учебный WB")
        expect(wb).to_be_visible()
        wb.get_by_role("button",name="Удалить",exact=True).click()
        expect(wb).to_have_count(0)
        expect(p.locator('[data-pm-telegram=connect]')).to_be_disabled()
        expect(p.locator("#pm-telegram-status")).to_contain_text("не настроен")
        self.assertFalse(p.locator("#tg-config-form").count())
        p.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"),390)
