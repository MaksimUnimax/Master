"""Actual browser quota and published guest catalogue."""
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI

class GuestUI(IndependentUI):
    def test_guest_catalog_quota_and_reload(self):
        p=self.page;p.goto("/")
        if p.locator("#cookie-choice").is_visible():p.locator("#cookie-decline").click()
        q=p.locator("#guest-quota");f=p.locator("#guest-form");field=f.locator("textarea[name=text]")
        expect(q).to_contain_text("12 из 12")
        self.assertEqual(p.locator("#attachment-picker,#attach-file,.octo-voice").count(),0)
        for i in range(12):
            field.fill("Что ты умеешь?" if i==0 else "13" if i==1 else "Сколько стоит монета?")
            f.get_by_role("button").click()
            expect(q).to_contain_text(f"{11-i} из 12")
            if i==0:expect(p.locator("#guest-messages")).to_contain_text("17. Telegram")
            if i==1:expect(p.locator("#guest-messages")).to_contain_text("только после входа")
        expect(field).to_be_disabled();expect(f.get_by_role("button")).to_be_disabled()
        expect(p.locator("#guest-limit")).to_be_visible()
        p.reload();expect(q).to_contain_text("0 из 12")
        expect(p.locator("#guest-messages .message.user")).to_have_count(12)
        expect(field).to_be_disabled()
        self.assertFalse(self.errors,self.errors)
