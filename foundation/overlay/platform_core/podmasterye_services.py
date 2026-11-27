"""Private usage projection and explicit Telegram delivery."""
import json
from decimal import Decimal
from datetime import datetime,timezone
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException
from . import coins,provider_keys,telegram_api, podmasterye_book as book,podmasterye_workshops as workshops
from .identity import _principal

def empty():return dict(attempts=0,pending=0,input=0,cache=0,output=0,charged=0,usd=Decimal(0),unknown_rub=0)

def aggregate(rows):
    buckets={"all":empty(),"today":empty(),"month":empty()}
    accounts={}
    now=datetime.now(timezone.utc)
    for login,ms,raw,charge,fx in rows:
        stamp=datetime.fromtimestamp(ms/1000,timezone.utc)
        targets=[buckets["all"],accounts.setdefault(login,empty())]
        if stamp.date()==now.date():targets.append(buckets["today"])
        if (stamp.year,stamp.month)==(now.year,now.month):targets.append(buckets["month"])
        u=json.loads(raw) if raw else {}
        for b in targets:
            b["attempts"]+=1;b["pending"]+=charge is None
            b["input"]+=u.get("input_tokens",0)+u.get("cache_creation_input_tokens",0)
            b["cache"]+=u.get("cache_read_input_tokens",0);b["output"]+=u.get("output_tokens",0)
            if charge is not None:
                b["charged"]+=charge
                if fx:b["usd"]+=Decimal(charge*10000//fx)/coins.UNIT
                else:b["unknown_rub"]+=charge
    def present(b):
        return {**{k:v for k,v in b.items() if k not in ("charged","usd","unknown_rub")},
            "coins":coins.display(b["charged"]),"rub":coins.display(b["charged"]-b["unknown_rub"]),"usd":format(b["usd"],"f"),
            "rubIncomplete":bool(b["unknown_rub"] or b["pending"])}
    return {"periods":{k:present(v) for k,v in buckets.items()},"accounts":[{"login":k,**present(v)} for k,v in sorted(accounts.items())],"timezone":"UTC"}

def usage(identity,token):
    with identity._lock:
        actor,_=_principal(identity._db,token)
        if not identity._db.execute("SELECT 1 FROM identity_admins WHERE actor_id=?",(actor,)).fetchone():raise HTTPException(403,"Требуются права администратора.")
        rows=identity._db.execute("""SELECT COALESCE(i.login,'Удалённый аккаунт'),a.started_ms,a.usage_json,a.charge,r.fx_e4
            FROM coin_attempts a JOIN usage_operations u USING(operation_id)
            LEFT JOIN identity_accounts i ON i.actor_id=u.actor_id
            LEFT JOIN coin_ruble_orders r USING(operation_id)
            WHERE a.rate_version!='openrouter-v1'""").fetchall()
        media=identity._db.execute("""SELECT a.model,COUNT(*),SUM(CASE WHEN a.charge IS NULL THEN 1 ELSE 0 END),
            COALESCE(SUM(CASE WHEN a.charge IS NOT NULL THEN json_extract(a.usage_json,'$.quantity') ELSE 0 END),0),
            COALESCE(SUM(a.charge),0)
            FROM coin_attempts a WHERE a.model IN ('deepseek-asr','deepseek-ocr','deepseek-ocr-layout','deepseek-parse','deepseek-parse-layout')
            GROUP BY a.model ORDER BY a.model""").fetchall()
    result=aggregate(rows)
    result["media"]=[{"mode":model.removeprefix("deepseek-"),"attempts":count,"pending":pending,"quantity":qty,"unit":"seconds" if model=="deepseek-asr" else "pages","rub":coins.display(cost)} for model,count,pending,qty,cost in media]
    return result

def routes(token_for,body):
    async def admin(req):
        token=token_for(req,allow_cookie=True);state=req.app.state
        r=await run_in_threadpool(usage,state.identity,token)
        r["configured"]=bool(provider_keys.read("deepseek"))
        r["gateway"]=bool(state.worker.gateway)
        return JSONResponse(r)
    async def telegram(req):
        state=req.app.state;identity=state.identity;token=token_for(req,allow_cookie=True)
        action=None
        if req.method=="POST":
            fields=await body(req,"action");action=fields["action"]
            if action not in ("test","summary","disconnect"):raise HTTPException(400,"Неизвестная операция.")
        with identity._lock:
            _,account=_principal(identity._db,token)
            w=workshops.resolve(identity._db,account,req.query_params.get("workshop"))
            s=state.telegram.status(identity._db,account)
            if action=="summary":
                r=book.report(identity._db,w,view="summary")["summary"]
                name=workshops.metadata(identity._db,w)["name"]
                message="Подмастерье · "+name+"\nСводка за весь период\nВыручка: "+str(r["revenue"])+" ₽\nЧистая прибыль: "+str(r["net_profit"])+" ₽\nЗапасы: "+str(r["inventory_rub"])+" ₽"
            else:message="Подмастерье: проверка интеграции Telegram."
        if action=="disconnect":
            with identity._write() as db:
                _,current=_principal(db,token)
                db.execute("DELETE FROM telegram_integration_consents WHERE workspace=?",(current,))
                db.execute("DELETE FROM telegram_recipients WHERE workspace=?",(current,))
            return JSONResponse({"configured":s["configured"],"linked":False,"hasBinding":False})
        if action:
            if not s["linked"]:raise HTTPException(409,"Telegram не привязан к этому аккаунту.")
            try:await state.telegram.send(account,message)
            except telegram_api.DeliveryError:raise HTTPException(502,"Не удалось доставить сообщение Telegram.") from None
            return JSONResponse({**s,"sent":True})
        return JSONResponse(s)
    return [Route("/api/admin/podmasterye/usage",admin),Route("/api/integrations/telegram",telegram,methods=["GET","POST"])]
