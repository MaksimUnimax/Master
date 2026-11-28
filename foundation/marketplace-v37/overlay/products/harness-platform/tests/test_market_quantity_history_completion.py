"""Known retention boundaries complete only after real persisted source windows."""
from datetime import date
import unittest

from platform_core import market_quantity as q
from tests import test_market_quantity_runtime as runtime
from tests import test_market_quantity_identity_quota as identity_quota


class HistoryCompletion(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=runtime.Runtime.asyncSetUp
    asyncTearDown=runtime.Runtime.asyncTearDown
    job=runtime.Runtime.job
    step=runtime.Runtime.step
    finish=runtime.Runtime.finish
    jwt=identity_quota.IdentityQuota.jwt
    create_identity=identity_quota.IdentityQuota.create_identity
    context=identity_quota.IdentityQuota.context
    verified_identity=identity_quota.IdentityQuota.verified_identity

    async def initial(self):
        # The authenticated personal profile uses the documented personal
        # quota. An opaque fake token correctly remains on the base quota and
        # would move the synthetic clock many days during this full history.
        _,cid,_=await self.verified_identity(exp=int(self.clock()+120*86400))
        sid=q.selected_stores(self.identity._db,self.ws,cid)[0]["id"]
        gid=self.identity._db.execute("SELECT id FROM market_data_groups WHERE source=? AND purpose='initial'",(sid,)).fetchone()[0]
        return sid,gid

    def queued(self,gid):
        return self.identity._db.execute("SELECT j.id FROM market_data_tasks j JOIN market_data_group_tasks g ON g.task_id=j.id WHERE g.group_id=? AND j.state NOT IN ('ready','no_data_confirmed') ORDER BY j.source,j.since DESC",(gid,)).fetchall()

    async def settle(self,gid):
        completed=0
        for _ in range(120):
            jobs=self.queued(gid)
            if not jobs:return completed
            job=self.job(jobs[0][0])
            if job["source"]=="WB-04":
                self.assertGreaterEqual(date.fromisoformat(job["since"]),date(2024,1,29),
                    "Final historical window must be clamped to the documented earliest date")
            done=await self.finish(job["id"])
            self.assertIn(done["state"],q.TERMINAL,done)
            completed+=1
        self.fail("Finite history did not settle")

    async def test_documented_finite_history_reaches_exact_floor_and_completes_group(self):
        sid,gid=await self.initial()
        self.assertNotEqual(q.group_public(self.identity._db,gid,self.ws)["state"],"ready")
        completed=await self.settle(gid)
        self.assertGreater(completed,40,"Exercise every real source window, not fabricated ready flags")
        floor=self.identity._db.execute("SELECT min(j.since) FROM market_data_tasks j JOIN market_data_group_tasks g ON g.task_id=j.id WHERE g.group_id=? AND j.source='WB-04'",(gid,)).fetchone()[0]
        self.assertEqual(floor,"2024-01-29")
        history=self.identity._db.execute("SELECT history_state FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0]
        self.assertEqual(history,"complete")
        self.assertEqual(q.group_public(self.identity._db,gid,self.ws)["state"],"ready")
        self.assertEqual(self.lab.errors,[])

    async def test_confirmed_empty_windows_reach_known_floor_without_early_completion(self):
        sid,gid=await self.initial()
        self.lab.fault=lambda event:{"status_code":204,"headers":{},"body":b""} if event["template"]=="WB-04" else None
        completed=await self.settle(gid)
        self.assertGreater(completed,40)
        rows=self.identity._db.execute("SELECT since,state FROM market_data_tasks WHERE store=? AND source='WB-04'",(sid,)).fetchall()
        self.assertEqual(min(a for a,_ in rows),"2024-01-29")
        self.assertGreater(len(rows),30)
        self.assertEqual({s for _,s in rows},{"no_data_confirmed"})
        self.assertEqual(self.identity._db.execute("SELECT history_state FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],"complete")
        self.assertEqual(q.group_public(self.identity._db,gid,self.ws)["state"],"ready")
        self.assertEqual(self.lab.errors,[])


if __name__=="__main__":unittest.main()
