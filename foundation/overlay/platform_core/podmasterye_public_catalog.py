"""Published product capabilities, independent of plugins and private account data."""
import json,re
from functools import lru_cache
from pathlib import Path

PATH=Path(__file__).with_name("podmasterye_public_catalog.json")
GROUPS=("Возможности","Интеграции")

def normalize(text):
    return " ".join(re.findall(r"[^\W_]+",text.casefold().replace("ё","е")))

@lru_cache(maxsize=1)
def catalog():
    rows=json.loads(PATH.read_text(encoding="utf-8"))
    seen_ids=set();seen_aliases={}
    for r in rows:
        if set(r)!={"id","group","title","overview","aliases","detail","access"} or not re.fullmatch(r"capability/[a-z_]+",r["id"]) or r["group"] not in GROUPS or r["access"]!="member":
            raise ValueError("Invalid public capability")
        if r["id"] in seen_ids or not r["title"] or not r["overview"] or not r["detail"]:raise ValueError("Invalid catalogue entry")
        seen_ids.add(r["id"])
        for a in (r["title"],*r["aliases"]):
            n=normalize(a)
            if not n or (n in seen_aliases and seen_aliases[n]!=r["id"]):raise ValueError("Ambiguous public alias: "+n)
            seen_aliases[n]=r["id"]
    return tuple(rows)

def guest_cards(db):
    # The product catalog is deployment data, never user-private state.
    return catalog()

def card_ids(cards):
    return [c["id"] for c in cards]

def overview(intro,cards):
    if not cards:return intro
    lines=[intro,"", "Что доступно в личном кабинете после регистрации:"]
    for i,c in enumerate(cards,1):
        lines.append(f"{i}. {c['title']} — {c['overview']}.")
    lines+=["","Напишите название или номер пункта, чтобы узнать подробнее. В гостевом чате доступны только справочные ответы о сервисе и точные команды бесплатных калькуляторов."]
    return "\n".join(lines)

def clarify(intro,cards):
    if not cards:return intro
    return intro+"\n\n"+"\n".join(f"{i}. {c['title']}" for i,c in enumerate(cards,1))

def resolve(text,cards,intro,fallback):
    """A direct shortcut requires a whole matching public question, not keywords
    embedded in an arbitrary instruction. Other messages go to the bounded classifier."""
    if not cards:return fallback,False,"scope"
    text=re.sub(r"^(?:а |и |ну )+","",text)
    if text in ("каталог","каталог возможностей","список возможностей","все возможности","покажи возможности","перечисли возможности"):
        return overview(intro,cards),False,"features"
    if text in ("плагины","какие плагины есть","есть ли плагины","какие у тебя плагины"):
        return "В Подмастерье нет подключаемых плагинов. Функции входят в личный кабинет.\n\n"+overview(intro,cards),False,"features"
    if text in ("интеграции","список интеграций","перечисли интеграции","какие интеграции"):
        return "В личном кабинете: "+", ".join(c["title"] for c in cards if c["group"]=="Интеграции")+". Выберите название, чтобы узнать условия подключения.",False,"connections"
    prefixes=("расскажи о ","расскажи про ","подробнее о ","подробнее про ","что такое ","что умеешь в разделе ")
    variants={text}
    for prefix in prefixes:
        if text.startswith(prefix):variants.add(text[len(prefix):])
    matches=[c for c in cards if variants.intersection(normalize(a) for a in (c["title"],*c["aliases"]))]
    if len(matches)==1:
        c=matches[0];return c["detail"],True,c["id"]
    return fallback,False,"scope"
