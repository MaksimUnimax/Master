"""Administrator configuration for the Telegram Login integration."""
import os
import json
import re
from pathlib import Path
from dataclasses import replace
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route
from .identity import _principal
from . import telegram_api as tg
from .podmasterye_market_links import private_write

def require_admin(db,token):
    actor,_=_principal(db,token)
    if not db.execute("SELECT 1 FROM identity_admins WHERE actor_id=?",(actor,)).fetchone():raise HTTPException(403,"Требуются права администратора.")

def configuration(fields):
    token=fields.get("bot_token");mode=fields.get("auth_mode")
    if not isinstance(token,str) or not re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{20,}",token):raise ValueError("Некорректный токен бота.")
    if mode not in ("widget","oidc"):raise ValueError("Некорректный способ входа.")
    bot=token.split(":",1)[0];username=fields.get("bot_username","");secret=fields.get("client_secret","")
    data={"client_id":bot,"bot_token":token,"auth_mode":mode}
    if mode=="widget":
        if not isinstance(username,str) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}",username.lstrip("@")):raise ValueError("Укажите имя Telegram-бота.")
        data["bot_username"]=username.lstrip("@")
        cfg=tg.Config(bot,None,token,None,data["bot_username"])
    else:
        if not isinstance(secret,str) or not 1<=len(secret)<=4096 or not secret.isascii() or not secret.isprintable():raise ValueError("Укажите Client Secret Telegram Login.")
        data["client_secret"]=secret
        cfg=tg.Config(bot,secret,token)
    route=os.getenv("PODMASTERYE_TELEGRAM_PROXY_PORT")
    if route:
        try:port=int(route)
        except ValueError:raise ValueError("Некорректная конфигурация маршрута Telegram.") from None
        if not 1<=port<=65535:raise ValueError("Некорректная конфигурация маршрута Telegram.")
        data["connect_proxy_port"]=port
        cfg=replace(cfg,proxy_port=port)
    return data,cfg

def routes(token_for,body):
    async def config(req):
        state=req.app.state;identity=state.identity;token=token_for(req,allow_cookie=True)
        with identity._lock:require_admin(identity._db,token)
        if req.method=="GET":
            cfg=state.telegram.config
            return JSONResponse({"configured":bool(cfg),"auth_mode":"oidc" if cfg and cfg.secret else "widget","callback":tg.CALLBACK,"origin":tg.SITE_ORIGIN})
        fields=await body(req,"bot_token","auth_mode",optional=("bot_username","client_secret"))
        data,cfg=configuration(fields)
        with identity._write() as db:
            require_admin(db,token)
            old=state.telegram.config
            if old and old.bot!=cfg.bot and db.execute("SELECT 1 FROM telegram_recipients LIMIT 1").fetchone():
                raise HTTPException(409,"Перед заменой бота отключите существующие привязки.")
            path=Path(state.worker.database_path).resolve().with_name("telegram.json")
            private_write(path,json.dumps(data).encode())
            db.execute("DELETE FROM telegram_integration_consents")
            state.telegram.config=cfg
        return JSONResponse({"configured":True,"auth_mode":fields["auth_mode"],"callback":tg.CALLBACK,"origin":tg.SITE_ORIGIN})
    return [Route("/api/admin/podmasterye/telegram-config",config,methods=["GET","POST"])]
