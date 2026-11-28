"""Real loopback HTTP, common executor/limiter and physical SQLite acceptance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import formatdate
import json
import io
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from platform_core.identity import IdentityStore
from platform_core import podmasterye_domain as domain, market_quantity as q
from platform_core.podmasterye_market_links import Store
from platform_core.market_quantity_runtime import Backend
from platform_core import market_quantity_providers as adapters, market_rate_limit as limiter
from tests.fixtures.market_quantity_cases import TEMPLATES, NOW, context_for, success_sequence
from tests.fixtures.market_quantity_http import Laboratory


class Clock:
    def __init__(self):self.now=float(NOW)
    def __call__(self):return self.now
    def advance(self,due):self.now=max(self.now+.001,due)


class Runtime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.identity=self.enterContext(IdentityStore(self.root/"state.sqlite3"))
        self.identity.create_account("quantity-fixture","password");self.token=self.identity.login("quantity-fixture","password")
        domain.init(self.identity);self.ws=self.identity._db.execute("SELECT workspace_id FROM identity_accounts").fetchone()[0]
        self.links=Store(self.identity,self.root);self.clock=Clock();self.seq=0
        self.lab=self.enterContext(Laboratory());self.client=httpx.AsyncClient(transport=self.lab.transport)
        self.state=SimpleNamespace(identity=self.identity,market_links=self.links,http=self.client)
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        # Signed file DNS resolution is exercised separately against the exact
        # allowlist. The loopback transport must not depend on public DNS uptime.
        self.enterContext(patch("platform_core.web_access.check_dns",return_value=None))
    async def asyncTearDown(self):await self.client.aclose()

    def create(self,tid,*,seller=None,context=None):
        self.seq+=1;p="ozon" if tid.startswith("OZ") else "wb" if tid.startswith("WB") else "yandex_market"
        f={"client_id":str(10000+self.seq),"api_key":"fixture-api-key-private"} if p=="ozon" else {"token":"fixture-wb-token-private"} if p=="wb" else {"api_key":"fixture-yandex-key-private"}
        cid=self.links.save(self.token,None,p,"Fixture "+str(self.seq),f)["id"]
        c=context_for(tid,**(context or {}));c.update(cid=cid,version=1,provider=p,client_id=f.get("client_id"),seller=seller or f.get("client_id") or "seller-"+str(self.seq))
        with self.identity._write() as db:
            if q.ROLE[tid]=="identity":
                jid=q.enqueue_identity(db,self.ws,cid)
                db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(q.encode({"token_class":"personal","client_id":f.get("client_id")}),jid))
                return jid,cid,db.execute("SELECT store FROM market_data_tasks WHERE id=?",(jid,)).fetchone()[0]
            sid=q.bind_verified(db,self.ws,cid,1,p,c["seller"],c,now=self.clock())
            jid=q.enqueue(db,sid,tid,c["from"],c["to"],cid=cid,version=1,context={k:v for k,v in c.items() if k not in ("store","cid","version","now","provider","seller")},now=self.clock())
        return jid,cid,sid

    def job(self,jid):return self.backend._row(self.identity._db,jid)

    async def step(self,jid):
        job=self.backend.claim(job_id=jid)
        if not job:return False
        with self.identity._lock:
            current,e=self.backend.guard(self.identity._db,job)
            f=self.links.unpack(job["workspace"],job["owner_cid"],job["provider"],e)
        ctx=self.backend.context(job,f)
        req=adapters.request(job["source"],json.loads(job["checkpoint"]),ctx)
        self.lab.prepare(job["source"],req,ctx,self.clock)
        await self.backend.run(job)
        return True

    async def finish(self,jid,*,max_steps=70,restart=False):
        for _ in range(max_steps):
            j=self.job(jid)
            if j["state"] in q.TERMINAL|{"denied","partial","needs_attention","uncertain","stopped"}:return j
            if j["due"]>self.clock():
                self.assertIsNone(self.backend.claim(job_id=jid),"premature retry admitted")
                self.clock.advance(j["due"])
            if restart:self.backend=Backend(self.state,clock=self.clock,jitter=0)
            await self.step(jid)
        self.fail("Job did not settle: "+str(self.job(jid)))

    async def test_all_18_templates_real_http_success_and_persisted_quantities(self):
        for tid in TEMPLATES:
            with self.subTest(template=tid):
                jid,cid,sid=self.create(tid);done=await self.finish(jid)
                self.assertIn(done["state"],q.TERMINAL,done)
                self.assertGreater(done["requests"],0)
                with q.local(self.identity._db,self.ws,done["provider"]) as dest:
                    self.assertEqual(dest.execute("PRAGMA integrity_check").fetchone()[0],"ok")
                    receipt=dest.execute("SELECT count(*) FROM quantity_step_receipts WHERE job=?",(jid,)).fetchone()[0]
                    self.assertEqual(receipt,done["step"])
                    text=" ".join(r[0] for table in ("quantity_rows","quantity_catalog","quantity_coverage") for r in dest.execute("SELECT body FROM "+table))
                    self.assertNotIn("buyer-data-must-not-survive",text)
                    self.assertNotIn("999999",text)
                    self.assertNotIn("fixture-api-key-private",text)
        self.assertEqual(self.lab.errors,[])

    async def test_18_templates_three_429_every_stage_then_restart_resume(self):
        for tid in TEMPLATES:
            with self.subTest(template=tid):
                self.lab.calls={};begin=len(self.lab.events)
                self.lab.fault=lambda e:{"status_code":429,"headers":{"Retry-After":"17"},"payload":{}} if e["ordinal"]<=3 else None
                jid,_,_=self.create(tid);done=await self.finish(jid,restart=True,max_steps=110)
                self.assertIn(done["state"],q.TERMINAL,done)
                events=self.lab.events[begin:];counts={}
                for event in events:
                    if event["status"]==429:counts[event["stage"]]=counts.get(event["stage"],0)+1
                self.assertTrue(counts)
                self.assertTrue(all(v==3 for v in counts.values()),counts)
                self.assertEqual(done["rate_limits"],3*len(counts))
                self.assertEqual(done["id"],jid)
                for a,b in zip(events,events[1:]):
                    if a["status"]==429:self.assertGreaterEqual(b["at"]-a["at"],17)
                successes=[e for e in events if e["generate"] and e["status"]==200]
                self.assertLessEqual(len(successes),2 if tid=="OZ-03" else 1)
        self.lab.fault=None

    async def test_permanent_rate_limit_is_durable_and_does_not_block_other_seller(self):
        self.lab.fault=lambda e:{"status_code":429,"headers":{},"payload":{}}
        jid,_,_=self.create("OZ-02")
        for _ in range(12):
            j=self.job(jid)
            if j["state"]=="deferred":break
            self.clock.advance(j["due"]);await self.step(jid)
        j=self.job(jid);self.assertEqual(j["state"],"deferred");self.assertEqual(j["requests"],5)
        self.assertGreaterEqual(j["due"],self.clock()+3600)
        self.assertIsNone(j["lease"])
        self.lab.fault=None
        other,_,_=self.create("OZ-02");self.assertIn((await self.finish(other))["state"],q.TERMINAL)
        self.assertEqual(self.job(jid)["requests"],5)

    async def test_every_template_every_network_stage_access_and_persistent_429(self):
        for tid in TEMPLATES:
            stages=list(dict.fromkeys(c["request"]["stage"] for c in success_sequence(tid)))
            for stage in stages:
                for code in (401,403,429):
                    with self.subTest(template=tid,stage=stage,status=code):
                        self.lab.calls={};begin=len(self.lab.events)
                        self.lab.fault=lambda e:{"status_code":code,"headers":{"Retry-After":"7"} if code==429 else {},"payload":{}} if e["stage"]==stage else None
                        jid,_,_=self.create(tid)
                        for _ in range(90):
                            job=self.job(jid)
                            if job["state"] in {"deferred","denied","needs_attention","uncertain","partial"}:break
                            if job["due"]>self.clock():
                                self.assertIsNone(self.backend.claim(job_id=jid));self.clock.advance(job["due"])
                            await self.step(jid)
                        done=self.job(jid);events=self.lab.events[begin:]
                        signed=stage=="download" and tid in ("OZ-03","YM-05","YM-06")
                        self.assertEqual(done["state"],"deferred" if code==429 else "needs_attention" if signed else "denied",done)
                        self.assertIsNone(done["lease"])
                        errors=[e for e in events if e["stage"]==stage and e["status"]==code]
                        self.assertGreaterEqual(len(errors),1)
                        self.assertLessEqual(len(errors),5 if code==429 else 4 if signed else 1)
                        self.assertFalse(any(e["generate"] and e["status"]==200 for e in events[1:]) and stage in ("generate","generate_current"))
        self.lab.fault=None

    async def test_every_template_retry_headers_variants_use_real_durable_wait(self):
        for tid in TEMPLATES:
            for variant in ("date","missing","malformed","zero","expired"):
                with self.subTest(template=tid,header=variant):
                    self.lab.calls={};fired=[False];observed=[None]
                    def fault(event):
                        if fired[0]:return None
                        fired[0]=True;observed[0]=self.clock()
                        headers={} if variant=="missing" else {"Retry-After":"garbage" if variant=="malformed" else "0" if variant=="zero" else formatdate(self.clock()+120 if variant=="date" else self.clock()-10,usegmt=True)}
                        return {"status_code":429,"headers":headers,"payload":{}}
                    self.lab.fault=fault;begin=len(self.lab.events)
                    jid,_,_=self.create(tid);done=await self.finish(jid,restart=True,max_steps=120)
                    self.assertIn(done["state"],q.TERMINAL,done)
                    events=self.lab.events[begin:]
                    self.assertEqual(sum(e["status"]==429 for e in events),1)
                    self.assertGreater(events[1]["at"],events[0]["at"])
                    if variant=="date":self.assertGreaterEqual(events[1]["at"]-events[0]["at"],119)
        self.lab.fault=None

    async def test_read_failures_retry_but_unknown_generate_is_never_repeated(self):
        for code in (408,500,502,503,504):
            for tid in TEMPLATES:
                with self.subTest(status=code,template=tid):
                    self.lab.calls={};self.lab.fault=lambda e:{"status_code":code,"headers":{},"payload":{}} if e["ordinal"]==1 else None
                    begin=len(self.lab.events);jid,_,_=self.create(tid);done=await self.finish(jid)
                    if any(e["generate"] and e["status"]==code for e in self.lab.events[begin:]):
                        self.assertEqual(done["state"],"uncertain")
                        self.assertEqual(sum(e["generate"] for e in self.lab.events[begin:]),1)
                        with self.identity._write() as db:
                            with self.assertRaises(Exception):q.market_sync_control(db,self.ws,jid,"retry")
                    else:self.assertIn(done["state"],q.TERMINAL,done)

    async def test_temporary_dns_failure_preserves_checkpoint_and_never_repeats_unknown_generate(self):
        # DNS errors are injected at the transport boundary; subsequent reads
        # recover through the real TCP lab and production durable executor.
        # This is explicitly a fault test, not a live DNS/provider observation.
        for tid in TEMPLATES:
            with self.subTest(template=tid):
                jid,_,_=self.create(tid);before=self.job(jid)
                with patch.object(self.backend,"transport",side_effect=httpx.ConnectError("Temporary failure in name resolution")) as fault:
                    for _ in range(30):
                        if self.job(jid)["due"]>self.clock():self.clock.advance(self.job(jid)["due"])
                        await self.step(jid)
                        if fault.await_count:break
                    self.assertEqual(fault.await_count,1)
                failed=self.job(jid)
                self.assertEqual(failed["checkpoint"],before["checkpoint"])
                self.assertIsNone(failed["receipt"])
                self.assertEqual(failed["requests"],1)
                generated=bool(self.lab.spec.get("generate"))
                if generated:
                    self.assertEqual(failed["state"],"uncertain")
                    with self.identity._write() as db:
                        with self.assertRaises(Exception):q.market_sync_control(db,self.ws,jid,"retry")
                else:
                    self.assertEqual(failed["state"],"waiting_retry")
                    self.assertGreater(failed["due"],self.clock())
                    self.assertIsNone(self.backend.claim(job_id=jid))
                    done=await self.finish(jid,restart=True)
                    self.assertIn(done["state"],q.TERMINAL)

    async def test_tls_and_origin_fail_closed_for_every_template(self):
        import ssl
        for tid in TEMPLATES:
            for error in (ssl.SSLError("CERTIFICATE_VERIFY_FAILED"),ValueError("origin")):
                with self.subTest(template=tid,error=type(error).__name__):
                    jid,_,_=self.create(tid);count=len(self.lab.events)
                    with patch.object(self.backend,"transport",side_effect=error) as fault:
                        for _ in range(30):
                            if self.job(jid)["due"]>self.clock():self.clock.advance(self.job(jid)["due"])
                            await self.step(jid)
                            if fault.await_count:break
                        self.assertEqual(fault.await_count,1)
                    failed=self.job(jid)
                    self.assertEqual(failed["state"],"needs_attention")
                    self.assertEqual(failed["requests"],1)
                    self.assertIsNone(failed["receipt"])
                    self.assertIsNone(self.backend.claim(job_id=jid))
                    self.assertEqual(len(self.lab.events),count)

    async def test_permanent_errors_do_not_retry_or_publish_fake_zero(self):
        for code in (400,401,403,404,409,410,422):
            for tid in TEMPLATES:
                self.lab.fault=lambda e:{"status_code":code,"headers":{},"payload":{}}
                jid,_,_=self.create(tid);done=await self.finish(jid)
                self.assertEqual(done["state"],"denied" if code in (401,403) else "needs_attention")
                self.assertEqual(done["requests"],1)
                self.assertIsNone(done["receipt"])

    async def test_every_template_tcp_timeout_reset_and_report_stage_recovery(self):
        for failure in ("timeout","disconnect",503):
            for generate_failure in (False,True):
                for tid in TEMPLATES:
                    with self.subTest(template=tid,failure=failure,generate_failure=generate_failure):
                        self.lab.calls={};self.lab.transport.short_timeout=failure=="timeout"
                        def fault(event):
                            if event["ordinal"]!=1 or event["generate"] and not generate_failure:return None
                            return failure if isinstance(failure,str) else {"status_code":failure,"headers":{},"payload":{}}
                        self.lab.fault=fault;begin=len(self.lab.events)
                        jid,_,_=self.create(tid);done=await self.finish(jid,max_steps=120,restart=True)
                        events=self.lab.events[begin:]
                        if any(e["generate"] and e["status"]!=200 for e in events) and generate_failure:
                            self.assertEqual(done["state"],"uncertain",done)
                            self.assertEqual(sum(e["generate"] for e in events),1)
                        else:
                            self.assertIn(done["state"],q.TERMINAL,done)
                            self.assertLessEqual(sum(e["generate"] and e["status"]==200 for e in events),2 if tid=="OZ-03" else 1)
        self.lab.transport.short_timeout=False;self.lab.fault=None

    async def test_bad_generate_response_is_uncertain_and_known_expired_report_reuses_id(self):
        for tid in ("OZ-03","WB-05","YM-05","YM-06"):
            for payload in (b"invalid-json",b"{}"):
                with self.subTest(template=tid,body=payload):
                    self.lab.fault=lambda e:{"status_code":200,"headers":{},"content":payload} if e["generate"] else None
                    begin=len(self.lab.events);jid,_,_=self.create(tid);done=await self.finish(jid)
                    self.assertEqual(done["state"],"uncertain",done)
                    with self.identity._write() as db:
                        with self.assertRaises(Exception):q.market_sync_control(db,self.ws,jid,"retry")
                    self.assertEqual(sum(e["generate"] for e in self.lab.events[begin:]),1)
            self.lab.calls={};begin=len(self.lab.events)
            self.lab.fault=lambda e:{"status_code":410,"headers":{},"payload":{}} if e["download"] and e["ordinal"]==1 else None
            jid,_,_=self.create(tid);done=await self.finish(jid,restart=True,max_steps=120)
            self.assertIn(done["state"],q.TERMINAL,done)
            events=self.lab.events[begin:]
            self.assertLessEqual(sum(e["generate"] and e["status"]==200 for e in events),2 if tid=="OZ-03" else 1)
        self.lab.fault=None

    async def test_all_templates_invalid_200_cannot_publish_success_or_zero(self):
        for tid in TEMPLATES:
            for payload in (b"invalid-json",b'{"unexpected_contract":true}'):
                with self.subTest(template=tid,body=payload):
                    self.lab.fault=lambda e:{"status_code":200,"headers":{},"content":payload}
                    begin=len(self.lab.events);jid,_,_=self.create(tid);done=await self.finish(jid)
                    expected="uncertain" if self.lab.events[begin]["generate"] else "partial"
                    self.assertEqual(done["state"],expected,done)
                    self.assertEqual(done["requests"],1);self.assertIsNone(done["receipt"])
        self.lab.fault=None

    async def test_refresh_after_corrupt_download_keeps_known_report(self):
        for tid in ("OZ-03","WB-05","YM-05","YM-06"):
            self.lab.fault=lambda e:{"status_code":200,"headers":{},"content":b"broken-report"} if e["download"] else None
            begin=len(self.lab.events);jid,cid,sid=self.create(tid);bad=await self.finish(jid)
            self.assertEqual(bad["state"],"partial",bad)
            cp=json.loads(bad["checkpoint"]);self.assertTrue(cp.get("report_id"))
            with self.identity._write() as db:
                self.assertEqual(q.enqueue(db,sid,tid,bad["since"],bad["until"],cid=cid,version=1,refresh=True),jid)
            refreshed=self.job(jid)
            self.assertEqual(refreshed["checkpoint"],bad["checkpoint"])
            self.assertEqual(refreshed["epoch"],bad["epoch"])
            self.lab.fault=None
            self.assertIn((await self.finish(jid))["state"],q.TERMINAL)
            events=self.lab.events[begin:]
            self.assertLessEqual(sum(e["generate"] for e in events),2 if tid=="OZ-03" else 1)

    async def test_expired_signed_403_refresh_is_bounded_and_never_revokes_api_scope(self):
        for tid in ("OZ-03","YM-05","YM-06"):
            for persistent in (False,True):
                self.lab.calls={};begin=len(self.lab.events)
                self.lab.fault=lambda e:{"status_code":403,"headers":{},"payload":{}} if e["download"] and (persistent or e["ordinal"]==1) else None
                jid,cid,_=self.create(tid);done=await self.finish(jid,max_steps=120)
                self.assertEqual(done["state"],"needs_attention" if persistent else "ready",done)
                self.assertFalse(self.identity._db.execute("SELECT 1 FROM market_data_denials WHERE cid=?",(cid,)).fetchone())
                self.assertLessEqual(sum(e["generate"] for e in self.lab.events[begin:]),2 if tid=="OZ-03" else 1)
                if persistent:self.assertEqual(sum(e["download"] for e in self.lab.events[begin:]),4)
        self.lab.fault=None

    async def test_cancel_during_generation_retains_report_without_publishing(self):
        jid,_,_=self.create("YM-05");transport=self.backend.transport
        async def stop_after_response(job,req,fields):
            response=await transport(job,req,fields)
            with self.identity._write() as db:q.market_sync_control(db,self.ws,jid,"cancel")
            return response
        self.backend.transport=stop_after_response
        await self.step(jid);stopped=self.job(jid)
        self.assertEqual(stopped["state"],"stopped")
        report=json.loads(stopped["checkpoint"])["report_id"]
        self.assertTrue(report);self.assertIsNone(stopped["inflight"])
        self.assertIsNone(stopped["receipt"])
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        with self.identity._write() as db:q.market_sync_control(db,self.ws,jid,"resume")
        done=await self.finish(jid);self.assertIn(done["state"],q.TERMINAL)
        self.assertEqual(sum(e["generate"] for e in self.lab.events),1)

    async def test_parent_group_stops_backfill_and_daily_then_resumes_same_tasks(self):
        jid,cid,sid=self.create("YM-03")
        with self.identity._write() as db:
            store=q.selected_stores(db,self.ws,sid)[0];self.backend.seed(db,store)
            gid=db.execute("SELECT id FROM market_data_groups WHERE source=? AND purpose='initial'",(sid,)).fetchone()[0]
            jobs={r[0] for r in db.execute("SELECT task_id FROM market_data_group_tasks WHERE group_id=?",(gid,))}
            first=q.market_sync_control(db,self.ws,gid,"cancel",request_id="stop-group")
            self.assertEqual(first,q.market_sync_control(db,self.ws,gid,"cancel",request_id="stop-group"))
            self.assertEqual(first["state"],"stopped")
        self.clock.advance(self.clock()+86401);self.backend.maintenance_once()
        self.assertEqual(self.identity._db.execute("SELECT paused FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],1)
        self.assertTrue(all(self.job(j)["state"]=="stopped" for j in jobs))
        before=len(self.lab.events)
        for j in jobs:self.assertIsNone(self.backend.claim(job_id=j))
        self.assertEqual(len(self.lab.events),before)
        with self.identity._write() as db:
            q.market_sync_control(db,self.ws,gid,"resume",request_id="resume-group")
            self.assertEqual(db.execute("SELECT paused FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0],0)
            self.assertEqual({r[0] for r in db.execute("SELECT task_id FROM market_data_group_tasks WHERE group_id=?",(gid,))},jobs)
        self.assertTrue(any(self.job(j)["state"]=="queued" for j in jobs))

    async def test_multiple_processes_share_atomic_lease_and_seller_quota(self):
        jid,cid,sid=self.create("YM-03")
        script='''import json,sys
from types import SimpleNamespace
from platform_core.identity import IdentityStore
from platform_core.market_quantity_runtime import Backend
with IdentityStore(sys.argv[1]) as identity:
 job=Backend(SimpleNamespace(identity=identity),clock=lambda:float(sys.argv[3])).claim(job_id=sys.argv[2])
 print(json.dumps({'claimed':bool(job),'lease':job['lease'] if job else None}))
'''
        workers=[subprocess.Popen([sys.executable,"-c",script,str(self.root/"state.sqlite3"),jid,str(self.clock())],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        results=[]
        for p in workers:
            out,err=await asyncio.to_thread(p.communicate,timeout=20)
            self.assertEqual(p.returncode,0,err);results.append(json.loads(out))
        self.assertEqual(sum(r["claimed"] for r in results),1)
        j=self.job(jid);request={"quota_profile":{"scope":"seller","key":"same-method","min_interval":30,"max_concurrency":1},"quota_scopes":[]}
        ctx={"provider":"wb","seller":"same-real-seller"}
        with self.identity._write() as db:
            permits,due=limiter.acquire(db,j,ctx,request,self.clock());self.assertIsNotNone(permits)
            limiter.release(db,permits)
            second=dict(j,id="another-key-job",lease="another-process")
            denied,due=limiter.acquire(db,second,ctx,request,self.clock());self.assertIsNone(denied);self.assertEqual(due,self.clock()+30)
            free,_=limiter.acquire(db,second,{**ctx,"seller":"other-seller"},request,self.clock());self.assertIsNotNone(free)

    async def test_shared_collector_runs_auto_history_without_ui_and_respects_group_stop(self):
        from platform_core.market_collect import Collector
        from urllib.parse import urlsplit
        self.clock.now=time.time()
        jid,cid,_=self.create("WB-01")
        self.state.worker=SimpleNamespace(database_path=str(self.root/"state.sqlite3"))
        self.lab.clock=time.time
        def resolve(method,path,body,headers):
            # The fixture selects a response from the actual durable dispatch,
            # while both production Collector consumers run autonomously.
            with self.identity._lock:
                ids=self.identity._db.execute("SELECT id FROM market_data_tasks WHERE state='running' AND inflight IS NOT NULL").fetchall()
                for active, in ids:
                    j=self.backend._row(self.identity._db,active)
                    e=self.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?",(j["owner_cid"],)).fetchone()[0]
                    fields=self.links.unpack(j["workspace"],j["owner_cid"],j["provider"],e)
                    ctx=self.backend.context(j,fields,db=self.identity._db);request=adapters.request(j["source"],json.loads(j["checkpoint"]),ctx)
                    if request["method"]==method and urlsplit(request["url"]).path==urlsplit(path).path:return j["source"],request,ctx
            raise AssertionError("No durable dispatch for background HTTP")
        self.lab.resolve_request=resolve
        collector=Collector(self.state)
        try:
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                with self.identity._lock:
                    group=self.identity._db.execute("SELECT id FROM market_data_groups WHERE purpose='initial'").fetchone()
                    completed=self.identity._db.execute("SELECT count(*) FROM market_data_tasks WHERE source!='WB-01' AND state IN ('ready','no_data_confirmed')").fetchone()[0]
                if group and completed:break
                await asyncio.sleep(.05)
            self.assertTrue(group);self.assertGreater(completed,0)
            self.assertIn(self.job(jid)["state"],q.TERMINAL)
            with self.identity._write() as db:
                result=q.market_sync_control(db,self.ws,group[0],"cancel")
                self.assertEqual(result["state"],"stopped")
            await asyncio.sleep(.15)
            count=len(self.lab.events)
            await collector.close();collector=Collector(self.state)
            await asyncio.sleep(.2)
            self.assertEqual(len(self.lab.events),count)
            self.assertEqual(self.lab.errors,[])
            self.assertFalse(hasattr(self.state,"model"))
        finally:await collector.close()

    async def test_archive_disconnect_and_corrupt_local_store_fail_closed(self):
        jid,cid,sid=self.create("WB-03")
        from platform_core import podmasterye_workshops as workshops
        with self.identity._write() as db:
            workshops.ensure(db,self.ws)
            db.execute("UPDATE pm_workshops SET archived=1 WHERE id=?",(self.ws,))
        self.assertIsNone(self.backend.claim(job_id=jid));self.assertEqual(self.job(jid)["state"],"stopped")
        with self.identity._write() as db:db.execute("UPDATE pm_workshops SET archived=0 WHERE id=?",(self.ws,))
        self.links.remove(self.token,None,cid,1)
        self.assertIsNone(self.backend.claim(job_id=jid))
        other,_,sid=self.create("WB-03");self.assertIn((await self.finish(other))["state"],q.TERMINAL)
        path=q.market_data.path_for(q.main_path(self.identity._db),self.ws,"wb")
        path.write_bytes(b"corrupted-sqlite")
        snapshot=q.quantity_snapshot(self.identity._db,self.ws)
        self.assertEqual(snapshot["rows"],[])
        self.assertTrue(snapshot["coverage"])
        self.assertTrue(all(not r["complete"] and r["state"]=="local_unavailable" for r in snapshot["coverage"]))

    async def test_signed_download_and_secrets_are_absent_even_from_debug_transport_logs(self):
        captured=io.StringIO();handler=logging.StreamHandler(captured)
        names=("httpx","httpcore.connection","httpcore.http11","httpcore.http2")
        previous={name:logging.getLogger(name).level for name in names}
        for name in names:
            logger=logging.getLogger(name);logger.setLevel(logging.DEBUG);logger.addHandler(handler)
        try:
            jid,_,_=self.create("YM-05");done=await self.finish(jid)
            self.assertIn(done["state"],q.TERMINAL)
            self.assertEqual(captured.getvalue(),"")
            logging.getLogger("httpx").info("unrelated logging remains available")
            self.assertIn("unrelated logging remains available",captured.getvalue())
            text=q.encode(q.job_public(self.identity._db,jid,self.ws))
            self.assertNotIn("https://",text);self.assertNotIn("fixture-yandex-key-private",text)
        finally:
            for name in names:
                logger=logging.getLogger(name);logger.removeHandler(handler);logger.setLevel(previous[name])

    async def test_reconnect_same_seller_adopts_existing_job_and_report_after_old_key_deletion(self):
        jid,cid,sid=self.create("YM-05")
        await self.step(jid);before=self.job(jid)
        report=json.loads(before["checkpoint"])["report_id"]
        self.links.remove(self.token,None,cid,1)
        saved=self.links.save(self.token,None,"yandex_market","Reconnected same seller",{"api_key":"replacement-private-key"})
        with self.identity._write() as db:
            rebound=q.bind_verified(db,self.ws,saved["id"],1,"yandex_market",before["seller"],json.loads(before["metadata"]),now=self.clock())
            self.assertEqual(rebound,sid)
            adopted=q.enqueue(db,sid,"YM-05",before["since"],before["until"],cid=saved["id"],version=1,now=self.clock())
            self.assertEqual(adopted,jid)
        self.assertEqual(json.loads(self.job(jid)["checkpoint"])["report_id"],report)
        self.assertEqual(self.job(jid)["owner_cid"],saved["id"])
        self.assertIn((await self.finish(jid))["state"],q.TERMINAL)
        self.assertEqual(sum(e["generate"] for e in self.lab.events),1)

    async def test_malformed_json_and_broken_archives_leave_last_snapshot(self):
        for tid in ("OZ-02","WB-03","YM-03","OZ-03","YM-05","YM-06"):
            self.lab.fault=None;jid,cid,sid=self.create(tid);done=await self.finish(jid)
            self.assertIn(done["state"],q.TERMINAL)
            with q.local(self.identity._db,self.ws,done["provider"]) as dest:
                before=dest.execute("SELECT * FROM quantity_rows WHERE store=? ORDER BY source,natural_key",(sid,)).fetchall()
                cards=dest.execute("SELECT * FROM quantity_catalog WHERE store=? ORDER BY sku",(sid,)).fetchall()
            with self.identity._write() as db:q.market_sync_control(db,self.ws,jid,"retry")
            self.lab.fault=lambda e:{"status_code":200,"headers":{},"content":b"not JSON or a valid archive"} if e["download"] or tid in ("OZ-02","WB-03","YM-03") else None
            bad=await self.finish(jid)
            self.assertEqual(bad["state"],"partial",bad)
            with q.local(self.identity._db,self.ws,done["provider"]) as dest:
                self.assertEqual(dest.execute("SELECT * FROM quantity_rows WHERE store=? ORDER BY source,natural_key",(sid,)).fetchall(),before)
                self.assertEqual(dest.execute("SELECT * FROM quantity_catalog WHERE store=? ORDER BY sku",(sid,)).fetchall(),cards)

    async def test_cancel_cooldown_rotation_and_two_worker_fencing(self):
        jid,cid,sid=self.create("OZ-02")
        first=self.backend.claim(job_id=jid);self.assertIsNotNone(first)
        other=Backend(self.state,clock=self.clock,jitter=0);self.assertIsNone(other.claim(job_id=jid))
        self.clock.advance(first["expires"]+1);second=other.claim(job_id=jid);self.assertNotEqual(first["lease"],second["lease"])
        await self.backend.run(first);self.assertEqual(self.job(jid)["requests"],0)
        with self.identity._write() as db:q.market_sync_control(db,self.ws,jid,"cancel")
        await other.run(second);self.assertEqual(self.job(jid)["requests"],0)
        with self.identity._write() as db:q.market_sync_control(db,self.ws,jid,"resume")
        self.lab.fault=lambda e:{"status_code":429,"headers":{"Retry-After":"300"},"payload":{}}
        await self.step(jid);due=self.job(jid)["due"]
        with self.identity._write() as db:
            q.market_sync_control(db,self.ws,jid,"cancel");q.market_sync_control(db,self.ws,jid,"resume")
        self.assertEqual(self.job(jid)["due"],due);self.assertIsNone(other.claim(job_id=jid))
        self.links.update(self.token,None,cid,1,{"client_id":str(10000+self.seq),"api_key":"new-fixture-secret"})
        self.clock.advance(due);self.assertIsNone(other.claim(job_id=jid));self.assertEqual(self.job(jid)["state"],"stopped")

    async def test_crash_between_local_commit_and_queue_ack_recovers_without_http(self):
        jid,_,_=self.create("WB-03")
        old=self.backend._ack
        def crash(*args,**kw):raise OSError("simulated disk full after local commit")
        self.backend._ack=crash
        await self.step(jid);after=self.job(jid);self.assertEqual(after["requests"],1)
        self.assertEqual(after["state"],"running")
        self.clock.advance(after["expires"]+1)
        self.backend=Backend(self.state,clock=self.clock,jitter=0)
        done=await self.finish(jid)
        self.assertIn(done["state"],q.TERMINAL);self.assertEqual(done["requests"],1)
        self.assertTrue(self.identity._db.execute("SELECT 1 FROM market_data_events WHERE job=? AND kind='receipt_recovered'",(jid,)).fetchone())

    async def test_100_clients_1000_duplicate_starts_one_logical_template_job(self):
        jid,cid,sid=self.create("YM-03")
        def submit(_):
            with self.identity._write() as db:return q.enqueue(db,sid,"YM-03","2026-10-01","2026-10-30",cid=cid,version=1)
        with ThreadPoolExecutor(max_workers=100) as pool:ids=list(pool.map(submit,range(1000)))
        self.assertEqual(set(ids),{jid})
        self.assertIn((await self.finish(jid))["state"],q.TERMINAL)
        count=len(self.lab.events)
        for _ in range(100):q.quantity_snapshot(self.identity._db,self.ws,"yandex_market")
        self.assertEqual(len(self.lab.events),count)


class RatePolicy(unittest.TestCase):
    def test_headers_never_shorten_official_interval_or_clock_skew(self):
        p={"min_interval":60,"backoff_base":8,"backoff_cap":900,"vendor_headers":["X-Ratelimit-Reset","X-RateLimit-Resource-Until"]}
        for value in (None,"garbage","0","-1",formatdate(NOW-100,usegmt=True)):
            h={} if value is None else {"Retry-After":value}
            self.assertGreaterEqual(limiter.retry_due(h,NOW,p,1,jitter=0),NOW+60)
        self.assertEqual(limiter.retry_due({"Retry-After":"120"},NOW,p,1,jitter=0),NOW+120)
        h={"Date":formatdate(NOW-3600,usegmt=True),"Retry-After":formatdate(NOW-3300,usegmt=True)}
        self.assertEqual(limiter.retry_due(h,NOW,p,1,jitter=0),NOW+300)
        self.assertEqual(limiter.retry_due({"X-Ratelimit-Reset":"700"},NOW,p,1,jitter=0),NOW+700)
        self.assertEqual(limiter.retry_due({"X-RateLimit-Resource-Until":formatdate(NOW+800,usegmt=True)},NOW,p,1,jitter=0),NOW+800)
    def test_yandex420_and_tls_fail_closed(self):
        self.assertEqual(limiter.classify(420,provider="yandex_market"),"rate_limited")
        self.assertEqual(limiter.classify(420,provider="ozon"),"needs_attention")
        self.assertEqual(limiter.classify(error="tls"),"needs_attention")
        self.assertEqual(limiter.classify(403,download=True),"denied")
        self.assertEqual(limiter.classify(403,download=True,signed_download=True),"refresh_report")


if __name__=="__main__":unittest.main()
