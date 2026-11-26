"""Versioned intent filter and bounded schema selection. No guessed financial writes."""
import json, math, re
from collections import Counter
from datetime import timedelta
from time import time
from . import podmasterye_matrix as matrix, podmasterye_book as book, podmasterye_agent_forms as agent, podmasterye_domain as domain

VERSION="routing-v11"
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
BUSINESS=re.compile(r"\b(?:мастерск\w*|производств\w*|закуп\w*|материал\w*|сырь\w*|издел\w*|бусин\w*|браслет\w*|рецептур\w*|рецепт\w*|себестоим\w*|прибыл\w*|выруч\w*|прода\w*|склад\w*|запас\w*|расход\w*|финанс\w*|отчет\w*|амортиз\w*|оборудован\w*|станок\w*|комисси\w*|работник\w*|сотрудник\w*|задач\w*|экономик\w*|денег|денежн\w*|интеграц\w*|телеграм\w*|telegram|ozon|озон|wildberries|wb|вб|кошелек|баланс|монет\w*|учет\w*|расчет\w*|калькулятор\w*|канал\w*|магазин\w*|товар\w*)\b",re.I)
OUTSIDE=re.compile(r"\b(?:погод\w*|столиц\w*|гороскоп\w*|футбол\w*|анекдот\w*|рецепт борща|напиши стих\w*|кто президент|python код|напиши код|игнорируй инструкц\w*)\b",re.I)
ANALYSIS=re.compile(r"\b(?:почему|сравни\w*|объясни\w*|проанализируй\w*|анализ\w*|причин\w*|оцен\w*|динамик\w*|прогноз\w*|снижен\w*|упал\w*|вырос\w*)\b")
READ=re.compile(r"\b(?:сколько|какая|какой|какие|покаж\w*|вывед\w*|отчет\w*|свер\w*|посчита\w*|рассчита\w*|сравни\w*)\b")
WRITE=re.compile(r"\b(?:добав\w*|созда\w*|запиш\w*|внес\w*|введ\w*|оформ\w*|купил\w*|закупил\w*|продал\w*|изготов\w*|измени\w*|обнови\w*|спиш\w*|сдела\w*|подготов\w*|заполн\w*|дополн\w*|заведи\w*)\b")
FORM_CUES={
 "purchase":r"\b(?:закуп\w*|купил\w*|покупк\w*)\b","sale":r"\b(?:продаж\w*|продал\w*)\b",
 "manufacture":r"\b(?:изготов\w*|выпуск\w*|партия|партию)\b","material":r"\bматериал\w*\b",
 "product":r"\b(?:издел\w*|товар\w*)\b","expense":r"\bрасход\w*\b","payment":r"\bоплат\w*\b",
 "return":r"\bвозврат\w*\b","task":r"\bзадач\w*\b","worker":r"\b(?:работник\w*|сотрудник\w*)\b",
 "asset_acquire":r"\b(?:станок\w*|оборудован\w*)\b","recipe_line":r"\bрецептур\w*\b","worker_payment":r"\bвыплат\w*\b",
 "opening":r"\bначальн\w+\s+остат\w*\b","writeoff":r"\bсписан\w*\b","sale_fee":r"\b(?:комисси\w*|удержан\w*)\b"}
EXTRA_CUES={"recipe":r"\b(?:рецепт\w*|рецептур\w*|норм\w* расход\w*|упаковк\w*|расчет\w*)\b","workshop_create":r"\bмастерск\w*\b","workshop_settings":r"\b(?:ставк\w* мастера|цвет мастерск\w*)\b","source_create":r"\b(?:источник\w*|свой магазин)\b","planning":r"\b(?:горизонт\w*|страхов\w*|план закуп\w*)\b","unit_target":r"\b(?:целевая цена|целевая прибыль|юнит)\b","filters":r"\b(?:фильтр\w*|категори\w*|период\w*)\b"}
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

def known(db,w,t,catalog):
    core,p=split_period(t)
    direct=matrix.route(db,w,t)
    if direct:
        ids=[direct.get("matrixId")]
        if any(r["id"] in ids and blocked(t,n) for _,r,n in catalog):return result("Фраза исключена из автоматического выбора. Уточните задачу.","excluded",ids)
        return {**direct,"filterReason":"exact","matrixVersion":VERSION,"matrixIds":ids}
    # Admin aliases and strictly order-preserving synonym matches, no fuzzy write.
    exact=[(a,r) for a,r,n in catalog if (a==core or (r["intent"] in ("faq","ui","report") and tokens(a)==tokens(core) and len(tokens(core))>=2)) and not blocked(t,n) and (not p or r["intent"] in ("ui","report"))]
    unique={r["id"]:r for a,r in exact}
    if len(unique)>1:return result("Уточните, какой раздел или показатель нужен: "+ "; ".join(r["aliases"][0] for r in list(unique.values())[:4])+".","ambiguous",tuple(unique))
    if len(unique)==1:
        r=next(iter(unique.values()));canonical=r["aliases"][0]+(" "+p if p else "")
        d=matrix.route(db,w,canonical)
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
        if k in assignments:return result("Поле указано дважды. Уточните одно значение.","ambiguous")
        assignments[k]=m[2]
    if not assignments and len(missing)==1 and (re.fullmatch(r"\d+(?:[.,]\d{1,2})?(?:\s*(?:₽|рублей|шт|штук|пачек))?",t.strip(),re.I) or (types[missing[0]] in ("material","product") and len(t.split())<=4)):
        assignments={missing[0]:t}
    if not assignments:return None
    try:
        parsed={k:parse_field(db,w,types[k],v) for k,v in assignments.items()}
        parsed=agent.normalize(db,w,form,parsed)
        return from_draft(db,scope,rid,form,{**a,**parsed})
    except ValueError as e:return result("Не удалось заполнить поле: "+str(e),"invalid_parameter")

def plan(t,ctx,ids):
    if ctx:
        f=ctx["form"]
        return {"tools":["current_form","prepare_accounting" if f.startswith("book.") else "prepare_form","form_catalog"],"forms":[f],"views":[]}
    # Narrow by lexical intent. BM25 is a candidate generator, not permission to execute.
    forms=[]
    if WRITE.search(t) or re.search(r"\b(?:архивир\w*|восстанов\w*|сторнир\w*|заверш\w*|перенес\w*|спис\w*|начн\w*)\b",t):
        forms=["book."+k for k,p in FORM_CUES.items() if re.search(p,t)]
        if "book.purchase" in forms:forms=[x for x in forms if x!="book.material"]
        if "book.worker_payment" in forms:forms=[x for x in forms if x!="book.worker"]
        forms += [k for k,p in EXTRA_CUES.items() if re.search(p,t)]
        if not forms:
            forms=["book."+ROWS[i]["op"] for i in ids if ROWS[i]["intent"]=="form" and len(set(tokens(t))&set(tokens(ROWS[i]["aliases"][0])))>=2][:3]
        if "book.sale_fee" in forms:forms=[f for f in forms if f not in ("book.sale","book.expense")]
        # For explicit forms use only the matching contract, never all 28 operations.
        if forms:
            forms=list(dict.fromkeys(forms))[:6]
            tools=["form_catalog"]
            if any(f.startswith("book.") for f in forms):tools.append("prepare_accounting")
            if any(not f.startswith("book.") for f in forms):tools.append("prepare_form")
            if "recipe" in forms:tools.append("prepare_recipe")
            if any(f.startswith("book.") for f in forms):tools.append("production_state")
            return {"tools":tools,"forms":forms,"views":[]}
    if ANALYSIS.search(t) or READ.search(t) or BUSINESS.search(t):
        views=[]
        if re.search(r"прибыл|финанс|выруч|денеж|расход|комисси",t):views.append("finance")
        if re.search(r"склад|остат|запас|сырь|материал",t):views.append("stock")
        if re.search(r"прода|товар|издел",t):views.append("sales")
        if re.search(r"закуп|прогноз",t):views.append("planning")
        if re.search(r"задач",t):views.append("tasks")
        if re.search(r"работник|сотрудник",t):views.append("workers")
        if re.search(r"оборудован|амортиз",t):views.append("assets")
        if re.search(r"себестоим|юнит|рентабель",t):views.append("unit")
        if not views:views=["summary"]
        # Summary is a small, useful companion for analytical questions.
        if ANALYSIS.search(t) and "summary" not in views:views.append("summary")
        return {"tools":["accounting_report","production_state"] if any(x in views for x in ("stock","unit","planning")) else ["accounting_report"],"forms":[],"views":views}
    return {"tools":[],"forms":[],"views":[]}

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
    return result("Уточните, какой показатель или раздел нужен за этот период.","clarify")

def choose(db,scope,rid,w,text,ctx,view=None):
    t=clean(text);cat=aliases(db);view=view or {}
    if not ctx:
        follow=view_followup(db,scope,w,t,view)
        if follow:return follow,{}
    if ctx:
        d=local_context(db,scope,rid,w,text,ctx)
        if d:return d,{}
        if OUTSIDE.search(t):return result("Помощник работает с учётом мастерской. Уточните поле формы.","outside"),{}
        return None,plan(t,ctx,[])
    if OUTSIDE.search(t):return result("Помогу с производством, учётом, продажами и экономикой мастерской. Уточните хозяйственный вопрос.","outside"),{}
    # Composite reads only. All components must resolve independently; no partial writes.
    pieces=re.split(r"\s*;\s*|\s+и\s+(?=(?:покажи|открой|выведи|сколько)\b)",t)
    if 1<len(pieces)<=5:
        matches=[known(db,w,p,cat) for p in pieces]
        if all(m and not m.get("accountingDraft") and m.get("filterReason") not in ("ambiguous","invalid_parameter") for m in matches):
            ids=[i for m in matches for i in m.get("matrixIds",[])]
            return result("\n".join(m["text"] for m in matches),"composite",ids,ui=matches[-1].get("ui",{})),{}
    # Full legacy recipe grammar is deliberately a draft now, not a silent mutation.
    if m:=domain.PATTERN.fullmatch(t):
        a=dict(material=m["material"],product=m["product"],pack_quantity=int(m["pack"]),usage_quantity=int(m["usage"]),pack_price=m["price"])
        d=domain.preview(a)
        return result("Подготовил рецептуру. "+domain.explain(d)+" Проверьте и сохраните форму.","recipe",ui={"page":"products"},draft=d),{}
    # Negation/condition cannot be silently stripped to a positive action.
    if re.search(r"\b(?:не (?:добавляй|записывай|показывай|открывай|создавай|списывай|продавай|сохраняй)|вместо|если|отмени запрос)\b",t):
        return result("Уточните, что нужно сделать. Ничего не изменено.","ambiguous"),{}
    d=known(db,w,t,cat)
    if d:return d,{}
    if re.fullmatch(r"почему (?:упала|снизилась|выросла|изменилась) (?:чистая )?прибыль",t):return compare_profit(db,w),{}
    # Natural complete read-only request, preserving meaning of its period.
    core,p=split_period(t)
    if re.fullmatch(r"(?:покажи|выведи|посчитай)\s+(?:мне\s+)?(?:чистую\s+)?прибыль",core):
        return known(db,w,"покажи чистую прибыль"+(" "+p if p else ""),cat),{}
    if not BUSINESS.search(t):
        return result("Не распознал хозяйственный запрос. Уточните показатель, раздел или операцию.","clarify"),{}
    ids=rank(t,cat)
    if len(tokens(core))<=1:
        labels=[ROWS[i]["aliases"][0] for i in ids if ROWS[i]["aliases"]][:3]
        return result("Уточните действие"+(": "+"; ".join(labels) if labels else "")+".","clarify",ids),{}
    # Unknown read/write question may use the model, but with bounded schemas.
    selected=plan(t,None,ids);selected["candidateIds"]=ids
    return None,selected

def record(db,scope,rid,out,selected,started,view=None):
    ids=(out or {}).get("matrixIds",selected.get("candidateIds",[]))
    kind="local" if out else "model"
    if selected:
        import hashlib
        selected["prefixId"]=hashlib.sha256(domain.encode({k:selected[k] for k in ("tools","forms","views")}).encode()+VERSION.encode()).hexdigest()[:16]
    reason=(out or {}).get("filterReason","model_fallback")
    db.execute("INSERT INTO pm_route_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (scope.workspace_id,scope.chat_id,rid,VERSION,kind,reason,domain.encode(ids),domain.encode(selected),started,int(time()*1000) if out else None,"complete" if out else "pending",domain.encode(view or {})))
def selection(db,scope,rid):
    r=db.execute("SELECT plan FROM pm_route_decisions WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
    return json.loads(r[0]) if r else None
