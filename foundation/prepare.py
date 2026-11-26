#!/usr/bin/env python3
"""Create a PRIVATE isolated Podmasterye foundation from the audited Octoport release.
Never run against production; source stays read-only. The public repo carries only new overlay code.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, os

PIN = "0deecb2089b4f56b28e21c7cf8e494fb4a8e3770"
HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--destination",required=True,type=Path)
    a=p.parse_args()
    src=a.source.resolve(); dest=a.destination.resolve()
    if src.name!=PIN or not (src/"release-manifest.json").is_file():
        raise SystemExit("Expected the audited source release "+PIN)
    if dest.exists() or dest==src or src in dest.parents or dest in src.parents:
        raise SystemExit("Destination must be a new separate directory")
    os.umask(0o077)
    dest.mkdir(mode=0o700,parents=True)
    ignored=shutil.ignore_patterns("__pycache__","*.pyc",".git",".local",".env",".env.*","node_modules")
    def ignore(directory,names):
        base=Path(directory)
        result=set(ignored(directory,names))
        result.update(name for name in names if (base/name).is_symlink())
        if base == src/"products/harness-platform/docs":
            result.add("plugins")
        return result
    for relative in ("products/harness-platform","integrations/harness-native-lab/gateway"):
        shutil.copytree(src/relative,dest/relative,ignore=ignore)
    shutil.copy2(src/"release-manifest.json",dest/"upstream-release-manifest.json")
    checks={str(f.relative_to(dest)):hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(dest.rglob("*")) if f.is_file()}
    (dest/"source-before-overlay.json").write_text(json.dumps(checks,indent=2))
    root=dest/"products/harness-platform"
    def edit(rel,old,new):
        f=root/rel; text=f.read_text()
        if text.count(old)!=1: raise RuntimeError("Unexpected source anchor: "+rel+" "+old[:80])
        f.write_text(text.replace(old,new,1))
    # Replace composition entry and route surface, keeping the upstream monetary endpoints.
    f=root/"platform_core/chat_api.py"; s=f.read_text()
    start=s.index("from .account_access import AccountAccess")
    stop=s.index("\n\nclass PrivateResponses",start)
    s=s[:start]+'''from .account_access import AccountAccess
from . import access_web, admin_statistics, provider_keys, chat_defaults, turn_progress
from .admin_costs import AdminCosts
from .browser_session import browser_routes, browser_token
from .chat_worker import ChatWorker, WorkerError
from .identity import AuthenticationError, ChatUnavailable
from .guest_registration import RegistrationStore
from .guest_web import guest_routes
from .web_ui import web_routes
from . import podmasterye_domain, podmasterye_scoped
'''+s[stop:]
    start=s.index("    router_plugin = None",s.index("def create_app("))
    stop=s.index("    async def logout(req):",start)
    s=s[:start]+'''    if composition_module is not None:
        raise ValueError("Product plugins are not supported")
    @asynccontextmanager
    async def lifespan(app):
        with ExitStack() as lifecycle:
            shared_path=database_path
            if str(shared_path)==":memory:":
                directory=lifecycle.enter_context(TemporaryDirectory())
                shared_path=Path(directory)/"platform.sqlite3"
            app.state.identity=lifecycle.enter_context(RegistrationStore(shared_path))
            podmasterye_domain.init(app.state.identity)
            app.state.account_access=AccountAccess(app.state.identity)
            app.state.progress=turn_progress.Progress()
            app.state.admin_costs=AdminCosts()
            if not os.getenv("HARNESS_USAGE_JOURNAL"):
                app.state.admin_costs.journal=Path(shared_path).with_name("usage.jsonl")
            app.state.worker=ChatWorker(shared_path,chat_directory)
            app.state.model_router=None
            async with httpx.AsyncClient(timeout=10,trust_env=False,follow_redirects=False) as http:
                app.state.http=http
                try:
                    yield
                finally:
                    await app.state.progress.close()
                    await app.state.worker.close()

'''+s[stop:]
    start=s.index("    async def scoped(req: Request, action):")
    stop=s.index("    def error_response",start)
    s=s[:start]+s[stop:]
    start=s.index("    return Starlette(lifespan=lifespan")
    s=s[:start]+'''    return Starlette(lifespan=lifespan,middleware=[Middleware(PrivateResponses)],routes=[
        *browser_routes(),*guest_routes(),*web_routes(),
        *[r for r in admin_statistics.routes() if r.path not in ("/admin/statistics/remove","/admin/statistics/remove-batch")],
        *turn_progress.routes(_token),*provider_keys.routes(_token,_body),*chat_defaults.routes(_token,_body),
        Route("/api/wallet",wallet),Route("/api/wallet/balance",wallet),
        Route("/api/admin/accounts/{login}/wallet",wallet),
        Route("/api/admin/coin-pricing",pricing,methods=["GET","POST"]),
        Route("/api/admin/coin-grants",credit,methods=["POST"]),
        *access_web.routes(),Route("/api/logout",logout,methods=["POST"]),
        Route("/api/recover",recover,methods=["POST"]),
        Route("/api/chats",chats,methods=["GET","POST"]),
        *podmasterye_scoped.routes(_token,_body),
    ],exception_handlers={cls:error_response for cls in (
        AuthenticationError,ChatUnavailable,WorkerError,HTTPException,ValueError)})
'''
    f.write_text(s)
    edit("platform_core/guest_registration.py","from .octopus_knowledge import published\nfrom .user_plugins.publication import synchronize\n","")
    edit("platform_core/guest_registration.py","                synchronize(db, published())\n","")
    edit("platform_core/guest_selector.py","from .user_plugins.publication import guest_cards","def guest_cards(db): return ()")
    edit("platform_core/public_faq.py",'return intro + "\\n\\nСейчас список возможностей обновляется. Могу рассказать, как открыть аккаунт и сколько стоит работа в сервисе."',"return intro")
    faq=root/"platform_core/public_faq.json"; cards=json.loads(faq.read_text())
    for v in cards.values(): v.pop("previous_answers",None);v.pop("previous_answer",None)
    new={
      "scope":"Я отвечаю на вопросы о Подмастерье, производстве, учёте, регистрации и стоимости.",
      "intro":"Рассказать, как учитывать материалы и рецептуры?",
      "features":"Подмастерье — учёт малого производства. Доступны материалы, закупки, склад, рецептуры, выпуск, продажи, оплаты, возвраты, расходы, финансы и прогноз закупок. Интеграции ещё разрабатываются.",
      "answer_cost":"Известные команды и расчёты выполняются без ИИ. Стоимость свободного запроса к ИИ зависит от фактических токенов. {signup_offer}",
      "pay":"В сервисе предусмотрена оплата через ЮKassa. Реальные способы доступны после настройки платежей. {checkout_steps}",
      "combined":"Известные команды работают без ИИ. Свободные запросы к ИИ оплачиваются монетами. {checkout_steps} {signup_offer}",
      "history":"Переписка привязана к аккаунту. После регистрации гостевой контекст можно использовать в личном помощнике.",
      "signin":"На странице входа введите логин и пароль, пройдите подтверждение. Откроется личный кабинет.",
      "business_advice":"Могу помочь с материальной себестоимостью и рецептурами. Полный производственный учёт ещё разрабатывается.",
      "shop":"Интеграции магазинов запланированы, но в первой сборке не подключены.",
      "platforms":"Интеграции Ozon, WB и внешних магазинов запланированы; в первой сборке не подключены.",
    }
    for key,value in new.items(): cards[key]["answer"]=value
    faq.write_text(json.dumps(cards,ensure_ascii=False,indent=2)+"\n")
    for rel in ("platform_core/access_mail.py","platform_core/access_web.py","platform_core/checkout.py","native/web/checkout.js","native/web/payment-return.js","platform_core/guest_selector.py","platform_core/guest_billing.py","platform_core/admin_statistics.py"):
        f=root/rel;s=f.read_text()
        # Keep original protocol keys. Change visible names and remove production redirect.
        s=s.replace("https://octoport.ru/payment/return", "https://INVALID-PODMASTER-RETURN/payment/return") if rel.endswith("checkout.js") else s
        s=s.replace("'https://INVALID-PODMASTER-RETURN/payment/return'","location.origin + '/payment/return'")
        s=s.replace("Октопорта","Подмастерья").replace("Октопорте","Подмастерье").replace("Октопорт","Подмастерье").replace("Octoport","Подмастерье").replace("Октопуса","Подмастерья")
        f.write_text(s)
    # Separate cookie names; eliminate old project's analytics.
    edit("platform_core/browser_session.py","__Host-harness_session","__Host-podmaster_session")
    edit("platform_core/browser_session.py","harness_local_session","podmaster_local_session")
    edit("platform_core/browser_session.py","__Host-harness_guest","__Host-podmaster_guest")
    edit("platform_core/browser_session.py","harness_local_guest","podmaster_local_guest")
    edit("platform_core/access_web.py","__Host-octo_verification","__Host-podmaster_verification")
    edit("platform_core/access_web.py","octo_local_verification","podmaster_local_verification")
    f=root/"platform_core/access_web.py";s=f.read_text()
    start=s.index("    # Keep administrator authenticator")
    end=s.index("    html = f",start)
    s=s[:start]+s[end:];f.write_text(s)
    # Native worker: static product MCP only; no marketplace composition.
    f=root/"native/chat-worker.mjs";s=f.read_text()
    s=s.replace("import { mountPlatformMcp } from './platform-mcp.mjs';","import { mountProductionMcp, registerProductionContext } from './podmasterye-mcp.mjs';")
    start=s.index("        if(attached.length || env.HARNESS_PLATFORM_COMPOSITION)")
    end=s.index("        if(req.illustrations",start)
    s=s[:start]+'''        if(req.action==='turn' && metered && req.grant && !req.replayOnly)
          await mountProductionMcp(ctx, await load('dsh-mcp-client'), {
            pythonExecutable:env.HARNESS_TEST_PYTHON, productDirectory,
            databasePath:env.HARNESS_PLATFORM_DATABASE, scope:req.scope,
            requestId:req.requestId,grant:req.grant,
          });
'''+s[end:]
    s=s.replace("registerConnectionContext(ctx,attached,available,req.connectionGuides,metered && !!req.knowledge);","registerProductionContext(ctx);")
    f.write_text(s)
    edit("platform_core/provider_keys.py", "/var/lib/harness-prod/provider-keys", "/var/lib/podmasterye/provider-keys")
    edit("native/web/checkout.js", "'octoport-checkout'", "'podmasterye-checkout'")
    edit("native/web/checkout.js", "if (new URLSearchParams(location.search).get('account') === 'wallet') reconcileOnReturn();",
         "if (document.body.dataset.mode === 'member' && (saved().awaiting || new URLSearchParams(location.search).get('account') === 'wallet')) reconcileOnReturn();")
    edit("platform_core/admin_statistics.py","can_remove=actor!=administrator","can_remove=False")
    f=root/"native/web/admin-statistics.html";s=f.read_text()
    s=s.replace("Октопорт","Подмастерье").replace('<a href="/admin/visits">Посещения</a>','')
    f.write_text(s)
    # Use verified contact for fiscal receipts, not the optional username.
    edit("platform_core/checkout.py","    customer_email = await run_in_threadpool(store.account_login, token)", """    def verified_contact():
        from .identity import _principal
        with store._lock:
            actor,_ = _principal(store._db,token)
            row=store._db.execute("SELECT email FROM access_contacts WHERE actor=? AND verified=1",(actor,)).fetchone()
            if row is None:
                raise HTTPException(400,"Подтвердите электронную почту перед оплатой.")
            return row[0]
    customer_email = await run_in_threadpool(verified_contact)""")
    # No product-specific cost/receipt logic is reimplemented.
    shutil.copytree(HERE/"overlay",root,dirs_exist_ok=True)
    (dest/"PODMASTERYE_SOURCE").write_text(PIN+"\n")
    print("Prepared private candidate:",root)
if __name__=="__main__": main()
