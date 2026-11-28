#!/usr/bin/env python3
"""Reproducible quantity stress on synthetic shops and REAL loopback HTTP.

Acceptance run (after the candidate is frozen)::
  PODMASTERYE_MARKET_WORKER=0 python3 acceptance/market_quantity_stress.py \
      --duration 1800 --shops 24 --workers 4 --events-per-adapter 1000 \
      --output /absolute/path/to/evidence/stress

Short runs are explicitly SMOKE, never evidence for the 30 minute criterion.
The quota clock is accelerated; elapsed load duration and latency use monotonic
wall time. Workers are real child processes using the real Backend, SQLite,
limiter, encryption store and adapters. Only provider transport is redirected
to the existing documented-shape Laboratory. No live provider is contacted.
"""
import argparse
import asyncio
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime,timezone
from email.utils import formatdate
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

import httpx
from platform_core.identity import IdentityStore,_principal
from platform_core.podmasterye_market_links import Store
from platform_core.market_quantity_runtime import Backend
from platform_core import market_quantity as q,market_rate_limit as limiter
from platform_core import market_quantity_providers as adapters
from tests.fixtures.market_quantity_cases import TEMPLATES,NOW,context_for,response_for
from tests.fixtures.market_quantity_http import Laboratory,LoopbackTransport
from tests.test_market_quantity_runtime import Clock

API="/api/integrations/marketplaces/operations"
ORIGIN="https://quantity-stress.example"
PASSWORD="isolated-quantity-stress-password"
# Fixed BEFORE baseline and load. Do not raise these after seeing a failure.
BUDGETS={"ui_p95_ms":2000,"ui_p99_ms":5000,"worker_step_p95_ms":2000,
         "rss_total_mb":1536,"mean_cpu_cores":4,"open_descriptors_total":512,
         "queued_tasks":50000,"early_requests":0,"uncontrolled_crashes":0,
         "cross_client_leaks":0,"integrity_errors":0,"model_calls":0,
         "minimum_wall_seconds":1800,"minimum_shops":20,
         "parallel_clients":100,"duplicate_starts":1000}


def dump(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    tmp.replace(path)


def percentiles(values):
    if not values:return {"count":0,"p50_ms":None,"p95_ms":None,"p99_ms":None,"max_ms":None}
    v=sorted(values)
    def nth(p):return round(v[min(len(v)-1,int((len(v)-1)*p))]*1000,3)
    return {"count":len(v),"p50_ms":nth(.5),"p95_ms":nth(.95),"p99_ms":nth(.99),"max_ms":round(v[-1]*1000,3)}


def source_digest():
    paths=[]
    for directory in ("platform_core","native","tests/fixtures","acceptance"):
        paths.extend(p for p in (ROOT/directory).rglob("*") if p.is_file() and p.suffix in (".py",".json",".mjs",".js",".css"))
    h=hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path.relative_to(ROOT)).encode()+b"\0"+path.read_bytes()+b"\0")
    return h.hexdigest()


def process_resources(pids):
    rss=descriptors=sockets=0
    for pid in pids:
        try:
            data=Path(f"/proc/{pid}/status").read_text()
            rss+=int(next(line.split()[1] for line in data.splitlines() if line.startswith("VmRSS:")))*1024
            fds=list(Path(f"/proc/{pid}/fd").iterdir());descriptors+=len(fds)
            for fd in fds:
                try:sockets+=os.readlink(fd).startswith("socket:")
                except OSError:pass
        except (OSError,StopIteration,ValueError):pass
    return {"rss_total_mb":round(rss/1024**2,3),"open_descriptors_total":descriptors,"open_sockets_total":sockets}


async def child_main(args):
    """One persistent real worker process. Parent owns a loopback fixture server."""
    os.environ["PODMASTERYE_MARKET_WORKER"]="0"
    identity=IdentityStore(Path(args.database));links=Store(identity,Path(args.database).parent)
    transport=LoopbackTransport(args.port)
    async with httpx.AsyncClient(transport=transport) as http:
        clock=[float(NOW)];state=SimpleNamespace(identity=identity,market_links=links,http=http)
        backend=Backend(state,clock=lambda:clock[0],jitter=0)
        # Signed URLs still pass the production origin allowlist. Actual sockets
        # target only loopback, so no public DNS lookup is necessary in the lab.
        with patch("platform_core.web_access.check_dns",new=AsyncMock(return_value=None)):
            print(json.dumps({"ready":True,"pid":os.getpid()}),flush=True)
            while True:
                line=await asyncio.to_thread(sys.stdin.readline)
                if not line:break
                message=json.loads(line)
                if message.get("stop"):break
                clock[0]=message["now"];transport.short_timeout=message.get("short_timeout",False)
                job=backend._row(identity._db,message["job_id"])
                if not job:raise RuntimeError("missing stress job")
                original_ack=backend._ack
                if message.get("crash_after_publish"):
                    def crash(*a,**kw):os._exit(79)
                    backend._ack=crash
                started=time.monotonic()
                try:await backend.run(job)
                except Exception as exc:
                    print(json.dumps({"error_type":type(exc).__name__}),flush=True)
                else:print(json.dumps({"done":True,"seconds":time.monotonic()-started}),flush=True)
                finally:backend._ack=original_ack
    identity.close()


class Worker:
    def __init__(self,harness,index):
        self.h=harness;self.index=index;self.process=None;self.backend=None;self.job=None
        self.lab=harness.stack.enter_context(Laboratory());self.lab.fault=self.respond
        self.attempts=Counter();self.forced=None;self.context=None;self.request=None

    async def start(self):
        self.stderr=(self.h.output/f"worker-{self.index}.stderr.log").open("ab")
        self.process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).resolve()),
            "--child","--database",str(self.h.database),"--port",str(self.lab.server.server_port),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=self.stderr,cwd=str(ROOT))
        greeting=await asyncio.wait_for(self.process.stdout.readline(),30)
        if not greeting or not json.loads(greeting).get("ready"):raise RuntimeError("Worker failed to start")

    async def stop(self,*,abrupt=False):
        if self.process and self.process.returncode is None:
            if abrupt:self.process.kill()
            else:
                self.process.stdin.write(b'{"stop":true}\n');await self.process.stdin.drain()
            try:await asyncio.wait_for(self.process.wait(),10)
            except asyncio.TimeoutError:self.process.kill();await self.process.wait()
        if getattr(self,"stderr",None):self.stderr.close()

    async def restart(self,*,abrupt=False):
        await self.stop(abrupt=abrupt);await self.start();self.h.counts["worker_process_restarts"]+=1

    def respond(self,event):
        job=self.job;key=(job["id"],job["epoch"],job["step"],event["stage"])
        self.attempts[key]+=1;attempt=self.attempts[key]
        fault=None;fault_name="success";headers={}
        # Fixture identities are unique between isolated owners. Same-seller
        # duplicate keys deliberately retain the same identity and quota scope.
        if self.h.faults:
            seed=int(hashlib.sha256((job["id"]+":"+str(job["epoch"])+":"+event["stage"]).encode()).hexdigest()[:8],16)
            if self.forced=="permanent429" or seed%11==0 and attempt<=3:
                fault_name="429";headers={"Retry-After":"17"}
                fault={"status_code":429,"headers":headers,"payload":{}}
            elif attempt==1:
                choice=seed%37
                if choice in (1,2):
                    fault_name="429";headers={"Retry-After":formatdate(self.h.clock()+19,usegmt=True)} if choice==1 else {"Retry-After":"invalid"}
                    fault={"status_code":429,"headers":headers,"payload":{}}
                elif choice==3 and not event["generate"]:
                    fault_name="503";fault={"status_code":503,"headers":{},"payload":{}}
                elif choice==4 and not event["generate"]:
                    fault_name="disconnect";fault="disconnect"
                elif choice==5 and not event["generate"]:
                    fault_name="malformed";fault={"status_code":200,"headers":{},"content":b"{not-json-or-valid-archive"}
        if self.forced=="timeout":
            fault_name="timeout";fault="timeout"
        if fault is None and job["source"]=="WB-01":
            shop=self.h.by_cid[job["owner_cid"]]
            fault={"status_code":200,"headers":{},"payload":{"sid":shop["seller"],"name":"Isolated fixture seller","tradeMark":"Fixture"}}
        with self.h.metrics_lock:
            for scope,profile in limiter.scopes(self.context,self.request):
                old=self.h.scope_attempts.get(scope)
                if old and event["at"]+1e-6<old["at"]+old["interval"]:
                    self.h.violations.append({"kind":"premature_interval","template":job["source"],"job":job["id"]})
                if event["at"]+1e-6<self.h.scope_cooldown.get(scope,0):
                    self.h.violations.append({"kind":"premature_retry_after","template":job["source"],"job":job["id"]})
                self.h.scope_attempts[scope]={"at":event["at"],"interval":max(.001,float(profile.get("min_interval",profile.get("interval",1))))}
                if fault_name=="429":
                    # Retry budget resets after a durable deferred cycle. The
                    # actual persisted active attempt count is authoritative;
                    # a cumulative fixture ordinal must not invent a delay.
                    self.h.scope_cooldown[scope]=max(self.h.scope_cooldown.get(scope,0),limiter.retry_due(headers,event["at"],self.request["quota_profile"],job["attempts"]+1,jitter=0))
            self.h.http_counts[job["source"]]+=1;self.h.http_status[fault_name]+=1
            self.h.shop_http[job["workspace"]]+=1
            self.h.connection_http[job["owner_cid"]]+=1
            self.h.stages[(job["source"],event["stage"],fault_name)]+=1
            record={"wall_elapsed":round(time.monotonic()-self.h.started,6),"logical_at":event["at"],"template":job["source"],
                    "stage":event["stage"],"job_id":job["id"],"epoch":job["epoch"],"step":job["step"],
                    "worker":self.index,"attempt_in_stage":attempt,"fault":fault_name,"generate":event["generate"],
                    "download":event["download"],"workspace":job["workspace"],"connection_id":job["owner_cid"]}
            self.h.event_file.write(json.dumps(record,ensure_ascii=False)+"\n");self.h.event_file.flush()
        return fault

    async def run(self,job,*,crash=False,forced=None):
        self.job=job;self.forced=forced
        crash=crash or job["id"] in self.h.armed_crashes
        with self.h.identity._lock:
            fields=self.h.links.unpack(job["workspace"],job["owner_cid"],job["provider"],
                self.h.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?",(job["owner_cid"],)).fetchone()[0])
        self.context=self.h.backend.context(job,fields)
        self.request=adapters.request(job["source"],json.loads(job["checkpoint"]),self.context)
        self.lab.prepare(job["source"],self.request,self.context,self.h.clock)
        message={"job_id":job["id"],"now":self.h.clock(),"crash_after_publish":crash,"short_timeout":forced=="timeout"}
        self.process.stdin.write((json.dumps(message)+"\n").encode());await self.process.stdin.drain()
        started=time.monotonic();line=await asyncio.wait_for(self.process.stdout.readline(),40)
        self.h.worker_latency.append(time.monotonic()-started)
        if not line:
            code=await self.process.wait()
            if not crash or code!=79:
                self.h.counts["uncontrolled_crashes"]+=1;raise RuntimeError("Unexpected worker process exit "+str(code))
            self.h.counts["injected_process_crashes_after_local_commit"]+=1
            self.h.armed_crashes.discard(job["id"])
            self.h.pending_recoveries[job["id"]]=time.monotonic()
            await self.restart();return
        outcome=json.loads(line)
        if outcome.get("error_type"):raise RuntimeError("Worker exception "+outcome["error_type"])
        latest=self.h.backend._row(self.h.identity._db,job["id"])
        if job["id"] in self.h.pending_recoveries and latest["state"] in q.TERMINAL|{"queued"} and latest["step"]>job["step"]:
            self.h.recovery_latency.append(time.monotonic()-self.h.pending_recoveries.pop(job["id"]))
        if latest["state"] in ("partial","needs_attention") and not latest.get("inflight"):
            # Explicit operator retry uses the production handler and preserves
            # any already known report ID; no checkpoint is edited by the lab.
            with self.h.identity._write() as db:q.market_sync_control(db,job["workspace"],job["id"],"retry")
            self.h.counts["controlled_retries_after_validation"]+=1


class Harness:
    def __init__(self,args):
        self.args=args;self.output=Path(args.output).resolve();self.output.mkdir(parents=True,exist_ok=True)
        self.database=self.output/"isolated-state"/"state.sqlite3";self.database.parent.mkdir(mode=0o700,exist_ok=True)
        self.stack=ExitStack();self.clock=Clock();self.started=time.monotonic();self.faults=False
        self.counts=Counter();self.http_counts=Counter();self.http_status=Counter();self.shop_http=Counter();self.connection_http=Counter();self.stages=Counter()
        self.scope_attempts={};self.scope_cooldown={};self.violations=[];self.samples=[]
        self.ui_latency=[];self.worker_latency=[];self.recovery_latency=[];self.pending_recoveries={};self.armed_crashes=set()
        self.metrics_lock=threading.Lock();self.event_file=self.stack.enter_context((self.output/"http-events.jsonl").open("w"))
        self.shops=[];self.by_cid={};self.jobs=defaultdict(list);self.rotation=Counter();self.workers=[]
        self.source_sha=source_digest();self.initial_cpu=resource.getrusage(resource.RUSAGE_SELF)
        self.stack.enter_context(patch.dict(os.environ,{"PODMASTERYE_MARKET_WORKER":"0","HARNESS_OFFLINE_MODEL":"1", "HARNESS_USAGE_JOURNAL":str(self.output/"model-usage.jsonl")}))

    async def setup(self):
        from platform_core.chat_api import create_app
        from platform_core import podmasterye_workshops as workshops
        from starlette.testclient import TestClient
        with IdentityStore(self.database) as identity:
            for i in range(self.args.shops):identity.create_account("stress-"+str(i),PASSWORD)
        self.app=create_app(self.database,self.database.parent/"chats")
        self.client=self.stack.enter_context(TestClient(self.app,base_url=ORIGIN))
        self.identity=self.app.state.identity;self.links=self.app.state.market_links
        self.local_http_guard=self.stack.enter_context(patch.object(self.app.state.http,"send",new_callable=AsyncMock,side_effect=AssertionError("Local UI attempted external HTTP")))
        self.backend=Backend(SimpleNamespace(identity=self.identity,market_links=self.links),clock=self.clock,jitter=0)
        for i in range(self.args.workers):
            worker=Worker(self,i);await worker.start();self.workers.append(worker)
        for i in range(self.args.shops):
            provider=("ozon","wb","yandex_market")[i%3]
            token=self.identity.login("stress-"+str(i),PASSWORD)
            with self.identity._write() as db:
                workspace=workshops.resolve(db,_principal(db,token)[1],None)
            seller=str(10000+i) if provider=="ozon" else "fixture-seller-"+str(i) if provider=="wb" else str(20000+i)+":campaign:"+str(30000+i)
            fields={"client_id":seller,"api_key":"fixture-private-ozon-"+str(i)} if provider=="ozon" else {"token":"fixture-private-wb-"+str(i)} if provider=="wb" else {"api_key":"fixture-private-ym-"+str(i)}
            connection=self.links.save(token,None,provider,"Stress shop "+str(i),fields)
            shop={"index":i,"provider":provider,"token":token,"workspace":workspace,"cid":connection["id"],"seller":seller,"identity_job":connection["job_id"]}
            self.shops.append(shop);self.by_cid[shop["cid"]]=shop
            with self.identity._write() as db:
                ctx=context_for(q.IDENTITY[provider],businessId=20000+i,campaignId=30000+i)
                db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(q.encode({k:v for k,v in ctx.items() if k not in ("from","to","store","cid","version","now","seller","provider")}),shop["identity_job"]))
            await self.settle(shop["identity_job"])
            selected=q.selected_stores(self.identity._db,workspace,shop["cid"])
            if len(selected)!=1:raise AssertionError("Identity did not bind exactly one fixture shop")
            shop["sid"]=selected[0]["id"]
            self.jobs[q.IDENTITY[provider]].append(shop["identity_job"])
            prefix={"ozon":"OZ-","wb":"WB-","yandex_market":"YM-"}[provider]
            for tid in (t for t in TEMPLATES if t.startswith(prefix) and q.ROLE[t]!="identity"):
                # Prefer the collector's real automatically seeded window.
                row=self.identity._db.execute("SELECT id FROM market_data_tasks WHERE store=? AND source=? ORDER BY since DESC LIMIT 1",(shop["sid"],tid)).fetchone()
                if row:jid=row[0]
                else:
                    with self.identity._write() as db:jid=q.enqueue(db,shop["sid"],tid,"2026-10-01","2026-10-30",cid=shop["cid"],version=1,context=context_for(tid),now=self.clock())
                self.jobs[tid].append(jid)
        # Two encrypted keys of one seller must bind one physical store and one
        # quota identity. They are exercised by alternating the task owner.
        first=self.shops[0]
        shared=self.links.save(first["token"],None,"ozon","Stress shared seller key",{"client_id":first["seller"],"api_key":"fixture-private-shared-key"})
        self.by_cid[shared["id"]]={**first,"cid":shared["id"]}
        await self.settle(shared["job_id"])
        ids=q.selected_stores(self.identity._db,first["workspace"],shared["id"])
        if len(ids)!=1 or ids[0]["id"]!=first["sid"]:raise AssertionError("Same seller created a second store")
        self.shared_cid=shared["id"]
        with self.identity._write() as db:
            shared_job=q.enqueue(db,first["sid"],"OZ-07","2026-09-01","2026-09-30",cid=self.shared_cid,version=1,context={"reason":"stress-shared-key"},now=self.clock())
        self.jobs["OZ-07"].append(shared_job)
        with self.identity._write() as db:db.execute("DELETE FROM coin_grants")

    async def settle(self,jid,max_steps=150):
        for _ in range(max_steps):
            row=self.backend._row(self.identity._db,jid)
            if row["state"] in q.TERMINAL:return row
            if row["state"] in ("uncertain","denied","stopped"):return row
            due=row["expires"] if row["state"]=="running" else row["due"]
            if due>self.clock():self.clock.advance(due)
            job=self.backend.claim(job_id=jid)
            if job:await self.workers[0].run(job)
        raise AssertionError("Fixture job did not settle")

    def api(self,shop,operation,args,request_id,channel="ui"):
        started=time.monotonic()
        response=self.client.post(API,headers={"Authorization":"Bearer "+shop["token"]},
            json={"operation":operation,"arguments":args,"requestId":request_id,"channel":channel})
        elapsed=time.monotonic()-started
        if response.status_code!=200:raise AssertionError("Operation status "+str(response.status_code)+": "+response.text[:200])
        with self.metrics_lock:self.ui_latency.append(elapsed)
        return response.json()

    async def client_burst(self):
        shop=self.shops[0];args={"source":shop["sid"],"from":"2026-10-01","to":"2026-10-30"}
        count_before=sum(self.http_counts.values())
        def run(i):return self.api(shop,"market_sync_request",args,"stress-duplicate-"+str(i),"ui" if i%2 else "chat")
        with ThreadPoolExecutor(max_workers=100) as pool:
            results=await asyncio.to_thread(lambda:list(pool.map(run,range(1000))))
        gids={r.get("job_id",r.get("id")) for r in results}
        if len(gids)!=1 or None in gids:raise AssertionError("Duplicate client commands created different groups")
        if sum(self.http_counts.values())!=count_before:raise AssertionError("Client enqueue made provider requests")
        duplicate=self.identity._db.execute("SELECT count(*) FROM (SELECT store,source,since,until,sku,count(*) n FROM market_data_tasks GROUP BY store,source,since,until,sku HAVING n>1)").fetchone()[0]
        if duplicate:raise AssertionError("Duplicate logical template windows")
        self.counts.update(parallel_clients=100,duplicate_starts=1000,single_group=1)
        for i in range(20):self.api(self.shops[i%len(self.shops)],"market_catalog",{},"stress-baseline-"+str(i))
        return {"requests":1000,"max_parallel_clients":100,"logical_groups":len(gids),"duplicate_windows":duplicate,
                "provider_http_during_enqueue":sum(self.http_counts.values())-count_before,"latency":percentiles(self.ui_latency)}

    def next_jobs(self):
        jobs=[];used=set();future=[]
        for tid in sorted(TEMPLATES,key=lambda t:(self.http_counts[t],t)):
            candidates=self.jobs[tid];base=self.rotation[tid]%len(candidates)
            for shift in range(len(candidates)):
                jid=candidates[(base+shift)%len(candidates)];row=self.backend._row(self.identity._db,jid)
                if row["store"] in used or row["state"]=="uncertain":continue
                if row["state"] in q.TERMINAL:
                    with self.identity._write() as db:q.market_sync_control(db,row["workspace"],jid,"retry")
                    row=self.backend._row(self.identity._db,jid)
                due=row["expires"] if row["state"]=="running" else row["due"]
                if due>self.clock():future.append(due);continue
                claimed=self.backend.claim(job_id=jid)
                if claimed:
                    jobs.append(claimed);used.add(row["store"]);self.rotation[tid]+=1;break
            if len(jobs)>=len(self.workers):break
        if not jobs and future:self.clock.advance(min(future))
        return jobs

    def sample(self):
        states=dict(self.identity._db.execute("SELECT state,count(*) FROM market_data_tasks GROUP BY state"))
        active=sum(states.get(state,0) for state in q.ACTIVE)
        r=process_resources([os.getpid(),*[w.process.pid for w in self.workers if w.process.returncode is None]])
        sample={"wall_elapsed":round(time.monotonic()-self.started,3),"logical_at":self.clock(),"queue":states,"queued_tasks":active,**r,
                "http_total":sum(self.http_counts.values()),"http_by_template":dict(self.http_counts),"faults":dict(self.http_status)}
        self.samples.append(sample);dump(self.output/"progress.json",sample)
        if states.get("deferred",0):self.counts["samples_with_durable_deferred"]+=1
        if r["rss_total_mb"]>BUDGETS["rss_total_mb"] or r["open_descriptors_total"]>BUDGETS["open_descriptors_total"] or active>BUDGETS["queued_tasks"]:
            self.violations.append({"kind":"resource_budget","sample":sample})

    async def controls(self,tick):
        # Cancellation is performed by the public shared operation; a stopped
        # job must not admit a request, and resume must preserve checkpoint/due.
        tid=TEMPLATES[tick%len(TEMPLATES)];jid=self.jobs[tid][0];row=self.backend._row(self.identity._db,jid)
        if row["state"] in q.ACTIVE and row["state"]!="running":
            before=sum(self.http_counts.values());saved=(row["checkpoint"],row["due"])
            shop=self.by_cid[row["owner_cid"]]
            self.api(shop,"market_sync_control",{"job_id":jid,"action":"cancel"},"stress-cancel-"+str(tick))
            if self.backend.claim(job_id=jid) is not None:raise AssertionError("Stopped job was claimable")
            self.api(shop,"market_sync_control",{"job_id":jid,"action":"resume"},"stress-resume-"+str(tick),"chat")
            after=self.backend._row(self.identity._db,jid)
            if saved!=(after["checkpoint"],after["due"]) or before!=sum(self.http_counts.values()):raise AssertionError("Cancel/resume lost checkpoint or made HTTP")
            self.counts["cancellations_resumed"]+=1
        # A local reader must not see another owner's store even when source is
        # an actual ID rather than a provider selector.
        first,other=self.shops[0],self.shops[1]
        try:q.quantity_snapshot(self.identity._db,other["workspace"],first["sid"])
        except Exception as exc:
            if getattr(exc,"status_code",None)!=404:raise
        else:self.violations.append({"kind":"cross_client_leak"})
        self.counts["cross_client_denials"]+=1

    async def load(self):
        self.faults=True;start=time.monotonic();self.load_started=start;next_sample=next_controls=next_restart=start
        next_daily=start+min(30,self.args.duration/3);batches=0;crash_due=start+min(15,self.args.duration/4)
        permanent_job=self.jobs["OZ-02"][0];permanent_until=start+min(60,self.args.duration/2)
        timeout_due=start+min(5,self.args.duration/3);timeout_injected=False
        while time.monotonic()-start<self.args.duration:
            batch_started=time.monotonic();jobs=self.next_jobs()
            if jobs:
                tasks=[]
                for i,job in enumerate(jobs):
                    crash=time.monotonic()>=crash_due and i==0 and q.ROLE[job["source"]]!="identity" and self.counts["injected_process_crashes_after_local_commit"]<max(1,int(self.args.duration//60))
                    if crash:self.armed_crashes.add(job["id"]);crash_due=time.monotonic()+60
                    forced="permanent429" if job["id"]==permanent_job and time.monotonic()<permanent_until else None
                    if forced is None and (not timeout_injected and time.monotonic()>=timeout_due or batches and batches%113==0) and i==0:
                        fields=self.links.unpack(job["workspace"],job["owner_cid"],job["provider"],self.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?",(job["owner_cid"],)).fetchone()[0])
                        if not adapters.request(job["source"],json.loads(job["checkpoint"]),self.backend.context(job,fields)).get("generate"):
                            forced="timeout";timeout_injected=True
                    tasks.append(self.workers[i].run(job,crash=crash,forced=forced))
                await asyncio.gather(*tasks);batches+=1
            now=time.monotonic()
            if now>=next_sample:self.sample();next_sample=now+5
            if now>=next_controls:
                await self.controls(batches)
                shop=self.shops[batches%len(self.shops)]
                self.api(shop,"market_sales",{"from":"2026-10-01","to":"2026-10-30"},"stress-read-"+str(batches))
                next_controls=now+1
            if now>=next_restart:
                await self.workers[batches%len(self.workers)].restart(abrupt=True);next_restart=now+30
            if now>=next_daily:
                self.clock.advance(self.clock()+86401)
                self.counts["daily_maintenance_enqueues"]+=self.backend.maintenance_once()
                for shop in self.shops:
                    for tid in q.TEMPLATES[shop["provider"]]:
                        row=self.identity._db.execute("SELECT id FROM market_data_tasks WHERE store=? AND source=? AND json_extract(context,'$.reason')='daily' ORDER BY updated DESC LIMIT 1",(shop["sid"],tid)).fetchone()
                        if row and row[0] not in self.jobs[tid]:self.jobs[tid].append(row[0])
                next_daily=float("inf")
            # A sustained target rate; waits are short and actual elapsed time
            # remains independent of the accelerated quota clock.
            await asyncio.sleep(max(.001,len(jobs)/self.args.target_rate-(time.monotonic()-batch_started)))
        self.load_seconds=time.monotonic()-start;self.faults=False
        for tid in TEMPLATES:
            for jid in self.jobs[tid]:await self.settle(jid)
        self.sample()

    def verify(self):
        errors=[];physical=[];reconciled=Counter();daily_completed=0
        sentinels=("buyer-data-must-not-survive","999999","fixture-private-","https://cdn1.ozone.ru/s3/reports/","https://storage.yandexcloud.net/test-quantity/")
        with self.identity._lock:
            main_ok=self.identity._db.execute("PRAGMA integrity_check").fetchone()[0]
            if main_ok!="ok":errors.append("main_integrity")
            duplicates=self.identity._db.execute("SELECT count(*) FROM (SELECT store,source,since,until,sku,count(*) n FROM market_data_tasks GROUP BY store,source,since,until,sku HAVING n>1)").fetchone()[0]
            model_calls=self.identity._db.execute("SELECT count(*) FROM coin_attempts").fetchone()[0]
            recoveries=self.identity._db.execute("SELECT count(*) FROM market_data_events WHERE kind='receipt_recovered'").fetchone()[0]
            retries=self.identity._db.execute("SELECT count(*) FROM market_data_events WHERE kind IN ('waiting_retry','deferred') AND code IN ('429','503','timeout','connection_reset')").fetchone()[0]
            http_attempts=self.identity._db.execute("SELECT count(*) FROM market_data_events WHERE kind='http_attempt'").fetchone()[0]
            for shop in self.shops:
                daily_completed+=bool(self.identity._db.execute("SELECT 1 FROM market_data_tasks WHERE store=? AND json_extract(context,'$.reason')='daily' AND state IN ('ready','no_data_confirmed') LIMIT 1",(shop["sid"],)).fetchone())
                with q.local(self.identity._db,shop["workspace"],shop["provider"]) as db:
                    if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":errors.append("physical_integrity")
                    foreign=db.execute("SELECT count(*) FROM quantity_rows WHERE store!=?",(shop["sid"],)).fetchone()[0]
                    if foreign:errors.append("foreign_store")
                    bodies=[r[0] for tab in ("quantity_rows","quantity_catalog","quantity_coverage") for r in db.execute("SELECT body FROM "+tab)]
                    if any(s in raw for raw in bodies for s in sentinels):errors.append("forbidden_projection_field")
                    # Independent fixture numbers, not a second execution of the
                    # adapter under test: persistence/retry must retain these.
                    for tid,raw in db.execute("SELECT source,body FROM quantity_rows WHERE store=?",(shop["sid"],)):
                        row=json.loads(raw);expected={}
                        if tid in ("OZ-03","OZ-05","OZ-06"):expected={"ordered_qty":3,"delivered_qty":3}
                        elif tid=="OZ-04":expected={"physical_return_qty":1,"loss_event_qty":1}
                        elif tid=="WB-03":expected={"ordered_qty":12,"lost_qty":3,"buyout_qty":9}
                        elif tid=="YM-03":expected={"ordered_qty":5,"delivered_qty":4,"physical_return_qty":1,"nonbuyout_qty":1}
                        elif tid=="YM-04":expected={"physical_return_qty":1}
                        if expected:
                            if any(row.get(k)!=v for k,v in expected.items()):errors.append("quantity_reference_mismatch:"+tid)
                            else:reconciled[tid]+=1
                    physical.append({"workspace":shop["workspace"],"provider":shop["provider"],"store_id":shop["sid"],"rows":len(bodies),"integrity":"ok","foreign_rows":foreign})
        if duplicates:errors.append("duplicate_logical_jobs")
        if daily_completed!=len(self.shops):errors.append("daily_collection_not_completed_per_shop")
        if not self.connection_http[self.shared_cid]:errors.append("shared_seller_second_key_not_exercised")
        if model_calls or self.local_http_guard.await_count:errors.append("local_model_or_http")
        if source_digest()!=self.source_sha:errors.append("candidate_changed_during_run")
        for worker in self.workers:
            if worker.lab.errors:errors.extend(worker.lab.errors)
        ui=percentiles(self.ui_latency);steps=percentiles(self.worker_latency)
        cpu=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_seconds=cpu.ru_utime+cpu.ru_stime-self.initial_cpu.ru_utime-self.initial_cpu.ru_stime+children.ru_utime+children.ru_stime
        mean_cpu=cpu_seconds/max(1,time.monotonic()-self.started)
        if ui["p95_ms"]>BUDGETS["ui_p95_ms"] or ui["p99_ms"]>BUDGETS["ui_p99_ms"]:errors.append("ui_latency_budget")
        if steps["p95_ms"]>BUDGETS["worker_step_p95_ms"]:errors.append("worker_latency_budget")
        if mean_cpu>BUDGETS["mean_cpu_cores"]:errors.append("cpu_budget")
        if self.pending_recoveries:errors.append("unrecovered_injected_crash")
        if not recoveries and self.counts["injected_process_crashes_after_local_commit"]:errors.append("no_receipt_recovery")
        if self.counts["uncontrolled_crashes"]:errors.append("uncontrolled_crash")
        if self.violations:errors.append("runtime_invariants")
        minimums={t:self.http_counts[t]>=max(1,self.args.events_per_template) for t in TEMPLATES}
        provider_counts={p:sum(n for t,n in self.http_counts.items() if t.startswith(prefix)) for p,prefix in (("ozon","OZ-"),("wb","WB-"),("yandex_market","YM-"))}
        provider_minimums={p:n>=self.args.events_per_adapter for p,n in provider_counts.items()}
        if not all(minimums.values()):errors.append("template_event_minimum")
        if not all(provider_minimums.values()):errors.append("adapter_event_minimum")
        acceptance=self.args.duration>=1800 and self.args.shops>=20 and self.args.events_per_adapter>=1000
        if acceptance and self.load_seconds<1800:errors.append("wall_duration")
        return {"status":"PASS" if acceptance and not errors else "FAIL" if errors else "SMOKE",
            "acceptance_run":acceptance,"synthetic_data":True,"live_provider_calls":0,
            "clock":{"quota":"accelerated deterministic","latency":"monotonic wall","load_wall_seconds":round(self.load_seconds,3),"logical_start":NOW,"logical_end":self.clock()},
            "candidate_source_sha256":self.source_sha,"budgets":BUDGETS,"errors":sorted(set(errors)),"violations":self.violations,
            "clients":self.args.shops,"worker_processes":self.args.workers,"counts":dict(self.counts),
            "http_events":sum(self.http_counts.values()),"http_attempts_db":http_attempts,"http_by_template":dict(self.http_counts),"faults":dict(self.http_status),
            "stages":[{"template":t,"stage":s,"outcome":o,"count":n} for (t,s,o),n in sorted(self.stages.items())],
            "template_minimums":minimums,"adapter_minimums":provider_minimums,"http_by_adapter":provider_counts,
            "retry_events":retries,"receipt_recoveries":recoveries,"recovery_latency":percentiles(self.recovery_latency),
            "ui_latency":ui,"worker_step_latency":steps,"throughput_http_per_second":round(sum(self.http_counts.values())/max(1,self.load_seconds),3),
            "cpu_seconds":round(cpu_seconds,3),"mean_cpu_cores":round(mean_cpu,3),"resource_samples":self.samples,
            "physical_databases":physical,"shop_http_counts":dict(self.shop_http),"model_calls":model_calls,
            "reference_quantity_rows":dict(reconciled),"shops_with_completed_daily_collection":daily_completed,
            "shared_seller_distinct_keys_http":{"first_key":self.connection_http[self.shops[0]["cid"]],"second_key":self.connection_http[self.shared_cid]},
            "model_usage_journal_present":(self.output/"model-usage.jsonl").exists(),"local_http_calls":self.local_http_guard.await_count,
            "duplicate_logical_jobs":duplicates,"scope":"MP-T31/32/33/34 isolated stress; does not satisfy MP-T35 live shops or browser E2E"}

    async def close(self):
        for worker in self.workers:await worker.stop()
        self.stack.close()


async def main(args):
    h=Harness(args)
    preflight={"declared_at":datetime.now(timezone.utc).isoformat(),"candidate_source_sha256":h.source_sha,
        "budgets":BUDGETS,"configuration":vars(args),"host":{"system":platform.platform(),"cpu_count":os.cpu_count(),
        "memory_kb":next((int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:")),None),
        "disk_free_bytes":shutil.disk_usage(h.output).free},"provider_calls":"loopback only","quota_clock":"accelerated","wall_load":"real"}
    dump(h.output/"preflight.json",preflight)
    try:
        await h.setup();baseline=await h.client_burst();dump(h.output/"baseline.json",baseline)
        print(json.dumps({"event":"load_start","duration":args.duration,"budgets":BUDGETS,"baseline":baseline}),flush=True)
        await h.load()
        # Capture actual exited-process CPU before final resource accounting.
        for worker in h.workers:await worker.stop()
        report=h.verify();dump(h.output/"report.json",report)
        print(json.dumps({k:report[k] for k in ("status","errors","http_events","http_by_template","faults","counts","clock")}),flush=True)
        return 0 if report["status"] in ("PASS","SMOKE") else 1
    except BaseException as exc:
        dump(h.output/"aborted.json",{"status":"FAIL","error_type":type(exc).__name__,"message":str(exc)[:500],"source_sha256":h.source_sha})
        raise
    finally:await h.close()


def arguments():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--duration",type=float,default=1800);p.add_argument("--shops",type=int,default=24)
    p.add_argument("--workers",type=int,default=4);p.add_argument("--events-per-adapter",type=int,default=1000)
    p.add_argument("--events-per-template",type=int,default=0,help="Optional stricter per-template minimum; all18 must always be exercised")
    p.add_argument("--target-rate",type=float,default=40);p.add_argument("--output")
    p.add_argument("--child",action="store_true");p.add_argument("--database");p.add_argument("--port",type=int)
    a=p.parse_args()
    if not a.child and (not a.output or a.duration<=0 or a.shops<3 or not 1<=a.workers<=8 or a.target_rate<=0):p.error("Invalid stress configuration")
    return a


if __name__=="__main__":
    parsed=arguments()
    if parsed.child:asyncio.run(child_main(parsed))
    else:raise SystemExit(asyncio.run(main(parsed)))
