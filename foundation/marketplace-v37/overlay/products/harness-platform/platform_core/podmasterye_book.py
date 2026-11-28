"""Deterministic accounting book. All values in integer kopecks; base quantities are integers.

All mutations share one SQLite write transaction. Product and material references
are resolved within the authenticated workspace. A stock event freezes the quantities,
value and recipe actually used. Corrections are appended, not destructive edits.
"""
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo
from .identity import _principal
from .podmasterye_domain import clean_name, key_id, encode, Conflict
from . import podmasterye_quality as quality
from . import podmasterye_extra as extra, podmasterye_corrections as corrections, podmasterye_assets as assets

ZONE=ZoneInfo("Asia/Yekaterinburg")
MAX_Q=10**12
MAX_M=10**16
UNITS=("шт","г","мл","мм","см²","компл")
CATEGORIES=("Реклама","Инструмент","Оборудование","Доставка","Упаковка","Подписки","Аренда","Услуги маркетплейса","Налоги","Оплата труда","Прочее")
FIN=("revenue","cogs","expenses","writeoffs","purchases","receipts","production_cash","valuation","capex","asset_proceeds","asset_disposal","depreciation")
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_book_rows(
 workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 type TEXT NOT NULL CHECK(type IN ('raw','lot','sale','asset')), key TEXT NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(workspace,type,key))""",
"""CREATE TABLE IF NOT EXISTS pm_book_events(
 seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
 workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 rid TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL, args TEXT NOT NULL,
 result TEXT NOT NULL, changes TEXT NOT NULL, finance TEXT NOT NULL,
 stock INTEGER NOT NULL CHECK(stock IN (0,1)), reverse_of TEXT,
 UNIQUE(workspace,rid), UNIQUE(workspace,reverse_of))""",
"""CREATE INDEX IF NOT EXISTS pm_book_period ON pm_book_events(workspace,day,seq)""",
"""CREATE INDEX IF NOT EXISTS pm_book_stock ON pm_book_events(workspace,stock,day)""",
)
def init(db):
    for stmt in SCHEMA: db.execute(stmt)
    # v4 table has a narrower CHECK constraint; preserve every row transactionally.
    sql=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pm_book_rows'").fetchone()[0]
    if "'asset'" not in sql:
        db.execute("ALTER TABLE pm_book_rows RENAME TO pm_book_rows_v4")
        db.execute(SCHEMA[0])
        db.execute("INSERT INTO pm_book_rows SELECT * FROM pm_book_rows_v4")
        db.execute("DROP TABLE pm_book_rows_v4")
    def column(table,col,decl):
        if col not in {r[1] for r in db.execute("PRAGMA table_info("+table+")")}:
            db.execute("ALTER TABLE "+table+" ADD COLUMN "+col+" "+decl)
    column("pm_materials","unit","TEXT NOT NULL DEFAULT 'шт'")
    column("pm_materials","category","TEXT NOT NULL DEFAULT ''")
    column("pm_products","category","TEXT NOT NULL DEFAULT ''")
    column("pm_products","sale_price","TEXT")
    column("pm_products","minutes","INTEGER")
    extra.init(db)
    corrections.init(db)
    from . import podmasterye_photos as photos
    photos.init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS pm_accounting_drafts(
        workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
        chat TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
        rid TEXT NOT NULL,args TEXT NOT NULL,result TEXT NOT NULL,
        PRIMARY KEY(workspace,chat,rid))""")

def today(): return datetime.now(ZONE).date()
def money(v): return format(Decimal(v)/100,".2f")
def quantity(v,zero=False):
    if type(v) is not int or not (0 if zero else 1)<=v<=MAX_Q:
        raise ValueError("Количество должно быть целым в базовых единицах.")
    return v
def minor(v,zero=True):
    if not isinstance(v,str) or not re.fullmatch(r"\d{1,12}(?:[.,]\d{1,2})?",v):
        raise ValueError("Укажите денежную сумму с точностью до копейки.")
    x=int(Decimal(v.replace(",","."))*100)
    if x>MAX_M or (x==0 and not zero): raise ValueError("Недопустимая сумма.")
    return x
def textval(v,limit=240):
    if not isinstance(v,str) or len(v)>limit or any(ord(c)<32 for c in v):
        raise ValueError("Некорректный текст.")
    return v.strip()
def dayval(v):
    if not isinstance(v,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",v):
        raise ValueError("Укажите дату ГГГГ-ММ-ДД.")
    d=date.fromisoformat(v)
    if d>today(): raise ValueError("Дата операции не может быть в будущем.")
    return v
def prorate(value,take,total):
    if total<=0 or not 0<=take<=total: raise ValueError("Нарушение остатка.")
    return (2*value*take+total)//(2*total)
def bounded(q,v):
    if not 0<=q<=MAX_Q or not 0<=v<=MAX_M or (q==0 and v!=0):
        raise ValueError("Недопустимый остаток или стоимость.")
def entity(db,w,kind,ref,include_archived=False):
    if not isinstance(ref,str) or len(ref)>120: raise ValueError("Укажите материал или изделие.")
    tab="pm_materials" if kind=="material" else "pm_products"
    # Exact stable ID or exact normalized name. Do not infer declensions or cross-workspace IDs.
    rows=db.execute("SELECT id,name FROM "+tab+" WHERE workspace=? AND (id=? OR normalized=?)"+("" if include_archived else " AND archived=0"),
                    (w,ref," ".join(ref.split()).casefold())).fetchall()
    if len(rows)!=1: raise ValueError("Не найден однозначный объект: "+ref)
    return rows[0]

# The same field contracts drive browser forms, local assistant and MCP.
# (type, label, required, optional default); no user/model-supplied workspace.
FIELDS={
 "material":("Материал",[
   ("entity_id","material","Существующий материал (пусто — новый)",False,""),("name","text","Название",True,None),("unit","unit","Базовая единица",True,"шт"),("pack","int","Единиц в упаковке",True,1),
   ("pack_price","money","Плановая цена упаковки, ₽",False,None),("category","text","Категория",False,""),("catalog_note","text","Заметка",False,""),
   ("initial_quantity","int0","Начальный остаток (при создании)",False,None),("initial_total","money","Стоимость начального остатка, ₽",False,None)]),
 "product":("Изделие",[
   ("entity_id","product","Существующее изделие (пусто — новое)",False,""),("name","text","Название",True,None),("category","text","Категория",False,""),
   ("sale_price","money","Плановая цена продажи, ₽",False,None),("minutes","int0","Время изготовления, мин",False,None),("catalog_note","text","Заметка",False,"")]),
 "opening":("Начальный остаток",[
   ("material","material","Материал",True,None),("quantity","int","Количество (базовые единицы)",True,None),("total","money","Стоимость всего остатка, ₽",True,None)]),
 "purchase":("Закупка",[
   ("material","material","Материал",True,None),("quantity","int","Количество",True,None),("purchase_unit","choice:base,pack","Единица закупки",True,"pack"),
   ("total","money","Общая сумма, ₽",True,None),("supplier","text","Поставщик",False,"")]),
 "manufacture":("Выпуск партии",[
   ("product","product","Изделие",True,None),("quantity","int","Количество изделий",True,None),
   ("extra","money","Оплаченные прямые затраты партии сверх сырья, ₽",False,"0"),
   ("cost_override","money","Ручная себестоимость единицы, ₽ (пусто — авто)",False,None),
   ("cost_reason","text","Причина ручной стоимости",False,"")]),
 "work_start":("Начать производство (НЗП)",[
   ("product","product","Изделие",True,None),("quantity","int","Количество",True,None),
   ("extra","money","Оплаченные затраты партии сверх сырья, ₽",False,"0")]),
 "work_finish":("Завершить производство (НЗП)",[
   ("product","product","Изделие",True,None),("quantity","int","Количество завершённых изделий",True,None),
   ("extra","money","Дополнительные оплаченные затраты, ₽",False,"0")]),
 "component_transfer":("Полуфабрикат в материалы",[
   ("product","product","Готовый полуфабрикат",True,None),("material","material","Материал для следующего этапа",True,None),
   ("quantity","int","Количество полуфабрикатов",True,None)]),
 "sale":("Продажа",[
   ("product","product","Изделие",True,None),("quantity","int","Количество",True,None),("unit_price","money","Цена за единицу, ₽",True,None),
   ("channel","text","Канал продаж",True,"Прямые продажи"),("paid_amount","money","Получено денег, ₽",True,"0"),
   ("auto_produce","bool","Изготовить недостающий объём из сырья",False,False),
   ("cost_override","money","Ручная себестоимость продажи за единицу, ₽ (пусто — FIFO)",False,None),
   ("cost_reason","text","Причина ручной себестоимости",False,"")]),
 "payment":("Оплата продажи",[
   ("sale","sale","Продажа",True,None),("amount","positive_money","Получено денег, ₽",True,None)]),
 "sale_fee":("Фактические удержания по продаже",[
   ("sale","sale","Продажа",True,None),("category","choice:Комиссия,Эквайринг,Логистика,Реклама,Прочее","Вид удержания",True,"Комиссия"),
   ("total","positive_money","Удержано или оплачено, ₽",True,None)]),
 "sale_fee_refund":("Возврат удержания",[
   ("event","event","ID операции удержания",True,None),("total","positive_money","Возвращено, ₽",True,None)]),
 "return":("Возврат продажи",[
   ("sale","sale","Продажа",True,None),("quantity","int","Количество возврата",True,None),
   ("refund","money","Возвращено денег, ₽",True,"0"),("restock","bool","Фактически возвращено и пригодно для продажи",True,False)]),
 "expense":("Расход",[
   ("category","category","Статья расхода",True,"Прочее"),("total","positive_money","Сумма, ₽",True,None)]),
 "worker_payment":("Выплата работнику",[("worker_id","worker","Работник",True,None),("total","positive_money","Сумма, ₽",True,None)]),
 "writeoff":("Списание материала",[
   ("material","material","Материал",True,None),("quantity","int","Количество (пусто — весь остаток)",False,None)]),
 "asset_acquire":("Оборудование и амортизация",[
   ("name","text","Название оборудования",True,None),("total","positive_money","Первоначальная стоимость, ₽",True,None),
   ("residual","money","Ликвидационная стоимость, ₽",True,"0"),("months","int","Срок службы, месяцев",True,None),
   ("paid","bool","Покупка оплачена сейчас (иначе ввод существующего актива)",True,False)]),
 "asset_retire":("Выбытие оборудования",[
   ("asset_id","asset","Оборудование",True,None),("total","money","Получено при выбытии, ₽",True,"0")]),
 "reverse":("Сторно операции",[
   ("event","event","Операция",True,None),("reason","text","Причина",True,None)]),
}
FIELDS.update(extra.FIELDS)
CATALOG=("material","product")
METADATA=tuple(extra.FIELDS)
PAGES={"material":"materials","product":"products","opening":"stock","purchase":"purchases","manufacture":"manufacture","sale":"sales","payment":"sales","return":"sales","expense":"expenses","writeoff":"stock","reverse":"journal"}
PAGES.update(extra.PAGES);PAGES["worker_payment"]="workers";PAGES["asset_acquire"]=PAGES["asset_retire"]="assets";PAGES.update(work_start="manufacture",work_finish="manufacture",component_transfer="manufacture",sale_fee="sales",sale_fee_refund="sales")
def forms():
    return {op:{"title":label,"page":PAGES[op],"fields":[{"name":n,"type":t,"label":l,"required":r,"default":v} for n,t,l,r,v in fs]+
               ([] if op in CATALOG+METADATA else [{"name":"day","type":"date","label":"Дата","required":True,"default":today().isoformat()},{"name":"note","type":"text","label":"Заметка","required":False,"default":""}])}
            for op,(label,fs) in FIELDS.items()}

def validate(op,args):
    if not isinstance(op,str) or op not in FIELDS or not isinstance(args,dict): raise ValueError("Неизвестная операция.")
    fs=forms()[op]["fields"]
    if set(args)-{f["name"] for f in fs}: raise ValueError("Лишние поля операции.")
    out={}
    for f in fs:
        n,t=f["name"],f["type"]; v=args.get(n,f["default"])
        if op=="quality_policy" and n not in args:continue
        if v is None or (isinstance(v,str) and not v.strip() and t!="bool"):
            if f["required"]: raise ValueError("Заполните поле: "+f["label"])
            out[n]=None if t in ("money","positive_money","int0","int","quality_return","quality_scrap") else ""
            continue
        if t in ("int","int0"): out[n]=quantity(v,t=="int0")
        elif t in ("money","positive_money"): out[n]=money(minor(v,t=="money"))
        elif t=="bool":
            if type(v) is not bool: raise ValueError("Укажите да или нет.")
            out[n]=v
        elif t=="date": out[n]=dayval(v)
        elif t=="future_date":
            if not isinstance(v,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",v):raise ValueError("Укажите дату.")
            date.fromisoformat(v);out[n]=v
        elif t in ("quality_return","quality_scrap"):out[n]=quality.percent(v,production=t=="quality_scrap")
        elif t=="percent":
            value=minor(v)
            if value>=10000:raise ValueError("Процентные удержания должны быть меньше 100%.")
            out[n]=money(value)
        elif t=="unit":
            if v not in UNITS: raise ValueError("Неизвестная единица.")
            out[n]=v
        elif t=="category":
            if v not in CATEGORIES: raise ValueError("Неизвестная статья расходов.")
            out[n]=v
        elif t.startswith("choice:"):
            if v not in t[7:].split(","): raise ValueError("Неизвестная единица закупки.")
            out[n]=v
        elif t=="identifiers":
            if not isinstance(v,str) or len(v)>2000:raise ValueError("Некорректный список объектов.")
            ids=[x.strip() for x in v.split(",")]
            if not 1<=len(ids)<=50 or len(set(ids))!=len(ids) or any(not re.fullmatch(r"[0-9a-f]{32}",x) for x in ids):raise ValueError("Выберите от 1 до 50 разных объектов.")
            out[n]=",".join(ids)
        elif t in ("material","product","sale","event","task","worker","asset"): out[n]=textval(v,120)
        elif n=="name": out[n]=clean_name(v)
        else: out[n]=textval(v)
    if op=="quality_policy" and not out:
        raise ValueError("Укажите изменяемый коэффициент брака.")
    if op=="material":
        q=out["initial_quantity"];v=out["initial_total"]
        if out["entity_id"] and (q is not None or v is not None):raise ValueError("Начальный остаток изменяется через складской журнал.")
        if q is not None and q>0 and v is None:raise ValueError("Укажите стоимость начального остатка.")
        if (q is None or q==0) and v not in (None,"0.00"):raise ValueError("Стоимость без количества.")
    if op in ("manufacture","sale") and out["cost_override"] is not None and not out["cost_reason"]:
        raise ValueError("Укажите причину ручной себестоимости.")
    return out

def current_recipe(db,w,pid):
    return [dict(material_id=m,material=n,per=q,unit=u) for m,n,q,u in db.execute("""SELECT m.id,m.name,r.qty,m.unit FROM pm_recipe r
          JOIN pm_materials m ON r.material=m.id WHERE r.product=? AND m.workspace=? ORDER BY m.id""",(pid,w))]

class Rows:
    def __init__(self,db,w,event):
        self.db,self.w,self.event=db,w,event
        self.rows={(t,k):json.loads(v) for t,k,v in db.execute("SELECT type,key,value FROM pm_book_rows WHERE workspace=?",(w,))}
        self.changes={};self.lot_counter=0
    def new_lot(self,v):
        self.lot_counter+=1;lid=uuid4().hex;v["ordinal"]=self.lot_counter;self.put("lot",lid,v);return lid
    def get(self,t,k):
        value=self.rows.get((t,k))
        return json.loads(encode(value)) if value is not None else None
    def put(self,t,k,v,restore=False):
        ident=(t,k)
        if ident not in self.changes: self.changes[ident]={"type":t,"key":k,"before":self.get(t,k)}
        if v is None: self.rows.pop(ident,None)
        else:
            v=dict(v)
            if not restore: v["revision"]=self.event
            if t in ("raw","lot"): bounded(v["quantity"],v["value"])
            self.rows[ident]=v
        self.changes[ident]["after"]=self.get(t,k)
    def flush(self):
        for (t,k),change in self.changes.items():
            v=change["after"]
            if v is None:self.db.execute("DELETE FROM pm_book_rows WHERE workspace=? AND type=? AND key=?",(self.w,t,k))
            else:self.db.execute("INSERT INTO pm_book_rows VALUES(?,?,?,?) ON CONFLICT(workspace,type,key) DO UPDATE SET value=excluded.value",(self.w,t,k,encode(v)))
    def raw_add(self,mid,qty,value,opening=False):
        cur=self.get("raw",mid)
        if opening and cur is not None: raise Conflict("Начальный остаток уже задан или были движения.")
        cur=cur or {"quantity":0,"value":0}
        cur.update(quantity=cur["quantity"]+qty,value=cur["value"]+value)
        self.put("raw",mid,cur)
    def raw_take(self,mid,qty,name):
        cur=self.get("raw",mid)
        if not cur or cur["quantity"]<qty: raise Conflict("Недостаточно материала: "+name)
        cost=prorate(cur["value"],qty,cur["quantity"])
        cur.update(quantity=cur["quantity"]-qty,value=cur["value"]-cost)
        self.put("raw",mid,cur)
        return cost
    def lots(self,pid,phase="ready"):
        return sorted(((key,v) for (t,key),v in self.rows.items() if t=="lot" and v["product_id"]==pid and v["quantity"]>0 and v.get("phase","ready")==phase),key=lambda x:(x[1]["seq"],x[1].get("ordinal",0),x[0]))
    def produce(self,pid,name,qty,extra,seq,frozen=None,override=None,phase="ready"):
        recipe=current_recipe(self.db,self.w,pid) if frozen is None else frozen
        if not recipe:raise Conflict("У изделия нет рецептуры: "+name)
        used=[];cost=extra
        for r in recipe:
            mid,mname,per,unit=r["material_id"],r["material"],r["per"],r["unit"]
            # Every frozen material still has to belong to this workshop.
            if not self.db.execute("SELECT 1 FROM pm_materials WHERE workspace=? AND id=? AND unit=?",(self.w,mid,unit)).fetchone():
                raise Conflict("Историческая единица материала недоступна: "+mname)
            need=quantity(per*qty);value=self.raw_take(mid,need,mname)
            used.append({"material_id":mid,"material":mname,"per":per,"unit":unit,"quantity":need,"value_minor":value})
            cost+=value
        actual=cost
        if override is not None:cost=override
        bounded(qty,cost)
        lid=self.new_lot({"product_id":pid,"product":name,"quantity":qty,"value":cost,"initial_quantity":qty,"initial_value":cost,"seq":seq,"recipe":used,"origin":self.event,"phase":phase})
        return lid,cost,used,actual
    def take_lots(self,pid,qty,phase="ready"):
        out=[];need=qty
        for lid,_ in self.lots(pid,phase):
            if not need:break
            lot=self.get("lot",lid);take=min(need,lot["quantity"])
            cost=prorate(lot["value"],take,lot["quantity"])
            lot.update(quantity=lot["quantity"]-take,value=lot["value"]-cost)
            self.put("lot",lid,lot)
            out.append({"lot":lid,"quantity":take,"value_minor":cost,"recipe":lot["recipe"],"returned":0,"returned_value":0})
            need-=take
        if need:raise Conflict("Недостаточно незавершённых изделий." if phase=="wip" else "Недостаточно готовых изделий.")
        return out
    def sale(self,sid):
        v=self.get("sale",sid)
        if not v: raise ValueError("Продажа не найдена.")
        return v

def material_usage(alloc,qty=None):
    sums={}
    for a in alloc:
        for r in a["recipe"]:
            mid=r["material_id"]; v=sums.setdefault(mid,{"material_id":mid,"material":r["material"],"unit":r["unit"],"quantity":0})
            v["quantity"]+=a["quantity"]*r["per"]
    return list(sums.values())

def catalog_write(db,w,rid,op,a):
    raw=encode({"operation":op,"arguments":a})
    existing=db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+rid)).fetchone()
    if existing:
        if existing[0]!=raw:raise Conflict("Идентификатор уже использован.")
        return json.loads(existing[1])
    name=a["name"]; norm=name.casefold()
    if op=="material":
        duplicate=db.execute("SELECT id FROM pm_materials WHERE workspace=? AND normalized=?",(w,norm)).fetchone()
        old=None
        if a["entity_id"]:
            mid,_=entity(db,w,"material",a["entity_id"])
            old=db.execute("SELECT id,pack,unit FROM pm_materials WHERE workspace=? AND id=?",(w,mid)).fetchone()
        if duplicate and (not old or duplicate[0]!=old[0]):raise Conflict("Материал с таким названием уже существует. Выберите его для изменения.")
        if old:
            mid,pack,unit=old
            if (pack,unit)!=(a["pack"],a["unit"]):
                used=db.execute("SELECT 1 FROM pm_recipe WHERE material=?",(mid,)).fetchone()
                movement=db.execute("SELECT 1 FROM pm_book_rows WHERE workspace=? AND type='raw' AND key=?",(w,mid)).fetchone()
                if used or movement:raise Conflict("Единицу или упаковку связанного материала менять нельзя.")
            db.execute("UPDATE pm_materials SET name=?,normalized=?,pack=?,price=?,unit=?,category=?,note=? WHERE id=? AND workspace=?",(name,norm,a["pack"],a["pack_price"],a["unit"],a["category"],a["catalog_note"],mid,w))
        else:
            mid=uuid4().hex
            db.execute("INSERT INTO pm_materials(id,workspace,name,normalized,pack,price,unit,category,note) VALUES(?,?,?,?,?,?,?,?,?)",(mid,w,name,norm,a["pack"],a["pack_price"],a["unit"],a["category"],a["catalog_note"]))
        if not old and a["initial_quantity"]:
            execute(db,w,"init-"+hashlib.sha256(rid.encode()).hexdigest(),"opening",{"material":mid,"quantity":a["initial_quantity"],"total":a["initial_total"],"note":"Начальный остаток при создании материала"})
        ident=mid
    else:
        duplicate=db.execute("SELECT id FROM pm_products WHERE workspace=? AND normalized=?",(w,norm)).fetchone()
        old=entity(db,w,"product",a["entity_id"]) if a["entity_id"] else None
        if duplicate and (not old or duplicate[0]!=old[0]):raise Conflict("Изделие с таким названием уже существует. Выберите его для изменения.")
        ident=old[0] if old else uuid4().hex
        if old:db.execute("UPDATE pm_products SET name=?,normalized=?,category=?,sale_price=?,minutes=?,note=? WHERE id=? AND workspace=?",(name,norm,a["category"],a["sale_price"],a["minutes"],a["catalog_note"],ident,w))
        else:db.execute("INSERT INTO pm_products(id,workspace,name,normalized,category,sale_price,minutes,note) VALUES(?,?,?,?,?,?,?,?)",(ident,w,name,norm,a["category"],a["sale_price"],a["minutes"],a["catalog_note"]))
    result={"id":ident,"kind":op,"summary":"Сохранено: "+name,"arguments":a}
    db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(w,"book:"+rid,raw,encode(result)))
    return result

def execute(db,w,rid,op,args,*,replay=None):
    key_id(rid);a=validate(op,args)
    if not replay and db.execute("SELECT 1 FROM pm_cancelled_events WHERE workspace=? AND rid=?",(w,rid)).fetchone():
        raise Conflict("Запись отменена исторической корректировкой.")
    allow_archived=bool(replay and replay.get("archived"))
    def resolve(kind,ref):return entity(db,w,kind,ref,include_archived=allow_archived)
    def production_recipe(pid):
        if replay and replay.get("recipe") is not None:return replay["recipe"]
        if replay and replay.get("require_frozen"):return None
        return current_recipe(db,w,pid)
    if op in CATALOG+METADATA:
        if db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND rid=?",(w,rid)).fetchone(): raise Conflict("Идентификатор уже использован.")
        return catalog_write(db,w,rid,op,a) if op in CATALOG else extra.metadata_write(db,w,rid,op,a)
    if db.execute("SELECT 1 FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+rid)).fetchone(): raise Conflict("Идентификатор уже использован.")
    raw=encode(a)
    old=db.execute("SELECT kind,args,result FROM pm_book_events WHERE workspace=? AND rid=?",(w,rid)).fetchone()
    if old:
        if old[0]!=op or validate(op,json.loads(old[1]))!=a:raise Conflict("Идентификатор уже использован.")
        return json.loads(old[2])
    eid=replay["id"] if replay else uuid4().hex;seq=db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM pm_book_events").fetchone()[0]
    rows=Rows(db,w,eid);f=dict.fromkeys(FIN,0);res={};reverse_of=None
    summary=""
    if op in ("opening","purchase","writeoff"):
        mid,name=resolve("material",a["material"])
        pack,unit=db.execute("SELECT pack,unit FROM pm_materials WHERE id=? AND workspace=?",(mid,w)).fetchone()
        requested=a["quantity"]
        if op=="writeoff" and requested is None:
            requested=(rows.get("raw",mid) or {}).get("quantity",0)
            if not requested:raise Conflict("Нет остатка для списания.")
        qty=requested*(pack if op=="purchase" and a["purchase_unit"]=="pack" else 1)
        quantity(qty)
        if op=="writeoff":
            value=rows.raw_take(mid,qty,name);f["writeoffs"]=value
        else:
            value=minor(a["total"]);rows.raw_add(mid,qty,value,opening=(op=="opening"))
            if op=="purchase":f["purchases"]=value
        res.update(material_id=mid,material=name,quantity=qty,unit=unit,value_rub=money(value),supplier=a.get("supplier",""))
        summary=FIELDS[op][0]+": "+name+" · "+str(qty)+" "+unit+" · "+money(value)+" ₽"
    elif op=="manufacture":
        pid,name=resolve("product",a["product"]);qty=a["quantity"];extra_cost=minor(a["extra"])
        frozen=production_recipe(pid)
        if frozen is None:raise Conflict("Нет исторической рецептуры выпуска.")
        override=minor(a["cost_override"])*qty if a["cost_override"] is not None else None
        lid,cost,used,actual=rows.produce(pid,name,qty,extra_cost,seq,frozen,override)
        f["production_cash"]=extra_cost;f["valuation"]=actual-cost
        res.update(product_id=pid,product=name,quantity=qty,lot_id=lid,cost_rub=money(cost),materials=used,
                   production_recipe=frozen,actual_cost_rub=money(actual),valuation_rub=money(actual-cost))
        summary=f"Выпуск: {name} · {qty} шт. · себестоимость партии {money(cost)} ₽"
    elif op=="work_start":
        pid,name=resolve("product",a["product"]);qty=a["quantity"];cost_extra=minor(a["extra"])
        frozen=production_recipe(pid)
        if frozen is None:raise Conflict("Нет исторической рецептуры.")
        lid,cost,used,actual=rows.produce(pid,name,qty,cost_extra,seq,frozen,phase="wip")
        f["production_cash"]=cost_extra
        res.update(product_id=pid,product=name,quantity=qty,lot_id=lid,cost_rub=money(cost),materials=used,production_recipe=frozen)
        summary="Начато производство: "+name+" · "+str(qty)+" шт. · "+money(cost)+" ₽"
    elif op=="work_finish":
        pid,name=resolve("product",a["product"]);qty=a["quantity"];cost_extra=minor(a["extra"])
        alloc=rows.take_lots(pid,qty,"wip")
        remain=qty;extra_left=cost_extra;cost=0
        for part in alloc:
            q=part["quantity"];e=prorate(extra_left,q,remain)
            remain-=q;extra_left-=e;v=part["value_minor"]+e;cost+=v
            rows.new_lot({"product_id":pid,"product":name,"quantity":q,"value":v,"initial_quantity":q,"initial_value":v,"seq":seq,"recipe":part["recipe"],"origin":eid,"phase":"ready"})
        f["production_cash"]=cost_extra
        res.update(product_id=pid,product=name,quantity=qty,cost_rub=money(cost))
        summary="Завершено производство: "+name+" · "+str(qty)+" шт. · "+money(cost)+" ₽"
    elif op=="component_transfer":
        pid,name=resolve("product",a["product"]);mid,mname=resolve("material",a["material"]);qty=a["quantity"]
        unit=db.execute("SELECT unit FROM pm_materials WHERE workspace=? AND id=?",(w,mid)).fetchone()[0]
        if unit not in ("шт","компл"):raise ValueError("Полуфабрикат переносится в материал в штуках/комплектах один к одному.")
        alloc=rows.take_lots(pid,qty);cost=sum(x["value_minor"] for x in alloc);rows.raw_add(mid,qty,cost)
        res.update(product_id=pid,product=name,material_id=mid,material=mname,quantity=qty,value_rub=money(cost))
        summary="Полуфабрикат "+name+" → "+mname+" · "+str(qty)+" · "+money(cost)+" ₽"
    elif op=="sale":
        pid,name=resolve("product",a["product"]);qty=a["quantity"]
        price=minor(a["unit_price"]);gross=price*qty
        if gross>MAX_M:raise ValueError("Слишком большая сумма.")
        paid=minor(a["paid_amount"])
        if paid>gross:raise ValueError("Оплата превышает сумму продажи.")
        ready=sum(v["quantity"] for _,v in rows.lots(pid))
        frozen=production_recipe(pid)
        if ready<qty:
            if not a["auto_produce"]:raise Conflict("Недостаточно готовых изделий. Разрешите изготовление недостающего объёма.")
            if frozen is None:raise Conflict("Нет зафиксированной исторической рецептуры для дополнительного выпуска.")
            rows.produce(pid,name,qty-ready,0,seq,frozen)
        alloc=rows.take_lots(pid,qty);physical=sum(x["value_minor"] for x in alloc)
        cost=minor(a["cost_override"])*qty if a["cost_override"] is not None else physical
        if cost>MAX_M:raise ValueError("Слишком большая себестоимость.")
        for x in alloc:
            x["reported_value"]=x["quantity"]*minor(a["cost_override"]) if a["cost_override"] is not None else x["value_minor"]
            x["returned_reported"]=0;x["restored_value"]=0;x["restored_reported"]=0
        rows.put("sale",eid,{"product_id":pid,"product":name,"quantity":qty,"returned":0,"price":price,"paid":paid,"channel":a["channel"],"day":a["day"],"allocations":alloc})
        f.update(revenue=gross,cogs=cost,receipts=paid)
        res.update(product_id=pid,product=name,quantity=qty,channel=a["channel"],sale_id=eid,
                   revenue_rub=money(gross),cogs_rub=money(cost),paid_rub=money(paid),due_rub=money(gross-paid),sales_quantity=qty,consumption=material_usage(alloc),physical_cogs_rub=money(physical),production_recipe=frozen)
        summary=f"Продажа: {name} · {qty} шт. · выручка {money(gross)} ₽ · себестоимость {money(cost)} ₽"
    elif op=="payment":
        sid=a["sale"];sale=rows.sale(sid)
        if a["day"]<sale["day"]:raise ValueError("Оплата не может быть раньше продажи.")
        value=minor(a["amount"],False);gross=(sale["quantity"]-sale["returned"])*sale["price"]
        if sale["paid"]+value>gross:raise Conflict("Сумма превышает долг покупателя.")
        sale["paid"]+=value;rows.put("sale",sid,sale);f["receipts"]=value
        res.update(sale_id=sid,product_id=sale["product_id"],product=sale["product"],channel=sale["channel"],paid_rub=money(value),due_rub=money(gross-sale["paid"]))
        summary=f"Получена оплата: {money(value)} ₽"
    elif op=="sale_fee":
        sid=a["sale"];sale=rows.sale(sid);value=minor(a["total"],False)
        if a["day"]<sale["day"]:raise ValueError("Удержание не может быть раньше продажи.")
        f["expenses"]=value
        res.update(sale_id=sid,product_id=sale["product_id"],product=sale["product"],channel=sale["channel"],category=a["category"],value_rub=money(value))
        summary="Удержание по продаже: "+a["category"]+" · "+money(value)+" ₽"
    elif op=="sale_fee_refund":
        row=db.execute("SELECT result,finance,day FROM pm_book_events WHERE workspace=? AND id=? AND kind='sale_fee'",(w,a["event"])).fetchone()
        if not row or db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND reverse_of=?",(w,a["event"])).fetchone():raise Conflict("Удержание недоступно.")
        original=json.loads(row[0]);value=minor(a["total"],False)
        if a["day"]<row[2]:raise ValueError("Возврат раньше удержания.")
        refunds=db.execute("SELECT result,finance FROM pm_book_events WHERE workspace=? AND kind='sale_fee_refund'",(w,)).fetchall()
        already=sum(-json.loads(fin)["expenses"] for r,fin in refunds if json.loads(r).get("fee_id")==a["event"] and not db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND reverse_of=?",(w,json.loads(r)["id"])).fetchone())
        if already+value>json.loads(row[1])["expenses"]:raise Conflict("Возврат превышает сумму удержания.")
        rows.sale(original["sale_id"]);f["expenses"]=-value
        res.update({k:original[k] for k in ("sale_id","product_id","product","channel","category")});res.update(fee_id=a["event"],value_rub=money(value))
        summary="Возврат удержания: "+money(value)+" ₽"
    elif op=="return":
        sid=a["sale"];sale=rows.sale(sid);qty=a["quantity"];refund=minor(a["refund"])
        if a["day"]<sale["day"]:raise ValueError("Возврат не может быть раньше продажи.")
        if qty>sale["quantity"]-sale["returned"]:raise Conflict("Возврат превышает остаток продажи.")
        gross=qty*sale["price"];remaining=(sale["quantity"]-sale["returned"]-qty)*sale["price"]
        if refund>gross or refund>sale["paid"] or sale["paid"]-refund>remaining:
            raise Conflict("Сумма возврата не соответствует фактической оплате и остатку долга.")
        left=qty;returned=[];restored=0;reported_restored=0
        for alloc in sale["allocations"]:
            avail=alloc["quantity"]-alloc["returned"]
            if not avail or not left:continue
            take=min(avail,left);cost=prorate(alloc["value_minor"]-alloc["returned_value"],take,avail)
            report_value=alloc.get("reported_value",alloc["value_minor"])
            report_returned=alloc.get("returned_reported",alloc["returned_value"])
            reported=prorate(report_value-report_returned,take,avail)
            alloc["returned"]+=take;alloc["returned_value"]+=cost;alloc["returned_reported"]=report_returned+reported;left-=take
            returned.append({"quantity":take,"recipe":alloc["recipe"]})
            if a["restock"]:
                rows.new_lot({"product_id":sale["product_id"],"product":sale["product"],"quantity":take,"value":cost,"initial_quantity":take,"initial_value":cost,"seq":seq,"recipe":alloc["recipe"],"origin":eid})
                restored+=cost;reported_restored+=reported
                alloc["restored_value"]=alloc.get("restored_value",0)+cost
                alloc["restored_reported"]=alloc.get("restored_reported",0)+reported
        if left:raise Conflict("Нарушена история партий продажи.")
        sale["returned"]+=qty;sale["paid"]-=refund;rows.put("sale",sid,sale)
        f.update(revenue=-gross,cogs=-reported_restored,receipts=-refund)
        usage=material_usage(returned)
        for u in usage:u["quantity"]=-u["quantity"]
        res.update(sale_id=sid,product_id=sale["product_id"],product=sale["product"],channel=sale["channel"],quantity=qty,
                   sales_quantity=-qty,consumption=usage,restocked=a["restock"],refund_rub=money(refund),restored_cost_rub=money(restored),reported_restored_cost_rub=money(reported_restored))
        summary=f"Возврат: {qty} шт. · возвращено денег {money(refund)} ₽"
    elif op in ("expense","worker_payment"):
        value=minor(a["total"],False);f["expenses"]=value
        category=a.get("category","Оплата труда")
        if op=="worker_payment":
            ident=extra.find(db,w,"pm_workers",a["worker_id"])
            worker=db.execute("SELECT name,archived FROM pm_workers WHERE workspace=? AND id=?",(w,ident)).fetchone()
            if worker[1] and not allow_archived:raise Conflict("Работник в архиве.")
            res.update(worker_id=ident,worker=worker[0])
        res.update(category=category,value_rub=money(value));summary=f"Расход: {category} · {money(value)} ₽"
    elif op=="asset_acquire":
        cost=minor(a["total"],False);residual=minor(a["residual"])
        if residual>cost or a["months"]>1200:raise ValueError("Проверьте ликвидационную стоимость и срок службы (1–1200 месяцев).")
        v={"name":a["name"],"cost":cost,"residual":residual,"months":a["months"],"acquired":a["day"],"paid":a["paid"],"note":a["note"]}
        assets.life(v);rows.put("asset",eid,v)
        f["capex"]=cost if a["paid"] else 0
        res.update(asset_id=eid,asset=a["name"],value_rub=money(cost));summary="Оборудование: "+a["name"]+" · "+money(cost)+" ₽"
    elif op=="asset_retire":
        ident=a["asset_id"];v=rows.get("asset",ident)
        if not v or v.get("retired"):raise Conflict("Оборудование недоступно.")
        if a["day"]<v["acquired"]:raise ValueError("Выбытие раньше приобретения.")
        proceeds=minor(a["total"]);book_value=v["cost"]-assets.accumulated(v,date.fromisoformat(a["day"])-timedelta(days=1))
        v["retired"]=a["day"];rows.put("asset",ident,v)
        f["asset_proceeds"]=proceeds;f["asset_disposal"]=book_value-proceeds
        res.update(asset_id=ident,asset=v["name"],value_rub=money(book_value),proceeds_rub=money(proceeds))
        summary="Выбытие: "+v["name"]+" · остаточная стоимость "+money(book_value)+" ₽"
    elif op=="reverse":
        reverse_of=a["event"]
        row=db.execute("SELECT kind,day,result,changes,finance,rid FROM pm_book_events WHERE workspace=? AND id=?",(w,reverse_of)).fetchone()
        if not row or row[0] in ("reverse","asset_acquire","asset_retire"):raise ValueError("Операция недоступна для сторно. Для оборудования используйте историческое исправление.")
        if row[5].startswith("ext-"):raise Conflict("Внешние заказы корректируются через возврат или событие источника.")
        if db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND reverse_of=?",(w,reverse_of)).fetchone():raise Conflict("Операция уже сторнирована.")
        if a["day"]<row[1]:raise ValueError("Сторно не может быть раньше операции.")
        if not a["reason"]:raise ValueError("Укажите причину.")
        if row[0] in ("sale","sale_fee"):
            if any(json.loads(r[0]).get("sale_id" if row[0]=="sale" else "fee_id")==reverse_of for r in db.execute(
                """SELECT result FROM pm_book_events e WHERE e.workspace=? AND e.kind IN ('sale_fee','sale_fee_refund')
                   AND NOT EXISTS(SELECT 1 FROM pm_book_events v WHERE v.workspace=e.workspace AND v.reverse_of=e.id)""",(w,))):
                raise Conflict("Сначала исправьте связанные удержания и возвраты.")
        changes=json.loads(row[3])
        for c in changes:
            if rows.get(c["type"],c["key"])!=c["after"]:raise Conflict("Есть последующие зависимые движения. Сначала исправьте их.")
        for c in reversed(changes):rows.put(c["type"],c["key"],c["before"],restore=True)
        old_fin=json.loads(row[4]);f={k:-old_fin.get(k,0) for k in FIN}
        original=json.loads(row[2])
        res.update({k:original[k] for k in ("product_id","product","material_id","material","channel","category","sale_id","worker_id","worker","fee_id") if k in original})
        res.update(sales_quantity=-original.get("sales_quantity",0),
                   consumption=[{**u,"quantity":-u["quantity"]} for u in original.get("consumption",[])],
                   original_kind=row[0],reverse_of=reverse_of,reason=a["reason"])
        summary="Сторно: "+original["summary"]
    stock=any(t in ("raw","lot") for t,k in rows.changes)
    if stock:
        last=db.execute("SELECT MAX(day) FROM pm_book_events WHERE workspace=? AND stock=1",(w,)).fetchone()[0]
        if last and a["day"]<last:raise Conflict("Дата раньше последнего складского движения. Ретроспективная переоценка пока не поддерживается.")
    res.update(id=eid,kind=op,day=a["day"],summary=summary,note=a["note"],arguments=a,
               finance={k:money(v) for k,v in f.items()})
    rows.flush()
    db.execute("INSERT INTO pm_book_events(seq,id,workspace,rid,kind,day,args,result,changes,finance,stock,reverse_of) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (seq,eid,w,rid,op,a["day"],raw,encode(res),encode(list(rows.changes.values())),encode(f),int(stock),reverse_of))
    return res

def revision(db,w,op,args):
    catalog=[list(r) for r in db.execute("SELECT id,name,pack,price,unit,category,archived,note FROM pm_materials WHERE workspace=? ORDER BY id",(w,))]
    products=[list(r) for r in db.execute("SELECT id,name,category,sale_price,minutes,archived,note FROM pm_products WHERE workspace=? ORDER BY id",(w,))]
    recipe=[list(r) for r in db.execute("SELECT r.product,r.material,r.qty FROM pm_recipe r JOIN pm_products p ON p.id=r.product WHERE p.workspace=? ORDER BY r.product,r.material",(w,))]
    last=db.execute("SELECT COALESCE(MAX(seq),0) FROM pm_book_events WHERE workspace=?",(w,)).fetchone()[0]
    return hashlib.sha256(encode([w,op,args,last,catalog,products,recipe,extra.settings_revision(db,w),corrections.revision_state(db,w),today().isoformat()]).encode()).hexdigest()

def preview_action(db,w,op,args):
    a=validate(op,args);rev=revision(db,w,op,a)
    db.execute("SAVEPOINT pm_preview")
    try:
        result=execute(db,w,"preview-"+uuid4().hex,op,a)
        preview={k:result[k] for k in ("summary","finance","quantity","cost_rub","cogs_rub","revenue_rub","due_rub","value_rub","restored_cost_rub") if k in result}
    finally:
        db.execute("ROLLBACK TO pm_preview")
        db.execute("RELEASE pm_preview")
    return {"operation":op,"arguments":a,"revision":rev,"preview":preview,"workshop":w}

def preview_for_user(store,token,op,args,workshop_id=None):
    from . import podmasterye_workshops as workshops
    with store._write() as db:
        _,a=_principal(db,token);w=workshops.resolve(db,a,workshop_id)
        return preview_action(db,w,op,args)

def mutate(store,token,rid,op,args,expected,workshop_id=None):
    from . import podmasterye_workshops as workshops
    with store._write() as db:
        _,account=_principal(db,token);w=workshops.resolve(db,account,workshop_id)
        key_id(rid);a=validate(op,args)
        prior=db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND rid=?",(w,rid)).fetchone() or db.execute("SELECT 1 FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+rid)).fetchone()
        if not prior and (not isinstance(expected,str) or revision(db,w,op,a)!=expected):
            raise Conflict("Данные изменились. Выполните предварительный расчёт заново.")
        return execute(db,w,rid,op,a)

def period(start=None,end=None):
    end=end or today().isoformat()
    start=start or "0001-01-01"
    for x in (start,end):
        if not isinstance(x,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",x):raise ValueError("Некорректный период.")
        date.fromisoformat(x)
    if start>end or end>today().isoformat():raise ValueError("Некорректный период.")
    return start,end

def totals(f):
    g=f["revenue"]-f["cogs"];net=g-f["expenses"]-f["writeoffs"]-f.get("valuation",0)-f.get("depreciation",0)-f.get("asset_disposal",0)
    cash=f["receipts"]-f["purchases"]-f["expenses"]-f["production_cash"]-f.get("capex",0)+f.get("asset_proceeds",0)
    return {**{k:money(v) for k,v in f.items()},"gross_profit":money(g),"net_profit":money(net),"cashflow":money(cash),
            "margin_percent":format((Decimal(g)*100/f["revenue"]).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if f["revenue"]>0 else None}
def aggregate(events):
    f=dict.fromkeys(FIN,0);wages=fees=0
    for r,fin in events:
        for k in FIN:f[k]+=fin.get(k,0)
        if r.get("worker_id"):wages+=fin.get("expenses",0)
        if r.get("sale_id"):fees+=fin.get("expenses",0)
    return {**totals(f),"worker_payments":money(wages),"sale_fees":money(fees),"other_expenses":money(f["expenses"]-wages-fees)}
def grouped(events,key):
    groups={}
    for r,f in events:
        if not r.get(key):continue
        if key in ("product_id","channel") and not any(f.get(k,0) for k in ("revenue","cogs","receipts","expenses")) and not r.get("sales_quantity"):continue
        if key=="category" and not f["expenses"]:continue
        k=r[key];g=groups.setdefault(k,{"name":r.get("product",k) if key=="product_id" else k,"events":[],"quantity":0})
        g["events"].append((r,f));g["quantity"]+=r.get("sales_quantity",0)
    return [{"key":k,"name":v["name"],"quantity":v["quantity"],**aggregate(v["events"])} for k,v in sorted(groups.items(),key=lambda kv:kv[1]["name"])]
def event_rows(db,w,start,end):
    reverse={r[0] for r in db.execute("SELECT reverse_of FROM pm_book_events WHERE workspace=? AND reverse_of IS NOT NULL",(w,))}
    out=[]
    for rid,s,f,request_id in db.execute("SELECT id,result,finance,rid FROM pm_book_events WHERE workspace=? AND day BETWEEN ? AND ? ORDER BY day,seq",(w,start,end)):
        r=json.loads(s);r["reversed"]=rid in reverse;r["external"]=request_id.startswith("ext-");out.append((r,json.loads(f)))
    out.extend(assets.report(db,w,start,end)[1]);out.sort(key=lambda x:x[0]["day"])
    return out

def report(db,w,start=None,end=None,horizon=30,lead=7,safety=3,view="all",limit=100,offset=0,event_group="all",target_profit="200",source="ledger",_unpaginated=False):
    start,end=period(start,end)
    for v in (horizon,lead,safety):
        if type(v) is not int or not 0<=v<=365:raise ValueError("Некорректный горизонт закупки.")
    if horizon==0:raise ValueError("Горизонт должен быть положительным.")
    if type(limit) is not int or not 1<=limit<=500 or type(offset) is not int or not 0<=offset<=10**7:raise ValueError("Некорректная страница.")
    quality_policy=quality.policy(db,w);return_defect,scrap=quality.rates(quality_policy)
    rows=Rows(db,w,"read")
    initial={}
    for r,fin in event_rows(db,w,"0001-01-01",today().isoformat()):
        if r["kind"]=="opening" and not r.get("reversed"):
            initial[r["material_id"]]=(r["quantity"],r["value_rub"])
    mats=[]
    for mid,name,pack,price,unit,cat,archived,note in db.execute("SELECT id,name,pack,price,unit,category,archived,note FROM pm_materials WHERE workspace=? ORDER BY normalized",(w,)):
        r=rows.get("raw",mid);qty=r["quantity"] if r else 0;value=r["value"] if r else 0
        avg=Decimal(value)/100/qty if qty else None
        mats.append(dict(id=mid,name=name,pack=pack,planned_pack_price=price,unit=unit,category=cat,quantity=qty,valued=r is not None,
                         archived=bool(archived),note=note,initial_quantity=initial.get(mid,(None,None))[0],initial_value_rub=initial.get(mid,(None,None))[1],
                         initial_unit_price_rub=format((Decimal(initial[mid][1])/initial[mid][0]).quantize(Decimal(".000001"),rounding=ROUND_HALF_UP),"f") if mid in initial else None,
                         value_rub=money(value),average_price_rub=format(avg.quantize(Decimal(".000001"),rounding=ROUND_HALF_UP),"f") if avg is not None else None))
    bymid={m["id"]:m for m in mats};products=[];byprod={}
    photo_ids={r[0] for r in db.execute("SELECT product FROM pm_product_photos WHERE workspace=?",(w,))}
    for pid,name,cat,price,minutes,archived,note in db.execute("SELECT id,name,category,sale_price,minutes,archived,note FROM pm_products WHERE workspace=? ORDER BY normalized",(w,)):
        lots=rows.lots(pid);qty=sum(v["quantity"] for _,v in lots);value=sum(v["value"] for _,v in lots)
        wip=rows.lots(pid,"wip");wip_qty=sum(v["quantity"] for _,v in wip);wip_value=sum(v["value"] for _,v in wip)
        recipe=[];cost=Decimal(0);known=True
        for mid,per in db.execute("SELECT material,qty FROM pm_recipe WHERE product=? ORDER BY material",(pid,)):
            m=bymid.get(mid)
            if not m:raise Conflict("Нарушена привязка рецептуры.")
            raw=rows.get("raw",mid)
            if raw and raw["quantity"]: unitcost=Decimal(raw["value"])/100/raw["quantity"]
            elif m["planned_pack_price"] is not None:unitcost=Decimal(m["planned_pack_price"])/m["pack"]
            else:unitcost=None
            if unitcost is None:known=False
            else:cost+=unitcost*per
            recipe.append({"material_id":mid,"material":m["name"],"unit":m["unit"],"usage":per})
        v=dict(id=pid,name=name,category=cat,sale_price=price,minutes=minutes,archived=bool(archived),note=note,has_photo=pid in photo_ids,quantity=qty,value_rub=money(value),wip_quantity=wip_qty,wip_value_rub=money(wip_value),recipe=recipe,
               estimated_material_cost_rub=format(cost.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if known and recipe else None,
               planned_material_cost_with_scrap_rub=format(quality.material_input(cost,scrap).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if known and recipe else None)
        products.append(v);byprod[pid]=v
    events=event_rows(db,w,start,end)
    asset_rows,_=assets.report(db,w,start,end)
    summary=aggregate(events)
    summary.update(sale_records=sum(1 if r["kind"]=="sale" else -1 if r.get("original_kind")=="sale" else 0 for r,f in events),
                   sales_quantity=sum(r.get("sales_quantity",0) for r,f in events),
                   raw_inventory_rub=money(sum(int(Decimal(m["value_rub"])*100) for m in mats)),
                   finished_inventory_rub=money(sum(int(Decimal(p["value_rub"])*100) for p in products)))
    summary["wip_inventory_rub"]=format(sum((Decimal(p["wip_value_rub"]) for p in products),Decimal(0)),".2f")
    summary["equipment_book_rub"]=format(sum((Decimal(a["book_value_rub"]) for a in asset_rows),Decimal(0)),".2f")
    summary["inventory_rub"]=format(Decimal(summary["raw_inventory_rub"])+Decimal(summary["finished_inventory_rub"])+Decimal(summary["wip_inventory_rub"]),".2f")
    batch_dates=dict(db.execute("SELECT id,day FROM pm_book_events WHERE workspace=?",(w,)))
    batches=[]
    for (t,k),lot in rows.rows.items():
        if t=="lot":
            batches.append({"id":k,"product_id":lot["product_id"],"product":lot["product"],"day":batch_dates.get(lot["origin"]),
              "initial_quantity":lot.get("initial_quantity"),"initial_value_rub":money(lot["initial_value"]) if "initial_value" in lot else None,
              "quantity":lot["quantity"],"value_rub":money(lot["value"]),"seq":lot["seq"],"phase":lot.get("phase","ready")})
    batches.sort(key=lambda x:(x["seq"],x["id"]),reverse=True)
    consumption={}
    for r,f in events:
        for u in r.get("consumption",[]):
            v=consumption.setdefault(u["material_id"],{"material_id":u["material_id"],"material":u["material"],"unit":u["unit"],"quantity":0})
            v["quantity"]+=u["quantity"]
    for v in consumption.values():
        mat=bymid.get(v["material_id"])
        v["pack_equivalent"]=format((Decimal(v["quantity"])/mat["pack"]).quantize(Decimal(".001"),rounding=ROUND_HALF_UP),"f") if mat else None
    sales=[]
    lifetime=events if start=="0001-01-01" and end==today().isoformat() else event_rows(db,w,"0001-01-01",today().isoformat())
    sale_cogs={};sale_fees={}
    sale_note={}
    for r,f in lifetime:
        sid=r.get("sale_id")
        if sid:
            sale_cogs[sid]=sale_cogs.get(sid,0)+f.get("cogs",0)
            sale_fees[sid]=sale_fees.get(sid,0)+f.get("expenses",0)
            if r["kind"]=="sale":sale_note[sid]=r.get("note","")
    for (t,k),s in rows.rows.items():
        if t!="sale":continue
        gross=(s["quantity"]-s["returned"])*s["price"]
        actual=sale_cogs.get(k,0);fees=sale_fees.get(k,0)
        sales.append({"id":k,"product":s["product"],"product_id":s["product_id"],"channel":s["channel"],"day":s["day"],"quantity":s["quantity"],"returned":s["returned"],
                      "gross_rub":money(gross),"unit_price_rub":money(s["price"]),"cogs_rub":money(actual),"profit_rub":money(gross-actual-fees),"fees_rub":money(fees),"net_receipts_rub":money(s["paid"]-fees),"note":sale_note.get(k,""),"paid_rub":money(s["paid"]),"due_rub":money(gross-s["paid"])})
    sales.sort(key=lambda x:(x["day"],x["id"]),reverse=True)
    summary["current_receivables_rub"]=format(sum((Decimal(s["due_rub"]) for s in sales),Decimal(0)),".2f")
    monthly={}
    for r,f in events:monthly.setdefault(r["day"][:7],[]).append((r,f))
    history_start=(today()-timedelta(days=29)).isoformat()
    recent=events if start==history_start and end==today().isoformat() else event_rows(db,w,history_start,today().isoformat())
    sales_parts=quality.sales_components(recent)
    demand={pid:quality.replacement_demand(v["delivered"],v["returned"],return_defect) for pid,v in sales_parts.items()}
    market_sales=None;planning_problems=[]
    if source!="ledger":
        from . import podmasterye_market_analytics as analytics
        market_sales=analytics.planning_sales(db,w,from_=history_start,to=today().isoformat(),source=source)
        demand={}
        if not market_sales["complete"]:
            planning_problems.append({"reason":"История маркетплейсов не подтверждена полностью.","details":market_sales["problems"]})
        for p in market_sales["rows"]:
            pid=p["product_id"];net=p["estimated_net"];returned=p["estimated_physical_returns"]
            if not pid:
                planning_problems.append({"sku":p["skus"],"reason":"Артикул не сопоставлен с изделием."});continue
            if not p["material_net_supported"]:
                planning_problems.append({"product_id":pid,"reason":"Календарный возврат не подтверждает физический возврат изделия; материальная потребность по чистым продажам неизвестна."});continue
            if net is None or return_defect and returned is None:
                planning_problems.append({"product_id":pid,"reason":"Не подтверждены коэффициент потерь или физические возвраты."});continue
            if pid not in byprod or byprod[pid].get("archived") or not byprod[pid]["recipe"]:
                planning_problems.append({"product_id":pid,"reason":"Изделие недоступно или не имеет рецептуры."});continue
            if any(line["material_id"] not in bymid or bymid[line["material_id"]]["archived"] for line in byprod[pid]["recipe"]):
                planning_problems.append({"product_id":pid,"reason":"Рецептура содержит недоступные материалы."});continue
            demand[pid]=Decimal(str(net))+Decimal(str(returned or 0))*return_defect
    cons={}
    for r,f in recent:
        for u in r.get("consumption",[]):cons[u["material_id"]]=cons.get(u["material_id"],0)+u["quantity"]
    if market_sales is not None:
        # This is a current-recipe sales equivalent, never an inventory posting.
        cons={}
        for p in market_sales["rows"]:
            if p["product_id"] in byprod and p["net"] is not None:
                for line in byprod[p["product_id"]]["recipe"]:
                    mid=line["material_id"];cons[mid]=cons.get(mid,0)+Decimal(str(p["net"]))*line["usage"]
    plans=[]
    for m in mats:
        mid=m["id"];sold_equiv=cons.get(mid,0);daily=Decimal(0);need=Decimal(0);coverage_days=[]
        for pid,n in demand.items():
            if n<=0 or pid not in byprod:continue
            p=byprod[pid]
            if p.get("archived") or m.get("archived"):continue
            per=next((r["usage"] for r in p["recipe"] if r["material_id"]==mid),0)
            if not per:continue
            # Keep the exact numerator over 30 days until the last division.
            # This avoids a whole extra package due to recurring decimal rates.
            daily+=n*per
            products_needed=int((n*horizon/30).to_integral_value(rounding="ROUND_CEILING"))
            need+=max(0,products_needed-p["quantity"]-p["wip_quantity"])*30*per
        nominal_need=need/30
        denom=Decimal(30)*(1-scrap)
        short_numerator=max(Decimal(0),need+daily*safety-m["quantity"]*denom)
        packs=int((short_numerator/(denom*m["pack"])).to_integral_value(rounding="ROUND_CEILING")) if daily else 0
        need=quality.material_input(need,scrap)/30
        daily=quality.material_input(daily,scrap)/30
        days=Decimal(m["quantity"])/daily if daily else None
        # Conservative reorder threshold: raw stock only. Quantity forecast also accounts for finished goods.
        trigger=days is not None and days<=lead+safety
        until=max(0,int(days)-lead-safety) if days is not None else None
        order_day=(today()+timedelta(days=min(until,36500))).isoformat() if until is not None and until<=36500 else None
        plans.append({"material_id":mid,"material":m["name"],"unit":m["unit"],"sold_equivalent_units":int(sold_equiv) if Decimal(sold_equiv)==Decimal(sold_equiv).to_integral_value() else format(sold_equiv,"f"),
                     "sold_equivalent_packs":format((Decimal(sold_equiv)/m["pack"]).quantize(Decimal(".001"),rounding=ROUND_HALF_UP),"f"),
                     "daily_forecast":format(daily.quantize(Decimal(".001"),rounding=ROUND_HALF_UP),"f"),
                     "raw_days":format(days.quantize(Decimal(".1"),rounding=ROUND_HALF_UP),"f") if days is not None else None,
                     "buy_packs":packs,"order_now":trigger,"order_day":order_day,"history_from":history_start,"history_to":today().isoformat(),
                     "buy_quantity":packs*m["pack"],
                     "nominal_production_need":format(nominal_need,"f"),
                     "production_scrap_need":format(need-nominal_need,"f"),
                     "gross_production_need":format(need,"f")})
    # Explicit current stock vs period financial flows. Pagination never truncates aggregates.
    groups={"all":None,"stock":{"opening","writeoff"},"purchases":{"purchase"},"manufacture":{"manufacture","work_start","work_finish","component_transfer"},"sales":{"sale","payment","return","sale_fee","sale_fee_refund"},"expenses":{"expense","worker_payment","sale_fee","sale_fee_refund"},"workers":{"worker_payment"},"assets":{"asset_acquire","asset_retire","depreciation"}}
    if event_group not in groups:raise ValueError("Неизвестный раздел журнала.")
    kinds=groups[event_group]
    allrows=[r for r,f in reversed(events) if kinds is None or r.get("original_kind",r["kind"]) in kinds]
    data={"period":{"from":start,"to":end},"summary":summary,"materials":mats,"products":products,"sales":sales,"batches":batches,"consumption":list(consumption.values()),
          "events":allrows if _unpaginated else allrows[offset:offset+limit],"event_count":len(allrows),"offset":0 if _unpaginated else offset,"limit":len(allrows) if _unpaginated else limit,
          "monthly":[{"month":k,**aggregate(v)} for k,v in sorted(monthly.items())],"by_product":grouped(events,"product_id"),
          "by_channel":grouped(events,"channel"),"by_expense":grouped(events,"category"),
          "planning":[] if planning_problems else plans,"planning_complete":not planning_problems,"planning_problems":planning_problems,
          "market_sales":market_sales,"quality_policy":quality_policy,"planning_settings":{"horizon":horizon,"lead":lead,"safety":safety,"source":source},
          "forms":forms(),"units":UNITS,"expense_categories":CATEGORIES,"today":today().isoformat(),
          "assumptions":"Склад на текущий момент; финансовые показатели за выбранный период. Прогноз по продажам за 30 календарных дней, возвратам с учётом указанного брака, текущим нормам, производственным потерям и готовому остатку; незаданные коэффициенты не учитываются. Нет резервов и поставок в пути. Налоги и комиссии — только введённые расходы; амортизация и переоценка неденежные. Плановые накладные не списываются повторно в фактической прибыли."}
    data["assets"]=asset_rows
    data.update(extra.additional_data(db,w,products,mats,events,target_profit))
    parts=("cogs","other_expenses","worker_payments","sale_fees","writeoffs","valuation","depreciation","asset_disposal","net_profit")
    rev=Decimal(summary["revenue"])
    data["distribution"]=[{"key":k,"amount_rub":summary[k],"percent":format((Decimal(summary[k])*100/rev).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if rev>0 else None} for k in parts]
    if view in ("all","planning"):
        from .podmasterye_seasonal import consumption_actual
        data["actual_consumption"]=consumption_actual(db,w,start,end)
    if view in ("all","journal"):data["corrections"]=corrections.history(db,w)
    if view=="all":return data
    allowed={"summary":("summary","period","assumptions"),"stock":("materials","products","batches","summary","assumptions"),
             "sales":("sales","by_product","by_channel","period","market_sales"),"planning":("planning","planning_complete","planning_problems","market_sales","planning_settings","quality_policy","consumption","actual_consumption","period","assumptions"),
             "finance":("summary","monthly","by_product","by_channel","by_expense","period","assumptions","distribution"),
             "journal":("events","event_count","offset","limit","period","corrections"),
             "tasks":("tasks","workshop","reminders"),"workers":("workers","period"),"unit":("unit_economics","target_profit","unit_period","channel_rates","cost_policy","quality_policy"),
             "catalog":("materials","products","workshop","stock_categories","recipe_versions","quality_policy"),"assets":("assets","summary","period")}
    if view not in allowed:raise ValueError("Неизвестный отчёт.")
    return {k:data[k] for k in allowed[view]}

def read(store,token,workshop_id=None,**opts):
    from . import podmasterye_workshops as workshops
    with store._lock:
        _,a=_principal(store._db,token);w=workshops.resolve(store._db,a,workshop_id)
        return report(store._db,w,**opts)
def export(store,token,fmt,workshop_id=None):
    from . import podmasterye_workshops as workshops
    with store._lock:
        _,a=_principal(store._db,token);w=workshops.resolve(store._db,a,workshop_id)
        records=event_rows(store._db,w,"0001-01-01",today().isoformat())
        d=report(store._db,w)
        d["corrections"]=corrections.history(store._db,w,limit=None)
        d["recipe_versions"]=[dict(id=seq,product_id=pid,day=day,recipe=json.loads(snapshot)) for seq,pid,day,snapshot in store._db.execute(
            "SELECT seq,product,day,snapshot FROM pm_recipe_versions WHERE workspace=? ORDER BY seq DESC",(w,))]
    headings=["Дата","Операция","ID","Описание","Заметка","Выручка","COGS","Расходы","Списания","Закупки","Поступления","Прямые затраты выпуска","Переоценка партий (неденежная)","Капвложения","Поступления от выбытия","Результат выбытия (расход)","Амортизация"]
    def safe(v):
        # Avoid spreadsheet formula injection from externally supplied names/notes.
        return "'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r") else v
    body=[[r["day"],r["kind"],r["id"],safe(r["summary"]),safe(r["note"]),*[money(f.get(k,0)) for k in FIN]] for r,f in records]
    if fmt=="csv":
        s=io.StringIO();writer=csv.writer(s,delimiter=";");writer.writerow(headings);writer.writerows(body)
        return ("\ufeff"+s.getvalue()).encode("utf-8"),"text/csv; charset=utf-8"
    tables=[
        ("Журнал",headings,body),
        ("Сырьё",["id","name","category","unit","pack","planned_pack_price","quantity","value_rub","average_price_rub","initial_quantity","initial_value_rub","initial_unit_price_rub","archived","note"],d["materials"]),
        ("Готовые изделия",["id","name","category","sale_price","minutes","quantity","value_rub","wip_quantity","wip_value_rub","estimated_material_cost_rub","planned_material_cost_with_scrap_rub","planned_labor_rub","planned_overhead_rub","planned_full_cost_rub","material_margin_percent","archived","note"],d["products"]),
        ("Рецептуры",["product_id","product","material_id","material","unit","usage"],[{**r,"product":p["name"],"product_id":p["id"]} for p in d["products"] for r in p["recipe"]]),
        ("Партии",["id","day","product_id","product","phase","initial_quantity","initial_value_rub","quantity","value_rub"],d["batches"]),
        ("Продажи",["id","day","product_id","product","channel","quantity","returned","unit_price_rub","gross_rub","cogs_rub","fees_rub","profit_rub","paid_rub","net_receipts_rub","due_rub","note"],d["sales"]),
        ("По месяцам",["month","revenue","cogs","gross_profit","expenses","other_expenses","worker_payments","sale_fees","writeoffs","valuation","depreciation","asset_disposal","net_profit","purchases","receipts","production_cash","capex","asset_proceeds","cashflow"],d["monthly"]),
        ("По товарам",["key","name","quantity","revenue","cogs","gross_profit","sale_fees","net_profit","receipts","margin_percent"],d["by_product"]),
        ("По каналам",["key","name","quantity","revenue","cogs","gross_profit","sale_fees","net_profit","receipts","margin_percent"],d["by_channel"]),
        ("Расходы по статьям",["name","expenses"],d["by_expense"]),
        ("Оборудование",["id","name","acquired","months","retired","cost_rub","residual_rub","depreciation_rub","book_value_rub","monthly_norm_rub","paid","note"],d["assets"]),
        ("Задачи",["id","name","description","due","priority","category","status","remind_days","updated"],d["tasks"]),
        ("Работники",["id","name","position","archived","payments_rub"],d["workers"]),
        ("Тарифы каналов",["channel","commission_percent","fixed_fee_rub"],d["channel_rates"]),
        ("Политика накладных",list(d["cost_policy"]),[d["cost_policy"]]),
        ("Коэффициенты брака",list(d["quality_policy"]),[d["quality_policy"]]),
        ("Юнит экономика 90 дней",["product","channel","quantity_90d","average_price_rub","actual_cogs_per_unit_rub","actual_fees_per_unit_rub","actual_profit_per_unit_rub","actual_receipts_rub","planned_material_cost_rub","planned_overhead_rub","planned_full_cost_rub","planned_proceeds_rub","planned_profit_rub","recommended_price_rub","cost_basis","rate_known"],d["unit_economics"]),
        ("План закупок",["material","unit","sold_equivalent_units","sold_equivalent_packs","daily_forecast","raw_days","buy_packs","buy_quantity","order_day","order_now"],d["planning"]),
        ("История рецептур",["id","product_id","day","recipe"],[{**r,"recipe":encode(r["recipe"])} for r in d["recipe_versions"]]),
        ("Исправления",["id","target","action","reason","day","summary"],[{**r,"summary":r["result"]["summary"]} for r in d["corrections"]]),
    ]
    numeric=set(FIN)|{"pack","quantity","minutes","wip_quantity","usage","initial_quantity","returned","months","remind_days","productive_hours","quantity_90d","sold_equivalent_units","sold_equivalent_packs","daily_forecast","raw_days","buy_packs","buy_quantity","planned_pack_price","sale_price","monthly_overhead","margin_percent","material_margin_percent","commission_percent","gross_profit","net_profit","cashflow","worker_payments","sale_fees","other_expenses"}
    def table_rows(title,keys,items,xlsx=False):
        if title=="Журнал":
            return [r[:5]+[Decimal(v) for v in r[5:]] for r in items] if xlsx else items
        def cell(k,v):
            if v is None:return None
            if k in numeric or k.endswith("_rub") or k.endswith("_percent"):
                try:return Decimal(str(v)) if xlsx else str(v)
                except Exception:return safe(v)
            return safe(v)
        return [[cell(k,item.get(k)) for k in keys] for item in items]
    if fmt=="xlsx":
        from openpyxl import Workbook
        wb=Workbook();wb.remove(wb.active)
        for title,keys,items in tables:
            sh=wb.create_sheet(title);sh.append(keys);sh.freeze_panes="A2"
            for vals in table_rows(title,keys,items,True):
                sh.append(vals)
            sh.auto_filter.ref=sh.dimensions
        out=io.BytesIO();wb.save(out);return out.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt=="csv-zip":
        import zipfile
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            for title,keys,items in tables:
                c=io.StringIO();wr=csv.writer(c,delimiter=";");wr.writerow(keys);wr.writerows(table_rows(title,keys,items))
                z.writestr(title+".csv",("\ufeff"+c.getvalue()).encode("utf-8"))
        return out.getvalue(),"application/zip"
    raise ValueError("Неизвестный формат.")
