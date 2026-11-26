"""Product HTTP routes. Local matrix is before the original paid Harness worker."""
import re
from functools import partial
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from . import podmasterye_domain as domain, podmasterye_book as book, podmasterye_workshops as workshops, coins, turn_progress
from .identity import _secret_digest, AuthenticationError, ChatUnavailable
from . import podmasterye_integrations as integrations, podmasterye_import as imports, podmasterye_corrections as corrections, podmasterye_photos as photos
from .chat_worker import WorkerError
from .admin_costs import present_chat
from . import chat_attachments

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
        return JSONResponse(await run_in_threadpool(domain.read_state,req.app.state.identity,token_for(req,allow_cookie=True),req.query_params.get('workshop')))
    async def save(req):
        token=token_for(req,allow_cookie=True)
        fields=await body(req,"requestId","recipe")
        try: result=await run_in_threadpool(domain.save_recipe,req.app.state.identity,token,fields["requestId"],fields["recipe"],req.query_params.get("workshop"))
        except domain.Conflict as e: raise HTTPException(409,str(e)) from None
        return JSONResponse(result)
    async def accounting(req):
        token=token_for(req,allow_cookie=True)
        q=req.query_params
        try:
            opts={k:q[k] for k in ("start","end","event_group","target_profit") if q.get(k)}
            for k in ("horizon","lead","safety","offset","limit"):
                if k in q:opts[k]=int(q[k])
            return JSONResponse(await run_in_threadpool(book.read,req.app.state.identity,token,req.query_params.get('workshop'),**opts))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
    async def prepare(req):
        token=token_for(req,allow_cookie=True)
        fields=await body(req,"operation","arguments")
        try:
            return JSONResponse(await run_in_threadpool(book.preview_for_user,req.app.state.identity,token,fields["operation"],fields["arguments"],req.query_params.get("workshop")))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def commit(req):
        token=token_for(req,allow_cookie=True)
        fields=await body(req,"requestId","operation","arguments","revision")
        try:
            result=await run_in_threadpool(book.mutate,req.app.state.identity,token,fields["requestId"],fields["operation"],fields["arguments"],fields["revision"],req.query_params.get("workshop"))
            return JSONResponse(result)
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def correction_preview(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"correction")
        try:return JSONResponse(await run_in_threadpool(corrections.preview,req.app.state.identity,token,req.query_params.get("workshop"),fields["correction"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def correction_commit(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"requestId","correction","revision")
        try:return JSONResponse(await run_in_threadpool(corrections.commit,req.app.state.identity,token,req.query_params.get("workshop"),fields["requestId"],fields["correction"],fields["revision"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def export(req):
        token=token_for(req,allow_cookie=True);fmt=req.path_params["format"]
        data,media=await run_in_threadpool(book.export,req.app.state.identity,token,fmt,req.query_params.get("workshop"))
        return Response(data,media_type=media,headers={"Content-Disposition":"attachment; filename=podmasterye-accounting."+("zip" if fmt=="csv-zip" else fmt),"Cache-Control":"no-store"})
    async def workshop_list(req):
        return JSONResponse(await run_in_threadpool(workshops.list_for_user,req.app.state.identity,token_for(req,allow_cookie=True)))
    async def workshop_change(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"requestId","action","arguments")
        try:return JSONResponse(await run_in_threadpool(workshops.change,req.app.state.identity,token,fields["requestId"],fields["action"],fields["arguments"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
    async def workshop_chat(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"workshop")
        try:return JSONResponse(await run_in_threadpool(workshops.choose_chat,req.app.state.identity,token,fields["workshop"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
    async def sources(req):
        token=token_for(req,allow_cookie=True)
        return JSONResponse(await run_in_threadpool(integrations.own_overview,req.app.state.identity,token,req.query_params.get("workshop")))
    async def source_change(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"action","arguments")
        try:return JSONResponse(await run_in_threadpool(integrations.change,req.app.state.identity,token,req.query_params.get("workshop"),fields["action"],fields["arguments"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def hook_order(req):
        fields=await body(req,"order_ref","date","shop_name","items")
        try:return JSONResponse(await run_in_threadpool(integrations.receive,req.app.state.identity,req.headers.get("authorization"),fields))
        except PermissionError:raise HTTPException(401,"Недействительный ключ.") from None
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def hook_catalog(req):
        fields=await body(req,"items",limit=256*1024)
        try:return JSONResponse(await run_in_threadpool(integrations.receive_catalog,req.app.state.identity,req.headers.get("authorization"),fields))
        except PermissionError:raise HTTPException(401,"Недействительный ключ.") from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def photo(req):
        token=token_for(req,allow_cookie=True);pid=req.path_params["product"]
        if req.method=="GET":
            try:raw=await run_in_threadpool(photos.get,req.app.state.identity,token,req.query_params.get("workshop"),pid)
            except ValueError as e:raise HTTPException(404,str(e)) from None
            return Response(raw,media_type="image/jpeg",headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})
        fields=await body(req,"content",limit=800*1024)
        try:return JSONResponse(await run_in_threadpool(photos.set_photo,req.app.state.identity,token,req.query_params.get("workshop"),pid,fields["content"]))
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def hook_event(req):
        fields=await body(req,"event_id","order_ref","line","kind","date","quantity","refund","restock")
        try:return JSONResponse(await run_in_threadpool(integrations.event,req.app.state.identity,req.headers.get("authorization"),fields))
        except PermissionError:raise HTTPException(401,"Недействительный ключ.") from None
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def integration_docs(req):
        return JSONResponse({"authorization":"Bearer <ключ источника>","order":{"method":"POST","path":"/api/hook/order","body":{"order_ref":"order-1","date":"2026-11-26","shop_name":"Магазин","items":[{"offer_id":"sku-1","name":"Изделие","qty":1,"price":"100.00"}]}},"return":{"method":"POST","path":"/api/hook/event","fields":["event_id","order_ref","line","kind","date","quantity","refund","restock"]},"catalog":{"method":"POST","path":"/api/hook/catalog","fields":["items[{offer_id,name,price,stock?}]"]},"note":"Ключ создаётся в кабинете, не передавайте его в чат. Повтор идентификатора не создаёт дубликат."})
    async def import_template(req):
        token_for(req,allow_cookie=True)
        return Response(imports.template(),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=materials-template.csv"})
    async def import_preview(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"filename","content",limit=800*1024)
        try:return JSONResponse(await run_in_threadpool(imports.preview_import,req.app.state.identity,token,req.query_params.get("workshop"),fields["filename"],fields["content"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def import_commit(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"requestId","rows","revision",limit=800*1024)
        try:return JSONResponse(await run_in_threadpool(imports.commit_import,req.app.state.identity,token,req.query_params.get("workshop"),fields["requestId"],fields["rows"],fields["revision"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def calculator(req):
        fields=await body(req,"name","items","sale_price","minutes","hourly_rate")
        try:return JSONResponse(await run_in_threadpool(imports.calculator,fields))
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def calculator_save(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"requestId","calculation")
        try:return JSONResponse(await run_in_threadpool(imports.save_calculator,req.app.state.identity,token,req.query_params.get("workshop"),fields["requestId"],fields["calculation"]))
        except domain.Conflict as e:raise HTTPException(409,str(e)) from None
        except ValueError as e:raise HTTPException(400,str(e)) from None
    async def scoped(req,action):
        token=token_for(req,allow_cookie=True); app=req.app.state; identity=app.identity
        if action=="turn":
            fields=await body(req,"requestId","text",optional=("maxCoins","formContext","viewContext","attachments"))
            rid,text=fields["requestId"],fields["text"]
            domain.key_id(rid)
            ids=chat_attachments.validate_ids(fields.get("attachments",[]))
            if not isinstance(text,str) or (not text.strip() and not ids) or len(text.encode())>8192:
                raise HTTPException(400,"Некорректное сообщение.")
            if "maxCoins" in fields: coins.parse_amount(fields["maxCoins"])
        scope=await run_in_threadpool(identity.resolve_chat,token,req.path_params["chat_id"])
        if action=="history":
            result=await run_in_threadpool(domain.history,identity,token,scope,50)
            await app.pm_chat_context.enrich(scope,result)
            return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"history",result))
        async with app.pm_chat_context.lock(scope):
            try: route,cached=await run_in_threadpool(domain.decide,identity,scope,token,rid,text,fields.pop('formContext',None),fields.pop('viewContext',None),ids,await run_in_threadpool(app.pm_chat_context.has_files,scope))
            except domain.Conflict as e: raise HTTPException(409,str(e)) from None
            if cached is not None:
                if route=="local":
                    # Durable local result precedes native publication. Retry with
                    # the same ID resumes publication without another calculation.
                    await app.pm_chat_context.sync_local(scope,token,rid)
                return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"turn",cached))
            def failed(code):
                with identity._write() as db:
                    domain.assert_scope(db,token,scope)
                    db.execute("UPDATE pm_route_decisions SET outcome=?,finished=unixepoch()*1000 WHERE workspace=? AND chat=? AND rid=? AND outcome!='complete'",(code,scope.workspace_id,scope.chat_id,rid))
            if not app.worker.gateway:
                await run_in_threadpool(failed,"gateway_unavailable")
                raise HTTPException(503,"ИИ пока не подключён. Известные команды и ручной учёт работают.")
            fields["session_digest"]=_secret_digest(token)
            if await run_in_threadpool(identity.has_claimed_guest_turns,scope): fields["claimedGuest"]=True
            live,owner=app.progress.begin(scope,rid)
            if owner: fields["on_progress"]=live.set
            async def work():
                try:
                    if ids:await app.media_jobs.automatic(scope,token,ids,rid,fields.get("maxCoins"))
                    await app.pm_chat_context.sync_local(scope,token,rid)
                    result=await app.worker.request(scope,"turn",**fields)
                    result=await run_in_threadpool(domain.complete,identity,scope,token,rid,result)
                    return JSONResponse(await run_in_threadpool(render,identity,app.admin_costs,token,scope,"turn",result))
                except WorkerError as e:
                    await run_in_threadpool(failed,e.code)
                    if e.code=="turn_unconfirmed":
                        result={"error":e.code,"operationId":e.operation_id}
                        return JSONResponse(await run_in_threadpool(present_chat,identity,app.admin_costs,token,scope,"turn",result),status_code=409)
                    raise
                except Exception:
                    await run_in_threadpool(failed,"failed")
                    raise
                finally:
                    if owner: app.progress.finish(scope,rid,live)
            return await work()
    return [
        Route("/api/workshops",workshop_list),
        Route("/api/integrations",sources),
        Route("/api/integration-docs",integration_docs),
        Route("/api/integrations/change",source_change,methods=["POST"]),
        Route("/api/hook/order",hook_order,methods=["POST"]),
        Route("/api/hook/catalog",hook_catalog,methods=["POST"]),
        Route("/api/accounting/photo/{product}",photo,methods=["GET","POST"]),
        Route("/api/hook/event",hook_event,methods=["POST"]),
        Route("/api/materials/template.csv",import_template),
        Route("/api/materials/import/preview",import_preview,methods=["POST"]),
        Route("/api/materials/import/commit",import_commit,methods=["POST"]),
        Route("/api/calculator",calculator,methods=["POST"]),
        Route("/api/calculator/save",calculator_save,methods=["POST"]),
        Route("/api/workshops/change",workshop_change,methods=["POST"]),
        Route("/api/workshops/chat",workshop_chat,methods=["POST"]),
        Route("/api/production",data),
        Route("/api/production/recipe",save,methods=["POST"]),
        Route("/api/accounting",accounting),
        Route("/api/accounting/preview",prepare,methods=["POST"]),
        Route("/api/accounting/commit",commit,methods=["POST"]),
        Route("/api/accounting/correction/preview",correction_preview,methods=["POST"]),
        Route("/api/accounting/correction/commit",correction_commit,methods=["POST"]),
        Route("/api/accounting/export/{format}",export),
        Route("/api/chats/{chat_id}/messages",partial(scoped,action="history")),
        Route("/api/chats/{chat_id}/turns",partial(scoped,action="turn"),methods=["POST"]),
    ]
