"""Workshop-owned marketplace connections. Credentials are never returned or sent to AI."""
import asyncio
import time
from weakref import WeakValueDictionary
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route
from .identity import _principal
from . import podmasterye_yandex_sales as sales, market_quantity as quantity
from . import integrations as upstream, podmasterye_workshops as workshops, podmasterye_yandex_market as yandex

PROVIDERS={p:{"title":upstream.PROVIDERS[p]["title"],"fields":upstream.PROVIDERS[p]["fields"]} for p in ("ozon","wb")}
PROVIDERS["yandex_market"]=yandex.PROVIDER
SCHEMA="""CREATE TABLE IF NOT EXISTS pm_market_connections(
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK(provider IN('ozon','wb','yandex_market')), name TEXT NOT NULL,
 encrypted BLOB NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 checks TEXT NOT NULL DEFAULT '{}', checked INTEGER, details TEXT NOT NULL DEFAULT '{}',
 UNIQUE(workspace,provider,name COLLATE NOCASE))"""

def init(db):
    # Domain initialization owns the transaction. The old encrypted values and
    # their associated-data identifiers are copied byte-for-byte.
    row=db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='pm_market_connections'").fetchone()
    if not row:
        db.execute(SCHEMA)
        return
    if "'yandex_market'" in row[0]:
        return
    # Fail closed if a future release adds a foreign-key dependency.
    for name, in db.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
        if any(fk[2]=="pm_market_connections" for fk in db.execute('PRAGMA foreign_key_list("'+name.replace('"','""')+'")')):
            raise RuntimeError("Marketplace migration requires an updated dependent-table plan")
    cols="id,workspace,provider,name,encrypted,version,checks,checked"
    db.execute(SCHEMA.replace("IF NOT EXISTS pm_market_connections","pm_market_connections_v33",1))
    db.execute("INSERT INTO pm_market_connections_v33("+cols+") SELECT "+cols+" FROM pm_market_connections")
    db.execute("DROP TABLE pm_market_connections")
    db.execute("ALTER TABLE pm_market_connections_v33 RENAME TO pm_market_connections")

def private_write(path,data):
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+"-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

class Store:
    def __init__(self,identity,root):
        self.identity=identity;self.path=Path(root)/"market-connections.key";self.sales_locks=WeakValueDictionary()
    def cipher(self):
        if not self.path.exists():
            if self.identity._db.execute("SELECT 1 FROM pm_market_connections LIMIT 1").fetchone():raise HTTPException(503,"Ключ шифрования отсутствует.")
            # Atomic creation without replacing an existing key.
            fd,tmp=tempfile.mkstemp(prefix=".market-key-",dir=self.path.parent)
            try:
                with os.fdopen(fd,"wb") as f:
                    f.write(AESGCM.generate_key(bit_length=256));f.flush();os.fsync(f.fileno())
                try:os.link(tmp,self.path)
                except FileExistsError:pass
            finally:Path(tmp).unlink(missing_ok=True)
        try:return AESGCM(self.path.read_bytes())
        except (OSError,ValueError):raise HTTPException(503,"Хранилище ключей недоступно.") from None
    def scope(self,db,token,w):
        return workshops.resolve(db,_principal(db,token)[1],w)
    def pack(self,w,c,p,fields):
        n=os.urandom(12);return n+self.cipher().encrypt(n,json.dumps(fields).encode(),json.dumps([w,c,p]).encode())
    def unpack(self,w,c,p,data):
        from cryptography.exceptions import InvalidTag
        try:return json.loads(self.cipher().decrypt(data[:12],data[12:],json.dumps([w,c,p]).encode()))
        except (InvalidTag,ValueError):raise HTTPException(503,"Не удалось открыть хранилище ключей.") from None
    def validate(self,p,fields):
        if p not in PROVIDERS:raise ValueError("Неизвестная площадка.")
        return yandex.credentials(fields) if p=="yandex_market" else upstream.credentials(p,fields)
    def get(self,db,w,c):
        row=db.execute("SELECT provider,name,encrypted,version,checks,checked,details FROM pm_market_connections WHERE workspace=? AND id=?",(w,c)).fetchone()
        if not row:raise HTTPException(404,"Подключение не найдено.")
        return row
    def public(self,w,c,row):
        p,n,e,v,checks,checked,details=row;f=self.unpack(w,c,p,e)
        checks=json.loads(checks)
        if p=="ozon":
            status="verified" if checks.get("Seller")=="verified" and all(x=="verified" for x in checks.values()) else "partial" if "verified" in checks.values() else "unconfirmed"
        elif p=="yandex_market":
            status="verified" if checks and all(x=="verified" for x in checks.values()) else "partial" if "verified" in checks.values() else "unconfirmed"
        else:status="verified" if "verified" in checks.values() else "unconfirmed"
        if checked is None:status="saved"
        result={"id":c,"provider":p,"name":n,"version":v,"configuredFields":sorted(f),"checks":checks,"checked":checked,"status":status}
        if p=="yandex_market":result["details"]=json.loads(details)
        return result
    def list(self,token,w):
        with self.identity._lock:
            db=self.identity._db;w=self.scope(db,token,w)
            ids=[r[0] for r in db.execute("SELECT id FROM pm_market_connections WHERE workspace=? ORDER BY name,id",(w,))]
            return {"providers":PROVIDERS,"connections":[self.public(w,c,self.get(db,w,c)) for c in ids]}
    def save(self,token,w,p,name,fields,*,request_id=None):
        import sqlite3
        f=self.validate(p,fields)
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not name.isprintable():raise ValueError("Некорректное название магазина.")
        name=name.strip();c=uuid4().hex
        try:
            with self.identity._write() as db:
                w=self.scope(db,token,w)
                args={"provider":p,"name":name,"fields":f}
                old=quantity.receipt(db,w,request_id,"connection.save",args)
                if old:return old
                db.execute("INSERT INTO pm_market_connections(id,workspace,provider,name,encrypted) VALUES(?,?,?,?,?)",(c,w,p,name,self.pack(w,c,p,f)))
                result=self.public(w,c,self.get(db,w,c))
                jid=quantity.enqueue_identity(db,w,c)
                result.update(job_id=jid,job=quantity.job_public(db,jid,w),state="collecting")
                quantity.receipt(db,w,request_id,"connection.save",args,result)
                return result
        except sqlite3.IntegrityError:raise HTTPException(409,"Магазин с таким названием уже существует.") from None
    def update(self,token,w,c,version,fields,*,request_id=None):
        with self.identity._write() as db:
            w=self.scope(db,token,w)
            args={"connection_id":c,"version":version,"fields":fields}
            old=quantity.receipt(db,w,request_id,"connection.update",args)
            if old:return old
            p,n,e,v,_,_,_=self.get(db,w,c)
            if type(version) is not int or version!=v:raise HTTPException(409,"Подключение изменилось. Обновите список.")
            if not isinstance(fields,dict) or not fields:raise ValueError("Укажите новые ключи.")
            f=self.validate(p,{**self.unpack(w,c,p,e),**self.validate(p,fields)})
            quantity.invalidate_connection(db,c)
            db.execute("UPDATE pm_market_connections SET encrypted=?,version=version+1,checks='{}',checked=NULL,details='{}' WHERE workspace=? AND id=?",(self.pack(w,c,p,f),w,c))
            result=self.public(w,c,self.get(db,w,c))
            jid=quantity.enqueue_identity(db,w,c,refresh=True)
            result.update(job_id=jid,job=quantity.job_public(db,jid,w),state="collecting")
            quantity.receipt(db,w,request_id,"connection.update",args,result)
            return result
    def remove(self,token,w,c,version,*,request_id=None):
        with self.identity._write() as db:
            w=self.scope(db,token,w)
            args={"connection_id":c,"version":version}
            old=quantity.receipt(db,w,request_id,"connection.remove",args)
            if old:return old
            row=self.get(db,w,c)
            if type(version) is not int or version!=row[3]:raise HTTPException(409,"Подключение изменилось.")
            quantity.invalidate_connection(db,c,"Подключение отключено пользователем.")
            db.execute("DELETE FROM pm_market_connections WHERE workspace=? AND id=?",(w,c))
            result={"removed":True}
            quantity.receipt(db,w,request_id,"connection.remove",args,result)
        return result
    def _source(self,db,w,c,campaign=None):
        stores=quantity.selected_stores(db,w,c)
        if campaign is not None:stores=[s for s in stores if s["metadata"].get("campaignId")==campaign]
        if len(stores)!=1:raise HTTPException(409,"Выберите подтверждённый магазин.")
        return stores[0]

    async def collect_orders(self,token,w,c,campaign,a,b,refresh,client):
        # Compatibility adapter: all new collection uses the same durable queue.
        # It never invokes the legacy request-bound pagination implementation.
        from . import podmasterye_market_analytics as analytics
        with self.identity._write() as db:
            w=self.scope(db,token,w);s=self._source(db,w,c,campaign)
            if type(refresh) is not bool:raise ValueError("Некорректный запрос.")
            if refresh:return quantity.market_sync_request(db,w,s["id"],a,b,refresh=True)
            return analytics.sales(db,w,from_=a,to=b,source=s["id"])

    async def realization(self,token,w,c,campaign,m,refresh,client):
        from . import podmasterye_market_analytics as analytics
        from datetime import timedelta
        a=sales.month_value(m);b=(a.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        b=min(b,sales.today())
        with self.identity._write() as db:
            w=self.scope(db,token,w);s=self._source(db,w,c,campaign)
            if type(refresh) is not bool:raise ValueError("Некорректный запрос.")
            if refresh:return quantity.market_sync_request(db,w,s["id"],str(a),str(b),refresh=True)
            return analytics.sales(db,w,from_=str(a),to=str(b),source=s["id"])

    async def check(self,token,w,c,client):
        with self.identity._write() as db:
            w=self.scope(db,token,w);self.get(db,w,c)
            jid=quantity.enqueue_identity(db,w,c,refresh=True)
            result=self.public(w,c,self.get(db,w,c))
            result.update(job_id=jid,job=quantity.job_public(db,jid,w),state="collecting")
        state=getattr(self,"state",None)
        if state and state.market_collector:state.market_collector.wake.set()
        return result

def routes(token_for,body):
    async def collection(req):
        s=req.app.state.market_links;t=token_for(req,allow_cookie=True);w=req.query_params.get("workshop")
        if req.method=="GET":return JSONResponse(s.list(t,w))
        a=await body(req,"provider","name","fields")
        return JSONResponse(s.save(t,w,a["provider"],a["name"],a["fields"]))
    async def action(req):
        s=req.app.state.market_links;t=token_for(req,allow_cookie=True);w=req.query_params.get("workshop");c=req.path_params["cid"]
        kind=req.path_params["action"]
        if kind=="check":
            await body(req);return JSONResponse(await s.check(t,w,c,req.app.state.http))
        if kind=="orders":
            a=await body(req,"campaignId","from","to","refresh")
            return JSONResponse(await s.collect_orders(t,w,c,a["campaignId"],a["from"],a["to"],a["refresh"],req.app.state.http))
        if kind=="realization":
            a=await body(req,"campaignId","month","refresh")
            return JSONResponse(await s.realization(t,w,c,a["campaignId"],a["month"],a["refresh"],req.app.state.http))
        if kind=="keys":
            a=await body(req,"version","fields");return JSONResponse(s.update(t,w,c,a["version"],a["fields"]))
        if kind=="remove":
            a=await body(req,"version");return JSONResponse(s.remove(t,w,c,a["version"]))
        raise HTTPException(404)
    return [Route("/api/integrations/marketplaces",collection,methods=["GET","POST"]),
            Route("/api/integrations/marketplaces/{cid}/{action}",action,methods=["POST"])]
