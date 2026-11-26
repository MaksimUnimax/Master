"""Business-workshop isolation, independent of the Harness account/wallet scope.

One account owns multiple accounting workspaces. The original account workspace
remains the default, so existing records require no data rewrite. A chat is bound
once to a business workshop; all agent calls keep the original account scope for
authentication, usage and coins.
"""
import json
from uuid import uuid4
from .identity import _principal
from .storage import Scope,_bind_chat
from .podmasterye_domain import Conflict,clean_name,encode,key_id

COLORS=("green","blue","amber","violet","gray")
DEFAULT={"name":"Моя мастерская","description":"","color":"green","hourly_rate":"0.00","archived":False,"demo":False}
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_workshops(
 id TEXT PRIMARY KEY REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 account TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 name TEXT NOT NULL, normalized TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT 'green', hourly_rate TEXT NOT NULL DEFAULT '0.00',
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
 demo INTEGER NOT NULL DEFAULT 0 CHECK(demo IN(0,1)),
 UNIQUE(account,normalized))""",
"""CREATE TABLE IF NOT EXISTS pm_workshop_chats(
 chat TEXT PRIMARY KEY REFERENCES chats(chat_id) ON DELETE CASCADE,
 account TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 workshop TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE)""",
"""CREATE TABLE IF NOT EXISTS pm_workshop_requests(
 account TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 rid TEXT NOT NULL, args TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(account,rid))""",
)
def init(db):
    for s in SCHEMA:db.execute(s)
def metadata(db,w):
    row=db.execute("SELECT id,name,description,color,hourly_rate,archived,demo FROM pm_workshops WHERE id=?",(w,)).fetchone()
    if not row:return {"id":w,**DEFAULT}
    return dict(id=row[0],name=row[1],description=row[2],color=row[3],hourly_rate=row[4],archived=bool(row[5]),demo=bool(row[6]))
def ensure(db,account):
    db.execute("INSERT OR IGNORE INTO pm_workshops(id,account,name,normalized) VALUES(?,?,?,?)",(account,account,DEFAULT["name"],DEFAULT["name"].casefold()))
def resolve(db,account,requested=None,*,include_archived=False):
    w=requested or account
    if not isinstance(w,str) or len(w)>128:raise ValueError("Некорректная мастерская.")
    if w==account:
        row=db.execute("SELECT archived FROM pm_workshops WHERE account=? AND id=?",(account,w)).fetchone()
        if row and row[0] and not include_archived:raise Conflict("Мастерская в архиве.")
        return w
    row=db.execute("SELECT archived FROM pm_workshops WHERE account=? AND id=?",(account,w)).fetchone()
    if not row:raise ValueError("Мастерская недоступна.")
    if row[0] and not include_archived:raise Conflict("Мастерская в архиве.")
    return w
def chat_workspace(db,scope):
    row=db.execute("SELECT workshop,account FROM pm_workshop_chats WHERE chat=?",(scope.chat_id,)).fetchone()
    if row and row[1]!=scope.workspace_id:raise Conflict("Чат относится к другому аккаунту.")
    return resolve(db,scope.workspace_id,row[0] if row else None)
def list_for_user(store,token):
    from . import podmasterye_book as book
    with store._write() as db:
        _,a=_principal(db,token);ensure(db,a)
        result=[]
        for w, in db.execute("SELECT id FROM pm_workshops WHERE account=? ORDER BY archived,demo,normalized",(a,)):
            r=metadata(db,w)
            if not r["archived"]:
                info=book.report(db,w,view="summary")["summary"]
                r.update(revenue=info["revenue"],profit=info["net_profit"],sales=info["sales_quantity"])
            result.append(r)
        return {"default":a,"workshops":result}
def change(store,token,rid,action,args):
    from . import podmasterye_book as book
    key_id(rid)
    if action not in ("create","demo","update","archive","restore") or not isinstance(args,dict):
        raise ValueError("Неизвестная операция мастерской.")
    allowed={"name","description","color","hourly_rate"} if action in ("create","demo") else {"id","name","description","color","hourly_rate"} if action=="update" else {"id"}
    if set(args)-allowed:raise ValueError("Лишние поля.")
    raw=encode([action,args])
    with store._write() as db:
        actor,a=_principal(db,token);ensure(db,a)
        old=db.execute("SELECT args,result FROM pm_workshop_requests WHERE account=? AND rid=?",(a,rid)).fetchone()
        if old:
            if old[0]!=raw:raise Conflict("Идентификатор запроса уже использован.")
            return json.loads(old[1])
        if action in ("archive","restore"):
            w=resolve(db,a,args.get("id"),include_archived=True)
            if w==a and action=="archive":raise Conflict("Основную мастерскую нельзя архивировать.")
            db.execute("UPDATE pm_workshops SET archived=? WHERE id=? AND account=?",(int(action=="archive"),w,a))
        else:
            current=metadata(db,resolve(db,a,args.get("id"),include_archived=False)) if action=="update" else DEFAULT
            name=clean_name(args.get("name","Демонстрационная мастерская" if action=="demo" else current["name"] if action=="update" else None))
            description=book.textval(args.get("description",current["description"]),2000)
            color=args.get("color",current["color"])
            if color not in COLORS:raise ValueError("Неизвестный цвет.")
            rate=book.money(book.minor(args.get("hourly_rate",current["hourly_rate"])))
            existing=db.execute("SELECT id FROM pm_workshops WHERE account=? AND normalized=?",(a,name.casefold())).fetchone()
            if action=="update":
                w=current["id"]
                if existing and existing[0]!=w:raise Conflict("Мастерская с таким названием уже существует.")
                db.execute("UPDATE pm_workshops SET name=?,normalized=?,description=?,color=?,hourly_rate=? WHERE id=? AND account=?",(name,name.casefold(),description,color,rate,w,a))
            else:
                if existing:raise Conflict("Мастерская с таким названием уже существует.")
                w=uuid4().hex;db.execute("INSERT INTO workspaces(workspace_id,owner_id) VALUES(?,?)",(w,actor))
                db.execute("INSERT INTO pm_workshops(id,account,name,normalized,description,color,hourly_rate,demo) VALUES(?,?,?,?,?,?,?,?)",(w,a,name,name.casefold(),description,color,rate,int(action=="demo")))
                if action=="demo":seed_demo(db,w)
        result=metadata(db,w)
        db.execute("INSERT INTO pm_workshop_requests VALUES(?,?,?,?)",(a,rid,raw,encode(result)))
        return result
def seed_demo(db,w):
    from . import podmasterye_book as b
    from . import podmasterye_domain as d
    item=d._save(db,w,"demo-recipe",{"product":"Браслет (пример)","material":"Бусины (пример)","pack_quantity":400,"usage_quantity":40,"pack_price":"800","unit":"шт"})
    b.execute(db,w,"demo-purchase","purchase",{"material":item["material_id"],"quantity":3,"purchase_unit":"pack","total":"2400","supplier":"Учебный поставщик"})
    b.execute(db,w,"demo-manufacture","manufacture",{"product":item["product_id"],"quantity":10})
    b.execute(db,w,"demo-sale","sale",{"product":item["product_id"],"quantity":5,"unit_price":"300","paid_amount":"1500","channel":"Учебная витрина"})
    b.execute(db,w,"demo-expense","expense",{"category":"Реклама","total":"100"})
def choose_chat(store,token,requested=None):
    with store._write() as db:
        actor,a=_principal(db,token);ensure(db,a);w=resolve(db,a,requested)
        row=db.execute("SELECT chat FROM pm_workshop_chats WHERE account=? AND workshop=? ORDER BY rowid LIMIT 1",(a,w)).fetchone()
        if row:chat=row[0]
        else:
            if w==a:
                old=db.execute("SELECT c.chat_id FROM chats c LEFT JOIN pm_workshop_chats p ON p.chat=c.chat_id WHERE c.workspace_id=? AND p.chat IS NULL ORDER BY c.rowid LIMIT 1",(a,)).fetchone()
            else:old=None
            chat=old[0] if old else uuid4().hex
            _bind_chat(db,Scope(actor,a,chat))
            db.execute("INSERT INTO pm_workshop_chats VALUES(?,?,?)",(chat,a,w))
        return {"chatId":chat,"workshop":metadata(db,w)}
