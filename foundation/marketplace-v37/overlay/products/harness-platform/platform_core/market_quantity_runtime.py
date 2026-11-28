"""Quantity backend of market_collect.Collector; no independent scheduler.

One HTTP stage per lease, durable pacing, private checkpoints, and a local
commit receipt before the main queue acknowledges a page or published snapshot.
"""
import asyncio
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import ssl
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from starlette.exceptions import HTTPException
from . import market_quantity as q, market_rate_limit as limiter
from . import market_quantity_registry as registry


class Fenced(Exception):pass

_PRIVATE_HTTP=ContextVar("market_quantity_private_http",default=False)

class _NetworkPrivacy(logging.Filter):
    def filter(self,record):
        # HTTPX logs full signed download URLs at INFO; HTTPcore can include
        # response headers at DEBUG. Preserve unrelated request logging, while
        # the marketplace executor emits its own sanitized event journal.
        return not _PRIVATE_HTTP.get()

def _protect_transport_logs():
    names={"httpx","httpcore","httpcore.connection","httpcore.http11","httpcore.http2","httpcore.proxy","httpcore.socks"}
    names.update(n for n in logging.Logger.manager.loggerDict if n.startswith(("httpx.","httpcore.")))
    for name in names:
        logger=logging.getLogger(name)
        if not any(isinstance(f,_NetworkPrivacy) for f in logger.filters):logger.addFilter(_NetworkPrivacy())


class Backend:
    def __init__(self,state,*,clock=None,jitter=None):
        self.state=state;self.clock=clock or time.time;self.jitter=jitter
        _protect_transport_logs()
        registry.validate_registry()

    def _row(self,db,jid):
        cur=db.execute("""SELECT j.*,s.workspace,s.provider,s.seller,s.metadata,s.verified
          FROM market_data_tasks j JOIN market_data_stores s ON s.id=j.store WHERE j.id=?""",(jid,))
        row=cur.fetchone()
        return dict(zip([c[0] for c in cur.description],row)) if row else None

    def guard(self,db,job,*,lease=True):
        row=self._row(db,job["id"])
        if not row or row["state"]!="running" or lease and row["lease"]!=job["lease"] or row["expires"]<=self.clock():raise Fenced()
        conn=db.execute("SELECT provider,encrypted,version FROM pm_market_connections WHERE id=? AND workspace=?",(row["owner_cid"],row["workspace"])).fetchone()
        if not conn or conn[0]!=row["provider"] or conn[2]!=row["key_version"] or not q.active_workspace(db,row["workspace"]):raise Fenced()
        if q.ROLE[row["source"]]!="identity" and not db.execute("SELECT 1 FROM market_data_links WHERE cid=? AND store=? AND version=?",(row["owner_cid"],row["store"],row["key_version"])).fetchone():raise Fenced()
        return row,conn[1]

    def claim(self,local_only=False,job_id=None):
        if local_only:return None
        now=self.clock()
        with self.state.identity._write() as db:
            self._reconcile_identity_waits(db,now,job_id)
            where=" AND j.id=?" if job_id else ""
            rows=db.execute("""SELECT j.id FROM market_data_tasks j WHERE
              ((j.state IN ('queued','collecting','waiting_retry','deferred') AND j.due<=?)
                OR (j.state='running' AND j.expires<=?))
              AND NOT EXISTS(SELECT 1 FROM market_data_tasks a WHERE a.store=j.store AND a.id!=j.id
                AND a.state='running' AND a.expires>?)"""+where+" ORDER BY j.due,j.updated,j.created LIMIT 30",(now,now,now,*([job_id] if job_id else []))).fetchall()
            for jid, in rows:
                job=self._row(db,jid)
                current=db.execute("SELECT version FROM pm_market_connections WHERE id=? AND workspace=?",(job["owner_cid"],job["workspace"])).fetchone()
                if current!=(job["key_version"],) or not q.active_workspace(db,job["workspace"]):
                    db.execute("UPDATE market_data_tasks SET state='stopped',lease=NULL,expires=0,detail='Доступ отозван или изменился.',updated=? WHERE id=?",(now,jid));continue
                if db.execute("SELECT 1 FROM market_data_denials WHERE cid=? AND version=? AND source=?",(job["owner_cid"],job["key_version"],job["source"])).fetchone():
                    db.execute("UPDATE market_data_tasks SET state='denied',detail='Источник приостановлен до проверки доступа.',updated=? WHERE id=?",(now,jid));continue
                lease=uuid4().hex
                db.execute("""UPDATE market_data_tasks SET state='running',lease=?,expires=?,started=coalesce(started,?),
                  cycle_started=coalesce(cycle_started,?),updated=? WHERE id=?""",(lease,now+90,now,now,now,jid))
                job=self._row(db,jid);q._event(db,jid,"claimed",now=now);return job
        return None

    def context(self,job,fields,*,db=None):
        if db is None:
            with self.state.identity._lock:
                return self.context(job,fields,db=self.state.identity._db)
        metadata=json.loads(job["metadata"]);extra=json.loads(job["context"])
        ctx={**metadata,**extra,"provider":job["provider"],"store":job["store"],"store_id":job["store"],
             "cid":job["owner_cid"],"version":job["key_version"],"seller":None if not job["verified"] else job["seller"],
             "from":job["since"],"to":job["until"],"now":self.clock()}
        if job["provider"]=="ozon":ctx["client_id"]=fields["client_id"];ctx["seller"]=fields["client_id"]
        if job["provider"]=="wb":
            # No caller-supplied class can relax the quota. A same-token
            # authenticated seller identity is required by the JWT contract.
            seller=job["seller"] if job["verified"] else None
            if seller is None:
                proven=db.execute("""SELECT DISTINCT s.seller FROM market_data_links l
                      JOIN market_data_stores s ON s.id=l.store
                      JOIN pm_market_connections c ON c.id=l.cid AND c.version=l.version
                      WHERE l.cid=? AND l.version=? AND s.workspace=? AND s.provider='wb' AND s.verified=1""",
                      (job["owner_cid"],job["key_version"],job["workspace"])).fetchall()
                if len(proven)==1:seller=proven[0][0]
            profile=registry.wb_token_profile(fields["token"],authenticated_seller=seller,now=self.clock())
            if seller is not None:ctx["seller"]=seller
            ctx.update(token_class=profile["token_class"],service_id=profile.get("service_id"))
        if not ctx.get("seller"):
            # An unconfirmed key cannot claim another seller identity. The
            # conservative service cap still applies; do not impose one key's
            # daily identity cooldown on every other new client.
            ctx["seller"]="unverified:"+hashlib.sha256(q.encode(fields).encode()).hexdigest()
        ctx.setdefault("token_class","base")
        return ctx

    def _identity_quota(self,db,job,fields,ctx,request,now):
        from . import market_quantity_providers as adapters
        if job["source"]!="WB-01" or str(ctx.get("seller","")).startswith("unverified:"):return now
        checked=db.execute("SELECT checked FROM pm_market_connections WHERE id=? AND version=? AND workspace=?",
                           (job["owner_cid"],job["key_version"],job["workspace"])).fetchone()
        if not checked or checked[0] is None:return now
        provisional={**ctx,"seller":"unverified:"+hashlib.sha256(q.encode(fields).encode()).hexdigest(),
                     "token_class":"base","service_id":None}
        old_request=adapters.request(job["source"],json.loads(job["checkpoint"]),provisional)
        return limiter.confirm_identity_scope(db,provisional,ctx,old_request,request,
                    max(float(checked[0]),float(job.get("last_attempt") or 0)),now)

    def _reconcile_identity_waits(self,db,now,job_id=None):
        from . import market_quantity_providers as adapters
        # Only a local quota_wait is eligible. Explicit Retry-After/backoff and
        # report deadlines are never reset by this proof-based reclassification.
        sql="SELECT id FROM market_data_tasks WHERE source='WB-01' AND state='waiting_retry' AND due>?"
        rows=db.execute(sql+(" AND id=?" if job_id else "")+" ORDER BY updated LIMIT 32",(now,*([job_id] if job_id else []))).fetchall()
        for jid, in rows:
            job=self._row(db,jid)
            event=db.execute("SELECT code,due FROM market_data_events WHERE job=? AND kind='waiting_retry' ORDER BY id DESC LIMIT 1",(jid,)).fetchone()
            if not event or event[0]!="quota_wait" or event[1]!=job["due"] or not q.active_workspace(db,job["workspace"]):continue
            connection=db.execute("SELECT encrypted FROM pm_market_connections WHERE id=? AND version=? AND workspace=?",(job["owner_cid"],job["key_version"],job["workspace"])).fetchone()
            if not connection:continue
            try:
                fields=self.state.market_links.unpack(job["workspace"],job["owner_cid"],job["provider"],connection[0])
                ctx=self.context(job,fields,db=db)
                if ctx.get("token_class") not in ("personal","service") or str(ctx["seller"]).startswith("unverified:"):continue
                request=adapters.request(job["source"],json.loads(job["checkpoint"]),ctx)
                due=self._identity_quota(db,job,fields,ctx,request,now)
            except (HTTPException,ValueError,KeyError,TypeError):
                db.execute("UPDATE market_data_tasks SET state='needs_attention',detail='Не удалось проверить сохранённый допуск подключения.',updated=? WHERE id=?",(now,jid))
                q._event(db,jid,"needs_attention",code="identity_scope_unavailable",now=now)
                continue
            db.execute("UPDATE market_data_tasks SET due=?,updated=? WHERE id=?",(due,now,jid))
            q._event(db,jid,"quota_scope_verified",code="same_generation_identity",due=due,now=now)

    @staticmethod
    def headers(provider,fields,request):
        if request.get("auth")=="none":return {"Accept":"application/octet-stream"}
        if provider=="ozon":return {"Client-Id":fields["client_id"],"Api-Key":fields["api_key"],"Accept":"application/json"}
        if provider=="wb":return {"Authorization":fields["token"],"Accept":"application/json"}
        return {"Api-Key":fields["api_key"],"Accept":"application/json"}

    async def transport(self,job,request,fields):
        """Bounded HTTPS only, no redirects, no auth on signed object downloads."""
        url=request["url"];u=urlsplit(url)
        allowed={"ozon":{"api-seller.ozon.ru"},"wb":{"common-api.wildberries.ru","content-api.wildberries.ru","seller-analytics-api.wildberries.ru","finance-api.wildberries.ru","statistics-api.wildberries.ru"},"yandex_market":{"api.partner.market.yandex.ru"}}
        if u.scheme!="https" or u.username or u.password or u.port not in (None,443) or u.fragment or "\\" in url:raise ValueError("origin")
        host=u.hostname or ""
        signed=request.get("download") and request.get("auth")=="none"
        if signed:
            from .market_quantity_providers import _grant_url,AdapterError
            try:_grant_url(url,job["provider"])
            except AdapterError:raise ValueError("origin") from None
            from .web_access import check_dns
            try:await check_dns(host)
            except ValueError:raise ValueError("origin") from None
        elif host not in allowed[job["provider"]]:raise ValueError("origin")
        size=min(int(request.get("max_bytes",32*1024**2)),32*1024**2)
        # HTTPX treats params={} as a replacement for the URL query. Signed
        # grants must retain every original query byte and receive no API key.
        kwargs={k:request[k] for k in ("json","params") if request.get(k) is not None and (k!="params" or request[k])}
        raw=bytearray()
        private=_PRIVATE_HTTP.set(True)
        try:
            async with self.state.http.stream(request["method"],url,headers=self.headers(job["provider"],fields,request),
                  timeout=float(request.get("timeout",30)),follow_redirects=False,**kwargs) as response:
                headers=dict(response.headers)
                length=headers.get("content-length")
                if length and (not length.isdigit() or int(length)>size):raise ValueError("report_too_large")
                async for part in response.aiter_bytes():
                    if len(raw)+len(part)>size:raise ValueError("report_too_large")
                    raw.extend(part)
                result={"status_code":response.status_code,"headers":headers}
        finally:_PRIVATE_HTTP.reset(private)
        if 200<=result["status_code"]<300:
            if request.get("download") and (request.get("response_kind")=="bytes" or signed):result["content"]=bytes(raw)
            elif result["status_code"]==204:result["payload"]=None
            else:
                try:result["payload"]=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(ValueError("invalid_json")))
                except (ValueError,UnicodeError,RecursionError):raise ValueError("invalid_json") from None
        return result

    def _pause(self,db,job,state,message,*,due=0,code=None,request=None,context=None,now=None):
        now=self.clock() if now is None else now
        self.guard(db,job)
        db.execute("""UPDATE market_data_tasks SET state=?,due=max(due,?),detail=?,lease=NULL,expires=0,
          inflight=CASE WHEN ?='uncertain' THEN inflight ELSE NULL END,updated=? WHERE id=? AND lease=?""",(state,due,message,state,now,job["id"],job["lease"]))
        q._event(db,job["id"],state,code=code,due=due,now=now)

    def _recover(self,db,job):
        with q.local(db,job["workspace"],job["provider"],True) as dest:
            row=dest.execute("SELECT outcome FROM quantity_step_receipts WHERE job=? AND epoch=? AND step=?",(job["id"],job["epoch"],job["step"])).fetchone()
        if row:
            self._ack(db,job,json.loads(row[0]),recovered=True)
            return True
        return False

    def _publish(self,db,job,out):
        """Commit normalized page plus recovery receipt; publish only complete windows."""
        now=self.clock();receipt=uuid4().hex
        outcome={k:out[k] for k in ("checkpoint","metadata","complete","next_due","state","coverage") if k in out}
        outcome["receipt"]=receipt
        # Do not retain raw provider JSON. Adapters whitelist quantity fields.
        with q.local(db,job["workspace"],job["provider"],True) as dest:
            for kind in ("rows","catalog"):
                for row in out.get(kind,[]):
                    key=str(row.get("natural_key") if kind=="rows" else row.get("sku"))
                    if key in ("None","") or len(key)>2048:raise ValueError("unknown_schema")
                    old=dest.execute("SELECT body FROM quantity_staging WHERE job=? AND epoch=? AND kind=? AND natural_key=?",(job["id"],job["epoch"],kind,key)).fetchone()
                    body=q.encode(row)
                    if old:raise ValueError("conflicting_duplicate")
                    dest.execute("INSERT OR IGNORE INTO quantity_staging VALUES(?,?,?,?,?)",(job["id"],job["epoch"],kind,key,body))
            if out.get("complete"):
                # A refreshed complete window replaces its previous projection as
                # one transaction; partial pages never erase the last good data.
                if q.ROLE[job["source"]]=="catalog":
                    dest.execute("DELETE FROM quantity_catalog WHERE store=?",(job["store"],))
                elif q.ROLE[job["source"]]=="boundary":
                    context=json.loads(job["context"])
                    posting=str(context.get("posting_number") or "");scheme=str(context.get("scheme") or "FBO").upper()
                    if not posting or scheme not in ("FBO","FBS"):raise ValueError("unknown_schema")
                    dest.execute("""DELETE FROM quantity_rows WHERE store=? AND source=?
                      AND json_extract(body,'$.posting_number')=? AND upper(json_extract(body,'$.scheme'))=?""",
                      (job["store"],job["source"],posting,scheme))
                elif job["source"]=="WB-03":
                    # Funnel quantities describe the entire requested interval.
                    # A larger window cannot replace a nested interval: the
                    # aggregate cannot be split back into days, and its retained
                    # coverage receipt would otherwise falsely prove empty data.
                    dest.execute("DELETE FROM quantity_rows WHERE store=? AND source=? AND since=? AND until=?",
                                 (job["store"],job["source"],job["since"],job["until"]))
                else:
                    dest.execute("DELETE FROM quantity_rows WHERE store=? AND source=? AND since>=? AND until<=?",(job["store"],job["source"],job["since"],job["until"]))
                for kind,key,body in dest.execute("SELECT kind,natural_key,body FROM quantity_staging WHERE job=? AND epoch=?",(job["id"],job["epoch"])).fetchall():
                    r=json.loads(body)
                    if kind=="catalog":
                        dest.execute("INSERT INTO quantity_catalog VALUES(?,?,?,?,?) ON CONFLICT(store,sku) DO UPDATE SET body=excluded.body,observed=excluded.observed,receipt=excluded.receipt",(job["store"],key,body,now,receipt))
                    else:
                        basis=r.get("quantity_basis")
                        day=(r.get("ordered_at") if basis=="order_cohort" else r.get("interval_from") if basis in ("funnel_interval","calendar_interval") else r.get("event_date")) or job["since"]
                        a=q.market_day(day) or "";b=q.market_day(r.get("interval_to") or day) or ""
                        dest.execute("""INSERT INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(store,source,natural_key)
                          DO UPDATE SET since=excluded.since,until=excluded.until,observed=excluded.observed,body=excluded.body,receipt=excluded.receipt,generation=excluded.generation""",(job["store"],job["source"],key,a,b,now,body,receipt,job["key_version"]))
                coverage=dict(out.get("coverage") or {})
                coverage.update(complete=True,state=out.get("state","ready"),schema_version="market-quantity/v1",observed_at=now)
                if q.ROLE[job["source"]]=="returns":coverage["observed_through"]=job["until"]
                dest.execute("""INSERT INTO quantity_coverage VALUES(?,?,?,?,?,?,?) ON CONFLICT(store,source,since,until)
                  DO UPDATE SET body=excluded.body,observed=excluded.observed,receipt=excluded.receipt""",(job["store"],job["source"],job["since"],job["until"],q.encode(coverage),now,receipt))
            dest.execute("INSERT INTO quantity_step_receipts VALUES(?,?,?,?,?,?)",(job["id"],job["epoch"],job["step"],receipt,q.encode(outcome),now))
        return outcome

    def _ack(self,db,job,outcome,*,recovered=False):
        self.guard(db,job)
        now=self.clock();complete=outcome.get("complete",False)
        state=outcome.get("state","ready") if complete else "queued"
        if complete and state not in q.TERMINAL:raise ValueError("unknown_schema")
        db.execute("""UPDATE market_data_tasks SET checkpoint=?,step=step+1,receipt=?,state=?,due=?,
          attempts=0,inflight=NULL,lease=NULL,expires=0,finished=?,updated=?,detail='' WHERE id=? AND lease=?""",
          (q.encode(outcome.get("checkpoint",{})),outcome["receipt"],state,float(outcome.get("next_due") or 0),now if complete else None,now,job["id"],job["lease"]))
        q._event(db,job["id"],"receipt_recovered" if recovered else "committed",now=now)
        if complete:
            if q.ROLE[job["source"]]=="identity":self._identity_done(db,job,outcome.get("metadata") or {})
            else:
                if job["source"]=="OZ-04":self._missing_postings(db,job)
                self._continue_history(db,job)
                self._finalize_history(db,job["store"])

    def _missing_postings(self,db,job):
        """Resolve orphan returns by posting ID, without declaring a full day."""
        with q.local(db,job["workspace"],job["provider"]) as dest:
            known={(str(r[0]).upper(),str(r[1]),str(r[2])) for r in dest.execute("SELECT json_extract(body,'$.scheme'),json_extract(body,'$.posting_number'),json_extract(body,'$.sku') FROM quantity_rows WHERE store=? AND source IN ('OZ-03','OZ-05','OZ-06')",(job["store"],)) if r[0] and r[1] and r[2]}
            missing=[json.loads(r[0]) for r in dest.execute("SELECT body FROM quantity_rows WHERE store=? AND source='OZ-04' AND since>=? AND until<=?",(job["store"],job["since"],job["until"]))]
        parent=json.loads(job["context"]).get("group_id")
        for row in missing:
            posting=str(row.get("posting_number") or "")
            scheme=str(row.get("scheme") or "").upper()
            key=(scheme,posting,str(row.get("sku") or ""))
            if not posting or key in known or scheme not in ("FBO","FBS"):continue
            day=q.market_day(row.get("ordered_at") or row.get("event_date")) or job["since"]
            context={"reason":"orphan_return","posting_number":posting,"scheme":scheme}
            if parent:context["group_id"]=parent
            q.enqueue(db,job["store"],"OZ-05",day,day,cid=job["owner_cid"],version=job["key_version"],context=context,now=self.clock())
            known.add(key)

    def _identity_done(self,db,job,metadata):
        provider=job["provider"];w=job["workspace"];cid=job["owner_cid"];v=job["key_version"]
        if provider=="yandex_market":
            campaigns=metadata.get("campaigns")
            if not isinstance(campaigns,list):raise ValueError("unknown_schema")
            for campaign in campaigns:
                seller=str(campaign["businessId"])+":campaign:"+str(campaign["campaignId"])
                sid=q.bind_verified(db,w,cid,v,provider,seller,{**metadata,**campaign},now=self.clock())
                self._migrate_yandex(db,w,cid,v,sid,campaign)
            checks={"Токен":"verified","Список магазинов":"verified"};details={**metadata,"complete":True}
        else:
            seller=metadata.get("seller")
            if provider=="ozon" and not seller:
                e=db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?",(cid,)).fetchone()[0]
                seller=self.state.market_links.unpack(w,cid,provider,e)["client_id"]
            if provider=="wb":
                e=db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?",(cid,)).fetchone()[0]
                fields=self.state.market_links.unpack(w,cid,provider,e)
                metadata={**metadata,**registry.wb_token_profile(fields["token"],authenticated_seller=seller,now=self.clock())}
            q.bind_verified(db,w,cid,v,provider,str(seller or ""),metadata,now=self.clock())
            checks={"Seller":"verified"} if provider=="ozon" else {"Профиль продавца":"verified"}
            details=metadata
        db.execute("UPDATE pm_market_connections SET checks=?,checked=?,details=? WHERE id=? AND version=?",(q.encode(checks),int(self.clock()),q.encode(details),cid,v))
        db.execute("DELETE FROM market_data_denials WHERE cid=? AND version=?",(cid,v))
        for s in q.selected_stores(db,w,cid):self.seed(db,s)

    def seed(self,db,s):
        now=self.clock();today=q.today(now);end=today-timedelta(days=1)
        gid=q.ensure_group(db,s["workspace"] if "workspace" in s else db.execute("SELECT workspace FROM market_data_stores WHERE id=?",(s["id"],)).fetchone()[0],s["id"],purpose="initial",now=now)
        if db.execute("SELECT state FROM market_data_groups WHERE id=?",(gid,)).fetchone()[0]=="stopped":return
        for tid in q.TEMPLATES[s["provider"]]:
            spec=registry.get_template(tid);history=spec["history"]
            if q.ROLE[tid]=="catalog":
                q.enqueue(db,s["id"],tid,cid=s["connection_id"],version=s["version"],context={"reason":"initial","group_id":gid});continue
            if history.get("max_lookback_days"):
                start=today-timedelta(days=history["max_lookback_days"])
                for a,b in q.windows(tid,str(start),str(end)):
                    q.enqueue(db,s["id"],tid,a,b,cid=s["connection_id"],version=s["version"],context={"reason":"initial","history_boundary":str(start),"group_id":gid})
            else:
                if tid=="YM-05":
                    start=end.replace(day=1)
                else:start=end-timedelta(days=(89 if tid=="OZ-03" else 29))
                boundary=history.get("earliest")
                if boundary:start=max(start,date.fromisoformat(boundary))
                job=self._history_job(db,s["id"],tid,str(start),str(end),s["connection_id"],s["version"],
                    {"reason":"initial","history_discovery":True,"history_boundary":boundary,"group_id":gid})
                if job["state"] in q.TERMINAL:self._continue_history(db,job)
        self._wb_window_edges(db,s,today,gid)
        db.execute("UPDATE market_data_schedule SET initial_version=?,next_due=?,history_detail=? WHERE store=?",(s["version"],now+86400,"Глубина подтверждается отдельно для каждого API; пустое окно не завершает исторический сбор.",s["id"]))
        self._finalize_history(db,s["id"])

    def _wb_window_edges(self,db,store,today,group):
        if store["provider"]!="wb":return
        from .podmasterye_market_analytics import MATURITY_DAYS
        retention=registry.get_template("WB-03")["history"]["max_lookback_days"]
        # Whole funnel intervals cannot be split when the mature 365-day
        # window moves. Preserve its future oldest day before API expiry and
        # observe its current maturity edge separately. Existing exact jobs,
        # checkpoints and cooldowns are reused by the shared queue.
        for days,reason in ((retention,"retention-boundary"),(MATURITY_DAYS,"maturity-boundary")):
            day=str(today-timedelta(days=days))
            q.enqueue(db,store["id"],"WB-03",day,day,cid=store["connection_id"],version=store["version"],
                      context={"reason":reason,"group_id":group},now=self.clock())

    def _finalize_history(self,db,store):
        row=db.execute("""SELECT s.provider,s.workspace,t.history_state,t.initial_version,t.paused
          FROM market_data_stores s JOIN market_data_schedule t ON t.store=s.id WHERE s.id=?""",(store,)).fetchone()
        if not row or row[2]=="complete" or not row[3] or row[4] or not q.active_workspace(db,row[1]):return
        group=db.execute("SELECT id,state FROM market_data_groups WHERE source=? AND purpose='initial'",(store,)).fetchone()
        if not group or group[1]!="active":return
        today=q.today(self.clock());end=str(today-timedelta(days=1))
        for source in q.TEMPLATES[row[0]]:
            history=registry.get_template(source)["history"]
            if q.ROLE[source]=="catalog":start=None
            elif history.get("max_lookback_days"):start=str(today-timedelta(days=history["max_lookback_days"]))
            elif history.get("earliest"):start=history["earliest"]
            else:return  # Empty windows never establish an unknown API floor.
            jobs=db.execute("""SELECT j.since,j.until,j.state FROM market_data_tasks j
              JOIN market_data_group_tasks link ON link.task_id=j.id
              JOIN pm_market_connections c ON c.id=j.owner_cid AND c.version=j.key_version
              JOIN market_data_links access ON access.store=j.store AND access.cid=c.id AND access.version=c.version
              WHERE link.group_id=? AND j.store=? AND j.source=?""",(group[0],store,source)).fetchall()
            if not jobs or any(state not in q.TERMINAL for _,_,state in jobs):return
            if start is not None and q._subtract(start,end,[(a,b) for a,b,_ in jobs if a and b]):return
        db.execute("""UPDATE market_data_schedule SET history_state='complete',history_detail=? WHERE store=?""",
          ("Первичная история всех обязательных источников собрана до документированных границ API. Ежедневное обновление продолжается.",store))

    def _history_job(self,db,store,source,start,end,cid,version,context):
        context=dict(context)
        if source=="YM-05":context["month"]=start[:7]
        jid=q.enqueue(db,store,source,start,end,cid=cid,version=version,context=context,now=self.clock())
        job=self._row(db,jid)
        # A manual/daily job may already own this exact interval. Attach the
        # initial-history continuation without resetting its report, lease,
        # cursor, cooldown, generation or explicit stopped state.
        current=json.loads(job["context"])
        current.update({key:context[key] for key in ("history_discovery","history_boundary","group_id") if key in context})
        encoded=q.encode(current)
        if encoded!=job["context"]:
            db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(encoded,jid))
            job["context"]=encoded
        return job

    def _continue_history(self,db,job):
        # Another channel can attach history to an already dispatched job.
        # Read its current annotation, rather than the pre-HTTP lease snapshot.
        current=self._row(db,job["id"])
        ctx=json.loads(current["context"] if current else job["context"])
        if ctx.get("group_id") and db.execute("SELECT state FROM market_data_groups WHERE id=?",(ctx["group_id"],)).fetchone()==("stopped",):return
        if not ctx.get("history_discovery") or not job["since"]:return
        since=job["since"]
        while True:
            end=date.fromisoformat(since)-timedelta(days=1)
            boundary=ctx.get("history_boundary")
            if boundary and str(end)<boundary:return
            # Unknown provider boundaries are never claimed complete. Stop only
            # at a documented bound or explicit attention for invalid dates.
            if end.year<2000:
                db.execute("UPDATE market_data_schedule SET history_state='needs_attention',history_detail='API не подтвердил нижнюю границу истории; требуется сверка доступности.' WHERE store=?",(job["store"],));return
            start=end.replace(day=1) if job["source"]=="YM-05" else end-timedelta(days=89 if job["source"]=="OZ-03" else 29)
            if boundary:start=max(start,date.fromisoformat(boundary))
            following=self._history_job(db,job["store"],job["source"],str(start),str(end),job["owner_cid"],job["key_version"],ctx)
            if following["state"] not in q.TERMINAL:return
            # A completed cached interval needs no second HTTP/report. Walk to
            # the next older interval within the same atomic queue transaction.
            since=following["since"]

    def _recover_history(self,db):
        tails={}
        rows=db.execute("""SELECT DISTINCT j.id,j.store,j.source,j.since,s.workspace
          FROM market_data_tasks j JOIN market_data_stores s ON s.id=j.store
          JOIN market_data_schedule schedule ON schedule.store=j.store AND schedule.paused=0
          JOIN market_data_group_tasks link ON link.task_id=j.id
          JOIN market_data_groups g ON g.id=link.group_id AND g.purpose='initial' AND g.state='active'
          JOIN pm_market_connections c ON c.id=j.owner_cid AND c.version=j.key_version AND c.workspace=s.workspace
          JOIN market_data_links access ON access.store=j.store AND access.cid=c.id AND access.version=c.version
          WHERE j.state IN ('ready','no_data_confirmed') AND j.since<>''
          AND json_extract(j.context,'$.history_discovery')=1""").fetchall()
        for jid,store,source,since,workspace in rows:
            if not q.active_workspace(db,workspace):continue
            key=(store,source)
            if key not in tails or since<tails[key][0]:tails[key]=(since,jid)
        for _,jid in tails.values():self._continue_history(db,self._row(db,jid))
        for store,_ in tails:self._finalize_history(db,store)

    def _migrate_yandex(self,db,w,cid,version,sid,campaign):
        bid,cam=campaign["businessId"],campaign["campaignId"]
        marker="ym-v35:"+cid+":"+str(version)+":"+str(cam)
        if db.execute("SELECT 1 FROM market_quantity_migrations WHERE id=?",(marker,)).fetchone():return
        # Reuse the exact calendar rows, never fabricate order cohorts.
        snaps=db.execute("SELECT month,collected,data FROM (SELECT month,updated AS collected,data FROM pm_ym_realization WHERE cid=? AND version=? AND campaign=? AND state='ready' AND data IS NOT NULL)",(cid,version,cam)).fetchall()
        with q.local(db,w,"yandex_market",True) as dest:
            for month,observed,raw in snaps:
                d=json.loads(raw);a=month+"-01";n=(date.fromisoformat(a).replace(day=28)+timedelta(days=4)).replace(day=1);b=str(n-timedelta(days=1));receipt=hashlib.sha256((marker+month+raw).encode()).hexdigest()
                for r in d.get("rows",[]):
                    key=f"realization:{month}:{r['kind']}:{r['orderId']}:{r['sku']}:{r['date']}"
                    out={"natural_key":key,"sku":r["sku"],"order_id":str(r["orderId"]),"event_date":r["date"],"quantity_basis":"calendar_event","delivered_qty":r.get("delivered",0),"physical_return_qty":r.get("returned",0),"nonbuyout_qty":r.get("unredeemed",0),"ordered_qty":None,"original_order_known":False,"physical_returns_known":True,"complete":True,"schema_version":"market-quantity/v1","source_id":"YM-05","observed_at":observed}
                    dest.execute("INSERT OR IGNORE INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?)",(sid,"YM-05",key,r["date"],r["date"],observed,q.encode(out),receipt,version))
                basis="calendar_event";complete=True
                if not d.get("rows") and d.get("products"):
                    basis="calendar_interval"
                    for r in d["products"]:
                        values=[r.get(k) for k in ("delivered","returned","unredeemed")]
                        if any(type(x) is not int or x<0 for x in values):complete=False;continue
                        key=f"legacy-realization:{month}:{r['sku']}"
                        out={"natural_key":key,"sku":r["sku"],"name":r.get("name",r["sku"]),"quantity_basis":"calendar_interval","interval_from":a,"interval_to":b,"delivered_qty":values[0],"physical_return_qty":values[1],"nonbuyout_qty":values[2],"ordered_qty":None,"original_order_known":False,"physical_returns_known":True,"complete":True,"schema_version":"market-quantity/v1","source_id":"YM-05","observed_at":observed}
                        dest.execute("INSERT OR IGNORE INTO quantity_rows VALUES(?,?,?,?,?,?,?,?,?)",(sid,"YM-05",key,a,b,observed,q.encode(out),receipt,version))
                elif not d.get("rows") and any(d.get("totals",{}).get(k,0) for k in ("delivered","returned","unredeemed")):
                    complete=False
                coverage={"quantity_basis":basis,"complete":complete,"state":"ready" if complete else "partial","physical_returns_known":complete,"migration":"v35"}
                dest.execute("INSERT OR IGNORE INTO quantity_coverage VALUES(?,?,?,?,?,?,?)",(sid,"YM-05",a,b,q.encode(coverage),observed,receipt))
        for sku,product in db.execute("SELECT sku,product FROM pm_ym_product_links WHERE cid=? AND campaign=? AND business=?",(cid,cam,bid)):
            db.execute("INSERT OR IGNORE INTO market_quantity_links(workspace,store,sku,product) VALUES(?,?,?,?)",(w,sid,sku,product))
        db.execute("INSERT INTO market_quantity_migrations VALUES(?,?,?)",(marker,self.clock(),hashlib.sha256(q.encode([len(snaps),sid]).encode()).hexdigest()))

    def maintenance_once(self):
        count=0;now=self.clock()
        with self.state.identity._write() as db:
            # Repair an already persisted ready->cached-ready chain after a
            # restart, independently of tomorrow's daily-refresh deadline.
            self._recover_history(db)
            for cid,w,version,checks,checked in db.execute("SELECT id,workspace,version,checks,checked FROM pm_market_connections").fetchall():
                if not q.active_workspace(db,w):continue
                if checked is not None and "verified" in json.loads(checks).values() and not db.execute("SELECT 1 FROM market_data_links l JOIN market_data_stores s ON s.id=l.store WHERE l.cid=? AND l.version=? AND s.verified=1",(cid,version)).fetchone():
                    q.enqueue_identity(db,w,cid);count+=1
            due=db.execute("SELECT s.workspace,s.id FROM market_data_schedule t JOIN market_data_stores s ON s.id=t.store WHERE t.next_due<=? AND t.paused=0",(now,)).fetchall()
            for w,sid in due:
                try:stores=q.selected_stores(db,w,sid)
                except HTTPException:continue
                if not stores or not q.active_workspace(db,w):continue
                s=stores[0];initial=db.execute("SELECT initial_version FROM market_data_schedule WHERE store=?",(sid,)).fetchone()[0]
                if initial!=s["version"]:self.seed(db,s);count+=1;continue
                today=q.today(now);gid=q.ensure_group(db,w,sid,purpose="initial",now=now)
                for tid in q.TEMPLATES[s["provider"]]:
                    if q.ROLE[tid]=="catalog":q.enqueue(db,sid,tid,cid=s["connection_id"],version=s["version"],refresh=True,context={"reason":"daily","group_id":gid})
                    else:
                        # Revisit mutable cohorts and recently updated returns;
                        # older settled windows remain local. Return adapters use
                        # their documented update axis, joining original orders.
                        lo=today-timedelta(days=60 if q.ROLE[tid]=="orders" else 30)
                        q._request_window(db,s,tid,str(lo),str(today),reason="daily",refresh=True,group_id=gid)
                self._wb_window_edges(db,s,today,gid)
                # An unresolved outcome remains mutable regardless of its age.
                # Refresh only its original source window (or one Ozon posting),
                # not every old settled order.
                with q.local(db,w,s["provider"],True) as dest:
                    mutable=dest.execute("""SELECT source,since,until,body FROM quantity_rows WHERE store=?
                      AND (json_extract(body,'$.terminal')=0 OR coalesce(json_extract(body,'$.unresolved_qty'),0)>0)""",(sid,)).fetchall()
                for source,a,b,raw in mutable:
                    if not a or a>=str(today-timedelta(days=60)):continue
                    row=json.loads(raw)
                    if s["provider"]=="ozon" and row.get("posting_number"):
                        q.enqueue(db,sid,"OZ-05",a,a,cid=s["connection_id"],version=s["version"],context={"reason":"unresolved","posting_number":row["posting_number"],"scheme":row.get("scheme","FBO"),"group_id":gid},refresh=True)
                    elif source in q.TEMPLATES[s["provider"]]:
                        q._request_window(db,s,source,a,b,reason="unresolved",refresh=True,group_id=gid)
                db.execute("UPDATE market_data_schedule SET next_due=? WHERE store=?",(now+86400,sid));count+=1
        return count

    async def maintenance(self):
        while True:
            try:self.maintenance_once()
            except asyncio.CancelledError:raise
            except Exception as e:logging.getLogger(__name__).warning("Marketplace maintenance deferred: %s",type(e).__name__)
            await asyncio.sleep(30)

    async def run(self,job):
        from . import market_quantity_providers as adapters
        permits=None;request=None;ctx=None;started=self.clock()
        try:
            with self.state.identity._write() as db:
                job,encrypted=self.guard(db,job)
                if self._recover(db,job):return
                if job["inflight"] and json.loads(job["inflight"]).get("generate"):
                    self._pause(db,job,"uncertain","Неизвестен исход создания отчёта. Сохранённое задание требует сверки.",code="generate_unknown");return
                fields=self.state.market_links.unpack(job["workspace"],job["owner_cid"],job["provider"],encrypted)
                ctx=self.context(job,fields,db=db);cp=json.loads(job["checkpoint"])
                request=adapters.request(job["source"],cp,ctx)
                self._identity_quota(db,job,fields,ctx,request,self.clock())
                permits,due=limiter.acquire(db,job,ctx,request,self.clock())
                if permits is None:
                    self._pause(db,job,"waiting_retry","Ожидаем разрешённого времени запроса площадки.",due=due,code="quota_wait");return
                db.execute("UPDATE market_data_tasks SET requests=requests+1,last_attempt=?,inflight=?,updated=? WHERE id=? AND lease=?",(self.clock(),q.encode({"generate":bool(request.get("generate")),"stage":request["stage"],"step":job["step"]}),self.clock(),job["id"],job["lease"]))
                q._event(db,job["id"],"http_attempt",code=request["stage"],now=self.clock())
            response=await self.transport(job,request,fields)
            status=response["status_code"]
            decision=registry.classify_error(job["source"],status,generate=request.get("generate",False),provider=job["provider"],download=request.get("download",False),signed_download=bool(request.get("download") and request.get("auth")=="none"))
            if decision=="success":
                out=adapters.consume(job["source"],cp,ctx,response)
                secrets=[v for k,v in fields.items() if k in ("api_key","token","performance_secret") and isinstance(v,str) and v]
                def reject_echo(value):
                    if isinstance(value,str):
                        if any(value==s or len(s)>=8 and s in value for s in secrets):raise ValueError("unknown_schema")
                    elif isinstance(value,dict):
                        for k,v in value.items():reject_echo(k);reject_echo(v)
                    elif isinstance(value,list):
                        for v in value:reject_echo(v)
                reject_echo(out)
                with self.state.identity._write() as db:
                    limiter.observe_success(db,ctx,request,response.get("headers",{}),self.clock())
                    try:self.guard(db,job)
                    except Fenced:
                        self._retain_stopped_report(db,job,out,request)
                        # Exiting normally commits the retained checkpoint;
                        # re-raising here would roll that safety write back.
                        return
                    outcome=self._publish(db,job,out)
                    self._ack(db,job,outcome)
                return
            if decision=="refresh_report":
                if not cp.get("report_id"):
                    decision="needs_attention"
                else:
                    refreshes=int(cp.get("download_refreshes",0))+1
                    if refreshes>3:
                        with self.state.identity._write() as db:
                            self._pause(db,job,"needs_attention","Площадка не разрешила скачать существующий отчёт после обновления ссылки. Данные сохранены; нужна проверка отчёта.",code="download_refresh_exhausted")
                        return
                    cp["download_refreshes"]=refreshes
                    cp["stage"]="poll";cp.pop("grant_url",None);cp.pop("url",None)
                    with self.state.identity._write() as db:
                        self.guard(db,job)
                        db.execute("UPDATE market_data_tasks SET checkpoint=?,inflight=NULL WHERE id=? AND lease=?",(q.encode(cp),job["id"],job["lease"]))
                        self._pause(db,job,"waiting_retry","Обновляем ссылку существующего отчёта.",due=limiter.retry_due(response.get("headers",{}),self.clock(),request["quota_profile"],refreshes,jitter=self.jitter),code="report_expired")
                    return
            await self._failure(job,request,ctx,decision,str(status),response.get("headers",{}))
        except Fenced:return
        except asyncio.CancelledError:
            # Lease recovery reconciles a committed receipt before deciding that
            # an in-flight generate is uncertain. Do not clear the evidence.
            raise
        except (httpx.TransportError,ssl.SSLError) as e:
            message=str(e).lower()
            kind="tls" if isinstance(e,ssl.SSLError) or "certificate" in message or "ssl" in message else "timeout" if isinstance(e,httpx.TimeoutException) else "temporary_dns" if "name" in message or "dns" in message else "connection_reset"
            decision=registry.classify_error(job["source"],error=kind,generate=bool(request and request.get("generate")),provider=job["provider"])
            await self._failure(job,request,ctx,decision,kind,{})
        except (sqlite3.Error,OSError):
            # Never acknowledge a database/disk failure. The durable inflight
            # marker and local receipt decide safe recovery after lease expiry.
            logging.getLogger(__name__).warning("Marketplace persistence deferred; job %s",job["id"])
        except Exception as e:
            code=getattr(e,"code",None) or (str(e) if isinstance(e,ValueError) and str(e) in {"origin","invalid_json","report_too_large","unknown_schema","conflicting_duplicate"} else "unknown_schema")
            # A malformed success response can hide a created report just as a
            # lost connection can. Never turn it into a repeatable generation.
            state="uncertain" if request and request.get("generate") and code!="origin" else "needs_attention" if code in ("origin","report_too_large") else "partial"
            try:
                with self.state.identity._write() as db:self._pause(db,job,state,"Исход создания отчёта неизвестен. Повторное создание запрещено." if state=="uncertain" else "Площадка не подтвердила структуру или полноту данных. Последний полный снимок сохранён.",code=code)
            except Fenced:pass
        finally:
            if permits:
                try:
                    with self.state.identity._write() as db:
                        limiter.release(db,permits)
                        q._event(db,job["id"],"attempt_finished",elapsed=max(0,self.clock()-started),now=self.clock())
                except (sqlite3.Error,OSError):pass

    def _retain_stopped_report(self,db,job,out,request):
        """Cancellation does not lose a generate response already in flight."""
        current=self._row(db,job["id"])
        cp=out.get("checkpoint") or {}
        if not request.get("generate") or not cp.get("report_id") or not current:return
        conn=db.execute("SELECT version FROM pm_market_connections WHERE id=?",(job["owner_cid"],)).fetchone()
        if current["state"]!="stopped" or current["epoch"]!=job["epoch"] or current["step"]!=job["step"] or current["key_version"]!=job["key_version"] or conn!=(job["key_version"],):return
        db.execute("UPDATE market_data_tasks SET checkpoint=?,inflight=NULL,step=step+1,updated=? WHERE id=?",(q.encode(cp),self.clock(),job["id"]))
        q._event(db,job["id"],"stopped_report_retained",now=self.clock())

    async def _failure(self,job,request,ctx,decision,code,headers):
        now=self.clock()
        with self.state.identity._write() as db:
            current,_=self.guard(db,job)
            if decision in ("retry","rate_limited"):
                attempts=current["attempts"]+1;p=request["quota_profile"]
                due=limiter.retry_due(headers,now,p,attempts,jitter=self.jitter)
                if decision=="rate_limited":limiter.cooldown(db,ctx,request,due,now)
                exhausted=attempts>=int(p.get("max_active_retries",5)) or now-(current["cycle_started"] or now)>=float(p.get("max_cycle_seconds",900))
                state="deferred" if exhausted else "waiting_retry"
                if exhausted:due=max(due,now+3600)
                db.execute("UPDATE market_data_tasks SET attempts=?,retries=retries+1,rate_limits=rate_limits+?,cycle_started=CASE WHEN ? THEN NULL ELSE cycle_started END WHERE id=?",(0 if exhausted else attempts,int(decision=="rate_limited"),exhausted,job["id"]))
                self._pause(db,job,state,"Площадка ограничила запросы; продолжение не ранее разрешённого срока." if decision=="rate_limited" else "Временная ошибка связи; задание сохранено для повторной попытки.",due=due,code=code)
            else:
                if decision=="denied":
                    db.execute("INSERT OR REPLACE INTO market_data_denials VALUES(?,?,?,?)",(job["owner_cid"],job["key_version"],job["source"],now))
                    db.execute("""UPDATE market_data_tasks SET state='denied',lease=NULL,expires=0,
                      detail='Источник приостановлен до проверки доступа.',updated=?
                      WHERE owner_cid=? AND key_version=? AND source=? AND id<>? AND state NOT IN ('ready','no_data_confirmed')""",(now,job["owner_cid"],job["key_version"],job["source"],job["id"]))
                text={"denied":"Площадка отказала в доступе. Проверьте ключ и разрешения.","uncertain":"Исход создания отчёта неизвестен. Автоматический повтор запрещён.","needs_attention":"Площадка отклонила запрос. Требуется проверка доступа или контракта API."}.get(decision,"Данные не подтверждены.")
                self._pause(db,job,decision,text,code=code)

