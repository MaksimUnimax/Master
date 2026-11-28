"""Scoped assistant proposals. Business writes use the existing ledger, never a model instruction alone."""
import hashlib
import json
import re
from time import time
from uuid import uuid4

from . import podmasterye_book as book, podmasterye_domain as domain, podmasterye_corrections as corrections, podmasterye_workshops as workshops

RECORD_KINDS=("material","product","task","worker","channel_rates","cost_policy","quality_policy","event")
PATCH_SCHEMA={"type":"object","additionalProperties":{"type":["string","integer","boolean","null"]}}
RECORD_SCHEMA={"type":"object","properties":{"kind":{"type":"string","enum":list(RECORD_KINDS)},"id":{"type":"string","maxLength":120}},"required":["kind"],"additionalProperties":False}
EDIT_SCHEMA={"type":"object","properties":{**RECORD_SCHEMA["properties"],"changes":PATCH_SCHEMA,"reason":{"type":"string","maxLength":240}},"required":["kind","changes"],"additionalProperties":False}
CONFIRM=re.compile(r"(?:(?:да|пожалуйста|сам|сама|самостоятельно)[,\s]+)*(?:сохрани|сохраняй|сохранить|подтверждаю(?: сохранение)?)(?:\s+(?:сам|сама|самостоятельно|это|черновик|запись|рецептуру|результат))?(?:[,\s]+(?:потом|затем)\s+(?:когда\s+вс[её]\s+добавим\s+)?покаж(?:и|ешь|ите)\s+(?:мне\s+)?(?:результат|что\s+получилось))?[.!]?",re.I)

def details(db,w,kind,ref=""):
    """Return current canonical form values; no account-wide queries or fuzzy selection."""
    if kind=="material":
        ident,_=book.entity(db,w,kind,ref)
        row=db.execute("SELECT name,unit,pack,price,category,note FROM pm_materials WHERE workspace=? AND id=?",(w,ident)).fetchone()
        return {"entity_id":ident,**dict(zip(("name","unit","pack","pack_price","category","catalog_note"),row))}
    if kind=="product":
        ident,_=book.entity(db,w,kind,ref)
        row=db.execute("SELECT name,category,sale_price,minutes,note FROM pm_products WHERE workspace=? AND id=?",(w,ident)).fetchone()
        return {"entity_id":ident,**dict(zip(("name","category","sale_price","minutes","catalog_note"),row))}
    if kind in ("task","worker"):
        from . import podmasterye_agent_forms as agent
        ident=agent._entity(db,w,kind,ref)
        if kind=="task":
            row=db.execute("SELECT name,description,due,remind_days,priority,category FROM pm_tasks WHERE workspace=? AND id=?",(w,ident)).fetchone()
            return {"task_id":ident,**dict(zip(("name","description","due","remind_days","priority","task_category"),row))}
        row=db.execute("SELECT name,position,archived FROM pm_workers WHERE workspace=? AND id=?",(w,ident)).fetchone()
        return {"worker_id":ident,"name":row[0],"position":row[1],"archived":bool(row[2])}
    if kind=="channel_rates":
        ref=domain.clean_name(ref)
        row=db.execute("SELECT channel,commission_bps,fixed_fee FROM pm_channel_rates WHERE workspace=? AND normalized=?",(w,ref.casefold())).fetchone()
        if not row:raise ValueError("Тариф канала не найден.")
        return {"channel":row[0],"commission":book.money(row[1]),"fixed_fee":book.money(row[2])}
    if kind=="quality_policy":
        from .podmasterye_quality import policy
        return policy(db,w)
    if kind=="cost_policy":
        row=db.execute("SELECT monthly_overhead,productive_hours,include_depreciation FROM pm_cost_policies WHERE workspace=?",(w,)).fetchone() or (0,0,0)
        return {"monthly_overhead":book.money(row[0]),"productive_hours":row[1],"include_depreciation":bool(row[2])}
    if kind=="event":
        row=db.execute("SELECT id,kind,args,result FROM pm_book_events WHERE workspace=? AND id=?",(w,ref)).fetchone()
        if not row or row[1] not in corrections.EDITABLE:raise ValueError("Операция недоступна для исправления.")
        event={"id":row[0],"kind":row[1],"args":json.loads(row[2]),"result":json.loads(row[3])}
        return {"target":event["id"],"operation":event["kind"],"arguments":corrections.stable_args(event)}
    raise ValueError("Неизвестный тип записи.")

def prepare_edit(db,scope,rid,args):
    from . import podmasterye_agent_forms as agent
    w=workshops.chat_workspace(db,scope)
    kind=args["kind"];ref=args.get("id","")
    current=details(db,w,kind,ref)
    changes=args["changes"]
    if not changes:raise ValueError("Укажите изменения.")
    if kind=="event":
        if not args.get("reason"):raise ValueError("Укажите причину исторического исправления.")
        p=corrections.canonical(db,w,{"action":"edit","target":current["target"],"operation":current["operation"],
            "arguments":{**current["arguments"],**changes},"reason":args["reason"]})
        rev=book.revision(db,w,"correction",p)
        db.execute("SAVEPOINT agent_correction_preview")
        try:preview=corrections.rebuild(db,w,"preview-"+uuid4().hex,p)
        finally:db.execute("ROLLBACK TO agent_correction_preview");db.execute("RELEASE agent_correction_preview")
        out={"correctionDraft":{"correction":p,"revision":rev,"preview":preview,"workshop":w},
             "page":book.PAGES[p["operation"]],"missing":[]}
        return agent.save_draft(db,scope,rid,out)
    if set(changes)&{"entity_id","task_id","worker_id","channel"}:
        raise ValueError("Нельзя менять идентификатор редактируемого объекта.")
    normalized=book.validate(kind,{**current,**changes})
    preview=book.preview_action(db,w,kind,normalized)
    return agent.save_draft(db,scope,rid,{"accountingDraft":preview,"page":book.PAGES[kind],"missing":[]})

def proposal_key(scope,rid):
    return "agent-"+hashlib.sha256(domain.encode([scope.chat_id,rid]).encode()).hexdigest()

def add_proposal(db,scope,rid,result):
    """Only complete, previewed operations receive a confirmation affordance."""
    if not result:return result
    w=workshops.chat_workspace(db,scope)
    try:
        if "marketDraft" in result:
            d=result["marketDraft"]
            if d.get("workshop")!=w or d.get("operation")!="market_mapping" or not d.get("revision"):return result
            kind="market";rev=d["revision"];summary=d["summary"]
        elif "correctionDraft" in result:
            d=result["correctionDraft"]
            if d.get("workshop")!=w or not d.get("revision") or not d.get("preview"):return result
            kind="correction";rev=d["revision"];summary=d["preview"]["summary"]
        elif "accountingDraft" in result:
            d=result["accountingDraft"]
            if d.get("missing") or d.get("validationError"):return result
            if not d.get("revision") or not d.get("preview"):
                d=book.preview_action(db,w,d["operation"],d["arguments"])
                result["accountingDraft"]=d
            if d["workshop"]!=w:return result
            kind="accounting";rev=d["revision"];summary=d["preview"]["summary"]
        elif "draft" in result or result.get("formDraft",{}).get("form")=="recipe":
            draft=result.get("draft")
            a={k:v for k,v in (draft or result["formDraft"]["arguments"]).items() if k in domain.RECIPE_FIELDS}
            a=domain.recipe_args(a)
            if "unit" not in a:a["unit"]="шт"
            rev=book.revision(db,w,"recipe",a)
            prepared=result.pop("recipeRevision",None)
            if draft:prepared=draft.pop("_prepared_revision",prepared)
            if prepared is not None and prepared!=rev:
                result["text"]="Данные изменились после подготовки рецептуры. Подготовьте запись заново."
                result.pop("draft",None);result.pop("formDraft",None)
                return result
            db.execute("SAVEPOINT agent_recipe_preview")
            try:domain._save(db,w,"preview-"+uuid4().hex,a)
            finally:db.execute("ROLLBACK TO agent_recipe_preview");db.execute("RELEASE agent_recipe_preview")
            result["draft"]=domain.preview(a)
            kind="recipe";summary="Рецептура: "+a["product"]+" / "+a["material"]
        else:return result
    except (ValueError,KeyError,TypeError):
        return result
    result["confirmation"]={"id":rid,"kind":kind,"revision":rev,"summary":summary,"status":"pending"}
    return result

def confirm_locked(db,scope,draft_id):
    domain.key_id(draft_id)
    w=workshops.chat_workspace(db,scope)
    row=db.execute("SELECT result FROM pm_turns WHERE workspace=? AND chat=? AND rid=?",
                   (scope.workspace_id,scope.chat_id,draft_id)).fetchone()
    if not row or not row[0]:raise ValueError("Черновик недоступен.")
    original=json.loads(row[0]);c=original.get("confirmation")
    if original.get("workshop")!=w or not c or c.get("id")!=draft_id:raise ValueError("Нет готовой записи для подтверждения.")
    if c.get("status")=="saved":
        return {"text":c["receipt"],"confirmedDraft":draft_id,"alreadySaved":True,"ui":original.get("ui",{})}
    if c.get("status")!="pending":raise ValueError("Черновик больше не доступен.")
    key=proposal_key(scope,draft_id)
    kind=c["kind"]
    if kind=="market":
        from . import podmasterye_market_operations as market
        d=original["marketDraft"]
        r=market.commit_mapping(db,w,d["arguments"],c["revision"],key);summary=r["summary"]
    elif kind=="accounting":
        d=original["accountingDraft"];op=d["operation"];a=book.validate(op,d["arguments"])
        # The same stable key makes the browser and assistant path idempotent.
        old=db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND rid=?",(w,key)).fetchone() or db.execute("SELECT 1 FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+key)).fetchone()
        if not old and book.revision(db,w,op,a)!=c["revision"]:raise domain.Conflict("Данные изменились. Подготовьте запись заново.")
        r=book.execute(db,w,key,op,a);summary=r["summary"]
    elif kind=="correction":
        p=original["correctionDraft"]["correction"]
        if book.revision(db,w,"correction",p)!=c["revision"]:raise domain.Conflict("Данные изменились. Подготовьте исправление заново.")
        r=corrections.rebuild(db,w,key,corrections.canonical(db,w,p));summary=r["summary"]
    elif kind=="recipe":
        a=domain.recipe_args({k:v for k,v in original["draft"].items() if k in domain.RECIPE_FIELDS})
        if book.revision(db,w,"recipe",a)!=c["revision"]:raise domain.Conflict("Данные изменились. Подготовьте рецептуру заново.")
        r=domain._save(db,w,key,a);summary="Рецептура сохранена: "+r["product"]+" / "+r["material"]
    else:raise ValueError("Неизвестный тип подтверждения.")
    c.update(status="saved",receipt=summary)
    db.execute("UPDATE pm_turns SET result=? WHERE workspace=? AND chat=? AND rid=?",
               (domain.encode(original),scope.workspace_id,scope.chat_id,draft_id))
    return {"text":summary,"confirmedDraft":draft_id,"alreadySaved":False,"ui":original.get("ui",{})}

def previous_proposal(db,scope):
    row=db.execute("""SELECT rid,result FROM pm_turns WHERE workspace=? AND chat=? AND result IS NOT NULL
       AND (json_type(result,'$.confirmation')='object' OR json_type(result,'$.draft')='object'
        OR json_type(result,'$.accountingDraft')='object' OR json_type(result,'$.formDraft')='object'
        OR json_type(result,'$.marketDraft')='object')
       ORDER BY rowid DESC LIMIT 1""",(scope.workspace_id,scope.chat_id)).fetchone()
    if not row:return None
    r=json.loads(row[1])
    if r.get("workshop",scope.workspace_id)!=workshops.chat_workspace(db,scope):return None
    return {"requestId":row[0],**{k:r[k] for k in ("draft","accountingDraft","formDraft","correctionDraft","marketDraft","confirmation") if k in r}}

def typed_confirmation(db,scope,text):
    if not CONFIRM.fullmatch(text.strip()):return None
    previous=previous_proposal(db,scope)
    if previous and previous.get("confirmation"):
        from .workshop_write_permissions import safe
        latest=db.execute("SELECT rid FROM pm_turns WHERE workspace=? AND chat=? AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1",(scope.workspace_id,scope.chat_id)).fetchone()
        if previous["confirmation"]["status"]=="pending" and not safe(previous) and (not latest or latest[0]!=previous["requestId"]):
            return {"text":"Для опасной операции откройте конкретный черновик и подтвердите его."}
        return confirm_locked(db,scope,previous["requestId"])
    if previous and previous.get("draft"):
        # Old recipe data is only re-prepared; never overwrite a catalogue
        # record using an obsolete proposal with no revision.
        try:
            a=domain.recipe_args({k:v for k,v in previous["draft"].items() if k in domain.RECIPE_FIELDS})
            w=workshops.chat_workspace(db,scope)
            review=bool(db.execute("SELECT 1 FROM pm_materials WHERE workspace=? AND normalized=?",(w,a["material"].casefold())).fetchone() or
                        db.execute("SELECT 1 FROM pm_products WHERE workspace=? AND normalized=?",(w,a["product"].casefold())).fetchone())
            return {"draft":domain.preview(a),"ui":{"page":"products"},"legacyReprepared":True,"legacyReviewRequired":review,
                    "text":"Восстановил старый черновик и проверяю его по текущим данным."}
        except ValueError:return None
    # Other legacy proposals need a fresh validated typed operation.
    if previous:return None
    return {"text":"Нет готового черновика для подтверждения. Укажите, что нужно сохранить."}

def confirm_from_button(store,scope,token,draft_id):
    from . import podmasterye_router as router
    domain.key_id(draft_id)
    rid="confirm-"+hashlib.sha256(domain.encode([scope.chat_id,draft_id]).encode()).hexdigest()
    text="Подтверждаю сохранение"
    with store._write() as db:
        domain.assert_scope(db,token,scope)
        old=db.execute("SELECT result FROM pm_turns WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
        if old:return json.loads(old[0])
        started=int(time()*1000)
        result=confirm_locked(db,scope,draft_id)
        result.update(role="assistant",requestId=rid,route="local",workshop=workshops.chat_workspace(db,scope))
        db.execute("INSERT INTO pm_turns VALUES(?,?,?,?,?,?,?)",(scope.workspace_id,scope.chat_id,rid,text,"local",domain.encode(result),started))
        router.record(db,scope,rid,result,{},started)
        return result
