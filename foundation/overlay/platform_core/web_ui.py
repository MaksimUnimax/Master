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
      <script defer src="/assets/podmasterye-accounting.js"></script><script defer src="/assets/podmasterye.js"></script><script defer src="/ui-assets/project/checkout.js"></script></body></html>''',status_code=status,headers=HEADERS)

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
        return document("Вход",f'''<header class="top"><b>Подмастерье</b><span>Учёт мастерской</span></header><main class="landing"><section><h1>Управляйте производством простыми словами</h1><p>Материалы, закупки, склад, выпуск продукции, продажи, расходы и прибыль — в одном кабинете.</p><div id="guest-messages" class="messages"></div><form id="guest-form"><label>Вопрос о сервисе<input name="text" required maxlength="1200" placeholder="Сколько стоит работа?"></label><button>Спросить</button></form></section><section id="public-auth" class="panel"><h2>{'Регистрация' if register else 'Вход'}</h2>{msg}{form}</section></main>''',status=status)
    admin_nav='<button data-page="admin">Администрирование</button>' if admin else ''
    admin_panel='''<section data-panel="admin" hidden><h2>Администрирование</h2><form id="pricing-form"><label>Наценка покупки, %<input name="markupPercent" required></label><button>Сохранить</button></form><form id="credit-form"><label>Логин<input name="login" required></label><label>Монеты<input name="amount" required></label><label>Причина<input name="reason" required></label><button>Начислить</button></form><form id="account-costs"><label>Логин для просмотра расходов<input name="login" required></label><button>Показать</button></form><pre id="account-costs-result"></pre><p><a href="/admin/statistics">Статистика, регистрационный бонус, лимит гостевого фильтра</a></p></section>''' if admin else ''
    return document("Мастерская",f'''<header class="top"><b>Подмастерье</b><span>{escape(login)}</span><span id="balance-label">Баланс —</span><button data-buy-coins>Пополнить</button><form method="post" action="/logout"><button class="secondary">Выйти</button></form></header>
    <div class="layout"><nav><button data-page="summary">Сводка</button><button data-page="products">Изделия и рецептуры</button><button data-page="materials">Материалы</button><button data-page="stock">Склад</button><button data-page="purchases">Закупки</button><button data-page="manufacture">Производство</button><button data-page="sales">Продажи</button><button data-page="expenses">Расходы</button><button data-page="finance">Финансы и отчёты</button><button data-page="planning">План закупок</button><button data-page="journal">Журнал операций</button><button data-page="wallet">Баланс ИИ</button>{admin_nav}</nav>
    <main><div class="toolstrip" id="accounting-filters"><label>С даты<input id="period-from" type="date"></label><label>По дату<input id="period-to" type="date"></label><button id="period-apply" type="button">Показать</button><button id="period-clear" class="secondary" type="button">Весь период</button><label>Поиск в каталоге<input id="catalog-filter" type="search" placeholder="Название или категория"></label></div><p id="accounting-status" class="book-status" role="status"></p><section data-panel="summary"><h1>Моя мастерская</h1><p class="hint">Финансы за выбранный период; запасы и долги — текущие.</p><div id="summary"></div></section>
    <section data-panel="products" hidden><h2>Изделия и рецептуры</h2><button data-book-op="product" type="button">Добавить изделие</button><form id="recipe-form" class="panel"><h3>Добавить материал к изделию</h3><div class="fields"><label>Изделие<input name="product" maxlength="120" required></label><label>Материал<input name="material" maxlength="120" required></label><label>Базовая единица<select name="unit"><option>шт</option><option>г</option><option>мл</option><option>мм</option><option>см²</option><option>компл</option></select></label><label>Единиц в закупочной упаковке<input name="pack_quantity" type="number" min="1" step="1" max="1000000000" required></label><label>Единиц на изделие<input name="usage_quantity" type="number" min="1" step="1" max="1000000000" required></label><label>Цена упаковки, ₽ (необязательно)<input name="pack_price" inputmode="decimal"></label></div><button>Сохранить</button><p id="recipe-status" role="status"></p></form><div id="products"></div></section>
    <section data-panel="materials" hidden><h2>Материалы</h2><button data-book-op="material" type="button">Добавить материал</button><div id="materials"></div></section>
    <section data-panel="stock" hidden><h2>Склад</h2><div id="stock-metrics"></div><div class="toolstrip"><button data-book-op="opening" type="button">Начальный остаток</button><button data-book-op="writeoff" type="button">Списать сырьё</button></div><h3>Сырьё</h3><div id="stock-raw"></div><h3 class="section-subtitle">Готовые изделия</h3><div id="stock-finished"></div><h3 class="section-subtitle">Начальные остатки и списания</h3><div data-event-table="stock"></div></section>
    <section data-panel="purchases" hidden><h2>Закупки</h2><div id="purchase-metrics"></div><button data-book-op="purchase" type="button">Добавить закупку</button><div data-event-table="purchases"></div></section>
    <section data-panel="manufacture" hidden><h2>Производство</h2><button data-book-op="manufacture" type="button">Изготовить партию</button><p class="hint">Фактическая стоимость сырья списывается из запасов. Прямые оплаченные затраты включаются в партию.</p><div data-event-table="manufacture"></div><h3 class="section-subtitle">История и остатки партий FIFO</h3><div id="production-batches"></div></section>
    <section data-panel="sales" hidden><h2>Продажи</h2><div id="sales-metrics"></div><div class="toolstrip"><button data-book-op="sale" type="button">Добавить продажу</button><button data-book-op="payment" type="button">Записать оплату</button><button data-book-op="return" type="button">Возврат</button></div><h3>Текущие продажи и долги (все даты)</h3><label>Фильтр канала<input id="sales-channel-filter" type="search"></label><div id="sales-current"></div><h3 class="section-subtitle">Движения за выбранный период</h3><div data-event-table="sales"></div></section>
    <section data-panel="expenses" hidden><h2>Расходы</h2><div id="expense-metrics"></div><button data-book-op="expense" type="button">Добавить расход</button><div data-event-table="expenses"></div></section>
    <section data-panel="finance" hidden><h2>Финансы и отчёты</h2><p id="finance-period"></p><div id="finance-metrics"></div><p class="hint">Прибыль и денежный поток разделены. Общие расходы не распределяются автоматически на товары или каналы.</p><div class="toolstrip"><a href="/api/accounting/export/xlsx">Выгрузить весь учёт XLSX</a><a href="/api/accounting/export/csv">Журнал CSV</a></div><h3>По месяцам</h3><div id="finance-monthly"></div><h3 class="section-subtitle">Валовая прибыль по товарам</h3><div id="finance-products"></div><h3 class="section-subtitle">По каналам</h3><div id="finance-channels"></div><h3 class="section-subtitle">Расходы по статьям</h3><div id="finance-expenses"></div></section>
    <section data-panel="planning" hidden><h2>План закупок</h2><div class="toolstrip"><label>Горизонт, дней<input type="number" id="plan-horizon" value="30" min="1" max="365"></label><label>Срок поставки, дней<input type="number" id="plan-lead" value="7" min="0" max="365"></label><label>Страховой запас, дней<input type="number" id="plan-safety" value="3" min="0" max="365"></label><button id="plan-apply" type="button">Пересчитать</button></div><p class="hint">Чистые продажи последних 30 дней. Эквивалент по исторической рецептуре не равен списанию сырья.</p><div id="planning"></div><h3 class="section-subtitle">Эквивалент расхода по чистым продажам за выбранный период</h3><div id="consumption-period"></div></section>
    <section data-panel="journal" hidden><h2>Журнал операций</h2><button data-book-op="reverse" type="button">Сторно по ID</button><div data-event-table="all"></div></section>
    <div class="event-pager" id="event-pager"><input id="event-offset" type="hidden" value="0"><button id="events-prev" class="secondary" type="button" disabled>Назад</button><span id="journal-count"></span><button id="events-next" class="secondary" type="button" disabled>Далее</button></div><p class="hint" id="accounting-assumptions"></p>
    <dialog id="book-dialog" class="book-dialog"><header><h2 id="book-title"></h2><button type="button" class="secondary" id="book-close">Закрыть</button></header><form id="book-form"><div id="book-fields" class="fields"></div><div class="toolstrip"><button type="submit" id="book-check">Предварительный расчёт</button><button type="button" id="book-confirm" disabled>Подтвердить запись</button></div></form><p id="book-preview"></p><p id="book-form-status" role="status"></p></dialog>
    <section data-panel="wallet" hidden><h2>Баланс</h2><p id="wallet-info"></p><button data-buy-coins>Купить монеты</button><h3>История списаний</h3><div id="wallet-history"></div></section>{admin_panel}</main>
    <aside><h2>Помощник</h2><p class="hint">Например: Добавь бусины пачками по 400 штук, на браслет уходит 40 штук</p><div id="messages" class="messages" aria-live="polite"></div><form id="assistant-form"><label>Задача<textarea name="text" rows="3" required maxlength="4000"></textarea></label><button disabled>Отправить</button></form><p id="assistant-status" role="status"></p></aside></div>''',member=True,admin=admin,status=status)

async def admin(request):
    if not request.app.state.identity.is_admin(browser_token(request)): raise HTTPException(403,"Administrator required")
    return RedirectResponse("/app/?section=admin",303,headers=_PRIVATE_HEADERS)
async def asset(request):
    name=request.path_params["name"]
    if name not in ("podmasterye.js","podmasterye-accounting.js","podmasterye.css","checkout.js","checkout.css","payment-return.js","theme.js","appearance.css","admin.css","presence.js","admin-statistics.js"): raise HTTPException(404)
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
