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
from . import podmasterye_domain as domain, podmasterye_book as book, podmasterye_matrix as matrix, podmasterye_workshops as workshops, podmasterye_agent_forms as agent

from . import podmasterye_agent_actions as actions

class ProductionTools:
    def __init__(self,store,scope,request,grant):
        self.store,self.scope,self.request=store,scope,domain.key_id(request)
        self.digest=hashlib.sha256(grant.encode()).hexdigest() if grant else ""
        with self.store._lock:self.authorize(self.store._db)
        self.tools={
            "production_state":Capability("production_state","Получить текущие материалы, изделия и материальную себестоимость из БД.",{"type":"object","properties":{},"additionalProperties":False},self.snapshot),
            "accounting_report":Capability("accounting_report","Получить рассчитанный сервером отчёт: summary, stock, sales, planning, finance, journal. Укажите даты периода; ограничьте детализацию.",matrix.report_schema(),self.accounting_report),
            "record_details":Capability("record_details","Прочитать текущие точные поля материала, изделия, задачи, работника, тарифа, политики накладных или операции журнала по ID (для каталога можно точное название).",actions.RECORD_SCHEMA,self.record_details),
            "prepare_edit":Capability("prepare_edit","Подготовить точное изменение существующей хозяйственной записи. Передай только изменяемые поля; остальные сохраняются. kind=event для исторического исправления, укажи ID и причину. Сохранение выполняется только после подтверждения пользователя.",actions.EDIT_SCHEMA,self.prepare_edit,effect="edit"),
            "prepare_accounting":Capability("prepare_accounting",matrix.operation_description(),matrix.operation_schema(),self.prepare_accounting,effect="edit"),
            "form_catalog":Capability("form_catalog","Без параметров — перечень доступных форм. С параметром form — точные поля выбранной формы, типы, требования и значения по умолчанию.",{"type":"object","properties":{"form":{"type":"string","enum":agent.active_names()}},"additionalProperties":False},self.form_catalog),
            "current_form":Capability("current_form","Получить текущий пользовательский черновик формы для дополнения.",agent.empty_schema(),self.current_form),
            "prepare_form":Capability("prepare_form","Заполнить известные поля формы, включая неполные данные. Не сохраняет запись. Имена полей см. form_catalog.",agent.schema(),self.prepare_form,effect="edit"),
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
    def record_details(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            return actions.details(self.store._db,workshops.chat_workspace(self.store._db,scope),args["kind"],args.get("id",""))
    def prepare_edit(self,scope,args):
        with self.store._write() as db:
            self.authorize(db)
            return actions.prepare_edit(db,scope,self.request,args)
    def snapshot(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            d=domain.state(self.store._db,workshops.chat_workspace(self.store._db,scope))
            for k,v in list(d.items()):
                if isinstance(v,list) and len(v)>30:d[k]=v[:30];d[k+"_truncated"]=len(v)-30
            return d
    def accounting_report(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            result=book.report(self.store._db,workshops.chat_workspace(self.store._db,scope),**args)
            # Keep model responses bounded. Complete detail remains available in the browser.
            for k,v in list(result.items()):
                if isinstance(v,list) and len(v)>30:
                    result[k]=v[:30];result[k+"_truncated"]=len(v)-30
            return result
    def form_catalog(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            form=args.get("form")
            if form:return agent.catalog([form])
            return {"forms":[{"form":"book."+k,"label":v["title"]} for k,v in book.forms().items()]+[{"form":k,"page":v[0]} for k,v in agent.active_extra().items()]}
    def current_form(self,scope,args):
        with self.store._lock:
            self.authorize(self.store._db)
            from . import podmasterye_router as router
            return {"current":agent.current(self.store._db,scope,self.request),"view":router.previous_view(self.store._db,scope,self.request)}
    def prepare_form(self,scope,args):
        with self.store._write() as db:
            self.authorize(db)
            result=agent.draft(db,scope,self.request,args["form"],args["arguments"],args.get("page"))
            return agent.save_draft(db,scope,self.request,result)
    def prepare_accounting(self,scope,args):
        with self.store._write() as db:
            self.authorize(db)
            result=agent.draft(db,scope,self.request,"book."+args["operation"],args["arguments"])
            agent.save_draft(db,scope,self.request,result)
            return {"draft":result["accountingDraft"],"saved":False}
    def prepare(self,scope,args):
        result=domain.preview(args)
        raw=domain.encode(domain.recipe_args(args))
        with self.store._write() as db:
            self.authorize(db)
            workshops.chat_workspace(db,scope)
            if db.execute("SELECT 1 FROM pm_accounting_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,self.request)).fetchone():raise ValueError("One draft per request")
            if db.execute('SELECT 1 FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?',(scope.workspace_id,scope.chat_id,self.request)).fetchone():raise ValueError('One draft per request')
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
