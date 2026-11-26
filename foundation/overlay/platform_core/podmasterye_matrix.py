"""Versioned local routing matrix. No paid calls for unambiguous phrases."""
import json
import re
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from . import podmasterye_book as book
from .podmasterye_domain import Conflict

VERSION="accounting-v2"
ITEMS=json.loads(Path(__file__).with_name("podmasterye_matrix.json").read_text(encoding="utf-8"))
def norm(t):return " ".join(t.casefold().replace("ё","е").split()).strip("?! .")
INDEX={}
for entry in ITEMS:
    for alias in entry["aliases"]:
        key=norm(alias)
        if key in INDEX:raise RuntimeError("Duplicate matrix alias")
        INDEX[key]=entry
    if entry["intent"]=="form" and entry["op"] not in book.FIELDS:raise RuntimeError("Unknown matrix operation")
PERIODS=("за прошлый месяц","за этот месяц","за текущий месяц","за последние 30 дней","за сегодня","за вчера","за весь период","за месяц")
METRICS={"net_profit":"Чистая прибыль","revenue":"Выручка","cashflow":"Денежный поток","inventory_rub":"Стоимость текущих запасов",
         "expenses":"Расходы","purchases":"Закупки","current_receivables_rub":"Текущая задолженность покупателей","writeoffs":"Стоимость списаний"}
def dates(s):
    now=book.today();start=now.replace(day=1);end=now
    if s=="за прошлый месяц":end=start-timedelta(days=1);start=end.replace(day=1)
    elif s=="за последние 30 дней":start=now-timedelta(days=29)
    elif s=="за вчера":start=end=now-timedelta(days=1)
    elif s=="за сегодня":start=now
    elif s=="за весь период":return None,None
    return start.isoformat(),end.isoformat()

def name_key(value):
    return tuple(norm(value).split())
def read_material(db,w,name):
    allrows=db.execute("SELECT id,name FROM pm_materials WHERE workspace=? ORDER BY normalized",(w,)).fetchall()
    exact=[r for r in allrows if name_key(r[1])==name_key(name)]
    if len(exact)==1:return exact[0]
    def stems(value):
        variants=set()
        for word in name_key(value):
            if len(word)<4:return set()
            forms={word}
            for ending in ("ами","ями","ов","ев","ей","ам","ям","ах","ях","ы","и","а","я","у","ю","е","ом","ем"):
                if word.endswith(ending) and len(word)-len(ending)>=4:forms.add(word[:-len(ending)])
            variants.add(frozenset(forms))
        return variants
    # Only a single lexical token is matched approximately; multiword names require exact match.
    if len(name_key(name))!=1:return None
    query=stems(name)
    matches=[r for r in allrows if len(name_key(r[1]))==1 and any(a&b for a in query for b in stems(r[1]))]
    return matches[0] if len(matches)==1 else None
def specific(db,w,t):
    suffix=None
    for p in PERIODS:
        if t.endswith(" "+p):t=t[:-len(p)-1];suffix=p;break
    patterns=(
      ("stock",r"сколько (?:материала )?(.+?) осталось(?: на складе)?"),
      ("consumption",r"сколько (?:упаковок|пачек|штук) (.+?) (?:ушло|израсходовано|продано)"),
      ("planning",r"сколько (.+?) (?:нужно |надо )?(?:купить|закупить)"),
    )
    for kind,pat in patterns:
        m=re.fullmatch(pat,t)
        if not m:continue
        found=read_material(db,w,m[1])
        out={"matrixId":{"stock":"A-R13","consumption":"A-R14","planning":"A-R15"}[kind],"matrixVersion":VERSION}
        if not found:
            return {**out,"text":"Не нашёл однозначный материал. Укажите его точное название из справочника.","ui":{"page":"materials"}}
        mid,name=found
        if kind=="stock":
            d=book.report(db,w,view="stock");v=next(x for x in d["materials"] if x["id"]==mid)
            text=f'{name}: учётный остаток {v["quantity"]} {v["unit"]}, стоимость {v["value_rub"]} ₽.' if v["valued"] else f'{name}: фактический остаток пока не введён.'
            return {**out,"text":text,"ui":{"page":"stock","entity":name}}
        if kind=="consumption":
            start,end=dates(suffix);d=book.report(db,w,start,end,view="planning")
            v=next((x for x in d["consumption"] if x["material_id"]==mid),None)
            text=f'{name}: по чистым продажам {v["quantity"]} {v["unit"]}, эквивалент {v["pack_equivalent"]} упаковки.' if v else f'{name}: за период нет расхода по учтённым чистым продажам.'
            return {**out,"text":text+" Это эквивалент по продажам, не фактическое списание сырья.","ui":{"page":"planning","entity":name,"filters":{"from":start,"to":end}}}
        d=book.report(db,w,view="planning");v=next(x for x in d["planning"] if x["material_id"]==mid)
        return {**out,"text":f'{name}: по прогнозу на 30 дней — {v["buy_packs"]} упаковок, ориентировочная дата заказа {v["order_day"] or "нет спроса"}. Без резервов и поставок в пути.',"ui":{"page":"planning","entity":name}}
    return None

def route(db,w,text):
    t=norm(text);suffix=None;entry=INDEX.get(t)
    if not entry:
        for p in PERIODS:
            if t.endswith(" "+p) and t[:-len(p)-1] in INDEX:
                e=INDEX[t[:-len(p)-1]]
                if e["intent"] in ("report","ui"):entry=e;suffix=p
                break
    args=None
    if not entry:
        found=specific(db,w,t)
        if found:return found
        for e in ITEMS:
            if e["intent"]=="form" and e.get("pattern") and (m:=re.fullmatch(e["pattern"]," ".join(text.strip().rstrip("!.").split()),re.I)):
                entry=e;args=m.groupdict();break
    if not entry:return None
    kind=entry["intent"]
    ui={"page":entry.get("page",book.PAGES.get(entry.get("op"),"summary"))}
    if suffix:
        a,b=dates(suffix);ui.update(filters={"from":a,"to":b})
    answer=entry.get("answer")
    out={"ui":ui,"matrixId":entry["id"],"matrixVersion":VERSION}
    if kind=="faq" or kind=="ui":
        out["text"]=answer or "Открываю нужный раздел."
        return out
    if kind=="report":
        start,end=dates(suffix);d=book.report(db,w,start,end,view=entry["view"])
        if entry.get("metric"):
            k=entry["metric"];out["text"]=f'{METRICS[k]}: {d["summary"][k]} ₽.'
            ui["highlight"]=k
            if k not in ("inventory_rub","current_receivables_rub"):
                ui["filters"]={"from":start,"to":end}
                out["text"]+=f" Период: {start or 'все даты'} — {end}."
        elif entry["view"]=="planning":
            suggestions=[p for p in d["planning"] if p["buy_packs"]>0]
            out["text"]=("Рекомендуемые закупки: "+ "; ".join(f'{p["material"]} — {p["buy_packs"]} уп.' for p in suggestions[:10])+".") if suggestions else "По чистым продажам последних 30 дней модель не выявила потребности в закупке. Проверьте полноту данных."
            out["text"]+=" Прогноз без резервов и ожидаемых поставок."
        elif entry["view"]=="stock":
            out["text"]="Текущие учётные остатки: "+("; ".join(f'{m["name"]}: {m["quantity"]} {m["unit"]}' for m in d["materials"][:10]) or "нет материалов")+"."
        else:
            ui["filters"]={"from":start,"to":end}
            out["text"]="Отчёт рассчитан; подробные данные показаны в разделе."
        return out
    op=entry["op"]
    if args:
        if "quantity" in args:args["quantity"]=int(args["quantity"])
        if "purchase_unit" in args:args["purchase_unit"]="pack" if args["purchase_unit"].casefold().startswith(("пач","упаков")) else "base"
        if "category" in args:
            cats=[c for c in book.CATEGORIES if norm(c)==norm(args["category"])]
            aliases={"рекламу":"Реклама","аренду":"Аренда","доставку":"Доставка","упаковку":"Упаковка","оплату труда":"Оплата труда"}
            args["category"]=cats[0] if cats else aliases.get(norm(args["category"]),"")
        # Resolve IDs exactly; an ambiguous name stays for user correction in the form.
        for field in ("material","product"):
            if field in args:
                try:args[field]=book.entity(db,w,field,args[field])[0]
                except ValueError:pass
    args={**entry.get("defaults",{}),**(args or {})}
    out["accountingDraft"]={"operation":op,"arguments":args}
    out["text"]="Подготовил форму «"+book.FIELDS[op][0]+"». Проверьте данные, выполните предварительный расчёт и подтвердите запись."
    return out

def operation_schema():
    properties={}
    for f in book.forms().values():
        for field in f["fields"]:
            n,t=field["name"],field["type"]
            if t in ("int","int0"):s={"type":"integer","minimum":0,"maximum":book.MAX_Q}
            elif t=="bool":s={"type":"boolean"}
            else:s={"type":"string","maxLength":240}
            properties[n]=s
    # Keep a single compact tool schema. Backend validates exact fields per op.
    return {"type":"object","properties":{"operation":{"type":"string","enum":list(book.FIELDS)},
            "arguments":{"type":"object","properties":properties,"additionalProperties":False}},
            "required":["operation","arguments"],"additionalProperties":False}

def report_schema():
    return {"type":"object","properties":{"view":{"type":"string","enum":["summary","stock","sales","planning","finance","journal","tasks","workers","unit","catalog"]},
        "start":{"type":"string"},"end":{"type":"string"},"target_profit":{"type":"string"},"horizon":{"type":"integer","minimum":1,"maximum":365},
        "lead":{"type":"integer","minimum":0,"maximum":365},"safety":{"type":"integer","minimum":0,"maximum":365},
        "limit":{"type":"integer","minimum":1,"maximum":30}},"required":["view"],"additionalProperties":False}

def operation_description():
    return "Подготовить черновик операции, не записывает склад или деньги. Используй точные ID или названия; суммы строками в рублях, количества целыми базовыми единицами. Поля: "+ "; ".join(
        k+"("+",".join(f["name"]+("!" if f["required"] and f["default"] is None else "") for f in v["fields"])+")" for k,v in book.forms().items())+". Для отсутствующих обязательных параметров спроси пользователя. Подтверждение только в кабинете."
