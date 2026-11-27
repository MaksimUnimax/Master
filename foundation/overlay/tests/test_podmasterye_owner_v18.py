"""v18 owner regressions: isolated database and signed synthetic Telegram consent."""
import os,re,hashlib,hmac,time
from urllib.parse import urlencode,parse_qs,urlsplit
from unittest.mock import patch,AsyncMock
from tests.test_podmasterye_market_links import Integrations,CONFIG,TG
from platform_core import telegram_api

class OwnerV18(Integrations):
    def test_proxy_config_preserved_and_asset_cache_private(self):
        fields={"auth_mode":"widget","bot_token":"123456789:fixture-token-not-real-123456789","bot_username":"example_fixture_bot"}
        with patch.dict(os.environ,{"PODMASTERYE_TELEGRAM_PROXY_PORT":"18765"}):
            r=self.c.post(CONFIG,headers=self.h("admin"),json=fields)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(telegram_api.Config.load().proxy_port,18765)
            self.assertEqual(self.app.state.telegram.config.proxy_port,18765)
        self.login("admin")
        page=self.c.get("/admin")
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.headers["cache-control"],"no-store")
        self.assertIn("app;dur=",page.headers["server-timing"])
        src=re.search(r'(/assets/podmasterye-admin\.js\?v=[0-9a-f]{24})',page.text).group(1)
        self.assertEqual(self.c.get(src).headers["cache-control"],"private, max-age=31536000, immutable")
        self.assertEqual(self.c.get(src.split("?")[0]+"?v=wrong").headers["cache-control"],"no-store")
        self.assertEqual(self.c.get("/api/admin/provider-balances").headers["cache-control"],"no-store")

    def test_failed_delivery_does_not_bind(self):
        fields={"auth_mode":"widget","bot_token":"123456789:fixture-token-not-real-123456789","bot_username":"example_fixture_bot"}
        self.assertEqual(self.c.post(CONFIG,headers=self.h("admin"),json=fields).status_code,200)
        h=self.login()
        challenge=self.c.post(TG+"/connect",headers=h,json={}).json()["url"]
        state=parse_qs(urlsplit(challenge).query)["state"][0]
        user={"id":1234567,"auth_date":int(time.time()),"first_name":"Fixture"}
        raw="\n".join(f"{k}={user[k]}" for k in sorted(user))
        user["hash"]=hmac.new(hashlib.sha256(fields["bot_token"].encode()).digest(),raw.encode(),hashlib.sha256).hexdigest()
        with patch.object(telegram_api,"send",new_callable=AsyncMock,side_effect=telegram_api.DeliveryError("unknown")):
            r=self.c.post("/api/telegram/complete",headers=h,json={"state":state,"user":user})
        self.assertEqual(r.status_code,409,r.text)
        self.assertIn("подтвердить доставку",r.text)
        self.assertFalse(self.c.get(TG,headers=self.h()).json()["linked"])
