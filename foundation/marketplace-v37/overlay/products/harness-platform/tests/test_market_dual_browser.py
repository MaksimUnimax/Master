"""Actual browser interactions with local fixtures; no live marketplace claim."""
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from playwright.sync_api import expect
from tests.browser import test_podmasterye_independent_ui as browser_fixture
from platform_core import market_quantity as quantity, podmasterye_domain as domain

from tests.fixtures.market_dual import finish_fixture_job

class MarketDualBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=os.environ.get("PODMASTER_BROWSER_ENGINE","chromium")
        if engine not in ("chromium","opera"):
            raise RuntimeError("PODMASTER_BROWSER_ENGINE must be chromium or opera")
        binary=os.environ.get("PLAYWRIGHT_OPERA_EXECUTABLE_PATH") if engine=="opera" else os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        if engine=="opera" and (not binary or "opera" not in str(Path(binary).resolve()).lower()):
            raise RuntimeError("Opera acceptance requires the actual Opera executable")
        with patch.dict(os.environ,{"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH":binary} if binary else {}):
            browser_fixture.IndependentUI.setUpClass.__func__(cls)
        (cls.evidence/("market-browser-"+engine+".json")).write_text(json.dumps({"engine":engine,"executable":binary,"version":cls.browser.version,"headless":os.environ.get("PODMASTER_BROWSER_HEADLESS","1")!="0","fixture":"isolated; no live API or model"},indent=2)+"\n")
    def setUp(self):
        browser_fixture.IndependentUI.setUp(self)
        with self.app.state.identity._write() as db:
            # This class owns an isolated DB. Both complete interaction paths
            # must work without any model-credit grant.
            db.execute("DELETE FROM coin_grants")

    def tearDown(self):
        browser_fixture.IndependentUI.tearDown(self)
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],0)
    sign_in=browser_fixture.IndependentUI.sign_in
    ready=browser_fixture.IndependentUI.ready
    nav=browser_fixture.IndependentUI.nav
    call=browser_fixture.IndependentUI.call

    def ask(self,text):
        p=self.page;before=p.locator("#messages .message.assistant").count()
        p.locator("#assistant-form textarea").fill(text)
        p.locator("#assistant-form button[type=submit]").click()
        expect(p.locator("#messages .message.assistant")).to_have_count(before+1)
        return p.locator("#messages .message.assistant").last

    def seed_catalog(self):
        w=self.page.evaluate("window.PMWorkshopId")
        with self.app.state.identity._write() as db:
            cid,version=db.execute("SELECT id,version FROM pm_market_connections WHERE workspace=? AND provider='ozon'",(w,)).fetchone()
            sid=quantity.bind_verified(db,w,cid,version,"ozon","browser-fixture",{"seller_id":"browser-fixture"})
            record=domain._save(db,w,"browser-recipe",{"material":"Бусины","product":"Браслет","unit":"шт","pack_quantity":100,"usage_quantity":9,"pack_price":"100"})
            with quantity.local(db,w,"ozon",True) as local:
                local.execute("INSERT INTO quantity_catalog VALUES(?,?,?,?,?)",(sid,"fixture-sku",json.dumps({"sku":"fixture-sku","name":"Браслет"}),time.time(),"browser-fixture-catalog"))
        return sid,record["product_id"]

    def test_chat_only_secure_connection_jobs_mapping_quality_and_export(self):
        self.sign_in();p=self.page
        expect(p.locator("#balance-label")).to_have_text("Баланс: 0,00 монет")
        chat_posts=[]
        p.on("request",lambda r:chat_posts.append(r.post_data or "") if r.method=="POST" and "/turns" in r.url else None)
        card=self.ask("подключить ozon")
        form=card.locator("[data-market-connection-form=create]")
        form.get_by_label("Название магазина").fill("Чат Ozon")
        form.get_by_label("Client-Id Seller API",exact=True).fill("12345")
        secret=form.get_by_label("Api-Key Seller API",exact=True)
        expect(secret).to_have_attribute("type","password")
        secret.fill("browser-private-fixture-key")
        form.get_by_role("button",name="Сохранить ключ",exact=True).click()
        expect(form.locator(":scope > [role=status]")).to_contain_text("Ключ сохранён")
        expect(secret).to_have_value("")
        self.assertNotIn("browser-private-fixture-key",p.locator("#messages").inner_text())
        self.assertTrue(all("browser-private-fixture-key" not in r for r in chat_posts))
        self.assertEqual(p.locator("nav button.active").get_attribute("data-page"),"summary")

        status=self.ask("статус маркетплейсов")
        job=status.locator(".settings-card").first
        expect(job).to_contain_text("Задание")
        job.get_by_role("button",name="Остановить",exact=True).click()
        expect(status).to_contain_text("Сбор остановлен")
        job=status.locator(".settings-card").first
        job.get_by_role("button",name="Продолжить",exact=True).click()
        expect(job).to_contain_text("Собираем")

        sid,product=self.seed_catalog()
        workspace=self.ask("управление маркетплейсами")
        workspace.get_by_role("button",name="Артикулы",exact=True).click()
        expect(workspace).to_contain_text("fixture-sku")
        workspace.get_by_role("button",name="Сопоставить",exact=True).click()
        mapping=workspace.locator("form").filter(has_text="Сопоставить артикул fixture-sku")
        mapping.get_by_label("Изделие мастерской").select_option(product)
        mapping.get_by_role("button",name="Проверить сопоставление",exact=True).click()
        expect(mapping.get_by_role("button",name="Подтвердить",exact=True)).to_be_enabled()
        mapping.get_by_role("button",name="Подтвердить",exact=True).click()
        expect(workspace).to_contain_text(product)
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT product FROM market_quantity_links WHERE store=? AND sku='fixture-sku'",(sid,)).fetchone()[0],product)

        workspace.get_by_role("button",name="Коэффициенты брака",exact=True).click()
        workspace.get_by_label("Брак среди физических возвратов, %").fill("25")
        workspace.get_by_label("Потери сырья при производстве, %").fill("10")
        workspace.get_by_role("button",name="Проверить изменение",exact=True).click()
        workspace.get_by_role("button",name="Подтвердить коэффициенты",exact=True).click()
        expect(workspace.get_by_role("status")).to_contain_text("Коэффициенты")
        workspace.get_by_role("button",name="Продажи",exact=True).click()
        expect(workspace).to_contain_text("Локальные данные")
        with p.expect_download() as exported:
            workspace.get_by_role("button",name="Экспорт полного отчёта",exact=True).click()
        self.assertEqual(exported.value.suggested_filename,"marketplace-report.zip")
        self.assertEqual(p.locator("nav button.active").get_attribute("data-page"),"summary")
        p.set_viewport_size({"width":390,"height":844})
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"),390)

    def test_cabinet_uses_the_same_secure_form_without_model(self):
        self.sign_in();p=self.page;self.nav("integrations")
        expect(p.locator("#balance-label")).to_have_text("Баланс: 0,00 монет")
        host=p.locator("#market-list")
        host.get_by_role("button",name="Подключения",exact=True).click()
        host.get_by_role("button",name="Подключить маркетплейс",exact=True).click()
        form=host.locator("[data-market-connection-form=create]")
        form.get_by_role("combobox",name="Площадка",exact=True).select_option("wb")
        form.get_by_label("Название магазина").fill("Кабинет WB")
        form.get_by_label("API-токен Wildberries").fill("cabinet-private-fixture-key")
        form.get_by_role("button",name="Сохранить ключ",exact=True).click()
        expect(host).to_contain_text("Кабинет WB")
        self.assertNotIn("cabinet-private-fixture-key",host.inner_text())
        self.assertEqual(p.locator("#messages .message.user").count(),0)
        item=host.locator(".settings-card").filter(has_text="Кабинет WB")
        item.get_by_role("button",name="Отключить",exact=True).click()
        item.get_by_role("button",name="Подтвердить отключение",exact=True).click()
        expect(host).not_to_contain_text("Кабинет WB")

    def test_group_progress_and_blocked_resume_stay_visible_in_chat(self):
        self.sign_in();p=self.page;w=p.evaluate("window.PMWorkshopId")
        connection=self.call("/api/integrations/marketplaces/connection",{"action":"create","requestId":"progress-connection","provider":"ozon","name":"Контроль прогресса","fields":{"client_id":"12345","api_key":"browser-progress-fixture-key"}})
        with self.app.state.identity._write() as db:
            quantity.bind_verified(db,w,connection["id"],connection["version"],"ozon","browser-progress",{"seller_id":"browser-progress"})
            group=quantity.market_sync_request(db,w,"ozon",from_="2026-09-01",to="2026-09-02",request_id="progress-group")
            gid=group["job_id"];jid=group["jobs"][0]["id"]
            db.execute("UPDATE market_data_tasks SET state='stopped' WHERE id IN (SELECT task_id FROM market_data_group_tasks WHERE group_id=?)",(gid,))
            db.execute("UPDATE market_data_tasks SET state='uncertain',inflight=?,detail=? WHERE id=?",(json.dumps({"generate":True}),"Исход создания отчёта неизвестен. Нужна сверка; повторное создание запрещено.",jid))
        card=self.ask("статус маркетплейсов")
        box=card.locator(".settings-card").filter(has=p.get_by_role("heading",name="Сбор истории "+gid,exact=True))
        expect(box).to_contain_text("Обработано периодов: 0 из "+str(group["progress"]["total"]))
        box.get_by_role("button",name="Продолжить",exact=True).click()
        expect(card.locator(".error")).to_contain_text("Исход создания отчёта неизвестен")
        # A later automatic status poll must not erase the explanation from
        # the action receipt; the user never has to open another UI section.
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/marketplaces/operations") and r.request.post_data_json.get("operation")=="market_sync_status"):
            pass
        expect(card.locator(".error")).to_contain_text("повторное создание запрещено")
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT state,requests FROM market_data_tasks WHERE id=?",(jid,)).fetchone(),("uncertain",0))
        self.assertEqual(p.locator("nav button.active").get_attribute("data-page"),"summary")

    def test_wb_realization_and_unknown_physical_returns_are_distinct(self):
        from tests.fixtures import market_quantity_cases as cases
        self.sign_in();p=self.page;w=p.evaluate("window.PMWorkshopId")
        connection=self.call("/api/integrations/marketplaces/connection",{"action":"create","requestId":"wb-report-connection","provider":"wb","name":"Реализация WB","fields":{"token":"wb-quantity-browser-fixture"}})
        sequence=cases.success_sequence("WB-04");rows=[row for step in sequence for row in step["outcome"].get("rows",[])]
        proof=sequence[-1]["outcome"]["coverage"]
        with self.app.state.identity._write() as db:
            sid=quantity.bind_verified(db,w,connection["id"],connection["version"],"wb","browser-wb-report",{})
            with quantity.local(db,w,"wb",True) as local:
                for row in rows:
                    local.execute("INSERT INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?)",(sid,"WB-04",row["natural_key"],"2026-10-01","2026-10-30",time.time(),json.dumps(row),"wb-browser-fixture",1))
                local.execute("INSERT INTO quantity_coverage VALUES(?,?,?,?,?,?,?)",(sid,"WB-04","2026-10-01","2026-10-30",json.dumps(proof),time.time(),"wb-browser-fixture"))
        self.nav("integrations");host=p.locator("#market-list")
        host.get_by_role("button",name="Продажи",exact=True).click();form=host.locator("form")
        form.get_by_role("combobox",name="Источник",exact=True).select_option("wb")
        form.get_by_label("С даты",exact=True).fill("2026-10-01");form.get_by_label("По дату",exact=True).fill("2026-10-30")
        form.get_by_role("button",name="Показать",exact=True).click()
        for label,value in (("Доставлено","3"),("Возвраты реализации","1"),("Физически возвращено","Не подтверждено"),("Чистые продажи, факт","2")):
            row=host.locator("tbody tr").filter(has=p.get_by_role("cell",name=label,exact=True))
            expect(row.get_by_role("cell",name=value,exact=True)).to_be_visible()
        self.assertEqual(p.locator("#messages .message.user").count(),0)
        # The confirmed delivered-volume basis remains selectable in both
        # interfaces when net material demand cannot be established for WB.
        p.goto("/app/?section=planning");self.ready()
        p.locator("#season-source").select_option("wb")
        expect(p.locator("#season-metric")).to_be_visible()
        p.locator("#season-metric").select_option("delivered")
        # A section URL deliberately opens the work surface. Restore the
        # assistant using the actual user control before the chat scenario.
        if not p.locator("#assistant-form textarea").is_visible():
            p.locator("#toggle-helper").click()
        card=self.ask("план закупок маркетплейсов")
        card.get_by_role("combobox",name="Источник",exact=True).select_option("wb")
        card.get_by_role("combobox",name="Основание плана",exact=True).select_option("delivered")
        card.get_by_label("История с месяца",exact=True).fill("2026-10")
        card.get_by_label("История по месяц",exact=True).fill("2026-10")
        card.get_by_label("Начало плана",exact=True).fill("2027-10")
        with p.expect_response(lambda r:r.request.method=="POST" and r.url.split("?")[0].endswith("/api/accounting/seasonal/plan")) as calculated:
            card.get_by_role("button",name="Рассчитать план",exact=True).click()
        self.assertEqual(calculated.value.status,200)
        self.assertEqual(calculated.value.request.post_data_json["metric"],"delivered")
        self.assertEqual(calculated.value.json()["metric"],"delivered")
