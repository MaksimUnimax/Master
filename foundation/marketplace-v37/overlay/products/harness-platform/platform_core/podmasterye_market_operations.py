"""Typed user operations shared by the cabinet, local grammar and MCP.

This is an adapter registry, not another collector or calculation engine. The
caller resolves the authenticated workshop before dispatch. Credentials never
belong to this registry: their write-only route delegates to MarketLinks.Store.
"""
from copy import deepcopy
from datetime import date
from functools import partial
import hashlib
import json
import csv
import io
import zipfile

from jsonschema import Draft202012Validator
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import podmasterye_domain as domain, podmasterye_workshops as workshops
from .identity import _principal

VERSION = "marketplace-user-v1"
SOURCE = {"type": "string", "pattern": r"^[A-Za-z0-9_:-]{1,160}$", "default": "all_marketplaces"}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 160, "pattern": r"^[A-Za-z0-9_:-]+$"}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
PAGE = {"offset": {"type": "integer", "minimum": 0, "maximum": 1000000, "default": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}}
FORECAST_SCHEMA = {"type":"object","properties":{"source":SOURCE,"history_from":{"type":"string","pattern":r"^\d{4}-\d{2}$"},"history_to":{"type":"string","pattern":r"^\d{4}-\d{2}$"},"target_from":{"type":"string","pattern":r"^\d{4}-\d{2}$"},"growth":{"type":"integer","minimum":-100,"maximum":1000},"reserve":{"type":"integer","minimum":0,"maximum":100},"lead":{"type":"integer","minimum":0,"maximum":365},"include_wip":{"type":"boolean"},"accept_no_data":{"type":"boolean"},"accept_empty_ledger":{"type":"boolean"},"metric":{"type":"string","enum":["net","delivered"]},"detail_month":{"type":"string"},**PAGE},"required":["source","history_from","history_to","target_from"],"additionalProperties":False}
STATE_LABELS = {
    "ready": "Данные готовы", "complete": "Данные готовы", "completed": "Данные готовы",
    "collecting": "Собираем данные", "running": "Собираем данные", "queued": "В очереди",
    "pending": "В очереди", "rate_limited": "Площадка ограничила частоту запросов",
    "waiting_retry": "Ожидаем допустимого времени повтора", "deferred": "Повтор отложен",
    "waiting_for_provider": "Ожидаем восстановления площадки", "partial": "Данные неполные",
    "denied": "Нет необходимого доступа", "uncertain": "Результат запроса не подтверждён",
    "needs_attention": "Требуется проверка", "stopped": "Сбор остановлен", "cancelled": "Сбор остановлен",
    "no_data_confirmed": "Отсутствие данных подтверждено", "zero": "Отсутствие данных подтверждено",
    "not_collected": "История ещё не собрана", "error": "Не удалось завершить сбор", "failed": "Не удалось завершить сбор",
}

def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}

def _entry(name, description, inputs, effect="read", *, handler=None, ui=None):
    return {"stable_id": name, "version": VERSION, "kind": "user_operation", "description": description,
        "model_description": description, "input_schema": inputs, "output_schema": {"type": "object"},
        "required_scope": "workshop.owner", "role": "owner", "effect": effect,
        "store_binding": "authenticated_workshop_and_verified_store", "handler": handler or name,
        "bindings": {"ui": ui or "marketplace-workspace", "local_matrix": name, "mcp": name},
        "source": "docs/MARKETPLACE_FULL_SPEC_RU.md", "verified_at": "2026-11-28",
        "error_policy": {"validation": "reject_without_effect", "permission": "deny_without_disclosure",
            "conflict": "refresh_and_prepare_again", "provider": "show_durable_job_state_without_http",
            "unknown": "fail_closed"},
        "progress_policy": {"authority": "market_collect", "identity": "shared_job_id",
            "cooldown": "preserve_next_retry_at", "cancel": "stop_new_requests", "snapshot": "last_complete_preserved",
            "local_operation": True, "model_calls": 0},
        "tests": {"contract": "tests/test_market_dual_contract.py", "dual_control": "tests/test_market_dual_contract.py"}}

REGISTRY = {
    "market_sales": _entry("market_sales", "Количества заказов, доставок, отмен и физических возвратов из локальной БД. Факт и прогноз раздельно; покрытие и несвязанные артикулы видны.",
        schema({"from": DATE, "to": DATE, "source": SOURCE, "product": IDENTIFIER,
                "group_by": {"type": "string", "enum": ["product", "marketplace", "day", "month"], "default": "product"}, **PAGE}, ("from", "to"))),
    "market_loss_rates": _entry("market_loss_rates", "Коэффициенты потерь по зрелой истории: числитель, знаменатель, период, покрытие и уровень товар/категория/магазин. Не вычисляет проценты моделью.",
        schema({"source": SOURCE, "product": IDENTIFIER, **PAGE})),
    "market_sync_status": _entry("market_sync_status", "Состояние подключённых магазинов, задач, покрытие истории, пропуски и время следующей попытки. Читает локальную БД без запросов к площадке.",
        schema({"source": SOURCE, "job_id": IDENTIFIER})),
    "market_sync_request": _entry("market_sync_request", "Поставить обновление или заполнение истории в общую очередь. Повтор использует существующую задачу и не обходит лимит площадки.",
        schema({"source": SOURCE, "from": DATE, "to": DATE, "refresh":{"type":"boolean","default":False}}), "edit"),
    "market_sync_control": _entry("market_sync_control", "Остановить, продолжить или повторить одну существующую задачу сбора по её ID. Сохраняет курсор и срок допустимого повтора.",
        schema({"job_id": IDENTIFIER, "action": {"type": "string", "enum": ["cancel", "resume", "retry"]}}, ("job_id", "action")), "edit"),
    "market_catalog": _entry("market_catalog", "Каталог площадок и явные связи артикулов с изделиями мастерской. Можно показать только несвязанные артикулы; пагинация не меняет общий итог.",
        schema({"source": SOURCE, "unmapped_only": {"type": "boolean", "default": False}, "search":{"type":"string","maxLength":160}, **PAGE})),
    "market_mapping": _entry("market_mapping", "Подготовить явную привязку артикула к изделию; product=null удаляет связь. Возвращает проверяемое подтверждение, не угадывает изделие.",
        schema({"source": SOURCE, "sku": {"type": "string", "minLength": 1, "maxLength": 240},
                "product": {"type": ["string", "null"], "maxLength": 160}}, ("source", "sku", "product")), "edit"),
    "market_connection": _entry("market_connection", "Показать подключения или защищённую карточку подключения, смены ключа, проверки либо отключения прямо в чате. Никогда не проси ключ текстом и не передавай его в инструмент.",
        schema({"action": {"type": "string", "enum": ["list", "connect", "rotate", "verify", "disconnect"], "default": "list"},
                "provider": {"type": "string", "enum": ["ozon", "wb", "yandex_market"]}, "connection_id": IDENTIFIER})),
}

EXPORTABLE = ("market_sales", "market_loss_rates", "market_catalog", "material_forecast", "accounting_report")
EXPORT_ARGS = {**FORECAST_SCHEMA["properties"], "from": DATE, "to": DATE, "start": DATE, "end": DATE,
    "product": IDENTIFIER, "group_by": {"type":"string","enum":["product","marketplace","day","month"]},
    "unmapped_only": {"type":"boolean"}, "search":{"type":"string","maxLength":160}, "view":{"type":"string","enum":["summary","stock","sales","planning","finance","journal","tasks","workers","unit","catalog","assets"]},
    "horizon":{"type":"integer","minimum":1,"maximum":365},"safety":{"type":"integer","minimum":0,"maximum":365},"target_profit":{"type":"string","maxLength":40}}
REGISTRY["market_export"] = _entry("market_export", "Выгрузить локальный количественный отчёт или план закупок в ZIP с JSON, CSV и контрольными суммами. Карточка скачивания доступна прямо в чате, модель не создаёт расчёты.",
    schema({"operation":{"type":"string","enum":list(EXPORTABLE)},"arguments":schema(EXPORT_ARGS)},("operation","arguments")))

def _output(properties, required):
    # Metadata may grow with the authoritative handler. Required data and all
    # declared quantities remain typed; malformed results never become zeroes.
    return {"type":"object","properties":properties,"required":list(required),"additionalProperties":True}

_COUNT={"type":"integer","minimum":0}
_STATE={"type":"string","enum":list(dict.fromkeys([*STATE_LABELS,"no_data","unknown","confirmation_required"]))}
_ROW=_output({key:{"type":["integer","string","null"]} for key in (
    "ordered","delivered","cancelled","nonbuyout","physical_returns","calendar_returns","losses","net",
    "estimated_net","estimated_delivered","estimated_losses","estimated_physical_returns","numerator","denominator")},())
_ROWS={"type":"array","items":_ROW}
_PROGRESS=_output({"total":_COUNT,"complete":_COUNT,"states":{"type":"object","additionalProperties":_COUNT}},())
_JOB=_output({"id":IDENTIFIER,"job_id":IDENTIFIER,"state":_STATE,"progress":_PROGRESS,
    "next_retry_at":{"type":["number","null"]},"message":{"type":"string"}},("id","job_id","state","progress"))
_STATUS=_output({"state":_STATE,"job_id":IDENTIFIER,"jobs":{"type":"array","items":_JOB},
    "groups":{"type":"array","items":_JOB},"stores":{"type":"array","items":{"type":"object"}},
    "coverage":{"type":"array","items":{"type":"object"}},"progress":_PROGRESS},("state",))
_STATUS["anyOf"]=[{"required":["job_id","progress"]},{"required":["jobs","groups","stores","coverage"]}]
_GROUP=_output(_STATUS["properties"],("job_id","state","jobs","progress"))
_REPORT=_output({"status":_STATE,"rows":_ROWS,"total":_COUNT,"offset":_COUNT,"limit":_COUNT,
    "totals":_ROW,"coverage":{"type":"array","items":{"type":"object"}},
    "complete":{"type":"boolean"},"forecast_complete":{"type":"boolean"},"stale":{"type":"boolean"},
    "external_calls":{"const":0},"model_calls":{"const":0}},
    ("status","rows","total","offset","limit","totals","coverage","external_calls","model_calls"))
_RATE_REPORT=_output({**_REPORT["properties"],"known_rates":_COUNT,"unknown_rates":_COUNT},
    ("status","rows","total","offset","limit","known_rates","unknown_rates","external_calls","model_calls"))
_CATALOG_ROW=_output({"sku":{"type":"string"},"store_id":IDENTIFIER,"provider":{"enum":["ozon","wb","yandex_market"]},
    "connection_id":IDENTIFIER,"product_id":{"type":["string","null"]}},("sku","store_id","provider","connection_id","product_id"))
_CATALOG=_output({"state":_STATE,"rows":{"type":"array","items":_CATALOG_ROW},"total":_COUNT,"offset":_COUNT,"limit":_COUNT,"has_more":{"type":"boolean"}},
    ("state","rows","total","offset","limit","has_more"))
_CONNECTION_CARD=_output({"kind":{"const":"connection"},"action":{"enum":["list","connect","rotate","verify","disconnect"]},
    "workshop":IDENTIFIER,"connections":{"type":"array","items":{"type":"object"}}},("kind","action","workshop","connections"))
_MAPPING_DRAFT=schema({"operation":{"const":"market_mapping"},"arguments":REGISTRY["market_mapping"]["input_schema"],
    "revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"workshop":IDENTIFIER,"summary":{"type":"string"}},
    ("operation","arguments","revision","workshop","summary"))
_EXPORT_CARD=schema({"kind":{"const":"export"},"operation":{"enum":list(EXPORTABLE)},"arguments":schema(EXPORT_ARGS),"workshop":IDENTIFIER},
    ("kind","operation","arguments","workshop"))
for _name,_schema in {
    "market_sales":_REPORT,"market_loss_rates":_RATE_REPORT,"market_catalog":_CATALOG,
    "market_sync_status":_STATUS,"market_sync_request":_GROUP,"market_sync_control":_JOB,
    "market_connection":_output({"state":_STATE,"marketCard":_CONNECTION_CARD},("state","marketCard")),
    "market_mapping":_output({"state":{"const":"confirmation_required"},"marketDraft":_MAPPING_DRAFT},("state","marketDraft")),
    "market_export":_output({"state":_STATE,"marketCard":_EXPORT_CARD},("state","marketCard")),
}.items():REGISTRY[_name]["output_schema"]=_schema

def validate_registry():
    for name, item in REGISTRY.items():
        if item["stable_id"] != name or item["kind"] != "user_operation" or not all(item["bindings"].values()):
            raise RuntimeError("Invalid marketplace user registry")
        Draft202012Validator.check_schema(item["input_schema"])
        Draft202012Validator.check_schema(item["output_schema"])
    return True

def declarations():
    return deepcopy(list(REGISTRY.values()))

def _arguments(operation, args):
    entry = REGISTRY.get(operation)
    if entry is None:
        raise ValueError("Неизвестная операция маркетплейса.")
    # Do not expose schema validation messages: they can contain supplied data.
    if next(Draft202012Validator(entry["input_schema"]).iter_errors(args), None):
        raise ValueError("Некорректные параметры операции маркетплейса.")
    for key in ("from", "to"):
        if key in args:
            if date.fromisoformat(args[key]).isoformat() != args[key]:
                raise ValueError("Укажите дату ГГГГ-ММ-ДД.")
    if args.get("from", "0001") > args.get("to", "9999"):
        raise ValueError("Начало периода позже окончания.")
    return {**{k: v["default"] for k, v in entry["input_schema"]["properties"].items() if "default" in v}, **args}

def connection_card(db, w, args):
    action = args.get("action", "list")
    connections = []
    for row in db.execute("SELECT id,provider,name,version,checks,checked,details FROM pm_market_connections WHERE workspace=? ORDER BY name,id", (w,)):
        connections.append(dict(zip(("id", "provider", "name", "version", "checks", "checked"), row[:6])))
        connections[-1]["checks"] = json.loads(connections[-1]["checks"])
        details=json.loads(row[6])
        # Only display metadata already confirmed by the identity template.
        # Never expose arbitrary checkpoint/transport metadata to a model.
        connections[-1]["details"]={"scopes":[v for v in details.get("scopes",[]) if isinstance(v,str)],
            "campaigns":[{k:c[k] for k in ("campaignId","businessId","name","placementType","apiAvailability") if k in c}
                for c in details.get("campaigns",[]) if isinstance(c,dict)]}
    selected = next((x for x in connections if x["id"] == args.get("connection_id")), None)
    if args.get("connection_id") and selected is None:
        raise ValueError("Подключение недоступно в этой мастерской.")
    if action in ("rotate", "verify", "disconnect") and selected is None:
        raise ValueError("Выберите конкретное подключение из списка.")
    return {"marketCard": {"kind": "connection", "action": action, "workshop": w,
            **({"provider": args["provider"]} if args.get("provider") else {}),
            **({"connection": selected} if selected else {}), "connections": connections},
        "state": "ready", "text": "Используйте защищённую карточку ниже. Ключ не попадает в переписку." if action in ("connect", "rotate") else "Подключения текущей мастерской."}

def _mapping_revision(db, w, args):
    from . import market_quantity as quantity
    # The source is resolved by the shared catalogue, including owner/store scope.
    catalog = quantity.catalog(db, w, source=args["source"], unmapped_only=False, offset=0, limit=100, _unpaginated=True)
    rows = catalog.get("rows", catalog.get("items", catalog.get("products", [])))
    candidates = [r for r in rows if str(r.get("sku", "")) == args["sku"]]
    if len(candidates) != 1:
        raise ValueError("Артикул не найден однозначно. Выберите конкретный магазин.")
    row = candidates[0]
    product = args.get("product")
    if product is not None:
        from . import podmasterye_book as book
        product, name = book.entity(db, w, "product", product)
    else:
        name = "снять привязку"
    canonical = {"source": row.get("store_id") or args["source"], "sku": args["sku"], "product": product}
    # Changing either side after preview requires a fresh confirmation.
    revision = hashlib.sha256(domain.encode([w, canonical, row.get("product_id"), row.get("mapping_revision",row.get("revision")), row.get("generation"), name]).encode()).hexdigest()
    return canonical, revision, name

def prepare_mapping(db, w, args):
    canonical, revision, name = _mapping_revision(db, w, args)
    return {"marketDraft": {"operation": "market_mapping", "arguments": canonical, "revision": revision,
            "workshop": w, "summary": canonical["sku"] + " → " + name}, "state": "confirmation_required"}

def commit_mapping(db, w, args, revision, request_id):
    from . import market_quantity as quantity
    canonical, current, _ = _mapping_revision(db, w, _arguments("market_mapping", args))
    # Existing mutation receipts make repeated UI/chat confirmation exactly once.
    raw = domain.encode({"operation": "market_mapping", "arguments": canonical, "revision": revision})
    key = "market-map:" + domain.key_id(request_id)
    old = db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?", (w, key)).fetchone()
    if old:
        if old[0] != raw:
            raise domain.Conflict("Идентификатор подтверждения уже использован с другими параметрами.")
        return json.loads(old[1])
    if revision != current:
        raise domain.Conflict("Сопоставление изменилось. Подготовьте его заново.")
    result = quantity.map_product(db, w, canonical["source"], canonical["sku"], canonical["product"])
    result = result if isinstance(result, dict) else {"saved": True}
    result = {**result, "summary": "Сопоставление артикула сохранено.", "state": "ready"}
    db.execute("INSERT INTO pm_mutations(workspace,rid,args,result) VALUES(?,?,?,?)", (w, key, raw, domain.encode(result)))
    return result

def execute(db, w, operation, args, *, request_id=None, channel="ui"):
    """The sole public dispatch. Channel is diagnostic, never an authorization."""
    result=_execute(db,w,operation,args,request_id=request_id,channel=channel)
    if next(Draft202012Validator(REGISTRY[operation]["output_schema"]).iter_errors(result),None):
        # Do not echo schema diagnostics: they can contain internal result data.
        raise HTTPException(502,"Локальный результат не соответствует контракту. Повторите чтение состояния.")
    return result

def _execute(db, w, operation, args, *, request_id=None, channel="ui"):
    a = _arguments(operation, args)
    from . import market_quantity as quantity
    if operation == "market_export":
        _export_arguments(a["operation"], a["arguments"])
        return {"state":"ready", "marketCard":{"kind":"export","operation":a["operation"],"arguments":a["arguments"],"workshop":w},
            "text":"Скачайте отчёт в карточке сообщения. Файл рассчитан сервером по локальным данным; покрытие и неизвестные значения сохранены."}
    if operation == "market_connection":
        return connection_card(db, w, a)
    if operation == "market_sales":
        from . import podmasterye_market_analytics as analytics
        a["from_"] = a.pop("from")
        return analytics.sales(db, w, **a)
    if operation == "market_loss_rates":
        from . import podmasterye_market_analytics as analytics
        return analytics.loss_rates(db, w, **a)
    if operation == "market_sync_status":
        return quantity.market_sync_status(db, w, **a)
    if operation == "market_sync_request":
        if "from" in a:
            a["from_"] = a.pop("from")
        return quantity.market_sync_request(db, w, **a, request_id=request_id)
    if operation == "market_sync_control":
        return quantity.market_sync_control(db, w, **a, request_id=request_id)
    if operation == "market_catalog":
        return quantity.catalog(db, w, **a)
    if operation == "market_mapping":
        return prepare_mapping(db, w, a)
    raise ValueError("Неизвестная операция маркетплейса.")

def _export_arguments(operation, args):
    if operation in REGISTRY and operation in EXPORTABLE:
        return _arguments(operation,args)
    if operation == "material_forecast":
        selected=FORECAST_SCHEMA
    elif operation == "accounting_report":
        from . import podmasterye_matrix as matrix
        selected=matrix.report_schema()
    else:
        raise ValueError("Этот отчёт недоступен для экспорта.")
    if next(Draft202012Validator(selected).iter_errors(args),None):
        raise ValueError("Некорректные параметры отчёта.")
    return dict(args)

def export_report(db,w,operation,args):
    """Full local projection, with explicit coverage; never fetches an API page."""
    a=_export_arguments(operation,args)
    a.pop("offset",None);a.pop("limit",None);a.pop("detail_month",None)
    if operation in ("market_sales","market_loss_rates"):
        from . import podmasterye_market_analytics as analytics, market_quantity as quantity, podmasterye_book as book
        selected_source=a.pop("source","all_marketplaces")
        snapshot=quantity.quantity_snapshot(db,w,source=selected_source)
        # All pages use the very same immutable snapshot, including totals.
        if operation=="market_sales":
            a["from_"]=a.pop("from")
            fn=partial(analytics.sales_snapshot,snapshot,as_of=analytics._report_clock(book.today()),source=selected_source,**a)
        else:
            fn=partial(analytics.loss_rates_snapshot,snapshot,as_of=analytics._report_clock(book.today()),**a)
        return fn(offset=0,limit=100,_unpaginated=True)
    if operation=="market_catalog":
        from . import market_quantity as quantity
        return quantity.catalog(db,w,**a,offset=0,limit=100,_unpaginated=True)
    if operation=="material_forecast":
        from . import podmasterye_seasonal as seasonal
        return seasonal.plan(db,w,**a)
    from . import podmasterye_book as book
    return book.report(db,w,**a,_unpaginated=True)

def export_archive(value):
    files={"report.json":(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode()}
    rows=value.get("rows",value.get("totals",[]))
    if isinstance(rows,dict):rows=[{"metric":key,"value":v} for key,v in rows.items()]
    if isinstance(rows,list) and all(isinstance(row,dict) for row in rows):
        fields=list(dict.fromkeys(key for row in rows for key in row))
        text=io.StringIO();writer=csv.DictWriter(text,fieldnames=fields,delimiter=";");writer.writeheader()
        def cell(v):
            if v is None:return "не подтверждено"
            if isinstance(v,(list,dict)):v=json.dumps(v,ensure_ascii=False,allow_nan=False)
            if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r"):return "'"+v
            return v
        writer.writerows({k:cell(v) for k,v in row.items()} for row in rows)
        files["rows.csv"]=text.getvalue().encode("utf-8-sig")
    files["SHA256SUMS.txt"]="".join(hashlib.sha256(raw).hexdigest()+"  "+name+"\n" for name,raw in files.items()).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,raw in files.items():archive.writestr(name,raw)
    return out.getvalue()

def summary(operation, value):
    """Display only. All quantities and states have already been calculated."""
    if value.get("text"):
        return value["text"]
    state = value.get("state", value.get("status", "ready"))
    label = STATE_LABELS.get(state, "Состояние: " + str(state))
    parts = [label + "."]
    job = value.get("job") or value
    if job.get("job_id") or job.get("id"):
        parts.append("Задание: " + str(job.get("job_id") or job["id"]) + ".")
    if job.get("next_retry_at") is not None:
        parts.append("Следующая попытка не ранее " + str(job["next_retry_at"]) + ".")
    if value.get("blocked_jobs"):
        parts.append("Действие недоступно для заданий: " + str(len(value["blocked_jobs"])) + ".")
        parts.extend(list(dict.fromkeys(str(row["message"]) for row in value["blocked_jobs"] if row.get("message")))[:5])
    if operation in ("market_sales", "market_loss_rates", "market_catalog"):
        parts.append("Результат из локальной базы; подробности и управление доступны в карточке сообщения.")
    return " ".join(parts)

def model_projection(operation,value):
    """Bounded user state for intent selection; full detail stays in the UI.

    The projection contains no child-template matrix, cursors or report polling
    instructions. It never changes a result or computes marketplace quantities.
    """
    if operation not in ("market_sync_status","market_sync_request","market_sync_control"):
        return value
    fields=("id","job_id","state","source","from","to","message","next_retry_at","last_success","progress")
    def public(row):return {k:row[k] for k in fields if k in row}
    out=public(value)
    if value.get("blocked_jobs"):
        out["blocked_count"]=len(value["blocked_jobs"])
        out["problems"]=list(dict.fromkeys(str(row["message"]) for row in value["blocked_jobs"] if row.get("message")))[:5]
    if "groups" in value:
        out["groups"]=[public(row) for row in value["groups"][:30]]
        out["group_count"]=len(value["groups"])
    if "stores" in value:
        out["stores"]=[{k:s[k] for k in ("store_id","provider","name","verified") if k in s} for s in value["stores"][:30]]
        out["store_count"]=len(value["stores"])
    out["detail_in_chat_card"]=True
    out["text"]=summary(operation,value)
    return out

def read_or_execute(store, token, workshop, operation, args, request_id, channel):
    if request_id is not None:
        domain.key_id(request_id)
    if REGISTRY.get(operation,{}).get("effect")=="read":
        with store._lock:
            db=store._db
            w=workshops.resolve(db,_principal(db,token)[1],workshop)
            return execute(db,w,operation,args,request_id=request_id,channel=channel)
    with store._write() as db:
        w=workshops.resolve(db,_principal(db,token)[1],workshop)
        return execute(db,w,operation,args,request_id=request_id,channel=channel)

def routes(token_for, body):
    async def operation(req):
        token = token_for(req, allow_cookie=True)
        a = await body(req, "operation", "arguments", "requestId", optional=("channel",))
        try:
            result = await run_in_threadpool(read_or_execute, req.app.state.identity, token,
                req.query_params.get("workshop"), a["operation"], a["arguments"], a["requestId"], a.get("channel", "ui"))
            return JSONResponse(result)
        except domain.Conflict as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, TypeError):
            raise HTTPException(400, "Проверьте параметры операции маркетплейса.") from None

    async def mapping_confirm(req):
        token = token_for(req, allow_cookie=True)
        a = await body(req, "arguments", "revision", "requestId")
        def save():
            with req.app.state.identity._write() as db:
                w = workshops.resolve(db, _principal(db, token)[1], req.query_params.get("workshop"))
                return commit_mapping(db, w, a["arguments"], a["revision"], a["requestId"])
        try:
            return JSONResponse(await run_in_threadpool(save))
        except domain.Conflict as e:
            raise HTTPException(409, str(e)) from None
        except (ValueError, TypeError):
            raise HTTPException(400, "Проверьте сопоставление артикула.") from None

    async def connection(req):
        # No credential data is accepted by execute() or the model tools. This
        # write-only path is used by the identical component in cabinet/chat.
        token = token_for(req, allow_cookie=True)
        a = await body(req, "action", "requestId", optional=("provider", "connection_id", "name", "version", "fields"))
        domain.key_id(a["requestId"])
        s = req.app.state.market_links
        w = req.query_params.get("workshop")
        try:
            if a["action"] == "create":
                result = await run_in_threadpool(s.save, token, w, a.get("provider"), a.get("name"), a.get("fields"), request_id=a["requestId"])
            elif a["action"] == "rotate":
                result = await run_in_threadpool(s.update, token, w, a.get("connection_id"), a.get("version"), a.get("fields"), request_id=a["requestId"])
            elif a["action"] == "disconnect":
                result = await run_in_threadpool(s.remove, token, w, a.get("connection_id"), a.get("version"), request_id=a["requestId"])
            elif a["action"] == "verify":
                result = await s.check(token, w, a.get("connection_id"), req.app.state.http)
            else:
                raise ValueError("Неизвестное действие.")
            return JSONResponse(result)
        except (ValueError, TypeError):
            raise HTTPException(400, "Проверьте обязательные поля подключения.") from None

    async def export(req):
        token=token_for(req,allow_cookie=True)
        a=await body(req,"operation","arguments")
        def build():
            with req.app.state.identity._lock:
                db=req.app.state.identity._db
                w=workshops.resolve(db,_principal(db,token)[1],req.query_params.get("workshop"))
                return export_archive(export_report(db,w,a["operation"],a["arguments"]))
        try:
            content=await run_in_threadpool(build)
            return Response(content,media_type="application/zip",headers={"Content-Disposition":"attachment; filename=marketplace-report.zip","Cache-Control":"no-store"})
        except (ValueError,TypeError):
            raise HTTPException(400,"Проверьте параметры экспорта.") from None

    return [Route("/api/integrations/marketplaces/operations", operation, methods=["POST"]),
            Route("/api/integrations/marketplaces/mapping-confirm", mapping_confirm, methods=["POST"]),
            Route("/api/integrations/marketplaces/connection", connection, methods=["POST"]),
            Route("/api/integrations/marketplaces/export", export, methods=["POST"])]

validate_registry()
