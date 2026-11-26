"""First production vertical slice. Same deterministic handler for UI and local assistant."""
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import time
from uuid import uuid4
from .identity import _principal, AuthenticationError, ChatUnavailable
from .storage import _owns_chat

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS pm_materials(
       id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       name TEXT NOT NULL, normalized TEXT NOT NULL, pack INTEGER NOT NULL CHECK(pack>0),
       price TEXT, UNIQUE(workspace,normalized))""",
    """CREATE TABLE IF NOT EXISTS pm_products(
       id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       name TEXT NOT NULL, normalized TEXT NOT NULL, UNIQUE(workspace,normalized))""",
    """CREATE TABLE IF NOT EXISTS pm_recipe(
       product TEXT NOT NULL REFERENCES pm_products(id) ON DELETE CASCADE,
       material TEXT NOT NULL REFERENCES pm_materials(id) ON DELETE CASCADE,
       qty INTEGER NOT NULL CHECK(qty>0), PRIMARY KEY(product,material))""",
    """CREATE TABLE IF NOT EXISTS pm_turns(
       workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       chat TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE, rid TEXT NOT NULL,
       text TEXT NOT NULL, route TEXT NOT NULL CHECK(route IN ('local','model')),
       result TEXT, created INTEGER NOT NULL, PRIMARY KEY(workspace,chat,rid))""",
    """CREATE TABLE IF NOT EXISTS pm_mutations(
       workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       rid TEXT NOT NULL, args TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(workspace,rid))""",
    """CREATE TABLE IF NOT EXISTS pm_drafts(
       workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
       chat TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE, rid TEXT NOT NULL,
       args TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(workspace,chat,rid))""",
)
RECIPE_FIELDS = {"material","product","pack_quantity","usage_quantity","pack_price","unit"}
RECIPE_SCHEMA = {"type":"object","properties":{
    "material":{"type":"string","minLength":1,"maxLength":120},
    "product":{"type":"string","minLength":1,"maxLength":120},
    "pack_quantity":{"type":"integer","minimum":1,"maximum":1000000000},
    "usage_quantity":{"type":"integer","minimum":1,"maximum":1000000000},
    "pack_price":{"type":["string","null"],"maxLength":22},"unit":{"type":"string","enum":["шт","г","мл","мм","см²","компл"]}},
    "required":["material","product","pack_quantity","usage_quantity"],"additionalProperties":False}
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
class Conflict(ValueError):
    pass

def init(store):
    with store._write() as db:
        for stmt in SCHEMA: db.execute(stmt)
        from . import podmasterye_book as book
        book.init(db)
        from . import podmasterye_workshops as workshops
        workshops.init(db)
        from . import podmasterye_integrations as integrations
        integrations.init(db)
        from . import podmasterye_market_links as market_links
        market_links.init(db)
        from . import podmasterye_agent_forms as agent
        agent.init(db)
        from . import podmasterye_router as router
        router.init(db)
        db.execute("""CREATE TABLE IF NOT EXISTS pm_turn_attachments(
          workspace TEXT NOT NULL,chat TEXT NOT NULL,rid TEXT NOT NULL,ids TEXT NOT NULL,
          PRIMARY KEY(workspace,chat,rid),FOREIGN KEY(workspace,chat,rid) REFERENCES pm_turns(workspace,chat,rid) ON DELETE CASCADE)""")

def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def key_id(value):
    if not isinstance(value,str) or not REQUEST_ID.fullmatch(value):
        raise ValueError("Некорректный идентификатор запроса.")
    return value

def clean_name(value):
    if not isinstance(value,str):
        raise ValueError("Укажите название.")
    result=" ".join(value.split())
    if not 1<=len(result)<=120 or not result.isprintable():
        raise ValueError("Название должно содержать от 1 до 120 символов.")
    return result

def recipe_args(args):
    if not isinstance(args,dict) or not RECIPE_FIELDS-{"pack_price","unit"}<=args.keys()<=RECIPE_FIELDS:
        raise ValueError("Укажите изделие, материал, упаковку и расход.")
    result={k:clean_name(args[k]) for k in ("material","product")}
    for k in ("pack_quantity","usage_quantity"):
        v=args[k]
        if type(v) is not int or not 1<=v<=1000000000:
            raise ValueError("Количество должно быть положительным целым числом.")
        result[k]=v
    price=args.get("pack_price")
    if price is not None:
        if not isinstance(price,str) or not re.fullmatch(r"[0-9]{1,12}(?:[.,][0-9]{1,6})?",price):
            raise ValueError("Укажите цену упаковки в рублях.")
        price=format(Decimal(price.replace(",",".")),"f")
    result["pack_price"]=price
    unit=args.get("unit")
    if unit is not None and unit not in ("шт","г","мл","мм","см²","компл"):
        raise ValueError("Неизвестная единица материала.")
    if unit is not None:result["unit"]=unit
    return result

def preview(args):
    v=recipe_args(args)
    cost=None
    if v["pack_price"] is not None:
        cost=format((Decimal(v["pack_price"])*v["usage_quantity"]/v["pack_quantity"]).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f")
    return {**v,"base_unit":v.get("unit","шт"),"purchase_unit":"упаковка",
            "products_per_pack":v["pack_quantity"]//v["usage_quantity"],
            "material_cost_rub":cost}

def assert_scope(db,token,scope):
    actor,workspace=_principal(db,token)
    if (actor,workspace)!=(scope.actor_id,scope.workspace_id) or not _owns_chat(db,scope):
        raise ChatUnavailable("Chat unavailable")

def _save(db,workspace,rid,args):
    v=recipe_args(args); raw=encode(v)
    old=db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?",(workspace,rid)).fetchone()
    if old:
        if old[0]!=raw: raise Conflict("Этот идентификатор уже использован.")
        return json.loads(old[1])
    mat=db.execute("SELECT id,pack,price,name,unit,archived FROM pm_materials WHERE workspace=? AND normalized=?",(workspace,v["material"].casefold())).fetchone()
    if mat:
        mid,pack,price,name,unit,archived=mat
        if archived:raise Conflict("Материал в архиве.")
        if v.get("unit",unit)!=unit:raise Conflict("Единица материала не совпадает со справочником.")
        v["unit"]=unit
        if pack!=v["pack_quantity"]:
            raise Conflict("У материала уже другая упаковка. Изменение общей единицы требует отдельной операции.")
        if v["pack_price"] is not None:
            db.execute("UPDATE pm_materials SET price=? WHERE id=? AND workspace=?",(v["pack_price"],mid,workspace))
        else:
            v["pack_price"]=price
        v["material"]=name
    else:
        mid=uuid4().hex
        v["unit"]=v.get("unit","шт")
        db.execute("INSERT INTO pm_materials(id,workspace,name,normalized,pack,price,unit) VALUES(?,?,?,?,?,?,?)",(mid,workspace,v["material"],v["material"].casefold(),v["pack_quantity"],v["pack_price"],v["unit"]))
    product=db.execute("SELECT id,name,archived FROM pm_products WHERE workspace=? AND normalized=?",(workspace,v["product"].casefold())).fetchone()
    if product:
        pid,v["product"],archived=product
        if archived:raise Conflict("Изделие в архиве.")
    else:
        pid=uuid4().hex
        db.execute("INSERT INTO pm_products(id,workspace,name,normalized) VALUES(?,?,?,?)",(pid,workspace,v["product"],v["product"].casefold()))
    from . import podmasterye_extra as extra
    extra.freeze_recipe(db,workspace,pid)
    db.execute("INSERT INTO pm_recipe VALUES(?,?,?) ON CONFLICT(product,material) DO UPDATE SET qty=excluded.qty",(pid,mid,v["usage_quantity"]))
    extra.freeze_recipe(db,workspace,pid)
    result={**preview(v),"material_id":mid,"product_id":pid}
    db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(workspace,rid,raw,encode(result)))
    return result

def save_recipe(store,token,rid,args,workshop_id=None):
    with store._write() as db:
        from . import podmasterye_workshops as workshops
        _,account=_principal(db,token);workspace=workshops.resolve(db,account,workshop_id)
        return _save(db,workspace,"manual:"+key_id(rid),args)

def state(db,workspace):
    mats=[dict(id=r[0],name=r[1],pack_quantity=r[2],pack_price=r[3],base_unit=r[4],category=r[5],stock=None)
          for r in db.execute("SELECT id,name,pack,price,unit,category FROM pm_materials WHERE workspace=? ORDER BY normalized",(workspace,))]
    products=[]
    for pid,name in db.execute("SELECT id,name FROM pm_products WHERE workspace=? ORDER BY normalized",(workspace,)):
        rows=[{**preview(dict(product=name,material=mn,pack_quantity=pack,usage_quantity=qty,pack_price=price,unit=unit)), "material_id":mid}
              for mid,mn,pack,price,qty,unit in db.execute("""SELECT m.id,m.name,m.pack,m.price,r.qty,m.unit FROM pm_recipe r JOIN pm_materials m ON m.id=r.material
                WHERE r.product=? AND m.workspace=? ORDER BY m.normalized""",(pid,workspace))]
        complete=bool(rows) and all(x["pack_price"] is not None for x in rows)
        total=sum((Decimal(x["pack_price"])*x["usage_quantity"]/x["pack_quantity"] for x in rows),Decimal(0)) if complete else None
        products.append(dict(id=pid,name=name,recipe=rows,material_cost_rub=format(total.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if complete else None))
    return {"materials":mats,"products":products}

def read_state(store,token,workshop_id=None):
    from . import podmasterye_workshops as workshops
    with store._lock:
        _,a=_principal(store._db,token);w=workshops.resolve(store._db,a,workshop_id)
        return state(store._db,w)

FAQ={
 "как считается себестоимость":"Стоимость материала на изделие = цена упаковки × расход / количество в упаковке. Складываем стоимости всех материалов. Если цена не задана, итог неизвестен. Это материальная себестоимость; труд и другие расходы появятся в следующих разделах.",
 "почему прибыль отличается от денежного потока":"Закупка уменьшает деньги и увеличивает запас. В прибыль входит себестоимость проданных изделий, а не вся закупка. Денежный поток и прибыль — разные показатели.",
 "как работает помощник":"Известные команды выполняются по матрице и готовым функциям без обращения к ИИ. Свободные формулировки обрабатывает DeepSeek через Harness. Расчёты выполняет программа.",
}
PATTERN=re.compile(r"(?:добавь|создай|заведи) (?P<material>[^,;]+?) (?:пачками|упаковками) по (?P<pack>\d{1,9})(?: шт(?:ук(?:и|а)?)?\.?)?\s*[,;]\s*на (?P<product>[^,;]+?) (?:уходит|расходуется|нужно) (?P<usage>\d{1,9})(?: шт(?:ук(?:и|а)?)?\.?)?(?:\s*[,;]\s*(?:цена упаковки|упаковка стоит) (?P<price>\d{1,12}(?:[.,]\d{1,6})?)(?: ₽| руб(?:лей)?)?)?",re.I)

def explain(r):
    price="Цена упаковки не указана." if r["material_cost_rub"] is None else "Стоимость материала на изделие: "+r["material_cost_rub"]+" ₽."
    return f'{r["material"]}: упаковка {r["pack_quantity"]} {r.get("base_unit","шт")}, на {r["product"]} — {r["usage_quantity"]} {r.get("base_unit","шт")}. Из упаковки — {r["products_per_pack"]} целых изделий. {price}'

def decide(store,scope,token,rid,text,form_context=None,view_context=None,attachment_ids=None,has_files=False):
    key_id(rid)
    with store._write() as db:
        assert_scope(db,token,scope)
        from . import podmasterye_workshops as workshops
        w,c=scope.workspace_id,scope.chat_id
        data_scope=workshops.chat_workspace(db,scope)
        from . import podmasterye_agent_forms as agent
        ctx=agent.context(db,scope,rid,form_context)
        from . import podmasterye_router as router
        view=router.validate_view(view_context)
        old=db.execute("SELECT text,route,result FROM pm_turns WHERE workspace=? AND chat=? AND rid=?",(w,c,rid)).fetchone()
        ids=attachment_ids or []
        if old:
            a=db.execute("SELECT ids FROM pm_turn_attachments WHERE workspace=? AND chat=? AND rid=?",(w,c,rid)).fetchone()
            if (json.loads(a[0]) if a else [])!=ids:raise Conflict("Этот идентификатор уже использован.")
            if old[0]!=text or agent.current(db,scope,rid)!=ctx or router.previous_view(db,scope,rid)!=view: raise Conflict("Этот идентификатор уже использован.")
            return old[1],json.loads(old[2]) if old[2] else None
        started=int(time()*1000)
        if ctx is not None:db.execute('INSERT INTO pm_agent_context VALUES(?,?,?,?)',(w,c,rid,encode(ctx)))
        result,selected=router.choose(db,scope,rid,data_scope,text,ctx,view,attachments=bool(ids),has_files=has_files,faq=getattr(store,'faq',None))
        route="local" if result else "model"
        if result:result.update(role="assistant",requestId=rid,route=route,workshop=data_scope)
        db.execute("INSERT INTO pm_turns VALUES(?,?,?,?,?,?,?)",(w,c,rid,text,route,encode(result) if result else None,started))
        if ids:db.execute('INSERT INTO pm_turn_attachments VALUES(?,?,?,?)',(w,c,rid,encode(ids)))
        router.record(db,scope,rid,result,selected,started,view)
        return route,result

def complete(store,scope,token,rid,result):
    with store._write() as db:
        assert_scope(db,token,scope)
        d=db.execute("SELECT result FROM pm_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
        from . import podmasterye_workshops as workshops
        result={**result,"route":"model","workshop":workshops.chat_workspace(db,scope)}
        a=db.execute("SELECT result FROM pm_accounting_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
        if a:
            from . import podmasterye_book as book
            draft=json.loads(a[0]); result["accountingDraft"]=draft
            result["text"]="Подготовил форму «"+book.FIELDS[draft["operation"]][0]+"». Проверьте расчёт и подтвердите запись."
            result["ui"]={"page":book.PAGES[draft["operation"]]}
        if d:
            result["draft"]=json.loads(d[0])
            result["text"]="Подготовил форму рецептуры. "+explain(result["draft"])+" Проверьте данные и нажмите «Сохранить»."
            result["ui"]={"page":"products"}
        agent=db.execute("SELECT value FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
        if agent:
            prepared=json.loads(agent[0])
            result.update({k:prepared[k] for k in ("accountingDraft","formDraft") if k in prepared})
            result["ui"]={"page":prepared["page"]}
            missing=prepared["missing"]
            result["text"]="Заполнил форму. "+("Уточните: "+", ".join(missing)+"." if missing else "Проверьте данные перед сохранением.")
            if prepared.get("accountingDraft",{}).get("validationError"):
                result["text"]+=" "+prepared["accountingDraft"]["validationError"]
        db.execute("UPDATE pm_turns SET result=? WHERE workspace=? AND chat=? AND rid=? AND route='model'",
                   (encode(result),scope.workspace_id,scope.chat_id,rid))
        db.execute("UPDATE pm_route_decisions SET finished=?,outcome='complete' WHERE workspace=? AND chat=? AND rid=?",(int(time()*1000),scope.workspace_id,scope.chat_id,rid))
        return result

def history(store,token,scope,limit):
    with store._lock:
        db=store._db; assert_scope(db,token,scope)
        rows=db.execute("SELECT rid,text,result FROM pm_turns WHERE workspace=? AND chat=? AND result IS NOT NULL ORDER BY rowid DESC LIMIT ?",
                       (scope.workspace_id,scope.chat_id,limit)).fetchall()
        guest_rows=db.execute("""SELECT t.request_id,t.text,t.answer FROM guest_turns t
            JOIN guest_chats g ON g.chat_id=t.chat_id
            WHERE t.chat_id=? AND g.claimed_actor=? ORDER BY t.rowid DESC LIMIT ?""",
            (scope.chat_id,scope.actor_id,max(0,limit-len(rows)))).fetchall()
        out=[]
        for rid,text,answer in reversed(guest_rows):
            out.extend([{"role":"user","text":text,"requestId":rid},{"role":"assistant","text":answer,"requestId":rid}])
        for rid,text,result in reversed(rows):
            out.extend([{"role":"user","text":text,"requestId":rid},json.loads(result)])
        return out
