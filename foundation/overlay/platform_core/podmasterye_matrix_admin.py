"""Administrator-only matrix tuning and route economics. Code handlers remain immutable."""
import json,re,math
from collections import Counter
from time import time
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route
from .identity import _principal
from . import coins, podmasterye_router as router, podmasterye_matrix as matrix, podmasterye_domain as domain

def require(db,token):
    actor,_=_principal(db,token)
    if not db.execute("SELECT 1 FROM identity_admins WHERE actor_id=?",(actor,)).fetchone():raise HTTPException(403,"Требуются права администратора.")
    return actor

def rows(db):
    edits=router.edit_rows(db)
    return [{"id":r["id"],"intent":r["intent"],"baseAliases":r["aliases"],"op":r.get("op"),"view":r.get("view"),"page":r.get("page"),"answer":r.get("answer"),
             **edits.get(r["id"],{"revision":0,"aliases":[],"negatives":[]})} for r in matrix.ITEMS]

def phrases(v):
    if not isinstance(v,list) or len(v)>30:raise ValueError("До 30 фраз на запись.")
    out=[]
    for a in v:
        if not isinstance(a,str) or not 2<=len(a.strip())<=160 or any(ord(c)<32 for c in a):raise ValueError("Некорректная фраза.")
        n=router.clean(a)
        if not n or n in out:raise ValueError("Пустая или повторяющаяся фраза.")
        out.append(n)
    return out

def validate(db,id,aliases,negatives):
    if id not in router.ROWS:raise HTTPException(404,"Запись матрицы не найдена.")
    aa,nn=phrases(aliases),phrases(negatives)
    base=router.ROWS[id]
    occupied={router.clean(a):r["id"] for r in matrix.ITEMS for a in r["aliases"]}
    for k,e in router.edit_rows(db).items():
        if k!=id:
            for a in e["aliases"]:occupied[router.clean(a)]=k
    for a in aa:
        if a in occupied:raise HTTPException(409,"Фраза уже используется в "+occupied[a]+".")
        if base["intent"]=="form" and (router.NEG.search(a) or not router.WRITE.search(a)):
            raise ValueError("Для формы нужна явная команда без отрицания или вопроса.")
    for a in [*base["aliases"],*aa]:
        if router.blocked(router.clean(a),nn):raise ValueError("Исключение блокирует положительный пример: "+a)
    return aa,nn

def edit(identity,token,id,revision,aliases,negatives):
    with identity._write() as db:
        actor=require(db,token)
        old=router.edit_rows(db).get(id,{"revision":0,"aliases":[],"negatives":[]})
        if type(revision) is not int or revision!=old["revision"]:raise HTTPException(409,"Матрица изменилась. Обновите запись.")
        a,n=validate(db,id,aliases,negatives)
        v=revision+1;now=int(time()*1000)
        params=(id,v,domain.encode(a),domain.encode(n),now,actor)
        db.execute("INSERT INTO pm_matrix_edits VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,aliases=excluded.aliases,negatives=excluded.negatives,updated=excluded.updated,actor=excluded.actor",params)
        db.execute("INSERT INTO pm_matrix_edit_history(id,revision,aliases,negatives,updated,actor) VALUES(?,?,?,?,?,?)",params)
        return {"id":id,"revision":v,"aliases":a,"negatives":n}

def percentile(xs,p):
    if not xs:return None
    a=sorted(xs);return a[max(0,math.ceil(p*len(a))-1)]

def stats(db):
    data=db.execute("""SELECT d.workspace,d.chat,d.rid,d.kind,d.reason,d.ids,d.plan,d.started,d.finished,d.outcome
                       FROM pm_route_decisions d ORDER BY d.started""").fetchall()
    attempts={}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='usage_operations'").fetchone():
        for w,c,r,raw,charge,fx in db.execute("""SELECT u.workspace_id,u.chat_id,u.run_key,a.usage_json,a.charge,r.fx_e4
             FROM usage_operations u JOIN coin_attempts a USING(operation_id) LEFT JOIN coin_ruble_orders r USING(operation_id)
             WHERE u.source='chat.turn' AND a.rate_version!='openrouter-v1'"""):
            attempts.setdefault((w,c,r),[]).append((raw,charge,fx))
    reasons=Counter();hits=Counter();prefixes=Counter();outcomes=Counter();lat=[];costs=[];calls=0;inputs=cache=output=0;pending=0;local=0;model=0;zero=0;paid_turns=0
    for w,c,r,kind,reason,ids,plan,start,finish,outcome in data:
        reasons[reason]+=1;outcomes[outcome]+=1
        if kind=="local":local+=1;hits.update(json.loads(ids))
        else:model+=1
        p=json.loads(plan);prefix=p.get("prefixId")
        if prefix:prefixes[prefix]+=1
        if finish is not None and outcome=="complete":lat.append(max(0,finish-start))
        aa=attempts.get((w,c,r),[]);calls+=len(aa)
        if not aa and kind=="local":zero+=1
        if aa:paid_turns+=1
        total=0;confirmed=True
        for raw,charge,fx in aa:
            u=json.loads(raw) if raw else {}
            inputs+=u.get("input_tokens",0)+u.get("cache_creation_input_tokens",0)
            cache+=u.get("cache_read_input_tokens",0);output+=u.get("output_tokens",0)
            if charge is None or not fx:confirmed=False
            if charge is not None and fx:total+=charge
            if charge is None:pending+=1
        if kind=="local" or (aa and confirmed and outcome=="complete"):costs.append(total)
    n=len(data)
    return {"version":router.VERSION,"turns":n,"local":local,"model":model,"zeroLlm":zero,
            "zeroLlmPercent":round(zero*100/n,2) if n else None,"paidTurns":paid_turns,"calls":calls,"input":inputs,"cache":cache,"output":output,"pending":pending,
            "reasons":dict(reasons),"hits":dict(hits),"outcomes":dict(outcomes),"prefixFamilies":len(prefixes),
            "latencyMs":{"p50":percentile(lat,.5),"p95":percentile(lat,.95)},
            "costRub":{"p50":coins.display(percentile(costs,.5)) if costs else None,"p95":coins.display(percentile(costs,.95)) if costs else None},
            "legacyTurns":db.execute("SELECT count(*) FROM pm_turns").fetchone()[0]-n}

def catalog_snapshot(identity,token):
    with identity._lock:
        require(identity._db,token)
        return {"version":router.VERSION,"rows":rows(identity._db)}

def stats_snapshot(identity,token):
    with identity._lock:
        require(identity._db,token)
        return stats(identity._db)

def routes(token_for,body):
    async def catalog(req):
        identity=req.app.state.identity;t=token_for(req,allow_cookie=True)
        from starlette.concurrency import run_in_threadpool
        return JSONResponse(await run_in_threadpool(catalog_snapshot,identity,t))
    async def update(req):
        identity=req.app.state.identity;t=token_for(req,allow_cookie=True)
        a=await body(req,"revision","aliases","negatives")
        return JSONResponse(edit(identity,t,req.path_params["id"],a["revision"],a["aliases"],a["negatives"]))
    async def statistics(req):
        identity=req.app.state.identity;t=token_for(req,allow_cookie=True)
        from starlette.concurrency import run_in_threadpool
        return JSONResponse(await run_in_threadpool(stats_snapshot,identity,t))
    return [Route("/api/admin/matrix",catalog),Route("/api/admin/matrix/stats",statistics),Route("/api/admin/matrix/{id}",update,methods=["POST"])]
