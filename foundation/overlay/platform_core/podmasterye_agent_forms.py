"""Allowlisted, scoped form drafts. Never execute business writes."""
from . import podmasterye_book as book, podmasterye_domain as domain, podmasterye_workshops as workshops

EXTRA = {
    "recipe":("products",{"product":"text","material":"text","unit":"unit","pack_quantity":"int","usage_quantity":"int","pack_price":"money"}),
    "workshop_create":("settings",{"name":"text","description":"longtext"}),
    "workshop_settings":("settings",{"name":"text","description":"longtext","hourly_rate":"money","color":"choice:green,blue,amber,violet,gray"}),
    "source_create":("integrations",{"name":"text","auto_produce":"bool"}),
    "filters":("current",{"start":"date","end":"date","search":"text","category":"text","channel":"text","task_status":"choice:all,active,done,archived","show_archived":"bool","product_view":"choice:list,cards","material_view":"choice:list,cards"}),
    "planning":("planning",{"horizon":"int","lead":"int0","safety":"int0"}),
    "unit_target":("unit",{"target_profit":"money"}),
}
PAGES={"summary","materials","products","stock","purchases","manufacture","sales","expenses","finance","journal","planning","workers","assets","unit","tasks","settings","integrations"}
def init(db):
    for table in ("pm_agent_drafts","pm_agent_context"):
        db.execute(f"""CREATE TABLE IF NOT EXISTS {table}(
            workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
            chat TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
            rid TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(workspace,chat,rid))""")

def catalog():
    return {"accounting":book.forms(),"other":{k:{"page":page,"fields":fields} for k,(page,fields) in EXTRA.items()},"pages":sorted(PAGES)}

def _fields(name):
    if name.startswith("book.") and name[5:] in book.FIELDS:
        return {f["name"]:f["type"] for f in book.forms()[name[5:]]["fields"]}
    if name in EXTRA:return EXTRA[name][1]
    raise ValueError("Unknown form")

def _entity(db,w,t,v):
    if t in ("material","product"):return book.entity(db,w,t,v,include_archived=True)[0]
    if t in ("task","worker"):
        table="pm_tasks" if t=="task" else "pm_workers"
        rows=db.execute("SELECT id FROM "+table+" WHERE workspace=? AND (id=? OR name=? COLLATE NOCASE)",(w,v,v)).fetchall()
        if len(rows)!=1:raise ValueError("Object is missing or ambiguous")
        return rows[0][0]
    if t in ("sale","asset"):
        if not db.execute("SELECT 1 FROM pm_book_rows WHERE workspace=? AND type=? AND key=?",(w,t,v)).fetchone():raise ValueError("Object is unavailable")
        return v
    if t=="event":
        if not db.execute("SELECT 1 FROM pm_book_events WHERE workspace=? AND id=?",(w,v)).fetchone():raise ValueError("Event is unavailable")
        return v
    raise ValueError("Unknown entity")

def normalize(db,w,name,args):
    types=_fields(name)
    if not isinstance(args,dict) or set(args)-set(types):raise ValueError("Unknown form fields")
    out={}
    for n,v in args.items():
        t=types[n]
        if v is None or v=="":continue
        if t in ("int","int0"):v=book.quantity(v,t=="int0")
        elif t in ("money","positive_money","percent"):
            v=book.money(book.minor(v,t!="positive_money"))
            if t=="percent" and book.minor(v)>=10000:raise ValueError("Invalid percentage")
        elif t=="bool":
            if type(v) is not bool:raise ValueError("Expected boolean")
        elif t=="date":v=book.dayval(v)
        elif t=="future_date":
            from datetime import date
            if not isinstance(v,str) or len(v)!=10 or date.fromisoformat(v).isoformat()!=v:raise ValueError("Invalid date")
        elif t=="unit":
            if v not in book.UNITS:raise ValueError("Unknown unit")
        elif t=="category":
            if v not in book.CATEGORIES:raise ValueError("Unknown category")
        elif t.startswith("choice:"):
            if v not in t[7:].split(","):raise ValueError("Unknown choice")
        elif t in ("material","product","task","worker","sale","asset","event"):v=_entity(db,w,t,book.textval(v,120))
        elif t=="identifiers":v=book.textval(v,2000)
        else:v=book.textval(v,2000 if t=="longtext" else 240)
        out[n]=v
    if name=="planning" and any(v>365 for v in out.values()):raise ValueError("Period too long")
    if name=="recipe" and any(out.get(k,1)>10**9 for k in ("pack_quantity","usage_quantity")):raise ValueError("Quantity too large")
    if name=="filters" and out.get("start","")>out.get("end","9999"):raise ValueError("Invalid period")
    return out

def schema():
    return {"type":"object","properties":{
        "form":{"type":"string","enum":[*("book."+op for op in book.FIELDS),*EXTRA]},
        "arguments":{"type":"object","additionalProperties":{"type":["string","integer","boolean","null"]}},
        "page":{"type":"string","enum":sorted(PAGES)}
    },"required":["form","arguments"],"additionalProperties":False}

def empty_schema():return {"type":"object","properties":{},"additionalProperties":False}

def current(db,scope,rid):
    row=db.execute("SELECT value FROM pm_agent_context WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
    return __import__("json").loads(row[0]) if row else None

def context(db,scope,rid,value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)!={"form","arguments"} or not isinstance(value["form"],str):raise ValueError("Invalid form context")
    return {"form":value["form"],"arguments":normalize(db,workshops.chat_workspace(db,scope),value["form"],value["arguments"])}

def draft(db,scope,rid,name,args,page=None):
    w=workshops.chat_workspace(db,scope)
    a=normalize(db,w,name,args)
    previous=current(db,scope,rid)
    if previous and previous["form"]==name:a={**previous["arguments"],**a}
    if name.startswith("book."):
        op=name[5:]
        fields=book.forms()[op]["fields"]
        missing=[f["label"] for f in fields if f["required"] and f["default"] is None and f["name"] not in a]
        out={"operation":op,"arguments":a,"workshop":w,"missing":missing}
        if not missing:
            try:out=book.preview_action(db,w,op,book.validate(op,a))
            except ValueError as e:out["validationError"]=str(e)
        if missing:out["missing"]=missing
        return {"accountingDraft":out,"page":book.PAGES[op],"missing":missing}
    target=EXTRA[name][0]
    if target=="current":target=page or "summary"
    if target not in PAGES:raise ValueError("Unknown page")
    return {"formDraft":{"form":name,"arguments":a,"workshop":w},"page":target,"missing":[]}

def save_draft(db,scope,rid,result):
    raw=domain.encode(result)
    for table in ("pm_drafts","pm_accounting_drafts"):
        if db.execute("SELECT 1 FROM "+table+" WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone():raise ValueError("One draft per request")
    old=db.execute("SELECT value FROM pm_agent_drafts WHERE workspace=? AND chat=? AND rid=?",(scope.workspace_id,scope.chat_id,rid)).fetchone()
    if old:
        if old[0]!=raw:raise ValueError("One draft per request")
    else:db.execute("INSERT INTO pm_agent_drafts VALUES(?,?,?,?)",(scope.workspace_id,scope.chat_id,rid,raw))
    return {"draft":result,"saved":False}
