"""Browser acceptance of sticky navigation and successful/failed Telegram callback."""
import hashlib,hmac,time
from urllib.parse import urlencode,parse_qs,urlsplit
from unittest.mock import patch,AsyncMock
from playwright.sync_api import expect
from platform_core import telegram_api
from test_podmasterye_independent_ui import IndependentUI

class OwnerV18UI(IndependentUI):
    def test_owner_navigation_and_telegram(self):
        self.sign_in()
        p=self.page
        expect(p.locator("#close-helper")).to_have_text("Мастерская")
        p.locator("#close-helper").click()
        expect(p.locator("#assistant-pane")).not_to_be_visible()
        expect(p.locator(".pm-work-header strong")).to_have_text("Мастерская")
        self.nav("settings")
        p.set_viewport_size({"width": 1100, "height": 550})
        p.evaluate("document.querySelector('#work-pane').scrollTop=100000")
        self.assertGreater(p.locator("#work-pane").evaluate("e=>e.scrollTop"),0)
        expect(p.locator("#expand-work")).to_be_in_viewport()
        p.locator("#expand-work").click()
        expect(p.locator("#assistant-pane")).to_be_visible()
        self.nav("integrations")
        wid=p.locator("#workshop-select").input_value()
        cfg=telegram_api.Config("123456789",None,"123456789:fixture-token-not-real-123456789",None,"example_fixture_bot")
        with patch.object(self.app.state.telegram,"config",cfg):
            def callback():
                url=self.call("/api/integrations/telegram/connect",{},workshop=False)["url"]
                state=parse_qs(urlsplit(url).query)["state"][0]
                user={"id":"1234567","auth_date":str(int(time.time())),"first_name":"Fixture"}
                raw="\n".join(f"{k}={user[k]}" for k in sorted(user))
                user["hash"]=hmac.new(hashlib.sha256(cfg.token.encode()).digest(),raw.encode(),hashlib.sha256).hexdigest()
                return "/telegram/return?"+urlencode({"state":state,**user})
            with patch.object(telegram_api,"send",new_callable=AsyncMock,side_effect=telegram_api.DeliveryError("unknown")):
                p.goto(callback())
                expect(p.locator("[role=status]")).to_contain_text("подтвердить доставку")
                self.assertIn("/telegram/return",p.url)
            p.goto("/app/?section=integrations")
            self.ready()
            # Fresh authorization must have a fresh signed receipt.
            time.sleep(1.1)
            p.evaluate("(w)=>sessionStorage.setItem('podmasterye.telegram.return','/app/?section=integrations&workshop='+w)",wid)
            with patch.object(telegram_api,"send",new_callable=AsyncMock,return_value=1) as send:
                p.goto(callback())
                expect(p).to_have_url(self.origin+"/app/?section=integrations&workshop="+wid)
                self.ready()
                expect(p.locator("#pm-telegram-status")).to_contain_text("Telegram подключён")
                self.assertEqual(send.await_count,1)
