"""Verified model capabilities and per-account model settings for built-in actions.

Provider metadata and real compatibility evidence are different facts. A new
OpenRouter model is visible in administration while pending; only a model with
evidence for the requested capability is selectable by users. Evidence is
written by the operator's acceptance runner, never by a browser checkbox.
"""
import hashlib
import json
import re
from time import time

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import assistant_preferences, model_choices
from .identity import _principal
from .operation_grants import OperationScope

IMAGE = "assistant.illustration"
MODEL = re.compile(r"[A-Za-z0-9_~./:-]{1,200}")
REQUIRED = {"chat": ("tools", "streaming", "context", "cancel"), "image": ("image", "artifact", "billing")}
SCHEMA = (
    assistant_preferences.SCHEMA,
    *model_choices.SCHEMA,
    "CREATE TABLE IF NOT EXISTS model_preferences(workspace TEXT PRIMARY KEY REFERENCES workspaces, model TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS ai_model_permissions(
       model TEXT PRIMARY KEY, enabled INTEGER NOT NULL CHECK(enabled IN(0,1)),
       revision INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_model_compatibility(
       model TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN('chat','image')),
       capabilities TEXT NOT NULL, evidence TEXT NOT NULL, verified_at INTEGER NOT NULL,
       PRIMARY KEY(model,purpose))""",
    """CREATE TABLE IF NOT EXISTS capability_model_settings(
       workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       capability TEXT NOT NULL, model TEXT NOT NULL, free INTEGER NOT NULL CHECK(free IN(0,1)),
       revision INTEGER NOT NULL, PRIMARY KEY(workspace,capability))""",
    """CREATE TABLE IF NOT EXISTS operation_capability_models(
       operation_id TEXT NOT NULL REFERENCES usage_operations(operation_id) ON DELETE CASCADE,
       capability TEXT NOT NULL,model TEXT NOT NULL,free INTEGER NOT NULL,revision INTEGER NOT NULL,
       PRIMARY KEY(operation_id,capability))""",
    """CREATE TABLE IF NOT EXISTS provider_balance_thresholds(
       provider TEXT PRIMARY KEY CHECK(provider IN('deepseek','openrouter')),
       threshold TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS illustration_requests(
       operation_id TEXT PRIMARY KEY REFERENCES usage_operations(operation_id) ON DELETE CASCADE,
       prompt_hash TEXT NOT NULL)""",
)


def initialize(db):
    from .schema_migrations import apply
    from .user_plugins.illustrations import SCHEMA as images_schema
    apply(db, "20261127_ai_v1", statements=(*SCHEMA, images_schema))
    apply(db, "20261127_ai_v2", statements=(
        """CREATE TABLE IF NOT EXISTS illustration_versions(
            illustration TEXT PRIMARY KEY REFERENCES plugin_illustrations(id) ON DELETE CASCADE,
            chat TEXT NOT NULL REFERENCES chats ON DELETE CASCADE,
            version INTEGER NOT NULL CHECK(version>0), UNIQUE(chat,version))""",
        """INSERT OR IGNORE INTO illustration_versions(illustration,chat,version)
            SELECT i.id,i.chat,ROW_NUMBER() OVER(PARTITION BY i.chat ORDER BY a.started_ms,i.rowid)
            FROM plugin_illustrations i JOIN coin_attempts a ON a.attempt_id=i.attempt""",
    ))


def compatible(db, model, purpose="chat"):
    row = db.execute("SELECT capabilities,evidence,verified_at FROM ai_model_compatibility WHERE model=? AND purpose=?",
                     (model, purpose)).fetchone()
    if row:
        capabilities = json.loads(row[0])
        return {"verified": all(capabilities.get(k) is True for k in REQUIRED[purpose]),
                "capabilities": capabilities, "evidence": row[1], "verifiedAt": row[2], "inherited": False}
    # Direct DeepSeek is the existing deployed adapter, not a newly advertised
    # third-party model. Its gateway restricts the actual supported model IDs.
    return {"verified": "/" not in model and purpose == "chat", "capabilities": {},
            "evidence": None, "verifiedAt": None, "inherited": "/" not in model and purpose == "chat"}


def record_compatibility(db, model, purpose, capabilities, evidence):
    """Operator-only acceptance hook; evidence identifies an actual saved run."""
    if not isinstance(model, str) or not MODEL.fullmatch(model) or purpose not in REQUIRED:
        raise ValueError("Invalid model compatibility record")
    if not isinstance(capabilities, dict) or set(capabilities) != set(REQUIRED[purpose]) or any(type(v) is not bool for v in capabilities.values()):
        raise ValueError("Every required capability must have a measured outcome")
    if not isinstance(evidence, str) or not re.fullmatch(r"[A-Za-z0-9_./:-]{8,240}", evidence):
        raise ValueError("A saved acceptance evidence reference is required")
    db.execute("""INSERT INTO ai_model_compatibility VALUES(?,?,?,?,?) ON CONFLICT(model,purpose)
        DO UPDATE SET capabilities=excluded.capabilities,evidence=excluded.evidence,verified_at=excluded.verified_at""",
        (model, purpose, json.dumps(capabilities, sort_keys=True), evidence, int(time())))


def model_allowed(db, model, purpose="chat"):
    row = db.execute("SELECT enabled FROM ai_model_permissions WHERE model=?", (model,)).fetchone()
    return (not row or bool(row[0])) and compatible(db, model, purpose)["verified"]


def decorate(db, catalog, *, admin=False):
    result = {}
    for model, source in catalog.items():
        row = dict(source)
        enabled = db.execute("SELECT enabled,revision FROM ai_model_permissions WHERE model=?", (model,)).fetchone()
        chat = compatible(db, model, "chat")
        illustration = compatible(db, model, "image")
        row.update(allowed=not enabled or bool(enabled[0]), permissionRevision=enabled[1] if enabled else 0)
        row["chat"] = bool(source.get("chat") and row["allowed"] and chat["verified"])
        row["image"] = bool(source.get("image") and row["allowed"] and illustration["verified"])
        if admin:
            row.update(advertisedChat=bool(source.get("chat")), advertisedImage=bool(source.get("image")),
                       compatibility={"chat": chat, "image": illustration})
        if admin or row["chat"] or row["image"]:
            result[model] = row
    return result


def action_model(db, workspace, capability=IMAGE):
    row = db.execute("SELECT model,free,revision FROM capability_model_settings WHERE workspace=? AND capability=?",
                     (workspace, capability)).fetchone()
    return {"model": row[0], "free": bool(row[1]), "revision": row[2]} if row else {"model": "", "free": False, "revision": 0}


def save_action_model(db, workspace, model, revision, catalog, capability=IMAGE):
    if capability != IMAGE or type(revision) is not int or not isinstance(model, str):
        raise HTTPException(400, "Некорректная настройка модели.")
    old = action_model(db, workspace, capability)
    if revision != old["revision"]:
        raise HTTPException(409, "Модель иллюстраций уже изменена. Обновите настройки.")
    if model and (not catalog.get(model, {}).get("image") or not model_allowed(db, model, "image")):
        raise HTTPException(400, "Эта модель пока недоступна для создания иллюстраций.")
    free = bool(catalog.get(model, {}).get("free"))
    if model != old["model"] or free != old["free"]:
        db.execute("""INSERT INTO capability_model_settings VALUES(?,?,?,?,?)
            ON CONFLICT(workspace,capability) DO UPDATE SET model=excluded.model,free=excluded.free,revision=excluded.revision""",
            (workspace, capability, model, int(free), revision + 1))
    return action_model(db, workspace, capability)


def image_enabled(db, scope):
    from .capability_registry import permitted
    model = action_model(db, scope.workspace_id)["model"]
    return permitted(db, scope, IMAGE) and bool(model and model_allowed(db, model, "image"))


def bind_action_models(db, scope, operation):
    value = action_model(db, scope.workspace_id)
    if value["model"] and not model_allowed(db, value["model"], "image"):
        value = {**value, "model": "", "free": False}
    db.execute("INSERT OR IGNORE INTO operation_capability_models VALUES(?,?,?,?,?)",
               (operation, IMAGE, value["model"], int(value["free"]), value["revision"]))


def turn_images_enabled(db, scope, request_id):
    from .capability_registry import permitted
    if not permitted(db, scope, IMAGE):
        return False
    row = db.execute("""SELECT m.model FROM usage_operations o JOIN operation_capability_models m USING(operation_id)
        WHERE o.actor_id=? AND o.workspace_id=? AND o.chat_id=? AND o.source='chat.turn' AND o.run_key=? AND m.capability=?""",
        (scope.actor_id, scope.workspace_id, scope.chat_id, request_id, IMAGE)).fetchone()
    return bool(row[0]) if row else image_enabled(db, scope)


def turn_selection(db, scope, request_id):
    """Resolve the immutable operation route before a retry's provider preflight."""
    operation = db.execute("""SELECT operation_id FROM usage_operations
        WHERE actor_id=? AND workspace_id=? AND chat_id=? AND source='chat.turn' AND run_key=?""",
        (scope.actor_id, scope.workspace_id, scope.chat_id, request_id)).fetchone()
    if operation:
        direct = db.execute("SELECT model FROM direct_operation_models WHERE operation_id=?", operation).fetchone()
        if direct:
            return "direct", True
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_routes'").fetchone():
            route = db.execute("SELECT model FROM operation_routes WHERE operation_id=?", operation).fetchone()
            if route:
                return route[0], True
    return model_choices.selection(db, scope.workspace_id)[0], False


class WorkshopRecoveryPolicy:
    """Product callbacks for the existing durable OpenRouter recovery engine."""
    def __init__(self, state):
        self.state = state

    def authorized(self, db, scope, checkpoint):
        from .capability_registry import permitted
        return (permitted(db, scope, "assistant.chat") and not checkpoint["connections"]
                and (not checkpoint["illustrations"] or permitted(db, scope, IMAGE)))

    def context(self, db, scope, checkpoint, request_id=None):
        from . import workshop_write_permissions as permissions
        return {"connections": [], "availableServices": [], "connectionGuides": {},
                "illustrations": checkpoint["illustrations"],
                "workshopWriteMode": permissions.turn_mode(db, scope, request_id)[0] if request_id else "confirm",
                "assistantPreferences": checkpoint.get("assistantPreferences", assistant_preferences.preferences(db, scope.workspace_id))}

    async def publish(self, scope, session, request_id, result):
        from starlette.concurrency import run_in_threadpool
        from .podmasterye_domain import complete_from_session
        await run_in_threadpool(complete_from_session, self.state.identity, scope, session, request_id, result)


def configure_router(state, router):
    if router is not None:
        router.recovery_policy = WorkshopRecoveryPolicy(state)


def prompt_key(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def routes(token_for, body):
    async def settings(req):
        identity = req.app.state.identity
        token = token_for(req, allow_cookie=True)
        identity.validate_session(token)
        router = req.app.state.model_router
        fields = await body(req, "model", "revision") if req.method == "POST" else None
        catalog = await router.models(current_tariff=fields is not None) if router else {}
        with identity._write() as db:
            actor, workspace = _principal(db, token)
            from .capability_registry import require
            try:
                require(db, OperationScope(actor, workspace), IMAGE)
            except PermissionError:
                raise HTTPException(403, "Настройки иллюстраций недоступны этому аккаунту.") from None
            current = (save_action_model(db, workspace, fields["model"], fields["revision"], catalog)
                       if fields is not None else action_model(db, workspace))
            options = decorate(db, catalog)
        selected = options.get(current["model"], {})
        changed = current["free"] and current["model"] and not selected.get("free", False)
        return JSONResponse({"current": current, "enabled": bool(router and router.available()),
            "confirmTariff": bool(changed), "models": [{k: v for k, v in row.items() if k not in ("rates", "imagePrice")}
                for row in options.values() if row["image"]],
            "message": "Тариф генератора изменился. Выберите модель заново." if changed else
                       "" if selected or not current["model"] else "Выбранная модель сейчас недоступна."})

    async def admin(req):
        state = req.app.state
        token = token_for(req, allow_cookie=True)
        if not state.identity.is_admin(token):
            raise HTTPException(403, "Требуются права администратора.")
        if req.method == "POST":
            data = await body(req, "model", "enabled", "revision")
            if not isinstance(data["model"], str) or not MODEL.fullmatch(data["model"]) or type(data["enabled"]) is not bool or type(data["revision"]) is not int:
                raise HTTPException(400, "Некорректные настройки модели.")
            with state.identity._write() as db:
                actor, _ = _principal(db, token)
                if not db.execute("SELECT 1 FROM identity_admins WHERE actor_id=?",(actor,)).fetchone():
                    raise HTTPException(403, "Требуются права администратора.")
                row = db.execute("SELECT revision FROM ai_model_permissions WHERE model=?", (data["model"],)).fetchone()
                if data["revision"] != (row[0] if row else 0):
                    raise HTTPException(409, "Настройки модели изменились. Обновите список.")
                db.execute("""INSERT INTO ai_model_permissions VALUES(?,?,?,?) ON CONFLICT(model) DO UPDATE SET
                    enabled=excluded.enabled,revision=excluded.revision,updated_at=excluded.updated_at""",
                    (data["model"], int(data["enabled"]), data["revision"] + 1, int(time())))
        from .chat_defaults import choice_catalog
        catalog, notice = await choice_catalog(state, refresh=req.query_params.get("refresh") == "1", admin=True)
        if not state.identity.is_admin(token):
            raise HTTPException(403, "Требуются права администратора.")
        return JSONResponse({"models": list(catalog.values()), "message": notice})

    return [Route("/api/assistant/illustrations/settings", settings, methods=["GET", "POST"]),
            Route("/api/admin/ai-models", admin, methods=["GET", "POST"])]
