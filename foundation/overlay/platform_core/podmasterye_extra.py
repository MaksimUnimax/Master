"""Supplemental built-in business operations. No additional login roles."""
import json
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from datetime import date,timedelta
from .podmasterye_domain import Conflict,encode,clean_name

TASK_CATS=("Заказ","Закупка","Звонок","Доставка","Изготовление","Маркетплейс","Личное","Прочее")
FIELDS={
 "material_archive":("Архив материала",[("material","material","Материал",True,None),("archived","bool","В архиве",True,True)]),
 "product_archive":("Архив изделия",[("product","product","Изделие",True,None),("archived","bool","В архиве",True,True)]),
 "bulk_archive":("Массовый архив каталога",[
   ("entity_kind","choice:product,material","Тип объектов",True,"product"),("entity_ids","identifiers","Идентификаторы объектов (через запятую)",True,None),
   ("archived","bool","В архиве",True,True)]),
 "recipe_line":("Строка рецептуры",[("product","product","Изделие",True,None),("material","material","Материал",True,None),("usage","int0","Расход (0 — удалить строку)",True,None)]),
 "task":("Задача",[("task_id","task","Существующая задача (пусто — новая)",False,""),("name","text","Название",True,None),
   ("description","text","Описание",False,""),("due","future_date","Срок",False,None),("remind_days","int0","Напомнить за дней до срока",True,0),("priority","choice:Низкая,Обычная,Высокая","Важность",True,"Обычная"),
   ("task_category","choice:"+",".join(TASK_CATS),"Категория",True,"Прочее")]),
 "task_state":("Статус задачи",[("task_id","task","Задача",True,None),("task_status","choice:active,done,archived","Статус",True,"done")]),
 "worker":("Работник (учёт труда)",[("worker_id","worker","Существующий работник",False,""),("name","text","Имя",True,None),("position","text","Должность",False,""),("archived","bool","В архиве",False,False)]),
 "cost_policy":("Накладные в плановой себестоимости",[
   ("monthly_overhead","money","Накладные расходы в месяц, ₽",True,"0"),
   ("productive_hours","int0","План производительных часов в месяц",True,0),
   ("include_depreciation","bool","Распределять амортизацию оборудования",True,False)]),
 "channel_rates":("Плановый тариф канала",[("channel","text","Канал",True,None),("commission","percent","Комиссия и процентные удержания, %",True,"0"),("fixed_fee","money","Фиксированные затраты на единицу, ₽",True,"0")]),
}
PAGES={"material_archive":"materials","product_archive":"products","bulk_archive":"products","recipe_line":"products","task":"tasks","task_state":"tasks","worker":"workers","channel_rates":"unit","cost_policy":"unit"}
SCHEMA=(
"""CREATE TABLE IF NOT EXISTS pm_tasks(
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 name TEXT NOT NULL, description TEXT NOT NULL, due TEXT, priority TEXT NOT NULL, category TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','done','archived')), updated TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS pm_workers(
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 name TEXT NOT NULL, position TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)))""",
"""CREATE TABLE IF NOT EXISTS pm_channel_rates(
 workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 channel TEXT NOT NULL, normalized TEXT NOT NULL, commission_bps INTEGER NOT NULL CHECK(commission_bps>=0 AND commission_bps<10000),
 fixed_fee INTEGER NOT NULL CHECK(fixed_fee>=0), PRIMARY KEY(workspace,normalized))""",
"""CREATE TABLE IF NOT EXISTS pm_cost_policies(
 workspace TEXT PRIMARY KEY REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 monthly_overhead INTEGER NOT NULL CHECK(monthly_overhead>=0),productive_hours INTEGER NOT NULL CHECK(productive_hours>=0),
 include_depreciation INTEGER NOT NULL CHECK(include_depreciation IN (0,1)))""",
"""CREATE TABLE IF NOT EXISTS pm_recipe_versions(
 seq INTEGER PRIMARY KEY, workspace TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
 product TEXT NOT NULL REFERENCES pm_products(id) ON DELETE CASCADE, snapshot TEXT NOT NULL, day TEXT NOT NULL)""",
)
def init(db):
    for stmt in SCHEMA:db.execute(stmt)
    if "remind_days" not in {r[1] for r in db.execute("PRAGMA table_info(pm_tasks)")}:
        db.execute("ALTER TABLE pm_tasks ADD COLUMN remind_days INTEGER NOT NULL DEFAULT 0")
    for t in ("pm_materials","pm_products"):
        cols={r[1] for r in db.execute("PRAGMA table_info("+t+")")}
        if "archived" not in cols:db.execute("ALTER TABLE "+t+" ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if "note" not in cols:db.execute("ALTER TABLE "+t+" ADD COLUMN note TEXT NOT NULL DEFAULT ''")
def freeze_recipe(db,w,pid):
    from . import podmasterye_book as book
    r=[dict(material_id=m,name=n,usage=q,unit=u,pack=pack,pack_price=price) for m,n,q,u,pack,price in db.execute(
      """SELECT m.id,m.name,r.qty,m.unit,m.pack,m.price FROM pm_recipe r JOIN pm_materials m ON m.id=r.material
      WHERE r.product=? AND m.workspace=? ORDER BY m.id""",(pid,w))]
    raw=encode(r);old=db.execute("SELECT snapshot FROM pm_recipe_versions WHERE workspace=? AND product=? ORDER BY seq DESC LIMIT 1",(w,pid)).fetchone()
    if not old or old[0]!=raw:db.execute("INSERT INTO pm_recipe_versions(workspace,product,snapshot,day) VALUES(?,?,?,?)",(w,pid,raw,book.today().isoformat()))
def find(db,w,table,ident):
    if table not in ("pm_tasks","pm_workers"):raise ValueError("Неизвестный объект.")
    row=db.execute("SELECT id FROM "+table+" WHERE workspace=? AND id=?",(w,ident)).fetchone()
    if not row:raise ValueError("Объект не найден.")
    return row[0]
def metadata_write(db,w,rid,op,a):
    from . import podmasterye_book as b
    old=db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?",(w,"book:"+rid)).fetchone()
    raw=encode({"operation":op,"arguments":a})
    if old:
        if old[0]!=raw:raise Conflict("Идентификатор уже использован.")
        return json.loads(old[1])
    if op=="bulk_archive":
        import hashlib
        typ=a["entity_kind"];ids=a["entity_ids"].split(",")
        for ident in ids:
            metadata_write(db,w,"bulk-"+hashlib.sha256(encode([rid,ident]).encode()).hexdigest(),typ+"_archive",{typ:ident,"archived":a["archived"]})
        ident=w;summary="Обработано объектов: "+str(len(ids))
    elif op in ("material_archive","product_archive"):
        typ="material" if op=="material_archive" else "product";tab="pm_materials" if typ=="material" else "pm_products"
        ident,name=b.entity(db,w,typ,a[typ],include_archived=True)
        if a["archived"]:
            if typ=="material":
                if db.execute("SELECT 1 FROM pm_recipe r JOIN pm_products p ON p.id=r.product WHERE r.material=? AND p.archived=0",(ident,)).fetchone():
                    raise Conflict("Материал используется в активной рецептуре. Сначала исправьте состав изделия.")
                v=db.execute("SELECT value FROM pm_book_rows WHERE workspace=? AND type='raw' AND key=?",(w,ident)).fetchone()
                if v and json.loads(v[0])["quantity"]:raise Conflict("Сначала оформите остаток материала.")
            else:
                rows=b.Rows(db,w,"archive")
                if rows.lots(ident) or rows.lots(ident,"wip"):raise Conflict("У изделия есть готовый остаток или незавершёнка.")
                if any(t=="sale" and s["product_id"]==ident and (s["quantity"]-s["returned"])*s["price"]>s["paid"] for (t,k),s in rows.rows.items()):
                    raise Conflict("У изделия есть неоплаченные продажи.")
        if typ=="product" and not a["archived"] and db.execute("SELECT 1 FROM pm_recipe r JOIN pm_materials m ON m.id=r.material WHERE r.product=? AND m.archived=1",(ident,)).fetchone():
            raise Conflict("Сначала восстановите материалы рецептуры.")
        db.execute("UPDATE "+tab+" SET archived=? WHERE workspace=? AND id=?",(int(a["archived"]),w,ident))
        summary=("В архиве: " if a["archived"] else "Восстановлено: ")+name
    elif op=="recipe_line":
        pid,name=b.entity(db,w,"product",a["product"])
        mid,mname=b.entity(db,w,"material",a["material"],include_archived=a["usage"]==0)
        freeze_recipe(db,w,pid)
        if a["usage"]==0:
            if not db.execute("DELETE FROM pm_recipe WHERE product=? AND material=?",(pid,mid)).rowcount:raise ValueError("Материал не входит в состав.")
        else:db.execute("INSERT INTO pm_recipe VALUES(?,?,?) ON CONFLICT(product,material) DO UPDATE SET qty=excluded.qty",(pid,mid,a["usage"]))
        freeze_recipe(db,w,pid);ident=pid;summary="Рецептура обновлена: "+name+" / "+mname
    elif op=="task":
        name=a["name"];ident=find(db,w,"pm_tasks",a["task_id"]) if a["task_id"] else uuid4().hex
        if a["remind_days"]>365:raise ValueError("Напоминание не более чем за 365 дней.")
        if a["task_id"]:
            db.execute("UPDATE pm_tasks SET name=?,description=?,due=?,priority=?,category=?,updated=?,remind_days=? WHERE id=? AND workspace=?",
              (name,a["description"],a["due"] or None,a["priority"],a["task_category"],b.today().isoformat(),a["remind_days"],ident,w))
        else:db.execute("INSERT INTO pm_tasks(id,workspace,name,description,due,priority,category,updated,remind_days) VALUES(?,?,?,?,?,?,?,?,?)",
              (ident,w,name,a["description"],a["due"] or None,a["priority"],a["task_category"],b.today().isoformat(),a["remind_days"]))
        summary="Задача сохранена: "+name
    elif op=="task_state":
        ident=find(db,w,"pm_tasks",a["task_id"])
        db.execute("UPDATE pm_tasks SET status=?,updated=? WHERE id=? AND workspace=?",(a["task_status"],b.today().isoformat(),ident,w))
        summary="Статус задачи изменён."
    elif op=="worker":
        ident=find(db,w,"pm_workers",a["worker_id"]) if a["worker_id"] else uuid4().hex
        if a["worker_id"]:db.execute("UPDATE pm_workers SET name=?,position=?,archived=? WHERE id=? AND workspace=?",(a["name"],a["position"],int(a["archived"]),ident,w))
        else:db.execute("INSERT INTO pm_workers VALUES(?,?,?,?,?)",(ident,w,a["name"],a["position"],int(a["archived"])))
        summary="Запись о работнике сохранена: "+a["name"]
    elif op=="cost_policy":
        monthly=b.minor(a["monthly_overhead"]);hours=a["productive_hours"];inc=a["include_depreciation"]
        if hours>744 or ((monthly or inc) and not hours):raise ValueError("Укажите от 1 до 744 производительных часов.")
        ident=w
        db.execute("INSERT INTO pm_cost_policies VALUES(?,?,?,?) ON CONFLICT(workspace) DO UPDATE SET monthly_overhead=excluded.monthly_overhead,productive_hours=excluded.productive_hours,include_depreciation=excluded.include_depreciation",(w,monthly,hours,int(inc)))
        summary="Политика плановых накладных сохранена."
    elif op=="channel_rates":
        name=clean_name(a["channel"]);ident=name.casefold()
        db.execute("INSERT INTO pm_channel_rates VALUES(?,?,?,?,?) ON CONFLICT(workspace,normalized) DO UPDATE SET channel=excluded.channel,commission_bps=excluded.commission_bps,fixed_fee=excluded.fixed_fee",(w,name,ident,b.minor(a["commission"]),b.minor(a["fixed_fee"])))
        summary="Плановый тариф сохранён: "+name
    else:raise ValueError("Неизвестная операция.")
    result={"id":ident,"kind":op,"summary":summary,"arguments":a}
    db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(w,"book:"+rid,raw,encode(result)))
    return result
def settings_revision(db,w):
    rows=[]
    for table,cols,where in (
        ("pm_tasks","id,name,description,due,priority,category,status,remind_days","workspace"),
        ("pm_cost_policies","workspace,monthly_overhead,productive_hours,include_depreciation","workspace"),
        ("pm_workers","id,name,position,archived","workspace"),
        ("pm_channel_rates","channel,normalized,commission_bps,fixed_fee","workspace"),
        ("pm_workshops","id,name,description,color,hourly_rate,archived","id"),
    ):
        rows.append([list(x) for x in db.execute("SELECT "+cols+" FROM "+table+" WHERE "+where+"=? ORDER BY 1",(w,))])
    return rows
def additional_data(db,w,products,materials,events,target_profit="200"):
    from . import podmasterye_book as b
    from . import podmasterye_workshops as workshops,podmasterye_assets as asset_module
    goal=b.minor(target_profit)
    meta=workshops.metadata(db,w)
    policy_row=db.execute("SELECT monthly_overhead,productive_hours,include_depreciation FROM pm_cost_policies WHERE workspace=?",(w,)).fetchone() or (0,0,0)
    monthly,hours,inc=policy_row
    asset_rows,_=asset_module.report(db,w,b.today().isoformat(),b.today().isoformat())
    norm_depr=sum((Decimal(a["monthly_norm_rub"]) for a in asset_rows),Decimal(0)) if inc else Decimal(0)
    monthly_total=Decimal(monthly)/100+norm_depr
    hourly_overhead=monthly_total/hours if hours else Decimal(0)
    policy=dict(monthly_overhead=b.money(monthly),productive_hours=hours,include_depreciation=bool(inc),
                monthly_depreciation_rub=format(norm_depr,".2f"),hourly_overhead_rub=format(hourly_overhead.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f"))
    rates=[dict(channel=n,commission_percent=b.money(bp),fixed_fee_rub=b.money(fixed)) for n,bp,fixed in db.execute("SELECT channel,commission_bps,fixed_fee FROM pm_channel_rates WHERE workspace=? ORDER BY normalized",(w,))]
    rate_by={r["channel"].casefold():r for r in rates}
    recent=b.event_rows(db,w,(b.today()-timedelta(days=89)).isoformat(),b.today().isoformat())
    agg={}
    for row,fin in recent:
        if not row.get("product_id") or not row.get("channel"):continue
        key=(row["product_id"],row["channel"])
        g=agg.setdefault(key,{"qty":0,"revenue":0,"cogs":0,"receipts":0,"fees":0})
        g["qty"]+=row.get("sales_quantity",0)
        for k in ("revenue","cogs","receipts"):g[k]+=fin.get(k,0)
        if row.get("sale_id"):g["fees"]+=fin.get("expenses",0)
    def decimal2(x):return format(x.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f")
    results=[];summary_categories={}
    for item in materials+products:
        key=item.get("category") or "Без категории"
        summary_categories[key]=summary_categories.get(key,0)+int((Decimal(item["value_rub"])+Decimal(item.get("wip_value_rub","0")))*100)
    for p in products:
        base=Decimal(p["estimated_material_cost_rub"]) if p["estimated_material_cost_rub"] is not None else None
        labor=Decimal(p["minutes"])*Decimal(meta["hourly_rate"])/60 if p["minutes"] is not None else None
        overhead=Decimal(p["minutes"])*hourly_overhead/60 if p["minutes"] is not None else None
        total=base+labor+overhead if base is not None and labor is not None and overhead is not None else None
        p["planned_overhead_rub"]=decimal2(overhead) if overhead is not None else None
        p["planned_labor_rub"]=decimal2(labor) if labor is not None else None
        p["planned_full_cost_rub"]=decimal2(total) if total is not None else None
        p["material_profit_rub"]=decimal2(Decimal(p["sale_price"])-base) if p["sale_price"] is not None and base is not None else None
        p["planned_full_profit_rub"]=decimal2(Decimal(p["sale_price"])-total) if p["sale_price"] is not None and total is not None else None
        p["material_margin_percent"]=decimal2((Decimal(p["sale_price"])-base)*100/Decimal(p["sale_price"])) if p["sale_price"] and Decimal(p["sale_price"])>0 and base is not None else None
        channels=sorted({ch for pid,ch in agg if pid==p["id"]}|{r["channel"] for r in rates}|{"Прямые продажи"})
        if p.get("archived"):continue
        for ch in channels:
            g=agg.get((p["id"],ch),{"qty":0,"revenue":0,"cogs":0,"receipts":0,"fees":0})
            n=g["qty"];price=Decimal(g["revenue"])/100/n if n>0 else Decimal(p["sale_price"]) if p["sale_price"] else None
            actual_avg=Decimal(g["cogs"])/100/n if n>0 else None
            rate=rate_by.get(ch.casefold())
            if rate is None and ch.casefold()=="прямые продажи":rate={"commission_percent":"0","fixed_fee_rub":"0"}
            pct=Decimal(rate["commission_percent"])/100 if rate else None;fixed=Decimal(rate["fixed_fee_rub"]) if rate else None
            # No invented channel fees. Material-only recommendation is explicitly distinguished.
            planned_cost=total if total is not None else base
            recommendation=(planned_cost+fixed+Decimal(goal)/100)/(1-pct) if planned_cost is not None and rate else None
            proceeds=price*(1-pct)-fixed if price is not None and rate else None
            results.append({"product_id":p["id"],"product":p["name"],"channel":ch,"quantity_90d":n,
                "average_price_rub":decimal2(price) if price is not None else None,"actual_cogs_per_unit_rub":decimal2(actual_avg) if actual_avg is not None else None,
                "planned_material_cost_rub":p["estimated_material_cost_rub"],"planned_full_cost_rub":p["planned_full_cost_rub"],
                "actual_fees_per_unit_rub":decimal2(Decimal(g["fees"])/100/n) if n>0 else None,
                "actual_profit_per_unit_rub":decimal2(Decimal(g["revenue"]-g["cogs"]-g["fees"])/100/n) if n>0 else None,
                "actual_receipts_rub":b.money(g["receipts"]-g["fees"]),
                "planned_overhead_rub":p["planned_overhead_rub"],
                "planned_proceeds_rub":decimal2(proceeds) if proceeds is not None else None,
                "planned_profit_rub":decimal2(proceeds-planned_cost) if proceeds is not None and planned_cost is not None else None,
                "cost_basis":"full" if total is not None else "material","rate_known":rate is not None,
                "recommended_price_rub":format(recommendation.quantize(Decimal(".01"),rounding=ROUND_CEILING),"f") if recommendation is not None else None})
    tasks=[dict(id=r[0],name=r[1],description=r[2],due=r[3],priority=r[4],category=r[5],status=r[6],updated=r[7],remind_days=r[8],overdue=bool(r[3] and r[3]<b.today().isoformat() and r[6]=="active"),reminder_due=bool(r[3] and r[6]=="active" and date.fromisoformat(r[3])<=b.today()+timedelta(days=r[8]))) for r in db.execute(
      "SELECT id,name,description,due,priority,category,status,updated,remind_days FROM pm_tasks WHERE workspace=? ORDER BY status,due IS NULL,due,name",(w,))]
    workers=[dict(id=r[0],name=r[1],position=r[2],archived=bool(r[3])) for r in db.execute("SELECT id,name,position,archived FROM pm_workers WHERE workspace=? ORDER BY name",(w,))]
    payments={}
    for row,f in events:
        wid=row.get("worker_id")
        if wid:payments[wid]=payments.get(wid,0)+f.get("expenses",0)
    for r in workers:r["payments_rub"]=b.money(payments.get(r["id"],0))
    suppliers=[r[0] for r in db.execute("SELECT DISTINCT json_extract(result,'$.supplier') FROM pm_book_events WHERE workspace=? AND kind='purchase' AND json_extract(result,'$.supplier')<>'' ORDER BY 1",(w,))]
    versions=[dict(id=seq,product_id=pid,day=day,recipe=json.loads(snapshot)) for seq,pid,day,snapshot in db.execute(
        "SELECT seq,product,day,snapshot FROM pm_recipe_versions WHERE workspace=? ORDER BY seq DESC LIMIT 1000",(w,))]
    return {"workshop":meta,"tasks":tasks,"workers":workers,"suppliers":suppliers,"channel_rates":rates,"unit_economics":results,
            "cost_policy":policy,"recipe_versions":versions,"reminders":[t for t in tasks if t["reminder_due"]],
            "target_profit":b.money(goal),"unit_period":{"from":(b.today()-timedelta(days=89)).isoformat(),"to":b.today().isoformat()},
            "stock_categories":[{"name":k,"value_rub":b.money(v)} for k,v in sorted(summary_categories.items())]}
