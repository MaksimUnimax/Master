"""Independent quality parameters for planning, never synthetic ledger events."""
import re
from decimal import Decimal
from collections import defaultdict

SCHEMA="""CREATE TABLE IF NOT EXISTS pm_quality_policy(
 workspace TEXT PRIMARY KEY REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 return_defect_bps INTEGER CHECK(return_defect_bps BETWEEN 0 AND 10000),
 production_scrap_bps INTEGER CHECK(production_scrap_bps BETWEEN 0 AND 9999))"""
FIELDS=("return_defect_percent","production_scrap_percent")

def init(db):db.execute(SCHEMA)

def percent(value,*,production=False):
    if value is None or value=="":return None
    if not isinstance(value,str) or not re.fullmatch(r"\d{1,3}(?:[.,]\d{1,2})?",value):
        raise ValueError("Укажите процент с точностью до сотых или оставьте поле пустым.")
    n=int(Decimal(value.replace(",","."))*100)
    if not 0<=n<=10000 or production and n==10000:
        raise ValueError("Производственные потери должны быть меньше 100%; брак возвратов — от 0 до 100%.")
    return format(Decimal(n)/100,".2f")

def policy(db,w):
    r=db.execute("SELECT return_defect_bps,production_scrap_bps FROM pm_quality_policy WHERE workspace=?",(w,)).fetchone() or (None,None)
    return {k:format(Decimal(v)/100,".2f") if v is not None else None for k,v in zip(FIELDS,r)}

def save(db,w,args):
    # An omitted field is unchanged. Only an explicit null clears a value.
    # The book preview/revision contract protects this read/modify/write from
    # stale confirmations and the metadata receipt makes retries idempotent.
    current=policy(db,w)
    r=percent(args.get(FIELDS[0],current[FIELDS[0]]))
    s=percent(args.get(FIELDS[1],current[FIELDS[1]]),production=True)
    values=[int(Decimal(v)*100) if v is not None else None for v in (r,s)]
    db.execute("""INSERT INTO pm_quality_policy VALUES(?,?,?)
        ON CONFLICT(workspace) DO UPDATE SET return_defect_bps=excluded.return_defect_bps,
        production_scrap_bps=excluded.production_scrap_bps""",(w,*values))

def rates(p):
    return tuple(Decimal(p[k] or 0)/100 for k in FIELDS)

def replacement_demand(delivered,returned,defect):
    """Expected products consumed by sales plus unusable physical returns.
    Usable returns offset demand exactly once, not an extra stock receipt.
    """
    return Decimal(delivered)-Decimal(returned)*(1-defect)

def material_input(norm,scrap):
    """Scrap is a fraction of gross material input; norm is useful input."""
    return Decimal(norm)/(1-scrap)

def sales_components(events):
    """Calendar ledger flows, including signed reversals; not a cohort estimate."""
    out=defaultdict(lambda:{"delivered":0,"returned":0})
    for r,_ in events:
        pid=r.get("product_id");q=r.get("sales_quantity",0)
        if not pid or not q:continue
        kind=r.get("original_kind",r.get("kind"))
        if kind=="sale":out[pid]["delivered"]+=q
        elif kind=="return":out[pid]["returned"]-=q
    return dict(out)
