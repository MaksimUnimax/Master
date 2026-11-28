"""Workshop projection of the shared marketplace store, queue and receipts.

This module supplies the Workshop connection/quantity contract to market_collect.
It uses market_data.local/path_for and the existing market_data_tasks queue name;
the financial Octoport source catalogue is never activated in this product.
No provider I/O, model calls, financial payloads or secret values belong here.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from starlette.exceptions import HTTPException
from . import market_data

PROVIDERS = ("ozon", "wb", "yandex_market")
IDENTITY = {"ozon": "OZ-01", "wb": "WB-01", "yandex_market": "YM-01"}
TEMPLATES = {"ozon": ("OZ-02", "OZ-03", "OZ-04", "OZ-06"),
             "wb": ("WB-02", "WB-03", "WB-04"),
             "yandex_market": ("YM-02", "YM-03", "YM-04", "YM-05")}
ROLE = {"OZ-01":"identity", "OZ-02":"catalog", "OZ-03":"orders", "OZ-04":"returns", "OZ-05":"boundary", "OZ-06":"orders", "OZ-07":"stocks",
        "WB-01":"identity", "WB-02":"catalog", "WB-03":"orders", "WB-04":"realization", "WB-05":"stocks",
        "YM-01":"identity", "YM-02":"catalog", "YM-03":"orders", "YM-04":"returns", "YM-05":"realization", "YM-06":"stocks"}
TERMINAL = {"ready", "no_data_confirmed"}
ACTIVE = {"queued", "running", "collecting", "waiting_retry", "deferred"}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS market_data_profile(id INTEGER PRIMARY KEY CHECK(id=1),profile TEXT NOT NULL,version INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS market_data_stores(
      id TEXT PRIMARY KEY,workspace TEXT NOT NULL,provider TEXT NOT NULL,seller TEXT NOT NULL,
      metadata TEXT NOT NULL DEFAULT '{}',verified INTEGER NOT NULL DEFAULT 0,
      UNIQUE(workspace,provider,seller))""",
    """CREATE TABLE IF NOT EXISTS market_data_links(
      cid TEXT NOT NULL REFERENCES pm_market_connections(id) ON DELETE CASCADE,
      store TEXT NOT NULL REFERENCES market_data_stores(id),version INTEGER NOT NULL,
      PRIMARY KEY(cid,store))""",
    """CREATE TABLE IF NOT EXISTS market_data_tasks(
      id TEXT PRIMARY KEY,store TEXT NOT NULL REFERENCES market_data_stores(id),source TEXT NOT NULL,
      since TEXT NOT NULL DEFAULT '',until TEXT NOT NULL DEFAULT '',sku TEXT NOT NULL DEFAULT '',
      owner_cid TEXT REFERENCES pm_market_connections(id) ON DELETE SET NULL,
      key_version INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'queued',due REAL NOT NULL DEFAULT 0,
      lease TEXT,expires REAL NOT NULL DEFAULT 0,detail TEXT NOT NULL DEFAULT '',
      requests INTEGER NOT NULL DEFAULT 0,finished REAL,started REAL,last_attempt REAL,
      receipt TEXT,checkpoint TEXT NOT NULL DEFAULT '{}',context TEXT NOT NULL DEFAULT '{}',
      step INTEGER NOT NULL DEFAULT 0,epoch INTEGER NOT NULL DEFAULT 1,
      attempts INTEGER NOT NULL DEFAULT 0,retries INTEGER NOT NULL DEFAULT 0,rate_limits INTEGER NOT NULL DEFAULT 0,
      cycle_started REAL,inflight TEXT,created REAL NOT NULL,updated REAL NOT NULL,
      UNIQUE(store,source,since,until,sku))""",
    "CREATE INDEX IF NOT EXISTS market_data_due ON market_data_tasks(state,due,expires)",
    """CREATE TABLE IF NOT EXISTS market_data_quota(
      scope TEXT PRIMARY KEY,due REAL NOT NULL DEFAULT 0,cooldown REAL NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS market_data_permits(
      id TEXT PRIMARY KEY,scope TEXT NOT NULL,job TEXT NOT NULL,lease TEXT NOT NULL,expires REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS market_permit_scope ON market_data_permits(scope,expires)",
    """CREATE TABLE IF NOT EXISTS market_data_denials(
      cid TEXT NOT NULL,version INTEGER NOT NULL,source TEXT NOT NULL,checked REAL NOT NULL,
      PRIMARY KEY(cid,version,source))""",
    """CREATE TABLE IF NOT EXISTS market_data_events(
      id INTEGER PRIMARY KEY,job TEXT,kind TEXT NOT NULL,at REAL NOT NULL,code TEXT,
      due REAL,scope TEXT,elapsed REAL)""",
    """CREATE TABLE IF NOT EXISTS market_operation_receipts(
      workspace TEXT NOT NULL,rid TEXT NOT NULL,operation TEXT NOT NULL,fingerprint TEXT NOT NULL,
      result TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(workspace,rid))""",
    """CREATE TABLE IF NOT EXISTS market_quantity_links(
      workspace TEXT NOT NULL,store TEXT NOT NULL REFERENCES market_data_stores(id),
      sku TEXT NOT NULL,product TEXT NOT NULL REFERENCES pm_products(id),
      revision INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(store,sku))""",
    """CREATE TABLE IF NOT EXISTS market_mapping_revisions(
      store TEXT NOT NULL,sku TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(store,sku))""",
    """CREATE TABLE IF NOT EXISTS market_quantity_migrations(
      id TEXT PRIMARY KEY,applied REAL NOT NULL,receipt TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS market_data_schedule(
      store TEXT PRIMARY KEY REFERENCES market_data_stores(id),next_due REAL NOT NULL,
      initial_version INTEGER NOT NULL DEFAULT 0,history_state TEXT NOT NULL DEFAULT 'discovering',
      history_detail TEXT NOT NULL DEFAULT '',paused INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS market_data_groups(
      id TEXT PRIMARY KEY,workspace TEXT NOT NULL,source TEXT NOT NULL,since TEXT NOT NULL,
      until TEXT NOT NULL,purpose TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'active',
      created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(workspace,source,since,until,purpose))""",
    """CREATE TABLE IF NOT EXISTS market_data_group_tasks(
      group_id TEXT NOT NULL REFERENCES market_data_groups(id),task_id TEXT NOT NULL REFERENCES market_data_tasks(id),
      PRIMARY KEY(group_id,task_id))""",
)
LOCAL = (
    """CREATE TABLE IF NOT EXISTS quantity_rows(
      store TEXT NOT NULL,source TEXT NOT NULL,natural_key TEXT NOT NULL,
      since TEXT NOT NULL,until TEXT NOT NULL,observed REAL NOT NULL,body TEXT NOT NULL,
      receipt TEXT NOT NULL,generation INTEGER NOT NULL,PRIMARY KEY(store,source,natural_key))""",
    "CREATE INDEX IF NOT EXISTS quantity_period ON quantity_rows(store,source,since,until)",
    """CREATE TABLE IF NOT EXISTS quantity_catalog(
      store TEXT NOT NULL,sku TEXT NOT NULL,body TEXT NOT NULL,observed REAL NOT NULL,
      receipt TEXT NOT NULL,PRIMARY KEY(store,sku))""",
    """CREATE TABLE IF NOT EXISTS quantity_staging(
      job TEXT NOT NULL,epoch INTEGER NOT NULL,kind TEXT NOT NULL,natural_key TEXT NOT NULL,
      body TEXT NOT NULL,PRIMARY KEY(job,epoch,kind,natural_key))""",
    """CREATE TABLE IF NOT EXISTS quantity_step_receipts(
      job TEXT NOT NULL,epoch INTEGER NOT NULL,step INTEGER NOT NULL,receipt TEXT NOT NULL,
      outcome TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(job,epoch,step))""",
    """CREATE TABLE IF NOT EXISTS quantity_coverage(
      store TEXT NOT NULL,source TEXT NOT NULL,since TEXT NOT NULL,until TEXT NOT NULL,
      body TEXT NOT NULL,observed REAL NOT NULL,receipt TEXT NOT NULL,
      PRIMARY KEY(store,source,since,until))""",
)

def encode(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def main_path(db):
    value=next((r[2] for r in db.execute("PRAGMA database_list") if r[1]=="main"),"")
    if not value:raise ValueError("Для истории требуется постоянная база данных.")
    return Path(value)

def install(db):
    existing=db.execute("SELECT 1 FROM sqlite_master WHERE name='market_data_tasks'").fetchone()
    profile=db.execute("SELECT 1 FROM sqlite_master WHERE name='market_data_profile'").fetchone()
    if existing and not profile:
        raise RuntimeError("Marketplace queue requires an explicit product-profile migration")
    for sql in SCHEMA:db.execute(sql)
    if "paused" not in {r[1] for r in db.execute("PRAGMA table_info(market_data_schedule)")}:
        db.execute("ALTER TABLE market_data_schedule ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
    db.execute("INSERT OR IGNORE INTO market_data_profile VALUES(1,'workshop-quantities',1)")
    if db.execute("SELECT profile FROM market_data_profile WHERE id=1").fetchone()[0]!="workshop-quantities":
        raise RuntimeError("Marketplace queue belongs to a different product contract")

@contextmanager
def local(db,w,provider,create=False):
    with market_data.local(main_path(db),w,provider,create) as dest:
        if create:
            for sql in LOCAL:dest.execute(sql)
        elif not dest.in_transaction:
            # SELECT alone does not start a Python SQLite transaction. Freeze
            # rows, catalogue and coverage at one committed local snapshot.
            dest.execute("BEGIN")
        yield dest

def active_workspace(db,w):
    # The worker must recheck account/workshop lifecycle, not only a stored token.
    r=db.execute("SELECT account,archived FROM pm_workshops WHERE id=?",(w,)).fetchone()
    account=r[0] if r else w
    if r and r[1]:return False
    if not db.execute("SELECT 1 FROM identity_accounts a JOIN workspaces w ON w.workspace_id=a.workspace_id AND w.owner_id=a.actor_id WHERE a.workspace_id=?",(account,)).fetchone():return False
    # Later platform lifecycle versions are optional in the production baseline.
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='account_lifecycle'").fetchone():
        cols={r[1] for r in db.execute("PRAGMA table_info(account_lifecycle)")}
        if {"workspace","state"}<=cols:
            r=db.execute("SELECT state FROM account_lifecycle WHERE workspace=?",(account,)).fetchone()
            if r and r[0]!="active":return False
    return True

def receipt(db,w,rid,operation,args,result=None):
    if rid is None:return None
    from .podmasterye_domain import key_id
    key_id(rid);fingerprint=sha256(encode(args).encode()).hexdigest()
    old=db.execute("SELECT operation,fingerprint,result FROM market_operation_receipts WHERE workspace=? AND rid=?",(w,rid)).fetchone()
    if old:
        if old[:2]!=(operation,fingerprint):raise HTTPException(409,"Идентификатор запроса уже использован с другими параметрами.")
        return json.loads(old[2])
    if result is not None:
        db.execute("INSERT INTO market_operation_receipts VALUES(?,?,?,?,?,?)",(w,rid,operation,fingerprint,encode(result),time.time()))
    return None

def selected_stores(db,w,source="all_marketplaces",*,include_unverified=False):
    if not isinstance(source,str) or len(source)>256:raise ValueError("Некорректный источник.")
    rows=db.execute("""SELECT s.id,s.provider,s.seller,s.metadata,s.verified,l.cid,l.version,c.name,c.checked
      FROM market_data_stores s JOIN market_data_links l ON l.store=s.id
      JOIN pm_market_connections c ON c.id=l.cid AND c.workspace=s.workspace AND c.provider=s.provider
      WHERE s.workspace=? AND l.version=c.version ORDER BY coalesce(c.checked,0) DESC,c.name,l.cid,s.id""",(w,)).fetchall()
    out={}
    confirmed_cids={r[5] for r in rows if r[4]}
    for sid,p,seller,metadata,verified,cid,version,name,checked in rows:
        if not include_unverified and not verified:continue
        if not verified and cid in confirmed_cids:continue
        if source not in ("all_marketplaces",p,sid,cid):continue
        if sid not in out:out[sid]={"id":sid,"store_id":sid,"provider":p,"seller":seller,"metadata":json.loads(metadata),"verified":bool(verified),"connection_id":cid,"version":version,"name":name,"checked":checked}
    if source not in ("all_marketplaces",*PROVIDERS) and not out:
        if not db.execute("SELECT 1 FROM pm_market_connections WHERE id=? AND workspace=?",(source,w)).fetchone():
            raise HTTPException(404,"Подтверждённый магазин не найден.")
    return list(out.values())

def _event(db,job,kind,*,code=None,due=None,scope=None,elapsed=None,now=None):
    db.execute("INSERT INTO market_data_events(job,kind,at,code,due,scope,elapsed) VALUES(?,?,?,?,?,?,?)",(job,kind,now if now is not None else time.time(),code,due,scope,elapsed))

def enqueue(db,store,template,since="",until="",*,cid,version,context=None,refresh=False,now=None):
    now=time.time() if now is None else now
    selector="";old=None
    if template=="OZ-05":
        posting=str((context or {}).get("posting_number", ""));scheme=str((context or {}).get("scheme","FBO")).upper()
        selector=scheme+":"+posting
        # A boundary lookup identifies one posting, independent of how many
        # return events/days requested it. Reuse earlier candidate checkpoints.
        old=db.execute("SELECT id,state,owner_cid,key_version FROM market_data_tasks WHERE store=? AND source='OZ-05' AND sku IN (?,?) AND upper(coalesce(json_extract(context,'$.scheme'),'FBO'))=? ORDER BY created LIMIT 1",(store,selector,posting,scheme)).fetchone()
        since=until=""
    key=(store,template,since,until,selector)
    if old is None:old=db.execute("SELECT id,state,owner_cid,key_version FROM market_data_tasks WHERE (store,source,since,until,sku)=(?,?,?,?,?)",key).fetchone()
    if old:
        if (context or {}).get("group_id"):
            db.execute("INSERT OR IGNORE INTO market_data_group_tasks VALUES(?,?)",(context["group_id"],old[0]))
        if old[2] is None or old[2]!=cid and old[1]=="denied":
            if not db.execute("SELECT 1 FROM market_data_links l JOIN pm_market_connections c ON c.id=l.cid AND c.version=l.version WHERE l.store=? AND l.cid=? AND l.version=?",(store,cid,version)).fetchone():raise HTTPException(409,"Сначала подтвердите подключение магазина.")
            raw,old_context,inflight=db.execute("SELECT checkpoint,context,inflight FROM market_data_tasks WHERE id=?",(old[0],)).fetchone()
            cp=json.loads(raw);ctx=json.loads(old_context);cp.pop("binding",None)
            uncertain=bool(inflight and json.loads(inflight).get("generate") and not cp.get("report_id"))
            resume=ctx.pop("access_invalidated",False) or old[1]=="denied"
            state="uncertain" if uncertain else "queued" if resume and old[1] not in TERMINAL else old[1]
            db.execute("UPDATE market_data_tasks SET owner_cid=?,key_version=?,state=?,checkpoint=?,context=?,lease=NULL,expires=0,updated=? WHERE id=?",(cid,version,state,encode(cp),encode(ctx),now,old[0]))
            old=(old[0],state,cid,version)
        refresh_identity=ROLE[template]=="identity" and refresh
        if refresh_identity or refresh and old[1] in TERMINAL|{"partial","denied","needs_attention"}:
            saved=json.loads(db.execute("SELECT checkpoint FROM market_data_tasks WHERE id=?",(old[0],)).fetchone()[0])
            # An acknowledged report survives a failed poll/download. Only a
            # completed historical refresh may start a new report generation.
            retain=old[1] not in TERMINAL and bool(saved.get("report_id")) and not refresh_identity
            if retain:
                db.execute("""UPDATE market_data_tasks SET owner_cid=?,key_version=?,state='queued',due=max(due,?),
                  lease=NULL,expires=0,attempts=0,cycle_started=NULL,inflight=NULL,finished=NULL,updated=? WHERE id=?""",(cid,version,now,now,old[0]))
                return old[0]
            db.execute("""UPDATE market_data_tasks SET owner_cid=?,key_version=?,state='queued',due=max(due,?),
              lease=NULL,expires=0,checkpoint='{}',step=0,epoch=epoch+1,attempts=0,cycle_started=NULL,
              inflight=NULL,finished=NULL,context=?,updated=? WHERE id=?""",(cid,version,now,encode(context or {}),now,old[0]))
        return old[0]
    jid=uuid4().hex
    db.execute("""INSERT INTO market_data_tasks(id,store,source,since,until,sku,owner_cid,key_version,context,created,updated)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(jid,store,template,since,until,selector,cid,version,encode(context or {}),now,now))
    _event(db,jid,"enqueued",now=now)
    if (context or {}).get("group_id"):
        db.execute("INSERT OR IGNORE INTO market_data_group_tasks VALUES(?,?)",(context["group_id"],jid))
    return jid

def enqueue_identity(db,w,cid,*,refresh=False):
    row=db.execute("SELECT provider,version FROM pm_market_connections WHERE id=? AND workspace=?",(cid,w)).fetchone()
    if not row:raise HTTPException(404,"Подключение не найдено.")
    p,v=row
    sid=sha256((w+"\0"+p+"\0pending:"+cid).encode()).hexdigest()[:32]
    db.execute("INSERT OR IGNORE INTO market_data_stores(id,workspace,provider,seller) VALUES(?,?,?,?)",(sid,w,p,"pending:"+cid))
    db.execute("INSERT INTO market_data_links VALUES(?,?,?) ON CONFLICT(cid,store) DO UPDATE SET version=excluded.version",(cid,sid,v))
    return enqueue(db,sid,IDENTITY[p],cid=cid,version=v,refresh=refresh)

def bind_verified(db,w,cid,version,provider,seller,metadata,*,now=None):
    if not isinstance(seller,str) or not seller or len(seller)>256:raise ValueError("Идентичность магазина не подтверждена.")
    now=time.time() if now is None else now
    row=db.execute("SELECT version FROM pm_market_connections WHERE workspace=? AND id=? AND provider=?",(w,cid,provider)).fetchone()
    if row!=(version,):raise HTTPException(409,"Подключение изменилось.")
    current=db.execute("""SELECT s.seller FROM market_data_links l JOIN market_data_stores s ON s.id=l.store
      WHERE l.cid=? AND s.verified=1""",(cid,)).fetchall()
    # One YM key can own several campaigns. A rotation cannot silently replace its business.
    old_ids={s[0].split(":campaign:",1)[0] for s in current}
    if old_ids and seller.split(":campaign:",1)[0] not in old_ids:
        raise HTTPException(409,"Ключ относится к другому магазину. Добавьте отдельное подключение.")
    sid=uuid4().hex
    db.execute("INSERT OR IGNORE INTO market_data_stores(id,workspace,provider,seller,metadata,verified) VALUES(?,?,?,?,?,1)",(sid,w,provider,seller,encode(metadata)))
    sid=db.execute("SELECT id FROM market_data_stores WHERE workspace=? AND provider=? AND seller=?",(w,provider,seller)).fetchone()[0]
    db.execute("UPDATE market_data_stores SET metadata=?,verified=1 WHERE id=?",(encode(metadata),sid))
    db.execute("INSERT INTO market_data_links VALUES(?,?,?) ON CONFLICT(cid,store) DO UPDATE SET version=excluded.version",(cid,sid,version))
    # A verified replacement key for the same seller resumes the existing
    # logical jobs. Retain report IDs/cursors; a lost generate response stays
    # uncertain. Never make a second business identity from the key version.
    for jid,old_version,state,raw,inflight,context in db.execute("SELECT id,key_version,state,checkpoint,inflight,context FROM market_data_tasks WHERE store=? AND owner_cid=?",(sid,cid)).fetchall():
        if old_version==version:continue
        cp=json.loads(raw);ctx=json.loads(context)
        cp.pop("binding",None)
        uncertain=bool(inflight and json.loads(inflight).get("generate") and not cp.get("report_id"))
        next_state="uncertain" if uncertain else "queued" if ctx.pop("access_invalidated",False) and state not in TERMINAL else state
        db.execute("UPDATE market_data_tasks SET key_version=?,checkpoint=?,context=?,state=?,inflight=?,lease=NULL,expires=0,updated=? WHERE id=?",(version,encode(cp),encode(ctx),next_state,inflight if uncertain else None,now,jid))
    db.execute("INSERT OR IGNORE INTO market_data_schedule(store,next_due) VALUES(?,?)",(sid,now))
    with local(db,w,provider,True):pass
    return sid

def invalidate_connection(db,cid,reason="Подключение изменилось."):
    for jid,raw in db.execute("SELECT id,context FROM market_data_tasks WHERE owner_cid=? AND state NOT IN ('ready','no_data_confirmed','stopped')",(cid,)).fetchall():
        ctx=json.loads(raw);ctx["access_invalidated"]=True
        db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(encode(ctx),jid))
    db.execute("""UPDATE market_data_tasks SET state='stopped',lease=NULL,expires=0,detail=?,updated=?
      WHERE owner_cid=? AND state NOT IN ('ready','no_data_confirmed')""",(reason,time.time(),cid))
    # Leave prior complete snapshots and quota cooldown untouched.

def _date(value):
    if not isinstance(value,str) or len(value)!=10:raise ValueError("Укажите дату ГГГГ-ММ-ДД.")
    return date.fromisoformat(value)

def today(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now,ZoneInfo("Europe/Moscow")).date()

def market_day(value):
    """Provider dates use Moscow calendar days; preserve already local dates."""
    if not value:return None
    value=str(value)
    if len(value)==10:return date.fromisoformat(value).isoformat()
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is not None:parsed=parsed.astimezone(ZoneInfo("Europe/Moscow"))
    return parsed.date().isoformat()

def ensure_group(db,w,source,since="",until="",purpose="user",*,now=None):
    stamp=time.time() if now is None else now
    gid=uuid4().hex
    db.execute("INSERT OR IGNORE INTO market_data_groups(id,workspace,source,since,until,purpose,created,updated) VALUES(?,?,?,?,?,?,?,?)",(gid,w,source,since,until,purpose,stamp,stamp))
    return db.execute("SELECT id FROM market_data_groups WHERE workspace=? AND source=? AND since=? AND until=? AND purpose=?",(w,source,since,until,purpose)).fetchone()[0]

def group_public(db,gid,w):
    r=db.execute("SELECT id,source,since,until,purpose,state,created,updated FROM market_data_groups WHERE id=? AND workspace=?",(gid,w)).fetchone()
    if not r:raise HTTPException(404,"Задание не найдено.")
    out=dict(zip(("id","source","from","to","purpose","state","created","updated"),r))
    tasks=db.execute("SELECT j.id,j.state,j.due,j.requests,j.retries,j.rate_limits FROM market_data_tasks j JOIN market_data_group_tasks g ON g.task_id=j.id WHERE g.group_id=? ORDER BY j.updated DESC",(gid,)).fetchall()
    counts={}
    for task in tasks:counts[task[1]]=counts.get(task[1],0)+1
    completed=sum(counts.get(s,0) for s in TERMINAL)
    if out["state"]!="stopped":
        out["state"]="collecting" if any(counts.get(s) for s in ("queued","collecting","running")) else "waiting_retry" if any(counts.get(s) for s in ("waiting_retry","deferred")) else "ready" if tasks and completed==len(tasks) else "partial"
        if out["purpose"]=="initial" and out["state"]=="ready":
            history=db.execute("SELECT history_state FROM market_data_schedule WHERE store=?",(out["source"],)).fetchone()
            if not history or history[0]!="complete":out["state"]="partial"
    out.update(job_id=gid,type="group",progress={"total":len(tasks),"complete":completed,"states":counts},
               jobs=[job_public(db,t[0],w) for t in tasks[:300]],has_more_jobs=len(tasks)>300,
               requests=sum(t[3] for t in tasks),retries=sum(t[4] for t in tasks),rate_limits=sum(t[5] for t in tasks),
               next_retry_at=min((t[2] for t in tasks if t[1] in ("waiting_retry","deferred")),default=None))
    if out["purpose"]=="initial":
        row=db.execute("SELECT history_state,history_detail,next_due,paused FROM market_data_schedule WHERE store=?",(out["source"],)).fetchone()
        if row:out["history"]={"state":row[0],"message":row[1],"next_update_at":row[2],"paused":bool(row[3])}
        out["progress"]["earliest_completed_window"]=db.execute("SELECT min(j.since) FROM market_data_tasks j JOIN market_data_group_tasks g ON g.task_id=j.id WHERE g.group_id=? AND j.state IN ('ready','no_data_confirmed') AND j.since!=''",(gid,)).fetchone()[0]
    return out

def windows(template,a,b):
    a,b=_date(a),_date(b)
    if a>b:raise ValueError("Начальная дата позже конечной.")
    while a<=b:
        if template=="YM-05":
            first=a.replace(day=1)
            following=(first.replace(day=28)+timedelta(days=4)).replace(day=1)
            end=following-timedelta(days=1)
            # The report is an indivisible calendar month. Its complete
            # window may be wider than the user's local display filter.
            yield first.isoformat(),min(end,today()).isoformat();a=following
        else:
            days=90 if template=="OZ-03" else 30
            end=min(b,a+timedelta(days=days-1));yield a.isoformat(),end.isoformat();a=end+timedelta(days=1)

def _subtract(a,b,covered):
    remaining=[(_date(a),_date(b))]
    for x,y in covered:
        lo,hi=_date(x),_date(y);next_=[]
        for start,end in remaining:
            if hi<start or lo>end:next_.append((start,end));continue
            if start<lo:next_.append((start,lo-timedelta(days=1)))
            if end>hi:next_.append((hi+timedelta(days=1),end))
        remaining=next_
    return [(str(x),str(y)) for x,y in remaining]

def _request_window(db,s,template,a,b,*,reason,refresh=False,group_id=None):
    matches=db.execute("""SELECT id,since,until,state FROM market_data_tasks WHERE store=? AND source=?
      AND since<=? AND until>=? AND state NOT IN ('stopped','denied','uncertain','needs_attention','partial')""",(s["id"],template,b,a)).fetchall()
    ids=[r[0] for r in matches]
    context={"reason":reason,**({"group_id":group_id} if group_id else {})}
    if template=="WB-03" and refresh:
        # Funnel aggregates are indivisible. Refresh their original intervals,
        # never create a sliding partially overlapping aggregate.
        for jid,x,y,state in matches:
            if state in TERMINAL:
                qid=enqueue(db,s["id"],template,x,y,cid=s["connection_id"],version=s["version"],context=context,refresh=True)
                ids.append(qid)
        covered=[(r[1],r[2]) for r in matches]
    else:covered=[(r[1],r[2]) for r in matches if not (refresh and r[3] in TERMINAL)]
    for x,y in _subtract(a,b,covered):
        for lo,hi in windows(template,x,y):
            ids.append(enqueue(db,s["id"],template,lo,hi,cid=s["connection_id"],version=s["version"],context=context,refresh=refresh))
    if group_id:
        db.executemany("INSERT OR IGNORE INTO market_data_group_tasks VALUES(?,?)",((group_id,jid) for jid in set(ids)))
    return list(dict.fromkeys(ids))

def market_sync_request(db,w,source="all_marketplaces",from_=None,to=None,request_id=None,refresh=False,**kw):
    from_=kw.pop("from",from_)
    if kw:raise ValueError("Неизвестные параметры синхронизации.")
    if type(refresh) is not bool:raise ValueError("Некорректный режим обновления.")
    args={"source":source,"from":from_,"to":to,"refresh":refresh}
    old=receipt(db,w,request_id,"sync",args)
    if old:return old
    current=today()
    end=_date(to) if to else current
    start=_date(from_) if from_ else end-timedelta(days=29)
    if end>current or start>end:raise ValueError("Некорректный период синхронизации.")
    stores=selected_stores(db,w,source)
    gid=ensure_group(db,w,source,str(start),str(end))
    ids=[]
    for s in stores:
        for tid in TEMPLATES[s["provider"]]:
            if ROLE[tid]=="catalog":ids.append(enqueue(db,s["id"],tid,cid=s["connection_id"],version=s["version"],context={"group_id":gid},refresh=refresh));continue
            if tid=="WB-03" and start<current-timedelta(days=365):
                lo=max(start,current-timedelta(days=365))
            elif tid=="WB-04":lo=max(start,date(2024,1,29))
            else:lo=start
            if lo<=end:ids.extend(_request_window(db,s,tid,str(lo),str(end),reason="user",group_id=gid,refresh=refresh))
    result=group_public(db,gid,w)
    result.update(job_ids=list(dict.fromkeys(ids)),message="История поставлена в очередь." if ids else "Нет подтверждённых магазинов. Проверьте подключение.")
    receipt(db,w,request_id,"sync",args,result)
    return result

def job_public(db,jid,w):
    if db.execute("SELECT 1 FROM market_data_groups WHERE id=? AND workspace=?",(jid,w)).fetchone():return group_public(db,jid,w)
    row=db.execute("""SELECT j.id,j.source,j.state,j.since,j.until,j.due,j.detail,j.requests,j.retries,j.rate_limits,
      j.started,j.finished,j.updated,j.step,s.provider,s.id,c.name,j.checkpoint,j.receipt
      FROM market_data_tasks j JOIN market_data_stores s ON s.id=j.store
      LEFT JOIN pm_market_connections c ON c.id=j.owner_cid WHERE j.id=? AND s.workspace=?""",(jid,w)).fetchone()
    if not row:raise HTTPException(404,"Задание не найдено.")
    keys=("id","template_id","state","from","to","next_retry_at","message","requests","retries","rate_limits","started","finished","updated","confirmed_steps","provider","store_id","store_name","checkpoint","receipt")
    out=dict(zip(keys,row));cp=json.loads(out.pop("checkpoint"))
    out["state"]="collecting" if out["state"] in ("queued","running") else "waiting_retry" if out["state"]=="deferred" else out["state"]
    out["job_id"]=out["id"]
    out["progress"]={k:cp[k] for k in ("stage","page","pages","row_count","rows_count","total") if k in cp and isinstance(cp[k],(str,int,float))}
    # report ID is safe; signed download URLs/cursors/secret metadata never enter public output.
    if isinstance(cp.get("report_id"),str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}",cp["report_id"]):out["report_id"]=cp["report_id"]
    return out

def market_sync_control(db,w,job_id,action,request_id=None):
    if action not in ("cancel","stop","resume","retry"):raise ValueError("Неизвестное действие задания.")
    args={"job_id":job_id,"action":action};old=receipt(db,w,request_id,"control",args)
    if old:return old
    job_public(db,job_id,w)
    group=db.execute("SELECT source,purpose FROM market_data_groups WHERE id=? AND workspace=?",(job_id,w)).fetchone()
    if group:
        blocked=[]
        for child, in db.execute("SELECT task_id FROM market_data_group_tasks WHERE group_id=?",(job_id,)).fetchall():
            try:_control_task(db,w,child,action)
            except HTTPException as exc:blocked.append({"job_id":child,"message":exc.detail})
        stopped=action in ("stop","cancel")
        db.execute("UPDATE market_data_groups SET state=?,updated=? WHERE id=?",("stopped" if stopped else "active",time.time(),job_id))
        if group[1]=="initial":db.execute("UPDATE market_data_schedule SET paused=? WHERE store=?",(int(stopped),group[0]))
        result=group_public(db,job_id,w)
        if blocked:result["blocked_jobs"]=blocked
    else:
        _control_task(db,w,job_id,action);result=job_public(db,job_id,w)
    receipt(db,w,request_id,"control",args,result);return result

def _control_task(db,w,job_id,action):
    state,cid,version,inflight=db.execute("SELECT state,owner_cid,key_version,inflight FROM market_data_tasks WHERE id=?",(job_id,)).fetchone()
    if action in ("cancel","stop"):
        if state in TERMINAL:return
        raw=db.execute("SELECT context FROM market_data_tasks WHERE id=?",(job_id,)).fetchone()[0]
        ctx=json.loads(raw);ctx.pop("access_invalidated",None)
        db.execute("UPDATE market_data_tasks SET context=? WHERE id=?",(encode(ctx),job_id))
        db.execute("UPDATE market_data_tasks SET state='stopped',detail='Остановлено пользователем.',lease=NULL,expires=0,updated=? WHERE id=?",(time.time(),job_id))
    else:
        current=db.execute("SELECT version FROM pm_market_connections WHERE id=? AND workspace=?",(cid,w)).fetchone()
        if current!=(version,):raise HTTPException(409,"Сначала проверьте действующий ключ подключения.")
        if state=="uncertain" or (inflight and json.loads(inflight).get("generate")):
            raise HTTPException(409,"Исход создания отчёта неизвестен. Нужна сверка; повторное создание запрещено.")
        if state in ACTIVE or state in TERMINAL and action=="resume":return
        reset=state in TERMINAL
        db.execute("""UPDATE market_data_tasks SET state='queued',lease=NULL,expires=0,attempts=0,cycle_started=NULL,
          detail='',finished=NULL,checkpoint=CASE WHEN ? THEN '{}' ELSE checkpoint END,
          step=CASE WHEN ? THEN 0 ELSE step END,epoch=epoch+?,updated=? WHERE id=?""",(reset,reset,int(reset),time.time(),job_id))
    _event(db,job_id,action)

def market_sync_status(db,w,source="all_marketplaces",job_id=None):
    if job_id:return job_public(db,job_id,w)
    stores=selected_stores(db,w,source,include_unverified=True)
    ids=[s["id"] for s in stores]
    jobs=[]
    if ids:
        marks=",".join("?" for _ in ids)
        jobs=[job_public(db,r[0],w) for r in db.execute(f"SELECT id FROM market_data_tasks WHERE store IN ({marks}) ORDER BY updated DESC LIMIT 300",ids)]
    groups=[group_public(db,r[0],w) for r in db.execute("SELECT id FROM market_data_groups WHERE workspace=? ORDER BY updated DESC",(w,)) if source=="all_marketplaces" or any(j["store_id"] in ids for j in group_public(db,r[0],w)["jobs"])]
    snap=quantity_snapshot(db,w,source)
    state="ready" if jobs and all(j["state"] in TERMINAL for j in jobs) else "collecting" if any(j["state"]=="collecting" for j in jobs) else "waiting_retry" if any(j["state"]=="waiting_retry" for j in jobs) else "partial"
    return {"state":state,"stores":[{k:v for k,v in s.items() if k not in ("seller","metadata")} for s in stores],"groups":groups,"jobs":jobs,"coverage":snap["coverage"],"last_success":max((c.get("observed_at",0) for c in snap["coverage"] if c.get("complete")),default=None),"has_more_jobs":len(jobs)==300}

def quantity_snapshot(db,workspace,source="all_marketplaces",start=None,end=None):
    stores=selected_stores(db,workspace,source)
    rows=[];coverage=[];observed=0
    def missing(s,state="not_collected"):
        for tid in TEMPLATES[s["provider"]]:
            if ROLE[tid] in ("catalog","stocks"):continue
            if not any(c["store_id"]==s["id"] and c["source_id"]==tid for c in coverage):
                coverage.append({"provider":s["provider"],"store_id":s["id"],"source_id":tid,"role":ROLE[tid],"required":True,"authoritative":True,"complete":False,"state":state,"from":start,"to":end})
    for s in stores:
        p=market_data.path_for(main_path(db),workspace,s["provider"])
        if not p.exists():missing(s);continue
        row_start=len(rows);coverage_start=len(coverage)
        try:
            with local(db,workspace,s["provider"]) as dest:
                if not dest.execute("SELECT 1 FROM sqlite_master WHERE name='quantity_rows'").fetchone():missing(s);continue
                query="SELECT body,source,observed,generation FROM quantity_rows WHERE store=?";params=[s["id"]]
                if start:query+=" AND until>=?";params.append(start)
                if end:query+=" AND since<=?";params.append(end)
                mappings=dict(db.execute("SELECT sku,product FROM market_quantity_links WHERE workspace=? AND store=?",(workspace,s["id"])))
                catalog={sku:json.loads(body) for sku,body in dest.execute("SELECT sku,body FROM quantity_catalog WHERE store=?",(s["id"],))}
                names=dict(db.execute("SELECT id,name FROM pm_products WHERE workspace=?",(workspace,)))
                for body,tid,stamp,generation in dest.execute(query,params):
                    r=json.loads(body);r.update(provider=s["provider"],store_id=s["id"],connection_id=s["connection_id"],source_id=tid,generation=generation)
                    sku=str(r.get("sku",""));r["product_id"]=mappings.get(sku)
                    card=catalog.get(sku,{})
                    for key in ("category_id","name"):
                        if not r.get(key) and card.get(key) is not None:r[key]=card[key]
                    r["product_name"]=names.get(r["product_id"])
                    rows.append(r);observed=max(observed,stamp)
                for body,stamp,tid,a,b in dest.execute("SELECT body,observed,source,since,until FROM quantity_coverage WHERE store=?",(s["id"],)):
                    c=json.loads(body);c.update(provider=s["provider"],store_id=s["id"],source_id=tid,role=ROLE.get(tid),required=tid in TEMPLATES[s["provider"]],authoritative=True,observed_at=stamp,**{"from":a,"to":b})
                    coverage.append(c)
        except (sqlite3.DatabaseError,ValueError,OSError):
            del rows[row_start:];del coverage[coverage_start:]
            missing(s,"local_unavailable")
        missing(s)
    return {"rows":rows,"coverage":coverage,"stores":[{k:v for k,v in s.items() if k not in ("seller","metadata")} for s in stores],"observed_at":observed or None}

def market_catalog(db,w,source="all_marketplaces",unmapped_only=False,offset=0,limit=30,search="",*,_unpaginated=False):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError("Некорректная страница каталога.")
    if not isinstance(search,str) or len(search)>255:raise ValueError("Некорректная строка поиска.")
    search=search.strip().casefold()
    items=[]
    for s in selected_stores(db,w,source):
        if not market_data.path_for(main_path(db),w,s["provider"]).exists():continue
        mappings=dict(db.execute("SELECT sku,product FROM market_quantity_links WHERE workspace=? AND store=?",(w,s["id"])))
        revisions=dict(db.execute("SELECT sku,revision FROM market_mapping_revisions WHERE store=?",(s["id"],)))
        with local(db,w,s["provider"]) as dest:
            if not dest.execute("SELECT 1 FROM sqlite_master WHERE name='quantity_catalog'").fetchone():continue
            for sku,body in dest.execute("SELECT sku,body FROM quantity_catalog WHERE store=? ORDER BY sku",(s["id"],)):
                if unmapped_only and sku in mappings:continue
                r=json.loads(body)
                if search and search not in str(sku).casefold() and search not in str(r.get("name","")).casefold():continue
                r.update(sku=sku,provider=s["provider"],store_id=s["id"],source=s["id"],connection_id=s["connection_id"],product_id=mappings.get(sku),mapping_revision=revisions.get(sku,0));items.append(r)
    selected=items if _unpaginated else items[offset:offset+limit]
    return {"state":"ready" if items else "partial","rows":selected,"items":selected,"total":len(items),"offset":0 if _unpaginated else offset,"limit":len(items) if _unpaginated else limit,"has_more":False if _unpaginated else offset+limit<len(items)}

def market_mapping(db,w,source,sku,product,request_id=None):
    if not isinstance(sku,str) or not 1<=len(sku)<=255 or not sku.isprintable():raise ValueError("Некорректный артикул.")
    args={"source":source,"sku":sku,"product":product};old=receipt(db,w,request_id,"mapping",args)
    if old:return old
    stores=selected_stores(db,w,source)
    if len(stores)!=1:raise ValueError("Выберите конкретный подтверждённый магазин.")
    s=stores[0]
    if product is not None:
        if not db.execute("SELECT 1 FROM pm_products WHERE id=? AND workspace=?",(product,w)).fetchone():raise HTTPException(404,"Изделие не найдено.")
        with local(db,w,s["provider"]) as dest:
            if not dest.execute("SELECT 1 FROM quantity_catalog WHERE store=? AND sku=?",(s["id"],sku)).fetchone():raise HTTPException(404,"Артикул не найден в собранном каталоге.")
        db.execute("""INSERT INTO market_quantity_links(workspace,store,sku,product) VALUES(?,?,?,?)
          ON CONFLICT(store,sku) DO UPDATE SET product=excluded.product,revision=market_quantity_links.revision+1""",(w,s["id"],sku,product))
    else:db.execute("DELETE FROM market_quantity_links WHERE workspace=? AND store=? AND sku=?",(w,s["id"],sku))
    db.execute("INSERT INTO market_mapping_revisions VALUES(?,?,1) ON CONFLICT(store,sku) DO UPDATE SET revision=revision+1",(s["id"],sku))
    revision=db.execute("SELECT revision FROM market_mapping_revisions WHERE store=? AND sku=?",(s["id"],sku)).fetchone()[0]
    result={"state":"ready","store_id":s["id"],"sku":sku,"product_id":product,"mapping_revision":revision}
    receipt(db,w,request_id,"mapping",args,result);return result

catalog=market_catalog
map_product=market_mapping
