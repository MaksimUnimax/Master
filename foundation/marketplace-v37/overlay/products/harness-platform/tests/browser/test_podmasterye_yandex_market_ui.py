"""Actual Yandex connection, durable verification and rotation with synthetic HTTP."""
from playwright.sync_api import expect
from tests.browser.test_podmasterye_independent_ui import IndependentUI
from tests.fixtures.market_dual import finish_fixture_job

class YandexMarketUI(IndependentUI):
    def test_market_connection_and_key_rotation(self):
        self.sign_in();p=self.page;self.nav("integrations");host=p.locator("#market-list")
        host.get_by_role("button",name="Подключения",exact=True).click()
        host.get_by_role("button",name="Подключить маркетплейс",exact=True).click()
        f=host.locator("[data-market-connection-form=create]")
        f.get_by_role("combobox",name="Площадка",exact=True).select_option("yandex_market")
        expect(f.locator("[name=api_key]")).to_have_attribute("type","password")
        expect(f.locator("[name=client_id]")).to_have_count(0)
        expect(f).to_contain_text("Просмотр всех данных")
        f.locator("[name=name]").fill("Учебный Маркет");f.locator("[name=api_key]").fill("fixture-ym-api-key")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/connection")) as saved:
            f.get_by_role("button",name="Сохранить ключ",exact=True).click()
        self.assertEqual(saved.value.status,200);connection=saved.value.json()
        c=host.locator(".settings-card").filter(has_text="Учебный Маркет")
        expect(c).to_contain_text("доступ ещё не проверен")
        self.assertNotIn("fixture-ym-api-key",c.inner_text())
        done,events=finish_fixture_job(self,connection["job_id"])
        self.assertEqual(done["state"],"ready");self.assertEqual(len(events),2)
        host.get_by_role("button",name="Подключения",exact=True).click()
        expect(c).to_contain_text("Доступ подтверждён")
        expect(c).to_contain_text("ID магазина: 123");expect(c).to_contain_text("ID кабинета: 12")
        expect(c).to_contain_text("Просмотр всех данных")
        p.reload();self.ready();self.nav("integrations");host.get_by_role("button",name="Подключения",exact=True).click()
        expect(c).to_contain_text("ID магазина: 123")
        c.get_by_role("button",name="Заменить ключ",exact=True).click()
        e=c.locator("[data-market-connection-form=rotate]")
        expect(e.locator("[name=api_key]")).to_have_value("")
        e.locator("[name=api_key]").fill("fixture-ym-new")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/connection")) as rotated:
            e.get_by_role("button",name="Сохранить ключ",exact=True).click()
        self.assertEqual(rotated.value.json()["state"],"collecting")
        expect(c).to_contain_text("доступ ещё не проверен");expect(c).not_to_contain_text("ID магазина: 123")
        c.get_by_role("button",name="Отключить",exact=True).click()
        c.get_by_role("button",name="Подтвердить отключение",exact=True).click()
        expect(c).to_have_count(0)
