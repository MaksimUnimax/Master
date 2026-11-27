"""Podmasterye administration. Shared navigation; separate, role-protected pages."""
from html import escape
import json
import logging
import sqlite3
from .podmasterye_admin_initial import initial
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse
from starlette.routing import Route
from .browser_session import browser_token,_PRIVATE_HEADERS
from .web_ui import version_asset_urls

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

def shell(active,title,body,*,status=200,scripts=(),initial_data=None):
    # Escape HTML parser terminators even if a user-controlled login or alias includes them.
    snapshot=json.dumps(initial_data or {},ensure_ascii=True,separators=(",",":"),allow_nan=False).replace("<","\\u003c")
    boot='<script type="application/json" id="pm-admin-initial">'+snapshot+'</script>' 
    tags=''.join(f'<script defer src="/assets/{name}"></script>' for name in scripts)
    wide=' pm-admin-visits' if active=='visits' else ' pm-admin-wide' if active in ('usage','matrix','statistics') else ''
    return HTMLResponse(version_asset_urls(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Подмастерье</title><script src="/assets/podmasterye-theme.js"></script><link rel="stylesheet" href="/assets/appearance.css"><link rel="stylesheet" href="/assets/admin.css"><link rel="stylesheet" href="/assets/podmasterye-admin.css">
<script defer src="/assets/presence.js"></script>{tags}</head>
<body class="octo-admin pm-admin"><div class="pm-admin-layout">{nav(active)}<main class="pm-admin-main{wide}"><h1>{escape(title)}</h1>{body}<p id="admin-problem" role="alert"></p>{boot}</main></div></body></html>'''),status_code=status,headers=HEADERS)

async def check(request):
    token=browser_token(request)
    if not await run_in_threadpool(request.app.state.identity.is_admin,token):
        raise HTTPException(403,"Требуются права администратора.")
    return token

async def page(request):
    token=await check(request)
    name=request.url.path.removeprefix("/admin").strip("/")
    titles=dict(PAGES)
    if name not in titles or name in ("statistics","visits"):raise HTTPException(404)
    content=(UI/("pm-admin-"+(name or "overview")+".html")).read_text()
    scripts=["podmasterye-admin.js"]
    if name=="matrix":scripts.append("podmasterye-matrix-admin.js")
    if name=="telegram":scripts.append("podmasterye-market-links.js")
    try:
        initial_data=await run_in_threadpool(initial,request.app.state,token,name)
    except PermissionError:
        raise HTTPException(403,"Требуются права администратора.") from None
    except (OSError,sqlite3.Error,ValueError):
        # A transient read failure must not hide the page or turn into cached private data.
        logging.getLogger(__name__).warning("Admin initial read unavailable: %s",name)
        initial_data={}
    return shell(name,titles[name],content,scripts=scripts,initial_data=initial_data)

def routes():
    return [Route("/admin"+("/"+name if name else ""),page) for name,_ in PAGES if name not in ("statistics","visits")]
