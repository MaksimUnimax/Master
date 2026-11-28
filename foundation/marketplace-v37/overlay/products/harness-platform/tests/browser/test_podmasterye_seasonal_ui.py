"""Browser acceptance: direct links, period plan, saved monthly collection."""
from playwright.sync_api import expect
from tests.browser.test_podmasterye_independent_ui import IndependentUI
from tests.fixtures.market_dual import finish_fixture_job
from tests.fixtures.market_quantity_cases import csv_bytes,zip_bytes

def report_response(day,n):
    raw=zip_bytes({name+".csv":csv_bytes(["ORDER_ID","YOUR_SKU","OFFER_NAME",quantity,event_date],
        [["9001","item-a","Браслет",str(count),day]]) for name,quantity,event_date,count in (
        ("delivered","DELIVERED_COUNT","DELIVERY_DATE",n),
        ("returned","RETURNED_COUNT","RETURN_WAREHOUSE_OR_SC_ACCEPT_DATE",0),
        ("unredeemed","UNREDEEMED_COUNT","UNREDEEMED_WAREHOUSE_OR_SC_ACCEPT_DATE",0))})
    return lambda event: {"status_code":200,"headers":{"content-type":"application/zip"},"content":raw} if event["download"] else None

class SeasonalUI(IndependentUI):
    def test_seasonal_links_and_plan(self):
        self.sign_in();p=self.page
        ids=self.call("/api/production/recipe",{"requestId":"seed","recipe":{"material":"Бусины","product":"Браслет","pack_quantity":100,"usage_quantity":4,"pack_price":"100"}})
        self.op("opening",material=ids["material_id"],quantity=500,total="500",day="2025-05-01")
        self.op("sale",product=ids["product_id"],quantity=100,unit_price="10",paid_amount="1000",auto_produce=True,day="2025-05-02")
        p.goto("/app/?section=planning");self.ready()
        expect(p.locator('[data-panel="planning"]')).to_be_visible()
        p.locator("#season-from").fill("2025-05")
        p.locator("#season-to").fill("2025-05")
        p.locator("#season-target").fill("2027-05")
        p.locator("#season-refresh").click()
        expect(p.locator("#season-status")).to_contain_text("Расчёт готов")
        expect(p.locator("#season-result")).to_contain_text("2025-05 → 2027-05")
        expect(p.locator("#season-result")).to_contain_text("Бусины")
        expect(p.locator("#season-result")).to_contain_text("400 шт")
        expect(p.locator("#season-result")).to_contain_text("300 шт")
        expect(p.locator("#actual-consumption-period")).to_contain_text("400 шт")
        self.assertEqual(self.report()["materials"][0]["quantity"],100)
        p.goto("/app/?section=sales");self.ready()
        expect(p.locator('[data-panel="sales"]')).to_be_visible()
    def test_history_resume_and_mapping(self):
        self.sign_in();p=self.page;self.nav("integrations");host=p.locator("#market-list")
        ids=self.call("/api/production/recipe",{"requestId":"seed","recipe":{"material":"Бусины","product":"Браслет","pack_quantity":100,"usage_quantity":4,"pack_price":"100"}})
        host.get_by_role("button",name="Подключения",exact=True).click()
        host.get_by_role("button",name="Подключить маркетплейс",exact=True).click()
        f=host.locator("[data-market-connection-form=create]")
        f.get_by_role("combobox",name="Площадка",exact=True).select_option("yandex_market")
        f.locator("[name=name]").fill("Учебный Маркет");f.locator("[name=api_key]").fill("fixture-ym-seasonal")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/connection")) as saved:
            f.get_by_role("button",name="Сохранить ключ",exact=True).click()
        connection=saved.value.json();done,_=finish_fixture_job(self,connection["job_id"])
        self.assertEqual(done["state"],"ready")
        first=self.call("/api/integrations/marketplaces/operations",{"operation":"market_sync_request","arguments":{"source":"yandex_market","from":"2025-05-01","to":"2025-05-31"},"requestId":"seed-may"})
        may=next(j for j in first["jobs"] if j["template_id"]=="YM-05" and j["from"]=="2025-05-01")
        completed,may_events=finish_fixture_job(self,may["id"],fault=report_response("2025-05-02",100))
        self.assertEqual(completed["state"],"ready")
        catalogue=next(j for j in first["jobs"] if j["template_id"]=="YM-02")
        completed,_=finish_fixture_job(self,catalogue["id"]);self.assertEqual(completed["state"],"ready")
        host.get_by_role("button",name="История и обновления",exact=True).click()
        host.get_by_text("Собрать выбранный период",exact=True).click()
        form=host.locator("details form")
        form.get_by_role("combobox",name="Источник",exact=True).select_option("yandex_market")
        form.get_by_label("С даты",exact=True).fill("2025-05-01");form.get_by_label("По дату",exact=True).fill("2025-06-30")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/operations") and r.request.post_data_json.get("operation")=="market_sync_request") as started:
            form.get_by_role("button",name="Запустить сбор",exact=True).click()
        self.assertEqual(started.value.status,200);group=started.value.json()
        june=next(j for j in group["jobs"] if j["template_id"]=="YM-05" and j["from"]=="2025-06-01")
        completed,june_events=finish_fixture_job(self,june["id"],fault=report_response("2025-06-02",50))
        self.assertEqual(completed["state"],"ready")
        self.assertEqual(sum(e["generate"] for e in may_events),1);self.assertEqual(sum(e["generate"] for e in june_events),1)
        previous=self.call("/api/integrations/marketplaces/operations",{"operation":"market_sync_status","arguments":{"job_id":may["id"]},"requestId":"may-still-ready"})
        self.assertEqual(previous["requests"],len(may_events))
        self.assertEqual(self.report()["summary"]["sales_quantity"],0)
        p.goto("/app/?section=planning");self.ready()
        p.locator("#season-source").select_option("yandex_market")
        p.locator("#season-from").fill("2025-05");p.locator("#season-to").fill("2025-06");p.locator("#season-target").fill("2027-05")
        p.locator("#season-refresh").click()
        expect(p.locator("#season-result")).to_contain_text("Не сопоставлен артикул")
        p.locator("#season-mapping").get_by_role("button",name="Сопоставить",exact=True).click()
        mapping=p.locator("#season-mapping form")
        mapping.get_by_role("combobox",name="Изделие мастерской",exact=True).select_option(ids["product_id"])
        mapping.get_by_role("button",name="Проверить сопоставление",exact=True).click()
        mapping.get_by_role("button",name="Подтвердить",exact=True).click()
        expect(p.locator("#season-status")).to_contain_text("Расчёт готов")
        expect(p.locator("#season-result")).to_contain_text("600 шт")
        self.assertEqual(self.report()["summary"]["sales_quantity"],0)
