"""Optional deterministic shortcuts before the ordinary authenticated Harness agent."""
import json, math, re
from collections import Counter
from datetime import timedelta
from time import time
from . import podmasterye_matrix as matrix, podmasterye_book as book, podmasterye_agent_forms as agent, podmasterye_domain as domain

VERSION="agent-first-v15"
ROWS={x["id"]:x for x in matrix.ITEMS}
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_matrix_edits(
 id TEXT PRIMARY KEY, revision INTEGER NOT NULL, aliases TEXT NOT NULL,
 negatives TEXT NOT NULL, updated INTEGER NOT NULL, actor TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS pm_matrix_edit_history(
 seq INTEGER PRIMARY KEY, id TEXT NOT NULL, revision INTEGER NOT NULL,
 aliases TEXT NOT NULL, negatives TEXT NOT NULL, updated INTEGER NOT NULL, actor TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS pm_route_decisions(
 workspace TEXT NOT NULL,chat TEXT NOT NULL,rid TEXT NOT NULL,version TEXT NOT NULL,
 kind TEXT NOT NULL,reason TEXT NOT NULL,ids TEXT NOT NULL,plan TEXT NOT NULL,
 started INTEGER NOT NULL,finished INTEGER,outcome TEXT NOT NULL,view_context TEXT NOT NULL,
 PRIMARY KEY(workspace,chat,rid),
 FOREIGN KEY(workspace,chat,rid) REFERENCES pm_turns(workspace,chat,rid) ON DELETE CASCADE)""",
)
def init(db):
    for sql in SCHEMA:db.execute(sql)

# Closed linguistic transformations, not substring replacement of an arbitrary command.
COURTESY=re.compile(r"^(?:(?:пожалуйста|будь добр|будьте добры|можешь|можете|подскажи(?:те)?|скажи(?:те)?)\s*[, ]+\s*)+",re.I)
TAIL=re.compile(r"(?:\s*,?\s+пожалуйста)$",re.I)
def clean(text):
    t=matrix.norm(text)
    t=COURTESY.sub("",t);return matrix.norm(TAIL.sub("",t))
WORDS=re.compile(r"[а-яa-z0-9]+",re.I)
NEG=re.compile(r"\b(?:не|нельзя|без|кроме|вместо|отмена|отменить|почему|зачем|если|ли|как)\b")
# Retain qualifiers; never treat a question about a write as a write.
STOP={"покажи","покажите","скажи","скажите","подскажи","подскажите","пожалуйста","мне","мой","мои","мою","моих","моей"}
SYN={"покажите":"покажи","откройте":"открой","выведи":"покажи","отобрази":"покажи","отобразите":"покажи","выведите":"покажи",
     "рассчитай":"посчитай","подсчитай":"посчитай","запишите":"запиши","добавьте":"добавь","создайте":"создай","внесите":"внеси",
     "выручку":"выручка","прибылью":"прибыль","прибылей":"прибыль","прибыле":"прибыль","продажах":"продажи","продажам":"продажи",
     "остаток":"остатки","остатков":"остатки","материалов":"материалы","закупок":"закупки","закупку":"закупка",
     "закупки":"закупки","отчетность":"отчеты","отчет":"отчет","товаров":"товары","изделий":"изделия",
     "расходов":"расходы","расходам":"расходы","финансов":"финансы","станки":"оборудование"}
WRITE=re.compile(r"\b(?:добав\w*|созда\w*|запиш\w*|внес\w*|введ\w*|оформ\w*|купил\w*|закупил\w*|продал\w*|изготов\w*|измени\w*|обнови\w*|спиш\w*|сдела\w*|подготов\w*|заполн\w*|дополн\w*|заведи\w*)\b")
def edit_rows(db):
    return {i:{"revision":v,"aliases":json.loads(a),"negatives":json.loads(n)} for i,v,a,n in db.execute("SELECT id,revision,aliases,negatives FROM pm_matrix_edits")}
def tokens(t):return [SYN.get(w,w) for w in WORDS.findall(t) if w not in STOP]
def split_period(t):
    for p in matrix.PERIODS:
        if t.endswith(" "+p):return t[:-len(p)-1],p
    return t,None
def aliases(db):
    edits=edit_rows(db)
    result=[]
    for row in matrix.ITEMS:
        e=edits.get(row["id"],{})
        for a in [*row["aliases"],*e.get("aliases",[])]:result.append((clean(a),row,e.get("negatives",[])))
    return result
def blocked(t,negative):
    return any(re.search(r"(?<!\w)"+re.escape(clean(n))+r"(?!\w)",t) for n in negative)
def rank(t,catalog):
    """BM25 proposes candidates only. Exact grammar/unique lexical match permits execution."""
    terms=tokens(t)
    if not terms:return []
    docs=[tokens(a) for a,_,_ in catalog];avg=sum(map(len,docs))/max(1,len(docs))
    df=Counter(k for doc in docs for k in set(doc));scores={}
    for doc,(a,row,neg) in zip(docs,catalog):
        if blocked(t,neg):continue
        freq=Counter(doc);value=0
        for k in set(terms):
            f=freq[k]
            if f:value+=math.log(1+(len(docs)-df[k]+.5)/(df[k]+.5))*f*2.2/(f+1.2*(.25+.75*len(doc)/max(avg,1)))
        if value>0:scores[row["id"]]=max(scores.get(row["id"],0),value)
    return sorted(scores,key=lambda k:(-scores[k],k))[:5]

def result(text,reason,ids=(),**kwargs):
    return {"text":text,"matrixVersion":VERSION,"filterReason":reason,**({"matrixId":ids[0],"matrixIds":list(ids)} if ids else {}),**kwargs}

def known(db,w,t,catalog,faq=None):
    core,p=split_period(t)
    direct=matrix.route(db,w,t,faq)
    if direct:
        ids=[direct.get("matrixId")]
        if direct.get("unresolved") or any(r["id"] in ids and blocked(t,n) for _,r,n in catalog):return None
        return {**direct,"filterReason":"exact","matrixVersion":VERSION,"matrixIds":ids}
    # Admin aliases and strictly order-preserving synonym matches, no fuzzy write.
    exact=[(a,r) for a,r,n in catalog if (a==core or (r["intent"] in ("faq","ui","report") and tokens(a)==tokens(core) and len(tokens(core))>=2)) and not blocked(t,n) and (not p or r["intent"] in ("ui","report"))]
    unique={r["id"]:r for a,r in exact}
    if len(unique)>1:return None
    if len(unique)==1:
        r=next(iter(unique.values()));canonical=r["aliases"][0]+(" "+p if p else "")
        d=matrix.route(db,w,canonical,faq)
        if d:return {**d,"filterReason":"lexical","matrixVersion":VERSION,"matrixIds":[r["id"]]}
    return None

def from_draft(db,scope,rid,form,args,page=None):
    d=agent.draft(db,scope,rid,form,args,page)
    out={k:d[k] for k in ("accountingDraft","formDraft") if k in d}
    missing=d["missing"]
    err=d.get("accountingDraft",{}).get("validationError")
    msg="Подготовил форму. "+("Уточните: "+", ".join(missing)+"." if missing else "Проверьте данные перед сохранением.")
    if err:msg+=" "+err
    return result(msg,"form_context",ui={"page":d["page"]},**out)

def parse_field(db,w,typ,v):
    v=v.strip()
    if typ in ("int","int0"):
        m=re.fullmatch(r"(\d{1,10})(?:\s+(?:шт|штук|штуки|пачек|пачки|упаковок|дней|месяцев|минут))?",v,re.I)
        if not m:raise ValueError("Укажите целое количество.")
        return int(m[1])
    if typ in ("money","positive_money","percent"):
        m=re.fullmatch(r"(\d{1,12}(?:[.,]\d{1,2})?)(?:\s*(?:₽|рублей|руб\.?|%))?",v,re.I)
        if not m:raise ValueError("Укажите сумму или процент числом.")
        return m[1]
    if typ=="bool":
        if clean(v) in ("да","включить","верно"):return True
        if clean(v) in ("нет","выключить"):return False
        raise ValueError("Укажите да или нет.")
    if typ.startswith("choice:"):
        for a in typ[7:].split(","):
            if clean(a)==clean(v):return a
        raise ValueError("Выберите допустимое значение.")
    if typ in ("material","product") and typ=="material":
        row=matrix.read_material(db,w,v)
        if row:return row[0]
    return v

def local_context(db,scope,rid,w,t,ctx):
    if not ctx:return None
    form=ctx["form"];a=ctx["arguments"];types=agent._fields(form)
    labels={k:k for k in types}
    missing=[]
    if form.startswith("book."):
        fields=book.forms()[form[5:]]["fields"]
        for f in fields:
            labels[clean(f["label"])]=f["name"]
            if f["required"] and f["default"] is None and f["name"] not in a:missing.append(f["name"])
    else:
        required={"recipe":("product","material","pack_quantity","usage_quantity"),"workshop_create":("name",),"source_create":("name",)}
        missing=[k for k in required.get(form,()) if k not in a]
    labels.update({k:v for k,v in {"количество":"quantity","сумма":"total","цена":"unit_price","материал":"material","изделие":"product","название":"name","цена упаковки":"pack_price","поставщик":"supplier","дата":"day","канал":"channel","оплачено":"paid_amount","получено":"paid_amount","описание":"description","горизонт":"horizon","резерв":"safety","целевая прибыль":"target_profit"}.items() if v in types})
    # Explicit assignments only; no inference from an arbitrary sentence.
    assignments={}
    for part in re.split(r"[;\n]",t):
        m=re.fullmatch(r"\s*([^:=]{1,100})\s*[:=]\s*(.+?)\s*",part)
        if not m or clean(m[1]) not in labels:assignments={};break
        k=labels[clean(m[1])]
        if k in assignments:return None
        assignments[k]=m[2]
    if not assignments and len(missing)==1 and (re.fullmatch(r"\d+(?:[.,]\d{1,2})?(?:\s*(?:₽|рублей|шт|штук|пачек))?",t.strip(),re.I) or (types[missing[0]] in ("material","product") and len(t.split())<=4)):
        assignments={missing[0]:t}
    if not assignments:return None
    try:
        parsed={k:parse_field(db,w,types[k],v) for k,v in assignments.items()}
        parsed=agent.normalize(db,w,form,parsed)
        return from_draft(db,scope,rid,form,{**a,**parsed})
    except ValueError as e:return result("Не удалось заполнить поле: "+str(e),"invalid_parameter")

def compare_profit(db,w):
    from decimal import Decimal
    now=book.today();first=now.replace(day=1);last=first-timedelta(days=1);previous=last.replace(day=1)
    end=min(last,previous+timedelta(days=now.day-1))
    days=(end-previous).days+1;current_end=first+timedelta(days=days-1)
    a=book.aggregate(book.event_rows(db,w,previous.isoformat(),end.isoformat()))
    b=book.aggregate(book.event_rows(db,w,first.isoformat(),current_end.isoformat()))
    diff=lambda k:Decimal(b[k])-Decimal(a[k])
    parts=[("Выручка","revenue",1),("Себестоимость","cogs",-1),("Расходы","expenses",-1),("Списания","writeoffs",-1),("Амортизация","depreciation",-1),("Переоценка","valuation",-1),("Выбытие оборудования","asset_disposal",-1)]
    delta=diff("net_profit");values=[(label,diff(k)*sign) for label,k,sign in parts]
    assert delta==sum((v for _,v in values),Decimal(0))
    values.sort(key=lambda x:abs(x[1]),reverse=True)
    lines=[f"Чистая прибыль: {a['net_profit']} → {b['net_profit']} ₽ (изменение {delta:+.2f} ₽).",
           f"Равные периоды: {previous.isoformat()}—{end.isoformat()} и {first.isoformat()}—{current_end.isoformat()}."]
    lines.extend(f"{label}: {value:+.2f} ₽ к изменению прибыли." for label,value in values if value)
    lines.append("Это арифметическая декомпозиция учтённых операций, а не доказательство внешних причин изменения.")
    return result("\n".join(lines),"analysis",ui={"page":"finance","filters":{"from":first.isoformat(),"to":current_end.isoformat()},"highlight":"net_profit"})

def validate_view(value):
    if value is None:return {}
    if not isinstance(value,dict) or set(value)-{"page","metric","start","end","search","category","channel"}:raise ValueError("Некорректный контекст страницы.")
    out={}
    page=value.get("page")
    if page not in agent.PAGES:raise ValueError("Неизвестный раздел.")
    out["page"]=page
    for k in ("search","category","channel"):
        if value.get(k):out[k]=book.textval(value[k],240)
    for k in ("start","end"):
        if value.get(k):out[k]=book.dayval(value[k])
    if out.get("start","")>out.get("end","9999"):raise ValueError("Некорректный период.")
    if value.get("metric"):
        if value["metric"] not in matrix.METRICS:raise ValueError("Неизвестный показатель.")
        out["metric"]=value["metric"]
    return out

def previous_view(db,scope,rid):
    row=db.execute("SELECT view_context FROM pm_route_decisions WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
    return json.loads(row[0]) if row else {}

def view_followup(db,scope,w,t,view):
    p=next((p for p in matrix.PERIODS if t in (p,"а "+p,"покажи "+p)),None)
    if not p:return None
    metric=view.get("metric")
    # Prefer the explicit last displayed metric, never infer a different metric from a word.
    if not metric:
        row=db.execute("SELECT result FROM pm_turns WHERE workspace=? AND chat=? AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1",(scope.workspace_id,scope.chat_id)).fetchone()
        ui=json.loads(row[0]).get("ui",{}) if row else {}
        if not view or ui.get("page")==view.get("page"):metric=ui.get("highlight")
    entries=[r for r in matrix.ITEMS if r.get("metric")==metric and r["intent"]=="report"] if metric else []
    if len(entries)==1:
        d=known(db,w,entries[0]["aliases"][0]+" "+p,aliases(db))
        if d:d["filterReason"]="view_context";return d
    page=view.get("page")
    if page in ("finance","sales","purchases","expenses","journal","assets","workers"):
        start,end=matrix.dates(p)
        return result("Установил период в текущем разделе.","view_context",ui={"page":page,"filters":{"from":start,"to":end}})
    return None

def service_match(db,w,t,cat,faq):
    # Exact published questions only. The guest selector's subject filter must
    # not classify or reject authenticated member messages.
    entry=matrix.INDEX.get(t)
    if entry is None and re.fullmatch(r"[^\d]+[а-яa-z]7",t):
        entry=matrix.INDEX.get(t[:-1])
    if not entry or "public_topic" not in entry:return None
    return known(db,w,entry["aliases"][0],cat,faq)

def choose(db,scope,rid,w,text,ctx,view=None,*,attachments=False,has_files=False,faq=None):
    t=clean(text);cat=aliases(db);view=view or {}
    # Stable contract: the native agent is always the fallback. Ranking is
    # diagnostic only; it neither admits users nor removes tools.
    def fallback(reason):
        return None,{"reason":reason,"candidateIds":rank(t,cat),"contract":"production-tools-v2"}
    if attachments:return fallback("attachment")
    if ctx:
        d=local_context(db,scope,rid,w,text,ctx)
        if d:return d,{}
        return fallback("form_context_miss")
    service=service_match(db,w,t,cat,faq)
    if service:return service,{}
    if has_files and re.search(r"\b(?:файл\w*|вложен\w*|документ\w*|таблиц\w*|фото\w*|картинк\w*|изображен\w*|аудио|накладн\w*|скан\w*|pdf|xlsx|csv)\b",t):
        return fallback("file_reference")
    follow=view_followup(db,scope,w,t,view)
    if follow:return follow,{}
    # A compound query is local only if all parts are fully matched read commands.
    pieces=re.split(r"\s*;\s*|\s+и\s+(?=(?:покажи|открой|выведи|сколько)\b)",t)
    if 1<len(pieces)<=5:
        matches=[known(db,w,p,cat,faq) for p in pieces]
        if all(m and not m.get("accountingDraft") and not m.get("draft") for m in matches):
            ids=[i for m in matches for i in m.get("matrixIds",[])]
            return result("\n".join(m["text"] for m in matches),"composite",ids,ui=matches[-1].get("ui",{})),{}
    if m:=domain.PATTERN.fullmatch(t):
        a=dict(material=m["material"],product=m["product"],pack_quantity=int(m["pack"]),usage_quantity=int(m["usage"]),pack_price=m["price"])
        d=domain.preview(a)
        return result("Подготовил рецептуру. "+domain.explain(d)+" Проверьте и сохраните форму.","recipe",ui={"page":"products"},draft=d),{}
    if re.search(r"\b(?:не (?:добавляй|записывай|показывай|открывай|создавай|списывай|продавай|сохраняй)|вместо|если|отмени запрос)\b",t):
        return fallback("conditional")
    d=known(db,w,t,cat,faq)
    if d:return d,{}
    if re.fullmatch(r"почему (?:упала|снизилась|выросла|изменилась) (?:чистая )?прибыль",t):
        return compare_profit(db,w),{}
    core,p=split_period(t)
    if re.fullmatch(r"(?:покажи|выведи|посчитай)\s+(?:мне\s+)?(?:чистую\s+)?прибыль",core):
        d=known(db,w,"покажи чистую прибыль"+(" "+p if p else ""),cat,faq)
        if d:return d,{}
    return fallback("template_miss")

def record(db,scope,rid,out,selected,started,view=None):
    ids=(out or {}).get("matrixIds",selected.get("candidateIds",[]))
    kind="local" if out else "model"
    if selected:
        import hashlib
        selected["prefixId"]=hashlib.sha256(selected["contract"].encode()).hexdigest()[:16]
    reason=(out or {}).get("filterReason",selected.get("reason","model_fallback"))
    db.execute("INSERT INTO pm_route_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (scope.workspace_id,scope.chat_id,rid,VERSION,kind,reason,domain.encode(ids),domain.encode(selected),started,int(time()*1000) if out else None,"complete" if out else "pending",domain.encode(view or {})))
def selection(db,scope,rid):
    r=db.execute("SELECT plan FROM pm_route_decisions WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
    return json.loads(r[0]) if r else None
