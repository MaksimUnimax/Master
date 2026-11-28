"""Durable historical continuation across previously collected windows.

Real loopback transport and isolated SQLite use synthetic provider reports.
Assign helpers explicitly: importing Runtime must not duplicate its test suite.
"""
import calendar
import io
import json
import unittest
import zipfile

from platform_core import market_quantity as q
from platform_core.market_quantity_runtime import Backend
from tests import test_market_quantity_runtime as runtime
from tests.fixtures import market_quantity_cases as cases


class HistoryContinuation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=runtime.Runtime.asyncSetUp
    asyncTearDown=runtime.Runtime.asyncTearDown
    create=runtime.Runtime.create
    job=runtime.Runtime.job
    step=runtime.Runtime.step
    finish=runtime.Runtime.finish

    def month_job(self,sid,cid,month):
        first=f"2026-{month:02d}-01"
        last=f"2026-{month:02d}-{27 if month==11 else calendar.monthrange(2026,month)[1]:02d}"
        with self.identity._write() as db:
            return q.enqueue(db,sid,"YM-05",first,last,cid=cid,version=1,
                context={"reason":"previous-user-request","month":first[:7]},now=self.clock())

    async def ready_months(self,months=(11,10,9)):
        first,cid,sid=self.create("YM-05",context={"from":"2026-11-01","to":"2026-11-27","month":"2026-11"})
        jobs={11:first}
        self.assertIn((await self.finish(first))["state"],q.TERMINAL)
        for month in months:
            if month==11:continue
            jid=self.month_job(sid,cid,month);jobs[month]=jid
            self.assertIn((await self.finish(jid))["state"],q.TERMINAL)
        return cid,sid,jobs

    def snapshot_progress(self,jid):
        job=self.job(jid)
        return {k:job[k] for k in ("state","checkpoint","step","epoch","due","receipt","requests","rate_limits")}

    def initial_chain(self,sid,jobs):
        """Persist the exact stalled older shape, not a fabricated ready flag."""
        with self.identity._write() as db:
            gid=q.ensure_group(db,self.ws,sid,purpose="initial",now=self.clock())
            newest=jobs[11];ctx=json.loads(self.job(newest)["context"])
            ctx.update(reason="initial",history_discovery=True,history_boundary=None,group_id=gid)
            db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(q.encode(ctx),newest))
            for jid in jobs.values():db.execute("INSERT OR IGNORE INTO market_data_group_tasks VALUES(?,?)",(gid,jid))
            db.execute("UPDATE market_data_schedule SET initial_version=1,next_due=? WHERE store=?",(self.clock()+86400,sid))
        return gid

    def find_month(self,sid,month):
        return self.identity._db.execute("SELECT id FROM market_data_tasks WHERE store=? AND source='YM-05' AND since=?",
            (sid,f"2026-{month:02d}-01")).fetchall()

    def seed_store(self,sid):
        with self.identity._write() as db:self.backend.seed(db,q.selected_stores(db,self.ws,sid)[0])

    async def test_seed_walks_three_ready_months_without_http_or_report_recreation(self):
        cid,sid,jobs=await self.ready_months()
        before={jid:self.snapshot_progress(jid) for jid in jobs.values()};http=len(self.lab.events)
        self.seed_store(sid)
        august=self.find_month(sid,8)
        self.assertEqual(len(august),1,"Ready November/October/September must not terminate discovery before August")
        self.assertEqual(self.job(august[0][0])["state"],"queued")
        self.assertEqual(len(self.lab.events),http)
        for jid,old in before.items():self.assertEqual(self.snapshot_progress(jid),old)
        self.assertEqual(sum(e["generate"] for e in self.lab.events),3)
        august_id=august[0][0]
        self.assertEqual(json.loads(self.job(august_id)["context"])["month"],"2026-08")
        generated=[]
        def observe(event):
            if event["generate"]:generated.append(dict(self.lab.spec["json"]))
        self.lab.fault=observe
        done=await self.finish(august_id,restart=True)
        self.lab.fault=None
        self.assertEqual(done["state"],"ready")
        self.assertEqual(generated,[{"campaignId":123,"year":2026,"month":8}])
        july=self.find_month(sid,7)
        self.assertEqual(len(july),1)
        self.assertEqual(self.job(july[0][0])["state"],"queued")
        self.assertEqual(json.loads(self.job(july[0][0])["context"])["month"],"2026-07")
        for jid,old in before.items():self.assertEqual(self.snapshot_progress(jid),old)
        self.assertEqual(self.lab.errors,[])

    async def test_pending_report_gains_history_context_without_losing_cooldown_then_restarts(self):
        cid,sid,jobs=await self.ready_months((11,))
        october=self.month_job(sid,cid,10);begin=len(self.lab.events);fired=[]
        def fault(event):
            if event["stage"]=="poll" and not fired:
                fired.append(True)
                return {"status_code":429,"headers":{"Retry-After":"123"},"payload":{}}
        self.lab.fault=fault
        for _ in range(15):
            j=self.job(october)
            if j["due"]>self.clock():self.clock.advance(j["due"])
            await self.step(october)
            if self.job(october)["rate_limits"]:break
        before=self.snapshot_progress(october)
        self.assertEqual(before["state"],"waiting_retry")
        self.assertTrue(json.loads(before["checkpoint"])["report_id"])
        quota=self.identity._db.execute("SELECT * FROM market_data_quota ORDER BY scope").fetchall()
        http=len(self.lab.events)
        self.seed_store(sid)
        self.assertEqual(self.snapshot_progress(october),before)
        self.assertEqual(self.identity._db.execute("SELECT * FROM market_data_quota ORDER BY scope").fetchall(),quota)
        ctx=json.loads(self.job(october)["context"])
        self.assertTrue(ctx.get("history_discovery"),"An existing pending report must inherit continuation")
        self.assertTrue(ctx.get("group_id"))
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        self.assertIsNone(self.backend.claim(job_id=october))
        self.assertEqual(len(self.lab.events),http)
        self.lab.fault=None
        done=await self.finish(october,restart=True)
        self.assertIn(done["state"],q.TERMINAL)
        self.assertEqual(json.loads(done["checkpoint"])["report_id"],json.loads(before["checkpoint"])["report_id"])
        self.assertEqual(done["epoch"],before["epoch"])
        self.assertEqual(len(self.find_month(sid,9)),1)
        self.assertEqual(sum(e["generate"] for e in self.lab.events[begin:]),1)
        self.assertEqual(self.lab.errors,[])

    async def test_maintenance_repairs_stalled_ready_chain_before_daily_deadline(self):
        cid,sid,jobs=await self.ready_months((11,10))
        self.initial_chain(sid,jobs)
        before={jid:self.snapshot_progress(jid) for jid in jobs.values()}
        next_due=self.identity._db.execute("SELECT next_due FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0]
        self.assertGreater(next_due,self.clock())
        http=len(self.lab.events)
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        self.backend.maintenance_once()
        september=self.find_month(sid,9)
        self.assertEqual(len(september),1,"Repair must not wait for tomorrow's daily schedule")
        self.assertEqual(self.job(september[0][0])["state"],"queued")
        self.assertEqual(len(self.lab.events),http)
        self.assertEqual(self.identity._db.execute("SELECT next_due FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],next_due)
        for jid,old in before.items():self.assertEqual(self.snapshot_progress(jid),old)

    async def test_maintenance_walks_confirmed_empty_tail_without_declaring_history_complete(self):
        # A real valid report ZIP contains its required tables and headers,
        # with zero data records. No ready/zero state is assigned by this test.
        with zipfile.ZipFile(io.BytesIO(cases.yandex_realization_zip("2026-11-01"))) as original:
            empty=cases.zip_bytes({name:original.read(name).splitlines(keepends=True)[0] for name in original.namelist()})
        self.lab.fault=lambda event:{"status_code":200,"headers":{"content-type":"application/zip"},"content":empty} if event["download"] else None
        cid,sid,jobs=await self.ready_months((11,10))
        self.lab.fault=None
        for jid in jobs.values():self.assertEqual(self.job(jid)["state"],"no_data_confirmed")
        self.initial_chain(sid,jobs)
        http=len(self.lab.events)
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        self.backend.maintenance_once()
        self.assertEqual(len(self.find_month(sid,9)),1,"A confirmed empty month is not the earliest available history boundary")
        self.assertEqual(len(self.lab.events),http)
        self.assertNotEqual(self.identity._db.execute("SELECT history_state FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],"complete")

    async def test_stopped_group_or_pending_child_never_resumes_from_seed_or_maintenance(self):
        for stop_group in (True,False):
            with self.subTest(stop_group=stop_group):
                cid,sid,jobs=await self.ready_months((11,))
                october=self.month_job(sid,cid,10);jobs[10]=october
                gid=self.initial_chain(sid,jobs)
                with self.identity._write() as db:q.market_sync_control(db,self.ws,gid if stop_group else october,"stop")
                before=self.snapshot_progress(october);http=len(self.lab.events)
                self.assertEqual(before["state"],"stopped")
                self.backend=Backend(self.state,clock=self.clock,jitter=0)
                self.seed_store(sid);self.backend.maintenance_once()
                self.assertEqual(self.snapshot_progress(october),before)
                self.assertEqual(self.find_month(sid,9),[])
                self.assertEqual(len(self.lab.events),http)
                if stop_group:
                    self.assertEqual(self.identity._db.execute("SELECT state FROM market_data_groups WHERE id=?",(gid,)).fetchone()[0],"stopped")
                    self.assertEqual(self.identity._db.execute("SELECT paused FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],1)


if __name__=="__main__":unittest.main()
