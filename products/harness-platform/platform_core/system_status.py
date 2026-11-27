"""Read-only deployment settings backed by the same product configuration.

Secrets and filesystem paths are never included. Changes to deployment identity,
mail transport and payment activation remain operations configuration, not a
second set of mutable settings in the application database.
"""
import os
from html import escape

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import analytics, checkout, schema_migrations, site_identity
from .admin_statistics import require_admin


def snapshot(state, token):
    with state.identity._lock:
        require_admin(state.identity._db, token)
        migrations = schema_migrations.applied(state.identity._db)
    try:
        effective_origin = site_identity.integration_origin()
        origin_error = False
    except ValueError:
        effective_origin, origin_error = None, True
    try:
        analytics_state = analytics.snapshot(state.pm_metrika_path)
        analytics_state = {key: analytics_state[key] for key in ("configured", "enabled", "originConfigured")}
    except (OSError, ValueError, KeyError):
        analytics_state = {"configured": False, "enabled": False, "invalid": True}
    loop = getattr(getattr(state, "timer", None), "loop", None)
    return {
        "service": site_identity.SERVICE_NAME, "assistant": site_identity.AGENT_NAME,
        "origin": {"configured": bool(site_identity.public_origin()), "value": effective_origin,
                   "invalid": origin_error},
        "indexing": bool(site_identity.public_origin() and os.getenv("PODMASTERYE_INDEX_PUBLIC") == "1"),
        "mail": {"transportConfigured": bool(os.getenv("HARNESS_SMTP_HOST") and os.getenv("HARNESS_SMTP_FROM"))},
        "payments": {"available": checkout.merchant() is not None,
                     "activationRequested": os.getenv("YOOKASSA_PAYMENTS_ENABLED") == "1",
                     "receiptConfigured": checkout.fiscal_policy() is not None,
                     "pilotOnly": os.getenv("YOOKASSA_PILOT_ONLY") == "1"},
        "analytics": analytics_state,
        "timer": {"running": bool(loop is not None and not loop.done())},
        "migrations": migrations,
        "irreversibleDeletion": False,
    }


def render(value):
    def row(label, content):
        return '<tr><th scope="row">'+escape(label)+'</th><td>'+escape(str(content))+'</td></tr>'
    origin = value["origin"]
    address = "Некорректная конфигурация; внешние действия недоступны." if origin["invalid"] else origin["value"]
    if address and not origin["configured"]:
        address += " · совместимый тестовый адрес, постоянный адрес не задан"
    payment = value["payments"]
    payment_state = ("Включены для пилотного аккаунта" if payment["pilotOnly"] else "Включены") if payment["available"] else "Выключены"
    if not payment["available"] and payment["activationRequested"]:
        payment_state += " · конфигурация магазина или чеков не принята"
    rows = [row("Сервис", value["service"]), row("Помощник", value["assistant"]), row("Внешний адрес", address or "Не задан"),
            row("Индексация публичных страниц", "Разрешена" if value["indexing"] else "Закрыта"),
            row("Почта", "Транспорт настроен; фактическую доставку проверяют отдельно" if value["mail"]["transportConfigured"] else "Транспорт не настроен"),
            row("Приём платежей", payment_state),
            row("Фискальные настройки", "Заданы" if payment["receiptConfigured"] else "Не заданы"),
            row("Посещения", "Сбор разрешён с согласия посетителя" if value["analytics"]["enabled"] else "Сбор выключен"),
            row("Планировщик", "Работает" if value["timer"]["running"] else "Не запущен"),
            row("Необратимое удаление", "Закрыто до утверждения политики хранения и отдельной приёмки")]
    migrations = ''.join(row(item["version"], item["checksum"]) for item in value["migrations"])
    return ('<section class="admin-card"><h2>Конфигурация сервиса</h2><p>Состояние текущего процесса. '
            'Адрес, почтовый транспорт и активация платежей управляются единой конфигурацией развёртывания.</p>'
            '<div class="table-scroll"><table>'+''.join(rows)+'</table></div></section>'
            '<section class="admin-card"><h2>Настройки подключений</h2><div class="button-group">'
            '<a href="/admin/keys">API-ключи</a><a href="/admin/models">Модели</a>'
            '<a href="/admin/telegram">Telegram</a><a href="/admin/visits">Метрика</a>'
            '<a href="/admin/finance">Платежи и сверка</a></div></section>'
            '<details class="admin-card"><summary>Применённые миграции базы данных</summary>'
            '<div class="table-scroll"><table>'+migrations+'</table></div></details>')


def routes(token_for):
    async def read(request):
        from .identity import AuthenticationError
        try:
            value = await run_in_threadpool(snapshot, request.app.state, token_for(request, allow_cookie=True))
        except AuthenticationError:
            raise
        except PermissionError:
            raise HTTPException(403, "Требуются права администратора.") from None
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    return [Route("/api/admin/system", read)]
