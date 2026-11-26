"""Podmasterye product UI. Keep the original auth and checkout HTTP contracts."""
from html import escape
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse,FileResponse,RedirectResponse
from starlette.routing import Route
from .browser_session import browser_token,_PRIVATE_HEADERS
from .identity import AuthenticationError,ChatUnavailable
from .checkout import checkout_routes

UI=Path(__file__).resolve().parents[1]/"native/web"
HEADERS={**_PRIVATE_HEADERS,"Content-Security-Policy":"default-src 'self'; script-src 'self' https://yookassa.ru; style-src 'self' 'unsafe-inline'; frame-src https://yookassa.ru https://*.yookassa.ru https://yoomoney.ru https://*.yoomoney.ru; connect-src 'self' https://yookassa.ru https://*.yookassa.ru https://yoomoney.ru https://*.yoomoney.ru; img-src 'self' data: https://*.yookassa.ru https://*.yoomoney.ru; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}

def document(title,body,*,member=False,admin=False,status=200):
    return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>{escape(title)} · Подмастерье</title><link rel="stylesheet" href="/assets/podmasterye.css"><link rel="stylesheet" href="/ui-assets/project/checkout.css"></head>
      <body data-mode="{'member' if member else 'guest'}" data-admin="{int(admin)}">{body}
      <script defer src="/assets/podmasterye.js"></script><script defer src="/ui-assets/project/checkout.js"></script></body></html>''',status_code=status,headers=HEADERS)

async def page(request,*,panel="",error="",status=200):
    identity=request.app.state.identity
    try:
        token=browser_token(request)
        await run_in_threadpool(identity.validate_session,token)
        login=await run_in_threadpool(identity.account_login,token)
        admin=await run_in_threadpool(identity.is_admin,token)
        if cid:=request.path_params.get("chat_id"):
            await run_in_threadpool(identity.resolve_chat,token,cid)
    except (AuthenticationError,ChatUnavailable):
        if request.query_params.get("account")=="wallet" and request.query_params.get("resume")!="1":
            return await payment_return(request)
        if request.url.path.startswith("/app/"):
            return RedirectResponse("/login",303,headers=_PRIVATE_HEADERS)
        register=panel=="register" or request.url.path=="/register"
        msg=f'<p class="error" role="alert">{escape(error)}</p>' if error else ''
        if register:
            form='''<form method="post" action="/register"><label>Логин<input name="login" autocomplete="username" required></label><label>Почта<input name="email" type="email" autocomplete="email" required></label><label>Пароль<input name="password" type="password" autocomplete="new-password" required></label><button>Создать аккаунт</button></form><a href="/login">Войти</a>'''
        else:
            form='''<form method="post" action="/login"><label>Логин<input name="login" autocomplete="username" required></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><label class="check"><input type="checkbox" name="remember"> Запомнить меня</label><button>Войти</button></form><form method="post" action="/register/start"><button class="secondary">Создать аккаунт</button></form>'''
        return document("Вход",f'''<header class="top"><b>Подмастерье</b><span>Учёт мастерской</span></header><main class="landing"><section><h1>Управляйте производством простыми словами</h1><p>Материалы, закупочные упаковки, изделия и расчёт себестоимости. Первый рабочий срез.</p><div id="guest-messages" class="messages"></div><form id="guest-form"><label>Вопрос о сервисе<input name="text" required maxlength="1200" placeholder="Сколько стоит работа?"></label><button>Спросить</button></form></section><section id="public-auth" class="panel"><h2>{'Регистрация' if register else 'Вход'}</h2>{msg}{form}</section></main>''',status=status)
    admin_nav='<button data-page="admin">Администрирование</button>' if admin else ''
    admin_panel='''<section data-panel="admin" hidden><h2>Администрирование</h2><form id="pricing-form"><label>Наценка покупки, %<input name="markupPercent" required></label><button>Сохранить</button></form><form id="credit-form"><label>Логин<input name="login" required></label><label>Монеты<input name="amount" required></label><label>Причина<input name="reason" required></label><button>Начислить</button></form><form id="account-costs"><label>Логин для просмотра расходов<input name="login" required></label><button>Показать</button></form><pre id="account-costs-result"></pre><p><a href="/admin/statistics">Статистика, регистрационный бонус, лимит гостевого фильтра</a></p></section>''' if admin else ''
    return document("Мастерская",f'''<header class="top"><b>Подмастерье</b><span>{escape(login)}</span><span id="balance-label">Баланс —</span><button data-buy-coins>Пополнить</button><form method="post" action="/logout"><button class="secondary">Выйти</button></form></header>
    <div class="layout"><nav><button data-page="summary">Сводка</button><button data-page="products">Изделия и рецептуры</button><button data-page="materials">Материалы</button><button data-page="wallet">Баланс</button>{admin_nav}</nav>
    <main><section data-panel="summary"><h1>Моя мастерская</h1><p>Первый срез: материальная себестоимость. Складские движения и финансовые отчёты ещё не подключены.</p><div id="summary"></div></section>
    <section data-panel="products" hidden><h2>Изделия и рецептуры</h2><form id="recipe-form" class="panel"><h3>Добавить материал к изделию</h3><div class="fields"><label>Изделие<input name="product" maxlength="120" required></label><label>Материал<input name="material" maxlength="120" required></label><label>Штук в закупочной упаковке<input name="pack_quantity" type="number" min="1" step="1" max="1000000000" required></label><label>Штук на изделие<input name="usage_quantity" type="number" min="1" step="1" max="1000000000" required></label><label>Цена упаковки, ₽ (необязательно)<input name="pack_price" inputmode="decimal"></label></div><button>Сохранить</button><p id="recipe-status" role="status"></p></form><div id="products"></div></section>
    <section data-panel="materials" hidden><h2>Материалы</h2><div id="materials"></div></section>
    <section data-panel="wallet" hidden><h2>Баланс</h2><p id="wallet-info"></p><button data-buy-coins>Купить монеты</button><h3>История списаний</h3><div id="wallet-history"></div></section>{admin_panel}</main>
    <aside><h2>Помощник</h2><p class="hint">Например: Добавь бусины пачками по 400 штук, на браслет уходит 40 штук</p><div id="messages" class="messages" aria-live="polite"></div><form id="assistant-form"><label>Задача<textarea name="text" rows="3" required maxlength="4000"></textarea></label><button>Отправить</button></form><p id="assistant-status" role="status"></p></aside></div>''',member=True,admin=admin,status=status)

async def admin(request):
    if not request.app.state.identity.is_admin(browser_token(request)): raise HTTPException(403,"Administrator required")
    return RedirectResponse("/app/?section=admin",303,headers=_PRIVATE_HEADERS)
async def asset(request):
    name=request.path_params["name"]
    if name not in ("podmasterye.js","podmasterye.css","checkout.js","checkout.css","payment-return.js","theme.js","appearance.css","admin.css","presence.js","admin-statistics.js"): raise HTTPException(404)
    return FileResponse(UI/name,media_type="text/css" if name.endswith(".css") else "text/javascript",headers=_PRIVATE_HEADERS)
async def style(request):
    return FileResponse(UI/"podmasterye.css",media_type="text/css",headers=_PRIVATE_HEADERS)
async def payment_return(request):
    return HTMLResponse('<!doctype html><meta charset="utf-8"><title>Возврат к оплате</title><script defer src="/ui-assets/project/payment-return.js"></script><a href="/?account=wallet&amp;resume=1">Вернуться в кошелёк</a>',headers=HEADERS)
async def payment(request):
    return RedirectResponse("/?account=wallet&resume=1#buy-coins",303,headers=_PRIVATE_HEADERS)
def web_routes():
    return [*checkout_routes(),Route("/",page),Route("/app/",page),Route("/app/chats/{chat_id}",page),Route("/admin",admin),
      Route("/payment",payment),Route("/payment/return",payment_return),Route("/assets/{name}",asset),
      Route("/ui-assets/project/{name}",asset),Route("/about/styles.css",style)]
