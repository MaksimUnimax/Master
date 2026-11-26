"""Podmasterye administration. Shared navigation; separate, role-protected pages."""
from html import escape
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse
from starlette.routing import Route
from .browser_session import browser_token,_PRIVATE_HEADERS

UI=Path(__file__).resolve().parents[1]/"native/web"
PAGES=(("","Обзор"),("keys","API-ключи"),("models","Модели"),("telegram","Telegram"),("coins","Монеты"),("usage","Расходы ИИ"),("matrix","Матрица и фильтры"),("statistics","Пользователи"),("visits","Посещения"))
HEADERS={**_PRIVATE_HEADERS,"Content-Security-Policy":"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'","Referrer-Policy":"no-referrer"}

def nav(active):
    links=[]
    for key,name in PAGES:
        url="/admin"+("/"+key if key else "")
        current=' aria-current="page"' if key==active else ''
        links.append(f'<a href="{url}"{current}>{escape(name)}</a>')
    return '<aside class="pm-admin-sidebar"><a class="pm-admin-brand" href="/app/">Подмастерье</a><p>Администрирование</p><nav aria-label="Разделы администрирования">'+''.join(links)+'</nav><div class="pm-admin-bottom"><a href="/app/">В мастерскую</a><button type="button" data-pm-theme>◐</button></div></aside>'

def shell(active,title,body,*,status=200,scripts=()):
    tags=''.join(f'<script defer src="/assets/{name}"></script>' for name in scripts)
    wide=' pm-admin-wide' if active in ('usage','matrix','statistics','visits') else ''
    return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Подмастерье</title><script src="/assets/podmasterye-theme.js"></script><link rel="stylesheet" href="/assets/appearance.css"><link rel="stylesheet" href="/assets/admin.css"><link rel="stylesheet" href="/assets/podmasterye-admin.css">
<script defer src="/assets/presence.js"></script>{tags}</head>
<body class="octo-admin pm-admin"><div class="pm-admin-layout">{nav(active)}<main class="pm-admin-main{wide}"><h1>{escape(title)}</h1>{body}<p id="admin-problem" role="alert"></p></main></div></body></html>''',status_code=status,headers=HEADERS)

async def check(request):
    token=browser_token(request)
    if not await run_in_threadpool(request.app.state.identity.is_admin,token):
        raise HTTPException(403,"Требуются права администратора.")
    return token

async def page(request):
    await check(request)
    name=request.url.path.removeprefix("/admin").strip("/")
    titles=dict(PAGES)
    if name not in titles or name in ("statistics","visits"):raise HTTPException(404)
    content=(UI/("pm-admin-"+(name or "overview")+".html")).read_text()
    scripts=["podmasterye-admin.js"]
    if name=="matrix":scripts.append("podmasterye-matrix-admin.js")
    if name=="telegram":scripts.append("podmasterye-market-links.js")
    return shell(name,titles[name],content,scripts=scripts)

def routes():
    return [Route("/admin"+("/"+name if name else ""),page) for name,_ in PAGES if name not in ("statistics","visits")]
