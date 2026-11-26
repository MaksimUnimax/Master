"""Source-scoped incoming store orders; no marketplace secrets in prompts or logs."""
import hashlib
import json
import secrets
from decimal import Decimal
from uuid import uuid4
from .identity import _principal
from .podmasterye_domain import Conflict,clean_name,key_id,encode
from . import podmasterye_book as book,podmasterye_workshops as workshops

SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_sources(
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 name TEXT NOT NULL, normalized TEXT NOT NULL, digest BLOB NOT NULL UNIQUE,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)),
 auto_produce INTEGER NOT NULL DEFAULT 0 CHECK(auto_produce IN(0,1)),
 UNIQUE(workspace,normalized))""",
"""CREATE TABLE IF NOT EXISTS pm_external_offers(
 source TEXT NOT NULL REFERENCES pm_sources(id) ON DELETE CASCADE,
 offer TEXT NOT NULL, name TEXT NOT NULL, price TEXT NOT NULL, product TEXT REFERENCES pm_products(id),
 PRIMARY KEY(source,offer))""",
"""CREATE TABLE IF NOT EXISTS pm_external_orders(
 source TEXT NOT NULL REFERENCES pm_sources(id) ON DELETE CASCADE,
 ref TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
 error TEXT NOT NULL DEFAULT '', result TEXT, PRIMARY KEY(source,ref))""",
"""CREATE TABLE IF NOT EXISTS pm_external_events(
 source TEXT NOT NULL REFERENCES pm_sources(id) ON DELETE CASCADE,
 ref TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(source,ref))""",
)
def init(db):
    for s in SCHEMA:db.execute(s)
    if "external_stock" not in {r[1] for r in db.execute("PRAGMA table_info(pm_external_offers)")}:
        db.execute("ALTER TABLE pm_external_offers ADD COLUMN external_stock INTEGER")
def source(db,w,ident):
    row=db.execute("SELECT id,name,enabled,auto_produce FROM pm_sources WHERE workspace=? AND id=?",(w,ident)).fetchone()
    if not row:raise ValueError("Источник недоступен.")
    return row
def overview(db,w):
    src=[]
    for ident,name,enabled,auto in db.execute("SELECT id,name,enabled,auto_produce FROM pm_sources WHERE workspace=? ORDER BY normalized",(w,)):
        offers=[dict(offer_id=o,name=n,price=p,product_id=pid,external_stock=stock) for o,n,p,pid,stock in db.execute("SELECT offer,name,price,product,external_stock FROM pm_external_offers WHERE source=? ORDER BY name,offer",(ident,))]
        orders=[dict(order_ref=r,day=d,status=s,error=e,items=len(json.loads(p)["items"])) for r,d,s,e,p in db.execute("SELECT ref,day,status,error,payload FROM pm_external_orders WHERE source=? ORDER BY day DESC,rowid DESC LIMIT 100",(ident,))]
        count=db.execute("SELECT count(*) FROM pm_external_orders WHERE source=? AND status<>'posted'",(ident,)).fetchone()[0]
        src.append(dict(id=ident,name=name,enabled=bool(enabled),auto_produce=bool(auto),offers=offers,orders=orders,pending=count))
    return {"sources":src}
def change(store,token,workshop,action,args):
    if action not in ("create","rotate","disable","enable","configure","map","create_product","retry") or not isinstance(args,dict):raise ValueError("Неизвестная операция.")
    allowed={"name","auto_produce"} if action=="create" else {"id","offer","product"} if action=="map" else {"id","offer","name","category"} if action=="create_product" else {"id","auto_produce"} if action=="configure" else {"id"}
    if set(args)-allowed:raise ValueError("Лишние поля.")
    with store._write() as db:
        _,account=_principal(db,token);w=workshops.resolve(db,account,workshop)
        if action=="create":
            name=clean_name(args.get("name"));auto=args.get("auto_produce",False)
            if type(auto) is not bool:raise ValueError("Укажите политику выпуска.")
            if db.execute("SELECT 1 FROM pm_sources WHERE workspace=? AND normalized=?",(w,name.casefold())).fetchone():raise Conflict("Источник уже существует.")
            ident=uuid4().hex;key=secrets.token_urlsafe(32)
            db.execute("INSERT INTO pm_sources(id,workspace,name,normalized,digest,auto_produce) VALUES(?,?,?,?,?,?)",(ident,w,name,name.casefold(),hashlib.sha256(key.encode()).digest(),int(auto)))
            return {"id":ident,"name":name,"apiKey":key}
        ident,name,enabled,auto=source(db,w,args.get("id"))
        if action=="rotate":
            key=secrets.token_urlsafe(32)
            db.execute("UPDATE pm_sources SET digest=? WHERE id=? AND workspace=?",(hashlib.sha256(key.encode()).digest(),ident,w))
            return {"id":ident,"apiKey":key}
        if action in ("disable","enable"):
            db.execute("UPDATE pm_sources SET enabled=? WHERE id=? AND workspace=?",(int(action=="enable"),ident,w))
        elif action=="configure":
            flag=args.get("auto_produce")
            if type(flag) is not bool:raise ValueError("Укажите политику выпуска.")
            db.execute("UPDATE pm_sources SET auto_produce=? WHERE id=? AND workspace=?",(int(flag),ident,w))
        elif action=="map":
            offer=book.textval(args.get("offer"),128);product,_=book.entity(db,w,"product",args.get("product"))
            if not db.execute("UPDATE pm_external_offers SET product=? WHERE source=? AND offer=?",(product,ident,offer)).rowcount:raise ValueError("Артикул не найден.")
            # No implicit posting on an unknown/disabled source.
            if enabled:retry(db,w,ident,name,bool(auto))
        elif action=="create_product":
            offer=book.textval(args.get("offer"),128)
            row=db.execute("SELECT name,price,product FROM pm_external_offers WHERE source=? AND offer=?",(ident,offer)).fetchone()
            if not row:raise ValueError("Артикул не найден.")
            if not row[2]:
                name_new=clean_name(args.get("name") or row[0]);category=book.textval(args.get("category",""))
                if db.execute("SELECT 1 FROM pm_products WHERE workspace=? AND normalized=?",(w,name_new.casefold())).fetchone():
                    raise Conflict("Изделие с таким названием существует. Выберите его для привязки.")
                result=book.execute(db,w,"srcprod-"+hashlib.sha256(encode([ident,offer]).encode()).hexdigest(),"product",
                    {"name":name_new,"category":category,"sale_price":row[1]})
                db.execute("UPDATE pm_external_offers SET product=? WHERE source=? AND offer=?",(result["id"],ident,offer))
            if enabled:retry(db,w,ident,name,bool(auto))
        elif action=="retry":
            if not enabled:raise Conflict("Источник отключён.")
            retry(db,w,ident,name,bool(auto))
        return {"id":ident,**overview(db,w)}
def own_overview(store,token,workshop):
    with store._lock:
        _,a=_principal(store._db,token);w=workshops.resolve(store._db,a,workshop)
        return overview(store._db,w)
def canonical(payload):
    if not isinstance(payload,dict) or set(payload)!={"order_ref","date","shop_name","items"}:raise ValueError("Поля: order_ref, date, shop_name, items.")
    ref=book.textval(payload["order_ref"],128);name=book.textval(payload["shop_name"],120);day=book.dayval(payload["date"])
    if not ref or not name:raise ValueError("Укажите номер и название магазина.")
    items=payload["items"]
    if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError("От 1 до 100 строк заказа.")
    out=[]
    for item in items:
        if not isinstance(item,dict) or set(item)!={"offer_id","name","price","qty"}:raise ValueError("Поля позиции: offer_id, name, price, qty.")
        offer=book.textval(item["offer_id"],128)
        if not offer:raise ValueError("Пустой артикул.")
        if type(item["price"]) not in (str,int,float):raise ValueError("Некорректная цена.")
        price=book.money(book.minor(str(item["price"])))
        qty=book.quantity(item["qty"])
        if book.minor(price)*qty>book.MAX_M:raise ValueError("Слишком большая сумма заказа.")
        out.append({"offer_id":offer,"name":clean_name(item["name"]),"price":price,"qty":qty})
    return {"order_ref":ref,"date":day,"shop_name":name,"items":out}
def authenticate(db,authorization):
    if not isinstance(authorization,str) or not authorization.startswith("Bearer ") or len(authorization)>100:raise PermissionError("Недействительный ключ.")
    key=authorization[7:]
    try:digest=hashlib.sha256(key.encode("ascii")).digest()
    except UnicodeEncodeError:raise PermissionError("Недействительный ключ.") from None
    row=db.execute("SELECT s.id,s.workspace,s.name,s.auto_produce FROM pm_sources s LEFT JOIN pm_workshops w ON w.id=s.workspace WHERE s.digest=? AND s.enabled=1 AND COALESCE(w.archived,0)=0",(digest,)).fetchone()
    if not row:raise PermissionError("Недействительный ключ.")
    return row
def post_order(db,w,ident,name,auto,ref):
    row=db.execute("SELECT payload,status,result FROM pm_external_orders WHERE source=? AND ref=?",(ident,ref)).fetchone()
    if not row:raise ValueError("Заказ не найден.")
    if row[1]=="posted":return json.loads(row[2])
    payload=json.loads(row[0]);items=payload["items"]
    ids=[]
    for item in items:
        r=db.execute("SELECT product FROM pm_external_offers WHERE source=? AND offer=?",(ident,item["offer_id"])).fetchone()
        if not r or not r[0]:
            db.execute("UPDATE pm_external_orders SET status='pending_mapping',error=? WHERE source=? AND ref=?",("Свяжите все артикулы с изделиями.",ident,ref))
            return {"order_ref":ref,"status":"pending_mapping","sales":0}
        ids.append(r[0])
    db.execute("SAVEPOINT external_order")
    try:
        results=[]
        for i,(item,pid) in enumerate(zip(items,ids)):
            rid="ext-"+hashlib.sha256(encode([ident,ref,i]).encode()).hexdigest()
            sale=book.execute(db,w,rid,"sale",{"product":pid,"quantity":item["qty"],"unit_price":item["price"],"channel":name,"paid_amount":book.money(book.minor(item["price"])*item["qty"]),"auto_produce":auto,"day":payload["date"],"note":"Внешний заказ "+ref})
            results.append(sale["id"])
        db.execute("RELEASE external_order")
    except (ValueError,Conflict) as e:
        db.execute("ROLLBACK TO external_order");db.execute("RELEASE external_order")
        db.execute("UPDATE pm_external_orders SET status='pending_stock',error=? WHERE source=? AND ref=?",(str(e)[:240],ident,ref))
        return {"order_ref":ref,"status":"pending_stock","sales":0}
    result={"order_ref":ref,"status":"posted","sales":len(results),"sale_ids":results}
    db.execute("UPDATE pm_external_orders SET status='posted',error='',result=? WHERE source=? AND ref=?",(encode(result),ident,ref))
    return result
def retry(db,w,ident,name,auto):
    refs=db.execute("SELECT ref FROM pm_external_orders WHERE source=? AND status<>'posted' ORDER BY day,rowid LIMIT 100",(ident,)).fetchall()
    for ref, in refs:post_order(db,w,ident,name,auto,ref)
def receive(store,authorization,payload):
    p=canonical(payload);raw=encode(p);ref=p["order_ref"]
    with store._write() as db:
        ident,w,name,auto=authenticate(db,authorization)
        old=db.execute("SELECT payload,status,result FROM pm_external_orders WHERE source=? AND ref=?",(ident,ref)).fetchone()
        if old:
            if old[0]!=raw:raise Conflict("Заказ с таким номером имеет другое содержимое.")
            return json.loads(old[2]) if old[1]=="posted" else post_order(db,w,ident,name,bool(auto),ref)
        db.execute("INSERT INTO pm_external_orders(source,ref,day,payload,status) VALUES(?,?,?,?,?)",(ident,ref,p["date"],raw,"pending_mapping"))
        for item in p["items"]:
            db.execute("INSERT INTO pm_external_offers(source,offer,name,price) VALUES(?,?,?,?) ON CONFLICT(source,offer) DO UPDATE SET name=excluded.name,price=excluded.price",(ident,item["offer_id"],item["name"],item["price"]))
        return post_order(db,w,ident,name,bool(auto),ref)
def event(store,authorization,payload):
    if not isinstance(payload,dict) or set(payload)!={"event_id","order_ref","line","kind","date","quantity","refund","restock"} or payload["kind"]!="return":
        raise ValueError("Поддерживается событие return: event_id, order_ref, line, kind, date, quantity, refund, restock.")
    eid=book.textval(payload["event_id"],128);ref=book.textval(payload["order_ref"],128);line=book.quantity(payload["line"],True)
    if not eid or not ref:raise ValueError("Пустой идентификатор.")
    refund=book.money(book.minor(str(payload["refund"])));day=book.dayval(payload["date"])
    qty=book.quantity(payload["quantity"]);restock=payload["restock"]
    if type(restock) is not bool:raise ValueError("Укажите состояние возврата.")
    raw=encode([ref,line,day,qty,refund,restock])
    with store._write() as db:
        ident,w,_,_=authenticate(db,authorization)
        old=db.execute("SELECT payload,result FROM pm_external_events WHERE source=? AND ref=?",(ident,eid)).fetchone()
        if old:
            if old[0]!=raw:raise Conflict("Идентификатор события уже использован.")
            return json.loads(old[1])
        order=db.execute("SELECT result FROM pm_external_orders WHERE source=? AND ref=? AND status='posted'",(ident,ref)).fetchone()
        if not order:raise Conflict("Заказ ещё не проведён.")
        ids=json.loads(order[0])["sale_ids"]
        if line>=len(ids):raise ValueError("Строка заказа не найдена.")
        rid="ext-return-"+hashlib.sha256(encode([ident,eid]).encode()).hexdigest()
        result=book.execute(db,w,rid,"return",{"sale":ids[line],"quantity":qty,"refund":refund,"restock":restock,"day":day,"note":"Возврат внешнего заказа "+ref})
        out={"event_id":eid,"status":"posted","return_id":result["id"]}
        db.execute("INSERT INTO pm_external_events VALUES(?,?,?,?)",(ident,eid,raw,encode(out)))
        return out


def receive_catalog(store,authorization,payload):
    if not isinstance(payload,dict) or set(payload)!={"items"} or not isinstance(payload["items"],list) or not 1<=len(payload["items"])<=500:
        raise ValueError("Ожидается каталог из 1–500 позиций.")
    items=[];seen=set()
    for r in payload["items"]:
        if not isinstance(r,dict) or not {"offer_id","name","price"}<=set(r)<={"offer_id","name","price","stock"}:raise ValueError("Некорректная позиция каталога.")
        offer=book.textval(r["offer_id"],128)
        if not offer or offer in seen:raise ValueError("Пустой или повторный артикул.")
        seen.add(offer)
        price=book.money(book.minor(str(r["price"])))
        stock=book.quantity(r["stock"],True) if r.get("stock") is not None else None
        items.append((offer,clean_name(r["name"]),price,stock))
    with store._write() as db:
        ident,w,_,_=authenticate(db,authorization)
        for o,n,p,stock in items:
            db.execute("""INSERT INTO pm_external_offers(source,offer,name,price,external_stock) VALUES(?,?,?,?,?)
              ON CONFLICT(source,offer) DO UPDATE SET name=excluded.name,price=excluded.price,external_stock=excluded.external_stock""",(ident,o,n,p,stock))
        return {"accepted":len(items),"stock_effect":False}
