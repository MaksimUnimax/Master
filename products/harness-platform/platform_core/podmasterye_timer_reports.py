"""Built-in scheduled reports are projections of the existing accounting service.

The registry is intentionally independent of schedules and delivery. Adding a
report does not add a queue, monetary calculator, or model call.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from . import podmasterye_book as book


@dataclass(frozen=True)
class Report:
    id: str
    title: str
    description: str


REPORTS = {r.id: r for r in (
    Report("profit", "Прибыль и расходы", "Выручка, себестоимость и фактическая прибыль за период."),
    Report("sales", "Продажи и выручка", "Продажи по изделиям и каналам за период."),
    Report("stock", "Остатки и дефицит материалов", "Текущие остатки и материалы для пополнения."),
    Report("purchases", "Закупки и потребность", "Закупки за период и текущий план пополнения."),
    Report("production", "Выпуск продукции", "Производственные операции и готовые партии."),
    Report("tasks", "Сроки задач", "Активные задачи, напоминания и просроченные сроки."),
)}
PERIODS = {"today": "Сегодня", "yesterday": "Вчера", "last7": "Последние 7 дней",
           "last30": "Последние 30 дней", "previous_month": "Прошлый месяц", "custom": "Свой период"}
FILTERS = {"products", "materials", "channels", "task_categories"}
REPORT_FILTERS = {"profit": {"products", "channels"}, "sales": {"products", "channels"},
                  "stock": {"materials"}, "purchases": {"materials"},
                  "production": {"products"}, "tasks": {"task_categories"}}


def argument_schema():
    variants = []
    for name in REPORTS:
        filters = {key: {"type": "array", "maxItems": 100,
                         "items": {"type": "string", "minLength": 1, "maxLength": 128}}
                   for key in sorted(REPORT_FILTERS[name])}
        props = {"report": {"const": name}, "period": {"type": "string", "enum": list(PERIODS)},
                 "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
                 "filters": {"type": "object", "properties": filters, "additionalProperties": False},
                 "horizon": {"type": "integer", "minimum": 1, "maximum": 365},
                 "lead": {"type": "integer", "minimum": 0, "maximum": 365},
                 "safety": {"type": "integer", "minimum": 0, "maximum": 365}}
        variants.append({"type": "object", "properties": props, "required": ["report"],
                         "additionalProperties": False,
                         "if": {"properties": {"period": {"const": "custom"}}, "required": ["period"]},
                         "then": {"required": ["from", "to"]},
                         "else": {"not": {"anyOf": [{"required": ["from"]}, {"required": ["to"]}]}}})
    return {"oneOf": variants}


def catalog():
    return [{"id": r.id, "title": r.title, "description": r.description,
             "cost": "0", "periods": list(PERIODS), "filters": sorted(REPORT_FILTERS[r.id])} for r in REPORTS.values()]


def validate(spec):
    if not isinstance(spec, dict) or set(spec) - {"report", "period", "from", "to", "filters", "horizon", "lead", "safety"}:
        raise ValueError("Проверьте параметры отчёта.")
    if (not isinstance(spec.get("report"),str) or spec["report"] not in REPORTS
            or not isinstance(spec.get("period","yesterday"),str) or spec.get("period","yesterday") not in PERIODS):
        raise ValueError("Выберите отчёт и его период.")
    out = {"report": spec["report"], "period": spec.get("period", "yesterday"), "filters": {}}
    if out["period"] == "custom":
        for key in ("from", "to"):
            value = spec.get(key)
            if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError("Для собственного периода укажите обе даты.")
            out[key] = value
        if out["from"] > out["to"]:
            raise ValueError("Начало периода должно быть не позже его окончания.")
    elif "from" in spec or "to" in spec:
        raise ValueError("Даты можно указывать только для собственного периода.")
    filters = spec.get("filters", {})
    if not isinstance(filters, dict) or set(filters) - REPORT_FILTERS[out["report"]]:
        raise ValueError("Неизвестный фильтр отчёта.")
    for key, values in filters.items():
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(x, str) or not 1 <= len(x) <= 128 for x in values):
            raise ValueError("Проверьте значения фильтра отчёта.")
        out["filters"][key] = sorted(set(values))
    for key, default in (("horizon", 30), ("lead", 7), ("safety", 3)):
        value = spec.get(key, default)
        if type(value) is not int or not (1 if key == "horizon" else 0) <= value <= 365:
            raise ValueError("Проверьте горизонт и сроки закупки.")
        out[key] = value
    return out


def period(spec, local_day):
    """Relative days are resolved at the scheduled occurrence in its IANA zone."""
    kind = spec["period"]
    if kind == "custom":
        return spec["from"], spec["to"]
    if kind == "yesterday":
        start = end = local_day - timedelta(days=1)
    elif kind == "previous_month":
        end = local_day.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        end = local_day
        start = end - timedelta(days={"today": 0, "last7": 6, "last30": 29}[kind])
    return start.isoformat(), end.isoformat()


def build(db, workshop, raw, local_day):
    spec = validate(raw)
    start, end = period(spec, local_day)
    # The book's current-stock date is authoritative. A timezone ahead of the
    # accounting day must not silently manufacture future ledger data.
    if end > book.today().isoformat():
        raise ValueError("Период ещё не наступил в учётном календаре. Выберите завершённый день.")
    data = book.report(db, workshop, start=start, end=end, horizon=spec["horizon"],
                       lead=spec["lead"], safety=spec["safety"])
    filters = spec["filters"]
    all_events = book.event_rows(db, workshop, start, end)
    def matches(row):
        return ((not filters.get("products") or row.get("product_id") in filters["products"])
                and (not filters.get("materials") or row.get("material_id") in filters["materials"]
                     or any(x.get("material_id") in filters["materials"] for x in row.get("consumption", [])))
                and (not filters.get("channels") or row.get("channel") in filters["channels"]))
    events = [(row, finance) for row, finance in all_events if matches(row)]
    selected_products = [p for p in data["products"] if not filters.get("products") or p["id"] in filters["products"]]
    selected_materials = [m for m in data["materials"] if not filters.get("materials") or m["id"] in filters["materials"]]
    plans = [p for p in data["planning"] if not filters.get("materials") or p["material_id"] in filters["materials"]]
    summary = book.aggregate(events)
    name = spec["report"]
    result = {"type": name, "title": REPORTS[name].title, "period": {"from": start, "to": end},
              "filters": filters, "costCoins": "0", "stockAsOf": data["today"], "assumptions": data["assumptions"]}
    if filters:
        result["filterNote"] = "Фильтр учитывает записи с явной связью с выбранными объектами. Общие расходы без такой связи не распределяются произвольно."
    if name == "profit":
        result.update(summary=summary, expenses=book.grouped(events, "category"))
    elif name == "sales":
        result.update(summary=summary, by_product=book.grouped(events, "product_id"), by_channel=book.grouped(events, "channel"),
                      quantity=sum(row.get("sales_quantity", 0) for row, _ in events),
                      sales=[s for s in data["sales"] if start <= s["day"] <= end and matches(s)])
    elif name == "stock":
        result.update(materials=selected_materials, products=selected_products,
                      shortage=[p for p in plans if p["buy_quantity"] > 0 or p["order_now"]])
    elif name == "purchases":
        result.update(summary=summary, purchases=[r for r, _ in events if r.get("original_kind", r["kind"]) == "purchase"], planning=plans)
    elif name == "production":
        result.update(operations=[r for r, _ in events if r.get("original_kind", r["kind"]) in
                                 {"manufacture", "work_start", "work_finish", "component_transfer"}],
                      batches=[b for b in data["batches"] if not filters.get("products") or b["product_id"] in filters["products"]])
    else:
        tasks = [t for t in data["tasks"] if t["status"] == "active" and
                 (not filters.get("task_categories") or t["category"] in filters["task_categories"])]
        result.update(tasks=tasks, reminders=[t for t in tasks if t.get("due") and
                      date.fromisoformat(t["due"]) - timedelta(days=t["remind_days"]) <= local_day],
                      overdue=[t for t in tasks if t.get("due") and t["due"] < local_day.isoformat()])
    return result


def render(result):
    """A bounded local summary; complete structured details stay in run history."""
    lines = [result["title"], result["period"]["from"] + " — " + result["period"]["to"]]
    if result.get("filters"):
        lines.append("Применены выбранные фильтры; их состав сохранён в полном результате.")
    name = result["type"]
    summary = result.get("summary", {})
    if name == "profit":
        for key, label in (("revenue", "Выручка"), ("cogs", "Себестоимость продаж"),
                           ("expenses", "Расходы"), ("writeoffs", "Списания"),
                           ("net_profit", "Чистая прибыль"), ("cashflow", "Денежный поток")):
            lines.append(f"{label}: {summary[key]} ₽")
    elif name == "sales":
        lines.extend([f"Продано, с учётом возвратов: {result['quantity']}", f"Выручка: {summary['revenue']} ₽"])
    elif name == "stock":
        lines.append("Остатки на " + result["stockAsOf"])
        lines.extend(f"{m['name']}: {m['quantity']} {m['unit']}" for m in result["materials"][:12])
        lines.append(f"Позиций для пополнения: {len(result['shortage'])}")
    elif name == "purchases":
        lines.extend([f"Закуплено на: {summary['purchases']} ₽", f"Операций закупки: {len(result['purchases'])}",
                      f"Материалов в плане пополнения: {sum(1 for p in result['planning'] if p['buy_quantity'] > 0)}"])
    elif name == "production":
        lines.extend([f"Производственных операций: {len(result['operations'])}", f"Текущих партий: {len(result['batches'])}"])
        lines.extend(str(r.get("summary", r["kind"])) for r in result["operations"][:8])
    elif name == "tasks":
        lines.extend([f"Активных задач: {len(result['tasks'])}", f"Просрочено: {len(result['overdue'])}"])
        lines.extend(f"{t['due']}: {t['name']}" for t in result["reminders"][:12])
    lines.append("Полные данные сохранены в истории таймера. Формирование отчёта — 0 монет.")
    return "\n".join(lines)[:3800]
