"""Calendar demand history and seasonal purchase planning. Read-only forecast.
Marketplace snapshots are NOT ledger sales and never move inventory.
"""
import json,re,calendar
from datetime import date,timedelta
from decimal import Decimal,ROUND_CEILING
from collections import defaultdict
from starlette.exceptions import HTTPException
from . import podmasterye_book as book, podmasterye_workshops as workshops, podmasterye_quality as quality
from .identity import _principal

SCHEMA="""CREATE TABLE IF NOT EXISTS pm_ym_product_links(
 cid TEXT NOT NULL REFERENCES pm_market_connections(id) ON DELETE CASCADE,
 campaign INTEGER NOT NULL,business INTEGER NOT NULL,sku TEXT NOT NULL,
 product TEXT NOT NULL REFERENCES pm_products(id) ON DELETE CASCADE,
 PRIMARY KEY(cid,campaign,business,sku))"""
def init(db):db.execute(SCHEMA)

def month(v):
    if not isinstance(v,str) or not re.fullmatch(r"\d{4}-\d{2}",v):raise ValueError("Укажите календарный месяц (ГГГГ-ММ).")
    d=date.fromisoformat(v+"-01")
    if not 2000<=d.year<=2100:raise ValueError("Недопустимый год.")
    return d
def shift(d,n):
    i=d.year*12+d.month-1+n
    return date(i//12,i%12+1,1)
def code(d):return d.isoformat()[:7]
def months(a,b):
    a,b=month(a),month(b)
    n=(b.year-a.year)*12+b.month-a.month+1
    if not 1<=n<=12:raise ValueError("Выберите от одного до 12 календарных месяцев.")
    if b>book.today().replace(day=1):raise ValueError("История не может быть в будущем.")
    return [shift(a,i) for i in range(n)]
def source_ref(cid,campaign):return "ym:"+cid+":"+str(campaign)
def available(db,w):
    out=[{"id":"ledger","title":"Проведённые продажи мастерской","kind":"ledger"}]
    from . import market_quantity
    stores=market_quantity.selected_stores(db,w)
    if stores:
        out.append({"id":"all_marketplaces","title":"Все подтверждённые маркетплейсы","kind":"marketplaces"})
        names={"ozon":"Ozon","wb":"Wildberries","yandex_market":"Яндекс Маркет"}
        for p in names:
            if any(s["provider"]==p for s in stores):out.append({"id":p,"title":names[p],"kind":p})
        out.extend({"id":s["store_id"],"title":names[s["provider"]]+" · "+s["name"],"kind":s["provider"]} for s in stores)
    for cid,name,details in db.execute("SELECT id,name,details FROM pm_market_connections WHERE workspace=? AND provider='yandex_market' ORDER BY name,id",(w,)):
        d=json.loads(details)
        if not d.get("complete"):continue
        for s in d.get("campaigns",[]):
            if s.get("apiAvailability") not in ("","AVAILABLE"):continue
            out.append({"id":source_ref(cid,s["campaignId"]),"title":"Яндекс Маркет · "+name+" · "+str(s["campaignId"]),"kind":"yandex_market","campaignId":s["campaignId"]})
    return out

def resolve(db,w,source):
    if not isinstance(source,str):raise ValueError("Укажите источник истории.")
    m=re.fullmatch(r"ym:([a-f0-9]{32}):([0-9]{1,19})",source)
    if not m:raise ValueError("Неизвестный источник истории.")
    cid=m[1];campaign=int(m[2])
    if campaign>=2**63:raise ValueError("Некорректный магазин.")
    row=db.execute("SELECT version,details,name FROM pm_market_connections WHERE workspace=? AND id=? AND provider='yandex_market'",(w,cid)).fetchone()
    if not row:raise HTTPException(404,"Подключение не найдено.")
    v,raw,name=row;details=json.loads(raw)
    shop=next((s for s in details.get("campaigns",[]) if s["campaignId"]==campaign),None)
    if not details.get("complete") or not shop or shop.get("apiAvailability") not in ("","AVAILABLE"):raise HTTPException(409,"Проверьте связь с магазином.")
    return cid,v,shop,name

def history(db,w,source,a,b):
    """Only the current verified connection/version; no overlapping snapshots summed."""
    if not isinstance(source,str) or not source.startswith("ym:"):
        from . import podmasterye_market_analytics as analytics
        ms=months(a,b);result=[];products=[]
        for m in ms:
            end=min(book.today(),shift(m,1)-timedelta(days=1))
            data=analytics.planning_sales(db,w,from_=m.isoformat(),to=end.isoformat(),source=source)
            result.append({"month":code(m),"state":"partial_month" if m==book.today().replace(day=1) else "ready" if data["complete"] else "partial",
                           "totals":data["totals"],"coverage":data["coverage"],"problems":data["problems"]})
            products.extend({**r,"month":code(m)} for r in data["rows"])
        return {"source":source,"from":a,"to":b,"months":result,"products":products,"complete":all(r["state"]=="ready" for r in result)}
    ms=months(a,b);cid,v,shop,name=resolve(db,w,source)
    rows={m:(state,requested,updated,json.loads(raw) if raw else None,error) for m,state,requested,updated,raw,error in db.execute(
        "SELECT month,state,requested,updated,data,error FROM pm_ym_realization WHERE cid=? AND version=? AND campaign=? AND month BETWEEN ? AND ?",
        (cid,v,shop["campaignId"],a,b))}
    result=[];units={}
    for m in ms:
        k=code(m);state,req,upd,data,error=rows.get(k,("not_collected",None,None,None,None))
        if data is not None and state=="ready":
            coverage="partial_month" if m==book.today().replace(day=1) else "no_data" if data.get("noData") else "ready"
            if data.get("month")!=k or data.get("kind")!="realization":raise book.Conflict("Некорректная история реализации.")
            for p in data.get("products",[]):
                sku=p["sku"]
                u=units.setdefault(sku,{"sku":sku,"name":p["name"],"delivered":0,"returned":0,"net":0,"unredeemed":0})
                for f in ("delivered","returned","net","unredeemed"):u[f]+=p[f]
            totals=data["totals"]
        else:
            coverage="invalid_snapshot" if state=="ready" else state;totals=None
        result.append({"month":k,"state":coverage,"collected":data.get("collected") if data and state=="ready" else None,
                       "totals":totals,"error":error})
    latest=db.execute("SELECT MAX(requested) FROM pm_ym_realization WHERE cid=? AND version=?",(cid,v)).fetchone()[0]
    import time
    mappings=dict(db.execute("SELECT sku,product FROM pm_ym_product_links WHERE cid=? AND campaign=? AND business=?",(cid,shop["campaignId"],shop["businessId"])))
    products=[]
    for sku,u in sorted(units.items()):
        pid=mappings.get(sku);p=db.execute("SELECT name,archived FROM pm_products WHERE workspace=? AND id=?",(w,pid)).fetchone() if pid else None
        products.append({**u,"productId":pid if p and not p[1] else None,"product":p[0] if p and not p[1] else None})
    return {"source":source,"shop":name,"campaignId":shop["campaignId"],"from":a,"to":b,"months":result,"products":products,
            "complete":all(r["state"]=="ready" for r in result),
            "retryAfterSeconds":max(0,120-(int(time.time())-latest)) if latest else 0}

def map_product(db,w,source,sku,product):
    if not isinstance(source,str) or not source.startswith("ym:"):
        from .market_quantity import map_product as market_map
        return market_map(db,w,source,sku,product)
    cid,v,shop,_=resolve(db,w,source)
    if not isinstance(sku,str) or not 1<=len(sku)<=255 or not sku.isprintable():raise ValueError("Некорректный артикул.")
    # Only observed articles in saved, ready reports may be mapped.
    observed=False
    for raw, in db.execute("SELECT data FROM pm_ym_realization WHERE cid=? AND version=? AND campaign=? AND state='ready' AND data IS NOT NULL",(cid,v,shop["campaignId"])):
        if any(p.get("sku")==sku for p in json.loads(raw).get("products",[])):observed=True;break
    if not observed:raise ValueError("Артикул отсутствует в собранной истории.")
    if product is None:
        db.execute("DELETE FROM pm_ym_product_links WHERE cid=? AND campaign=? AND business=? AND sku=?",(cid,shop["campaignId"],shop["businessId"],sku))
        return {"sku":sku,"productId":None}
    if not isinstance(product,str) or not db.execute("SELECT 1 FROM pm_products WHERE workspace=? AND id=? AND archived=0",(w,product)).fetchone():
        raise ValueError("Изделие недоступно в этой мастерской.")
    db.execute("""INSERT INTO pm_ym_product_links VALUES(?,?,?,?,?)
        ON CONFLICT(cid,campaign,business,sku) DO UPDATE SET product=excluded.product""",(cid,shop["campaignId"],shop["businessId"],sku,product))
    return {"sku":sku,"productId":product}

def consumption_actual(db,w,start,end):
    """Raw material movements at production time (including auto-production).
    Net sales equivalent is a different metric, already in book.report.
    """
    out={}
    for kind,raw,changes in db.execute("SELECT kind,result,changes FROM pm_book_events WHERE workspace=? AND day BETWEEN ? AND ? AND kind IN ('manufacture','work_start','sale','writeoff','reverse') ORDER BY day,seq",(w,start,end)):
        r=json.loads(raw);original=r.get("original_kind",kind)
        if original not in ("manufacture","work_start","sale","writeoff"):continue
        for ch in json.loads(changes):
            if ch["type"]!="raw":continue
            mid=ch["key"]
            used=(ch["before"] or {}).get("quantity",0)-(ch["after"] or {}).get("quantity",0)
            value=(ch["before"] or {}).get("value",0)-(ch["after"] or {}).get("value",0)
            if not used and not value:continue
            rec=out.setdefault(mid,{"material_id":mid,"production_quantity":0,"production_minor":0,"writeoff_quantity":0,"writeoff_minor":0})
            prefix="writeoff" if original=="writeoff" else "production"
            rec[prefix+"_quantity"]+=used;rec[prefix+"_minor"]+=value
    result=[]
    for mid,x in sorted(out.items()):
        m=db.execute("SELECT name,unit,pack FROM pm_materials WHERE workspace=? AND id=?",(w,mid)).fetchone()
        if not m:raise book.Conflict("Не найден материал складского движения.")
        result.append({"material_id":mid,"material":m[0],"unit":m[1],"pack":m[2],
                       "production_quantity":x["production_quantity"],"production_value_rub":book.money(x["production_minor"]),
                       "writeoff_quantity":x["writeoff_quantity"],"writeoff_value_rub":book.money(x["writeoff_minor"])})
    return sorted(result,key=lambda x:x["material"])

def ceil(v):return int(Decimal(v).to_integral_value(rounding=ROUND_CEILING))
def plan(db,w,*,source="ledger",history_from,history_to,target_from,growth=0,reserve=0,lead=7,include_wip=True,accept_no_data=False,accept_empty_ledger=False,metric="net"):
    past=months(history_from,history_to);target=month(target_from)
    if target<book.today().replace(day=1) or shift(target,len(past)-1).year>2100:raise ValueError("Планируйте текущие или будущие месяцы.")
    for v,lo,hi in ((growth,-100,1000),(reserve,0,100),(lead,0,365)):
        if type(v) is not int or not lo<=v<=hi:raise ValueError("Некорректный параметр прогноза.")
    if type(include_wip) is not bool or type(accept_no_data) is not bool or type(accept_empty_ledger) is not bool or metric not in ("net","delivered"):raise ValueError("Некорректные параметры прогноза.")
    if source=="ledger" and metric!="net":raise ValueError("Для учёта используются чистые продажи.")
    prod={p:{"productId":p,"product":n,"archived":bool(a),"recipe":book.current_recipe(db,w,p)} for p,n,a in db.execute("SELECT id,name,archived FROM pm_products WHERE workspace=?",(w,))}
    mats={m:{"material_id":m,"material":n,"unit":u,"pack":pack,"price":price,"archived":bool(a)} for m,n,u,pack,price,a in db.execute("SELECT id,name,unit,pack,price,archived FROM pm_materials WHERE workspace=?",(w,))}
    stock=book.Rows(db,w,"read");ready={p:sum(v["quantity"] for _,v in stock.lots(p))+(sum(v["quantity"] for _,v in stock.lots(p,"wip")) if include_wip else 0) for p in prod}
    raw={m:(stock.get("raw",m) or {}).get("quantity",0) for m in mats}
    unknown_stock={m for m in mats if stock.get("raw",m) is None}
    qp=quality.policy(db,w);return_defect,scrap=quality.rates(qp)
    demand={code(m):defaultdict(int) for m in past}
    components={code(m):defaultdict(lambda:{"delivered":0,"returned":0}) for m in past}
    coverage=[];unmapped={};problems=[];warnings=[]
    def required(k,pid):
        if metric=="delivered":return Decimal(demand[k][pid])
        v=components[k][pid]
        if "estimatedNet" in v:
            return Decimal(v["estimatedNet"])+Decimal(v.get("estimatedPhysicalReturns") or 0)*return_defect
        return quality.replacement_demand(v["delivered"],v["returned"],return_defect)
    if source=="ledger":
        start=code(past[0])+"-01";end=min(book.today(),shift(past[-1],1)-timedelta(days=1)).isoformat()
        seen=set()
        for raw_result, in db.execute("SELECT result FROM pm_book_events WHERE workspace=? AND day BETWEEN ? AND ? ORDER BY day,seq",(w,start,end)):
            r=json.loads(raw_result);pid=r.get("product_id");q=r.get("sales_quantity",0);m=r["day"][:7]
            if pid and q:
                demand[m][pid]+=q;seen.add(m)
                kind=r.get("original_kind",r.get("kind"))
                if kind=="sale":components[m][pid]["delivered"]+=q
                elif kind=="return":components[m][pid]["returned"]-=q
        for m in past:
            k=code(m);state="partial_month" if m==book.today().replace(day=1) else "ledger_records" if k in seen else "ledger_no_sales_records"
            coverage.append({"month":k,"state":state})
            if state=="ledger_no_sales_records" and not accept_empty_ledger:
                problems.append({"month":k,"reason":"Нет записей продаж. Подтвердите нулевой спрос или загрузите историю."})
        warnings.append("История учёта содержит только проведённые записи. Отсутствие записей не доказывает отсутствие продаж на площадках.")
        if accept_empty_ledger:warnings.append("По вашему выбору месяцы без учётных записей считаются нулевыми; это предположение.")
    elif not isinstance(source,str) or not source.startswith("ym:"):
        from . import podmasterye_market_analytics as analytics
        for m in past:
            k=code(m);end=min(book.today(),shift(m,1)-timedelta(days=1))
            data=analytics.planning_sales(db,w,from_=m.isoformat(),to=end.isoformat(),source=source)
            coverage.append({"month":k,"state":"partial_month" if m==book.today().replace(day=1) else "ready" if data["complete"] else "partial",
                             "sources":data["coverage"],"estimated":any(not r["mature"] for r in data["rows"])})
            if not data["complete"]:
                problems.append({"month":k,"reason":"Количественная история площадок не подтверждена полностью.","details":data["problems"]})
            for p in data["rows"]:
                pid=p["product_id"]
                if not pid:
                    unmapped[p["key"]]={"name":p["name"],"skus":p["skus"]};continue
                net=p["estimated_net"]
                returned=p["estimated_physical_returns"]
                if metric=="delivered":
                    if p["estimated_delivered"] is None:
                        problems.append({"month":k,"productId":pid,"reason":"Недостаточно данных для оценки доставок и физических возвратов."});continue
                    q=Decimal(str(p["estimated_delivered"]))
                else:
                    if not p["material_net_supported"]:
                        problems.append({"month":k,"productId":pid,"reason":"Календарный возврат не подтверждает физический возврат изделия. Для консервативного плана доступен показатель «Доставлено»."});continue
                    if net is None or return_defect and returned is None:
                        problems.append({"month":k,"productId":pid,"reason":"Недостаточно зрелой истории или разбивки физических возвратов для прогноза."});continue
                    q=Decimal(str(net))
                demand[k][pid]+=q
                components[k][pid]={"delivered":p["delivered"],"returned":p["physical_returns"],
                                    "estimatedNet":str(net),"estimatedPhysicalReturns":str(returned) if returned is not None else None}
            warnings.extend(data["warnings"])
        warnings.append("Маркетплейсы читаются из локальных количественных баз. Проведённые продажи мастерской не прибавляются к тем же внешним заказам; исторический импорт не создаёт складские движения.")
    else:
        h=history(db,w,source,history_from,history_to)
        coverage=h["months"]
        cid,v,shop,_=resolve(db,w,source)
        mappings={p["sku"]:p for p in h["products"]}
        for c in coverage:
            k=c["month"];state=c["state"]
            if state=="no_data" and accept_no_data:continue
            if state not in ("ready","partial_month"):
                problems.append({"month":k,"reason":"Нет подтверждённой истории: "+state})
                continue
            row=db.execute("SELECT data FROM pm_ym_realization WHERE cid=? AND version=? AND campaign=? AND month=? AND state='ready'",(cid,v,shop["campaignId"],k)).fetchone()
            d=json.loads(row[0])
            for p in d["products"]:
                q=p[metric];sku=p["sku"];mapped=mappings[sku]
                if not mapped["productId"]:
                    if q or p["delivered"] or p["returned"]:unmapped[sku]=mapped
                    continue
                pid=mapped["productId"]
                demand[k][pid]+=q
                for f in ("delivered","returned"):components[k][pid][f]+=p[f]
        warnings.append("План только для выбранного магазина по календарным отчётам реализации; не прибавляйте его к тем же продажам из общего учёта. Возвраты FBS вне данного отчёта требуют сверки.")
        if accept_no_data:warnings.append("По вашему выбору месяцы с ответом NO_DATA считаются нулевыми; это предположение.")
    for c in coverage:
        if c["state"]=="partial_month":problems.append({"month":c["month"],"reason":"Исторический месяц ещё не завершён."})
    for sku,p in unmapped.items():problems.append({"sku":sku,"product":p["name"],"reason":"Не сопоставлен артикул с изделием."})
    # Do not silently exclude archived or unconfigured products.
    for k,qs in demand.items():
        for pid,n in qs.items():
            if n<=0 and required(k,pid)<=0:continue
            p=prod.get(pid)
            if not p or p["archived"] or not p["recipe"]:
                problems.append({"month":k,"productId":pid,"quantity":str(n),"reason":"Изделие отсутствует, архивировано или без рецептуры."})
            elif any(r["material_id"] not in mats or mats[r["material_id"]]["archived"] for r in p["recipe"]):
                problems.append({"month":k,"productId":pid,"quantity":str(n),"reason":"Рецептура содержит недоступные материалы."})
    meta={"source":source,"historyFrom":history_from,"historyTo":history_to,"targetFrom":target_from,"targetTo":code(shift(target,len(past)-1)),
          "growthPercent":growth,"reservePercent":reserve,"leadDays":lead,"metric":metric,"includeWip":include_wip,"qualityPolicy":qp,
          "coverage":coverage,"problems":problems,"warnings":warnings,
          "historySales":[{"month":k,"productId":pid,"product":prod.get(pid,{}).get("product",pid),"quantity":int(n) if Decimal(n)==Decimal(n).to_integral_value() else format(n,"f"),
                           **components[k][pid],"replacementDemand":format(required(k,pid),"f")} for k,qs in demand.items() for pid,n in sorted(qs.items())]}
    warnings.append("Текущие остатки сырья и готовых изделий используются один раз и переносятся между месяцами. Промежуточные продажи, поставки в пути, резервы и склад маркетплейса не прогнозируются.")
    warnings.append("Используются действующие нормы и размеры упаковки, а не нормы исторического года. Потребность рассчитана до начала каждого месяца; закупки не создаются.")
    if include_wip:warnings.append("Незавершённые изделия считаются доступными к началу периода; это плановое допущение.")
    if metric=="net":
        warnings.append("Возвраты считаются пригодными для повторной продажи, кроме указанного процента брака. Дополнительное производство равно чистому спросу плюс ожидаемый брак возвратов; возвраты не добавляются второй раз в остаток. Избыточные возвраты за месяц не переносятся в прогнозный склад.")
        if qp["return_defect_percent"] is None:warnings.append("Процент брака возвратов не задан; все возвраты условно пригодны.")
    else:warnings.append("Режим «Доставлено» консервативно не уменьшает спрос на возвраты; коэффициент брака возвратов не применяется повторно.")
    if qp["production_scrap_percent"] is None:warnings.append("Производственные потери не заданы и не включены в прогноз.")
    else:warnings.append("Производственные потери — доля всего затрачиваемого сырья; полезная норма делится на (1 − доля потерь). Фактические складские движения не изменяются.")
    if problems:return {**meta,"complete":False,"months":[],"totals":[]}
    lines=[];overall={};missing=set()
    for idx,base in enumerate(past):
        k=code(base);t=shift(target,idx);need=defaultdict(int);product_lines=[]
        for pid,n in sorted(demand[k].items()):
            if n<=0 and required(k,pid)<=0:continue
            p=prod[pid]
            factor=Decimal(100+growth)/100
            forecast=ceil(max(Decimal(0),Decimal(n)*factor))
            replacement=ceil(max(Decimal(0),required(k,pid)*factor))
            take=min(ready[pid],replacement);ready[pid]-=take
            produce=replacement-take
            contributions=[]
            for r in p["recipe"]:
                qty=produce*r["per"];need[r["material_id"]]+=qty
                contributions.append({"material_id":r["material_id"],"material":r["material"],"unit":r["unit"],"per":r["per"],"quantity":qty})
            product_lines.append({"productId":pid,"product":p["product"],"historicalSales":int(n) if Decimal(n)==Decimal(n).to_integral_value() else format(n,"f"),"forecastSales":forecast,
                                  "replacementDemand":replacement,"returnDefectReplacements":max(0,replacement-forecast),"fromReady":take,"produce":produce,"recipe":contributions})
        materials=[]
        for mid,needed in sorted(need.items()):
            if not needed:continue
            nominal=needed
            needed=ceil(quality.material_input(nominal,scrap))
            loss=needed-nominal
            m=mats[mid];available_raw=raw[mid];buffer=ceil(Decimal(needed)*reserve/100)
            short=max(0,needed+buffer-available_raw);packs=ceil(Decimal(short)/m["pack"])
            bought=packs*m["pack"];raw[mid]=available_raw+bought-needed
            price=m["price"];cost=Decimal(price)*packs if price is not None else None
            if mid in unknown_stock:missing.add(mid)
            deadline=t-timedelta(days=lead)
            line={"material_id":mid,"material":m["material"],"unit":m["unit"],"pack":m["pack"],"need":needed,"reserve":buffer,
                "nominalNeed":nominal,"productionScrap":loss,
                "opening":available_raw,"stockKnown":mid not in unknown_stock,"shortfall":short,"buyPacks":packs,"buyQuantity":bought,"closing":raw[mid],
                "plannedPackPrice":price,"costRub":format(cost,".2f") if cost is not None else None,
                "orderBy":deadline.isoformat() if packs else None,"overdue":bool(packs and deadline<book.today())}
            materials.append(line)
            v=overall.setdefault(mid,{"material_id":mid,"material":m["material"],"unit":m["unit"],"pack":m["pack"],"need":0,"nominalNeed":0,"productionScrap":0,"buyPacks":0,"buyQuantity":0,"costRub":"0.00","stockKnown":mid not in unknown_stock})
            for f in ("need","nominalNeed","productionScrap","buyPacks","buyQuantity"):v[f]+=line[f]
            v["closing"]=raw[mid]
            v["costRub"]=format(Decimal(v["costRub"])+cost,".2f") if cost is not None and v["costRub"] is not None else None
        lines.append({"historyMonth":k,"targetMonth":code(t),"products":product_lines,"materials":materials,
                      "summary":{name:sum(p[name] for p in product_lines) for name in ("forecastSales","produce","returnDefectReplacements","replacementDemand","fromReady")}})
    if missing:warnings.append("Для части материалов фактический остаток не введён: сценарий условно использует ноль; уточните остаток до закупки.")
    return {**meta,"complete":True,"stockComplete":not missing,"months":lines,"totals":sorted(overall.values(),key=lambda r:r["material"])}

def read(store,token,requested,action,args):
    with store._lock:
        db=store._db;_,account=_principal(db,token);w=workshops.resolve(db,account,requested)
        if action=="sources":return {"sources":available(db,w),"products":[{"id":p,"name":n} for p,n in db.execute("SELECT id,name FROM pm_products WHERE workspace=? AND archived=0 ORDER BY normalized",(w,))]}
        if action=="history":return history(db,w,**args)
        return plan(db,w,**args)
def change_map(store,token,requested,args):
    with store._write() as db:
        _,account=_principal(db,token);w=workshops.resolve(db,account,requested)
        return map_product(db,w,**args)
