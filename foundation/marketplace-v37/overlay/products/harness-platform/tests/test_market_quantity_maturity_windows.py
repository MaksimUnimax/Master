"""Rolling WB mature samples via the real queue, adapter, TCP and SQLite.

The clock and provider values are synthetic. No API call is sent to WB. Four
orders and one loss per day make independently requested intervals consistent;
the test never manufactures normalized rows or ready coverage in the database.
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest

from platform_core import market_quantity as q
from platform_core import market_quantity_registry as registry
from platform_core import podmasterye_market_analytics as analytics
from tests import test_market_quantity_runtime as runtime
from tests import test_market_quantity_identity_quota as identity_quota
from tests.fixtures import market_quantity_cases as cases


class MatureWindowLifecycle(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime.Runtime.asyncSetUp
    asyncTearDown = runtime.Runtime.asyncTearDown
    job = runtime.Runtime.job
    step = runtime.Runtime.step
    finish = runtime.Runtime.finish
    jwt = identity_quota.IdentityQuota.jwt
    create_identity = identity_quota.IdentityQuota.create_identity
    context = identity_quota.IdentityQuota.context
    verified_identity = identity_quota.IdentityQuota.verified_identity

    def provider_response(self, event):
        if event["template"] != "WB-03":
            return None
        ctx = self.lab.context
        days = (date.fromisoformat(ctx["to"]) - date.fromisoformat(ctx["from"])).days + 1
        return {"status_code": 200, "headers": {}, "payload": {"data": {"products": [
            cases.wb_funnel(ctx, ordered=4*days, lost=days, buyout=3*days)
        ]}}}

    async def drain_funnel(self, sid):
        jobs = self.identity._db.execute("SELECT id FROM market_data_tasks WHERE store=? AND source='WB-03' AND state NOT IN ('ready','no_data_confirmed') ORDER BY since", (sid,)).fetchall()
        for (jid,) in jobs:
            done = await self.finish(jid, restart=True)
            self.assertIn(done["state"], q.TERMINAL, done)

    def evidence(self, sid, day):
        snapshot = q.quantity_snapshot(self.identity._db, self.ws, sid)
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        report = analytics.loss_rates_snapshot(snapshot, as_of=now)
        row = next(r for r in report["rows"] if r["sku"] == "101")
        return {"day": day, "at": now.isoformat(), "from": row["from"], "to": row["to"],
                "value": row["value"], "numerator": row["numerator"], "denominator": row["denominator"],
                "physical_return_rate": row["physical_return_rate"], "coverage": row["coverage"],
                "funnel_windows": [dict(zip(("from", "to", "state"), r)) for r in self.identity._db.execute(
                    "SELECT since,until,state FROM market_data_tasks WHERE store=? AND source='WB-03' ORDER BY since,until", (sid,))],
                "actual_loopback_http": sum(e["template"] == "WB-03" for e in self.lab.events)}

    def save_evidence(self, scenario, records):
        path = os.environ.get("MARKET_MATURITY_EVIDENCE")
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = json.loads(target.read_text()) if target.exists() else {}
            existing[scenario] = records
            target.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n")

    async def start_store(self):
        self.lab.fault = self.provider_response
        _, cid, _ = await self.verified_identity(exp=int(self.clock()+120*86400))
        sid = q.selected_stores(self.identity._db, self.ws, cid)[0]["id"]
        return sid

    async def test_seed_preserves_exact_retention_and_maturity_boundaries(self):
        sid = await self.start_store()
        today = q.today(self.clock())
        days = (registry.get_template("WB-03")["history"]["max_lookback_days"], analytics.MATURITY_DAYS)
        windows = {(a, b) for a, b in self.identity._db.execute("SELECT since,until FROM market_data_tasks WHERE store=? AND source='WB-03'", (sid,))}
        for n in days:
            with self.subTest(days=n):
                edge = str(today-timedelta(days=n))
                self.assertIn((edge, edge), windows, "Indivisible 30-day reports cannot preserve this daily rolling boundary")

    async def test_daily_queue_keeps_365_mature_days_at_day29_and_day30(self):
        sid = await self.start_store()
        await self.drain_funnel(sid)
        records = []
        for day in range(1, 31):
            due = self.identity._db.execute("SELECT next_due FROM market_data_schedule WHERE store=?", (sid,)).fetchone()[0]
            self.clock.advance(due + .01)
            self.backend.maintenance_once()
            await self.drain_funnel(sid)
            if day in (29, 30):
                records.append(self.evidence(sid, day))
        self.save_evidence("continuous", records)
        for item in records:
            with self.subTest(day=item["day"]):
                self.assertEqual(item["value"], "0.25", json.dumps(item, ensure_ascii=False))
                self.assertEqual((item["numerator"], item["denominator"]), (365, 1460))
                self.assertIsNone(item["physical_return_rate"], "Cohort cancelCount still does not prove physical returns")
        self.assertEqual(self.lab.errors, [])

    async def test_missed_retention_day_remains_unknown_after_it_expires(self):
        sid = await self.start_store()
        await self.drain_funnel(sid)
        initial_due = self.identity._db.execute("SELECT next_due FROM market_data_schedule WHERE store=?", (sid,)).fetchone()[0]
        # No scheduler/HTTP work on D1. The missing old singleton is genuinely
        # no longer queryable on D2, even though its enclosing aggregate exists.
        self.clock.advance(initial_due + 86400 + .01)
        self.backend.maintenance_once()
        await self.drain_funnel(sid)
        for day in range(3, 31):
            due = self.identity._db.execute("SELECT next_due FROM market_data_schedule WHERE store=?", (sid,)).fetchone()[0]
            self.clock.advance(due + .01)
            self.backend.maintenance_once()
            await self.drain_funnel(sid)
        record = self.evidence(sid, 30)
        self.save_evidence("missed-day", [record])
        self.assertIsNone(record["value"])
        self.assertFalse(record["coverage"]["complete"])
        self.assertEqual(self.lab.errors, [])


if __name__ == "__main__":
    unittest.main()
