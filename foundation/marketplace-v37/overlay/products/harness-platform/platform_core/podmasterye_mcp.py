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
from . import podmasterye_market_operations as market_operations
from functools import partial

class ProductionTools:
    def __init__(self,store,scope,request,grant):
        self.store,self.scope,self.request=store,scope,domain.key_id(request)
        self.digest=hashlib.sha256(grant.encode()).hexdigest() if grant else ""
        with self.store._lock:self.authorize(self.store._db)
        self.tools={
            "production_state":Capability("production_state","Получить текущие материалы, изделия и материальную себестоимость из БД.",{"type":"object","properties":{},"additionalProperties":False},self.snapshot),
            "accounting_report":Capability("accounting_report","Получить рассчитанный сервером отчёт: summary, stock, sales, planning, finance, journal. Укажите даты периода; ограничьте детализацию.",matrix.report_schema(),self.accounting_report),
            "seasonal_sources":Capability("seasonal_sources","Список доступных источников истории продаж: проведённый учёт и проверенные магазины Ozon, Wildberries и Яндекс Маркета. Не суммируй повторно одинаковые продажи из разных источников.",{"type":"object","properties":{},"additionalProperties":False},self.seasonal_sources),
            "material_forecast":Capability("material_forecast","Сезонный план закупок по историческим продажам одного источника и текущим рецептурам. Исторический период: от 1 до 12 месяцев YYYY-MM; target_from — первый месяц будущего периода такой же длины. growth — изменение объёма в %, reserve — страховой запас %, lead — срок поставки в днях. Используй source из seasonal_sources. При неполном покрытии, отсутствии рецептуры или сопоставления SKU не выдавай расчёт за полный. Для детализации укажи detail_month (YYYY-MM целевого периода); offset/limit для страниц деталей. Не проводит продажи и не списывает склад.",market_operations.FORECAST_SCHEMA,self.material_forecast),
            "record_details":Capability("record_details","Прочитать текущие точные поля материала, изделия, задачи, работника, тарифа, политики накладных или операции журнала по ID (для каталога можно точное название).",actions.RECORD_SCHEMA,self.record_details),
            "prepare_edit":Capability("prepare_edit","Подготовить точное изменение существующей хозяйственной записи. Передай только изменяемые поля; остальные сохраняются. kind=event для исторического исправления, укажи ID и причину. Сервер сохранит полную проверенную запись после завершения хода, если есть разрешение пользователя; иначе покажет подтверждение.",actions.EDIT_SCHEMA,self.prepare_edit,effect="edit"),
            "prepare_accounting":Capability("prepare_accounting",matrix.operation_description(),matrix.operation_schema(),self.prepare_accounting,effect="edit"),
            "form_catalog":Capability("form_catalog","Без параметров — перечень доступных форм. С параметром form — точные поля выбранной формы, типы, требования и значения по умолчанию.",{"type":"object","properties":{"form":{"type":"string","enum":agent.active_names()}},"additionalProperties":False},self.form_catalog),
            "current_form":Capability("current_form","Получить текущий пользовательский черновик формы для дополнения.",agent.empty_schema(),self.current_form),
            "prepare_form":Capability("prepare_form","Заполнить известные поля формы, включая неполные данные. Для полной хозяйственной операции сервер применяет действующее разрешение записи после завершения хода. Имена полей см. form_catalog.",agent.schema(),self.prepare_form,effect="edit"),
            "prepare_recipe":Capability("prepare_recipe","Подготовить форму материала и рецептуры. При разрешённой записи сервер проведёт рецептуру после успешного завершения хода; иначе покажет подтверждение. Количество в упаковке и расход на изделие — штуки, цена всей упаковки необязательна.",domain.RECIPE_SCHEMA,self.prepare),
        }
        for name, declaration in market_operations.REGISTRY.items():
            self.tools[name] = Capability(name, declaration["model_description"], declaration["input_schema"],
                partial(self.market_operation, operation=name), effect=declaration["effect"])
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

    def market_operation(self, scope, args, *, operation):
        with self.store._write() as db:
            self.authorize(db)
            w = workshops.chat_workspace(db, scope)
            result = market_operations.execute(db, w, operation, args,
                request_id="market-" + hashlib.sha256(domain.encode([self.request, operation, args]).encode()).hexdigest(), channel="chat")
            # UI presentation uses the same operation and durable job ID. It
            # never competes with a prepared accounting/mapping confirmation.
            if "marketCard" in result or "marketDraft" in result:
                agent.save_draft(db, scope, self.request, {**result, "page": "integrations", "missing": [],
                    "text": market_operations.summary(operation, result)})
            elif operation in ("market_sync_status","market_sync_request","market_sync_control"):
                key=(scope.workspace_id,scope.chat_id,self.request)
                existing=db.execute("SELECT value FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?",key).fetchone()
                has_record=any(db.execute("SELECT 1 FROM "+table+" WHERE workspace=? AND chat=? AND rid=?",key).fetchone() for table in ("pm_drafts","pm_accounting_drafts"))
                if not has_record and (not existing or json.loads(existing[0]).get("_presentation_only") is True):
                    target={"job_id":result["job_id"]} if result.get("job_id") else {"source":args.get("source","all_marketplaces")}
                    agent.save_draft(db,scope,self.request,{"_presentation_only":True,"marketCard":{"kind":"sync","arguments":target,"workshop":w},
                        "page":"integrations","missing":[],"text":market_operations.summary(operation,result)})
            return market_operations.model_projection(operation,result)
    def seasonal_sources(self,scope,args):
        from . import podmasterye_seasonal as seasonal
        with self.store._lock:
            self.authorize(self.store._db)
            return {"sources":seasonal.available(self.store._db,workshops.chat_workspace(self.store._db,scope))}
    def material_forecast(self,scope,args):
        from . import podmasterye_seasonal as seasonal
        params=dict(args);detail=params.pop("detail_month",None);offset=params.pop("offset",0);limit=params.pop("limit",30)
        with self.store._lock:
            self.authorize(self.store._db)
            d=seasonal.plan(self.store._db,workshops.chat_workspace(self.store._db,scope),**params)
        months=d.pop("months");hist=d.pop("historySales");totals=d.pop("totals");problems=d.pop("problems")
        d.update(problemCount=len(problems),problems=problems[offset:offset+limit],historySalesCount=len(hist),historySales=hist[offset:offset+limit],materialCount=len(totals),totals=totals[offset:offset+limit],offset=offset,limit=limit,
            monthSummary=[{"historyMonth":m["historyMonth"],"targetMonth":m["targetMonth"],"forecastSales":m["summary"]["forecastSales"],"returnDefectReplacements":m["summary"]["returnDefectReplacements"],"replacementDemand":m["summary"]["replacementDemand"],"produce":m["summary"]["produce"],"materialCount":len(m["materials"])} for m in months])
        if detail:
            m=next((m for m in months if m["targetMonth"]==detail),None)
            if m:d["monthDetail"]={"targetMonth":detail,"productCount":len(m["products"]),"materialCount":len(m["materials"]),"products":m["products"][offset:offset+limit],"materials":m["materials"][offset:offset+limit]}
        return d
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
            return {"current":agent.current(self.store._db,scope,self.request),"view":router.previous_view(self.store._db,scope,self.request),
                    "previousProposal":actions.previous_proposal(self.store._db,scope)}
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
            w=workshops.chat_workspace(db,scope)
            canonical=domain.recipe_args(args)
            canonical.setdefault("unit","шт")
            result["_prepared_revision"]=book.revision(db,w,"recipe",canonical)
            if db.execute("SELECT 1 FROM pm_accounting_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,self.request)).fetchone():raise ValueError("One draft per request")
            old_agent=db.execute('SELECT value FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?',(scope.workspace_id,scope.chat_id,self.request)).fetchone()
            if old_agent:
                if json.loads(old_agent[0]).get("_presentation_only") is not True:raise ValueError('One draft per request')
                db.execute('DELETE FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?',(scope.workspace_id,scope.chat_id,self.request))
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
