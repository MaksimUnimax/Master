"""Bounded file import and public deterministic price calculator."""
import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from .identity import _principal
from .podmasterye_domain import Conflict,clean_name,encode,key_id,_save
from . import podmasterye_book as book,podmasterye_workshops as workshops

MAX_FILE=512*1024
MAX_ROWS=300
HEADERS=("name","category","unit","pack","pack_price","initial_quantity","initial_total","note")
ALIASES={
 "название":"name","материал":"name","наименование":"name","категория":"category",
 "единица":"unit","ед. изм.":"unit","единица измерения":"unit","упаковка":"pack","единиц в упаковке":"pack",
 "цена упаковки":"pack_price","плановая цена упаковки":"pack_price","начальный остаток":"initial_quantity",
 "стоимость остатка":"initial_total","сумма начального остатка":"initial_total","заметка":"note",
}
def template():
    return ("\ufeff"+";".join(HEADERS)+"\nБусины;Фурнитура;шт;400;800;0;0;Пример\n").encode("utf-8")

def cells_from_file(name,encoded):
    if not isinstance(name,str) or not isinstance(encoded,str) or len(encoded)>MAX_FILE*2:
        raise ValueError("Файл слишком большой.")
    try:data=base64.b64decode(encoded,validate=True)
    except ValueError:raise ValueError("Некорректный файл.") from None
    if not data or len(data)>MAX_FILE:raise ValueError("Файл должен быть не больше 512 КБ.")
    if name.lower().endswith(".csv"):
        try:s=data.decode("utf-8-sig")
        except UnicodeDecodeError:raise ValueError("Сохраните CSV в UTF-8.") from None
        try:
            dialect=csv.Sniffer().sniff(s[:4096],delimiters=";,\t")
        except csv.Error:dialect=csv.excel
        rows=[]
        for i,row in enumerate(csv.reader(io.StringIO(s),dialect)):
            if i>MAX_ROWS+1:raise ValueError("Не более 300 строк.")
            rows.append(row)
        return rows
    if name.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries=z.infolist()
                if len(entries)>2000 or sum(x.file_size for x in entries)>8*1024*1024:raise ValueError("Слишком большой XLSX.")
                if any("vbaProject" in x.filename or "externalLinks/" in x.filename for x in entries):raise ValueError("Файл с макросами или внешними ссылками не поддерживается.")
            wb=load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
        except ValueError:raise
        except Exception:raise ValueError("Не удалось прочитать XLSX.") from None
        try:
            sheet=wb.active
            if (sheet.max_row or 0)>MAX_ROWS+1 or (sheet.max_column or 0)>20:raise ValueError("Не более 300 строк и 20 колонок.")
            rows=[]
            for i,row in enumerate(sheet.iter_rows()):
                if i>MAX_ROWS:raise ValueError("Не более 300 строк.")
                if len(row)>20:raise ValueError("Слишком много колонок.")
                if any(c.data_type in ("f","e") for c in row):raise ValueError("Замените формулы и ошибки значениями.")
                rows.append([c.value for c in row])
            return rows
        finally:wb.close()
    raise ValueError("Поддерживаются CSV и XLSX.")
def integer(value,field,default=None,zero=False):
    if value in (None,""):
        if default is None:raise ValueError("Заполните "+field)
        return default
    try:x=Decimal(str(value).replace(",","."))
    except Exception:raise ValueError("Некорректное количество: "+field) from None
    if not x.is_finite() or x!=x.to_integral_value() or not 0<=x<=book.MAX_Q:raise ValueError("Некорректное целое количество: "+field)
    return book.quantity(int(x),zero)
def amount(v):
    if v in (None,""):return None
    return book.money(book.minor(str(v).replace(",",".")))
def normalize(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_ROWS:raise ValueError("От 1 до 300 материалов.")
    out=[];seen=set()
    for i,r in enumerate(rows,2):
        try:
            if not isinstance(r,dict) or set(r)-set(HEADERS):raise ValueError("Лишние поля.")
            name=clean_name(r.get("name"))
            if name.casefold() in seen:raise ValueError("Повтор названия.")
            seen.add(name.casefold())
            unit=str(r.get("unit") or "шт").strip()
            if unit not in book.UNITS:raise ValueError("Неизвестная базовая единица.")
            qty=integer(r.get("initial_quantity"),"остаток",0,True);total=amount(r.get("initial_total"))
            if qty and total is None:raise ValueError("Укажите стоимость начального остатка.")
            if not qty and total not in (None,"0.00"):raise ValueError("Стоимость без количества.")
            out.append({"name":name,"category":book.textval(str(r.get("category") or "")),"unit":unit,
                        "pack":integer(r.get("pack"),"упаковка",1),"pack_price":amount(r.get("pack_price")),
                        "initial_quantity":qty,"initial_total":total or "0.00","note":book.textval(str(r.get("note") or ""))})
        except (ValueError,TypeError) as e:raise ValueError(f"Строка {i}: {e}") from None
    return out
def parse_file(name,encoded):
    rows=cells_from_file(name,encoded)
    if len(rows)<2:raise ValueError("В файле нет материалов.")
    header=[]
    for h in rows[0]:
        k=str(h or "").strip().casefold()
        header.append(ALIASES.get(k,k))
    if len(header)!=len(set(header)) or "name" not in header or set(header)-set(HEADERS):raise ValueError("Используйте заголовки из шаблона импорта.")
    return normalize([dict(zip(header,row)) for row in rows[1:] if any(v not in (None,"") for v in row)])
def apply(db,w,rid,rows):
    result=[]
    for i,r in enumerate(rows):
        key=hashlib.sha256(encode([rid,i]).encode()).hexdigest()
        if db.execute("SELECT 1 FROM pm_materials WHERE workspace=? AND normalized=?",(w,r["name"].casefold())).fetchone():
            raise Conflict("Материал уже существует: "+r["name"]+". Импорт не перезаписывает справочник.")
        m=book.execute(db,w,"imp-"+key,"material",{"name":r["name"],"unit":r["unit"],"pack":r["pack"],
              "pack_price":r["pack_price"],"category":r["category"],"catalog_note":r["note"]})
        if r["initial_quantity"]:
            book.execute(db,w,"open-"+key,"opening",{"material":m["id"],"quantity":r["initial_quantity"],"total":r["initial_total"]})
        result.append(m["id"])
    return result
def preview_import(store,token,workshop,name,encoded):
    rows=parse_file(name,encoded)
    with store._write() as db:
        _,a=_principal(db,token);w=workshops.resolve(db,a,workshop)
        rev=book.revision(db,w,"import_materials",rows)
        db.execute("SAVEPOINT import_preview")
        try:apply(db,w,"preview-"+uuid4().hex,rows)
        finally:db.execute("ROLLBACK TO import_preview");db.execute("RELEASE import_preview")
        return {"rows":rows,"revision":rev,"workshop":w,"count":len(rows)}
def commit_import(store,token,workshop,rid,rows,rev):
    key_id(rid);rows=normalize(rows);raw=encode(rows)
    with store._write() as db:
        _,a=_principal(db,token);w=workshops.resolve(db,a,workshop)
        old=db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?",(w,"import:"+rid)).fetchone()
        if old:
            if old[0]!=raw:raise Conflict("Идентификатор импорта уже использован.")
            return json.loads(old[1])
        if rev!=book.revision(db,w,"import_materials",rows):raise Conflict("Справочник изменился. Повторите предварительный просмотр.")
        ids=apply(db,w,rid,rows);result={"count":len(ids),"ids":ids}
        db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(w,"import:"+rid,raw,encode(result)))
        return result

CALC_UNITS={"шт":("шт",1),"компл":("компл",1),"г":("г",1),"кг":("г",1000),"мл":("мл",1),"л":("мл",1000),"мм":("мм",1),"см":("мм",10),"м":("мм",1000),"см²":("см²",1),"дм²":("см²",100),"м²":("см²",10000)}
def number(v,maximum=10**9,decimals=3):
    if not isinstance(v,str) or not re.fullmatch(r"\d{1,12}(?:[.,]\d{1,"+str(decimals)+r"})?",v):raise ValueError("Укажите неотрицательное число.")
    q=Decimal(v.replace(",","."))
    if q>maximum:raise ValueError("Слишком большое значение.")
    return q
def decimal2(v):return format(v.quantize(Decimal(".01"),rounding=ROUND_HALF_UP),"f")
def calculator(a):
    if not isinstance(a,dict) or set(a)!={"name","items","sale_price","minutes","hourly_rate"}:raise ValueError("Некорректные поля расчёта.")
    name=clean_name(a["name"]);items=a["items"]
    if not isinstance(items,list) or not 1<=len(items)<=50:raise ValueError("От 1 до 50 строк материалов.")
    seen=set();materials=Decimal(0);out=[]
    for row in items:
        if not isinstance(row,dict) or not {"name","quantity","unit","price"}<=row.keys()<={"name","quantity","unit","price","pack_quantity"}:raise ValueError("Некорректная строка материала.")
        n=clean_name(row["name"])
        if n.casefold() in seen:raise ValueError("Объедините повторяющийся материал.")
        seen.add(n.casefold())
        u=row["unit"]
        if not isinstance(u,str) or u not in CALC_UNITS:raise ValueError("Неизвестная единица.")
        qty=number(row["quantity"]);price=Decimal(book.money(book.minor(row["price"])))
        if qty<=0:raise ValueError("Количество должно быть больше нуля.")
        pack=number(row.get("pack_quantity","1"))
        if pack<=0:raise ValueError("Количество в упаковке должно быть больше нуля.")
        value=qty*price/pack;materials+=value
        line={"name":n,"quantity":format(qty,"f"),"unit":u,"price":decimal2(price),"cost_rub":decimal2(value)}
        if "pack_quantity" in row:line["pack_quantity"]=format(pack,"f")
        out.append(line)
    sale=Decimal(book.money(book.minor(a["sale_price"])));minutes=number(a["minutes"],525600,2);hour=Decimal(book.money(book.minor(a["hourly_rate"])))
    labor=minutes*hour/60;gross=sale-materials;full=materials+labor
    return {"name":name,"items":out,"sale_price":decimal2(sale),"minutes":format(minutes,"f"),"hourly_rate":decimal2(hour),
        "materials_rub":decimal2(materials),"labor_rub":decimal2(labor),"full_cost_rub":decimal2(full),"material_profit_rub":decimal2(gross),
        "profit_rub":decimal2(sale-full),"margin_percent":decimal2(gross*100/sale) if sale else None,
        "full_margin_percent":decimal2((sale-full)*100/sale) if sale else None,"markup_percent":decimal2((sale-full)*100/full) if full else None,
        "income_per_hour_rub":decimal2(gross*60/minutes) if minutes else None}
def profit_calculator(args):
    if not isinstance(args,dict) or set(args)!={"revenue","cost","expenses"}:raise ValueError("Некорректные поля расчёта прибыли.")
    revenue,cost,expenses=(Decimal(book.money(book.minor(args[k]))) for k in ("revenue","cost","expenses"))
    gross=revenue-cost;total=cost+expenses;profit=revenue-total
    return {"revenue_rub":decimal2(revenue),"cost_rub":decimal2(cost),"expenses_rub":decimal2(expenses),
            "gross_profit_rub":decimal2(gross),"total_cost_rub":decimal2(total),"profit_rub":decimal2(profit),
            "margin_percent":decimal2(profit*100/revenue) if revenue else None,
            "return_on_cost_percent":decimal2(profit*100/total) if total else None}

def save_calculator(store,token,workshop,rid,args):
    key_id(rid);c=calculator(args)
    raw=encode(args)
    with store._write() as db:
        _,a=_principal(db,token);w=workshops.resolve(db,a,workshop)
        old=db.execute("SELECT args,result FROM pm_mutations WHERE workspace=? AND rid=?",(w,"calculator:"+rid)).fetchone()
        if old:
            if old[0]!=raw:raise Conflict("Идентификатор расчёта уже использован.")
            return json.loads(old[1])
        if db.execute("SELECT 1 FROM pm_products WHERE workspace=? AND normalized=?",(w,c["name"].casefold())).fetchone():
            raise Conflict("Изделие уже существует. Выберите другое название.")
        pid=None
        for i,line in enumerate(c["items"]):
            unit,factor=CALC_UNITS[line["unit"]];usage=Decimal(line["quantity"])*factor
            pack_value=Decimal(line.get("pack_quantity","1"))*factor
            if usage!=usage.to_integral_value() or usage>10**9:raise ValueError("Расход должен выражаться целым числом базовых единиц.")
            if pack_value!=pack_value.to_integral_value() or not 1<=pack_value<=10**9:raise ValueError("Упаковка должна выражаться целым числом базовых единиц.")
            pack=int(pack_value)
            prior=db.execute("SELECT unit,pack,price FROM pm_materials WHERE workspace=? AND normalized=?",(w,line["name"].casefold())).fetchone()
            if prior and (prior[0]!=unit or prior[1]!=pack or prior[2] is None or Decimal(prior[2])!=Decimal(line["price"])):
                raise Conflict("Материал уже есть с другими параметрами: "+line["name"])
            key=hashlib.sha256(encode([rid,i]).encode()).hexdigest()
            result=_save(db,w,"calc-"+key,{"product":c["name"],"material":line["name"],"pack_quantity":pack,"usage_quantity":int(usage),"pack_price":line["price"],"unit":unit})
            pid=result["product_id"]
        minutes=Decimal(c["minutes"])
        if minutes!=minutes.to_integral_value():raise ValueError("При сохранении используйте целые минуты.")
        db.execute("UPDATE pm_products SET sale_price=?,minutes=? WHERE workspace=? AND id=?",(c["sale_price"],int(minutes),w,pid))
        result={"product_id":pid,"name":c["name"],"message":"Изделие и рецептура сохранены. Ставка труда задаётся в настройках мастерской."}
        db.execute("INSERT INTO pm_mutations VALUES(?,?,?,?)",(w,"calculator:"+rid,raw,encode(result)))
        return result
