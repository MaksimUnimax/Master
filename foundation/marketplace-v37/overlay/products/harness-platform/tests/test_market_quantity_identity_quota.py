"""WB identity quota regression through real loopback HTTP and durable SQLite.

JWT claims and seller responses here are synthetic. No test is live API proof.
Only selected harness helpers are reused; its unrelated tests are not inherited.
"""
import base64
import json
import unittest

from platform_core import market_quantity as q
from platform_core.market_quantity_runtime import Backend
from tests import test_market_quantity_runtime as runtime_fixtures
from tests.fixtures.market_quantity_cases import response_for


class IdentityQuota(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime_fixtures.Runtime.asyncSetUp
    asyncTearDown = runtime_fixtures.Runtime.asyncTearDown
    job = runtime_fixtures.Runtime.job
    step = runtime_fixtures.Runtime.step

    def jwt(self, **changes):
        claims = {"acc": 3, "for": "self", "t": False, "sid": "test-seller-uuid",
                  "exp": int(self.clock()+172800), "s": (1 << 1) | (1 << 2) | (1 << 13)}
        claims.update(changes)
        encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return "header."+encoded+".synthetic-signature"

    def create_identity(self, **claims):
        saved = self.links.save(self.token, None, "wb", "WB identity fixture", {"token": self.jwt(**claims)})
        with self.identity._write() as db:
            jid = q.enqueue_identity(db, self.ws, saved["id"])
        return jid, saved["id"]

    def context(self, jid):
        job = self.job(jid)
        encrypted = self.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?", (job["owner_cid"],)).fetchone()[0]
        fields = self.links.unpack(self.ws, job["owner_cid"], "wb", encrypted)
        return self.backend.context(job, fields)

    def refresh(self, jid):
        with self.identity._write() as db:
            q.market_sync_control(db, self.ws, jid, "retry")

    async def verified_identity(self, **claims):
        jid, cid = self.create_identity(**claims)
        self.assertEqual(self.context(jid)["token_class"], "base")
        await self.step(jid)
        self.assertEqual(self.job(jid)["state"], "ready")
        self.assertEqual(len(self.lab.events), 1)
        return jid, cid, self.lab.events[0]["at"]

    async def test_same_generation_personal_refresh_uses_60_seconds_without_early_http(self):
        jid, cid, first = await self.verified_identity()
        self.refresh(jid)
        self.assertEqual(self.context(jid)["token_class"], "personal")
        self.clock.advance(first+1)
        await self.step(jid)
        self.assertEqual(len(self.lab.events), 1, "Identity promotion must retain the first request time")
        pending = self.job(jid)
        self.assertEqual(pending["state"], "waiting_retry")
        self.assertGreaterEqual(pending["due"], first+60)
        self.assertLessEqual(pending["due"], first+61)
        self.clock.advance(first+59)
        self.assertIsNone(self.backend.claim(job_id=jid))
        self.clock.advance(first+60.01)
        await self.step(jid)
        self.assertEqual(self.job(jid)["state"], "ready")
        self.assertEqual(len(self.lab.events), 2)
        self.assertGreaterEqual(self.lab.events[1]["at"]-first, 60)
        self.assertEqual(self.job(jid)["owner_cid"], cid)

    async def test_persisted_provisional_daily_quota_wait_is_reassessed_after_restart(self):
        jid, _, first = await self.verified_identity()
        self.refresh(jid)
        # Reproduce a checkpoint saved by the prior implementation: no HTTP
        # was sent; a provisional base quota incorrectly delayed this refresh.
        with self.identity._write() as db:
            db.execute("UPDATE market_data_tasks SET state='waiting_retry',due=? WHERE id=?", (first+86400, jid))
            q._event(db, jid, "waiting_retry", code="quota_wait", due=first+86400, now=self.clock())
        self.clock.advance(first+61)
        self.backend = Backend(self.state, clock=self.clock, jitter=0)
        await self.step(jid)
        self.assertEqual(len(self.lab.events), 2)
        self.assertEqual(self.job(jid)["state"], "ready")
        self.assertLess(self.lab.events[-1]["at"]-first, 120)

    async def test_authenticated_promotion_preserves_explicit_server_cooldown(self):
        def server_signal(event):
            response = response_for("WB-01", self.lab.spec, self.lab.context)
            response["headers"] = {"Retry-After": "120000", "X-Ratelimit-Remaining": "0"}
            return response
        self.lab.fault = server_signal
        jid, _, first = await self.verified_identity()
        self.lab.fault = None
        self.refresh(jid)
        self.clock.advance(first+61)
        await self.step(jid)
        self.assertEqual(len(self.lab.events), 1)
        self.assertGreaterEqual(self.job(jid)["due"], first+120000)
        self.assertEqual(self.job(jid)["state"], "waiting_retry")
        self.backend = Backend(self.state, clock=self.clock, jitter=0)
        self.clock.advance(first+119999)
        self.assertIsNone(self.backend.claim(job_id=jid))

    async def test_personal_refresh_429_and_explicit_retry_keep_retry_after(self):
        jid, _, first = await self.verified_identity()
        self.refresh(jid)
        self.clock.advance(first+61)
        self.lab.fault = lambda event: {"status_code": 429, "headers": {"Retry-After": "300"}, "payload": {}}
        await self.step(jid)
        delayed = self.job(jid)
        self.assertEqual(delayed["rate_limits"], 1)
        self.assertGreaterEqual(delayed["due"], self.clock()+300)
        self.refresh(jid)
        self.backend = Backend(self.state, clock=self.clock, jitter=0)
        self.clock.advance(delayed["due"]-1)
        self.assertIsNone(self.backend.claim(job_id=jid))
        self.assertEqual(len(self.lab.events), 2)
        self.lab.fault = None
        self.clock.advance(delayed["due"]+.001)
        await self.step(jid)
        self.assertEqual(self.job(jid)["state"], "ready")
        self.assertGreaterEqual(self.lab.events[-1]["at"]-self.lab.events[-2]["at"], 300)

    async def test_rotated_key_cannot_reuse_prior_generation_identity_proof(self):
        jid, cid, first = await self.verified_identity()
        self.links.update(self.token, None, cid, 1, {"token": self.jwt(exp=int(first+259200))})
        with self.identity._write() as db:
            rotated = q.enqueue_identity(db, self.ws, cid, refresh=True)
        self.assertEqual(self.job(rotated)["key_version"], 2)
        self.assertEqual(self.context(rotated)["token_class"], "base")
        self.assertTrue(self.context(rotated)["seller"].startswith("unverified:"))
        self.assertEqual(len(self.lab.events), 1)

    async def test_authenticated_seller_mismatching_jwt_sid_keeps_base_limit(self):
        jid, _, first = await self.verified_identity(sid="another-seller-uuid")
        self.refresh(jid)
        self.assertEqual(self.context(jid)["token_class"], "base")
        self.clock.advance(first+61)
        await self.step(jid)
        self.assertEqual(len(self.lab.events), 1)
        self.assertGreaterEqual(self.job(jid)["due"], first+86400)

    async def test_expired_token_cannot_promote_previously_verified_identity(self):
        jid, _, first = await self.verified_identity(exp=int(self.clock()+120))
        self.refresh(jid)
        self.clock.advance(first+121)
        self.assertEqual(self.context(jid)["token_class"], "base")
        await self.step(jid)
        self.assertEqual(len(self.lab.events), 1)
        self.assertGreaterEqual(self.job(jid)["due"], first+86400)


if __name__ == "__main__":
    unittest.main()
