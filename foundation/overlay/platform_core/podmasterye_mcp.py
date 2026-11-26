"""Static built-in tools, not user plugins. The model cannot choose an account."""
import argparse
import asyncio
import hashlib
import json
import os
from .catalog import Capability
from .dispatch import UnavailableTool, InvalidToolInput, ToolExecutionFailed
from .mcp_server import serve_stdio
from .storage import Scope, Store, _owns_chat
from . import podmasterye_domain as domain

class ProductionTools:
    def __init__(self,store,scope,request,grant):
        self.store,self.scope,self.request=store,scope,domain.key_id(request)
        self.digest=hashlib.sha256(grant.encode()).hexdigest() if grant else ""
        self.tools={
            "production_state":Capability("production_state","Получить текущие материалы, изделия и материальную себестоимость из БД.",{"type":"object","properties":{},"additionalProperties":False},self.snapshot),
            "prepare_recipe":Capability("prepare_recipe","Подготовить форму материала и рецептуры. Не сохраняет изделие без подтверждения пользователя. Количество в упаковке и расход на изделие — штуки, цена всей упаковки необязательна.",domain.RECIPE_SCHEMA,self.prepare),
        }
    def authorize(self,db):
        s=self.scope
        if not _owns_chat(db,s):
            raise UnavailableTool("Tool unavailable in this chat")
        row=db.execute("""SELECT 1 FROM usage_grants g JOIN usage_operations o USING(operation_id)
          JOIN marketplace_retry_windows r ON r.token_hash=g.token_hash
          JOIN identity_sessions i ON i.digest=r.session_digest AND i.actor_id=o.actor_id
          JOIN workspace_paid_model_access p ON p.workspace_id=o.workspace_id
          WHERE g.token_hash=? AND g.expires_at>unixepoch() AND i.expires_at>unixepoch()
          AND o.actor_id=? AND o.workspace_id=? AND o.chat_id=? AND o.source='chat.turn' AND o.run_key=?""",
          (self.digest,s.actor_id,s.workspace_id,s.chat_id,self.request)).fetchone()
        if not row: raise UnavailableTool("Tool unavailable in this chat")
    def list_tools(self):
        with self.store._lock:
            self.authorize(self.store._db)
        return tuple(self.tools.values())
    def call_tool(self,name,args):
        tool=self.tools.get(name)
        if not tool: raise UnavailableTool("Tool unavailable in this chat")
        try: tool.validate(args)
        except ValueError: raise InvalidToolInput("Invalid tool input") from None
        try: return tool.handler(self.scope,args)
        except UnavailableTool: raise
        except (ValueError,TypeError): raise InvalidToolInput("Invalid tool input") from None
        except Exception: raise ToolExecutionFailed("Tool execution failed") from None
    def snapshot(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            return domain.state(self.store._db,scope.workspace_id)
    def prepare(self,scope,args):
        result=domain.preview(args)
        raw=domain.encode(domain.recipe_args(args))
        with self.store._write() as db:
            self.authorize(db)
            row=db.execute("SELECT args,result FROM pm_drafts WHERE workspace=? AND chat=? AND rid=?",
                           (scope.workspace_id,scope.chat_id,self.request)).fetchone()
            if row:
                if row[0]!=raw: raise ValueError("One draft per request")
                return {"draft":json.loads(row[1]),"saved":False}
            db.execute("INSERT INTO pm_drafts VALUES(?,?,?,?,?)",(scope.workspace_id,scope.chat_id,self.request,raw,domain.encode(result)))
        return {"draft":result,"saved":False}

def main():
    parser=argparse.ArgumentParser()
    for k in ("db","actor","workspace","chat","request"): parser.add_argument("--"+k,required=True)
    a=parser.parse_args()
    with Store(a.db,create=False) as store:
        asyncio.run(serve_stdio(ProductionTools(store,Scope(a.actor,a.workspace,a.chat),a.request,os.environ.get("PODMASTER_OPERATION_GRANT",""))))
if __name__=="__main__": main()
