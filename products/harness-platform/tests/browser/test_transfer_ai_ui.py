"""New AI settings interact with the real scoped HTTP routes; no provider egress."""
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI, P


class TransferAIUI(IndependentUI):
    @classmethod
    def setUpClass(cls):
        isolated = tempfile.TemporaryDirectory(prefix="pm-ai-keys-")
        cls.addClassCleanup(isolated.cleanup)
        settings = patch.dict(os.environ, {"HARNESS_PROVIDER_KEYS_DIR": str(Path(isolated.name) / "keys"),
            "HARNESS_OPENROUTER_ENABLED": "0", "HARNESS_WEB_ENABLED": "0"})
        settings.start()
        cls.addClassCleanup(settings.stop)
        super().setUpClass()

    def test_account_profile_and_admin_provider_forms(self):
        self.sign_in()
        self.nav("settings")
        p = self.page
        host = p.locator("[data-pm-ai-settings]")
        style = host.locator('[data-ai="preferences"]')
        expect(style.locator('[name="address"]')).to_have_value("на вы")
        style.locator('[name="address"]').select_option("на ты")
        style.locator('[name="tone"]').select_option("по-деловому")
        style.locator('[name="detail"]').select_option("подробно")
        style.get_by_role("button", name="Сохранить", exact=True).click()
        expect(host.locator('[data-ai="status"]')).to_have_text("Настройки общения сохранены.")
        self.assertEqual(self.call("/api/assistant/preferences", workshop=False)["current"]["address"], "на ты")
        p.reload()
        self.ready()
        self.nav("settings")
        expect(style.locator('[name="address"]')).to_have_value("на ты")
        style.get_by_role("button", name="По умолчанию", exact=True).click()
        expect(style.locator('[name="address"]')).to_have_value("на вы")
        expect(host.locator('[data-ai="image-notice"]')).to_contain_text("Нет доступных генераторов")
        host.scroll_into_view_if_needed()
        p.screenshot(path=str(self.evidence / "ai-settings-desktop.png"), animations="disabled")
        p.set_viewport_size({"width": 390, "height": 844})
        host.scroll_into_view_if_needed()
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth * Number(getComputedStyle(document.documentElement).zoom)"), 391)
        p.screenshot(path=str(self.evidence / "ai-settings-mobile.png"), animations="disabled")

        # The server fixture issues its normal administrator session. The
        # browser never receives a saved provider secret from any API response.
        self.app.state.identity.set_admin(self.login, True)
        token = self.app.state.identity.login(self.login, P)
        self.ctx.add_cookies([{"name": "podmaster_local_session", "value": token,
            "url": self.origin, "httpOnly": True, "sameSite": "Strict"}])
        p.set_viewport_size({"width": 1440, "height": 1000})
        p.goto("/admin/keys")
        form = p.locator('[data-pm-ai-admin="keys"] form[data-provider="openrouter"]')
        expect(form).to_be_visible()
        form.locator('[name="key"]').fill("sk-or-browser-fixture")
        form.get_by_role("button", name="Сохранить ключ OpenRouter", exact=True).click()
        expect(form.locator('[name="key"]')).to_have_value("")
        expect(p.locator('[data-ai="key-state-openrouter"]')).to_contain_text("ключ сохранён")
        self.assertNotIn("sk-or-browser-fixture", str(self.call("/api/admin/provider-keys", workshop=False)))
        p.screenshot(path=str(self.evidence / "ai-provider-keys.png"), animations="disabled")

        models = {"deepseek-flash": {"id": "deepseek-flash", "name": "DeepSeek Flash", "efforts": ["off", "high"], "defaultEffort": "high"}}
        with patch("platform_core.chat_defaults.available_models", new=AsyncMock(return_value=models)):
            p.goto("/admin/models")
            model_form = p.locator('[data-ai="default-model"]')
            expect(model_form.locator('[name="model"]')).to_have_value("deepseek-flash")
            model_form.locator('[name="effort"]').select_option("off")
            model_form.get_by_role("button", name="Установить по умолчанию").click()
            expect(p.locator('[data-ai="default-current"]')).to_contain_text("Без рассуждений")
            permission = p.locator('[data-ai="admin-model-list"] button').first
            permission.click()
            expect(p.locator('[data-ai="admin-model-list"] button').first).to_have_text("Разрешить")
            expect(model_form.get_by_role("button", name="Установить по умолчанию")).to_be_disabled()
            p.screenshot(path=str(self.evidence / "ai-models-admin.png"), animations="disabled")
        p.goto("/admin")
        balances = p.locator('[data-pm-ai-admin="balances"]')
        expect(balances.locator('[data-ai="balances"]')).to_contain_text("OpenRouter")
        interval = balances.locator('[data-ai="balance-interval"]')
        interval.locator('[name="intervalMinutes"]').fill("17")
        interval.get_by_role("button", name="Сохранить интервал").click()
        expect(interval.locator('[name="intervalMinutes"]')).to_have_value("17")
        self.assertEqual(self.call("/api/admin/provider-balances", workshop=False)["intervalMinutes"], 17)
        p.screenshot(path=str(self.evidence / "ai-balances-admin.png"), animations="disabled")

