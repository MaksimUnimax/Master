"""Reference Metrika reports, with a dedicated counter and credential for this service."""
import json,re
from argparse import Namespace
from datetime import datetime
from functools import partial
from html import escape
from pathlib import Path
from urllib.request import build_opener
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route
from . import admin_visits as reference,metrika_report as metrika
from .admin_statistics import TZ,require_admin
from .browser_session import _form_fields,_redirect
from .podmasterye_admin_web import check,shell
from .podmasterye_market_links import private_write

PATH="/admin/visits"
DOMAIN="podmasterye.185-219-43-9.sslip.io"

def load(path):
    try:
        d=json.loads(path.read_text())
        return (counter_id(d["counter"]),metrika.validate_token(d["token"]))
    except FileNotFoundError:return None

def counter_id(raw):
    if not isinstance(raw,str) or not re.fullmatch(r"[1-9][0-9]{0,17}",raw):raise ValueError("Укажите номер собственного счётчика.")
    if raw=="114504756":raise ValueError("Нельзя использовать счётчик Octoport.")
    return raw

def get_report(counter,token,start,end,*,summary=False):
    args=Namespace(counter=int(counter),date_from=start,date_to=end,report="summary" if summary else "all",top=10)
    return metrika.report(build_opener(metrika.NoRedirects()),args,metrika.validate_token(token),fetch=partial(metrika.get_report,attempts=1,timeout=5))

def render(period,ranges,start,end,today,configured,*,report=None,message="",status=200):
    options="".join(f'<option value="{key}" data-from="{a}" data-to="{b}"'+(" selected" if key==period else "")+f'>{label}</option>' for key,(label,a,b) in ranges.items())
    options+='<option value="custom"'+(' selected' if period=='custom' else '')+'>Свой период</option>'
    saved=escape(configured[0]) if configured else ""
    connection="Собственный счётчик "+saved+" подключён." if configured else "Счётчик не подключён. Данных посещаемости пока нет."
    action=escape(PATH+"?"+reference.period_query(period,start,end),quote=True)
    body=f'''<section><h2>Отчёт по {DOMAIN}</h2><p>Яндекс Метрика · {connection}</p>
<form id="visits-filters" class="stats-search" method="get" action="{PATH}"><label class="visits-period">Период<select name="period">{options}</select></label>
<label>С<input type="date" name="date_from" value="{escape(start[:10],quote=True)}" max="{today}"></label><label>По<input type="date" name="date_to" value="{escape(end[:10],quote=True)}" max="{today}"></label><button>Показать</button></form>
<p class="stats-message" role="{'alert' if status>=400 else 'status'}">{escape(message)}</p></section>
<section><h2>Подключение Метрики</h2><p>Используйте отдельный счётчик Подмастерья с правом metrika:read. История Octoport не импортируется.</p>
<form method="post" action="{action}" autocomplete="off"><label>Номер счётчика<input name="counter" inputmode="numeric" pattern="[1-9][0-9]{{0,17}}" maxlength="18" value="{saved}" required></label><label>OAuth-токен<input type="password" name="token" maxlength="2048" autocomplete="new-password" required></label><button>Проверить и сохранить</button></form>
<details><summary>Как подключить</summary><ol><li>Создайте собственный счётчик для {DOMAIN} в Яндекс Метрике.</li><li>В <a href="https://oauth.yandex.ru/?dialog=create-client-entry" rel="noreferrer">Яндекс OAuth</a> создайте приложение с разрешением <code>metrika:read</code>.</li><li>Получите токен для аккаунта, имеющего доступ к этому счётчику, и сохраните номер и токен здесь.</li></ol><p class="stats-hint">Отчёт не устанавливает счётчик на страницы сайта. Сбор посещений требует отдельного подключения аналитики с согласием посетителей.</p></details></section>'''
    if report is not None:body+='<div class="visits-table">'+reference.render_report(report)+'</div>'
    return shell("visits","Посещения",body,status=status,scripts=("admin-visits.js",))

async def visits(request):
    token=await check(request);identity=request.app.state.identity
    path=request.app.state.pm_metrika_path
    today=datetime.now(TZ).date();ranges=reference.ranges_for(today)
    q=request.query_params;period=q.get("period","7")
    if period not in ranges and period!="custom":period="7"
    if period=="custom":start,end=q.get("date_from",""),q.get("date_to","")
    else:_,start,end=ranges[period]
    configured=None
    try:
        configured=await run_in_threadpool(load,path)
        if not reference.valid_dates(start,end,today):
            return render(period,ranges,start,end,today,configured,message="Укажите корректный диапазон дат.",status=400)
        if request.method=="POST":
            fields=await _form_fields(request,{"counter","token"},max_bytes=8192)
            c=counter_id(fields["counter"].strip());key=metrika.validate_token(fields["token"].strip())
            await run_in_threadpool(get_report,c,key,today.isoformat(),today.isoformat(),summary=True)
            def save():
                with identity._lock:
                    require_admin(identity._db,token)
                    private_write(path,json.dumps({"counter":c,"token":key}).encode())
            await run_in_threadpool(save)
            return _redirect(PATH+"?saved=1&"+reference.period_query(period,start,end))
        report=await run_in_threadpool(get_report,*configured,start,end) if configured else None
        return render(period,ranges,start,end,today,configured,report=report,message="Доступ к Метрике проверен." if q.get("saved")=="1" and report else "")
    except (ValueError,metrika.ReportError) as e:return render(period,ranges,start,end,today,configured,message=str(e),status=400 if request.method=="POST" else 502)
    except (OSError,UnicodeError,KeyError):return render(period,ranges,start,end,today,configured,message="Хранилище настроек недоступно.",status=503)

def routes():return [Route(PATH,visits,methods=["GET","POST"])]
