"""Product HTTP routes. Local matrix is before the original paid Harness worker."""
import re
from functools import partial
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route
from . import podmasterye_domain as domain, coins, turn_progress
from .identity import _secret_digest, AuthenticationError, ChatUnavailable
from .chat_worker import WorkerError
from .admin_costs import present_chat

def render(identity,costs,token,scope,action,result):
    result=present_chat(identity,costs,token,scope,action,result)
    messages=result if action=="history" else [result]
    if identity.can_view_costs(token,scope):
        for m in messages:
            if m.get("role")=="assistant" and m.get("route")=="local":
                m["modelCost"]={"rub":"0","usd":"0"}
                m["modelUsage"]={"tokens":{"input":0,"cache":0,"output":0},"coins":"0","pending":False}
    return result

def routes(token_for,body):
    async def data(req):
        return JSONResponse(await run_in_threadpool(domain.read_state,req.app.state.identity,token_for(req,allow_cookie=True)))
    async def save(req):
        token=token_for(req,allow_cookie=True)
        fields=await body(req,"requestId","recipe")
        try: result=await run_in_threadpool(domain.save_recipe,req.app.state.identity,token,fields["requestId"],fields["recipe"])
        except domain.Conflict as e: raise HTTPException(409,str(e)) from None
        return JSONResponse(result)
    async def scoped(req,action):
        token=token_for(req,allow_cookie=True); app=req.app.state; identity=app.identity
        if action=="turn":
            fields=await body(req,"requestId","text",optional=("maxCoins",))
            rid,text=fields["requestId"],fields["text"]
            domain.key_id(rid)
            if not isinstance(text,str) or not text.strip() or len(text.encode())>8192:
                raise HTTPException(400,"Некорректное сообщение.")
            if "maxCoins" in fields: coins.parse_amount(fields["maxCoins"])
        scope=await run_in_threadpool(identity.resolve_chat,token,req.path_params["chat_id"])
        if action=="history":
            result=await run_in_threadpool(domain.history,identity,token,scope,50)
            return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"history",result))
        try: route,cached=await run_in_threadpool(domain.decide,identity,scope,token,rid,text)
        except domain.Conflict as e: raise HTTPException(409,str(e)) from None
        if cached is not None:
            return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"turn",cached))
        if not app.worker.gateway:
            raise HTTPException(503,"ИИ пока не подключён. Известные команды и ручной учёт работают.")
        fields["session_digest"]=_secret_digest(token)
        if await run_in_threadpool(identity.has_claimed_guest_turns,scope): fields["claimedGuest"]=True
        live,owner=app.progress.begin(scope,rid)
        if owner: fields["on_progress"]=live.set
        async def work():
            try:
                result=await app.worker.request(scope,"turn",**fields)
                result=await run_in_threadpool(domain.complete,identity,scope,token,rid,result)
                return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"turn",result))
            except WorkerError as e:
                if e.code=="turn_unconfirmed":
                    result={"error":e.code,"operationId":e.operation_id}
                    return JSONResponse(await run_in_threadpool(present_chat,identity,app.admin_costs,token,scope,"turn",result),status_code=409)
                raise
            finally:
                if owner: app.progress.finish(scope,rid,live)
        return await work()
    return [
        Route("/api/production",data),
        Route("/api/production/recipe",save,methods=["POST"]),
        Route("/api/chats/{chat_id}/messages",partial(scoped,action="history")),
        Route("/api/chats/{chat_id}/turns",partial(scoped,action="turn"),methods=["POST"]),
    ]
