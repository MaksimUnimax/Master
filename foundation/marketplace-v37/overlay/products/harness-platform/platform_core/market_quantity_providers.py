"""Pure, restartable quantity adapters for the existing marketplace collector.

``request(id, checkpoint, context)`` describes exactly one authorized read.
``consume(id, checkpoint, context, response)`` validates its result and returns
the next checkpoint plus a minimal quantity projection. Neither function does
network, database, model, billing, sleeping or logging I/O. The existing
collector owns grants, rate permits, leases, receipts and atomic publication.
"""
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import re
import stat
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit
import zipfile
from zoneinfo import ZoneInfo

from .market_quantity_registry import get_template, quota_profile, VERSION
from .marketplace_matrix.document_formats import valid_document

MOSCOW = ZoneInfo("Europe/Moscow")
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
QTY_FIELDS = ("ordered_qty", "delivered_qty", "cancelled_qty", "nonbuyout_qty", "physical_return_qty", "lost_qty")
WB_QUANTITY_FIELDS = ["rrdId", "reportId", "reportType", "dateFrom", "dateTo", "nmId", "vendorCode", "sku",
    "subjectName", "quantity", "docTypeName", "sellerOperName", "orderDt", "saleDt", "rrDate", "srid", "shkId", "orderId"]
OZ_STATES = {"delivered": "delivered", "cancelled": "cancelled", "awaiting_registration": "pending",
    "acceptance_in_progress": "pending", "awaiting_approve": "pending", "awaiting_packaging": "pending",
    "awaiting_deliver": "pending", "arbitration": "pending", "client_arbitration": "pending",
    "delivering": "pending", "driver_pickup": "pending", "not_accepted": "pending", "sent_by_seller": "pending",
    "Доставлен": "delivered", "Отменён": "cancelled", "Отменен": "cancelled", "Доставляется": "pending",
    "Ожидает отгрузки": "pending", "Ожидает сборки": "pending", "Ожидает в ПВЗ": "pending"}


class AdapterError(ValueError):
    def __init__(self, code, safe_message="Площадка не подтвердила полноту количественных данных."):
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


def _need(ok, code="QUANTITY_SCHEMA"):
    if not ok:
        raise AdapterError(code)


def _text(value, *, maximum=1024, empty=False):
    _need(isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
          and (value.isprintable() or empty and value == ""), "QUANTITY_TEXT")
    return value


def _id(value, *, zero=False):
    _need(type(value) in (str, int) and re.fullmatch(r"[0-9]{1,24}", str(value)) is not None, "QUANTITY_ID")
    _need(int(value) >= (0 if zero else 1), "QUANTITY_ID")
    return str(value)


def _report_id(value):
    _text(value, maximum=255)
    _need(re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", value) is not None, "QUANTITY_REPORT_ID")
    return value


def _qty(value, *, zero=True):
    _need(type(value) in (str, int) and re.fullmatch(r"(?:0|[1-9][0-9]{0,12})", str(value)) is not None, "QUANTITY_UNITS")
    n = int(value)
    _need(zero or n > 0, "QUANTITY_UNITS")
    return n


def _oz_total(page):
    # Seller API replaces total with total_items on 2026-12-07. Normalize both
    # wire versions to the existing checkpoint.total; conflicting counts cannot
    # establish complete pagination, even when the preferred field is valid.
    _need(type(page) is dict, "QUANTITY_SCHEMA")
    _need("total_items" in page or "total" in page, "QUANTITY_TOTAL_MISSING")
    total = _qty(page["total_items"] if "total_items" in page else page["total"])
    if "total_items" in page and "total" in page:
        _need(total == _qty(page["total"]), "QUANTITY_TOTAL_CONFLICT")
    return total


def _day(value):
    _need(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "QUANTITY_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise AdapterError("QUANTITY_DATE") from None


def _stamp(value, *, naive_utc=False):
    _text(value)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            _need(naive_utc, "QUANTITY_TIMEZONE")
            result = result.replace(tzinfo=timezone.utc)
        return result.isoformat()
    except (ValueError, TypeError):
        raise AdapterError("QUANTITY_DATE") from None


def _within_period(timestamp, context):
    a, b = _period(context)
    d = datetime.fromisoformat(timestamp).astimezone(MOSCOW).date()
    _need(a <= d <= b, "QUANTITY_ORDER_PERIOD")


def _period(context):
    a, b = _day(context.get("from")), _day(context.get("to"))
    _need(a <= b, "QUANTITY_PERIOD")
    return a, b


def _utc_bounds(context):
    a, b = _period(context)
    start = datetime.combine(a, datetime.min.time(), MOSCOW)
    end = datetime.combine(b + timedelta(days=1), datetime.min.time(), MOSCOW) - timedelta(microseconds=1)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def _now(context):
    value = context.get("now")
    _need(type(value) in (int, float) and value >= 0, "QUANTITY_CLOCK")
    return int(value)


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _checkpoint(template_id, checkpoint, context):
    _need(type(checkpoint) is dict and type(context) is dict, "QUANTITY_CHECKPOINT")
    cp = deepcopy(checkpoint)
    t = get_template(template_id)
    binding = {k: context.get(k) for k in ("provider", "store", "cid", "version", "seller", "client_id",
              "businessId", "campaignId", "from", "to", "month", "scheme", "posting_number", "placementType")}
    binding["template_id"] = template_id
    fingerprint = _hash(binding)
    _need(cp.get("binding", fingerprint) == fingerprint, "QUANTITY_SCOPE_CHANGED")
    cp.setdefault("binding", fingerprint)
    cp.setdefault("schema", "market-quantity-checkpoint/v1")
    _need(cp["schema"] == "market-quantity-checkpoint/v1", "QUANTITY_CHECKPOINT_SCHEMA")
    cp.setdefault("stage", t["initial_stage"])
    if template_id == "OZ-05" and not checkpoint:
        cp["stage"] = str(context.get("scheme", "FBO")).lower()
    if template_id == "YM-06" and not checkpoint and context.get("placementType") in ("FBY", "LAAS"):
        cp["stage"] = "generate"
    if (template_id == "YM-06" and cp["stage"] == "download" and cp.get("report_generation_stage") == "generate_current"
            and "warehouse_scope_single_campaign" not in cp):
        # Upgrade an older saved report checkpoint by rechecking its original
        # warehouse scope. Its ID/link survive; no new report is generated.
        cp["scope_resume_stage"] = "download"
        cp["scope_previous_warehouse_ids"] = list(cp.get("partner_warehouse_ids") or [])
        _need(cp["scope_previous_warehouse_ids"], "QUANTITY_WAREHOUSE_SCOPE")
        _new_stage(cp, "warehouses_current")
        for key in ("warehouse_seen", "warehouse_matches", "warehouse_ambiguous"):
            cp.pop(key, None)
    _need(cp["stage"] in t["stages"], "QUANTITY_STAGE")
    _need(not cp.get("complete"), "QUANTITY_ALREADY_COMPLETE")
    return t, cp


def _grant_url(value, provider):
    _text(value, maximum=8192)
    try:
        u = urlsplit(value)
        roots = (("cdn1.ozone.ru", "cdn2.ozone.ru", "cdn.ozon.ru", "api-seller.ozon.ru", "ir.ozone.ru") if provider == "ozon" else
                 ("storage.yandexcloud.net", "s3.mds.yandex.net", "s3.mdst.yandex.net", "market.yandex.ru", "market.yandex.net",
                  "market-mbi-prod.s3-private.mds.yandex.net"))
        host = u.hostname or ""
        _need(u.scheme == "https" and u.username is None and u.password is None and u.port in (None, 443)
              and not u.fragment and "\\" not in value and not any(ord(c) < 33 for c in value)
              and any(host == x or host.endswith("." + x) for x in roots), "QUANTITY_DOWNLOAD_ORIGIN")
        return value
    except ValueError:
        raise AdapterError("QUANTITY_DOWNLOAD_ORIGIN") from None


def request(template_id, checkpoint, context):
    t, cp = _checkpoint(template_id, checkpoint, context)
    stage = cp["stage"]
    # A report link expires; refresh its known ID, never create a new report.
    if stage == "download" and cp.get("url_expires_at", 2**63) <= _now(context):
        stage = "poll"
    s = t["stages"][stage]
    path = s["path"]
    if path:
        values = {"businessId": _id(context["businessId"]) if "{businessId}" in path else "",
                  "campaignId": _id(context["campaignId"]) if "{campaignId}" in path else "",
                  "report_id": quote(_report_id(cp["report_id"]), safe="") if "{report_id}" in path else ""}
        url = s["origin"] + path.format(**values)
    else:
        url = _grant_url(cp.get("grant_url"), t["provider"])
    body, params = None, {}
    if s["method"] == "POST":
        body = {}
    if template_id == "OZ-02":
        body = ({"filter": {"visibility": "ALL"}, "last_id": cp.get("cursor", ""), "limit": 1000}
                if stage == "list" else {"product_id": cp["pending_ids"]})
    elif template_id == "OZ-03":
        if stage == "generate":
            a, b = _utc_bounds(context)
            body = {"filter": {"processed_at_from": a, "processed_at_to": b,
                    "delivery_schema": [cp.get("scheme", "FBO").lower()]}, "language": "DEFAULT"}
        elif stage == "poll":
            body = {"code": _report_id(cp["report_id"])}
    elif template_id == "OZ-04":
        a, b = _utc_bounds(context)
        body = {"filter": {"logistic_return_date": {"time_from": a, "time_to": b}}, "last_id": cp.get("cursor", 0), "limit": 500}
    elif template_id == "OZ-05":
        body = {"posting_number": _text(context.get("posting_number"), maximum=160),
                "with": {"analytics_data": False, "financial_data": False}}
    elif template_id == "OZ-06":
        a, b = _utc_bounds(context)
        body = {"cursor": cp.get("cursor", ""), "filter": {"since": a, "to": b}, "limit": 100,
                "sort_dir": "ASC", "translit": False, "with": {"analytics_data": False, "financial_data": False, "legal_info": False}}
    elif template_id == "OZ-07":
        body = {"filter": {"visibility": "ALL"}, "limit": 1000, "cursor": cp.get("cursor", "")}
    elif template_id == "WB-02":
        body = {"settings": {"sort": {"ascending": True}, "filter": {"withPhoto": -1},
                "cursor": {"limit": 100, **cp.get("cursor", {})}}}
    elif template_id == "WB-03":
        a, b = _period(context)
        today = datetime.fromtimestamp(_now(context), MOSCOW).date()
        _need(a >= today - timedelta(days=365) and b <= today and (b-a).days < 365, "QUANTITY_HISTORY_BOUND")
        period = {"start": str(a), "end": str(b)}
        # An omitted comparison window can be defaulted outside the available
        # history and rejected by WB even when selectedPeriod itself is valid.
        # We consume only selected quantities, so keep both windows explicit.
        previous_day = str(a - timedelta(days=1))
        body = {"selectedPeriod": period, "pastPeriod": {"start": previous_day, "end": previous_day}, "nmIds": [], "brandNames": [],
                "subjectIds": [], "tagIds": [], "skipDeletedNm": False, "limit": 1000, "offset": cp.get("offset", 0)}
    elif template_id == "WB-04":
        a, b = _period(context)
        _need(a >= date(2024, 1, 29), "QUANTITY_HISTORY_BOUND")
        body = {"dateFrom": str(a), "dateTo": str(b), "period": "weekly", "limit": 100000,
                "rrdId": cp.get("cursor", 0), "fields": WB_QUANTITY_FIELDS}
    elif template_id == "WB-05" and stage == "generate":
        params = {"locale": "ru", "groupByNm": "true", "groupBySa": "true", "groupByBarcode": "true"}
    elif template_id == "YM-01" and stage == "campaigns":
        params = {"limit": 100}
    elif template_id == "YM-02":
        params = {"limit": 100}
        body = {"archived": bool(cp.get("archived", False))}
    elif template_id == "YM-03":
        a, b = _period(context)
        _need((b-a).days < 30, "QUANTITY_PERIOD")
        params = {"limit": 50}
        body = {"campaignIds": [int(_id(context.get("campaignId")))], "fake": False, "sourcePlatforms": ["MARKET"],
                "dates": {"creationDateFrom": str(a), "creationDateTo": str(b+timedelta(days=1))}}
    elif template_id == "YM-04":
        a, b = _period(context)
        params = {"fromDate": str(a), "toDate": str(b), "limit": 100}
    elif template_id == "YM-06" and stage.startswith("warehouses_"):
        _need(context.get("placementType") in ("FBS", "DBS", "EXPRESS"), "QUANTITY_PLACEMENT_UNKNOWN")
        params = {"limit": 30}
        body = {"campaignIds": [int(_id(context.get("campaignId")))]} if stage == "warehouses_legacy" else {}
    elif template_id in ("YM-05", "YM-06") and s["generate"]:
        params = {"format": "CSV"}
        if template_id == "YM-05":
            month = context.get("month") or context.get("from", "")[:7]
            d = _day(month + "-01")
            a, b = _period(context)
            _need(a.strftime("%Y-%m") == month == b.strftime("%Y-%m"), "QUANTITY_REPORT_PERIOD")
            body = {"campaignId": int(_id(context.get("campaignId"))), "year": d.year, "month": d.month}
        elif stage == "generate_current":
            ids = cp.get("partner_warehouse_ids")
            _need(type(ids) is list and ids and cp.get("warehouse_scope_verified"), "QUANTITY_WAREHOUSE_SCOPE")
            body = {"partnerWarehouseIds": [int(_id(x)) for x in ids]}
        elif context.get("placementType") in ("FBY", "LAAS"):
            body = {"campaignId": int(_id(context.get("campaignId")))}
        else:
            _need(cp.get("warehouse_groups_verified") and not cp.get("failed_legacy_report"), "QUANTITY_WAREHOUSE_SCOPE")
            body = {"businessId": int(_id(context.get("businessId"))),
                    "campaignIds": [int(_id(context.get("campaignId")))]}
    if template_id.startswith("YM-") and cp.get("cursor") and (stage in ("campaigns", "list") or stage.startswith("warehouses_")):
        params["pageToken"] = cp["cursor"]
    quota = quota_profile(template_id, stage, context)
    global_quota = deepcopy(quota)
    scopes = [quota]
    if t["provider"] == "ozon":
        global_quota.update(key="ozon:seller-global", min_interval=1, interval=1, scope="seller", documented=True)
        scopes = [global_quota, quota]
    elif t["provider"] == "yandex_market":
        global_quota.update(key="yandex:global", min_interval=0, interval=0, max_concurrency=4)
        scopes = [global_quota, quota]
    elif t["provider"] == "wb" and context.get("token_class") in ("service", "base_with_secret"):
        # The documented service ceiling is shared by all sellers using the
        # same registered service, in addition to seller-local pacing.
        _need(context.get("service_id"), "QUANTITY_SERVICE_SCOPE_REQUIRED")
        global_quota.update(scope="service")
        scopes = [global_quota, quota]
    return {**s, "method": s["method"], "url": url, "json": body, "params": params, "stage": stage,
            "quota_profile": quota, "quota_scopes": scopes, "error_policy": t["error_policy"],
            "timeout": 55, "max_bytes": MAX_FILE_BYTES if s["download"] else 32*1024*1024,
            "response_kind": "bytes" if s["download"] and template_id != "WB-05" else "json"}


def _base(tid, context, sku, basis, natural_key, **values):
    row = {"provider": get_template(tid)["provider"], "store_id": str(context.get("store", context.get("seller", ""))),
           "connection_id": str(context.get("cid", "")), "connection_generation": context.get("version"),
           "sku": _text(str(sku), maximum=255), "category_id": None, "quantity_basis": basis,
           "natural_key": natural_key, "source_id": tid, "schema_version": "market-quantity/v1",
           "observed_at": _now(context), "original_order_known": False, "physical_returns_known": False,
           "terminal": False, "complete": True, **{k: None for k in QTY_FIELDS}}
    row.update(values)
    return row


def _page(cp, rows, cursor, *, complete, cursor_key="cursor", count_rows=True):
    keys = [r["natural_key"] for r in rows]
    _need(len(keys) == len(set(keys)), "QUANTITY_DUPLICATE_ROW")
    digest = _hash(keys)
    if rows:
        seen = cp.setdefault("seen_pages", [])
        _need(digest not in seen, "QUANTITY_DUPLICATE_PAGE")
        seen.append(digest)
    if count_rows:
        cp["row_count"] = cp.get("row_count", 0) + len(rows)
    cp["pages"] = cp.get("pages", 0) + 1
    if not complete:
        _need(cursor not in (None, "", {}, 0), "QUANTITY_MISSING_CURSOR")
        if isinstance(cursor, str):
            _text(cursor, maximum=4096)
        elif type(cursor) is int:
            _id(cursor)
        else:
            _need(type(cursor) is dict and set(cursor) == {"updatedAt", "nmID"}, "QUANTITY_CURSOR_SCHEMA")
            _stamp(cursor["updatedAt"])
            _id(cursor["nmID"], zero=True)
        marker = _hash(cursor)
        seen = cp.setdefault("seen_cursors", [])
        _need(marker not in seen and cursor != cp.get(cursor_key), "QUANTITY_CURSOR_LOOP")
        seen.append(marker)
        cp[cursor_key] = cursor


def _new_stage(cp, stage):
    cp["stage"] = stage
    for key in ("cursor", "seen_cursors", "seen_pages", "offset", "total", "count", "pending_ids", "next_cursor"):
        cp.pop(key, None)


def _result(tid, cp, context, *, rows=None, catalog=None, metadata=None, complete=False, delay=0):
    cp["complete"] = complete
    coverage = {"source_id": tid, "from": context.get("from"), "to": context.get("to"),
                "axis": get_template(tid)["history"]["axis"], "complete": complete,
                "pages": cp.get("pages", 0), "rows": cp.get("row_count", 0),
                "observed_at": _now(context), "zero_confirmed": bool(complete and tid not in ("OZ-01", "WB-01", "YM-01") and not cp.get("row_count", 0))}
    return {"checkpoint": cp, "rows": rows or [], "catalog": catalog or [], "metadata": metadata or {},
            "complete": complete, "next_due": _now(context)+int(delay) if delay else 0,
            "state": "no_data_confirmed" if coverage["zero_confirmed"] else "ready" if complete else "collecting",
            "coverage": coverage}


def _payload(response):
    _need(type(response) is dict, "QUANTITY_RESPONSE")
    status = response.get("status_code", 200)
    _need(type(status) is int and status in (200, 201, 204), "QUANTITY_HTTP_NOT_HANDLED")
    if status == 204:
        return None
    data = response.get("payload")
    if data is None and response.get("content"):
        try:
            data = json.loads(response["content"])
        except (ValueError, TypeError, UnicodeError):
            raise AdapterError("QUANTITY_INVALID_JSON") from None
    _need(type(data) in (dict, list), "QUANTITY_SCHEMA")
    if isinstance(data, dict):
        _need(data.get("status") != "ERROR" and not data.get("error") and not data.get("errors")
              and not ("code" in data and type(data["code"]) is int and data["code"] != 0), "QUANTITY_DOMAIN_ERROR")
    return data


def _catalog(tid, context, raw):
    if tid == "OZ-02":
        skus = {str(_id(x)) for x in [raw.get("sku"), *(s.get("sku") for s in raw.get("sources", []))] if x is not None}
        _need(skus, "QUANTITY_CATALOG_SKU")
        category = raw.get("description_category_id")
        kind = raw.get("type_id")
        cat = f"{_id(category)}.{_id(kind)}" if category is not None and kind is not None else None
        return [{"sku": sku, "id": _id(raw["id"]), "offer_id": _text(raw["offer_id"], maximum=255),
                 "title": _text(raw["name"]), "category_id": cat, "archived": bool(raw.get("is_archived", raw.get("archived", False)))} for sku in sorted(skus)]
    if tid == "WB-02":
        return [{"sku": _id(raw["nmID"]), "id": _id(raw["nmID"]), "offer_id": _text(raw["vendorCode"], maximum=255),
                 "title": _text(raw.get("title") or str(raw["nmID"])), "category_id": _id(raw["subjectID"]), "archived": False}]
    offer = raw["offer"]
    mapping = raw.get("mapping") or {}
    return [{"sku": _text(offer["offerId"], maximum=255), "offer_id": offer["offerId"],
             "market_sku": str(mapping["marketSku"]) if mapping.get("marketSku") is not None else None, "title": _text(offer.get("name") or offer["offerId"]),
             "category_id": str(mapping["marketCategoryId"]) if mapping.get("marketCategoryId") else None,
             "archived": bool(offer.get("archived", False))}]


def _oz_postings(tid, context, postings, scheme):
    result = []
    _need(type(postings) is list, "QUANTITY_POSTINGS")
    for o in postings:
        posting = _text(o["posting_number"], maximum=160)
        status = o["status"]
        _need(status in OZ_STATES, "QUANTITY_ORDER_STATUS")
        state = OZ_STATES[status]
        ordered_at = _stamp(o.get("in_process_at") or o.get("created_at"))
        if tid == "OZ-06":
            _within_period(ordered_at, context)
        products = o["products"]
        _need(type(products) is list and products, "QUANTITY_POSTING_PRODUCTS")
        for item in products:
            sku, quantity = _id(item["sku"]), _qty(item["quantity"], zero=False)
            result.append(_base(tid, context, sku, "order_cohort", f"order:{scheme}:{posting}:{sku}",
                scheme=scheme, posting_number=posting, order_id=str(o.get("order_id") or o.get("order_number") or posting),
                line_id=sku, ordered_at=ordered_at, ordered_qty=quantity, original_order_known=True,
                delivered_qty=quantity if state == "delivered" else 0 if state == "cancelled" else None,
                cancelled_qty=quantity if state == "cancelled" else 0, lost_qty=quantity if state == "cancelled" else None,
                status=state, terminal=state in ("delivered", "cancelled"),
                unresolved_qty=quantity if state == "pending" else 0,
                offer_id=str(item.get("offer_id", "")), name=_text(item.get("name") or sku)))
    return result


def _oz_returns(tid, context, batch):
    result = []
    for r in batch:
        rid, p = _id(r["id"]), r["product"]
        sku, qty = _id(p["sku"]), _qty(p["quantity"], zero=False)
        scheme = _text(r["schema"]).upper()
        _need(scheme in ("FBO", "FBS"), "QUANTITY_RETURN_SCHEME")
        kind = r["type"]
        _need(kind in ("Cancellation", "ClientReturn", "FullReturn", "PartialReturn"), "QUANTITY_RETURN_TYPE")
        posting = _text(r.get("posting_number_key") or r.get("posting_number"), maximum=160)
        units = [_id(e["exemplar_id"]) for e in r["exemplars"]]
        _need(len(units) == len(set(units)) == qty, "QUANTITY_EXEMPLAR_COVERAGE")
        visual = r.get("visual") or {}
        status = (visual.get("status") or {}).get("sys_name")
        physical = kind == "ClientReturn" and status in ("ArrivedAtReturnPlace", "ReceivedBySeller", "ReturnedToOzon", "Utilizing", "Utilized")
        cancelled_return = status in ("Rejected", "CrmRejected", "Cancelled", "CancelledDisputeNotOpen")
        result.append(_base(tid, context, sku, "return_event", f"return:{scheme}:{rid}:{sku}",
            event_id=rid, posting_number=posting, order_id=str(r.get("order_id") or r.get("order_number") or ""),
            scheme=scheme, unit_ids=units, return_type=kind, return_status=status,
            event_date=_stamp(visual["change_moment"]) if visual.get("change_moment") else None,
            event_date_basis="visual_status_change", loss_event_qty=0 if cancelled_return else qty,
            physical_return_qty=qty if physical else 0 if kind == "Cancellation" or cancelled_return else None,
            physical_returns_known=physical or kind == "Cancellation" or cancelled_return,
            nonbuyout_qty=qty if kind in ("FullReturn", "PartialReturn") and not cancelled_return else None,
            terminal=physical or cancelled_return, complete=True))
    return result


def _wb_funnel(tid, context, batch):
    rows = []
    for r in batch:
        p, v = r["product"], r["statistic"]["selected"]
        sku = _id(p["nmId"])
        period = v["period"]
        _need(period == {"start": context["from"], "end": context["to"]}, "QUANTITY_PERIOD_MISMATCH")
        ordered, lost, bought = (_qty(v[k]) for k in ("orderCount", "cancelCount", "buyoutCount"))
        _need(lost <= ordered and bought <= ordered, "QUANTITY_FUNNEL_BALANCE")
        unresolved = max(0, ordered-lost-bought)
        rows.append(_base(tid, context, sku, "funnel_interval", f"funnel:{sku}:{period['start']}:{period['end']}",
            interval_from=period["start"], interval_to=period["end"], ordered_qty=ordered, lost_qty=lost,
            buyout_qty=bought, original_order_known=True, terminal=unresolved == 0, unresolved_qty=unresolved,
            category_id=str(p.get("subjectId")) if p.get("subjectId") else None,
            name=_text(p.get("title") or sku), offer_id=str(p.get("vendorCode", ""))))
    return rows


def _wb_realization(tid, context, batch):
    rows = []
    for r in batch:
        rid = _id(r["rrdId"])
        # Financial adjustments are not quantity sales. Explicitly select the
        # documented sale/return operations; keep no monetary/PII projection.
        operation = r.get("sellerOperName")
        document = r.get("docTypeName")
        if operation not in ("Продажа", "Возврат") or document not in ("Продажа", "Возврат"):
            continue
        _need(operation == document, "QUANTITY_OPERATION_CONFLICT")
        n = _qty(r["quantity"])
        sku = _id(r["nmId"])
        order_dt = _stamp(r["orderDt"]) if r.get("orderDt") else None
        event_dt = r.get("saleDt") or r.get("rrDate")
        if event_dt and len(event_dt) == 10:
            event_dt = str(_day(event_dt))
        elif event_dt:
            event_dt = _stamp(event_dt)
        _need(event_dt is not None, "QUANTITY_EVENT_DATE")
        rows.append(_base(tid, context, sku, "calendar_event", f"realization:{rid}", event_id=rid,
            report_id=_id(r["reportId"]), order_id=_text(str(r.get("srid") or r.get("orderId") or rid)),
            line_id=str(r.get("shkId") or ""), ordered_at=order_dt, event_date=event_dt,
            delivered_qty=n if operation == "Продажа" else 0,
            calendar_return_qty=n if operation == "Возврат" else 0,
            physical_return_qty=None if operation == "Возврат" else 0,
            physical_returns_known=False, terminal=True, operation="delivered" if operation == "Продажа" else "returned",
            offer_id=str(r.get("vendorCode", ""))))
    return rows


def _ym_orders(tid, context, batch):
    rows = []
    unit_states = {"CREATED", "SHIPPED", "CANCELLED", "DELIVERED_TO_BUYER", "LOST", "REJECTED", "RETURNED"}
    for o in batch:
        oid = _id(o["orderId"])
        _need(str(o["campaignId"]) == str(context["campaignId"]) and o.get("fake") is False, "QUANTITY_ORDER_SCOPE")
        _need(o.get("sourcePlatform", "MARKET") == "MARKET", "QUANTITY_ORDER_SOURCE_PLATFORM")
        created = _stamp(o["creationDate"])
        a, b = _period(context)
        day = datetime.fromisoformat(created).astimezone(MOSCOW).date()
        _need(a <= day <= b, "QUANTITY_ORDER_PERIOD")
        _need(type(o["items"]) is list, "QUANTITY_ORDER_ITEMS")
        for i in o["items"]:
            iid, sku, n = _id(i["id"], zero=True), _text(i["offerId"], maximum=255), _qty(i["count"])
            counts = {}
            statuses = i.get("itemStatuses")
            if statuses is not None:
                _need(type(statuses) is list and statuses, "QUANTITY_UNIT_STATUS")
                for s in statuses:
                    _need(s["status"] in unit_states and s["status"] not in counts, "QUANTITY_UNIT_STATUS")
                    counts[s["status"]] = _qty(s["count"])
            proven = bool(statuses is not None and sum(counts.values()) == n)
            delivered = counts.get("DELIVERED_TO_BUYER", 0) + counts.get("RETURNED", 0) if proven else None
            returned = counts.get("RETURNED", 0) if proven else None
            cancelled, nonbuyout = (counts.get("CANCELLED", 0), counts.get("REJECTED", 0)) if proven else (None, None)
            lost = cancelled + nonbuyout + returned + counts.get("LOST", 0) if proven else None
            unresolved = counts.get("CREATED", 0) + counts.get("SHIPPED", 0) if proven else n
            rows.append(_base(tid, context, sku, "order_cohort", f"order:{oid}:{iid}",
                order_id=oid, line_id=iid, ordered_at=created, ordered_qty=n, original_order_known=True,
                delivered_qty=delivered, cancelled_qty=cancelled, nonbuyout_qty=nonbuyout,
                physical_return_qty=returned, lost_qty=lost, physical_returns_known=proven,
                terminal=proven and unresolved == 0, unresolved_qty=unresolved,
                status=str(o.get("status", "UNKNOWN")), unit_statuses=counts,
                name=_text(i.get("offerName") or sku), complete=proven))
    return rows


def _ym_returns(tid, context, batch):
    rows = []
    physical_stages = {"RECEIVED", "IN_TRANSIT", "READY_FOR_PICKUP", "PICKED", "FULFILMENT_RECEIVED",
                       "PREPARED_FOR_UTILIZATION", "UTILIZED", "READY_FOR_EXPROPRIATION", "RECEIVED_FOR_EXPROPRIATION"}
    terminal_stages = {"PICKED", "FULFILMENT_RECEIVED", "UTILIZED", "RECEIVED_FOR_EXPROPRIATION"}
    for r in batch:
        rid, oid, kind = _id(r["id"]), _id(r["orderId"]), r["returnType"]
        _need(kind in ("RETURN", "UNREDEEMED"), "QUANTITY_RETURN_TYPE")
        shipment, refund, fast = r.get("shipmentStatus"), r.get("refundStatus"), r.get("fastReturn", False)
        _need(type(fast) is bool, "QUANTITY_RETURN_FAST_FLAG")
        # ReturnDTO explicitly says fastReturn leaves the goods with the buyer.
        # Refund processing therefore has no unresolved material movement.
        cash_only_return = kind == "RETURN" and fast
        physical = kind == "RETURN" and not fast and shipment in physical_stages
        cancelled = shipment in ("CANCELLED", "EXPIRED") or refund in ("CANCELLED", "REJECTED")
        confirmed = physical or (kind == "UNREDEEMED" and shipment in physical_stages)
        for item in r["items"]:
            sku, n = _text(item["shopSku"], maximum=255), _qty(item["count"])
            rows.append(_base(tid, context, sku, "return_event", f"return:{oid}:{rid}:{sku}",
                event_id=rid, order_id=oid, event_date=_stamp(r["creationDate"]) if r.get("creationDate") else None,
                updated_at=_stamp(r["updateDate"]) if r.get("updateDate") else None, event_date_basis="return_creation",
                return_type=kind, return_status=shipment, fast_return=fast,
                physical_return_qty=n if physical else 0 if fast or cancelled or kind == "UNREDEEMED" else None,
                physical_returns_known=physical or fast or cancelled or kind == "UNREDEEMED",
                nonbuyout_qty=n if kind == "UNREDEEMED" and confirmed else 0 if cancelled or cash_only_return else None,
                loss_event_qty=n if confirmed else 0 if cancelled or cash_only_return else None,
                terminal=cancelled or cash_only_return or shipment in terminal_stages,
                complete=confirmed or cancelled or cash_only_return))
    return rows


def _safe_zip(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES, "QUANTITY_REPORT_SIZE")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        items = archive.infolist()
        _need(items and len(items) <= 50 and sum(i.file_size for i in items) <= MAX_EXPANDED_BYTES, "QUANTITY_ARCHIVE_SIZE")
        names = set()
        for item in items:
            path = PurePosixPath(item.filename)
            _need(not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename
                  and not (item.flag_bits & 1) and not stat.S_ISLNK(item.external_attr >> 16)
                  and item.filename not in names, "QUANTITY_ARCHIVE_PATH")
            names.add(item.filename)
            _need(item.file_size <= MAX_EXPANDED_BYTES and
                  (item.compress_size > 0 or item.file_size == 0) and
                  (item.file_size / max(1, item.compress_size)) <= 1000, "QUANTITY_ARCHIVE_SIZE")
        _need(archive.testzip() is None, "QUANTITY_ARCHIVE_CORRUPT")
        return archive
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        raise AdapterError("QUANTITY_ARCHIVE_CORRUPT") from None


def _csv(raw):
    _need(type(raw) is bytes and len(raw) <= MAX_FILE_BYTES and valid_document("report.csv", raw), "QUANTITY_CSV_INVALID")
    try:
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
        first = text.splitlines()[0]
        delimiter = ";" if ";" in first else "," if "," in first else "\t"
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        _need(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), "QUANTITY_CSV_HEADER")
        records = list(reader)
        _need(all(None not in row and all(v is not None for v in row.values()) for row in records), "QUANTITY_CSV_TRUNCATED")
        return reader.fieldnames, records
    except (UnicodeError, csv.Error, IndexError):
        raise AdapterError("QUANTITY_CSV_INVALID") from None


def _oz_report(tid, cp, context, raw):
    header, values = _csv(raw)
    required = {"Номер отправления", "SKU", "Принят в обработку", "Количество", "Статус"}
    _need(required <= set(header), "QUANTITY_OZON_REPORT_COLUMNS")
    rows = []
    scheme = cp.get("scheme", "FBO")
    for v in values:
        posting, sku, n = _text(v["Номер отправления"], maximum=160), _id(v["SKU"]), _qty(v["Количество"], zero=False)
        status = v["Статус"]
        _need(status in OZ_STATES, "QUANTITY_ORDER_STATUS")
        state = OZ_STATES[status]
        created = _stamp(v["Принят в обработку"], naive_utc=True)
        _within_period(created, context)
        rows.append(_base(tid, context, sku, "order_cohort", f"order:{scheme}:{posting}:{sku}", scheme=scheme,
            posting_number=posting, order_id=v.get("Номер заказа") or posting, line_id=sku,
            ordered_at=created, original_order_known=True, ordered_qty=n, status=state,
            delivered_qty=n if state == "delivered" else 0 if state == "cancelled" else None,
            cancelled_qty=n if state == "cancelled" else 0, lost_qty=n if state == "cancelled" else None,
            terminal=state != "pending", unresolved_qty=n if state == "pending" else 0,
            delivered_at=_stamp(v["Дата доставки"], naive_utc=True) if v.get("Дата доставки") else None,
            offer_id=v.get("Артикул", ""), name=v.get("Название товара") or sku))
    return rows


def _ym_realization(tid, context, raw):
    # Reuse the accepted v35/v36 quantity-only CSV contract. Additional archive
    # checks apply before the existing parser, without changing its accounting.
    with _safe_zip(raw):
        pass
    from .podmasterye_yandex_sales import parse_report
    month = context.get("month") or context["from"][:7]
    try:
        parsed = parse_report(raw, month, "\x00")
    except Exception:
        raise AdapterError("QUANTITY_YANDEX_REPORT_SCHEMA") from None
    rows = []
    for r in parsed["rows"]:
        kind, oid, sku = r["kind"], r["orderId"], r["sku"]
        rows.append(_base(tid, context, sku, "calendar_event", f"realization:{month}:{kind}:{oid}:{sku}:{r['date']}",
            order_id=oid, event_date=r["date"], operation=kind, name=r["name"],
            delivered_qty=r.get("delivered", 0), physical_return_qty=r.get("returned", 0),
            nonbuyout_qty=r.get("unredeemed", 0), physical_returns_known=True, terminal=True))
    return rows


def _ym_stocks(tid, context, raw, checkpoint=None):
    checkpoint = checkpoint or {}
    current = checkpoint.get("report_generation_stage") == "generate_current"
    rows = []
    with _safe_zip(raw) as archive:
        known = {"stocks_on_warehouses.csv": ("SHOP_SKU", "VALID", "WAREHOUSE"),
                 "stocks_business.csv": ("SHOP_SKU", "COUNT", "WAREHOUSE_AND_SHOP"),
                 "mass_shared_stocks.csv": ("SHOP_SKU", "COUNT", None)}
        matched = 0
        for info in archive.infolist():
            name = PurePosixPath(info.filename).name
            if current:
                if PurePosixPath(name).suffix.lower() != ".csv":
                    continue
                header, values = _csv(archive.read(info))
                # The current v3 API's live CSV uses WAREHOUSE and no placement
                # column; the published reference still shows the older
                # stocks_business layout. Recognize these precise quantity
                # signatures, never a guessed filename or a foreign sheet.
                _need({"SHOP_SKU", "COUNT", "RESERVE", "ERRORS", "PRODUCT_NAME"} <= set(header), "QUANTITY_STOCK_COLUMNS")
                warehouse_columns = {"WAREHOUSE", "WAREHOUSE_AND_SHOP"} & set(header)
                _need(len(warehouse_columns) == 1, "QUANTITY_STOCK_SCOPE_COLUMNS")
                sku_col, qty_col, warehouse_col = "SHOP_SKU", "COUNT", next(iter(warehouse_columns))
                _need("PLACEMENT_TYPE" in header or checkpoint.get("warehouse_scope_single_campaign"), "QUANTITY_STOCK_SCOPE_COLUMNS")
                name = "stocks_current"
            else:
                if name not in known:
                    continue
                sku_col, qty_col, warehouse_col = known[name]
                header, values = _csv(archive.read(info))
            matched += 1
            _need({sku_col, qty_col} <= set(header), "QUANTITY_STOCK_COLUMNS")
            for r in values:
                _need(not r.get("ERRORS"), "QUANTITY_STOCK_ERROR")
                if current and "PLACEMENT_TYPE" in header:
                    placement = {"FBS": "FBS", "DBS": "DBS", "EXPRESS": "EXPRESS", "Экспресс": "EXPRESS"}.get(r["PLACEMENT_TYPE"])
                    _need(placement is not None, "QUANTITY_STOCK_PLACEMENT")
                    if placement != context.get("placementType"):
                        continue
                sku = _text(r[sku_col], maximum=255)
                warehouse = r.get(warehouse_col, "shared") if warehouse_col else "shared"
                rows.append(_base(tid, context, sku, "stock_snapshot", f"stock:{name}:{warehouse}:{sku}",
                    stock_qty=_qty(r[qty_col]), reserved_qty=_qty(r.get("RESERVE") or r.get("RESERVED")) if r.get("RESERVE") or r.get("RESERVED") else 0,
                    stock_kind="physical_valid" if name == "stocks_on_warehouses.csv" else "available",
                    available_qty=_qty(r["AVAILABLE_FOR_ORDER"]) if r.get("AVAILABLE_FOR_ORDER") else (_qty(r[qty_col]) if name != "stocks_on_warehouses.csv" else None),
                    warehouse=warehouse, name=r.get("PRODUCT_NAME") or sku, terminal=True))
        _need(matched == 1, "QUANTITY_STOCK_SHEET")
    return rows


def _ym_warehouse_consume(cp, context, data, stage):
    """Resolve the actual stock-report API without conflating campaigns.

    Current warehouses bind a model to a campaign explicitly; missing campaign
    IDs never mean the only store we happen to have connected. The group API is
    a separately scoped fallback, not an interpretation of warehouse names.
    """
    result = data["result"]
    batch = result["warehouses"]
    _need(type(batch) is list and len(batch) <= 30, "QUANTITY_WAREHOUSE_SCHEMA")
    campaign = _id(context.get("campaignId"))
    placement = context.get("placementType")
    _need(placement in ("FBS", "DBS", "EXPRESS"), "QUANTITY_PLACEMENT_UNKNOWN")
    seen = cp.setdefault("warehouse_seen", [])
    matches = cp.setdefault("warehouse_matches", [])
    ambiguous = cp.setdefault("warehouse_ambiguous", [])
    page_ids = []
    for warehouse in batch:
        wid = _id(warehouse["id"])
        _need(wid not in seen, "QUANTITY_DUPLICATE_WAREHOUSE")
        seen.append(wid)
        page_ids.append({"natural_key": wid})
        if stage == "warehouses_current":
            models = warehouse["models"]
            _need(type(models) is list and all(type(x) is dict for x in models), "QUANTITY_WAREHOUSE_SCHEMA")
            candidates = [m for m in models if m.get("placementType") == placement]
            _need(all(m.get("placementType") in ("FBS", "DBS", "EXPRESS") for m in models), "QUANTITY_PLACEMENT_UNKNOWN")
            if any(m.get("campaignId") is None for m in candidates):
                ambiguous.append(wid)
            associated = {_id(m["campaignId"]) for m in candidates if m.get("campaignId") is not None}
            if campaign in associated:
                _need(len(associated) == 1 and wid not in ambiguous, "QUANTITY_WAREHOUSE_SCOPE_AMBIGUOUS")
                matches.append(wid)
                single = all(m.get("campaignId") is not None and _id(m["campaignId"]) == campaign for m in models)
                cp["warehouse_scope_single_campaign"] = cp.get("warehouse_scope_single_campaign", True) and single
        else:
            _need(_id(warehouse["campaignId"]) == campaign, "QUANTITY_WAREHOUSE_SCOPE")
            group = warehouse.get("groupInfo")
            if type(group) is dict and group.get("id") is not None:
                _id(group["id"])
                matches.append(wid)
            else:
                ambiguous.append(wid)
    cursor = (result.get("paging") or {}).get("nextPageToken")
    _page(cp, page_ids, cursor, complete=not cursor, count_rows=False)
    if cursor:
        return _result("YM-06", cp, context)
    if stage == "warehouses_current" and matches and not ambiguous:
        previous = cp.get("scope_previous_warehouse_ids")
        if cp.get("scope_resume_stage"):
            _need(set(previous or []) == set(matches) and cp["scope_resume_stage"] == "download"
                  and cp.get("report_id"), "QUANTITY_WAREHOUSE_SCOPE_CHANGED")
        cp["partner_warehouse_ids"] = sorted(matches, key=int)
        cp["warehouse_scope_verified"] = True
        _new_stage(cp, cp.pop("scope_resume_stage", "generate_current"))
        cp.pop("scope_previous_warehouse_ids", None)
    elif stage == "warehouses_current":
        _need(not cp.get("scope_resume_stage"), "QUANTITY_WAREHOUSE_SCOPE_CHANGED")
        # The current endpoint does not prove membership of warehouse groups.
        # Ask the documented campaign-filtered group endpoint before selecting
        # its older report. An empty discovery is never a zero-stock proof.
        cp["current_warehouse_discovery"] = {"matched": matches[:], "ambiguous": ambiguous[:]}
        for key in ("warehouse_seen", "warehouse_matches", "warehouse_ambiguous"):
            cp.pop(key, None)
        _new_stage(cp, "warehouses_legacy")
    else:
        _need(matches and not ambiguous, "QUANTITY_WAREHOUSE_SCOPE_AMBIGUOUS")
        _need(not cp.get("failed_legacy_report"), "QUANTITY_REPORT_FAILED")
        cp["warehouse_groups_verified"] = True
        cp["partner_warehouse_ids"] = sorted(matches, key=int)
        _new_stage(cp, "generate")
    return _result("YM-06", cp, context)


def _report_consume(tid, cp, context, response, data, stage):
    if get_template(tid)["stages"][stage]["generate"]:
        if tid == "WB-05":
            rid = data["data"]["taskId"]
        elif tid.startswith("YM-"):
            rid = data["result"]["reportId"]
        else:
            rid = data.get("result", data)["code"]
        cp["report_id"] = _report_id(rid)
        cp["report_generation_stage"] = stage
        cp["stage"] = "poll"
        cp["report_generated_at"] = _now(context)
        return _result(tid, cp, context, delay=5)
    if stage == "poll":
        cp["stage"] = "poll"
        result = data["data"] if tid == "WB-05" else data["result"]
        if tid == "WB-05":
            _need(str(result["id"]) == cp["report_id"], "QUANTITY_REPORT_ID_MISMATCH")
        elif tid == "OZ-03" and result.get("code") is not None:
            _need(result["code"] == cp["report_id"], "QUANTITY_REPORT_ID_MISMATCH")
        status = result["status"]
        if status in ("PENDING", "PROCESSING", "pending", "processing", "waiting", "new", "in_progress"):
            return _result(tid, cp, context, delay=5 if tid == "WB-05" else 10)
        if tid.startswith("YM-") and status in ("DONE", "FAILED") and result.get("subStatus") == "NO_DATA":
            # This is an explicit terminal statement for the previously issued
            # scoped request. A bare DONE or a pending NO_DATA is not evidence.
            if tid == "YM-05":
                a, b = _period(context)
                month = context.get("month") or str(a)[:7]
                _need(str(a)[:7] == month == str(b)[:7], "QUANTITY_REPORT_PERIOD")
            else:
                _need(context.get("placementType") in ("FBY", "LAAS") or cp.get("warehouse_scope_verified")
                      or cp.get("warehouse_groups_verified"), "QUANTITY_WAREHOUSE_SCOPE")
            return _result(tid, cp, context, complete=True, metadata={"provider_no_data": True,
                "provider_terminal_status": status, "provider_terminal_substatus": "NO_DATA"})
        if (tid == "YM-06" and status == "FAILED" and cp.get("report_generation_stage", "generate") == "generate"
                and context.get("placementType") in ("FBS", "DBS", "EXPRESS")
                and not cp.get("warehouse_groups_verified") and not cp.get("failed_legacy_report")):
            # Migration of a checkpoint created by the obsolete unconditional
            # FBS report route. The failure is known, not an ambiguous generate.
            # Keep that ID permanently and discover the alternative contract;
            # the same legacy generation can never be submitted again here.
            cp["failed_legacy_report"] = {"id": cp.pop("report_id"), "status": "FAILED", "observed_at": _now(context)}
            cp.pop("grant_url", None)
            cp.pop("url_expires_at", None)
            _new_stage(cp, "warehouses_current")
            return _result(tid, cp, context)
        _need(status in ("DONE", "done", "success"), "QUANTITY_REPORT_FAILED")
        cp["stage"] = "download"
        if tid != "WB-05":
            cp["grant_url"] = _grant_url(result["file"], get_template(tid)["provider"])
            cp["url_expires_at"] = _now(context) + 3600
            if tid == "OZ-03" and result.get("expires_at"):
                cp["url_expires_at"] = int(datetime.fromisoformat(_stamp(result["expires_at"])).timestamp())
                _need(cp["url_expires_at"] > _now(context), "QUANTITY_REPORT_EXPIRED")
        return _result(tid, cp, context)
    if tid == "WB-05":
        if response.get("status_code") == 204:
            batch = []
        else:
            _need(type(data) is list, "QUANTITY_STOCK_SCHEMA")
            batch = data
        rows = []
        for r in batch:
            sku = _id(r["nmId"])
            barcode = _text(str(r.get("barcode") or ""), maximum=255, empty=True)
            _need(type(r["warehouses"]) is list, "QUANTITY_STOCK_SCHEMA")
            for w in r["warehouses"]:
                warehouse = _text(w["warehouseName"])
                # Summary and transit lines are separate from physical stock;
                # they must never be summed again with individual warehouses.
                kind = "in_transit" if warehouse in ("В пути до получателей", "В пути возвраты на склад WB", "To the client", "From the client") else "aggregate" if warehouse in ("Всего находится на складах", "Total in warehouses") else "warehouse"
                rows.append(_base(tid, context, sku, "stock_snapshot", f"stock:{sku}:{barcode}:{warehouse}",
                    stock_qty=_qty(w["quantity"]), barcode=barcode, warehouse=warehouse, stock_kind=kind, terminal=True))
    else:
        raw = response.get("content")
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES, "QUANTITY_REPORT_SIZE")
        rows = _oz_report(tid, cp, context, raw) if tid == "OZ-03" else _ym_realization(tid, context, raw) if tid == "YM-05" else _ym_stocks(tid, context, raw, cp)
    _page(cp, rows, None, complete=True)
    cp.pop("grant_url", None)
    cp.pop("url_expires_at", None)
    if tid == "OZ-03" and cp.get("scheme", "FBO") == "FBO":
        cp["scheme"] = "FBS"
        cp.setdefault("completed_reports", []).append(cp.pop("report_id"))
        _new_stage(cp, "generate")
        return _result(tid, cp, context, rows=rows)
    return _result(tid, cp, context, rows=rows, complete=True)


def consume(template_id, checkpoint, context, response):
    """Consume one successful response. HTTP failures stay in the shared executor."""
    try:
        return _consume(template_id, checkpoint, context, response)
    except AdapterError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, IndexError):
        raise AdapterError("QUANTITY_SCHEMA") from None


def _consume(tid, checkpoint, context, response):
    t, cp = _checkpoint(tid, checkpoint, context)
    req = request(tid, cp, context)
    stage = req["stage"]
    cp["stage"] = stage
    if stage == "download" and tid != "WB-05":
        _need(response.get("status_code", 200) == 200, "QUANTITY_HTTP_NOT_HANDLED")
        data = None
    else:
        data = _payload(response)
    if tid == "YM-06" and stage.startswith("warehouses_"):
        return _ym_warehouse_consume(cp, context, data, stage)
    if any(s["generate"] for s in t["stages"].values()):
        return _report_consume(tid, cp, context, response, data, stage)
    if tid == "OZ-01":
        roles = data["roles"]
        _need(type(roles) is list and all(type(r) in (dict, str) for r in roles), "QUANTITY_IDENTITY_SCHEMA")
        scopes = sorted({_text(r) if isinstance(r, str) else _text(r.get("name") or r.get("role")) for r in roles})
        seller = _id(context.get("seller") or context.get("client_id"))
        return _result(tid, cp, context, complete=True, metadata={"seller": seller, "scopes": scopes, "campaigns": []})
    if tid == "WB-01":
        seller = _text(data["sid"], maximum=128)
        _need(re.fullmatch(r"[A-Za-z0-9_-]{8,128}", seller), "QUANTITY_SELLER_ID")
        return _result(tid, cp, context, complete=True, metadata={"seller": seller, "scopes": [], "campaigns": []})
    if tid == "YM-01" and stage == "identity":
        scopes = data["result"]["apiKey"]["authScopes"]
        _need(type(scopes) is list and scopes and all(type(s) is str for s in scopes), "QUANTITY_IDENTITY_SCOPE")
        cp["scopes"] = sorted(set(scopes))
        cp["stage"] = "campaigns"
        return _result(tid, cp, context)
    if tid == "YM-01":
        batch = data["campaigns"]
        _need(type(batch) is list and len(batch) <= 100, "QUANTITY_CAMPAIGN_SCHEMA")
        campaigns = []
        for r in batch:
            campaigns.append({"campaignId": int(_id(r["id"])), "businessId": int(_id(r["business"]["id"])),
                "placementType": _text(r.get("placementType", "UNKNOWN")), "apiAvailability": _text(r.get("apiAvailability", "UNKNOWN")),
                "name": _text(r.get("domain") or str(r["id"]))})
        cursor = (data.get("paging") or {}).get("nextPageToken")
        _page(cp, [{"natural_key": str(c["campaignId"])} for c in campaigns], cursor, complete=not cursor)
        cp.setdefault("campaigns", []).extend(campaigns)
        all_campaigns = cp["campaigns"]
        _need(len({c["campaignId"] for c in all_campaigns}) == len(all_campaigns), "QUANTITY_DUPLICATE_CAMPAIGN")
        businesses = {c["businessId"] for c in all_campaigns}
        _need(len(businesses) <= 1, "QUANTITY_TOKEN_BUSINESS_SCOPE")
        return _result(tid, cp, context, complete=not cursor, metadata={"seller": str(next(iter(businesses))) if businesses else None,
                "scopes": cp["scopes"], "campaigns": all_campaigns})
    if tid == "OZ-02":
        if stage == "list":
            page = data["result"]
            batch, total = page["items"], _oz_total(page)
            _need(type(batch) is list and len(batch) <= 1000 and cp.get("total", total) == total, "QUANTITY_TOTAL_CHANGED")
            cp["total"] = total
            ids = [_id(r["product_id"]) for r in batch]
            _need(len(ids) == len(set(ids)), "QUANTITY_DUPLICATE_PRODUCT")
            cp["count"] = cp.get("count", 0) + len(ids)
            _need(cp["count"] <= total and (ids or total == cp["count"]), "QUANTITY_CATALOG_INCOMPLETE")
            cp["pending_ids"], cp["next_cursor"] = ids, page.get("last_id", "")
            if not ids:
                return _result(tid, cp, context, complete=True)
            cp["stage"] = "details"
            return _result(tid, cp, context)
        batch = data["items"]
        _need(type(batch) is list and len(batch) == len(cp["pending_ids"])
              and {_id(r["id"]) for r in batch} == set(cp["pending_ids"]), "QUANTITY_CATALOG_DETAILS")
        cards = [c for r in batch for c in _catalog(tid, context, r)]
        complete = cp["count"] == cp["total"]
        _page(cp, [{"natural_key": c["sku"]} for c in cards], cp["next_cursor"], complete=complete)
        cp["stage"] = "list"
        cp.pop("pending_ids", None)
        return _result(tid, cp, context, catalog=cards, complete=complete)
    if tid == "WB-02":
        batch, paging = data["cards"], data["cursor"]
        _need(type(batch) is list and len(batch) <= 100 and _qty(paging["total"]) == len(batch), "QUANTITY_CATALOG_COUNT")
        cards = [c for r in batch for c in _catalog(tid, context, r)]
        done = paging["total"] < 100
        cursor = {"updatedAt": _stamp(paging["updatedAt"]), "nmID": int(_id(paging["nmID"], zero=True))} if not done else None
        _page(cp, [{"natural_key": c["sku"]} for c in cards], cursor, complete=done)
        return _result(tid, cp, context, catalog=cards, complete=done)
    if tid == "YM-02":
        result = data["result"]
        batch = result["offerMappings"]
        _need(type(batch) is list and len(batch) <= 100, "QUANTITY_CATALOG_SCHEMA")
        cards = [c for r in batch for c in _catalog(tid, context, r)]
        for c in cards:
            c["archived"] = bool(cp.get("archived", False))
        cursor = (result.get("paging") or {}).get("nextPageToken")
        _page(cp, [{"natural_key": c["sku"]} for c in cards], cursor, complete=not cursor)
        done = not cursor and cp.get("archived", False)
        if not cursor and not cp.get("archived", False):
            _new_stage(cp, "list")
            cp["archived"] = True
        return _result(tid, cp, context, catalog=cards, complete=done)
    if tid in ("OZ-05", "OZ-06"):
        if tid == "OZ-05":
            posting = data.get("result", data)
            _need(posting["posting_number"] == context["posting_number"], "QUANTITY_POSTING_ID_MISMATCH")
            rows = _oz_postings(tid, context, [posting], stage.upper())
            _page(cp, rows, None, complete=True)
            return _result(tid, cp, context, rows=rows, complete=True)
        _need(type(data) is dict and "postings" in data and type(data.get("has_next")) is bool, "QUANTITY_POSTINGS_SCHEMA")
        rows = _oz_postings(tid, context, data["postings"], stage.upper())
        done = not data["has_next"]
        _page(cp, rows, data.get("cursor"), complete=done)
        complete = done and stage == "fbs"
        if done and stage == "fbo":
            _new_stage(cp, "fbs")
        return _result(tid, cp, context, rows=rows, complete=complete)
    if tid == "OZ-04":
        _need(type(data["returns"]) is list and type(data["has_next"]) is bool, "QUANTITY_RETURNS_SCHEMA")
        rows = _oz_returns(tid, context, data["returns"])
        cursor = int(_id(data["returns"][-1]["id"])) if data["returns"] else None
        _page(cp, rows, cursor, complete=not data["has_next"])
        return _result(tid, cp, context, rows=rows, complete=not data["has_next"])
    if tid == "OZ-07":
        batch, total = data["items"], _oz_total(data)
        _need(type(batch) is list and cp.get("total", total) == total, "QUANTITY_STOCK_TOTAL")
        cp["total"] = total
        cp["count"] = cp.get("count", 0) + len(batch)
        _need(cp["count"] <= total and (batch or cp["count"] == total), "QUANTITY_STOCK_INCOMPLETE")
        rows = []
        for r in batch:
            _need(type(r["stocks"]) is list and r["stocks"], "QUANTITY_STOCK_SKU_MISSING")
            for stock in r["stocks"]:
                sku = _id(stock["sku"])
                typ = _text(stock["type"])
                rows.append(_base(tid, context, sku, "stock_snapshot", f"stock:{r['product_id']}:{sku}:{typ}",
                    stock_qty=_qty(stock["present"]), reserved_qty=_qty(stock["reserved"]),
                    stock_kind=typ, offer_id=_text(r["offer_id"], maximum=255), terminal=True))
        done = cp["count"] == total
        _page(cp, rows, data.get("cursor"), complete=done)
        return _result(tid, cp, context, rows=rows, complete=done)
    if tid == "WB-03":
        batch = data["data"]["products"]
        _need(type(batch) is list and len(batch) <= 1000, "QUANTITY_FUNNEL_SCHEMA")
        rows = _wb_funnel(tid, context, batch)
        done = len(batch) < 1000
        offset = cp.get("offset", 0) + len(batch)
        _page(cp, rows, offset, complete=done, cursor_key="offset")
        return _result(tid, cp, context, rows=rows, complete=done)
    if tid == "WB-04":
        if response.get("status_code") == 204:
            return _result(tid, cp, context, complete=True)
        _need(type(data) is list and data, "QUANTITY_FINANCE_TERMINAL_204_REQUIRED")
        ids = [int(_id(r["rrdId"])) for r in data]
        _need(len(ids) == len(set(ids)) and min(ids) > cp.get("cursor", 0) and ids == sorted(ids), "QUANTITY_FINANCE_CURSOR")
        rows = _wb_realization(tid, context, data)
        _page(cp, rows, ids[-1], complete=False)
        return _result(tid, cp, context, rows=rows)
    if tid in ("YM-03", "YM-04"):
        result = data if tid == "YM-03" else data["result"]
        batch = result["orders"] if tid == "YM-03" else result["returns"]
        _need(type(batch) is list and len(batch) <= (50 if tid == "YM-03" else 100), "QUANTITY_PAGE_SIZE")
        rows = _ym_orders(tid, context, batch) if tid == "YM-03" else _ym_returns(tid, context, batch)
        cursor = (result.get("paging") or {}).get("nextPageToken")
        _page(cp, rows, cursor, complete=not cursor)
        return _result(tid, cp, context, rows=rows, complete=not cursor)
    raise AdapterError("QUANTITY_TEMPLATE_NOT_IMPLEMENTED")
