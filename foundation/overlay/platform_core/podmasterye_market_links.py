"""Workshop-owned marketplace connections. Credentials are never returned or sent to AI."""
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
from . import integrations as upstream, podmasterye_workshops as workshops

PROVIDERS={p:{"title":upstream.PROVIDERS[p]["title"],"fields":upstream.PROVIDERS[p]["fields"]} for p in ("ozon","wb")}
SCHEMA="""CREATE TABLE IF NOT EXISTS pm_market_connections(
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK(provider IN('ozon','wb')), name TEXT NOT NULL,
 encrypted BLOB NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 checks TEXT NOT NULL DEFAULT '{}', checked INTEGER,
 UNIQUE(workspace,provider,name COLLATE NOCASE))"""

def init(db):db.execute(SCHEMA)

def private_write(path,data):
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+"-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

class Store:
    def __init__(self,identity,root):
        self.identity=identity;self.path=Path(root)/"market-connections.key"
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
        return upstream.credentials(p,fields)
    def get(self,db,w,c):
        row=db.execute("SELECT provider,name,encrypted,version,checks,checked FROM pm_market_connections WHERE workspace=? AND id=?",(w,c)).fetchone()
        if not row:raise HTTPException(404,"Подключение не найдено.")
        return row
    def public(self,w,c,row):
        p,n,e,v,checks,checked=row;f=self.unpack(w,c,p,e)
        checks=json.loads(checks)
        if p=="ozon":
            status="verified" if checks.get("Seller")=="verified" and all(x=="verified" for x in checks.values()) else "partial" if "verified" in checks.values() else "unconfirmed"
        else:status="verified" if "verified" in checks.values() else "unconfirmed"
        if checked is None:status="saved"
        return {"id":c,"provider":p,"name":n,"version":v,"configuredFields":sorted(f),"checks":checks,"checked":checked,"status":status}
    def list(self,token,w):
        with self.identity._lock:
            db=self.identity._db;w=self.scope(db,token,w)
            ids=[r[0] for r in db.execute("SELECT id FROM pm_market_connections WHERE workspace=? ORDER BY name,id",(w,))]
            return {"providers":PROVIDERS,"connections":[self.public(w,c,self.get(db,w,c)) for c in ids]}
    def save(self,token,w,p,name,fields):
        import sqlite3
        f=self.validate(p,fields)
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not name.isprintable():raise ValueError("Некорректное название магазина.")
        name=name.strip();c=uuid4().hex
        try:
            with self.identity._write() as db:
                w=self.scope(db,token,w)
                db.execute("INSERT INTO pm_market_connections(id,workspace,provider,name,encrypted) VALUES(?,?,?,?,?)",(c,w,p,name,self.pack(w,c,p,f)))
                return self.public(w,c,self.get(db,w,c))
        except sqlite3.IntegrityError:raise HTTPException(409,"Магазин с таким названием уже существует.") from None
    def update(self,token,w,c,version,fields):
        with self.identity._write() as db:
            w=self.scope(db,token,w);p,n,e,v,_,_=self.get(db,w,c)
            if type(version) is not int or version!=v:raise HTTPException(409,"Подключение изменилось. Обновите список.")
            if not isinstance(fields,dict) or not fields:raise ValueError("Укажите новые ключи.")
            f=self.validate(p,{**self.unpack(w,c,p,e),**self.validate(p,fields)})
            db.execute("UPDATE pm_market_connections SET encrypted=?,version=version+1,checks='{}',checked=NULL WHERE workspace=? AND id=?",(self.pack(w,c,p,f),w,c))
            return self.public(w,c,self.get(db,w,c))
    def remove(self,token,w,c,version):
        with self.identity._write() as db:
            w=self.scope(db,token,w);row=self.get(db,w,c)
            if type(version) is not int or version!=row[3]:raise HTTPException(409,"Подключение изменилось.")
            db.execute("DELETE FROM pm_market_connections WHERE workspace=? AND id=?",(w,c))
        return {"removed":True}
    async def check(self,token,w,c,client):
        with self.identity._lock:
            db=self.identity._db;w=self.scope(db,token,w);p,_,e,v,_,_=self.get(db,w,c);f=self.unpack(w,c,p,e)
        results=await upstream.probe(client,p,f)
        with self.identity._write() as db:
            self.scope(db,token,w)
            if not db.execute("UPDATE pm_market_connections SET checks=?,checked=unixepoch() WHERE workspace=? AND id=? AND version=?",(json.dumps(results,ensure_ascii=False),w,c,v)).rowcount:
                raise HTTPException(409,"Ключи изменились во время проверки.")
            return self.public(w,c,self.get(db,w,c))

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
        if kind=="keys":
            a=await body(req,"version","fields");return JSONResponse(s.update(t,w,c,a["version"],a["fields"]))
        if kind=="remove":
            a=await body(req,"version");return JSONResponse(s.remove(t,w,c,a["version"]))
        raise HTTPException(404)
    return [Route("/api/integrations/marketplaces",collection,methods=["GET","POST"]),
            Route("/api/integrations/marketplaces/{cid}/{action}",action,methods=["POST"])]
