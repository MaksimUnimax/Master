"""Reversible account lifecycle and an explicit, non-destructive impact preview.

Financial evidence and business records are never deleted by this module.
Irreversible deletion remains unavailable until an approved retention policy and
its separately accepted implementation exist. Blocking revokes authority, not
the evidence needed to settle an already dispatched provider attempt.
"""
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from time import time

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import coins, schema_migrations

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS account_lifecycle (
       actor_id TEXT PRIMARY KEY REFERENCES identity_accounts(actor_id),
       status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','blocked','archived')),
       revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
       protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0,1)),
       reason TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT(unixepoch()))""",
    """CREATE TABLE IF NOT EXISTS account_lifecycle_audit (
       id INTEGER PRIMARY KEY, operator TEXT NOT NULL, actor TEXT NOT NULL,
       action TEXT NOT NULL, old_status TEXT NOT NULL, new_status TEXT NOT NULL,
       revision INTEGER NOT NULL, reason TEXT NOT NULL, request_id TEXT NOT NULL,
       created_at INTEGER NOT NULL DEFAULT(unixepoch()))""",
    """CREATE TABLE IF NOT EXISTS account_lifecycle_requests (
       operator TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL,
       result TEXT NOT NULL, created_at INTEGER NOT NULL DEFAULT(unixepoch()),
       PRIMARY KEY(operator,request_id))""",
    """CREATE TABLE IF NOT EXISTS account_integration_pauses (
       workspace TEXT NOT NULL REFERENCES workspaces(workspace_id),
       channel TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
       reason TEXT NOT NULL, PRIMARY KEY(workspace,channel))""",
    "INSERT OR IGNORE INTO account_lifecycle(actor_id) SELECT actor_id FROM identity_accounts",
)


def initialize(db):
    schema_migrations.apply(db, "20261127_lifecycle_v1", SCHEMA)


def _exists(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone())


def status(db, actor):
    if not _exists(db, "account_lifecycle"):
        return {"status": "active", "revision": 1, "protected": False}
    row = db.execute("SELECT status,revision,protected FROM account_lifecycle WHERE actor_id=?", (actor,)).fetchone()
    return dict(status=row[0], revision=row[1], protected=bool(row[2])) if row else dict(status="active", revision=1, protected=False)


def assert_active(db, actor):
    if status(db, actor)["status"] != "active":
        from .identity import AuthenticationError
        raise AuthenticationError("Аккаунт заблокирован или находится в архиве.")


def assert_workspace_active(db, workspace):
    # Core Store is also used by trusted, non-account Harness compositions.
    # Once the account schema exists, missing ownership always fails closed.
    if not _exists(db, "identity_accounts"):
        if _exists(db, "account_lifecycle") or not db.execute(
                "SELECT 1 FROM workspaces WHERE workspace_id=?", (workspace,)).fetchone():
            raise PermissionError("Аккаунт недоступен.")
        return
    row = db.execute("""SELECT a.actor_id FROM identity_accounts a JOIN workspaces w
        ON w.owner_id=a.actor_id WHERE w.workspace_id=?""", (workspace,)).fetchone()
    if not row:
        raise PermissionError("Аккаунт недоступен.")
    assert_active(db, row[0])


def integration_paused(db, workspace, channel):
    return _exists(db, "account_integration_pauses") and bool(db.execute(
        "SELECT 1 FROM account_integration_pauses WHERE workspace=? AND channel=?", (workspace, channel)).fetchone())


def require_integration(db, workspace, channel):
    assert_workspace_active(db, workspace)
    if integration_paused(db, workspace, channel):
        raise PermissionError("Отправка приостановлена. Возобновите интеграцию в настройках.")


def _targets(actors):
    if not isinstance(actors, list) or not 1 <= len(actors) <= 100:
        raise ValueError("Выберите от 1 до 100 аккаунтов.")
    if any(not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", a) for a in actors):
        raise ValueError("Некорректный аккаунт.")
    if len(set(actors)) != len(actors):
        raise ValueError("Аккаунт выбран несколько раз.")
    return actors


def _account(db, actor):
    row = db.execute("SELECT login,workspace_id FROM identity_accounts WHERE actor_id=?", (actor,)).fetchone()
    if not row:
        raise LookupError("Аккаунт не найден.")
    return row


def _workspaces(db, actor):
    return [r[0] for r in db.execute("SELECT workspace_id FROM workspaces WHERE owner_id=? ORDER BY workspace_id", (actor,))]


def _count(db, table, condition, params):
    return db.execute('SELECT count(*) FROM "' + table + '" WHERE ' + condition, params).fetchone()[0] if _exists(db, table) else 0


def _native(journal, actor):
    if journal is None:
        return {"files": None, "bytes": None, "complete": False}
    path = Path(journal)
    if not path.exists():
        return {"files": 0, "bytes": 0, "complete": True}
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if not _exists(db, "chat_files"):
                return {"files": 0, "bytes": 0, "complete": True}
            count, size = db.execute("SELECT count(*),coalesce(sum(bytes),0) FROM chat_files WHERE actor_id=?", (actor,)).fetchone()
            return {"files": count, "bytes": size, "complete": True}
    except sqlite3.Error:
        return {"files": None, "bytes": None, "complete": False}


def _dependencies(db, actor, workspace, journal):
    spaces = _workspaces(db, actor)
    slots = ",".join("?" for _ in spaces)
    # Every directly owned table participates. FK-only child rows are added
    # separately below. Counts expose no contents or integration credentials.
    counts = {}
    for table, in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall():
        if not re.fullmatch(r"[A-Za-z0-9_]+", table):
            continue
        cols = {r[1] for r in db.execute('PRAGMA table_info("' + table + '")')}
        scope = next((x for x in ("workspace_id", "workspace", "account") if x in cols), None)
        if scope:
            counts[table] = _count(db, table, '"' + scope + '" IN (' + slots + ')', spaces)
        elif "actor_id" in cols:
            counts[table] = _count(db, table, "actor_id=?", (actor,))
    joins = {
        "coin_attempts": ("operation_id IN (SELECT operation_id FROM coin_orders WHERE workspace_id=?)", (workspace,)),
        "usage_grants": ("operation_id IN (SELECT operation_id FROM usage_operations WHERE workspace_id=?)", (workspace,)),
        "timer_runs": ("event IN (SELECT id FROM timer_events WHERE workspace=?)", (workspace,)),
        "pm_recipe": ("product IN (SELECT id FROM pm_products WHERE workspace IN (" + slots + "))", spaces),
        "pm_external_orders": ("source IN (SELECT id FROM pm_sources WHERE workspace IN (" + slots + "))", spaces),
        "pm_external_offers": ("source IN (SELECT id FROM pm_sources WHERE workspace IN (" + slots + "))", spaces),
        "pm_external_events": ("source IN (SELECT id FROM pm_sources WHERE workspace IN (" + slots + "))", spaces),
    }
    for table, (query, params) in joins.items():
        counts[table] = _count(db, table, query, params)
    available, held = coins.balances(db, workspace)
    pending = _count(db, "coin_checkouts", "workspace_id=? AND status='pending'", (workspace,))
    unknown = db.execute("""SELECT count(*) FROM coin_attempts a JOIN coin_orders o USING(operation_id)
        WHERE o.workspace_id=? AND a.charge IS NULL""", (workspace,)).fetchone()[0]
    return {"records": counts, "workshops": len(spaces), "nativeFiles": _native(journal, actor),
            "wallet": {"available": coins.display(available), "reserved": coins.display(held),
                       "availableUnits": str(available), "reservedUnits": str(held),
                       "pendingPayments": pending, "unconfirmedAttempts": unknown}}


def _eligibility(db, administrator, actor, action):
    current = status(db, actor)
    if action == "delete":
        return "Не утверждена политика хранения данных и не принята процедура необратимого удаления."
    if action not in ("block", "archive", "restore"):
        raise ValueError("Неизвестное действие.")
    if action != "restore":
        if actor == administrator:
            return "Нельзя отключить аккаунт, из которого выполнен вход."
        if current["protected"]:
            return "Этот аккаунт защищён от отключения."
        if db.execute("SELECT 1 FROM identity_admins WHERE actor_id=?", (actor,)).fetchone():
            active_admins = sum(status(db, row[0])["status"] == "active" for row in db.execute("SELECT actor_id FROM identity_admins"))
            if active_admins <= 1:
                return "Нельзя отключить последнего действующего администратора."
    return None


def _preview(db, administrator, actor, action, journal):
    login, workspace = _account(db, actor)
    current = status(db, actor)
    dependencies = _dependencies(db, actor, workspace, journal)
    signature = hashlib.sha256(json.dumps([actor, action, current, dependencies],
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    reason = _eligibility(db, administrator, actor, action)
    return {"actor": actor, "login": login, **current, "action": action, "expected": signature,
            "allowed": reason is None, "blockedReason": reason, **dependencies,
            "effects": [] if action == "delete" else
                ["Доступ к аккаунту будет восстановлен; расписания и интеграции останутся приостановленными."] if action == "restore" else
                ["Активные сеансы и разрешения на новые платные вызовы будут отозваны.",
                 "Расписания и интеграции будут приостановлены.",
                 "Хозяйственные записи, файлы, деньги и сведения для сверки сохранятся."]}


def preview(store, token, actors, action, journal=None):
    from .admin_statistics import require_admin
    _targets(actors)
    with store._lock:
        administrator = require_admin(store._db, token)
        result = []
        for actor in actors:
            try:
                result.append(_preview(store._db, administrator, actor, action, journal))
            except LookupError as error:
                result.append({"actor": actor, "allowed": False, "blockedReason": str(error)})
        return {"items": result, "retentionPolicy": "not_approved", "irreversibleDeletion": False}


def revoke_timers(db, workspace, *, chats=None):
    """Revoke pending authority in an account or a selected set of its chats.

    Account and business-workshop lifecycle use the same timer invalidation.
    Unknown/in-flight delivery evidence is retained, never marked successful.
    """
    if chats is not None and not chats:
        return
    condition, params = "workspace=?", [workspace]
    if chats is not None:
        condition += " AND chat IN (" + ",".join("?" for _ in chats) + ")"
        params.extend(chats)
    if _exists(db, "timer_events"):
        db.execute("""UPDATE timer_events SET revision=revision+1,next_us=NULL,
            status=CASE WHEN status='active' THEN 'paused' ELSE status END
            WHERE """ + condition, params)
        if _exists(db, "timer_runs"):
            db.execute("""UPDATE timer_runs SET state='cancelled',finished=?,
                message='Разрешение отозвано при отключении аккаунта или мастерской.'
                WHERE state='queued' AND event IN
                (SELECT id FROM timer_events WHERE """ + condition + ")", [int(time()*1_000_000), *params])
    if _exists(db, "timer_drafts"):
        # New-event previews have no accepted event revision; revoke them too.
        db.execute("""UPDATE timer_drafts SET revision=revision+1,receipt=NULL,
            plan=NULL,schedule=NULL,preview=NULL WHERE accepted=0 AND """ + condition, params)
        if _exists(db, "timer_preview_bindings"):
            db.execute("""UPDATE timer_preview_bindings SET expires=0 WHERE draft IN
                (SELECT id FROM timer_drafts WHERE accepted=0 AND """ + condition + ")", params)


def _pause(db, actor, workspace, revision):
    db.execute("DELETE FROM identity_sessions WHERE actor_id=?", (actor,))
    db.execute("DELETE FROM usage_grants WHERE operation_id IN (SELECT operation_id FROM usage_operations WHERE actor_id=?)", (actor,))
    # Preserve reservations for dispatched attempts with unknown provider outcome.
    coins.close_orders(db, workspace)
    for w in _workspaces(db, actor):
        revoke_timers(db, w)
        if _exists(db, "pm_sources"):
            db.execute("UPDATE pm_sources SET enabled=0 WHERE workspace=?", (w,))
        for channel in ("telegram", "marketplace"):
            db.execute("""INSERT INTO account_integration_pauses(workspace,channel,revision,reason) VALUES(?,?,?,?)
                ON CONFLICT(workspace,channel) DO UPDATE SET revision=excluded.revision,reason=excluded.reason""",
                       (w, channel, revision, "account_lifecycle"))
    if _exists(db, "telegram_integration_consents"):
        db.execute("DELETE FROM telegram_integration_consents WHERE workspace=?", (workspace,))


def change(store, token, request_id, items, action, reason, journal=None):
    from .admin_statistics import require_admin
    from .podmasterye_domain import Conflict, key_id
    key_id(request_id)
    if not isinstance(items, list) or any(not isinstance(x, dict) or set(x) != {"actor", "expected"} for x in items):
        raise ValueError("Нужны выбранные аккаунты и проверенные версии предварительного просмотра.")
    _targets([x["actor"] for x in items])
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500 or not reason.isprintable():
        raise ValueError("Укажите причину от 1 до 500 символов.")
    reason = reason.strip()
    if action not in ("block", "archive", "restore", "delete"):
        raise ValueError("Неизвестное действие.")
    payload = json.dumps([items, action, reason], sort_keys=True, separators=(",", ":"))
    with store._write() as db:
        administrator = require_admin(db, token)
        old = db.execute("SELECT payload,result FROM account_lifecycle_requests WHERE operator=? AND request_id=?", (administrator, request_id)).fetchone()
        if old:
            if old[0] != payload:
                raise Conflict("Идентификатор запроса уже использован с другими параметрами.")
            return json.loads(old[1])
        result = []
        for index, item in enumerate(items):
            savepoint = "lifecycle_item_" + str(index)
            db.execute("SAVEPOINT " + savepoint)
            try:
                actor = item["actor"]
                now = _preview(db, administrator, actor, action, journal)
                if not now["allowed"]:
                    raise PermissionError(now["blockedReason"])
                if now["expected"] != item["expected"]:
                    raise Conflict("Состояние аккаунта изменилось. Обновите предварительный просмотр.")
                next_status = {"block": "blocked", "archive": "archived", "restore": "active"}[action]
                revision = now["revision"] + 1
                _, workspace = _account(db, actor)
                db.execute("""INSERT INTO account_lifecycle(actor_id,status,revision,reason) VALUES(?,?,?,?)
                    ON CONFLICT(actor_id) DO UPDATE SET status=excluded.status,revision=excluded.revision,
                    reason=excluded.reason,updated_at=unixepoch()""", (actor, next_status, revision, reason))
                if next_status != "active":
                    _pause(db, actor, workspace, revision)
                db.execute("""INSERT INTO account_lifecycle_audit(operator,actor,action,old_status,new_status,revision,reason,request_id)
                    VALUES(?,?,?,?,?,?,?,?)""", (administrator, actor, action, now["status"], next_status, revision, reason, request_id))
                result.append({"actor": actor, "ok": True, "status": next_status, "revision": revision})
            except (ValueError, PermissionError, LookupError) as error:
                db.execute("ROLLBACK TO " + savepoint)
                result.append({"actor": item["actor"], "ok": False, "error": str(error)})
            finally:
                db.execute("RELEASE " + savepoint)
        response = {"items": result, "changed": sum(x["ok"] for x in result)}
        db.execute("INSERT INTO account_lifecycle_requests(operator,request_id,payload,result) VALUES(?,?,?,?)",
                   (administrator, request_id, payload, json.dumps(response, ensure_ascii=False)))
        return response


def resume_integration(store, token, channel):
    from .identity import _principal
    if channel not in ("telegram", "marketplace"):
        raise ValueError("Неизвестная интеграция.")
    with store._write() as db:
        actor, workspace = _principal(db, token)
        for w in _workspaces(db, actor):
            db.execute("DELETE FROM account_integration_pauses WHERE workspace=? AND channel=?", (w, channel))
        return {"resumed": True, "channel": channel}


def routes(token_for, body):
    async def inspect(request):
        data = await body(request, "actors", "action")
        from .identity import AuthenticationError
        try:
            return JSONResponse(await run_in_threadpool(preview, request.app.state.identity,
                token_for(request, allow_cookie=True), data["actors"], data["action"], request.app.state.worker.journal))
        except AuthenticationError:
            raise
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
    async def mutate(request):
        data = await body(request, "requestId", "items", "action", "reason")
        from .identity import AuthenticationError
        try:
            return JSONResponse(await run_in_threadpool(change, request.app.state.identity,
                token_for(request, allow_cookie=True), data["requestId"], data["items"], data["action"], data["reason"],
                request.app.state.worker.journal))
        except AuthenticationError:
            raise
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
    async def resume(request):
        data = await body(request, "channel")
        return JSONResponse(await run_in_threadpool(resume_integration, request.app.state.identity,
            token_for(request, allow_cookie=True), data["channel"]))
    return [Route("/api/admin/accounts/preview", inspect, methods=["POST"]),
            Route("/api/admin/accounts/lifecycle", mutate, methods=["POST"]),
            Route("/api/account/integrations/resume", resume, methods=["POST"])]
