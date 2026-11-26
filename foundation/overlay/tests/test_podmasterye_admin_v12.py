"""Reference admin acceptance on an isolated database, no external services."""
from datetime import date
from unittest.mock import patch,AsyncMock
from tests.test_podmasterye_market_links import Integrations
from platform_core import podmasterye_visits as visits,provider_balances,metrika_report

class AdminPages(Integrations):
    def test_separate_pages_and_permission(self):
        paths=["/admin","/admin/keys","/admin/models","/admin/telegram","/admin/coins","/admin/usage","/admin/matrix","/admin/statistics","/admin/visits"]
        for path in paths:
            self.c.cookies.clear()
            self.assertEqual(self.c.get(path).status_code,401,path)
            self.login("owner")
            self.assertEqual(self.c.get(path).status_code,403,path)
            self.login("admin")
            r=self.c.get(path);self.assertEqual(r.status_code,200,(path,r.text))
            self.assertIn('href="'+path+'" aria-current="page"',r.text)
            self.assertNotIn("OpenRouter",r.text)
        self.assertEqual(self.c.get("/app/?section=admin",follow_redirects=False).headers["location"],"/admin")
        self.assertEqual(self.c.get("/api/admin/provider-balances",headers=self.h("other")).status_code,403)
        self.assertEqual(set(self.c.get("/api/admin/provider-balances",headers=self.h("admin")).json()["providers"]),{"deepseek"})
        self.assertEqual(self.c.post("/api/admin/provider-balances/settings",headers=self.h("admin"),json={"intervalMinutes":23}).status_code,200)
        self.assertEqual(self.c.get("/api/admin/provider-balances",headers=self.h("admin")).json()["intervalMinutes"],23)
    def test_visits_separate_counter(self):
        self.login("admin")
        self.assertNotIn("114504756",self.c.get("/admin/visits").text)
        self.assertIn(visits.DOMAIN,metrika_report.PAGE_FILTER)
        self.assertNotIn("octoport.ru",metrika_report.PAGE_FILTER)
        self.assertEqual(self.c.post("/admin/visits",headers={"Origin":"https://podmaster.example"},data={"counter":"114504756","token":"fixture-token"}).status_code,400)
        fixture={"totals":{"visits":17,"visitors":12,"pageviews":34,"bounce_percent":10,"average_seconds":55},"date_from":"2026-11-01","date_to":"2026-11-26","sections":{"daily":{"title":"По дням","rows":[]},"sources":{"title":"Источники трафика","rows":[]}},"notes":[]}
        with patch.object(visits,"get_report",return_value=fixture) as report:
            r=self.c.post("/admin/visits",headers={"Origin":"https://podmaster.example"},data={"counter":"987654321","token":"fixture-token"},follow_redirects=False)
            self.assertEqual(r.status_code,303,r.text)
            self.assertEqual(report.call_args.args[0],"987654321")
            self.assertTrue(report.call_args.kwargs["summary"])
            r=self.c.get("/admin/visits?period=custom&date_from=2026-11-01&date_to=2026-11-26")
            self.assertEqual(r.status_code,200,r.text);self.assertIn("Источники трафика",r.text);self.assertIn(">17</dd>",r.text)
            self.assertNotIn("fixture-token",r.text)
            self.assertEqual(report.call_args.args[2:],("2026-11-01","2026-11-26"))
        self.assertEqual(self.app.state.pm_metrika_path.stat().st_mode&0o777,0o600)
        self.login("owner")
        self.assertEqual(self.c.get("/admin/visits").status_code,403)
