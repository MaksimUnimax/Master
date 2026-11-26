"""Atomic ledger corrections with frozen production norms and immutable before/after evidence.

All edits are evaluated in a savepoint before confirmation. Rebuild chronological
movements from stable event IDs, using frozen recipes for historical production.
Never guess an unavailable historical recipe or allow negative balances.
"""
import hashlib
import json
from uuid import uuid4
from .identity import _principal
from .podmasterye_domain import Conflict, encode, key_id

EDITABLE=("opening","purchase","manufacture","sale","payment","return","expense","worker_payment","writeoff","asset_acquire","asset_retire","work_start","work_finish","component_transfer","sale_fee","sale_fee_refund")
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_corrections(
 seq INTEGER PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 rid TEXT NOT NULL, target TEXT, action TEXT NOT NULL, reason TEXT NOT NULL, args TEXT NOT NULL,
 before_state TEXT NOT NULL, after_state TEXT NOT NULL, result TEXT NOT NULL, day TEXT NOT NULL,
 UNIQUE(workspace,rid))""",
"""CREATE TABLE IF NOT EXISTS pm_cancelled_events(
 workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 rid TEXT NOT NULL, event TEXT NOT NULL, PRIMARY KEY(workspace,rid))""",
)
def init(db):
    for s in SCHEMA:db.execute(s)
def revision_state(db,w):
    return db.execute("SELECT COALESCE(MAX(seq),0) FROM pm_corrections WHERE workspace=?",(w,)).fetchone()[0]
def canonical(db,w,payload):
    from . import podmasterye_book as b
    if not isinstance(payload,dict) or set(payload)!={"action","target","operation","arguments","reason"}:raise ValueError("Неверные поля исправления.")
    action=payload["action"]
    if action not in ("edit","delete","insert"):raise ValueError("Неизвестное исправление.")
    reason=b.textval(payload["reason"],240)
    if not reason:raise ValueError("Укажите причину исправления.")
    target=payload["target"]
    if action=="insert":
        if target not in ("",None):raise ValueError("Для новой операции не нужен ID.")
        op=payload["operation"]
        if op not in EDITABLE:raise ValueError("Эта операция не поддерживает историческое внесение.")
        return dict(action=action,target="",operation=op,arguments=b.validate(op,payload["arguments"]),reason=reason)
    if not isinstance(target,str) or not target:raise ValueError("Выберите операцию.")
    row=db.execute("SELECT kind,rid,reverse_of FROM pm_book_events WHERE workspace=? AND id=?",(w,target)).fetchone()
    if not row or row[0] not in EDITABLE:raise ValueError("Операция недоступна для исправления.")
    if row[1].startswith(("ext-","ext-return-")):raise Conflict("Внешние заказы корректируются событиями источника или возвратом.")
    if db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND reverse_of=?",(w,target)).fetchone():raise Conflict("Запись уже сторнирована.")
    if payload["operation"]!=row[0]:raise ValueError("Тип операции менять нельзя.")
    a=b.validate(row[0],payload["arguments"]) if action=="edit" else {}
    if action=="delete" and payload["arguments"]!={}:raise ValueError("Лишние данные удаления.")
    return dict(action=action,target=target,operation=row[0],arguments=a,reason=reason)
def read_events(db,w):
    fields="seq,id,rid,kind,day,args,result,changes,finance,stock,reverse_of"
    rows=[]
    for v in db.execute("SELECT "+fields+" FROM pm_book_events WHERE workspace=? ORDER BY day,seq",(w,)):
        r=dict(zip(fields.split(","),v))
        for k in ("args","result","changes","finance"):r[k]=json.loads(r[k])
        rows.append(r)
    return rows
def frozen_recipe(event):
    result=event["result"]
    if "production_recipe" in result:return result["production_recipe"]
    if event["kind"] in ("manufacture","work_start"):return result.get("materials",[])
    if event["kind"]=="sale":
        # Legacy auto-production is identifiable by a lot created within this sale.
        for c in event["changes"]:
            v=c["after"]
            if c["type"]=="lot" and c["before"] is None and v and v.get("origin")==event["id"]:return v["recipe"]
    return None
def stable_args(event):
    a=dict(event["args"]);r=event["result"];kind=event["kind"]
    if kind in ("opening","purchase","writeoff","component_transfer") and r.get("material_id"):a["material"]=r["material_id"]
    if kind in ("manufacture","sale","work_start","work_finish","component_transfer") and r.get("product_id"):a["product"]=r["product_id"]
    if kind=="writeoff" and a.get("quantity") is None:a["quantity"]=r["quantity"]
    return a
def ledger_finance(db,w):
    from . import podmasterye_book as b
    return b.report(db,w,view="summary")["summary"]
def rebuild(db,w,rid,payload):
    from . import podmasterye_book as b
    action,target,op,args=(payload[k] for k in ("action","target","operation","arguments"))
    before=read_events(db,w)
    if len(before)>2000:raise Conflict("Слишком большой журнал для одной интерактивной корректировки.")
    summary_before=ledger_finance(db,w)
    changed=[];target_row=None
    for e in before:
        if e["id"]==target:
            target_row=e
            if action=="delete":continue
            a=dict(args)
            # Resolve current input once; an unchanged product keeps its historic recipe.
            if op in ("manufacture","sale","work_start"):
                pid,_=b.entity(db,w,"product",a["product"],include_archived=True)
                a["product"]=pid
                if pid!=e["result"].get("product_id"):
                    # Explicitly changing the product uses its current recipe, with a recorded reason.
                    recipe=b.current_recipe(db,w,pid)
                else:recipe=frozen_recipe(e)
            else:recipe=None
            changed.append({**e,"args":a,"day":a["day"],"_edited":True,"_recipe":recipe})
        else:changed.append(e)
    if action=="insert":
        target=uuid4().hex
        changed.append(dict(seq=max([e["seq"] for e in before]+[0])+1,id=target,rid="hist-"+hashlib.sha256(rid.encode()).hexdigest(),kind=op,day=args["day"],args=args,result={},changes=[],finance={},stock=0,reverse_of=None,_edited=True,_recipe=None))
    if action!="insert" and target_row is None:raise ValueError("Операция не найдена.")
    # Replay from a clean derived ledger; original snapshots are kept in pm_corrections.
    db.execute("DELETE FROM pm_book_rows WHERE workspace=?",(w,))
    db.execute("DELETE FROM pm_book_events WHERE workspace=?",(w,))
    if action=="delete":
        db.execute("INSERT INTO pm_cancelled_events(workspace,rid,event) VALUES(?,?,?)",(w,target_row["rid"],target))
    result=None
    for e in sorted(changed,key=lambda e:(e["day"],e["seq"])):
        a=e["args"] if e.get("_edited") else stable_args(e)
        recipe=e.get("_recipe") if e.get("_edited") else frozen_recipe(e)
        legacy=not e.get("_edited") or (action=="edit" and recipe is None and e["kind"] in ("manufacture","sale","work_start"))
        # If an old auto-production path newly requires a recipe and none was frozen,
        # fail closed rather than apply today's material norms to a past sale.
        try:
            r=b.execute(db,w,e["rid"],e["kind"],a,replay={"id":e["id"],"recipe":recipe,"require_frozen":legacy,"archived":True})
        except (ValueError,Conflict) as err:
            raise Conflict("Исправление нарушает операцию "+e["day"]+" "+e["kind"]+": "+str(err)) from None
        if e["id"]==target:result=r
    after=read_events(db,w)
    summary_after=ledger_finance(db,w)
    out={"id":target,"action":action,"operation":op,"summary":"Журнал пересчитан: "+str(len(after))+" операций.","before":summary_before,"after":summary_after,"event":result}
    db.execute("INSERT INTO pm_corrections(workspace,rid,target,action,reason,args,before_state,after_state,result,day) VALUES(?,?,?,?,?,?,?,?,?,?)",
       (w,rid,target,action,payload["reason"],encode(payload),encode(before),encode(after),encode(out),b.today().isoformat()))
    return out
def preview(store,token,workshop,payload):
    from . import podmasterye_book as b,podmasterye_workshops as ws
    with store._write() as db:
        _,a=_principal(db,token);w=ws.resolve(db,a,workshop)
        p=canonical(db,w,payload);rev=b.revision(db,w,"correction",p)
        db.execute("SAVEPOINT correction_preview")
        try:result=rebuild(db,w,"preview-"+uuid4().hex,p)
        finally:db.execute("ROLLBACK TO correction_preview");db.execute("RELEASE correction_preview")
        return {"correction":p,"revision":rev,"preview":result,"workshop":w}
def commit(store,token,workshop,rid,payload,revision):
    from . import podmasterye_book as b,podmasterye_workshops as ws
    key_id(rid)
    with store._write() as db:
        _,a=_principal(db,token);w=ws.resolve(db,a,workshop)
        old=db.execute("SELECT args,result FROM pm_corrections WHERE workspace=? AND rid=?",(w,rid)).fetchone()
        if old:
            if old[0]!=encode(payload):raise Conflict("Идентификатор исправления уже использован.")
            return json.loads(old[1])
        p=canonical(db,w,payload)
        if b.revision(db,w,"correction",p)!=revision:raise Conflict("Данные изменились. Повторите расчёт исправления.")
        return rebuild(db,w,rid,p)
def history(db,w,limit=100):
    return [dict(id=seq,target=target,action=action,reason=reason,day=day,result=json.loads(res)) for seq,target,action,reason,day,res in db.execute(
       "SELECT seq,target,action,reason,day,result FROM pm_corrections WHERE workspace=? ORDER BY seq DESC LIMIT ?",(w,-1 if limit is None else limit))]
