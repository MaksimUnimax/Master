"""One durable request coordinator for every Workshop marketplace API stage.

Callers own a short main-database transaction. Waiting never occupies a worker.
The scope is based on the confirmed seller, never on a browser/chat/API key.
"""
from email.utils import parsedate_to_datetime
from hashlib import sha256
import math
import random
from uuid import uuid4


def _number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) and n>=0 else None
    except (ValueError,TypeError,OverflowError):return None

def _date(v):
    try:return parsedate_to_datetime(v).timestamp()
    except (TypeError,ValueError,OverflowError,AttributeError):return None

def retry_due(headers,now,profile,attempt,*,jitter=None):
    h={str(k).lower():str(v).strip() for k,v in headers.items()}
    interval=max(0.001,float(profile.get("min_interval",profile.get("interval",1))))
    base=max(0.001,float(profile.get("backoff_base",8)))
    cap=max(base,float(profile.get("backoff_cap",900)))
    backoff=min(cap,base*2**min(max(int(attempt)-1,0),24))
    bounds=[now+interval,now+backoff]
    server_date=_date(h.get("date"))
    value=h.get("retry-after")
    seconds=_number(value)
    if seconds is not None:bounds.append(now+seconds)
    else:
        deadline=_date(value)
        if deadline is not None:
            bounds.append(deadline)
            if server_date is not None:bounds.append(now+max(0,deadline-server_date))
    for name in profile.get("vendor_headers",[]):
        name=name.lower();v=h.get(name)
        if v is None:continue
        if name=="x-ratelimit-resource-until":
            deadline=_date(v)
            if deadline is not None:
                bounds.append(deadline)
                if server_date is not None:bounds.append(now+max(0,deadline-server_date))
        elif name in ("x-ratelimit-retry","x-ratelimit-reset","x-ratelimit-reset-after"):
            n=_number(v)
            if n is not None:
                # WB documents reset/retry as remaining seconds. Ozon reset may
                # be an epoch; the profile declares that semantic explicitly.
                bounds.append(n if profile.get("reset_is_epoch") and name.endswith("reset") else now+n)
        elif name in ("ratelimit-reset","x-rate-limit-reset"):
            n=_number(v)
            if n is not None:bounds.append(n if n>now else now+n)
    extra=random.uniform(0,min(1,backoff/10)) if jitter is None else max(0,float(jitter))
    return max(bounds)+extra

def scopes(context,request):
    profiles=[request["quota_profile"],*request.get("quota_scopes",[])]
    seen=set();out=[]
    for p in profiles:
        if not isinstance(p,dict):continue
        scope=p.get("scope","seller")
        if scope=="service":identity=str(context.get("service_id") or "unclassified-service")
        elif scope=="business":identity=str(context.get("businessId") or context.get("seller") or "unverified")
        elif scope=="campaign":identity=str(context.get("campaignId") or context.get("seller") or "unverified")
        else:identity=str(context.get("seller") or "unverified")
        raw=[context["provider"],scope,identity,p["key"]]
        key=sha256("\0".join(raw).encode()).hexdigest()
        if key not in seen:out.append((key,p));seen.add(key)
    return out

def acquire(db,job,context,request,now):
    limits=scopes(context,request)
    db.execute("DELETE FROM market_data_permits WHERE expires<=?",(now,))
    wait=now
    for key,p in limits:
        db.execute("INSERT OR IGNORE INTO market_data_quota(scope) VALUES(?)",(key,))
        due,cooldown=db.execute("SELECT due,cooldown FROM market_data_quota WHERE scope=?",(key,)).fetchone()
        wait=max(wait,due,cooldown)
        held=db.execute("SELECT expires FROM market_data_permits WHERE scope=? AND expires>? ORDER BY expires",(key,now)).fetchall()
        cap=max(1,int(p.get("max_concurrency",1)))
        if len(held)>=cap:wait=max(wait,held[0][0])
    if wait>now:return None,wait
    permits=[]
    expiry=now+max(90,float(request.get("timeout",30))+15)
    for key,p in limits:
        pid=uuid4().hex;permits.append(pid)
        interval=max(0.001,float(p.get("min_interval",p.get("interval",1))))
        db.execute("INSERT INTO market_data_permits VALUES(?,?,?,?,?)",(pid,key,job["id"],job["lease"],expiry))
        db.execute("UPDATE market_data_quota SET due=max(due,?),updated=? WHERE scope=?",(now+interval,now,key))
    return permits,now

def release(db,permits):
    for pid in permits or ():db.execute("DELETE FROM market_data_permits WHERE id=?",(pid,))

def confirm_identity_scope(db,old_context,new_context,old_request,new_request,last_success,now):
    """Carry a same-key identity request into its authenticated quota scope.

    The caller must prove the current connection generation. A provisional
    interval can be reclassified, but an observed provider cooldown cannot be
    shortened. Existing confirmed-seller/service limits always remain binding.
    The provisional scope is retained for still-unverified uses of that key.
    """
    old={(p.get("scope","seller"),p["key"]):(key,p) for key,p in scopes(old_context,old_request)}
    deadline=now
    for key,p in scopes(new_context,new_request):
        previous=old.get((p.get("scope","seller"),p["key"]))
        row=db.execute("SELECT cooldown,updated FROM market_data_quota WHERE scope=?",(previous[0],)).fetchone() if previous else None
        last=max(float(last_success or 0),float(row[1]) if row else 0)
        inherited_cooldown=float(row[0]) if row else 0
        db.execute("INSERT OR IGNORE INTO market_data_quota(scope) VALUES(?)",(key,))
        db.execute("UPDATE market_data_quota SET due=max(due,?),cooldown=max(cooldown,?),updated=? WHERE scope=?",
                   (last+float(p["min_interval"]),inherited_cooldown,now,key))
        due,cool=db.execute("SELECT due,cooldown FROM market_data_quota WHERE scope=?",(key,)).fetchone()
        deadline=max(deadline,due,cool)
    return deadline

def cooldown(db,context,request,due,now):
    for key,_ in scopes(context,request):
        db.execute("INSERT OR IGNORE INTO market_data_quota(scope) VALUES(?)",(key,))
        db.execute("UPDATE market_data_quota SET cooldown=max(cooldown,?),updated=? WHERE scope=?",(due,now,key))

def observe_success(db,context,request,headers,now):
    """An exhausted successful response is a quota signal before the next 429."""
    h={str(k).lower():str(v).strip() for k,v in headers.items()}
    if any(h.get(k)=="0" for k in ("x-ratelimit-remaining","x-rate-limit-remaining","x-ratelimit-resource-remaining","ratelimit-remaining")):
        due=retry_due(headers,now,request["quota_profile"],1,jitter=0)
        cooldown(db,context,request,due,now)

def classify(status=None,error=None,*,generate=False,provider=None,download=False,signed_download=False):
    if status==429 or status==420 and provider=="yandex_market":return "rate_limited"
    if download and status in (404,410) or signed_download and status in (401,403):return "refresh_report"
    if status in (401,403):return "denied"
    if error in ("tls","origin"):return "needs_attention"
    if error in ("timeout","connection_reset","temporary_dns") or status in (408,500,502,503,504):
        return "uncertain" if generate else "retry"
    if status in (400,402,404,409,410,413,422):return "needs_attention"
    if status is not None and 200<=status<300:return "success"
    return "needs_attention"
