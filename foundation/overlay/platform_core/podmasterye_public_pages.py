"""Server-rendered public product pages. No access to private workshop data."""
import os
from html import escape
from urllib.parse import urlsplit
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from .browser_session import browser_token, _PRIVATE_HEADERS
from .identity import AuthenticationError
from . import checkout, coins
from .guest_selector import GUEST_MESSAGE_LIMIT
from .podmasterye_public_catalog import catalog

# Published seller details copied from Octoport public-info/seller-footer.html
# and public-info/support.html. No payment credentials or account data.
SELLER = "ИП Ягофаров Максим Ринатович"
INN = "741705866660"
OGRNIP = "320745600093211"
CONTACT = "OpenScripts@yandex.com"
SUPPORT = "support@octoport.ru"

PAGES = {
    "about": ("/about/", "Описание", "Программа для расчёта себестоимости продукции и учёта производства",
              "Подмастерье — онлайн-сервис для расчёта себестоимости изделий, учёта материалов, закупок, склада, производства, продаж и прибыли небольших мастерских."),
    "calculator": ("/kalkulyator", "Калькулятор", "Калькулятор себестоимости изделия онлайн бесплатно",
              "Рассчитайте себестоимость продукции: материалы, цена упаковки, расход, труд, прибыль, маржа и наценка. Бесплатно, без регистрации и ИИ."),
    "profit": ("/kalkulyator-pribyli/", "Калькулятор прибыли", "Калькулятор прибыли онлайн",
              "Бесплатный калькулятор прибыли с продажи изделия и партии: цена, себестоимость, комиссия, доставка, расходы, маржа и точка безубыточности."),
    "support": ("/support", "Поддержка", "Поддержка Подмастерья",
                "Помощь с регистрацией, учётом мастерской, файлами и работой помощника. Как сообщить об ошибке."),
    "contacts": ("/contacts", "Контакты", "Контакты и реквизиты Подмастерья",
                 "Контактные адреса поддержки и опубликованные реквизиты исполнителя сервиса Подмастерье."),
    "payment": ("/payment", "Оплата", "Стоимость Подмастерья и оплата работы ИИ",
                 "Стоимость монет, бесплатные расчёты и порядок пополнения баланса ИИ в Подмастерье."),
    "faq": ("/faq", "Частые вопросы", "Частые вопросы о Подмастерье",
            "Ответы на вопросы о себестоимости, учёте мастерской, интеграциях, файлах и регистрации."),
    "privacy": ("/privacy", "Данные и cookie", "Данные и cookie",
                "Информация о хранении учётных данных, истории чата, файлах, cookie и работе ИИ в Подмастерье."),
    "login": ("/login", "Вход", "Вход в Подмастерье", "Войдите в личный кабинет мастерской."),
    "register": ("/register", "Регистрация", "Регистрация в Подмастерье", "Создайте аккаунт мастерской."),
}
INDEXABLE = ("about", "calculator", "profit", "support", "contacts", "payment", "faq", "privacy")

def origin():
    raw = os.getenv("PODMASTERYE_PUBLIC_ORIGIN", "").rstrip("/")
    try:
        u = urlsplit(raw)
        if (u.scheme == "https" and u.hostname and u.netloc == u.hostname and
                not (u.path or u.query or u.fragment or u.username or u.password)):
            return raw
    except ValueError:
        pass
    return ""

def indexing():
    return bool(origin() and os.getenv("PODMASTERYE_INDEX_PUBLIC") == "1")

def metadata(key):
    path, label, title, desc = PAGES[key]
    canonical = origin() + path
    robots = "index, follow" if indexing() and key in INDEXABLE else "noindex, follow"
    return title, robots, (
        '<meta name="description" content="' + escape(desc, quote=True) + '">'
        '<meta name="robots" content="' + robots + '">'
        '<link rel="canonical" href="' + escape(canonical, quote=True) + '">'
        '<meta property="og:type" content="website">'
        '<meta property="og:title" content="' + escape(title + " · Подмастерье", quote=True) + '">'
        '<meta property="og:description" content="' + escape(desc, quote=True) + '">'
        '<meta property="og:url" content="' + escape(canonical, quote=True) + '">'
    )

def link(key, text=None, cls=""):
    path, label, _, _ = PAGES[key]
    return f'<a class="{escape(cls, quote=True)}" href="{path}" data-public-panel="{key}">{escape(text or label)}</a>'

def mail(address):
    return f'<a href="mailto:{escape(address, quote=True)}">{escape(address)}</a>'

def seller():
    return f"""<section class="pm-public-section pm-seller"><h2>Реквизиты исполнителя</h2>
    <p>{escape(SELLER)}</p><dl><dt>ИНН</dt><dd>{INN}</dd><dt>ОГРНИП</dt><dd>{OGRNIP}</dd></dl>
    <p>{mail(CONTACT)}</p></section>"""

def footer():
    return '<footer class="pm-public-footer">'+seller()+'<div class="pm-public-links">'+link("privacy")+" "+link("support")+'</div><p class="hint">Подмастерье · 2026</p></footer>'

def about():
    groups = []
    for group in ("Возможности", "Интеграции"):
        items = "".join('<article class="pm-public-feature"><h3>'+escape(r["title"])+'</h3><p>'+escape(r["detail"])+'</p></article>' for r in catalog() if r["group"] == group)
        groups.append('<section class="pm-public-section"><h2>'+group+'</h2>'+items+'</section>')
    return """<header class="pm-public-hero"><p class="pm-public-kicker">Учёт малого производства</p>
      <h1>Подмастерье — программа учёта производства и себестоимости</h1>
      <p class="pm-public-lead">Подмастерье — онлайн-программа для расчёта себестоимости продукции и управленческого учёта малого производства. Материалы, рецептуры, склад, закупки, выпуск, продажи и прибыль — в одной мастерской. Работайте через формы или поручайте задачи помощнику.</p>
      <div class="pm-public-actions">"""+link("register","Создать мастерскую","pm-public-primary")+"""<a href="/kalkulyator" data-public-panel="calculator" class="pm-public-secondary">Калькулятор себестоимости</a></div></header>
      <section class="pm-public-section"><h2>Для кого предназначен сервис</h2><p>Для мастеров, небольших производств, ремесленных мастерских, производителей украшений, сувениров, изделий ручной работы и других товаров. Ведите управленческий учёт своей мастерской: от закупки сырья до расчёта прибыли с продажи.</p></section>
      <section class="pm-public-section"><h2>Как начать работу</h2><ol><li>Создайте аккаунт и внесите материалы, упаковки и закупочные цены.</li><li>Добавьте изделия и рецептуры: сколько материалов уходит на единицу продукции.</li><li>Учитывайте закупки, выпуск, продажи и расходы. Сверяйте остатки и финансовые результаты.</li></ol></section>"""+ "".join(groups)+"""
      <section class="pm-public-section"><h2>Помощник и документы</h2><p>В личном кабинете помощник получает отчёты из учётного ядра, готовит записи и сохраняет их после подтверждения пользователя. Он может создавать XLSX, DOCX, PPTX, PDF, CSV, TXT, JSON и ZIP, а также новые версии созданных им файлов.</p>
      <p>Гостевой помощник отвечает на вопросы о сервисе и управляет бесплатными калькуляторами по точным шаблонам. Доступ к учёту мастерской, файлам и голосовому вводу появляется после регистрации. Интернет-поиск пока не подключён.</p></section>
      <section class="pm-public-section" id="handmade"><h2>Расчёт себестоимости изделий и учёт ручной работы</h2><p>Программа помогает рассчитать затраты на материалы по нормам расхода, учитывать закупочные упаковки, выпуск продукции, продажи и фактические расходы. Подходит мастерам украшений, швейных изделий, свечей и домашним кондитерам. Сравнивайте себестоимость изделия с ценой продажи и оценивайте прибыль; управленческий учёт не заменяет обязательную бухгалтерскую отчётность.</p>
      <p>Начните с бесплатного <a href="/kalkulyator" data-public-panel="calculator">калькулятора себестоимости</a> или <a href="/kalkulyator-pribyli/" data-public-panel="profit">калькулятора прибыли</a>. Зарегистрируйтесь, чтобы сохранить рецептуры и вести постоянный учёт материалов, себестоимости и продаж.</p></section>
      <section class="pm-public-section"><h2>Стоимость работы</h2><p>Ручной учёт и локальные программные расчёты не расходуют монеты. Запросы к ИИ и платная обработка файлов оплачиваются по фактическому расходу.</p>"""+link("payment","Подробнее об оплате")+"</section>"

async def payment_content(request, signed_in):
    store=request.app.state.identity
    rate=await run_in_threadpool(store.public_coin_price)
    bonus=await run_in_threadpool(store.public_signup_coins)
    enabled=bool(await run_in_threadpool(checkout.merchant)) and os.getenv("YOOKASSA_PILOT_ONLY")!="1"
    total=coins.purchase_total(rate,100).replace(".",",")
    state="1" if enabled else "0"
    note=("Войдите в аккаунт перед оплатой, чтобы монеты поступили на ваш баланс." if not signed_in
          else "После подтверждения платежа монеты будут зачислены на баланс.") if enabled else "Приём платежей сейчас отключён. Оплата не производится."
    methods=("СБП","Банковские карты","ЮMoney","SberPay","T-Pay")
    methods_html="".join('<span class="pm-payment-method">'+escape(method)+'</span>' for method in methods)
    return f"""<header class="pm-public-hero"><h1>Оплата работы Подмастерья</h1><p class="pm-public-lead">Пополните баланс для работы с ИИ и платной обработки файлов.</p></header>
      <section class="pm-public-section pm-payment-card"><h2>Пополнить баланс</h2>
      <form id="public-payment-form" data-enabled="{state}" data-member="{int(signed_in)}">
        <label for="public-payment-count">Количество монет</label><input id="public-payment-count" name="coins" type="number" inputmode="numeric" min="1" max="8000000" step="1" value="100" required>
        <div class="pm-payment-total"><span>К оплате</span><output id="public-payment-total" for="public-payment-count" aria-live="polite">{escape(total)} ₽</output></div>
        <button type="submit" id="public-payment-submit" disabled>Перейти к оплате</button>
        <p id="public-payment-status" role="status">{escape(note)}</p>
      </form>
      <div class="pm-payment-methods"><h3>Способы оплаты через ЮKassa</h3><div>{methods_html}</div><p class="hint">Доступность конкретного способа определяется ЮKassa при оплате.</p></div>
      <p>Стартовый бонус при первой регистрации: {escape(bonus.replace(".",","))} монет.</p></section>
      <section class="pm-public-section"><h2>Что не расходует монеты</h2><p>Ручное ведение учёта, локальные команды и программные расчёты.</p></section>
      <section class="pm-public-section"><h2>Вопросы об оплате</h2><p>Если возникла проблема с пополнением, обратитесь в поддержку. Не передавайте реквизиты карты, пароли и коды подтверждения.</p>{link("support","Обратиться в поддержку")}</section>"""

def support():
    return """<header class="pm-public-hero"><h1>Поддержка Подмастерья</h1><p class="pm-public-lead">Вопросы о входе, работе с мастерской, отчётах, файлах и помощнике.</p></header>
    <section class="pm-public-section"><h2>Написать в поддержку</h2><p>Контакт поддержки: """+mail(SUPPORT)+""".</p><p>Укажите раздел сервиса, время и часовой пояс, браузер, что вы делали и какой результат получили. Если есть текст ошибки, приложите его.</p><p>Перед отправкой удалите со скриншотов ключи API, пароли, коды подтверждения и конфиденциальные сведения.</p></section>
    <section class="pm-public-section"><h2>С чего начать</h2><p>Спросите гостевого помощника о возможностях и условиях работы или откройте """+link("faq","частые вопросы")+". Для доступа к своей мастерской "+link("login","войдите в аккаунт")+".</p></section>"

def contacts():
    return '<header class="pm-public-hero"><h1>Контакты и реквизиты</h1><p class="pm-public-lead">Контакты исполнителя сервиса «Подмастерье».</p></header><section class="pm-public-section"><h2>Электронная почта</h2><p>По общим вопросам: '+mail(CONTACT)+'.</p><p>Поддержка: '+mail(SUPPORT)+'.</p></section>'

def faq(store):
    from .podmasterye_matrix import ITEMS
    from .podmasterye_workshops import multiple_enabled
    from .guest_billing import fill_terms
    entries = []
    with store._lock:
        for item in ITEMS:
            if item.get("intent") != "faq" or not item.get("answer") or not item.get("aliases"):
                continue
            label=item["aliases"][0]
            answer=item["answer"]
            if label=="как работают мастерские" and not multiple_enabled():
                answer="В аккаунте сейчас доступна одна мастерская. В ней ведутся справочники, склад, производство, продажи и учёт операций."
            answer=fill_terms(store._db,answer)
            entries.append('<details class="pm-public-feature"><summary>'+escape(label.capitalize())+'</summary><p>'+escape(answer)+'</p></details>')
    return '<header class="pm-public-hero"><h1>Частые вопросы</h1></header>'+''.join(entries)

def privacy():
    return """<header class="pm-public-hero"><h1>Данные и cookie</h1><p class="pm-public-lead">Информация о текущем режиме работы сервиса.</p></header>
      <section class="pm-public-section"><h2>Аккаунт и переписка</h2><p>Необходимые cookie поддерживают вход, подтверждение регистрации и гостевую сессию. История диалогов и данные мастерской хранятся на сервере, настройки оформления — в браузере.</p></section>
      <section class="pm-public-section"><h2>Данные для помощника</h2><p>Для обработки задач модель может получать текст запроса, необходимые результаты учётных операций и выбранные вложения. Калькулятор и локальные расчёты выполняются без ИИ. Ключи интеграций вводите только в предназначенные для них поля личного кабинета, не в чат.</p></section>
      <section class="pm-public-section"><h2>Текущий статус</h2><p>Это информационное описание тестового режима, а не окончательная политика обработки персональных данных публичного сервиса. Необязательная аналитика посещений не подключена.</p><p>Вопросы об обработке данных: """+mail(CONTACT)+".</p></section>"

async def signed_in(request):
    try:
        token = browser_token(request)
        await run_in_threadpool(request.app.state.identity.validate_session, token)
        return True
    except AuthenticationError:
        return False

def auth_content(key, form, error=""):
    title = "Регистрация" if key=="register" else "Вход"
    msg = '<p class="error" role="alert">'+escape(error)+'</p>' if error else ""
    return f'<section class="pm-public-auth"><h1>{title}</h1><p class="pm-public-lead">{"Создайте аккаунт и начните вести учёт мастерской." if key=="register" else "Откройте свой личный кабинет."}</p>{msg}<div class="pm-auth-card" id="public-auth">{form}</div><p class="hint">{link("privacy","О данных и cookie")}</p></section>'

def panel_response(request,key,content,*,status=200,is_member=False):
    if request.method=="GET" and request.headers.get("X-PM-Panel")=="1":
        path,label,title,desc=PAGES[key]
        robots="index, follow" if indexing() and key in INDEXABLE else "noindex, follow"
        return JSONResponse({"key":key,"label":label,"title":title+" · Подмастерье",
            "description":desc,"robots":robots,"canonical":origin()+path,
            "member":is_member,"html":content+footer()},status_code=status,
            headers={**_PRIVATE_HEADERS,"X-Robots-Tag":robots,"Vary":"X-PM-Panel"})
    return shell(key,content,status=status,is_member=is_member)

def shell(key, content, *, status=200, is_member=False):
    from .web_ui import asset_version, HEADERS
    title, robots, meta = metadata(key)
    nav = []
    for k in ("about","payment","support","contacts","faq","privacy"):
        nav.append(f'<a href="{PAGES[k][0]}" data-public-panel="{k}"'+(' aria-current="page"' if k==key else '')+'>'+PAGES[k][1]+'</a>')
    if is_member:
        account = '<a href="/app/">Моя мастерская</a>'
        assistant = '<aside class="pm-public-assistant" aria-label="Помощник"><div class="assistant-header"><h2>Помощник</h2></div><div class="assistant-intro"><h2>Ваша мастерская</h2><p>Вы вошли в аккаунт. Продолжайте диалог в личном кабинете.</p><a class="pm-public-primary" href="/app/">Открыть мастерскую</a></div></aside>'
    else:
        account = link("login","Вход")+link("register","Регистрация")
        assistant = f"""<aside class="pm-public-assistant" aria-label="Помощник" id="public-chat-pane">
        <div class="assistant-header"><h2>Помощник</h2><button type="button" id="public-open-info" class="secondary">Описание</button></div>
        <div class="assistant-intro" id="guest-intro"><h2>С чего начнём?</h2><p>Расскажу о сервисе и помогу заполнить бесплатный калькулятор. Например, напишите «Открой калькулятор себестоимости».</p></div>
        <div class="messages" id="guest-messages" aria-live="polite"></div>
        <p id="guest-quota" class="hint" role="status">Доступно до {GUEST_MESSAGE_LIMIT} бесплатных сообщений.</p>
        <form id="guest-form" class="composer" aria-label="Гостевой чат">
          <label class="sr-only" for="guest-input">Вопрос о сервисе</label><textarea id="guest-input" name="text" rows="1" maxlength="1200" placeholder="Спросите о Подмастерье…" disabled required></textarea>
          <div class="composer-footer"><span class="pm-public-guest-label">Гостевой режим</span><span class="spacer"></span><button type="submit" disabled aria-label="Отправить" title="Отправить"><svg viewBox="0 0 24 24"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button></div>
        </form><p id="guest-status" role="status"></p><p id="guest-limit" hidden>Бесплатные сообщения закончились. {link("register","Создать аккаунт")} или {link("login","войти")}.</p></aside>"""
    helper_nav = '' if is_member else '<a href="/about/" data-public-chat aria-controls="public-chat-pane">Помощник</a>'
    css = asset_version("podmasterye.css")
    public_css = asset_version("podmasterye-public.css")
    script = asset_version("podmasterye-public.js")
    theme = asset_version("podmasterye-theme.js")
    calc_script=asset_version("podmasterye-public-calculator.js")
    return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · Подмастерье</title>{meta}
      <script src="/assets/podmasterye-theme.js?v={theme}"></script><link rel="stylesheet" href="/assets/podmasterye.css?v={css}"><link rel="stylesheet" href="/assets/podmasterye-public.css?v={public_css}"></head>
      <body data-mode="public" data-public-key="{key}" data-public-surface="{'info' if is_member else 'split'}">
      <header class="top"><button type="button" class="icon-btn" id="public-menu-toggle" aria-label="Развернуть меню" title="Развернуть меню" aria-controls="public-menu" aria-expanded="false"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg></button><a class="pm-brand" href="/" aria-label="Подмастерье"><span class="brand-mark" aria-hidden="true">П</span><b>Подмастерье</b></a><span class="spacer"></span>{link("calculator","Калькулятор")}<button type="button" class="icon-btn" data-pm-theme aria-label="Сменить тему">◐</button></header>
      <div class="layout pm-public-layout"><nav id="public-menu" aria-label="Разделы Подмастерья"><div class="pm-nav-header"><strong>Меню</strong></div>{helper_nav}<div class="nav-group">О сервисе</div>{''.join(nav)}<div class="nav-group">Аккаунт</div>{account}<div class="nav-group">Инструменты</div>{link("calculator","Калькулятор себестоимости")}{link("profit")}</nav>{assistant}
      <main id="public-info-pane" aria-label="Информация о сервисе"><div class="pm-work-header"><strong id="public-panel-title">{escape(PAGES[key][1])}</strong><button id="public-open-chat" type="button" class="secondary">Помощник</button></div>
      <div id="public-info-content" data-panel-key="{key}">{content}{footer()}</div></main></div>
      <div id="cookie-choice" class="cookie-choice" hidden><p>Мы используем необходимые cookie для входа и сохранения контекста. Необязательная аналитика отключена.</p>{link("privacy","Подробнее")}<button type="button" id="cookie-accept">Понятно</button><button type="button" class="secondary" id="cookie-decline">Только необходимые</button></div>
      <script defer src="/assets/podmasterye-public-calculator.js?v={calc_script}"></script><script defer src="/assets/podmasterye-public.js?v={script}"></script></body></html>""",status_code=status,headers={**HEADERS,"X-Robots-Tag":robots,"Vary":"X-PM-Panel"})

async def page(request, key):
    member = await signed_in(request)
    if key=="payment":
        content=await payment_content(request, member)
    elif key in ("calculator","profit"):
        from .podmasterye_public_calculators import cost_content,profit_content
        content=(cost_content if key=="calculator" else profit_content)(member)
    elif key=="faq":
        content=await run_in_threadpool(faq,request.app.state.identity)
    else:
        content={"about":about,"support":support,"contacts":contacts,"privacy":privacy}[key]()
    return panel_response(request,key,content,is_member=member)

async def robots(request):
    if not indexing():
        return Response("User-agent: *\nDisallow: /\n",media_type="text/plain")
    return Response("User-agent: *\nDisallow: /api/\nDisallow: /app/\nDisallow: /admin\nDisallow: /guest/\nDisallow: /auth/\nDisallow: /login\nDisallow: /register\nDisallow: /payment/return\nSitemap: "+origin()+"/sitemap.xml\n",media_type="text/plain")

async def sitemap(request):
    base=origin()
    if not base:
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',media_type="application/xml")
    urls="".join("<url><loc>"+escape(base+PAGES[k][0])+"</loc></url>" for k in INDEXABLE)
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+urls+"</urlset>",media_type="application/xml")
