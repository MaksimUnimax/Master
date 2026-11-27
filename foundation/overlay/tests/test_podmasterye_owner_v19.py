"""v19 regressions: private initial state and distinct Telegram setup/binding."""
import json,re
from tests.test_podmasterye_market_links import Integrations,CONFIG
from platform_core.podmasterye_admin_web import shell

class OwnerV19(Integrations):
    def test_initial_payload_matches_read_routes(self):
        self.login("admin")
        for page in ("","keys","models","telegram","coins","usage","matrix"):
            r=self.c.get("/admin"+("/"+page if page else ""))
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.headers["cache-control"],"no-store")
            raw=re.search(r'<script type="application/json" id="pm-admin-initial">(.*?)</script>',r.text,re.S).group(1)
            initial=json.loads(raw)
            self.assertTrue(initial,page)
            for url,value in initial.items():
                self.assertEqual(value,self.c.get(url).json(),url)
        self.login("owner")
        self.assertEqual(self.c.get("/admin/telegram").status_code,403)
        self.assertEqual(self.c.get(CONFIG).status_code,403)
        self.login("admin")
        r=self.c.get("/admin/statistics")
        self.assertRegex(r.text,r'/assets/admin\.css\?v=[a-f0-9]{24}')
        self.assertNotIn("<function nav at",r.text)
    def test_telegram_identity_visible_without_credentials(self):
        h=self.h("admin")
        fields={"auth_mode":"widget","bot_token":"123456789:fixture-token-not-real-123456789","bot_username":"example_fixture_bot"}
        d=self.c.post(CONFIG,headers=h,json=fields)
        self.assertEqual(d.status_code,200,d.text)
        self.assertTrue(d.json()["configured"])
        self.assertFalse(d.json()["linked"])
        self.assertEqual(d.json()["bot_username"],"example_fixture_bot")
        self.assertTrue(d.json()["token_saved"])
        self.assertNotIn(fields["bot_token"],d.text)
        self.login("admin")
        page=self.c.get("/admin/telegram")
        self.assertIn("example_fixture_bot",page.text)
        self.assertNotIn(fields["bot_token"],page.text)
        with self.app.state.identity._write() as db:
            from platform_core.identity import _principal
            _,account=_principal(db,self.tokens["admin"])
            db.execute("INSERT INTO telegram_recipients(workspace,bot,recipient) VALUES(?,?,?)",(account,"123456789",9876543))
        d=self.c.get(CONFIG).json()
        self.assertTrue(d["linked"])
        self.assertNotIn("recipient",d)
    def test_html_initial_escapes_script_terminator(self):
        r=shell("keys","Ключи","",initial_data={"x":"</script><img src=x>"})
        html=r.body.decode()
        self.assertNotIn("</script><img",html)
        raw=re.search(r'id="pm-admin-initial">(.*?)</script>',html,re.S).group(1)
        self.assertEqual(json.loads(raw),{"x":"</script><img src=x>"})
