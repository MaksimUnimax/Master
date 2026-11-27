"""Built-in timer acceptance through the real isolated HTTP + native application.

No paid provider is configured. Reports create no coin attempt; Telegram remains disconnected.
The same checks can be run against Chromium and Opera using the existing
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH fixture setting.
"""
import json
import time
import unittest
from uuid import uuid4

from playwright.sync_api import expect
import test_podmasterye_independent_ui as fixture
from tests.auth_fixture import email_opted_out
from platform_core import podmasterye_timer as timer
from platform_core import podmasterye_workshops as workshops


class WorkshopTimerUI(unittest.TestCase):
    # Reuse only the isolated app/browser fixture, not its unrelated test cases.
    setUpClass = fixture.IndependentUI.__dict__["setUpClass"]
    setUp = fixture.IndependentUI.setUp
    tearDown = fixture.IndependentUI.tearDown
    sign_in = fixture.IndependentUI.sign_in
    ready = fixture.IndependentUI.ready
    call = fixture.IndependentUI.call

    def open_timer(self):
        self.page.locator('nav button[data-page="schedule"]').click()
        host = self.page.locator("#timer-app")
        expect(host.locator("[data-new]")).to_be_visible()
        return host

    def create_ui(self, title="Проверка расписания", report="profit", kind="weekly"):
        host = self.open_timer()
        host.locator("[data-new]").click()
        host.locator('[name="title"]').fill(title)
        host.locator('[name="report"]').select_option(report)
        host.locator('[name="period"]').select_option("today")
        host.locator('[name="frequency"]').select_option(kind)
        host.locator('[name="zone"]').fill("Asia/Qyzylorda")
        host.locator('[name="time"]').fill("09:00, 18:00")
        host.locator('[name="channel_telegram"]').check()
        host.locator('[data-form] button[type="submit"]').click()
        expect(host.locator("[data-preview-text]")).to_contain_text("0 монет")
        host.locator("[data-confirm]").click()
        expect(host.locator("[data-status]")).to_have_text("Расписание сохранено.")
        return host, host.locator(".pm-timer-event").filter(has_text=title)

    def test_member_preview_edit_run_delivery_and_download(self):
        self.sign_in()
        host, card = self.create_ui()
        expect(card).to_contain_text("Активен")
        card.get_by_role("button", name="Изменить", exact=True).click()
        host.locator('[name="frequency"]').select_option("monthly")
        host.locator('[name="monthday"]').fill("31")
        host.locator('[data-form] button[type="submit"]').click()
        expect(host.locator("[data-preview-rule]")).to_contain_text("Ежемесячно")
        host.locator("[data-confirm]").click()
        expect(card).to_contain_text("Ежемесячно")
        card.get_by_role("button", name="Пауза", exact=True).click()
        expect(card).to_contain_text("На паузе")
        card.get_by_role("button", name="Возобновить", exact=True).click()
        expect(card).to_contain_text("Активен")
        card.get_by_role("button", name="Запустить сейчас", exact=True).click()
        deadline = time.monotonic() + 15
        while "Telegram не подключён" not in host.locator("[data-runs]").inner_text():
            if time.monotonic() > deadline:
                self.fail(host.locator("[data-runs]").inner_text())
            host.get_by_role("button", name="Обновить", exact=True).click()
            self.page.wait_for_timeout(100)
        expect(host.locator("[data-runs]")).to_contain_text("Чат: Доставлено")
        expect(host.locator("[data-runs]")).to_contain_text("0 монет")
        with self.page.expect_download() as result:
            host.get_by_role("link", name="Скачать полный результат").click()
        with open(result.value.path(), encoding="utf8") as stream:
            value = json.load(stream)
        self.assertEqual(value["report"]["type"], "profit")
        # Reopening the mounted panel keeps the report form and authoritative
        # timer history. The main transcript is a single assistant exchange.
        self.page.reload(); self.ready(); host = self.open_timer()
        card = host.locator(".pm-timer-event").filter(has_text="Проверка расписания")
        card.get_by_role("button", name="История", exact=True).click()
        expect(host.locator(".pm-timer-run")).to_have_count(1)
        card.get_by_role("button", name="Отменить", exact=True).click()
        expect(card).to_contain_text("Отменён")
        card.get_by_role("button", name="История", exact=True).click()
        expect(host.locator(".pm-timer-run")).to_have_count(1)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"), 391)
        with self.app.state.identity._lock:
            db = self.app.state.identity._db
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pm_turns WHERE rid LIKE 'timer_%'").fetchone()[0], 1)

    def fixture_event(self, token, title):
        store = self.app.state.identity
        chat = workshops.choose_chat(store, token)["chatId"]
        scope = store.resolve_chat(token, chat)
        raw = {"title": title, "kind": "report", "schedule": {"kind": "once", "zone": "UTC", "at": "2099-01-01T10:00:00Z"}, "channels": ["chat"], "report": {"report": "tasks", "period": "today"}}
        with store._write() as db:
            preview = timer.prepare(db, scope, uuid4().hex, raw)
            return timer.confirm(db, scope, uuid4().hex, preview["id"], preview["revision"], preview["receipt"])

    def test_admin_queue_pagination_pause_and_member_access(self):
        store = self.app.state.identity
        owner = store.login(self.login, fixture.P)
        events = [self.fixture_event(owner, "Личная задача " + str(i)) for i in range(21)]
        self.sign_in()
        self.call("/api/admin/timer", expected=403, workshop=False)
        self.call("/api/admin/timer/pause", {"requestId": uuid4().hex, "eventId": events[-1]["id"], "revision": 1}, expected=403, workshop=False)
        # Already-authenticated fixture sessions isolate this test's subject:
        # admin timer controls. Real admin MFA is covered by auth acceptance.
        admin = "timer_admin_" + uuid4().hex[:8]
        store.create_account(admin, fixture.P); email_opted_out(store, admin); store.set_admin(admin, True)
        token = store.login(admin, fixture.P)
        self.ctx.clear_cookies()
        self.ctx.add_cookies([{"name": "podmaster_local_session", "value": token, "url": self.origin, "httpOnly": True, "sameSite": "Strict"}])
        self.assertEqual(self.page.goto("/admin/timer").status, 200)
        expect(self.page.locator("#admin-timer-status")).to_have_text("Состояние обновлено.")
        expect(self.page.locator("#admin-timer-rows tr")).to_have_count(20)
        expect(self.page.locator("#admin-timer-rows")).not_to_contain_text("Личная задача")
        self.page.locator("#admin-timer-next").click()
        expect(self.page.locator("#admin-timer-page")).to_contain_text("Страница 2")
        self.page.locator("#admin-timer-prev").click()
        expect(self.page.locator("#admin-timer-page")).to_contain_text("Страница 1")
        row = self.page.locator("#admin-timer-rows tr").filter(has_text=events[-1]["id"])
        row.get_by_role("button", name="Приостановить").click()
        expect(row).to_contain_text("На паузе")
        self.page.reload()
        expect(row).to_contain_text("На паузе")
        with store._lock:
            self.assertEqual(store._db.execute("SELECT COUNT(*) FROM timer_admin_actions WHERE event=?", (events[-1]["id"],)).fetchone()[0], 1)
        self.ctx.clear_cookies()
        self.assertEqual(self.ctx.request.get(self.origin + "/api/admin/timer").status, 401)


if __name__ == "__main__":
    unittest.main()
