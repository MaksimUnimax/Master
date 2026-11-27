"""Guest calculator commands: fixed templates and typed actions, never model-generated."""
from functools import lru_cache
from pathlib import Path
import json,re
from . import podmasterye_import as calc
from .podmasterye_domain import clean_name
from .podmasterye_book import minor,money

SCHEMA="""CREATE TABLE IF NOT EXISTS guest_calculator_actions(
 chat TEXT NOT NULL, request TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(chat,request), FOREIGN KEY(chat,request) REFERENCES guest_turns(chat_id,request_id) ON DELETE CASCADE)"""
@lru_cache(maxsize=1)
def matrix():
    rows=json.loads(Path(__file__).with_name("podmasterye_guest_calculator_matrix.json").read_text())
    assert len({r["id"] for r in rows})==len(rows)
    for r in rows:
        assert r["panel"] in ("calculator","profit")
        assert r["action"] in ("open","help","set","material","remove","calculate")
        for p in r["patterns"]:re.compile(p,re.I)
    return tuple(rows)

def match(message):
    text=message.strip()
    text=re.sub(r"^(?:пожалуйста|подскажи(?:те)?|скажи(?:те)?)[, ]+", "",text,flags=re.I)
    text=re.sub(r"[, ]+пожалуйста[.!?]?$","",text,flags=re.I).rstrip("!?").strip()
    for r in matrix():
        m=next((m for p in r["patterns"] if (m:=re.fullmatch(p,text,re.I))),None)
        if not m:
            m=next((m for p in r["patterns"] if (m:=re.fullmatch(p,text.rstrip(".").strip(),re.I))),None)
        if not m:continue
        data=m.groupdict()
        a={"panel":r["panel"],"action":r["action"],"template":r["id"]}
        try:
            if r["action"]=="set":
                f=r["field"];v=data["value"].strip()
                if f=="product_name":v=clean_name(v)
                elif f=="minutes":v=format(calc.number(v,525600,2),"f")
                else:v=money(minor(v))
                a.update(field=f,value=v)
            elif r["action"]=="material":
                name=clean_name(data["name"]);unit=data["unit"].lower()
                q=calc.number(data["quantity"]);pack=calc.number(data.get("pack_quantity") or "1")
                if q<=0 or pack<=0 or unit not in calc.CALC_UNITS:raise ValueError("Упаковка и расход должны быть больше нуля.")
                a["item"]={"name":name,"quantity":format(q,"f"),"unit":unit,"price":money(minor(data["price"])),"pack_quantity":format(pack,"f")}
            elif r["action"]=="remove":a["name"]=clean_name(data["name"])
        except ValueError as e:
            return ("Проверьте данные: "+str(e)+" Заполните форму справа или воспользуйтесь инструкцией.",None)
        return r["reply"],a
    # Calculator-related free-form instructions must not invoke a paid selector
    # or perform approximate field extraction. Only exact templates may mutate.
    if re.search(r"\b(?:калькулятор\w*|рассчитай\w*|посчитай\w*|материал\s*:|изделие\s*:|цена продажи\s*:|стоимость часа\s*:|себестоимость продаж\s*:|выручка\s*:|прочие расходы\s*:|время(?: изготовления)?\s*:)",text,re.I):
        return ("Для бесплатного расчёта используйте форму или точные команды из инструкции: «Открой калькулятор себестоимости», «Как пользоваться калькулятором», «Открой калькулятор прибыли». Сложные задачи и учёт мастерской доступны после регистрации.",None)
    return None

def remember(db,chat,rid,action):
    if action is not None:
        db.execute("INSERT INTO guest_calculator_actions VALUES(?,?,?)",(chat,rid,json.dumps(action,ensure_ascii=False,separators=(",",":"))))

def attach(db,chat,rows):
    if not rows:return rows
    actions=dict(db.execute("SELECT request,payload FROM guest_calculator_actions WHERE chat=?",(chat,)))
    for row in rows:
        if row["requestId"] in actions:row["calculatorAction"]=json.loads(actions[row["requestId"]])
    return rows
