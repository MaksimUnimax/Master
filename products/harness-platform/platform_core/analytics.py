"""Dedicated product analytics configuration; no token is sent to the browser."""
import hashlib
import json
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from .site_identity import public_origin


def read(path):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Некорректные настройки аналитики.")
    return data


def snapshot(path):
    data = read(path)
    from .podmasterye_visits import counter_id
    counter = counter_id(data["counter"]) if data.get("counter") else None
    configured = bool(counter and data.get("token"))
    revision = hashlib.sha256(json.dumps([counter, bool(data.get("analyticsEnabled"))],
                                        separators=(",", ":")).encode()).hexdigest()
    return {"configured": configured, "enabled": bool(data.get("analyticsEnabled")) and configured,
            "counter": counter, "originConfigured": bool(public_origin()), "revision": revision}


def public_configuration(path, hostname):
    try:
        value = snapshot(path)
        origin = public_origin()
        if not origin or hostname != urlsplit(origin).hostname or not value["enabled"]:
            return {"enabled": False}
        return {"enabled": True, "counter": value["counter"], "origin": origin}
    except (OSError, ValueError, KeyError):
        return {"enabled": False}


def configure(store, token, path, enabled, revision):
    from .admin_statistics import require_admin
    from .podmasterye_market_links import private_write
    from .podmasterye_domain import Conflict
    if type(enabled) is not bool:
        raise ValueError("Укажите состояние сбора посещений.")
    with store._lock:
        require_admin(store._db, token)
        current = snapshot(path)
        if current["revision"] != revision:
            raise Conflict("Настройки Метрики изменились. Обновите страницу.")
        if enabled and (not current["configured"] or not current["originConfigured"]):
            raise ValueError("Сначала настройте собственный счётчик, токен отчётов и постоянный адрес сервиса.")
        data = read(path)
        data["analyticsEnabled"] = enabled
        private_write(path, json.dumps(data, ensure_ascii=False).encode())
        return snapshot(path)


def routes(token_for, body):
    async def public(request):
        value = await run_in_threadpool(public_configuration, request.app.state.pm_metrika_path,
                                       request.url.hostname)
        return JSONResponse(value, headers={"Cache-Control": "no-store"})
    async def settings(request):
        token = token_for(request, allow_cookie=True)
        state = request.app.state
        from .admin_statistics import require_admin
        from .identity import AuthenticationError
        try:
            if request.method == "POST":
                data = await body(request, "enabled", "revision")
                value = await run_in_threadpool(configure, state.identity, token, state.pm_metrika_path,
                                               data["enabled"], data["revision"])
            else:
                def fetch():
                    with state.identity._lock:
                        require_admin(state.identity._db, token)
                        return snapshot(state.pm_metrika_path)
                value = await run_in_threadpool(fetch)
        except AuthenticationError:
            raise
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
        return JSONResponse(value)
    return [Route("/api/analytics/config", public),
            Route("/api/admin/analytics", settings, methods=["GET", "POST"])]
