"""Browser collection/export contract over durable local data and synthetic HTTP."""
from playwright.sync_api import expect
from tests.browser.test_podmasterye_independent_ui import IndependentUI
from tests.fixtures.market_dual import finish_fixture_job

class SalesUI(IndependentUI):
    def test_orders_and_realization(self):
        self.sign_in();p=self.page;self.nav("integrations");host=p.locator("#market-list")
        host.get_by_role("button",name="Подключения",exact=True).click()
        host.get_by_role("button",name="Подключить маркетплейс",exact=True).click()
        f=host.locator("[data-market-connection-form=create]")
        f.get_by_role("combobox",name="Площадка",exact=True).select_option("yandex_market")
        f.locator("[name=name]").fill("Учебный Маркет");f.locator("[name=api_key]").fill("fixture-market-key")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/connection")) as saved:
            f.get_by_role("button",name="Сохранить ключ",exact=True).click()
        connection=saved.value.json();done,_=finish_fixture_job(self,connection["job_id"])
        self.assertEqual(done["state"],"ready")
        host.get_by_role("button",name="История и обновления",exact=True).click()
        host.get_by_text("Собрать выбранный период",exact=True).click()
        form=host.locator("details form")
        form.get_by_role("combobox",name="Источник",exact=True).select_option("yandex_market")
        form.get_by_label("С даты",exact=True).fill("2026-10-01");form.get_by_label("По дату",exact=True).fill("2026-10-30")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/operations") and r.request.post_data_json.get("operation")=="market_sync_request") as started:
            form.get_by_role("button",name="Запустить сбор",exact=True).click()
        self.assertEqual(started.value.status,200);group=started.value.json()
        job=next(j for j in group["jobs"] if j["template_id"]=="YM-05" and j["from"]=="2026-10-01")
        done,events=finish_fixture_job(self,job["id"])
        self.assertEqual(done["state"],"ready")
        self.assertEqual(sum(e["generate"] for e in events),1)
        self.assertEqual(sum(e["download"] for e in events),1)
        # The same local report is visible after a reload, with no new provider
        # request/report generation and no implicit accounting sale.
        for reload in (False,True):
            if reload:p.reload();self.ready();self.nav("integrations")
            host.get_by_role("button",name="Продажи",exact=True).click()
            report=host.locator("form")
            report.get_by_role("combobox",name="Источник",exact=True).select_option("yandex_market")
            report.get_by_label("С даты",exact=True).fill("2026-10-01");report.get_by_label("По дату",exact=True).fill("2026-10-30")
            report.get_by_role("button",name="Показать",exact=True).click()
            for label,value in (("Доставлено","5"),("Физически возвращено","1"),("Чистые продажи, факт","4")):
                row=host.locator("tbody tr").filter(has=p.get_by_role("cell",name=label,exact=True))
                expect(row.get_by_role("cell",name=value,exact=True)).to_be_visible()
            self.assertNotIn("fixture-market-key",host.inner_text())
        status=self.call("/api/integrations/marketplaces/operations",{"operation":"market_sync_status","arguments":{"job_id":job["id"]},"requestId":"browser-saved-status"})
        self.assertEqual(status["requests"],len(events))
        self.assertEqual(self.report()["summary"]["sales_quantity"],0)
