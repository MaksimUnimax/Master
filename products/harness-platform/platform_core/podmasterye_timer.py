"""Workshop composition of the shared durable timer, local reports and delivery.

HTTP, assistant drafts and background jobs all use the same scoped operations.
The schedule never carries a login token, provider key, SQL or model instruction.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
import json
import time
from uuid import uuid4
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from . import podmasterye_book as book, podmasterye_domain as domain, podmasterye_workshops as workshops
from . import podmasterye_timer_reports as reports
from .storage import Scope
from .identity import AuthenticationError
from .user_plugins.timer import jobs, schedule, store
from .user_plugins.timer.recipe import PlanError

BASE = "/api/chats/{chat_id}/timer"
PREVIEW_SECONDS = 1800
ACTION_SECONDS = 900


def argument_schema(*, assistant=False):
    """Real prepare-handler contract shared with the capability catalog."""
    from .podmasterye_matrix import operation_schema
    props = {"title": {"type": "string", "minLength": 1, "maxLength": 120},
             "schedule": schedule.argument_schema(),
             "channels": {"type": "array", "items": {"type": "string", "enum": ["chat", "telegram"]},
                          "minItems": 1, "maxItems": 2, "uniqueItems": True}}
    key = {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,128}$"}
    if assistant:
        return {"type": "object", "properties": {**props, "report": reports.argument_schema(),
                "eventId": key, "revision": {"type": "integer", "minimum": 1}},
                "required": ["title", "schedule", "channels", "report"], "additionalProperties": False,
                "dependentRequired": {"eventId": ["revision"], "revision": ["eventId"]}}
    definition = {"oneOf": [
        {"type": "object", "properties": {**props, "kind": {"const": "report"}, "report": reports.argument_schema()},
         "required": ["title", "schedule", "report"], "additionalProperties": False},
        {"type": "object", "properties": {**props, "kind": {"const": "action"}, **operation_schema()["properties"]},
         "required": ["title", "kind", "schedule", "operation", "arguments"], "additionalProperties": False},
    ]}
    return {"type": "object", "properties": {"requestId": key, "definition": definition,
            "eventId": key, "revision": {"type": "integer", "minimum": 1}},
            "required": ["requestId", "definition"], "additionalProperties": False,
            "dependentRequired": {"eventId": ["revision"], "revision": ["eventId"]}}


TABLES = (
    """CREATE TABLE IF NOT EXISTS timer_composition(
        id INTEGER PRIMARY KEY CHECK(id=1), access TEXT NOT NULL CHECK(access IN ('builtin','plugin')))""",
    """CREATE TABLE IF NOT EXISTS timer_workshop_bindings(
        event TEXT PRIMARY KEY REFERENCES timer_events(id) ON DELETE CASCADE,
        workshop TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS timer_preview_bindings(
        draft TEXT PRIMARY KEY REFERENCES timer_drafts(id) ON DELETE CASCADE,
        workshop TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
        expires INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS timer_control_requests(
        workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT NOT NULL,
        PRIMARY KEY(workspace,request_id))""",
)


def initialize(db):
    from .schema_migrations import apply
    jobs.initialize(db)
    apply(db, "20261127_workshop_timer_v1", statements=TABLES)
    apply(db, "20261127_timer_admin_v1", statements=("""CREATE TABLE IF NOT EXISTS timer_admin_actions(
        operator TEXT NOT NULL, request_id TEXT NOT NULL, event TEXT NOT NULL, revision INTEGER NOT NULL,
        payload TEXT NOT NULL, created INTEGER NOT NULL DEFAULT(unixepoch()), PRIMARY KEY(operator,request_id))""",))
    db.execute("INSERT INTO timer_composition VALUES(1,'builtin') ON CONFLICT(id) DO UPDATE SET access=excluded.access")


def authorized(db, scope, capability="timer.manage"):
    from .account_lifecycle import assert_workspace_active
    from .capability_registry import require
    assert_workspace_active(db, scope.workspace_id)
    require(db, scope, capability)
    return workshops.chat_workspace(db, scope)


def definition(raw):
    if not isinstance(raw, dict) or set(raw) - {"title", "kind", "schedule", "channels", "report", "operation", "arguments"}:
        raise ValueError("Проверьте поля поручения.")
    title = domain.clean_name(raw.get("title"))
    kind = raw.get("kind", "report")
    if kind not in ("report", "action"):
        raise ValueError("Выберите отчёт или хозяйственное действие.")
    rule = raw.get("schedule")
    schedule.validate(rule)
    channels = raw.get("channels", ["chat"])
    if (not isinstance(channels, list) or not channels or any(not isinstance(c,str) for c in channels)
            or len(channels) != len(set(channels)) or set(channels) - {"chat", "telegram"}):
        raise ValueError("Выберите основной чат, Telegram или оба канала.")
    plan = {"type": "workshop", "channels": sorted(channels), "telegram": "telegram" in channels,
            "notify": "all", "steps": [{"tool": "accounting_report", "args": {}}]}
    if kind == "report":
        if "operation" in raw or "arguments" in raw:
            raise ValueError("Отчёт не выполняет хозяйственное действие.")
        plan["report"] = reports.validate(raw.get("report"))
    else:
        if "report" in raw:
            raise ValueError("Проверьте поля хозяйственного действия.")
        op = raw.get("operation")
        if not isinstance(op,str) or op not in book.FIELDS:
            raise ValueError("Для этого действия нет принятого хозяйственного обработчика.")
        plan["operation"], plan["arguments"] = op, book.validate(op, raw.get("arguments"))
        plan["confirmation"] = "each_occurrence"
    return title, kind, rule, plan


def replay(db, scope, request_id, arguments):
    domain.key_id(request_id)
    encoded = domain.encode(arguments)
    row = db.execute("SELECT arguments,result FROM timer_control_requests WHERE workspace=? AND request_id=?", (scope.workspace_id, request_id)).fetchone()
    if row:
        if row[0] != encoded:
            raise HTTPException(409, "Этот идентификатор запроса уже использован с другими параметрами.")
        return json.loads(row[1])
    return None


def record_request(db, scope, request_id, arguments, result):
    db.execute("INSERT INTO timer_control_requests VALUES(?,?,?,?)", (scope.workspace_id, request_id, domain.encode(arguments), domain.encode(result)))
    return result


def draft_view(row):
    return {"id": row["id"], "kind": row["kind"], "revision": row["revision"], "title": row["instructions"][-1],
            "eventId": row["target"], "preview": row["preview"], "receipt": row["receipt"],
            "schedule": row["schedule"], "plan": row["plan"], "accepted": bool(row["accepted"])}


def event_view(row):
    return {"id": row["id"], "kind": row["kind"], "revision": row["revision"], "title": row["instructions"][-1],
            "schedule": row["schedule"], "plan": row["plan"],
            "status": "cancelled" if row.get("cancelled") else row["status"],
            "nextAt": schedule.timestamp(row["next_us"]).isoformat() if row["next_us"] is not None else None}


def prepare(db, scope, request_id, raw, event_id=None, expected_revision=None, *, now=None):
    workshop = authorized(db, scope)
    arguments = ["prepare", scope.chat_id, raw, event_id, expected_revision]
    prior = replay(db, scope, request_id, arguments)
    if prior is not None:
        return prior
    title, kind, rule, plan = definition(raw)
    now = int(time.time()) if now is None else now
    local_day = schedule.timestamp(now * 1_000_000).astimezone(__import__("zoneinfo").ZoneInfo(rule["zone"])).date()
    if event_id is not None:
        domain.key_id(event_id)
        if type(expected_revision) is not int or expected_revision<1:
            raise ValueError("Нужна актуальная версия поручения.")
        current = store.event(db, scope, event_id)
        if current.get("cancelled") or current["revision"] != expected_revision:
            raise HTTPException(409, "Поручение изменилось. Откройте актуальную версию.")
        if current["kind"] != kind:
            raise ValueError("Для другого типа создайте отдельное поручение.")
    elif expected_revision is not None:
        raise ValueError("Для нового поручения версия не указывается.")
    if schedule.next_after(rule, now * 1_000_000, now * 1_000_000) is None:
        raise ValueError("Время разового поручения уже прошло.")
    if kind == "report":
        sample = reports.build(db, workshop, plan["report"], local_day)
        preview = reports.render(sample)
    else:
        authorized(db, scope, "accounting.write")
        sample = book.preview_action(db, workshop, plan["operation"], plan["arguments"])
        preview = "В назначенное время подготовлю действие «" + book.FIELDS[plan["operation"]][0] + "».\n" + str(sample["preview"].get("summary", ""))
        preview += "\nПеред каждым исполнением потребуется ваше подтверждение актуальных данных. До подтверждения учёт не меняется."
    key = hashlib.sha256((scope.workspace_id + ":" + request_id).encode()).hexdigest()[:32]
    draft = store.start(db, scope, kind, title, event_id, request_id=key)
    receipt = store.record_preview(db, scope, key, draft["revision"], rule, plan, preview)
    db.execute("INSERT INTO timer_preview_bindings VALUES(?,?,?)", (key, workshop, now + PREVIEW_SECONDS))
    return record_request(db, scope, request_id, arguments, {**draft_view(store.draft(db, scope, key)), "receipt": receipt,
                          "expiresAt": now + PREVIEW_SECONDS, "costCoins": "0"})


def confirm(db, scope, request_id, draft_id, revision, receipt, *, now=None):
    workshop = authorized(db, scope)
    domain.key_id(draft_id)
    arguments = ["confirm", scope.chat_id, draft_id, revision, receipt]
    prior = replay(db, scope, request_id, arguments)
    if prior is not None:
        return prior
    now = int(time.time()) if now is None else now
    draft = store.draft(db, scope, draft_id)
    binding = db.execute("SELECT workshop,expires FROM timer_preview_bindings WHERE draft=?", (draft_id,)).fetchone()
    if not binding or binding[0] != workshop or (not draft["accepted"] and binding[1] <= now):
        raise HTTPException(409, "Предпросмотр устарел. Проверьте поручение заново.")
    if draft["kind"] == "action":
        authorized(db, scope, "accounting.write")
    if draft["target"]:
        original=store.event(db,scope,draft["target"])
        if original["status"]=="completed":
            # Saving a newly checked date deliberately rearms a completed event.
            # Editing an explicitly paused event still preserves its pause.
            db.execute("UPDATE timer_events SET status='active' WHERE id=? AND revision=?",(original["id"],draft["base_revision"]))
    event = store.confirm(db, scope, draft_id, revision, receipt, now_us=now * 1_000_000)
    db.execute("UPDATE timer_events SET domain='workshop' WHERE id=?", (event["id"],))
    db.execute("INSERT INTO timer_workshop_bindings VALUES(?,?) ON CONFLICT(event) DO UPDATE SET workshop=excluded.workshop", (event["id"], workshop))
    return record_request(db, scope, request_id, arguments, event_view(store.event(db, scope, event["id"])))


def cancel_draft(db,scope,request_id,draft_id,revision):
    authorized(db,scope)
    domain.key_id(draft_id)
    args=["cancel_draft",scope.chat_id,draft_id,revision]
    old=replay(db,scope,request_id,args)
    if old is not None:return old
    store.cancel(db,scope,draft_id,revision)
    return record_request(db,scope,request_id,args,{"cancelled":True})


def listing(db, scope, before=None, limit=50):
    authorized(db, scope)
    if type(limit) is not int or not 1 <= limit <= 100 or (before is not None and (type(before) is not int or not 0 < before < 2**63)):
        raise ValueError("Некорректная страница таймеров.")
    rows, cursor = store.list_events(db, scope, before=before, page_size=limit)
    events = [event_view(store.event(db, scope, row["id"])) for row in rows]
    ids = db.execute("""SELECT d.id FROM timer_drafts d JOIN timer_preview_bindings p ON p.draft=d.id
        WHERE d.workspace=? AND d.chat=? AND d.accepted=0 AND d.receipt IS NOT NULL
        AND p.expires>unixepoch() ORDER BY d.rowid DESC LIMIT 50""", (scope.workspace_id, scope.chat_id)).fetchall()
    drafts = [draft_view(store.draft(db, scope, row[0])) for row in ids]
    return {"events": events, "nextCursor": cursor, "drafts": drafts, "reports": reports.catalog(),
            "policies": {"missed": "one_then_next_future", "missingMonthDay": "skip", "dstGap": "skip", "dstFold": "first"}}


def control(db, scope, request_id, event_id, operation, revision, *, now=None):
    authorized(db, scope)
    domain.key_id(event_id)
    if type(revision) is not int or revision<1:
        raise ValueError("Нужна актуальная версия поручения.")
    arguments = ["control", scope.chat_id, event_id, operation, revision]
    prior = replay(db, scope, request_id, arguments)
    if prior is not None:
        return prior
    event = store.event(db, scope, event_id)
    if event["revision"] != revision or event.get("cancelled"):
        raise HTTPException(409, "Поручение изменилось. Откройте актуальную версию.")
    now = jobs.now_us() if now is None else now
    if operation == "run":
        # The request key owns this manual occurrence even if a retry arrives later.
        run = uuid4().hex
        while db.execute("SELECT 1 FROM timer_runs WHERE event=? AND revision=? AND due=?", (event_id, revision, now)).fetchone():
            now += 1
        db.execute("INSERT INTO timer_runs(id,event,revision,due,state,manual) VALUES(?,?,?,?,'queued',1)", (run,event_id,revision,now))
        result = {"runId": run, "state": "queued"}
    elif operation == "cancel":
        db.execute("UPDATE timer_events SET cancelled=1,status='paused',next_us=NULL,revision=revision+1 WHERE id=?", (event_id,))
        db.execute("UPDATE timer_runs SET state='cancelled',finished=? WHERE event=? AND state='queued'", (now,event_id))
        result = event_view(store.event(db,scope,event_id))
    elif operation in ("pause", "resume"):
        if operation == "resume" and event["status"] == "completed":
            raise HTTPException(409, "Разовое поручение завершено. Для новой даты отредактируйте его.")
        store.change_status(db,scope,event_id,operation,now_us=now)
        # Pausing revokes every previously issued occurrence and action proposal.
        if operation == "pause" and event["status"] == "active":
            db.execute("UPDATE timer_events SET revision=revision+1 WHERE id=?", (event_id,))
            db.execute("UPDATE timer_runs SET state='cancelled',finished=? WHERE event=? AND state='queued'", (now,event_id))
        result = event_view(store.event(db,scope,event_id))
    else:
        raise ValueError("Неизвестное действие с таймером.")
    return record_request(db,scope,request_id,arguments,result)


def history(db, scope, event_id, before=None, limit=50):
    authorized(db,scope)
    event=store.event(db,scope,event_id)
    if type(limit) is not int or not 1 <= limit <= 100 or (before is not None and (type(before) is not int or not 0 < before < 2**63)):
        raise ValueError("Некорректная страница истории.")
    cursor = db.execute("""SELECT rowid,id,revision,due,started,finished,state,outcome,message,chat_delivery,
        telegram_delivery,result,manual,attempts FROM timer_runs WHERE event=? AND (? IS NULL OR rowid<?)
        ORDER BY rowid DESC LIMIT ?""", (event_id,before,before,limit+1))
    keys = [c[0] for c in cursor.description]
    rows = [dict(zip(keys,r)) for r in cursor]
    next_cursor = rows[limit-1]["rowid"] if len(rows)>limit else None
    for row in rows:
        row["result"] = json.loads(row["result"]) if row["result"] else None
    return {"event":event_view(event),"runs": rows[:limit], "nextCursor": next_cursor}


def run_owned(db, scope, run):
    authorized(db,scope)
    row = db.execute("""SELECT r.event,r.revision,r.result,r.state,r.telegram_delivery,r.chat_delivery
        FROM timer_runs r JOIN timer_events e ON e.id=r.event
        WHERE r.id=? AND e.workspace=? AND e.chat=?""", (run,scope.workspace_id,scope.chat_id)).fetchone()
    if row is None:
        raise HTTPException(404,"Результат недоступен.")
    return row


def retry_delivery(db,scope,request_id,run,channel):
    authorized(db,scope)
    arguments=["retry",scope.chat_id,run,channel]
    old=replay(db,scope,request_id,arguments)
    if old is not None:
        return old
    row=run_owned(db,scope,run)
    Runtime.authorize_delivery_db(db,scope,run)
    if channel not in ("chat","telegram"):
        raise ValueError("Выберите канал доставки.")
    status=row[4] if channel=="telegram" else row[5]
    if status=="unknown" or status=="sending":
        raise HTTPException(409,"Исход отправки неизвестен. Автоматический повтор запрещён, чтобы не отправить дубликат.")
    if status not in ("failed","disconnected","blocked","rejected"):
        raise HTTPException(409,"Для этой доставки повтор не требуется или разрешение отозвано.")
    db.execute("UPDATE timer_runs SET "+channel+"_delivery='pending',"+channel+"_attempts=0,retry_at=0 WHERE id=?", (run,))
    return record_request(db,scope,request_id,arguments,{"runId":run,"channel":channel,"state":"pending"})


class Runtime:
    def __init__(self,state):
        self.state=state

    @staticmethod
    def authorize(db,scope,event):
        workshop=authorized(db,scope,"timer.run")
        binding=db.execute("SELECT workshop FROM timer_workshop_bindings WHERE event=?", (event["id"],)).fetchone()
        if event.get("cancelled") or event.get("domain")!="workshop" or not binding or binding[0]!=workshop:
            raise PermissionError("Поручение недоступно в этой мастерской.")
        return workshop

    @staticmethod
    def authorize_delivery_db(db,scope,run):
        row=db.execute("SELECT event,revision,manual FROM timer_runs WHERE id=?",(run,)).fetchone()
        if row is None:
            raise PermissionError("Результат недоступен.")
        event=store.event(db,scope,row[0])
        if event.get("cancelled") or event["revision"]!=row[1] or (event["status"]=="paused" and not row[2]):
            raise HTTPException(409,"Поручение изменено или поставлено на паузу. Запустите актуальную проверку.")
        Runtime.authorize(db,scope,event)

    def authorize_delivery(self,db,scope,run):
        self.authorize_delivery_db(db,scope,run)

    async def execute_event(self,scope,event,run,due):
        def local():
            with self.state.identity._write() as db:
                workshop=self.authorize(db,scope,event)
                plan=event["plan"]
                if event["kind"]=="report":
                    from zoneinfo import ZoneInfo
                    authorized(db,scope,"reports.read")
                    day=schedule.timestamp(due).astimezone(ZoneInfo(event["schedule"]["zone"])).date()
                    result=reports.build(db,workshop,plan["report"],day)
                    return {"outcome":"report","message":reports.render(result),"report":result}
                authorized(db,scope,"accounting.write")
                proposal=book.preview_action(db,workshop,plan["operation"],plan["arguments"])
                proposal.update(expiresAt=int(time.time())+ACTION_SECONDS,requestId="timer-action-"+run)
                message="Подготовлено действие «"+book.FIELDS[plan["operation"]][0]+"».\n"+str(proposal["preview"].get("summary",""))
                message+="\nОткройте историю таймера и подтвердите актуальные данные. Пока учёт не изменён."
                return {"outcome":"awaiting_confirmation","message":message,"proposal":proposal}
        return await run_in_threadpool(local)

    async def publish(self,scope,run,text):
        with self.state.identity._lock:
            self.authorize_delivery(self.state.identity._db,scope,run)
        # The native transcript owns context. The existing pm_turns table is its
        # product projection, just as for ordinary local and model exchanges.
        result=await self.state.worker.request(scope,"timerExchange",requestId="timer_"+run,text="",answer=text)
        with self.state.identity._write() as db:
            self.authorize_delivery(db,scope,run)
            value={**result,"role":"assistant","text":text,"requestId":"timer_"+run,"route":"local","system":True}
            db.execute("""INSERT OR IGNORE INTO pm_turns(workspace,chat,rid,text,route,result,created)
                VALUES(?,?,?,'','local',?,?)""", (scope.workspace_id,scope.chat_id,"timer_"+run,domain.encode(value),int(time.time()*1000)))


def confirm_action(identity,token,scope,run):
    """Use the existing accounting command. A timed action has no alternate writer."""
    with identity._write() as db:
        domain.assert_scope(db,token,scope)
        row=run_owned(db,scope,run)
        Runtime.authorize_delivery_db(db,scope,run)
        value=json.loads(row[2]) if row[2] else {}
        if value.get("outcome")=="changed":
            return value
        if value.get("outcome")!="awaiting_confirmation" or row[3]!="done":
            raise HTTPException(409,"Это действие не ожидает подтверждения.")
        proposal=value["proposal"]
        if proposal["expiresAt"]<=int(time.time()):
            raise HTTPException(409,"Предложение устарело. Запустите новую проверку.")
        authorized(db,scope,"accounting.write")
        result=book.commit_action(db,proposal["workshop"],proposal["requestId"],proposal["operation"],
                                 proposal["arguments"],proposal["revision"])
        # Ledger effect and receipt are atomic in the same existing identity DB.
        value={**value,"outcome":"changed","actionResult":result,"message":result.get("summary","Действие выполнено.")}
        db.execute("UPDATE timer_runs SET outcome='changed',message=?,result=? WHERE id=?",(value["message"],domain.encode(value),run))
        return value


@asynccontextmanager
async def activate(state):
    with state.identity._write() as db:
        initialize(db)
    state.timer=jobs.Scheduler(state,Runtime(state))
    try:
        yield state.timer
    finally:
        await state.timer.close()


def routes(token_for,body):
    async def endpoint(req,action):
        token=token_for(req,allow_cookie=True)
        identity=req.app.state.identity
        scope=await run_in_threadpool(identity.resolve_chat,token,req.path_params["chat_id"])
        fields={}
        if action=="prepare":
            fields=await body(req,"requestId","definition",optional=("eventId","revision"))
        elif action=="confirm":
            fields=await body(req,"requestId","draftId","revision","receipt")
        elif action=="control":
            fields=await body(req,"requestId","operation","revision")
        elif action=="cancel_draft":
            fields=await body(req,"requestId","revision")
        elif action=="retry":
            fields=await body(req,"requestId","channel")
        elif action=="confirm_action":
            await body(req)
            result=await run_in_threadpool(confirm_action,identity,token,scope,req.path_params["run"])
            return JSONResponse(result)
        def operation():
            with identity._write() if req.method=="POST" else identity._lock:
                db=identity._db
                domain.assert_scope(db,token,scope)
                if action=="list":
                    before=int(req.query_params["before"]) if req.query_params.get("before") else None
                    value=listing(db,scope,before)
                    value["telegram"]=req.app.state.telegram.status(db,scope.workspace_id)
                    return value
                if action=="history":
                    before=int(req.query_params["before"]) if req.query_params.get("before") else None
                    return history(db,scope,req.path_params["event"],before)
                if action=="prepare":
                    return prepare(db,scope,fields["requestId"],fields["definition"],fields.get("eventId"),fields.get("revision"))
                if action=="confirm":
                    return confirm(db,scope,fields["requestId"],fields["draftId"],fields["revision"],fields["receipt"])
                if action=="control":
                    return control(db,scope,fields["requestId"],req.path_params["event"],fields["operation"],fields["revision"])
                if action=="cancel_draft":
                    return cancel_draft(db,scope,fields["requestId"],req.path_params["draft"],fields["revision"])
                if action=="retry":
                    return retry_delivery(db,scope,fields["requestId"],req.path_params["run"],fields["channel"])
                if action=="download":
                    row=run_owned(db,scope,req.path_params["run"])
                    return json.loads(row[2]) if row[2] else {"state":row[3]}
                raise ValueError("Неизвестная операция.")
        result=await run_in_threadpool(operation)
        if req.method=="POST" and hasattr(req.app.state,"timer"):
            req.app.state.timer.wake.set()
        headers={"Content-Disposition":"attachment; filename=workshop-timer-report.json"} if action=="download" else None
        return JSONResponse(result,headers=headers)
    def route(path,action,method="GET"):
        async def handle(req):
            try:
                return await endpoint(req,action)
            except AuthenticationError:
                raise
            except PermissionError as exc:
                raise HTTPException(403,str(exc)) from None
        return Route(BASE+path,handle,methods=[method])
    return [route("","list"),route("/preview","prepare","POST"),route("/confirm","confirm","POST"),
            route("/events/{event}","control","POST"),route("/events/{event}/history","history"),
            route("/drafts/{draft}/cancel","cancel_draft","POST"),
            route("/runs/{run}/retry","retry","POST"),route("/runs/{run}/confirm","confirm_action","POST"),
            route("/runs/{run}/report.json","download")]


def admin_routes(token_for,body):
    """Operational metadata only. Administrators do not read private reports here."""
    from .admin_statistics import require_admin
    from .identity import AuthenticationError
    def admin(db,token):
        try:return require_admin(db,token)
        except AuthenticationError:raise
        except PermissionError:raise HTTPException(403,"Требуются права администратора.") from None
    async def overview(req):
        token=token_for(req,allow_cookie=True);identity=req.app.state.identity
        limit=int(req.query_params.get("limit","20"));page=int(req.query_params.get("page","1"))
        if limit not in (10,20,50,100) or page<1:raise ValueError("Некорректная страница.")
        def read():
            with identity._lock:
                db=identity._db;admin(db,token)
                counts={state:n for state,n in db.execute("SELECT state,COUNT(*) FROM timer_runs GROUP BY state")}
                total=db.execute("SELECT COUNT(*) FROM timer_events").fetchone()[0]
                rows=db.execute("""SELECT e.id,a.login,e.revision,e.status,e.cancelled,e.next_us,
                    (SELECT r.outcome FROM timer_runs r WHERE r.event=e.id ORDER BY r.rowid DESC LIMIT 1),
                    (SELECT r.telegram_delivery FROM timer_runs r WHERE r.event=e.id ORDER BY r.rowid DESC LIMIT 1)
                    FROM timer_events e JOIN identity_accounts a ON a.workspace_id=e.workspace
                    ORDER BY e.rowid DESC LIMIT ? OFFSET ?""",(limit,(page-1)*limit)).fetchall()
                return {"counts":counts,"total":total,"page":page,"limit":limit,"events":[dict(id=r[0],login=r[1],revision=r[2],
                        status="cancelled" if r[4] else r[3],nextAt=schedule.timestamp(r[5]).isoformat() if r[5] else None,
                        lastOutcome=r[6],telegramDelivery=r[7]) for r in rows]}
        return JSONResponse(await run_in_threadpool(read))
    async def pause(req):
        token=token_for(req,allow_cookie=True);fields=await body(req,"requestId","eventId","revision")
        def change():
            with req.app.state.identity._write() as db:
                actor=admin(db,token);domain.key_id(fields["requestId"])
                domain.key_id(fields["eventId"])
                if type(fields["revision"]) is not int or fields["revision"] < 1:
                    raise ValueError("Нужна актуальная версия поручения.")
                payload=domain.encode(fields)
                old=db.execute("SELECT payload FROM timer_admin_actions WHERE operator=? AND request_id=?",(actor,fields["requestId"])).fetchone()
                if old:
                    if old[0]!=payload:raise HTTPException(409,"Этот запрос уже использован.")
                    return {"paused":True}
                row=db.execute("SELECT revision,cancelled FROM timer_events WHERE id=?",(fields["eventId"],)).fetchone()
                if not row:raise HTTPException(404,"Поручение не найдено.")
                if row[0]!=fields["revision"] or row[1]:raise HTTPException(409,"Поручение изменилось.")
                db.execute("UPDATE timer_events SET status='paused',next_us=NULL,revision=revision+1 WHERE id=?",(fields["eventId"],))
                db.execute("UPDATE timer_runs SET state='cancelled',finished=? WHERE event=? AND state='queued'",(jobs.now_us(),fields["eventId"]))
                db.execute("INSERT INTO timer_admin_actions(operator,request_id,event,revision,payload) VALUES(?,?,?,?,?)",(actor,fields["requestId"],fields["eventId"],fields["revision"],payload))
                return {"paused":True}
        return JSONResponse(await run_in_threadpool(change))
    return [Route("/api/admin/timer",overview),Route("/api/admin/timer/pause",pause,methods=["POST"])]


def assistant_capabilities(context):
    """Mount in ProductionTools after its normal grant/session authorization.

The assistant can prepare a schedule; only the existing owner UI confirms it.
"""
    from .catalog import Capability
    def list_timers(scope,args):
        with context.store._lock:
            context.authorize(context.store._db)
            return listing(context.store._db,scope)
    def preview_timer(scope,args):
        with context.store._write() as db:
            context.authorize(db)
            raw={"title":args["title"],"kind":"report","schedule":args["schedule"],"channels":args["channels"],"report":args["report"]}
            key="agent-timer-"+hashlib.sha256(domain.encode([context.request,args]).encode()).hexdigest()
            return prepare(db,scope,key,raw,args.get("eventId"),args.get("revision"))
    return {
        "timer_list":Capability("timer_list","Показать встроенные таймеры, историю настройки и доступные бесплатные хозяйственные отчёты.",
            {"type":"object","properties":{},"additionalProperties":False},list_timers),
        "timer_prepare":Capability("timer_prepare","Подготовить бесплатный отчёт по расписанию и локальный предпросмотр. Укажи явно согласованные время, часовой пояс, период и каналы. Пользователь сохраняет последний предпросмотр в разделе «Таймер»; инструмент не активирует отправки.",
            argument_schema(assistant=True),preview_timer,effect="edit"),
    }
