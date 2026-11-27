"""Typed built-in capability policy, independent of user-installed plugins.

The registry describes the existing authoritative handlers. It never creates a
second wallet or a second accounting implementation. Every caller must first
authenticate its session or operation grant; this policy then checks the exact
account/chat scope again at the service boundary.
"""
from dataclasses import dataclass
from .storage import Scope, _owns_chat


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    effect: str = "read"
    role: str = "user"
    cost: str = "local"
    confirmation: str = "none"
    handler: str = ""
    scope: str = "account"
    authority: str = "session"


CAPABILITIES = {item.id: item for item in (
    Capability("account.profile", "Профиль", "read", handler="account_finance.profile"),
    Capability("account.wallet", "Кошелёк", handler="identity.wallet"),
    Capability("accounting.read", "Хозяйственный учёт", handler="podmasterye_book.report", scope="workshop_chat"),
    Capability("reports.read", "Отчёты мастерской", handler="podmasterye_book.report", scope="workshop_chat"),
    Capability("accounting.write", "Хозяйственная операция", "write", confirmation="data_version",
               handler="podmasterye_book.commit_action", scope="workshop_chat"),
    Capability("timer.manage", "Расписания", "schedule", confirmation="event_version",
               handler="podmasterye_timer.prepare", scope="workshop_chat"),
    Capability("timer.run", "Запуск расписания", "schedule", confirmation="event_version",
               handler="podmasterye_timer.control", scope="workshop_chat"),
    Capability("assistant.chat", "Подмастерье", "generation", cost="provider_quote",
               handler="podmasterye_scoped.routes:turn", scope="workshop_chat"),
    Capability("assistant.web", "Поиск и чтение сайтов", "read", cost="provider_quote",
               handler="web_access.WebAccess.request", scope="workshop_chat", authority="operation_grant"),
    Capability("assistant.illustration", "Иллюстрации", "generation", cost="provider_quote",
               handler="user_plugins.illustrations.create", scope="workshop_chat", authority="operation_grant"),
    Capability("assistant.preferences", "Настройки общения", "account",
               handler="assistant_preferences.update", confirmation="settings_version"),
    Capability("files.read", "Чтение файлов", handler="native/chat-files.mjs:read_chat_file",
               scope="workshop_chat", authority="operation_grant"),
    Capability("files.create", "Документы", "write", handler="native/document-tools.mjs:create_document",
               scope="workshop_chat", authority="operation_grant"),
    Capability("telegram.send", "Уведомления Telegram", "delivery", confirmation="channel_selection",
               handler="telegram_integration.TelegramIntegration.send", authority="confirmed_channel"),
    Capability("admin.accounts", "Аккаунты", "account", role="admin", confirmation="account_version",
               handler="account_lifecycle.change", scope="admin_accounts"),
    Capability("admin.finance", "Расходы и сверка", "finance", role="admin", confirmation="receipt",
               handler="account_finance.admin_report", scope="admin_accounts"),
    Capability("admin.models", "Модели и провайдеры", "account", role="admin", confirmation="settings_version",
               handler="ai_settings.routes:admin", scope="admin_service"),
    Capability("admin.timer", "Состояние расписаний", role="admin", handler="podmasterye_timer.admin_routes:overview", scope="admin_accounts"),
    Capability("admin.analytics", "Посещения", role="admin", handler="podmasterye_visits.visits", scope="admin_service"),
    Capability("admin.system", "Состояние системы", role="admin", handler="system_status.snapshot", scope="admin_service"),
)}


def permitted(db, scope, capability_id):
    item = CAPABILITIES.get(capability_id)
    if item is None:
        return False
    actor, workspace = getattr(scope, "actor_id", None), getattr(scope, "workspace_id", None)
    if not actor or not workspace:
        return False
    owner = db.execute("""SELECT 1 FROM identity_accounts a JOIN workspaces w
        ON w.workspace_id=a.workspace_id AND w.owner_id=a.actor_id
        WHERE a.actor_id=? AND a.workspace_id=?""", (actor, workspace)).fetchone()
    if not owner:
        return False
    from .account_lifecycle import assert_active
    try:
        assert_active(db, actor)
        if getattr(scope, "chat_id", None):
            if not _owns_chat(db, scope):
                return False
            from .podmasterye_workshops import chat_workspace
            chat_workspace(db, scope)
    except (PermissionError, ValueError):
        return False
    if item.role == "admin" and not db.execute(
            "SELECT 1 FROM identity_admins WHERE actor_id=?", (actor,)).fetchone():
        return False
    return True


def require(db, scope, capability_id):
    if not permitted(db, scope, capability_id):
        raise PermissionError("Возможность недоступна этому аккаунту или чату.")


def _object(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


def schema(capability_id):
    """Schema of the named *existing* handler, never a synthetic dispatcher.

    Account/chat identities and operation grants are transport authority; they
    cannot be supplied as ordinary tool arguments. Binding metadata below names
    the route or native tool that accepts each contract.
    """
    from . import podmasterye_matrix as matrix
    if capability_id not in CAPABILITIES:
        raise KeyError(capability_id)
    key = {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,128}$"}
    version = {"type": "integer", "minimum": 1}
    if capability_id in ("accounting.read", "reports.read"):
        return matrix.report_schema()
    if capability_id == "accounting.write":
        return _object({"requestId": key, **matrix.operation_schema()["properties"],
                        "revision": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
                       ("requestId", "operation", "arguments", "revision"))
    if capability_id == "timer.manage":
        from .podmasterye_timer import argument_schema
        return argument_schema()
    if capability_id == "timer.run":
        return _object({"requestId": key, "operation": {"const": "run"}, "revision": version},
                       ("requestId", "operation", "revision"))
    if capability_id == "assistant.preferences":
        from .assistant_preferences import OPTIONS
        return _object({**{k: {"type": "string", "enum": values} for k, values in OPTIONS.items()},
                        "revision": {"type": "integer", "minimum": 0}}, (*OPTIONS, "revision"))
    if capability_id == "assistant.illustration":
        from .user_plugins.illustrations import CREATE_SCHEMA
        from copy import deepcopy
        return deepcopy(CREATE_SCHEMA)
    if capability_id == "assistant.chat":
        from . import podmasterye_agent_forms as forms
        context = forms.schema(); context["properties"].pop("page")
        view = _object({"page": {"type": "string", "enum": sorted(forms.PAGES)},
                        "metric": {"type": "string", "enum": list(matrix.METRICS)},
                        **{k: {"type": "string", "maxLength": 240} for k in ("search", "category", "channel")},
                        **{k: {"type": "string", "format": "date"} for k in ("start", "end")}}, ("page",))
        return _object({"requestId": key, "text": {"type": "string", "maxLength": 8192},
                        "maxCoins": {"type": "string", "pattern": r"^[0-9]{1,7}(\.[0-9]{1,12})?$"},
                        "attachments": {"type": "array", "items": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                                        "maxItems": 10, "uniqueItems": True},
                        "formContext": context, "viewContext": view}, ("requestId", "text"))
    if capability_id == "assistant.web":
        return {"oneOf": [
            _object({"query": {"type": "string", "minLength": 1, "maxLength": 128},
                     "count": {"type": "integer", "minimum": 1, "maximum": 8},
                     "need_content": {"const": False}}, ("query", "need_content")),
            _object({"url": {"type": "string", "format": "uri", "pattern": "^https?://"}}, ("url",))]}
    if capability_id == "files.read":
        return _object({"id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                        "offset": {"type": "integer", "minimum": 0},
                        "page": {"type": "integer", "minimum": 1}, "frame": {"type": "integer", "minimum": 1},
                        "action": {"type": "string", "enum": ["read", "search", "sheets", "range", "sum"]},
                        **{k: {"type": "string"} for k in ("crop", "member", "sheet", "range", "search")}})
    if capability_id == "files.create":
        return _object({"format": {"type": "string", "enum": ["xlsx", "docx", "pptx", "pdf", "csv", "txt", "md", "json", "zip"]},
                        "name": {"type": "string", "minLength": 1, "maxLength": 160},
                        "content_json": {"type": "string", "maxLength": 262144,
                                         "description": "JSON content defined by the native document_formats tool."}},
                       ("format", "name", "content_json"))
    if capability_id == "telegram.send":
        return _object({"text": {"type": "string", "minLength": 1, "maxLength": 4096}}, ("text",))
    if capability_id == "admin.accounts":
        return _object({"requestId": key, "items": {"type": "array", "minItems": 1, "maxItems": 100,
                        "items": _object({"actor": key, "expected": {"type": "string", "minLength": 1}}, ("actor", "expected"))},
                        "action": {"type": "string", "enum": ["block", "archive", "restore"]},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 500}},
                       ("requestId", "items", "action", "reason"))
    if capability_id == "admin.finance":
        return _object({**{k: {"type": "string"} for k in ("start", "end", "zone", "login", "provider", "kind", "operation")},
                        "state": {"type": "string", "enum": ["", "reserved", "running", "pending", "settled", "conflict"]},
                        "sort": {"type": "string", "enum": ["date", "account", "provider", "coins", "cost"]},
                        "direction": {"type": "string", "enum": ["asc", "desc"]},
                        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
                        "limit": {"type": "integer", "enum": [10, 20, 50, 100]}})
    if capability_id == "admin.models":
        return _object({"model": {"type": "string", "pattern": "^[A-Za-z0-9_~./:-]{1,200}$"},
                        "enabled": {"type": "boolean"}, "revision": {"type": "integer", "minimum": 0}},
                       ("model", "enabled", "revision"))
    if capability_id == "admin.timer":
        return _object({"page": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "enum": [10, 20, 50, 100]}})
    if capability_id == "admin.analytics":
        return _object({"period": {"type": "string"}, "date_from": {"type": "string", "format": "date"},
                        "date_to": {"type": "string", "format": "date"}})
    # Profile, wallet balance and system metadata reads have no user arguments.
    return _object()


BINDINGS = {
    "account.profile": ("http", "GET /api/profile"),
    "account.wallet": ("http", "GET /api/wallet"),
    "accounting.read": ("service", "podmasterye_book.report"),
    "reports.read": ("service", "podmasterye_book.report"),
    "accounting.write": ("http", "POST /api/accounting/commit"),
    "timer.manage": ("http", "POST /api/chats/{chat_id}/timer/preview"),
    "timer.run": ("http", "POST /api/chats/{chat_id}/timer/events/{event}"),
    "assistant.chat": ("http", "POST /api/chats/{chat_id}/turns"),
    "assistant.web": ("operation_http", "POST /v1/tools/{search|fetch}"),
    "assistant.illustration": ("native_tool", "create_illustration"),
    "assistant.preferences": ("http", "POST /api/assistant/preferences"),
    "files.read": ("native_tool", "read_chat_file"),
    "files.create": ("native_tool", "create_document"),
    "telegram.send": ("service", "TelegramIntegration.send"),
    "admin.accounts": ("http", "POST /api/admin/accounts/lifecycle"),
    "admin.finance": ("http", "GET /api/admin/finance"),
    "admin.models": ("http", "POST /api/admin/ai-models"),
    "admin.timer": ("http", "GET /api/admin/timer"),
    "admin.analytics": ("http", "GET /admin/visits"),
    "admin.system": ("http", "GET /api/admin/system"),
}


def describe(db, scope):
    return [dict(id=c.id, label=c.label, effect=c.effect, role=c.role, cost=c.cost,
                 scope=c.scope, authority=c.authority, builtin=True,
                 confirmation=c.confirmation, handler=c.handler,
                 transport=BINDINGS[c.id][0], entrypoint=BINDINGS[c.id][1],
                 argumentSchema=schema(c.id)) for c in CAPABILITIES.values()
            if permitted(db, scope, c.id)]


def report(db, scope, **arguments):
    require(db, scope, "reports.read")
    from . import podmasterye_book as book, podmasterye_workshops as workshops
    return book.report(db, workshops.chat_workspace(db, scope), **arguments)


def accounting(db, scope, request_id, operation, arguments, revision):
    """One confirmed execution contract, usable by HTTP, tools and schedules."""
    require(db, scope, "accounting.write")
    from . import podmasterye_book as book, podmasterye_workshops as workshops
    workspace = workshops.chat_workspace(db, scope)
    return book.commit_action(db, workspace, request_id, operation, arguments, revision)
