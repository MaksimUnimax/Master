"""Deterministic fixed asset register and depreciation. Integer kopecks.

Management accounting only: straight line over calendar days, acquisition date
included, retirement date excluded. Capex is cash flow; depreciation is noncash.
"""
from datetime import date,timedelta
from calendar import monthrange
from decimal import Decimal,ROUND_HALF_UP

def add_months(day,months):
    y,m=divmod(day.year*12+day.month-1+months,12)
    if y>9999:raise ValueError("Срок службы выходит за поддерживаемый диапазон дат.")
    return date(y,m+1,min(day.day,monthrange(y,m+1)[1]))
def life(asset):
    start=date.fromisoformat(asset["acquired"])
    if start.year<1900:raise ValueError("Год приобретения должен быть не ранее 1900.")
    end=add_months(start,asset["months"])
    return start,end,(end-start).days
def accumulated(asset,through):
    from . import podmasterye_book as b
    start,end,days=life(asset)
    through=min(through,date.fromisoformat(asset["retired"])-timedelta(days=1)) if asset.get("retired") else through
    count=max(0,min(days,(through-start).days+1))
    return b.prorate(asset["cost"]-asset["residual"],count,days)
def report(db,w,start,end):
    from . import podmasterye_book as b
    from .podmasterye_domain import encode
    lower=date.fromisoformat(start);upper=date.fromisoformat(end)
    events=[];assets=[]
    for key,raw in db.execute("SELECT key,value FROM pm_book_rows WHERE workspace=? AND type='asset' ORDER BY key",(w,)):
        import json
        a=json.loads(raw);acq,expiry,days=life(a)
        stop=min(upper,expiry-timedelta(days=1))
        if a.get("retired"):stop=min(stop,date.fromisoformat(a["retired"])-timedelta(days=1))
        first=max(acq,lower)
        current=first
        period_cost=0
        while current<=stop:
            last=min(stop,date(current.year,current.month,monthrange(current.year,current.month)[1]))
            cost=accumulated(a,last)-accumulated(a,current-timedelta(days=1))
            if cost:
                f=dict.fromkeys(b.FIN,0);f["depreciation"]=cost
                events.append(({"id":"dep-"+key+"-"+last.isoformat(),"kind":"depreciation","day":last.isoformat(),
                  "asset_id":key,"asset":a["name"],"category":"Амортизация","summary":"Амортизация: "+a["name"]+" · "+b.money(cost)+" ₽",
                  "note":"Расчётная неденежная операция","reversed":False,"derived":True,
                  "finance":{k:b.money(v) for k,v in f.items()}},f))
                period_cost+=cost
            if last==stop:break
            current=last+timedelta(days=1)
        asof=b.today()
        acc=accumulated(a,asof)
        active=not a.get("retired")
        assets.append({"id":key,"name":a["name"],"acquired":a["acquired"],"months":a["months"],"retired":a.get("retired"),
            "cost_rub":b.money(a["cost"]),"residual_rub":b.money(a["residual"]),"depreciation_rub":b.money(acc),
            "period_depreciation_rub":b.money(period_cost),"book_value_rub":b.money(a["cost"]-acc) if active else "0.00",
            "monthly_norm_rub":format((Decimal(a["cost"]-a["residual"])/100/a["months"]).quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f") if active and asof<expiry else "0.00",
            "paid":a["paid"],"note":a.get("note","")})
    return assets,events
