"""Initial state for a server-rendered administration page. Private, one navigation only."""
from time import time
from starlette.exceptions import HTTPException
from . import provider_keys, guest_activity, guest_selector, podmasterye_services, podmasterye_matrix_admin, podmasterye_telegram_config
from .admin_statistics import require_admin
from .operation_grants import direct_default

def initial(state,token,page):
    identity=state.identity
    with identity._lock:
        require_admin(identity._db,token)
    if page=="keys":
        return {"/api/admin/provider-keys":{"deepseek":{"configured":bool(provider_keys.read("deepseek"))}}}
    if page=="models":
        with identity._lock:
            require_admin(identity._db,token)
            model,effort=direct_default(identity._db,state.worker.env.get("HARNESS_CHAT_MODEL","deepseek-flash"))
        return {"/api/admin/chat-default":{"model":model,"effort":effort}}
    if page=="telegram":
        return {"/api/admin/podmasterye/telegram-config":podmasterye_telegram_config.status(state,token)}
    if page=="coins":
        return {"/api/admin/coin-pricing":identity.pricing(token,None,update=False)}
    if page=="usage":
        return {"/api/admin/podmasterye/usage":podmasterye_services.usage_payload(state,token)}
    if page=="matrix":
        return {"/api/admin/matrix":podmasterye_matrix_admin.catalog_snapshot(identity,token),
                "/api/admin/matrix/stats":podmasterye_matrix_admin.stats_snapshot(identity,token)}
    if page=="":
        with identity._lock:
            require_admin(identity._db,token)
            guest=guest_activity.period_report(identity._db,guest_selector.day(time()),"today")
        return {"/api/admin/provider-balances":state.provider_balances.snapshot(token),
                "/api/admin/guest-activity?period=today":guest}
    return {}
