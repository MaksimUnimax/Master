"""Local quantitative marketplace projections for both user interfaces.

There is no network, model, scheduler or inventory mutation in this module.
The durable collector owns source qualification and ``market_quantity`` owns
the physical stores. Calendar realization is never fabricated into an order
cohort. Rates retain their integer numerators and original denominators.

The Ozon quantity reducer below is adapted from the existing Harness runtime
``parameter_support/parameter_producers.py:physical_outcomes``. Only the
quantity union is reused; financial templates and provider IO are excluded.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from copy import deepcopy
import re
from zoneinfo import ZoneInfo

MATURITY_DAYS = 30
HISTORY_DAYS = 365
# A documented precision criterion instead of an invented default percentage.
# A complete source window and a 95% Wilson half-width <= 10 percentage points
# are both necessary. It is evaluated independently at SKU/category/store.
WILSON_Z = Decimal("1.959963984540054")
MAX_RATE_HALF_WIDTH = Decimal("0.10")
POLICY_VERSION = "mature-quantity-v1"
PROVIDERS = ("ozon", "wb", "yandex_market")
SOURCE_ZONE=ZoneInfo("Europe/Moscow")
QUANTITIES = ("ordered", "delivered", "cancelled", "nonbuyout", "physical_returns", "calendar_returns", "losses", "net")
ESTIMATES = ("estimated_net", "estimated_losses", "estimated_physical_returns", "estimated_delivered")
ROLE = {"OZ-03":"orders", "OZ-04":"returns", "OZ-05":"boundary", "OZ-06":"orders",
        "WB-03":"orders", "WB-04":"realization", "YM-03":"orders", "YM-04":"returns", "YM-05":"realization"}


class QuantityError(ValueError):
    """Safe source diagnostic; contains no provider payload or credentials."""


def _day(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:raise QuantityError("Не подтверждён часовой пояс количественного события.")
        return value.astimezone(SOURCE_ZONE).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T[^\s]+)?", value):
        raise QuantityError("Некорректная дата количественного источника.")
    if "T" in value:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        if stamp.tzinfo is None:raise QuantityError("Не подтверждён часовой пояс количественного события.")
        return stamp.astimezone(SOURCE_ZONE).date()
    return date.fromisoformat(value)


def _integer(value):
    if type(value) is int and 0 <= value <= 10**15:
        return value
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9]\d{0,14})", value):
        return int(value)
    raise QuantityError("Источник не подтвердил целое количество единиц.")


def _qty(row, name):
    value = row.get(name)
    return None if value is None else _integer(value)


def _text(value):
    if not isinstance(value, str) or not value or len(value)>1024 or any(ord(c)<32 for c in value):
        raise QuantityError("Не подтверждён идентификатор количественного факта.")
    return value


def _decimal(value):
    if value is None:
        return None
    n=Decimal(value)
    return int(n) if n==n.to_integral_value() else format(n,"f")


def _scope(row):
    provider=row.get("provider")
    if provider not in PROVIDERS:
        raise QuantityError("Неизвестная площадка.")
    return provider,_text(str(row.get("store_id") or ""))


def _instant(value):
    if isinstance(value,datetime):
        if value.tzinfo is None:raise QuantityError("Не подтверждён часовой пояс наблюдения.")
        return value.astimezone(SOURCE_ZONE)
    if type(value) in (int,float):return datetime.fromtimestamp(value,SOURCE_ZONE)
    if isinstance(value,str) and "T" in value:return _instant(datetime.fromisoformat(value.replace("Z","+00:00")))
    return datetime.combine(_day(value),time.min,SOURCE_ZONE)


def _report_clock(day):
    current=datetime.now(SOURCE_ZONE)
    return current if current.date()==_day(day) else _instant(day)


def _freshness(proofs,now,unresolved=()):
    """Only recently changing windows need daily observation, not closed history."""
    now=_instant(now);boundary=now.date()-timedelta(days=60);sources=[];observations=[]
    requirements={};current=defaultdict(list)
    for p in proofs:
        lo=max(_day(p["from"]),_day(p["required_from"]));hi=min(_day(p["to"]),_day(p["required_to"]))
        mutable=hi>boundary or any(lo<=d<=hi for d in unresolved)
        observed=None
        try:
            if p.get("observed_at") is not None:observed=_instant(p["observed_at"])
        except (ValueError,TypeError,OverflowError,OSError):pass
        if observed is not None:observations.append(observed)
        age=max(0,(now-observed).total_seconds()) if observed is not None else None
        status="closed" if not mutable else "unknown" if age is None else "stale" if age>86400 else "fresh"
        requirements[p["role"]]=(_day(p["required_from"]),_day(p["required_to"]))
        if status in ("closed","fresh"):current[p["role"]].append((lo,hi))
        elif lo<=boundary:
            # A yearly historical proof can remain authoritative for its closed
            # part while a fresh daily window covers its changing suffix. An
            # older overlapping observation must not poison the newer proof.
            parts=[(lo,min(hi,boundary))]
            for day in sorted(set(unresolved)):
                next_=[]
                for a,b in parts:
                    if not a<=day<=b:next_.append((a,b));continue
                    if a<day:next_.append((a,day-timedelta(days=1)))
                    if day<b:next_.append((day+timedelta(days=1),b))
                parts=next_
            current[p["role"]].extend(parts)
        sources.append({"source_id":p.get("source_id"),"role":p["role"],"from":lo.isoformat(),"to":hi.isoformat(),
                        "observed_at":observed.isoformat() if observed else None,"age_seconds":age,"mutable":mutable,"status":status})
    incomplete=[role for role,(lo,hi) in requirements.items() if not _interval_complete(current[role],lo,hi)]
    stale=bool(incomplete) and any(p["status"]=="stale" and p["role"] in incomplete for p in sources)
    unknown=bool(incomplete) and any(p["status"]=="unknown" and p["role"] in incomplete for p in sources)
    return {"status":"stale" if stale else "unknown" if unknown else "fresh" if any(p["mutable"] for p in sources) else "closed",
            "stale":stale,"fresh_enough":not incomplete,"incomplete_roles":incomplete,"max_age_seconds":86400,
            "observed_at":max(observations).isoformat() if observations else None,"sources":sources}


def _identity(row):
    order=(row.get("posting_number") or row.get("posting") or row.get("order_id")) if row.get("provider")=="ozon" else row.get("order_id")
    return (*_scope(row),str(row.get("scheme") or ""),
            str(order or ""),
            str(row.get("line_id") or row.get("sku") or ""))


def physical_outcome_union(orders, returns, *, boundaries=()):
    """The existing Octoport physical union, scoped to ONE verified store.

    Inputs preserve its schema: orders have scheme/posting/sku/day/units/state;
    returns have scheme/posting/sku/exemplars/type. ``returned_units`` is the
    legacy name for unioned loss exemplars (including Cancellation), NOT proof
    of physically received customer returns. Never use it as a defect base.
    """
    index={};duplicates=0;returned=defaultdict(set);duplicate_returns=0
    allowed={tuple(v) for v in boundaries}
    for r in orders:
        key=(_text(r["scheme"]),_text(r["posting"]),str(_integer(r["sku"])))
        if r["scheme"] not in ("FBO","FBS") or r["state"] not in ("delivered","cancelled","pending") or _integer(r["units"])<=0:
            raise QuantityError("Не подтверждены схема, статус или количество отправления.")
        _day(r["day"])
        if key in index:
            if index[key]!=r:raise QuantityError("Противоречивые строки одного отправления.")
            duplicates+=1
        else:index[key]=deepcopy(r)
    for r in returns:
        if r["type"] not in ("Cancellation","ClientReturn","FullReturn","PartialReturn"):
            raise QuantityError("Неизвестный тип исхода Ozon.")
        key=(_text(r["scheme"]),_text(r["posting"]),str(_integer(r["sku"])))
        if key not in index and key not in allowed:
            raise QuantityError("Возврат не связан с подтверждённой исходной когортой.")
        ids={str(_integer(v)) for v in r["exemplars"]}
        if not ids or len(ids)!=len(r["exemplars"]) or "0" in ids:
            raise QuantityError("Не подтверждена полнота экземпляров возврата.")
        duplicate_returns+=len(returned[key]&ids);returned[key]|=ids
        if key in index and len(returned[key])>index[key]["units"]:
            raise QuantityError("Потери превышают исходное количество заказа.")
    failed=pending=physical=0
    for key,r in index.items():
        n=r["units"];lost=len(returned[key])
        failed+=n if r["state"]=="cancelled" else lost
        physical+=lost
        if r["state"]=="pending":pending+=n-lost
    return {"ordered_units":sum(r["units"] for r in index.values()),"failed_units":failed,
            "pending_units":pending,"returned_units":physical,"duplicate_order_rows":duplicates,
            "duplicate_return_exemplars":duplicate_returns}


def _row_values(row):
    values={k:_qty(row,n) for k,n in (("ordered","ordered_qty"),("delivered","delivered_qty"),
        ("cancelled","cancelled_qty"),("nonbuyout","nonbuyout_qty"),
        ("physical_returns","physical_return_qty"),("calendar_returns","calendar_return_qty"),("losses","lost_qty"))}
    if row.get("physical_returns_known") is not True:
        values["physical_returns"]=None
    n=values["ordered"]
    if n is not None:
        if row.get("original_order_known") is not True:
            values["ordered"]=n=None
        elif any(v is not None and v>n for v in values.values()):
            raise QuantityError("Количество исхода превышает исходное количество заказа.")
    d,r=values["delivered"],values["physical_returns"]
    calendar=row.get("quantity_basis") in ("calendar_event","calendar_interval")
    if calendar and values["calendar_returns"] is None:values["calendar_returns"]=r
    if row.get("quantity_basis")=="order_cohort" and d is not None and r is not None and r>d:
        raise QuantityError("Физические возвраты превышают доставки в исходной когорте.")
    if values["losses"] is None and n is not None:
        parts=[values[k] for k in ("cancelled","nonbuyout","physical_returns")]
        if values["cancelled"]==n:
            values["losses"]=n
        elif all(v is not None for v in parts) and (row.get("outcomes_disjoint") is True or sum(bool(v) for v in parts)<=1):
            values["losses"]=sum(parts)
        if values["losses"] is not None and values["losses"]>n:
            raise QuantityError("Потери превышают исходное количество заказа.")
    if row.get("quantity_basis") in ("order_cohort","funnel_interval") and r is not None and values["losses"] is not None and r>values["losses"]:
        raise QuantityError("Физические возвраты превышают объединение потерянных единиц.")
    net_returns=values["calendar_returns"] if calendar else r
    values["net"]=d-net_returns if d is not None and net_returns is not None else None
    if values["net"] is None and row.get("terminal") is True and n is not None and values["losses"] is not None:
        values["net"]=n-values["losses"]
    return values


def _equivalent_fact(left,right):
    """Report and incremental APIs can observe one fact under different IDs.

    Only provenance/optional presentation fields are ignored. Conflicting
    known quantities or lifecycle states cannot become an arbitrary winner.
    """
    if _identity(left)!=_identity(right):return False
    for key in ("ordered_qty","delivered_qty","cancelled_qty","nonbuyout_qty","physical_return_qty","calendar_return_qty","lost_qty",
                "terminal","status","interval_from","interval_to","event_date"):
        if left.get(key) is not None and right.get(key) is not None and left[key]!=right[key]:return False
    if left.get("ordered_at") and right.get("ordered_at") and _day(left["ordered_at"])!=_day(right["ordered_at"]):return False
    return True


def _rows(snapshot,as_of):
    """Deduplicate snapshots, join late outcomes and preserve their time axis."""
    seen={};problems=[]
    for raw in snapshot.get("rows",[]):
        if raw.get("quantity_basis") not in ("order_cohort","calendar_event","calendar_interval","funnel_interval","return_event"):
            continue
        try:
            key=(*_scope(raw),raw["quantity_basis"],_text(str(raw.get("natural_key") or "")))
            prior=seen.get(key)
            if prior is not None and prior!=raw:
                if prior.get("original_order_known") is True and raw.get("original_order_known") is True and prior.get("ordered_qty")!=raw.get("ordered_qty"):
                    raise QuantityError("Изменился исходный знаменатель заказа.")
                old=str(prior.get("observed_at") or "");new=str(raw.get("observed_at") or "")
                if new==old:
                    if not _equivalent_fact(prior,raw):raise QuantityError("Противоречивые снимки одного факта.")
                    raw={**prior,**{k:v for k,v in raw.items() if v is not None}}
                    for known in ("physical_returns_known","original_order_known"):
                        raw[known]=prior.get(known) is True or raw.get(known) is True
                if new<old:continue
            seen[key]=deepcopy(raw)
        except (ValueError,KeyError,TypeError) as e:
            problems.append({"reason":str(e) if isinstance(e,QuantityError) else "Некорректный количественный факт."})
    orders={};other=[];events=defaultdict(list)
    for row in seen.values():
        if row["quantity_basis"]=="order_cohort" and row.get("ordered_qty") is not None:
            key=_identity(row);prior=orders.get(key)
            if prior:
                if prior.get("ordered_qty")!=row.get("ordered_qty"):
                    problems.append({"store_id":key[1],"reason":"Изменился исходный знаменатель заказа."});row["complete"]=False
                if str(prior.get("observed_at") or "")>str(row.get("observed_at") or ""):continue
            orders[key]=row
        elif (row.get("order_id") or row.get("posting_number")) and (row.get("quantity_basis")=="return_event" or row.get("loss_event_qty") is not None or row.get("return_type") or row.get("event_kind") in ("return","nonbuyout","cancel")):
            events[_identity(row)].append(row)
        else:other.append(row)
    for key,event_rows in events.items():
        row=orders.get(key)
        if row is None:
            matches=[r for k,r in orders.items() if k[:4]==key[:4] and str(r.get("sku"))==str(event_rows[0].get("sku"))]
            if len(matches)==1:row=matches[0]
        if row is None:
            for event in event_rows:
                problems.append({"store_id":key[1],"sku":event.get("sku"),"reason":"Возврат не связан с подтверждённой исходной позицией заказа.","event_date":event.get("event_date")})
            continue
        try:
            n=_integer(row["ordered_qty"]);ids=set();physical=set();physical_known=True
            loss_events=[];ym_physical=0;ym_nonbuyout=0;ym_fast=False
            for event in event_rows:
                if event.get("event_date") is not None and _day(event["event_date"])>as_of:
                    raise QuantityError("Дата исхода находится в будущем.")
                if event.get("complete") is not True:row["complete"]=False
                if key[0]=="yandex_market":
                    if event.get("fast_return") is True and event.get("return_type")=="RETURN":
                        # fastReturn explicitly leaves the goods with the buyer.
                        # It is a monetary refund, not a physical loss or an
                        # unresolved material movement.
                        if event.get("physical_returns_known") is not True or _qty(event,"physical_return_qty")!=0:
                            raise QuantityError("Не подтверждён нулевой физический исход fastReturn.")
                        ym_fast=True
                        continue
                    if event.get("physical_returns_known") is not True:physical_known=False
                    else:ym_physical+=_qty(event,"physical_return_qty") or 0
                    ym_nonbuyout+=_qty(event,"nonbuyout_qty") or 0
                    continue
                units=event.get("unit_ids")
                qty=event.get("loss_event_qty",event.get("physical_return_qty"))
                if qty==0:
                    # A rejected/cancelled return request is not a lost unit.
                    continue
                if not isinstance(units,list) or len(set(map(str,units)))!=_integer(qty):
                    raise QuantityError("Недостаточно идентификаторов для объединения исходов заказа.")
                ids.update(map(str,units))
                if event.get("physical_returns_known") is True:
                    r=_qty(event,"physical_return_qty")
                    if r:
                        pids=event.get("physical_return_unit_ids",units if r==len(units) else None)
                        if pids is None or len(set(map(str,pids)))!=r:
                            raise QuantityError("Не подтверждены экземпляры физических возвратов.")
                        physical.update(map(str,pids))
                else:physical_known=False
                if key[0]=="ozon":
                    loss_events.append({"scheme":row.get("scheme"),"posting":key[3],"sku":str(row["sku"]),
                                        "exemplars":units,"type":event.get("return_type")})
            if len(ids)>n:raise QuantityError("Потери превышают исходное количество заказа.")
            cancelled=_qty(row,"cancelled_qty")
            if key[0]=="ozon":
                state="cancelled" if cancelled==n else "delivered" if row.get("terminal") is True else "pending"
                result=physical_outcome_union([{"scheme":row.get("scheme"),"posting":key[3],"sku":str(row["sku"]),
                    "day":_day(row["ordered_at"]).isoformat(),"units":n,"state":state}],loss_events)
                known=result["failed_units"]
            elif key[0]=="yandex_market":
                # YM itemStatuses are a disjoint cumulative unit partition.
                # Return IDs provide another cumulative observation of the same
                # order/SKU, not an extra sale or an additive second return.
                if not row.get("unit_statuses") or not row.get("physical_returns_known"):
                    raise QuantityError("Не подтверждена количественная разбивка исходной позиции Маркета.")
                original_physical=_qty(row,"physical_return_qty") or 0
                if ym_fast and original_physical>ym_physical:
                    # The aggregate RETURNED partition has no unit identity
                    # linking it to cash-only vs ordinary return records.
                    # Do not subtract an arbitrary fast quantity or retain an
                    # unproved physical maximum in material consumption.
                    row.update(physical_return_qty=None,physical_returns_known=False,lost_qty=None,terminal=False)
                    raise QuantityError("RETURNED и fastReturn не позволяют подтвердить физические исходы отдельных единиц заказа.")
                physical_qty=max(original_physical,ym_physical)
                nonbuyout=max(_qty(row,"nonbuyout_qty") or 0,ym_nonbuyout)
                known=(cancelled or 0)+nonbuyout+physical_qty+_integer(row["unit_statuses"].get("LOST",0))
                if known>n:raise QuantityError("Исходы Маркета превышают исходный заказ.")
                row["nonbuyout_qty"]=nonbuyout
            elif cancelled==n:known=n
            elif cancelled in (0,None) and _qty(row,"nonbuyout_qty") in (0,None):known=len(ids)
            else:
                prior_ids=row.get("loss_unit_ids")
                if not isinstance(prior_ids,list):raise QuantityError("Не подтверждено пересечение отмен и возвратов.")
                known=len(ids|set(map(str,prior_ids)))
            old=_qty(row,"lost_qty")
            row["lost_qty"]=max(old or 0,known)
            # A source snapshot is cumulative. Never add its already recorded
            # return quantity to the same event exemplars a second time.
            if physical_known:
                row["physical_return_qty"]=max(_qty(row,"physical_return_qty") or 0,ym_physical if key[0]=="yandex_market" else len(physical))
                row["physical_returns_known"]=True
            else:
                row["physical_returns_known"]=False
            if any(e.get("terminal") is False for e in event_rows):row["terminal"]=False
        except (ValueError,KeyError,TypeError) as e:
            row["complete"]=False
            problems.append({"store_id":key[1],"sku":row.get("sku"),"reason":str(e) if isinstance(e,QuantityError) else "Не подтверждена связь исходов заказа."})
    # A complete empty return observation proves zero; an absent/partial source
    # never does. Postings themselves do not establish the return denominator.
    return_coverage={}
    for row in orders.values():
        if row.get("provider")!="ozon":continue
        try:
            coverage_key=(_scope(row),_day(row["ordered_at"]))
            if coverage_key not in return_coverage:
                return_coverage[coverage_key]=_coverage(snapshot,coverage_key[0],"order_cohort",coverage_key[1],as_of,as_of,rate=True,roles=("returns",))["complete"]
            observed=return_coverage[coverage_key]
            if observed and _identity(row) not in events:
                if row.get("physical_return_qty") is None:
                    row.update(physical_return_qty=0,physical_returns_known=True)
                if row.get("nonbuyout_qty") is None:row["nonbuyout_qty"]=0
                if row.get("lost_qty") is None:row["lost_qty"]=_qty(row,"cancelled_qty") or 0
        except (KeyError,ValueError,TypeError):pass
    result=[]
    for row in [*orders.values(),*other]:
        try:
            basis=row["quantity_basis"]
            start=_day(row.get("ordered_at") if basis=="order_cohort" else row.get("interval_from") if basis in ("funnel_interval","calendar_interval") else row.get("event_date"))
            end=_day(row["interval_to"]) if basis in ("funnel_interval","calendar_interval") else start
            if end<start or start>as_of:raise QuantityError("Неподтверждённые границы количественного периода.")
            values=_row_values(row)
            result.append({**row,"_start":start,"_end":end,"_values":values,
                "_mature":basis in ("order_cohort","funnel_interval") and end<=as_of-timedelta(days=MATURITY_DAYS) and row.get("terminal") is True})
        except (ValueError,KeyError,TypeError) as e:
            problems.append({"store_id":row.get("store_id"),"sku":row.get("sku"),"reason":str(e) if isinstance(e,QuantityError) else "Неполный количественный факт."})
    return result,problems


def _interval_complete(parts,start,end):
    cursor=start
    for a,b in sorted(parts):
        if a>b or b<cursor:continue
        if a>cursor:return False
        cursor=max(cursor,b+timedelta(days=1))
        if cursor>end:return True
    return cursor>end


def _coverage(snapshot,scope,basis,start,end,as_of,*,rate=False,roles=None,now=None,unresolved=()):
    roles=roles or (("orders",) if basis=="funnel_interval" else ("orders","returns") if basis=="order_cohort" else ("realization",))
    proofs=[];missing=[]
    for role in roles:
        intervals=[]
        required_end=as_of if rate and role=="returns" else end
        for c in snapshot.get("coverage",[]):
            if (c.get("provider"),str(c.get("store_id")))!=scope:continue
            # A single-posting lookup is a useful boundary fact. It never
            # establishes that every other order in its date window was read.
            if c.get("source_id")=="OZ-05" and role=="orders":continue
            actual_role=c.get("role") or ROLE.get(c.get("source_id"))
            if actual_role!=role:continue
            cb=c.get("quantity_basis")
            if cb is not None and cb!=basis and role!="returns":continue
            if c.get("complete") is not True or c.get("state") not in ("ready","complete","zero","no_data","no_data_confirmed"):continue
            try:
                a,b=_day(c["from"]),_day(c["to"])
                if role=="returns" and rate:
                    # The observation validates this exact requested window;
                    # it cannot turn an old window into coverage through today.
                    if c.get("observed_through") is None or _day(c["observed_through"])<b:continue
                if b<start or a>required_end:continue
                intervals.append((a,b));proofs.append({"source_id":c.get("source_id"),"role":role,"from":a.isoformat(),"to":b.isoformat(),
                    "observed_at":c.get("observed_at"),"observed_through":c.get("observed_through"),"required_from":start.isoformat(),"required_to":required_end.isoformat()})
            except (ValueError,TypeError,KeyError):continue
        if not _interval_complete(intervals,start,required_end):missing.append(role)
    freshness=_freshness(proofs,now or as_of,unresolved)
    return {"complete":not missing and freshness["fresh_enough"],"interval_complete":not missing,"from":start.isoformat(),"to":end.isoformat(),
            "missing_roles":missing,"proofs":proofs,"freshness":freshness}


def _wilson(losses,units):
    if not units:return None
    with localcontext() as ctx:
        ctx.prec=40
        n=Decimal(units);p=Decimal(losses)/n;z2=WILSON_Z**2
        return WILSON_Z*(p*(1-p)/n+z2/(4*n*n)).sqrt()/(1+z2/n)


def _training_period(as_of):
    end=as_of-timedelta(days=MATURITY_DAYS)
    return end-timedelta(days=HISTORY_DAYS-1),end


def _interval_selection(snapshot,rows,scope,basis,start,end,as_of,*,now=None,group_by=None):
    """Choose whole published source windows, then take their complete rows.

    Selection is global for the source/store, never per SKU: an absent SKU in
    an exact complete report must not reappear from an overlapping old report.
    A date aggregate is indivisible. No prorating, subtraction of overlapping
    totals, or inferred daily quantities can fill an uncollected edge.
    """
    now=now or as_of;role="orders" if basis=="funnel_interval" else "realization"
    by_window=defaultdict(list)
    for r in rows:
        if _scope(r)==scope and r["quantity_basis"]==basis:
            by_window[(r.get("source_id"),r["_start"],r["_end"])].append(r)
    windows={};missing_projection=[]
    for raw in snapshot.get("coverage",[]):
        if (raw.get("provider"),str(raw.get("store_id")))!=scope:continue
        source=raw.get("source_id")
        if (raw.get("role") or ROLE.get(source))!=role or raw.get("quantity_basis") not in (None,basis):continue
        if raw.get("complete") is not True or raw.get("state") not in ("ready","complete","zero","no_data","no_data_confirmed"):continue
        try:
            lo,hi=_day(raw["from"]),_day(raw["to"])
            if lo<start or hi>end or hi<lo:continue
            if group_by=="day" and lo!=hi:continue
            if group_by=="month" and lo.replace(day=1)!=hi.replace(day=1):continue
            key=(source,lo,hi);facts=by_window.get(key,[])
            empty=raw.get("zero_confirmed") is True or raw.get("state") in ("zero","no_data","no_data_confirmed")
            count=raw.get("rows")
            if (not facts and not empty) or (empty and facts) or (type(count) is int and count!=len(facts)):
                missing_projection.append(key);continue
            stamp=_instant(raw["observed_at"]).timestamp() if raw.get("observed_at") is not None else 0
            if key in windows and windows[key]["stamp"]>stamp:continue
            p={"source_id":source,"role":role,"from":lo.isoformat(),"to":hi.isoformat(),
               "required_from":lo.isoformat(),"required_to":hi.isoformat(),"observed_at":raw.get("observed_at")}
            fresh=_freshness([p],now,[r["_start"] for r in facts if r.get("terminal") is False])["fresh_enough"]
            windows[key]={"key":key,"raw":raw,"rows":facts,"stamp":stamp,"fresh":fresh}
        except (ValueError,KeyError,TypeError,OverflowError,OSError):continue

    def partition(options):
        edges=defaultdict(list)
        for item in options:edges[item["key"][1]].append(item)
        paths={end+timedelta(days=1):()}
        for lo in sorted(edges,reverse=True):
            choices=[(item,)+paths[item["key"][2]+timedelta(days=1)] for item in edges[lo]
                     if item["key"][2]+timedelta(days=1) in paths]
            if choices:
                paths[lo]=min(choices,key=lambda path:(len(path),-min(p["stamp"] for p in path),tuple(str(p["key"]) for p in path)))
        return paths.get(start)

    # Prefer a current complete partition. Within it, one exact window wins
    # over multiple pieces. A stale saved partition remains visible as stale.
    chosen=partition([p for p in windows.values() if p["fresh"]]) or partition(windows.values())
    overlap=False;last_end=None
    for key in sorted(windows,key=lambda k:(k[1],k[2],str(k[0]))):
        if last_end is not None and key[1]<=last_end:overlap=True
        last_end=max(last_end,key[2]) if last_end else key[2]
    selected=[r for item in chosen or () for r in item["rows"]]
    restricted={**snapshot,"coverage":[p["raw"] for p in chosen]} if chosen else snapshot
    proof=_coverage(restricted,scope,basis,start,end,as_of,now=now,
                    unresolved=[r["_start"] for r in selected if r.get("terminal") is False])
    proof["interval_selection"]={"complete":chosen is not None,"exact":bool(chosen and len(chosen)==1),
        "windows":[{"source_id":p["key"][0],"from":p["key"][1].isoformat(),"to":p["key"][2].isoformat()} for p in chosen or ()],
        "overlapping_intervals":overlap,"missing_projections":len(missing_projection)}
    proof["complete"]=proof["complete"] and chosen is not None
    issue=None if chosen else ("Подтверждённое окно не содержит сохранённой полной проекции строк." if missing_projection else
        "Не подтверждён полный набор непересекающихся интервалов выбранного периода; агрегаты нельзя обрезать.")
    return selected,proof,issue


def _rate_index(snapshot,rows,as_of,*,now=None):
    """One linear pass; reporting many SKUs does not rescan all order history."""
    by_scope=defaultdict(list);groups=defaultdict(list);bases={};coverage={}
    start,end=_training_period(as_of)
    for r in rows:
        if r["quantity_basis"] in ("order_cohort","funnel_interval"):by_scope[_scope(r)].append(r)
    for scope,rs in by_scope.items():
        basis="funnel_interval" if scope[0]=="wb" and any(r["quantity_basis"]=="funnel_interval" for r in rs) else "order_cohort"
        bases[scope]=basis
        if basis=="funnel_interval":
            rs,coverage[scope],_=_interval_selection(snapshot,rs,scope,basis,start,end,as_of,now=now)
        else:coverage[scope]=_coverage(snapshot,scope,basis,start,end,as_of,rate=True,now=now,
            unresolved=[r["_start"] for r in rs if r.get("terminal") is not True])
        for r in rs:
            if r["quantity_basis"]!=basis:continue
            groups[(scope,"store",scope[1])].append(r)
            groups[(scope,"sku",str(r.get("sku") or ""))].append(r)
            if r.get("category_id") is not None:groups[(scope,"category",str(r["category_id"]))].append(r)
    return {"groups":groups,"basis":bases,"coverage":coverage,"now":now or as_of}


def _rate(snapshot,rows,target,as_of,*,index=None):
    start,end=_training_period(as_of);scope=_scope(target)
    index=index or _rate_index(snapshot,rows,as_of)
    basis=index["basis"].get(scope,"order_cohort")
    coverage=index["coverage"].get(scope) or _coverage(snapshot,scope,basis,start,end,as_of,rate=True,now=index["now"])
    choices=[("sku",str(target.get("sku") or ""))]
    if target.get("category_id") is not None:choices.append(("category",str(target["category_id"])))
    choices.append(("store",scope[1]));attempts=[]
    for level,ident in choices:
        selected=index["groups"].get((scope,level,ident),[])
        selection=coverage.get("interval_selection",{})
        eligible=[];excluded=0;invalid=0;conflict=bool(selection.get("overlapping_intervals") and not selection.get("complete"));intervals=defaultdict(list)
        for r in selected:
            if r["_end"]<start or r["_start"]>end:continue
            v=r["_values"]
            if r.get("complete") is not True or v["ordered"] is None or v["losses"] is None:
                invalid+=1;continue
            if r["_start"]<start or r["_end"]>end or not r["_mature"]:
                excluded+=1;continue
            if basis=="funnel_interval":
                sku=str(r.get("sku"));a,b=r["_start"],r["_end"]
                if any(a<=prior_b and b>=prior_a for prior_a,prior_b in intervals[sku]):conflict=True
                intervals[sku].append((a,b))
            eligible.append(r)
        denominator=sum(r["_values"]["ordered"] for r in eligible)
        numerator=sum(r["_values"]["losses"] for r in eligible)
        physical_known=bool(eligible) and all(r["_values"]["physical_returns"] is not None for r in eligible)
        physical=sum(r["_values"]["physical_returns"] or 0 for r in eligible) if physical_known else None
        width=_wilson(numerator,denominator)
        sample=width is not None and width<=MAX_RATE_HALF_WIDTH
        sufficient=sample and coverage["complete"] and not conflict and invalid==0
        rate=Decimal(numerator)/denominator if denominator else None
        value={"provider":scope[0],"store_id":scope[1],"sku":str(target.get("sku") or ""),"product_id":target.get("product_id"),
            "category_id":target.get("category_id"),"status":"ready" if sufficient else "unknown", "value":_decimal(rate) if sufficient else None,
            "loss_rate_percent":_decimal(rate*100) if sufficient else None,"observed_ratio":_decimal(rate),
            "numerator":numerator,"denominator":denominator,"source_level":level,"scope_id":ident,
            "from":start.isoformat(),"to":end.isoformat(),"as_of":as_of.isoformat(),"maturity_days":MATURITY_DAYS,
            "coverage":coverage,"sample_sufficient":sample,"wilson95_half_width":_decimal(width),
            "observed_at":coverage["freshness"]["observed_at"],"freshness":coverage["freshness"],"stale":coverage["freshness"]["stale"],
            "max_half_width":str(MAX_RATE_HALF_WIDTH),"excluded_rows":excluded,"invalid_rows":invalid,"overlapping_intervals":conflict,
            "physical_returns_known":physical_known,"physical_return_numerator":physical,
            "physical_return_rate":_decimal(Decimal(physical)/denominator) if sufficient and physical_known and denominator else None,
            "method":"cancelCount/orderCount" if basis=="funnel_interval" else "physical_outcome_union" if scope[0]=="ozon" else "unique_lost/original_ordered",
            "policy_version":POLICY_VERSION}
        attempts.append({"level":level,"numerator":numerator,"denominator":denominator,"sample_sufficient":sample,"excluded_rows":excluded})
        if sufficient:return {**value,"fallback_attempts":attempts}
    return {**value,"fallback_attempts":attempts}


def _estimate(row,rate):
    v=row["_values"]
    result={k:None for k in ESTIMATES}
    if row["quantity_basis"] in ("calendar_event","calendar_interval") or row["_mature"]:
        return {"estimated_net":v["net"],"estimated_losses":v["losses"],"estimated_physical_returns":v["physical_returns"],"estimated_delivered":v["delivered"]}
    if row.get("complete") is not True or rate.get("value") is None or v["ordered"] is None or v["losses"] is None:
        return result
    n=Decimal(v["ordered"]);loss=max(Decimal(v["losses"]),n*Decimal(rate["value"]))
    if loss>n:raise QuantityError("Ожидаемые потери превышают исходный заказ.")
    result.update(estimated_net=n-loss,estimated_losses=loss)
    if rate.get("physical_return_rate") is not None and v["physical_returns"] is not None:
        returns=max(Decimal(v["physical_returns"]),n*Decimal(rate["physical_return_rate"]))
        # Already known non-physical outcomes consume part of the same loss
        # union. A cancelled unit cannot also become a predicted buyer return.
        known_nonphysical=Decimal(v["losses"]-v["physical_returns"])
        returns=min(returns,loss-known_nonphysical)
        if returns<=loss:result.update(estimated_physical_returns=returns,estimated_delivered=n-loss+returns)
    return result


def _sum(rows,keys):
    return {k:_decimal(sum(Decimal(str(r[k])) for r in rows)) if rows and all(r.get(k) is not None for r in rows) else 0 if not rows else None for k in keys}


def _limit(offset,limit):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError("Некорректная страница отчёта.")


def _targets(snapshot,rows):
    targets={}
    for r in [*snapshot.get("rows",[]),*rows]:
        if r.get("sku") is None:continue
        try:key=(*_scope(r),str(r["sku"]))
        except QuantityError:continue
        prior=targets.get(key,{})
        targets[key]={**prior,**r}
    return targets


def loss_rates_snapshot(snapshot,*,as_of,product=None,offset=0,limit=30,_unpaginated=False):
    _limit(offset,limit);now=_instant(as_of);as_of=_day(as_of);rows,problems=_rows(snapshot,as_of)
    result=[];index=_rate_index(snapshot,rows,as_of,now=now)
    for target in _targets(snapshot,rows).values():
        if product is None or target.get("product_id")==product:
            result.append(_rate(snapshot,rows,target,as_of,index=index))
    result.sort(key=lambda r:(r["provider"],r["store_id"],r["sku"]))
    observed=max((r["observed_at"] for r in result if r["observed_at"]),default=None)
    return {"status":"ready" if result and not problems and all(r["status"]=="ready" for r in result) else "partial" if result else "no_data",
        "rows":result if _unpaginated else result[offset:offset+limit],"total":len(result),"offset":offset,"limit":len(result) if _unpaginated else limit,
        "as_of":as_of.isoformat(),"calculated_at":now.isoformat(),"observed_at":observed,"stale":any(r["stale"] for r in result),
        "freshness":{"status":"stale" if any(r["stale"] for r in result) else "unknown" if any(r["freshness"]["status"]=="unknown" for r in result) else "fresh","max_age_seconds":86400},
        "policy_version":POLICY_VERSION,"problems":problems,
        "known_rates":sum(r["status"]=="ready" for r in result),"unknown_rates":sum(r["status"]!="ready" for r in result),
        "policy":{"maturity_days":MATURITY_DAYS,"history_days":HISTORY_DAYS,"confidence":"0.95","max_half_width":str(MAX_RATE_HALF_WIDTH),"full_coverage_required":True},
        "external_calls":0,"model_calls":0}


def sales_snapshot(snapshot,*,from_,to,as_of,source="all_marketplaces",product=None,group_by="product",offset=0,limit=30,_unpaginated=False):
    _limit(offset,limit);now=_instant(as_of);start,end,as_of=map(_day,(from_,to,as_of))
    if end<start or end>as_of:raise ValueError("Некорректный период отчёта.")
    if group_by not in ("product","marketplace","day","month","sku","store"):raise ValueError("Неизвестная группировка.")
    normalized,problems=_rows(snapshot,as_of);targets=_targets(snapshot,normalized)
    scopes={_scope(r) for r in normalized}
    for s in snapshot.get("stores",[]):
        try:scopes.add(_scope({**s,"store_id":s.get("store_id") or s.get("id")}))
        except QuantityError:pass
    for c in snapshot.get("coverage",[]):
        try:scopes.add(_scope(c))
        except QuantityError:pass
    selected=[];coverage=[];bases={};rates={};unmapped=[];rate_index=_rate_index(snapshot,normalized,as_of,now=now)
    for scope in sorted(scopes):
        candidates=[r for r in normalized if _scope(r)==scope and r["_start"]<=end and r["_end"]>=start]
        unresolved=[r["_start"] for r in candidates if r.get("terminal") is False]
        def coverage_for(basis):return _coverage(snapshot,scope,basis,start,end,as_of,now=now,unresolved=unresolved)
        options=("funnel_interval","order_cohort","calendar_event","calendar_interval") if scope[0]=="wb" else ("order_cohort","calendar_event","calendar_interval","funnel_interval")
        basis=next((b for b in options if coverage_for(b)["complete"] and any(r["quantity_basis"]==b for r in candidates)),None)
        if basis is None:basis=next((b for b in options if any(r["quantity_basis"]==b for r in candidates)),None)
        if basis is None:basis=next((b for b in options if coverage_for(b)["complete"]),options[0])
        proof=coverage_for(basis);bases[scope]=basis
        if basis in ("funnel_interval","calendar_interval"):
            candidates,proof,issue=_interval_selection(snapshot,normalized,scope,basis,start,end,as_of,now=now,group_by=group_by)
            if issue:problems.append({"store_id":scope[1],"reason":issue})
        coverage.append({"provider":scope[0],"store_id":scope[1],"quantity_basis":basis,**proof})
        for r in candidates:
            if r["quantity_basis"]!=basis:continue
            if product is not None and r.get("product_id")!=product:continue
            if r["_start"]<start or r["_end"]>end:
                problems.append({"store_id":scope[1],"reason":"Интервальный агрегат нельзя обрезать до выбранных дат."});continue
            if basis in ("funnel_interval","calendar_interval") and group_by in ("day","month") and (r["_start"]!=r["_end"] if group_by=="day" else r["_start"].replace(day=1)!=r["_end"].replace(day=1)):
                problems.append({"store_id":scope[1],"reason":"Воронка не содержит доказанной разбивки по выбранной календарной группе."});continue
            key=(*scope,str(r.get("sku")))
            if key not in rates:rates[key]=_rate(snapshot,normalized,targets.get(key,r),as_of,index=rate_index)
            estimate=_estimate(r,rates[key])
            item={**r["_values"],**estimate,"provider":scope[0],"store_id":scope[1],"sku":str(r.get("sku") or ""),
                "product_id":r.get("product_id"),"product":r.get("product") or r.get("product_name"),"name":r.get("name") or str(r.get("sku") or ""),
                "quantity_basis":basis,"day":r["_start"].isoformat(),"month":r["_start"].isoformat()[:7],"mature":r["_mature"],
                "complete":r.get("complete") is True,"physical_returns_known":r["_values"]["physical_returns"] is not None,
                "material_net_supported":not (basis in ("calendar_event","calendar_interval") and r["_values"]["calendar_returns"] and r["_values"]["physical_returns"] is None),
                "rate_source_level":rates[key]["source_level"],"rate_known":rates[key]["value"] is not None}
            selected.append(item)
            if not item["product_id"]:unmapped.append({k:item[k] for k in ("provider","store_id","sku","name","ordered","delivered","physical_returns","net")})
    groups=defaultdict(list)
    for r in selected:
        product_key=r["product_id"] or (r["provider"],r["store_id"],r["sku"])
        key=product_key if group_by=="product" else r["provider"] if group_by=="marketplace" else r["store_id"] if group_by=="store" else (r["provider"],r["store_id"],r["sku"]) if group_by=="sku" else (r[group_by],product_key)
        groups[str(key)].append(r)
    result=[]
    for key,rs in sorted(groups.items()):
        r=rs[0];row={"key":key,**_sum(rs,(*QUANTITIES,*ESTIMATES)),"product_id":r["product_id"] if group_by in ("product","day","month","sku") else None,
            "product":r["product"],"name":r["name"],"providers":sorted({x["provider"] for x in rs}),"store_ids":sorted({x["store_id"] for x in rs}),
            "skus":sorted({x["sku"] for x in rs}),"quantity_bases":sorted({x["quantity_basis"] for x in rs}),"mature":all(x["mature"] for x in rs),
            "complete":all(x["complete"] for x in rs),"physical_returns_known":all(x["physical_returns_known"] for x in rs),
            "material_net_supported":all(x["material_net_supported"] for x in rs)}
        if group_by in ("day","month"):row[group_by]=r[group_by]
        result.append(row)
    complete=bool(coverage) and all(c["complete"] for c in coverage) and not problems and all(r["complete"] for r in selected)
    if not selected and not complete:totals={k:None for k in (*QUANTITIES,*ESTIMATES)}
    else:totals=_sum(selected,(*QUANTITIES,*ESTIMATES))
    forecast_complete=complete and all(r["estimated_net"] is not None for r in selected)
    warnings=[]
    stale=any(c["freshness"]["stale"] for c in coverage)
    observed=max((c["freshness"]["observed_at"] for c in coverage if c["freshness"]["observed_at"]),default=None)
    if stale:warnings.append("Данные изменяемых периодов наблюдались более суток назад. Показан последний сохранённый снимок; дождитесь обновления перед новым планом.")
    if any(r["calendar_returns"] is not None and r["physical_returns"] is None for r in selected):
        warnings.append("Возврат в календарной реализации не подтверждает физическую приёмку товара. Чистая реализация показана; без физической разбивки такой возврат не уменьшает материальную потребность и не служит базой брака.")
    elif any(r["physical_returns"] is None for r in selected):
        warnings.append("Физическая приёмка возвратов не подтверждена источником. Неизвестное количество не равно нулю и не служит базой расчёта брака возвратов.")
    if len(set(bases.values()))>1:warnings.append("Источники используют разные оси времени: когорты заказов и календарную реализацию. Они показаны с основанием и не суммируются повторно внутри магазина.")
    if any(not r["mature"] and r["quantity_basis"] not in ("calendar_event","calendar_interval") for r in selected):warnings.append("Свежие или незавершённые заказы показаны отдельно как оценка итоговых потерь от исходного объёма.")
    return {"status":"ready" if complete and selected else "no_data_confirmed" if complete else "partial", "complete":complete,
        "forecast_complete":forecast_complete,"source":source,"from":start.isoformat(),"to":end.isoformat(),"as_of":as_of.isoformat(),
        "calculated_at":now.isoformat(),"observed_at":observed,"stale":stale,
        "freshness":{"status":"stale" if stale else "unknown" if any(c["freshness"]["status"]=="unknown" for c in coverage) else "fresh" if any(c["freshness"]["status"]=="fresh" for c in coverage) else "closed","max_age_seconds":86400},
        "group_by":group_by,"rows":result if _unpaginated else result[offset:offset+limit],"total":len(result),"offset":offset,"limit":len(result) if _unpaginated else limit,"totals":totals,
        "observed_totals":{k:_decimal(sum(Decimal(str(r[k])) for r in selected if r[k] is not None)) for k in QUANTITIES},
        "coverage":coverage,"unmapped":unmapped[:100],"unmapped_count":len(unmapped),"problems":problems,"warnings":warnings,
        "external_calls":0,"model_calls":0}


def _snapshot(db,w,source):
    from .market_quantity import quantity_snapshot
    return quantity_snapshot(db,w,source=source)


def sales(db,w,*,from_=None,to=None,source="all_marketplaces",product=None,group_by="product",offset=0,limit=30,as_of=None,**aliases):
    from . import podmasterye_book as book
    if from_ is None:from_=aliases.pop("from",None)
    if aliases:raise ValueError("Неизвестные параметры количественного отчёта.")
    as_of=as_of or _report_clock(book.today());to=to or _day(as_of).isoformat()
    from_=from_ or (_day(to)-timedelta(days=29)).isoformat()
    return sales_snapshot(_snapshot(db,w,source),from_=from_,to=to,source=source,as_of=as_of,product=product,group_by=group_by,offset=offset,limit=limit)


def loss_rates(db,w,source="all_marketplaces",product=None,offset=0,limit=30,as_of=None):
    from . import podmasterye_book as book
    return loss_rates_snapshot(_snapshot(db,w,source),as_of=as_of or _report_clock(book.today()),product=product,offset=offset,limit=limit)


def read(store,token,workshop_id=None,action="sales",**args):
    from .identity import _principal
    from . import podmasterye_workshops as workshops
    with store._lock:
        _,account=_principal(store._db,token);w=workshops.resolve(store._db,account,workshop_id)
        if action=="sales":return sales(store._db,w,**args)
        if action=="loss_rates":return loss_rates(store._db,w,**args)
        raise ValueError("Неизвестная операция количественной аналитики.")


def planning_sales(db,w,*,from_,to,source):
    """Unpaginated internal projection; public totals are never page totals."""
    snapshot=_snapshot(db,w,source)
    from . import podmasterye_book as book
    return sales_snapshot(snapshot,from_=from_,to=to,source=source,as_of=_report_clock(book.today()),group_by="product",limit=100,_unpaginated=True)
