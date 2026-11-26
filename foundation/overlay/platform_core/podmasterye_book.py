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

ZONE=ZoneInfo("Asia/Yekaterinburg")
MAX_Q=10**12
MAX_M=10**16
UNITS=("шт","г","мл","мм","см²","компл")
CATEGORIES=("Реклама","Инструмент","Оборудование","Доставка","Упаковка","Подписки","Аренда","Услуги маркетплейса","Налоги","Оплата труда","Прочее")
FIN=("revenue","cogs","expenses","writeoffs","purchases","receipts","production_cash")
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_book_rows(
 workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 type TEXT NOT NULL CHECK(type IN ('raw','lot','sale')), key TEXT NOT NULL, value TEXT NOT NULL,
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
    def column(table,col,decl):
        if col not in {r[1] for r in db.execute("PRAGMA table_info("+table+")")}:
            db.execute("ALTER TABLE "+table+" ADD COLUMN "+col+" "+decl)
    column("pm_materials","unit","TEXT NOT NULL DEFAULT 'шт'")
    column("pm_materials","category","TEXT NOT NULL DEFAULT ''")
    column("pm_products","category","TEXT NOT NULL DEFAULT ''")
    column("pm_products","sale_price","TEXT")
    column("pm_products","minutes","INTEGER")
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
def entity(db,w,kind,ref):
    if not isinstance(ref,str) or len(ref)>120: raise ValueError("Укажите материал или изделие.")
    tab="pm_materials" if kind=="material" else "pm_products"
    # Exact stable ID or exact normalized name. Do not infer declensions or cross-workspace IDs.
    rows=db.execute("SELECT id,name FROM "+tab+" WHERE workspace=? AND (id=? OR normalized=?)",
                    (w,ref," ".join(ref.split()).casefold())).fetchall()
    if len(rows)!=1: raise ValueError("Не найден однозначный объект: "+ref)
    return rows[0]

# The same field contracts drive browser forms, local assistant and MCP.
# (type, label, required, optional default); no user/model-supplied workspace.
FIELDS={
 "material":("Материал",[
   ("entity_id","material","Существующий материал (пусто — новый)",False,""),("name","text","Название",True,None),("unit","unit","Базовая единица",True,"шт"),("pack","int","Единиц в упаковке",True,1),
   ("pack_price","money","Плановая цена упаковки, ₽",False,None),("category","text","Категория",False,"")]),
 "product":("Изделие",[
   ("entity_id","product","Существующее изделие (пусто — новое)",False,""),("name","text","Название",True,None),("category","text","Категория",False,""),
   ("sale_price","money","Плановая цена продажи, ₽",False,None),("minutes","int0","Время изготовления, мин",False,None)]),
 "opening":("Начальный остаток",[
   ("material","material","Материал",True,None),("quantity","int","Количество (базовые единицы)",True,None),("total","money","Стоимость всего остатка, ₽",True,None)]),
 "purchase":("Закупка",[
   ("material","material","Материал",True,None),("quantity","int","Количество",True,None),("purchase_unit","choice:base,pack","Единица закупки",True,"pack"),
   ("total","money","Общая сумма, ₽",True,None),("supplier","text","Поставщик",False,"")]),
 "manufacture":("Выпуск партии",[
   ("product","product","Изделие",True,None),("quantity","int","Количество изделий",True,None),
   ("extra","money","Оплаченные прямые затраты партии сверх сырья, ₽",False,"0")]),
 "sale":("Продажа",[
   ("product","product","Изделие",True,None),("quantity","int","Количество",True,None),("unit_price","money","Цена за единицу, ₽",True,None),
   ("channel","text","Канал продаж",True,"Прямые продажи"),("paid_amount","money","Получено денег, ₽",True,"0"),
   ("auto_produce","bool","Изготовить недостающий объём из сырья",False,False)]),
 "payment":("Оплата продажи",[
   ("sale","sale","Продажа",True,None),("amount","positive_money","Получено денег, ₽",True,None)]),
 "return":("Возврат продажи",[
   ("sale","sale","Продажа",True,None),("quantity","int","Количество возврата",True,None),
   ("refund","money","Возвращено денег, ₽",True,"0"),("restock","bool","Фактически возвращено и пригодно для продажи",True,False)]),
 "expense":("Расход",[
   ("category","category","Статья расхода",True,"Прочее"),("total","positive_money","Сумма, ₽",True,None)]),
 "writeoff":("Списание материала",[
   ("material","material","Материал",True,None),("quantity","int","Количество (базовые единицы)",True,None)]),
 "reverse":("Сторно операции",[
   ("event","event","Операция",True,None),("reason","text","Причина",True,None)]),
}
CATALOG=("material","product")
PAGES={"material":"materials","product":"products","opening":"stock","purchase":"purchases","manufacture":"manufacture","sale":"sales","payment":"sales","return":"sales","expense":"expenses","writeoff":"stock","reverse":"journal"}
def forms():
    return {op:{"title":label,"page":PAGES[op],"fields":[{"name":n,"type":t,"label":l,"required":r,"default":v} for n,t,l,r,v in fs]+
               ([] if op in CATALOG else [{"name":"day","type":"date","label":"Дата","required":True,"default":today().isoformat()},{"name":"note","type":"text","label":"Заметка","required":False,"default":""}])}
            for op,(label,fs) in FIELDS.items()}

def validate(op,args):
    if not isinstance(op,str) or op not in FIELDS or not isinstance(args,dict): raise ValueError("Неизвестная операция.")
    fs=forms()[op]["fields"]
    if set(args)-{f["name"] for f in fs}: raise ValueError("Лишние поля операции.")
    out={}
    for f in fs:
        n,t=f["name"],f["type"]; v=args.get(n,f["default"])
        if v is None or (isinstance(v,str) and not v.strip() and t!="bool"):
            if f["required"]: raise ValueError("Заполните поле: "+f["label"])
            out[n]=None if t in ("money","positive_money","int0") else ""
            continue
        if t in ("int","int0"): out[n]=quantity(v,t=="int0")
        elif t in ("money","positive_money"): out[n]=money(minor(v,t=="money"))
        elif t=="bool":
            if type(v) is not bool: raise ValueError("Укажите да или нет.")
            out[n]=v
        elif t=="date": out[n]=dayval(v)
        elif t=="unit":
            if v not in UNITS: raise ValueError("Неизвестная единица.")
            out[n]=v
        elif t=="category":
            if v not in CATEGORIES: raise ValueError("Неизвестная статья расходов.")
            out[n]=v
        elif t.startswith("choice:"):
            if v not in t[7:].split(","): raise ValueError("Неизвестная единица закупки.")
            out[n]=v
        elif t in ("material","product","sale","event"): out[n]=textval(v,120)
        elif n=="name": out[n]=clean_name(v)
        else: out[n]=textval(v)
    return out

class Rows:
    def __init__(self,db,w,event):
        self.db,self.w,self.event=db,w,event
        self.rows={(t,k):json.loads(v) for t,k,v in db.execute("SELECT type,key,value FROM pm_book_rows WHERE workspace=?",(w,))}
        self.changes={}
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
    def lots(self,pid):
        return sorted(((key,v) for (t,key),v in self.rows.items() if t=="lot" and v["product_id"]==pid and v["quantity"]>0),key=lambda x:(x[1]["seq"],x[0]))
    def produce(self,pid,name,qty,extra,seq):
        recipe=self.db.execute("""SELECT m.id,m.name,r.qty,m.unit FROM pm_recipe r
          JOIN pm_materials m ON r.material=m.id WHERE r.product=? AND m.workspace=? ORDER BY m.id""",(pid,self.w)).fetchall()
        if not recipe: raise Conflict("У изделия нет рецептуры: "+name)
        used=[];cost=extra
        for mid,mname,per,unit in recipe:
            need=quantity(per*qty);value=self.raw_take(mid,need,mname)
            used.append({"material_id":mid,"material":mname,"per":per,"unit":unit,"quantity":need,"value_minor":value})
            cost+=value
        bounded(qty,cost)
        lid=uuid4().hex
        self.put("lot",lid,{"product_id":pid,"product":name,"quantity":qty,"value":cost,"initial_quantity":qty,"initial_value":cost,"seq":seq,"recipe":used,"origin":self.event})
        return lid,cost,used
    def take_lots(self,pid,qty):
        out=[];need=qty
        for lid,_ in self.lots(pid):
            if not need:break
            lot=self.get("lot",lid);take=min(need,lot["quantity"])
            cost=prorate(lot["value"],take,lot["quantity"])
            lot.update(quantity=lot["quantity"]-take,value=lot["value"]-cost)
            self.put("lot",lid,lot)
            out.append({"lot":lid,"quantity":take,"value_minor":cost,"recipe":lot["recipe"],"returned":0,"returned_value":0})
            need-=take
        if need:raise Conflict("Недостаточно готовых изделий.")
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
            db.execute("UPDATE pm_materials SET name=?,normalized=?,pack=?,price=?,unit=?,category=? WHERE id=? AND workspace=?",(name,norm,a["pack"],a["pack_price"],a["unit"],a["category"],mid,w))
        else:
            mid=uuid4().hex
            db.execute("INSERT INTO pm_materials(id,workspace,name,normalized,pack,price,unit,category) VALUES(?,?,?,?,?,?,?,?)",(mid,w,name,norm,a["pack"],a["pack_price"],a["unit"],a["category"]))
        ident=mid
    else:
        duplicate=db.execute("SELECT id FROM pm_products WHERE workspace=? AND normalized=?",(w,norm)).fetchone()
        old=entity(db,w,"product",a["entity_id"]) if a["entity_id"] else None
        if duplicate and (not old or duplicate[0]!=old[0]):raise Conflict("Изделие с таким названием уже существует. Выберите его для изменения.")
        ident=old[0] if old else uuid4().hex
        if old:db.execute("UPDATE pm_products SET name=?,normalized=?,category=?,sale_price=?,minutes=? WHERE id=? AND workspace=?",(name,norm,a["category"],a["sale_price"],a["minutes"],ident,w))
        else:db.execute("INSERT INTO pm_products(id,workspace,name,normalized,category,sale_price,minutes) VALUES(?,?,?,?,?,?,?)",(ident,w,name,norm,a["category"],a["sale_price"],a["minutes"]))
    result={"id":ident,"kind":op,"summary":"Сохранено: "+name,"arguments":a}
    db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(w,"book:"+rid,raw,encode(result)))
    return result

def execute(db,w,rid,op,args):
    key_id(rid);a=validate(op,args)
    if op in CATALOG:
        if db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND rid=?",(w,rid)).fetchone(): raise Conflict("Идентификатор уже использован.")
        return catalog_write(db,w,rid,op,a)
    if db.execute("SELECT 1 FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+rid)).fetchone(): raise Conflict("Идентификатор уже использован.")
    raw=encode(a)
    old=db.execute("SELECT kind,args,result FROM pm_book_events WHERE workspace=? AND rid=?",(w,rid)).fetchone()
    if old:
        if old[:2]!=(op,raw):raise Conflict("Идентификатор уже использован.")
        return json.loads(old[2])
    eid=uuid4().hex;seq=db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM pm_book_events").fetchone()[0]
    rows=Rows(db,w,eid);f=dict.fromkeys(FIN,0);res={};reverse_of=None
    summary=""
    if op in ("opening","purchase","writeoff"):
        mid,name=entity(db,w,"material",a["material"])
        pack,unit=db.execute("SELECT pack,unit FROM pm_materials WHERE id=? AND workspace=?",(mid,w)).fetchone()
        qty=a["quantity"]*(pack if op=="purchase" and a["purchase_unit"]=="pack" else 1)
        quantity(qty)
        if op=="writeoff":
            value=rows.raw_take(mid,qty,name);f["writeoffs"]=value
        else:
            value=minor(a["total"]);rows.raw_add(mid,qty,value,opening=(op=="opening"))
            if op=="purchase":f["purchases"]=value
        res.update(material_id=mid,material=name,quantity=qty,unit=unit,value_rub=money(value),supplier=a.get("supplier",""))
        summary=FIELDS[op][0]+": "+name+" · "+str(qty)+" "+unit+" · "+money(value)+" ₽"
    elif op=="manufacture":
        pid,name=entity(db,w,"product",a["product"]);qty=a["quantity"];extra=minor(a["extra"])
        lid,cost,used=rows.produce(pid,name,qty,extra,seq);f["production_cash"]=extra
        res.update(product_id=pid,product=name,quantity=qty,lot_id=lid,cost_rub=money(cost),materials=used)
        summary=f"Выпуск: {name} · {qty} шт. · себестоимость партии {money(cost)} ₽"
    elif op=="sale":
        pid,name=entity(db,w,"product",a["product"]);qty=a["quantity"]
        price=minor(a["unit_price"]);gross=price*qty
        if gross>MAX_M:raise ValueError("Слишком большая сумма.")
        paid=minor(a["paid_amount"])
        if paid>gross:raise ValueError("Оплата превышает сумму продажи.")
        ready=sum(v["quantity"] for _,v in rows.lots(pid))
        if ready<qty:
            if not a["auto_produce"]:raise Conflict("Недостаточно готовых изделий. Разрешите изготовление недостающего объёма.")
            rows.produce(pid,name,qty-ready,0,seq)
        alloc=rows.take_lots(pid,qty);cost=sum(x["value_minor"] for x in alloc)
        if cost>MAX_M:raise ValueError("Слишком большая себестоимость.")
        rows.put("sale",eid,{"product_id":pid,"product":name,"quantity":qty,"returned":0,"price":price,"paid":paid,"channel":a["channel"],"day":a["day"],"allocations":alloc})
        f.update(revenue=gross,cogs=cost,receipts=paid)
        res.update(product_id=pid,product=name,quantity=qty,channel=a["channel"],sale_id=eid,
                   revenue_rub=money(gross),cogs_rub=money(cost),paid_rub=money(paid),due_rub=money(gross-paid),sales_quantity=qty,consumption=material_usage(alloc))
        summary=f"Продажа: {name} · {qty} шт. · выручка {money(gross)} ₽ · себестоимость {money(cost)} ₽"
    elif op=="payment":
        sid=a["sale"];sale=rows.sale(sid)
        if a["day"]<sale["day"]:raise ValueError("Оплата не может быть раньше продажи.")
        value=minor(a["amount"],False);gross=(sale["quantity"]-sale["returned"])*sale["price"]
        if sale["paid"]+value>gross:raise Conflict("Сумма превышает долг покупателя.")
        sale["paid"]+=value;rows.put("sale",sid,sale);f["receipts"]=value
        res.update(sale_id=sid,product_id=sale["product_id"],product=sale["product"],channel=sale["channel"],paid_rub=money(value),due_rub=money(gross-sale["paid"]))
        summary=f"Получена оплата: {money(value)} ₽"
    elif op=="return":
        sid=a["sale"];sale=rows.sale(sid);qty=a["quantity"];refund=minor(a["refund"])
        if a["day"]<sale["day"]:raise ValueError("Возврат не может быть раньше продажи.")
        if qty>sale["quantity"]-sale["returned"]:raise Conflict("Возврат превышает остаток продажи.")
        gross=qty*sale["price"];remaining=(sale["quantity"]-sale["returned"]-qty)*sale["price"]
        if refund>gross or refund>sale["paid"] or sale["paid"]-refund>remaining:
            raise Conflict("Сумма возврата не соответствует фактической оплате и остатку долга.")
        left=qty;returned=[];restored=0
        for alloc in sale["allocations"]:
            avail=alloc["quantity"]-alloc["returned"]
            if not avail or not left:continue
            take=min(avail,left);cost=prorate(alloc["value_minor"]-alloc["returned_value"],take,avail)
            alloc["returned"]+=take;alloc["returned_value"]+=cost;left-=take
            returned.append({"quantity":take,"recipe":alloc["recipe"]})
            if a["restock"]:
                rows.put("lot",uuid4().hex,{"product_id":sale["product_id"],"product":sale["product"],"quantity":take,"value":cost,"initial_quantity":take,"initial_value":cost,"seq":seq,"recipe":alloc["recipe"],"origin":eid})
                restored+=cost
        if left:raise Conflict("Нарушена история партий продажи.")
        sale["returned"]+=qty;sale["paid"]-=refund;rows.put("sale",sid,sale)
        f.update(revenue=-gross,cogs=-restored,receipts=-refund)
        usage=material_usage(returned)
        for u in usage:u["quantity"]=-u["quantity"]
        res.update(sale_id=sid,product_id=sale["product_id"],product=sale["product"],channel=sale["channel"],quantity=qty,
                   sales_quantity=-qty,consumption=usage,restocked=a["restock"],refund_rub=money(refund),restored_cost_rub=money(restored))
        summary=f"Возврат: {qty} шт. · возвращено денег {money(refund)} ₽"
    elif op=="expense":
        value=minor(a["total"],False);f["expenses"]=value
        res.update(category=a["category"],value_rub=money(value));summary=f"Расход: {a['category']} · {money(value)} ₽"
    elif op=="reverse":
        reverse_of=a["event"]
        row=db.execute("SELECT kind,day,result,changes,finance FROM pm_book_events WHERE workspace=? AND id=?",(w,reverse_of)).fetchone()
        if not row or row[0]=="reverse":raise ValueError("Операция недоступна для сторно.")
        if db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND reverse_of=?",(w,reverse_of)).fetchone():raise Conflict("Операция уже сторнирована.")
        if a["day"]<row[1]:raise ValueError("Сторно не может быть раньше операции.")
        if not a["reason"]:raise ValueError("Укажите причину.")
        changes=json.loads(row[3])
        for c in changes:
            if rows.get(c["type"],c["key"])!=c["after"]:raise Conflict("Есть последующие зависимые движения. Сначала исправьте их.")
        for c in reversed(changes):rows.put(c["type"],c["key"],c["before"],restore=True)
        f={k:-v for k,v in json.loads(row[4]).items()}
        original=json.loads(row[2])
        res.update({k:original[k] for k in ("product_id","product","material_id","material","channel","category","sale_id") if k in original})
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
    catalog=[list(r) for r in db.execute("SELECT id,name,pack,price,unit,category FROM pm_materials WHERE workspace=? ORDER BY id",(w,))]
    products=[list(r) for r in db.execute("SELECT id,name,category,sale_price,minutes FROM pm_products WHERE workspace=? ORDER BY id",(w,))]
    recipe=[list(r) for r in db.execute("SELECT r.product,r.material,r.qty FROM pm_recipe r JOIN pm_products p ON p.id=r.product WHERE p.workspace=? ORDER BY r.product,r.material",(w,))]
    last=db.execute("SELECT COALESCE(MAX(seq),0) FROM pm_book_events WHERE workspace=?",(w,)).fetchone()[0]
    return hashlib.sha256(encode([w,op,args,last,catalog,products,recipe]).encode()).hexdigest()

def preview_action(db,w,op,args):
    a=validate(op,args);rev=revision(db,w,op,a)
    db.execute("SAVEPOINT pm_preview")
    try:
        result=execute(db,w,"preview-"+uuid4().hex,op,a)
        preview={k:result[k] for k in ("summary","finance","quantity","cost_rub","cogs_rub","revenue_rub","due_rub","value_rub","restored_cost_rub") if k in result}
    finally:
        db.execute("ROLLBACK TO pm_preview")
        db.execute("RELEASE pm_preview")
    return {"operation":op,"arguments":a,"revision":rev,"preview":preview}

def preview_for_user(store,token,op,args):
    with store._write() as db:
        _,w=_principal(db,token)
        return preview_action(db,w,op,args)

def mutate(store,token,rid,op,args,expected):
    with store._write() as db:
        _,w=_principal(db,token)
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
    g=f["revenue"]-f["cogs"];net=g-f["expenses"]-f["writeoffs"]
    cash=f["receipts"]-f["purchases"]-f["expenses"]-f["production_cash"]
    return {**{k:money(v) for k,v in f.items()},"gross_profit":money(g),"net_profit":money(net),"cashflow":money(cash),
            "margin_percent":format((Decimal(g)*100/f["revenue"]).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if f["revenue"]>0 else None}
def aggregate(events):
    f=dict.fromkeys(FIN,0)
    for r,fin in events:
        for k in FIN:f[k]+=fin.get(k,0)
    return totals(f)
def grouped(events,key):
    groups={}
    for r,f in events:
        if not r.get(key):continue
        if key in ("product_id","channel") and not any(f[k] for k in ("revenue","cogs","receipts")) and not r.get("sales_quantity"):continue
        if key=="category" and not f["expenses"]:continue
        k=r[key];g=groups.setdefault(k,{"name":r.get("product",k) if key=="product_id" else k,"events":[],"quantity":0})
        g["events"].append((r,f));g["quantity"]+=r.get("sales_quantity",0)
    return [{"key":k,"name":v["name"],"quantity":v["quantity"],**aggregate(v["events"])} for k,v in sorted(groups.items(),key=lambda kv:kv[1]["name"])]
def event_rows(db,w,start,end):
    reverse={r[0] for r in db.execute("SELECT reverse_of FROM pm_book_events WHERE workspace=? AND reverse_of IS NOT NULL",(w,))}
    out=[]
    for rid,s,f in db.execute("SELECT id,result,finance FROM pm_book_events WHERE workspace=? AND day BETWEEN ? AND ? ORDER BY day,seq",(w,start,end)):
        r=json.loads(s);r["reversed"]=rid in reverse;out.append((r,json.loads(f)))
    return out

def report(db,w,start=None,end=None,horizon=30,lead=7,safety=3,view="all",limit=100,offset=0,event_group="all"):
    start,end=period(start,end)
    for v in (horizon,lead,safety):
        if type(v) is not int or not 0<=v<=365:raise ValueError("Некорректный горизонт закупки.")
    if horizon==0:raise ValueError("Горизонт должен быть положительным.")
    if type(limit) is not int or not 1<=limit<=500 or type(offset) is not int or not 0<=offset<=10**7:raise ValueError("Некорректная страница.")
    rows=Rows(db,w,"read")
    mats=[]
    for mid,name,pack,price,unit,cat in db.execute("SELECT id,name,pack,price,unit,category FROM pm_materials WHERE workspace=? ORDER BY normalized",(w,)):
        r=rows.get("raw",mid);qty=r["quantity"] if r else 0;value=r["value"] if r else 0
        avg=Decimal(value)/100/qty if qty else None
        mats.append(dict(id=mid,name=name,pack=pack,planned_pack_price=price,unit=unit,category=cat,quantity=qty,valued=r is not None,
                         value_rub=money(value),average_price_rub=format(avg.quantize(Decimal(".000001"),rounding=ROUND_HALF_UP),"f") if avg is not None else None))
    bymid={m["id"]:m for m in mats};products=[];byprod={}
    for pid,name,cat,price,minutes in db.execute("SELECT id,name,category,sale_price,minutes FROM pm_products WHERE workspace=? ORDER BY normalized",(w,)):
        lots=rows.lots(pid);qty=sum(v["quantity"] for _,v in lots);value=sum(v["value"] for _,v in lots)
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
        v=dict(id=pid,name=name,category=cat,sale_price=price,minutes=minutes,quantity=qty,value_rub=money(value),recipe=recipe,
               estimated_material_cost_rub=format(cost.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if known and recipe else None)
        products.append(v);byprod[pid]=v
    events=event_rows(db,w,start,end)
    summary=aggregate(events)
    summary.update(sale_records=sum(1 if r["kind"]=="sale" else -1 if r.get("original_kind")=="sale" else 0 for r,f in events),
                   sales_quantity=sum(r.get("sales_quantity",0) for r,f in events),
                   raw_inventory_rub=money(sum(int(Decimal(m["value_rub"])*100) for m in mats)),
                   finished_inventory_rub=money(sum(int(Decimal(p["value_rub"])*100) for p in products)))
    summary["inventory_rub"]=format(Decimal(summary["raw_inventory_rub"])+Decimal(summary["finished_inventory_rub"]),".2f")
    batch_dates=dict(db.execute("SELECT id,day FROM pm_book_events WHERE workspace=?",(w,)))
    batches=[]
    for (t,k),lot in rows.rows.items():
        if t=="lot":
            batches.append({"id":k,"product_id":lot["product_id"],"product":lot["product"],"day":batch_dates.get(lot["origin"]),
              "initial_quantity":lot.get("initial_quantity"),"initial_value_rub":money(lot["initial_value"]) if "initial_value" in lot else None,
              "quantity":lot["quantity"],"value_rub":money(lot["value"]),"seq":lot["seq"]})
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
    for (t,k),s in rows.rows.items():
        if t!="sale":continue
        gross=(s["quantity"]-s["returned"])*s["price"]
        sales.append({"id":k,"product":s["product"],"product_id":s["product_id"],"channel":s["channel"],"day":s["day"],"quantity":s["quantity"],"returned":s["returned"],
                      "gross_rub":money(gross),"paid_rub":money(s["paid"]),"due_rub":money(gross-s["paid"])})
    sales.sort(key=lambda x:(x["day"],x["id"]),reverse=True)
    summary["current_receivables_rub"]=format(sum((Decimal(s["due_rub"]) for s in sales),Decimal(0)),".2f")
    monthly={}
    for r,f in events:monthly.setdefault(r["day"][:7],[]).append((r,f))
    history_start=(today()-timedelta(days=29)).isoformat()
    recent=events if start==history_start and end==today().isoformat() else event_rows(db,w,history_start,today().isoformat())
    demand={};cons={}
    for r,f in recent:
        if r.get("product_id"):demand[r["product_id"]]=demand.get(r["product_id"],0)+r.get("sales_quantity",0)
        for u in r.get("consumption",[]):cons[u["material_id"]]=cons.get(u["material_id"],0)+u["quantity"]
    plans=[]
    for m in mats:
        mid=m["id"];sold_equiv=cons.get(mid,0);daily=Decimal(0);need=Decimal(0);coverage_days=[]
        for pid,n in demand.items():
            if n<=0 or pid not in byprod:continue
            p=byprod[pid]
            per=next((r["usage"] for r in p["recipe"] if r["material_id"]==mid),0)
            if not per:continue
            rate=Decimal(n)/30;daily+=rate*per
            # Forecast production after consuming existing finished inventory.
            need+=max(Decimal(0),rate*horizon-p["quantity"])*per
            coverage_days.append(Decimal(p["quantity"])/rate)
        safety_need=daily*safety
        short=max(Decimal(0),need+safety_need-m["quantity"])
        packs=int((short/m["pack"]).to_integral_value(rounding="ROUND_CEILING")) if daily else 0
        days=Decimal(m["quantity"])/daily if daily else None
        # Conservative reorder threshold: raw stock only. Quantity forecast also accounts for finished goods.
        trigger=days is not None and days<=lead+safety
        until=max(0,int(days)-lead-safety) if days is not None else None
        order_day=(today()+timedelta(days=min(until,36500))).isoformat() if until is not None and until<=36500 else None
        plans.append({"material_id":mid,"material":m["name"],"unit":m["unit"],"sold_equivalent_units":sold_equiv,
                     "sold_equivalent_packs":format((Decimal(sold_equiv)/m["pack"]).quantize(Decimal(".001"),rounding=ROUND_HALF_UP),"f"),
                     "daily_forecast":format(daily.quantize(Decimal(".001"),rounding=ROUND_HALF_UP),"f"),
                     "raw_days":format(days.quantize(Decimal(".1"),rounding=ROUND_HALF_UP),"f") if days is not None else None,
                     "buy_packs":packs,"order_now":trigger,"order_day":order_day,"history_from":history_start,"history_to":today().isoformat(),
                     "buy_quantity":packs*m["pack"]})
    # Explicit current stock vs period financial flows. Pagination never truncates aggregates.
    groups={"all":None,"stock":{"opening","writeoff"},"purchases":{"purchase"},"manufacture":{"manufacture"},"sales":{"sale","payment","return"},"expenses":{"expense"}}
    if event_group not in groups:raise ValueError("Неизвестный раздел журнала.")
    kinds=groups[event_group]
    allrows=[r for r,f in reversed(events) if kinds is None or r.get("original_kind",r["kind"]) in kinds]
    data={"period":{"from":start,"to":end},"summary":summary,"materials":mats,"products":products,"sales":sales,"batches":batches,"consumption":list(consumption.values()),
          "events":allrows[offset:offset+limit],"event_count":len(allrows),"offset":offset,"limit":limit,
          "monthly":[{"month":k,**aggregate(v)} for k,v in sorted(monthly.items())],"by_product":grouped(events,"product_id"),
          "by_channel":grouped(events,"channel"),"by_expense":grouped(events,"category"),
          "planning":plans,"planning_settings":{"horizon":horizon,"lead":lead,"safety":safety},
          "forms":forms(),"units":UNITS,"expense_categories":CATEGORIES,"today":today().isoformat(),
          "assumptions":"Склад на текущий момент; финансовые показатели за выбранный период. Прогноз по чистым продажам за 30 календарных дней, текущим нормам и готовому остатку; нет резервов и поставок в пути. Налоги и комиссии — только введённые расходы."}
    if view=="all":return data
    allowed={"summary":("summary","period","assumptions"),"stock":("materials","products","batches","summary","assumptions"),
             "sales":("sales","by_product","by_channel","period"),"planning":("planning","planning_settings","consumption","period","assumptions"),
             "finance":("summary","monthly","by_product","by_channel","by_expense","period","assumptions"),
             "journal":("events","event_count","offset","limit","period")}
    if view not in allowed:raise ValueError("Неизвестный отчёт.")
    return {k:data[k] for k in allowed[view]}

def read(store,token,**opts):
    with store._lock:
        _,w=_principal(store._db,token)
        return report(store._db,w,**opts)
def export(store,token,fmt):
    with store._lock:
        _,w=_principal(store._db,token)
        records=event_rows(store._db,w,"0001-01-01",today().isoformat())
        d=report(store._db,w)
    headings=["Дата","Операция","ID","Описание","Заметка","Выручка","COGS","Расходы","Списания","Закупки","Поступления","Прямые затраты выпуска"]
    def safe(v):
        # Avoid spreadsheet formula injection from externally supplied names/notes.
        return "'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r") else v
    body=[[r["day"],r["kind"],r["id"],safe(r["summary"]),safe(r["note"]),*[money(f[k]) for k in FIN]] for r,f in records]
    if fmt=="csv":
        s=io.StringIO();writer=csv.writer(s,delimiter=";");writer.writerow(headings);writer.writerows(body)
        return ("\ufeff"+s.getvalue()).encode("utf-8"),"text/csv; charset=utf-8"
    if fmt=="xlsx":
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active;ws.title="Журнал";ws.append(headings)
        for line in body:ws.append(line)
        for title,items,keys in (("Сырьё",d["materials"],["id","name","category","unit","pack","planned_pack_price","quantity","value_rub","average_price_rub"]),
                                 ("Готовые изделия",d["products"],["id","name","category","sale_price","minutes","quantity","value_rub","estimated_material_cost_rub"]),
                                 ("Рецептуры",[{**r,"product":p["name"],"product_id":p["id"]} for p in d["products"] for r in p["recipe"]],["product_id","product","material_id","material","unit","usage"]),
                                 ("Партии",d["batches"],["id","day","product_id","product","initial_quantity","initial_value_rub","quantity","value_rub"]),
                                 ("Продажи",d["sales"],["id","day","product_id","product","channel","quantity","returned","gross_rub","paid_rub","due_rub"]),
                                 ("По месяцам",d["monthly"],["month","revenue","cogs","gross_profit","expenses","writeoffs","net_profit","cashflow"])):
            sh=wb.create_sheet(title);sh.append(keys)
            for item in items:sh.append([safe(item.get(k)) for k in keys])
        out=io.BytesIO();wb.save(out);return out.getvalue(),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    raise ValueError("Неизвестный формат.")
