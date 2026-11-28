#!/usr/bin/env python3
"""Bounded REAL provider reads through the production quantity Backend.

Run only against an isolated, encrypted private-live copy prepared on Alisa.
The program never opens a production database, starts a background Collector,
changes credentials, sends messages, calls a model, or replaces API responses.
HTTP budgets limit acceptance work; they never shorten durable quota deadlines.
"""
import argparse
import asyncio
from collections import Counter
import codecs
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from platform_core.identity import IdentityStore
from platform_core import podmasterye_domain as domain
from platform_core.podmasterye_market_links import Store
from platform_core import market_quantity as q
from platform_core import market_quantity_registry as registry
from platform_core.market_quantity_runtime import Backend


SCHEMA = "market-quantity-live-evidence/v1"
ALL_IDS = {t["id"] for t in registry.templates()}
STOPPED = {"partial", "denied", "needs_attention", "uncertain", "stopped"}
SHAPE_KEYS = frozenset("""result data status errors error code roles name methods role sid campaigns business id apiKey authScopes
offerMappings offer offerId archived mapping marketSku marketCategoryId paging nextPageToken orders orderId campaignId
creationDate updateDate fake items count itemStatuses offerName products sku quantity posting_number order_id order_number
in_process_at created_at has_next cursor total last_id product_id offer_id sources description_category_id type_id
returns product schema type exemplars exemplar_id visual change_moment sys_name stocks present reserved nmID nmId vendorCode
subjectID subjectId title cards updatedAt selected statistic period start end orderCount cancelCount buyoutCount rrdId reportId
reportType dateFrom dateTo docTypeName sellerOperName orderDt saleDt rrDate srid shkId warehouses warehouseName taskId subStatus
file expires_at estimatedGenerationTime returnType shipmentStatus refundStatus fastReturn shopSku instances apiAvailability
placementType domain financeCount models groupInfo sourcePlatform""".split())
KNOWN_REPORTS = {"delivered.csv", "returned.csv", "unredeemed.csv", "stocks_on_warehouses.csv", "stocks_business.csv", "mass_shared_stocks.csv"}
REPORT_ENUMS = {"PENDING", "PROCESSING", "FAILED", "DONE", "NO_DATA", "TOO_LARGE", "RESOURCE_NOT_FOUND",
                "waiting", "processing", "success", "failed", "done", "new", "in_progress", "purged", "canceled"}
QUANTITY_COLUMNS = {"Номер отправления", "Номер заказа", "SKU", "Принят в обработку", "Количество", "Статус",
    "Артикул", "Название товара", "Дата доставки", "SHOP_SKU", "PRODUCT_NAME", "COUNT", "RESERVE", "RESERVED",
    "WAREHOUSE", "WAREHOUSE_AND_SHOP", "PLACEMENT_TYPE", "ERRORS", "VALID", "AVAILABLE_FOR_ORDER",
    "ORDER_ID", "YOUR_SKU", "OFFER_NAME", "DELIVERED_COUNT", "DELIVERY_DATE", "RETURNED_COUNT",
    "RETURN_WAREHOUSE_OR_SC_ACCEPT_DATE", "UNREDEEMED_COUNT", "UNREDEEMED_WAREHOUSE_OR_SC_ACCEPT_DATE"}


def source_hashes():
    paths = [ROOT/"platform_core"/name for name in ("market_quantity_providers.py", "market_quantity_registry.py",
             "market_quantity_runtime.py", "market_rate_limit.py", "market_quantity.py", "market_data.py", "podmasterye_yandex_sales.py")]
    paths.append(Path(__file__).resolve())
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in paths}


def report_observation(payload):
    data = payload.get("result", payload.get("data", {})) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return {}
    result = {k: data[k] if data[k] in REPORT_ENUMS else "UNRECOGNIZED" for k in ("status", "subStatus") if isinstance(data.get(k), str)}
    result["file_present"] = bool(isinstance(data.get("file"), str) and data["file"])
    if result["file_present"]:
        try:
            host = urlsplit(data["file"]).hostname or ""
            # Domain-only diagnostics are safe; signed path/query/fragment are
            # never written. Unknown origins remain undisclosed and blocked.
            roots = ("ozon.ru", "ozone.ru", "ozonusercontent.com", "yandexcloud.net", "yandex.ru", "yandex.net")
            result["file_host"] = host if any(host == r or host.endswith("."+r) for r in roots) else "UNRECOGNIZED"
        except ValueError:
            result["file_host"] = "MALFORMED"
    return result


def pseudonym(value):
    return sha256(str(value).encode()).hexdigest()[:16]


def structure(value, depth=0):
    """No values or unrecognized provider-controlled object keys leave memory."""
    if depth > 8:
        return {"type": type(value).__name__, "depth_limited": True}
    if isinstance(value, dict):
        return {"type": "object", "keys": {k: structure(v, depth+1) for k, v in value.items() if k in SHAPE_KEYS},
                "unretained_key_count": sum(k not in SHAPE_KEYS for k in value)}
    if isinstance(value, list):
        unique = {}
        for v in value[:3]:
            shape = structure(v, depth+1)
            unique[json.dumps(shape, sort_keys=True)] = shape
        return {"type": "array", "length": len(value), "first_element_shapes": list(unique.values())}
    return {"type": "null" if value is None else "boolean" if type(value) is bool else "integer" if type(value) is int else "number" if type(value) is float else "string" if isinstance(value, str) else "unsupported"}


def csv_header_structure(raw):
    result = {}
    try:
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        prefix = codecs.getincrementaldecoder(encoding)(errors="strict").decode(raw[:16384], final=False)
        line = prefix.splitlines()[0]
        delimiter = ";" if ";" in line else "," if "," in line else "\t"
        header = next(csv.reader([line], delimiter=delimiter, strict=True))
        result["known_quantity_columns"] = sorted(set(header) & QUANTITY_COLUMNS)
        result["unretained_column_count"] = sum(x not in QUANTITY_COLUMNS for x in header)
    except (ValueError, UnicodeError, csv.Error, IndexError, StopIteration):
        result["readable_quantity_header"] = False
    return result


def file_structure(raw):
    result = {"bytes": len(raw), "type": "binary"}
    if raw.startswith(b"PK"):
        result["type"] = "zip"
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                result["members"] = len(infos)
                result["known_members"] = sorted({PurePosixPath(i.filename).name for i in infos if PurePosixPath(i.filename).name in KNOWN_REPORTS})
                result["expanded_bytes"] = sum(i.file_size for i in infos)
                suffixes = Counter(PurePosixPath(i.filename).suffix.lower() for i in infos)
                result["member_types"] = {suffix if suffix in {".csv", ".json", ".xlsx", ".xml", ".txt"} else "unrecognized": count for suffix,count in suffixes.items()}
                if result["expanded_bytes"] <= 128*1024*1024:
                    result["csv_headers"] = []
                    for info in infos[:3]:
                        if PurePosixPath(info.filename).suffix.lower() == ".csv":
                            with archive.open(info) as stream:
                                result["csv_headers"].append(csv_header_structure(stream.read(16384)))
        except (zipfile.BadZipFile, ValueError, OSError, RuntimeError):
            result["readable_zip_directory"] = False
    else:
        result["type"] = "non_zip_document"
        result.update(csv_header_structure(raw))
    return result


def warehouse_observation(payload, context):
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    batch = result.get("warehouses") if isinstance(result, dict) else None
    if not isinstance(batch, list):
        return {}
    models = [model for warehouse in batch if isinstance(warehouse, dict) and isinstance(warehouse.get("models"), list)
              for model in warehouse["models"] if isinstance(model, dict)]
    return {"warehouses": len(batch), "models_with_campaign": sum(m.get("campaignId") is not None for m in models),
        "target_campaign_matches": sum(str(m.get("campaignId")) == str(context.get("campaignId")) for m in models),
        "groups": sum(bool(w.get("groupInfo")) for w in batch if isinstance(w, dict)),
        "placements": {k: sum(m.get("placementType") == k for m in models) for k in ("FBS", "DBS", "EXPRESS")}}


def wire_quantities(template, request, response, context):
    """Independent conservation totals from real wire fields, never adapters.

    These checks do not prove seller-cabinet agreement or inferred outcomes.
    Only direct counts that have a lossless local counterpart are compared.
    Return-event row/exemplar conservation is kept separate from the domain's
    physical-return classification. No IDs, names or money leave this function.
    """
    metrics = Counter()
    def units(value):
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,13}", value):
            return int(value)
        raise ValueError("quantity")
    def add(basis, field, value):
        metrics[basis+"."+field] += units(value)
    def records(raw):
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
        line = text.splitlines()[0]
        delim = ";" if ";" in line else "," if "," in line else "\t"
        reader = csv.DictReader(io.StringIO(text), delimiter=delim, strict=True)
        rows = list(reader)
        if not reader.fieldnames or any(None in row or None in row.values() for row in rows):
            raise ValueError("csv")
        return reader.fieldnames, rows
    status, stage = response.get("status_code"), request["stage"]
    if status not in (200, 201, 204):
        return {"status": "NO_SUCCESS_DATA", "metrics": {}}
    if template in ("OZ-01", "WB-01", "YM-01"):
        return {"status": "NOT_APPLICABLE_IDENTITY", "metrics": {}}
    try:
        data = response.get("payload")
        if template == "OZ-02":
            if stage == "details":
                count = sum(len({str(v) for v in [item.get("sku"), *[x.get("sku") for x in item.get("sources", [])]] if v is not None}) for item in data["items"])
                add("catalog", "rows", count)
            elif data["result"].get("items") == []:
                # Independent wire evidence: do not reuse the adapter's parser.
                # Both API counter names must agree before certifying an empty
                # catalogue; an invalid preferred count cannot fall back.
                totals = []
                for field in ("total_items", "total"):
                    if field in data["result"]:
                        value = data["result"][field]
                        if type(value) not in (str, int) or re.fullmatch(r"(?:0|[1-9][0-9]{0,12})", str(value)) is None:
                            raise ValueError("catalog_total")
                        totals.append(units(value))
                if not totals or len(set(totals)) != 1:
                    raise ValueError("catalog_total")
                if totals[0] == 0:
                    add("catalog", "rows", 0)
        elif template == "WB-02":
            add("catalog", "rows", len(data["cards"]))
        elif template == "YM-02":
            add("catalog", "rows", len(data["result"]["offerMappings"]))
        elif template in ("OZ-05", "OZ-06"):
            orders = [data.get("result", data)] if template == "OZ-05" else data["postings"]
            items = [item for order in orders for item in order["products"]]
            add("order_cohort", "rows", len(items))
            add("order_cohort", "ordered_qty", sum(units(item["quantity"]) for item in items))
        elif template == "OZ-04":
            add("return_event", "rows", len(data["returns"]))
            add("return_event", "unit_id_count", sum(len(item["exemplars"]) for item in data["returns"]))
        elif template == "OZ-07":
            stocks = [stock for item in data["items"] for stock in item["stocks"]]
            add("stock_snapshot", "rows", len(stocks))
            for target, source in (("stock_qty", "present"), ("reserved_qty", "reserved")):
                add("stock_snapshot", target, sum(units(s[source]) for s in stocks))
        elif template == "WB-03":
            products = data["data"]["products"]
            add("funnel_interval", "rows", len(products))
            for target, source in (("ordered_qty", "orderCount"), ("lost_qty", "cancelCount"), ("buyout_qty", "buyoutCount")):
                add("funnel_interval", target, sum(units(p["statistic"]["selected"][source]) for p in products))
        elif template == "WB-04":
            items = [] if status == 204 else [r for r in data if r.get("sellerOperName") == r.get("docTypeName") and r.get("sellerOperName") in ("Продажа", "Возврат")]
            add("calendar_event", "rows", len(items))
            for operation, field in (("Продажа", "delivered_qty"), ("Возврат", "calendar_return_qty")):
                add("calendar_event", field, sum(units(r["quantity"]) for r in items if r["sellerOperName"] == operation))
        elif template == "WB-05" and stage == "download":
            stocks = [] if status == 204 else [s for item in data for s in item["warehouses"]]
            add("stock_snapshot", "rows", len(stocks))
            add("stock_snapshot", "stock_qty", sum(units(s["quantity"]) for s in stocks))
        elif template == "YM-03":
            items = [item for order in data["orders"] for item in order["items"]]
            add("order_cohort", "rows", len(items))
            add("order_cohort", "ordered_qty", sum(units(item["count"]) for item in items))
        elif template == "YM-04":
            add("return_event", "rows", sum(len(item["items"]) for item in data["result"]["returns"]))
        elif template in ("OZ-03", "YM-05", "YM-06") and stage == "download":
            raw = response["content"]
            if template == "OZ-03":
                _, items = records(raw)
                add("order_cohort", "rows", len(items))
                add("order_cohort", "ordered_qty", sum(units(row["Количество"]) for row in items))
            else:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    if len(archive.infolist()) > 50 or sum(i.file_size for i in archive.infolist()) > 128*1024*1024:
                        raise ValueError("archive")
                    for info in archive.infolist():
                        if PurePosixPath(info.filename).suffix.lower() != ".csv":
                            continue
                        if template == "YM-05" and PurePosixPath(info.filename).name not in ("delivered.csv", "returned.csv", "unredeemed.csv"):
                            continue
                        header, items = records(archive.read(info))
                        if template == "YM-05":
                            mapping = {"DELIVERED_COUNT": "delivered_qty", "RETURNED_COUNT": "physical_return_qty", "UNREDEEMED_COUNT": "nonbuyout_qty"}
                            found = set(mapping) & set(header)
                            if len(found) != 1:
                                raise ValueError("realization_schema")
                            column = next(iter(found))
                            add("calendar_event", mapping[column], sum(units(r[column]) for r in items))
                        else:
                            column = "VALID" if "VALID" in header else "COUNT"
                            if "PLACEMENT_TYPE" in header:
                                items = [r for r in items if r["PLACEMENT_TYPE"] in (context.get("placementType"), "Экспресс" if context.get("placementType") == "EXPRESS" else None)]
                            add("stock_snapshot", "rows", len(items))
                            add("stock_snapshot", "stock_qty", sum(units(r[column]) for r in items))
                            reserved = "RESERVED" if "RESERVED" in header else "RESERVE" if "RESERVE" in header else None
                            if reserved:
                                add("stock_snapshot", "reserved_qty", sum(units(r[reserved] or 0) for r in items))
        elif template in ("YM-05", "YM-06") and stage == "poll":
            result = data["result"]
            if result.get("status") in ("DONE", "FAILED") and result.get("subStatus") == "NO_DATA":
                basis = "calendar_event" if template == "YM-05" else "stock_snapshot"
                for field in (("rows", "delivered_qty", "physical_return_qty", "nonbuyout_qty") if template == "YM-05" else ("rows", "stock_qty")):
                    add(basis, field, 0)
        return {"status": "OBSERVED" if metrics else "NO_QUANTITY_DATA_STAGE", "metrics": dict(metrics)}
    except (ValueError, TypeError, KeyError, UnicodeError, csv.Error, zipfile.BadZipFile, OverflowError, IndexError, RuntimeError, OSError, AttributeError):
        return {"status": "UNSUPPORTED_WIRE_SCHEMA", "metrics": {}}


def safe_headers(headers, profile):
    allowed = {"retry-after", "date", "content-type", *[n.lower() for n in profile.get("vendor_headers", [])]}
    out = {}
    for k, value in headers.items():
        key = str(k).lower()
        if key not in allowed:
            continue
        value = str(value).strip()
        # Only numbers, an HTTP date, or a fixed media type are retained.
        if re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,6})?", value) or re.fullmatch(r"[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} [0-9:]{8} GMT", value):
            out[key] = value
        elif key == "content-type":
            mime = value.split(";", 1)[0].lower()
            out[key] = mime if mime in {"application/json", "application/zip", "application/octet-stream", "text/csv", "text/plain", "text/html"} else "unrecognized"
        else:
            out[key] = "unrecognized_value"
    return out


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name("."+path.name+".tmp")
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class EvidenceBackend(Backend):
    def __init__(self, state, path, *, run_id):
        super().__init__(state)
        self.path = path
        self.calls = 0
        self.events = []
        self.run_id = run_id

    def record(self, event):
        event = {"schema": SCHEMA, "run": self.run_id, **event}
        self.events.append(event)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False)+"\n")
            stream.flush()
            os.fsync(stream.fileno())

    async def transport(self, job, request, fields):
        # This wrapper observes the same real transport. It neither changes its
        # requests nor substitutes a response, clock, DNS resolver or rate limit.
        self.calls += 1
        started = time.time()
        template = registry.get_template(job["source"])
        event = {"kind": "real_http", "at": started, "job": pseudonym(job["id"]), "template": job["source"],
                 "step": job["step"], "epoch": job["epoch"],
                 "provider": job["provider"], "stage": request["stage"], "method": request["method"],
                 "endpoint_template": template["stages"][request["stage"]]["path"] or "private_signed_download",
                 "generate": bool(request["generate"]), "download": bool(request["download"]),
                 "quota_min_interval": request["quota_profile"]["min_interval"],
                 "quota_documented": request["quota_profile"]["documented"],
                 "token_class": request["quota_profile"].get("token_class")}
        try:
            response = await super().transport(job, request, fields)
            event.update(status=response["status_code"], seconds=round(time.time()-started, 4),
                         headers=safe_headers(response.get("headers", {}), request["quota_profile"]))
            if "payload" in response:
                event["shape"] = structure(response["payload"])
                if request["stage"] == "poll":
                    event["report"] = report_observation(response["payload"])
                if request["stage"].startswith("warehouses_"):
                    event["warehouse_scope"] = warehouse_observation(response["payload"], self.context(job, fields))
            elif "content" in response:
                event["shape"] = file_structure(response["content"])
            event["wire_quantities"] = wire_quantities(job["source"], request, response, self.context(job, fields))
            self.record(event)
            return response
        except BaseException as exc:
            event.update(exception_type=type(exc).__name__, seconds=round(time.time()-started, 4))
            self.record(event)
            raise


def private_paths(state):
    value = Path(state).expanduser().resolve()
    dbpath = value / "state.sqlite3" if value.is_dir() else value
    directory = dbpath.parent
    # This acceptance program is intentionally incapable of opening either live
    # product's production data path, even if the CLI is mistyped.
    if "candidates" not in directory.parts or not directory.name.startswith(("private-live", "private_live")):
        raise ValueError("State must be an isolated private-live directory inside candidates")
    for file in (dbpath, directory / "market-connections.key"):
        info = file.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError("Private state must use separate regular files with private permissions")
    if directory.stat().st_mode & 0o077:
        raise ValueError("Private state directory must not be accessible to other users")
    return dbpath, directory


def encrypted_snapshot(db):
    rows = db.execute("SELECT id,workspace,provider,version,encrypted FROM pm_market_connections ORDER BY id").fetchall()
    digest = sha256()
    for cid, workspace, provider, version, encrypted in rows:
        digest.update(json.dumps([cid, workspace, provider, version], separators=(",", ":")).encode())
        digest.update(bytes(encrypted))
    return len(rows), digest.digest()


AUDIT_QUANTITIES = ("ordered_qty", "delivered_qty", "cancelled_qty", "nonbuyout_qty", "physical_return_qty",
                    "calendar_return_qty", "lost_qty", "buyout_qty", "stock_qty", "reserved_qty")


def normalized_metrics(rows, catalog_count=0):
    metrics = Counter({"catalog.rows": catalog_count})
    for row in rows:
        basis = row.get("quantity_basis", "unknown")
        metrics[basis+".rows"] += 1
        if basis == "return_event":
            metrics[basis+".unit_id_count"] += len(row.get("unit_ids") or [])
        for field in AUDIT_QUANTITIES:
            if type(row.get(field)) is int:
                metrics[basis+"."+field] += row[field]
    return dict(metrics)


def quantity_totals(db, job):
    totals, stock_by_kind = {}, {}
    with q.local(db, job["workspace"], job["provider"]) as local:
        # A return's event date can precede the source's update-date window.
        # The atomic publication receipt identifies this exact collection;
        # date filtering would silently omit those legitimate returned units.
        rows = [json.loads(body) for body, in local.execute("SELECT body FROM quantity_rows WHERE store=? AND source=? AND receipt=?", (job["store"], job["source"], job["receipt"]))]
        for row in rows:
            basis = row.get("quantity_basis", "unknown")
            target = totals.setdefault(basis, {"rows": 0, "known_quantities": {}, "unknown_quantities": {}, "incomplete_rows": 0})
            target["rows"] += 1
            target["incomplete_rows"] += int(not row.get("complete", True))
            for field in AUDIT_QUANTITIES:
                value = row.get(field)
                if type(value) is int:
                    target["known_quantities"][field] = target["known_quantities"].get(field, 0)+value
                elif field in row:
                    target["unknown_quantities"][field] = target["unknown_quantities"].get(field, 0)+1
            if basis == "stock_snapshot":
                kind = row.get("stock_kind")
                safe_kind = kind if kind in {"aggregate", "warehouse", "in_transit", "available", "physical_valid", "fbo", "fbs"} else "other"
                grouping = stock_by_kind.setdefault(safe_kind, {"rows": 0, "stock_qty": 0, "reserved_qty": 0})
                grouping["rows"] += 1
                for field in ("stock_qty", "reserved_qty"):
                    if type(row.get(field)) is int:
                        grouping[field] += row[field]
        cards = local.execute("SELECT count(*) FROM quantity_catalog WHERE store=? AND receipt=?", (job["store"], job["receipt"])).fetchone()[0]
    return {"basis": totals, "catalog_count": cards, "stock_by_kind": stock_by_kind, "comparable_metrics": normalized_metrics(rows, cards)}


def reconcile_wire(db, job, events, local_totals):
    if q.ROLE[job["source"]] == "identity":
        return {"status": "NOT_APPLICABLE_IDENTITY", "kind": "api_to_local_projection"}
    if job["state"] not in q.TERMINAL:
        return {"status": "BLOCKED_INCOMPLETE_SOURCE", "kind": "api_to_local_projection"}
    with q.local(db, job["workspace"], job["provider"]) as local:
        steps = {r[0] for r in local.execute("SELECT step FROM quantity_step_receipts WHERE job=? AND epoch=?", (job["id"], job["epoch"]))}
    by_step = {event["step"]: event for event in events if event.get("epoch") == job["epoch"] and event.get("status") in (200, 201, 204) and event.get("step") in steps}
    if not steps or set(by_step) != steps:
        return {"status": "NOT_FULLY_OBSERVED_THIS_RUN", "kind": "api_to_local_projection",
                "observed_committed_steps": len(by_step), "committed_steps": len(steps)}
    if any(e.get("wire_quantities", {}).get("status") == "UNSUPPORTED_WIRE_SCHEMA" for e in by_step.values()):
        return {"status": "UNSUPPORTED_WIRE_SCHEMA", "kind": "api_to_local_projection"}
    sums = Counter()
    for event in by_step.values():
        for field, value in event.get("wire_quantities", {}).get("metrics", {}).items():
            sums[field] += value
    if not sums:
        return {"status": "NO_COMPARABLE_COUNTERS", "kind": "api_to_local_projection"}
    local = local_totals["comparable_metrics"]
    comparisons = {field: {"api": value, "local": local.get(field, 0), "equal": value == local.get(field, 0)} for field, value in sorted(sums.items())}
    return {"status": "MATCH" if all(c["equal"] for c in comparisons.values()) else "MISMATCH",
            "kind": "api_to_local_projection", "comparisons": comparisons,
            "scope": "Direct quantity and row conservation only; not seller-cabinet reconciliation or physical-outcome proof."}


async def run(state, evidence_dir, *, templates=None, max_seconds=600, max_requests=100, from_=None, to=None):
    selected = set(templates or ALL_IDS)
    if not selected or not selected <= ALL_IDS:
        raise ValueError("Unknown template selection")
    if max_seconds <= 0 or max_requests <= 0:
        raise ValueError("Positive live budgets are required")
    evidence = Path(evidence_dir)
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    started = time.time()
    hashes_at_start = source_hashes()
    run_id = datetime.fromtimestamp(started, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backend = EvidenceBackend(state, evidence / "http.jsonl", run_id=run_id)
    wanted_providers = {registry.get_template(tid)["provider"] for tid in selected}
    connections = state.identity._db.execute("SELECT id,workspace,provider,version FROM pm_market_connections ORDER BY provider,id").fetchall()
    connections = [r for r in connections if r[2] in wanted_providers]
    originals = encrypted_snapshot(state.identity._db)
    key_fingerprint_before = sha256(state.market_links.path.read_bytes()).digest()
    cipher_valid_before = 0
    connection_blockers = {}
    for cid, workspace, provider, version in connections:
        row = state.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?", (cid,)).fetchone()
        fields = state.market_links.unpack(workspace, cid, provider, row[0])
        cipher_valid_before += 1
        if provider == "wb":
            profile = registry.wb_token_profile(fields.get("token"), now=started)
            if profile["classification"] in ("sandbox", "expired"):
                connection_blockers[cid] = "BLOCKED_"+profile["classification"].upper()+"_TOKEN"
        del fields
    today = datetime.now(timezone.utc).date()
    end = datetime.fromisoformat(to).date() if to else today-timedelta(days=1)
    start = datetime.fromisoformat(from_).date() if from_ else end-timedelta(days=29)
    if not start <= end < today or (end-start).days > 29:
        raise ValueError("Live acceptance window must be a completed interval of at most 30 days")
    managed, identities, enrolled, blocked = {}, {}, set(), {}
    with state.identity._write() as db:
        for cid, workspace, provider, version in connections:
            if cid in connection_blockers:
                continue
            jid = q.enqueue_identity(db, workspace, cid)
            identities[cid] = jid
            managed[jid] = {"dependency": q.IDENTITY[provider] not in selected}

    def enroll():
        with state.identity._write() as db:
            for cid, workspace, provider, version in connections:
                if cid not in identities:
                    continue
                identity = backend._row(db, identities[cid])
                if identity["state"] not in q.TERMINAL:
                    continue
                for store in q.selected_stores(db, workspace, cid):
                    for tid in sorted(selected | ({"OZ-06"} if "OZ-05" in selected else set())):
                        if registry.get_template(tid)["provider"] != provider or q.ROLE[tid] == "identity":
                            continue
                        enrollment = (store["id"], tid)
                        if enrollment in enrolled:
                            continue
                        context = {"reason": "live_acceptance", "live_run": run_id}
                        a, b = str(start), str(end)
                        if q.ROLE[tid] in ("catalog", "stocks"):
                            a = b = ""
                        if tid == "YM-05":
                            bdate = today.replace(day=1)-timedelta(days=1)
                            a, b = str(bdate.replace(day=1)), str(bdate)
                            context["month"] = a[:7]
                        if tid == "OZ-05":
                            postings = {}
                            with q.local(db, workspace, provider) as local:
                                for body, in local.execute("SELECT body FROM quantity_rows WHERE store=? AND source IN ('OZ-06','OZ-03') ORDER BY observed DESC", (store["id"],)):
                                    row = json.loads(body)
                                    if row.get("posting_number") and row.get("scheme") in ("FBO", "FBS"):
                                        postings.setdefault(row["scheme"], row["posting_number"])
                                    if len(postings) == 2:
                                        break
                            if not postings:
                                blocked[enrollment] = "BLOCKED_NO_REAL_POSTING"
                                continue
                            for scheme, posting_number in postings.items():
                                j = q.enqueue(db, store["id"], tid, a, b, cid=store["connection_id"], version=store["version"],
                                              context={**context, "scheme": scheme, "posting_number": posting_number})
                                managed[j] = {"dependency": False, "scheme": scheme}
                            blocked.pop(enrollment, None)
                        else:
                            j = q.enqueue(db, store["id"], tid, a, b, cid=store["connection_id"], version=store["version"], context=context)
                            managed[j] = {"dependency": tid not in selected}
                        enrolled.add(enrollment)

    last_progress = 0
    while time.time()-started < max_seconds and backend.calls < max_requests:
        enroll()
        current = [backend._row(state.identity._db, jid) for jid in managed]
        active = [job for job in current if job["state"] not in q.TERMINAL | STOPPED]
        if not active:
            break
        progressed = False
        for job in sorted(active, key=lambda j: (j["due"], j["requests"], j["created"])):
            if backend.calls >= max_requests or time.time()-started >= max_seconds:
                break
            claimed = backend.claim(job_id=job["id"])
            if claimed:
                await backend.run(claimed)
                progressed = True
        now = time.time()
        if now-last_progress >= 30:
            print(json.dumps({"live_progress": {"seconds": round(now-started), "real_http_requests": backend.calls,
                "managed_jobs": len(managed), "terminal_jobs": sum(j["state"] in q.TERMINAL for j in current)}}), flush=True)
            last_progress = now
        if not progressed:
            due = min(max(job["due"], job["expires"] if job["state"] == "running" else 0) for job in active)
            remaining = max_seconds-(now-started)
            if due-now > remaining:
                break
            await asyncio.sleep(min(15, max(.05, due-now), remaining))
    enroll()
    cipher_valid_after = 0
    for cid, workspace, provider, version in connections:
        row = state.identity._db.execute("SELECT encrypted FROM pm_market_connections WHERE id=?", (cid,)).fetchone()
        fields = state.market_links.unpack(workspace, cid, provider, row[0])
        cipher_valid_after += 1
        del fields
    results = []
    for jid, details in managed.items():
        job = backend._row(state.identity._db, jid)
        events = [e for e in backend.events if e["job"] == pseudonym(jid)]
        cp = json.loads(job["checkpoint"])
        codes = [r[0] for r in state.identity._db.execute("SELECT code FROM market_data_events WHERE job=? AND code IS NOT NULL ORDER BY at", (jid,))]
        quantities = quantity_totals(state.identity._db, job)
        reconciliation = reconcile_wire(state.identity._db, job, events, quantities)
        results.append({"template": job["source"], "provider": job["provider"], "job": pseudonym(jid), "store": pseudonym(job["store"]),
                        "dependency": details["dependency"], "scheme": details.get("scheme"), "state": job["state"],
                        "acceptance": "OBSERVED_COMPLETE" if job["state"] in q.TERMINAL and events else "CACHED_COMPLETE" if job["state"] in q.TERMINAL else "BLOCKED",
                        "from": job["since"], "to": job["until"], "next_allowed_at": job["due"],
                        "http_requests_this_run": len(events), "http_requests_total": job["requests"],
                        "rate_limits_total": job["rate_limits"], "retries_total": job["retries"],
                        "report_id_persisted": bool(cp.get("report_id")), "completed_report_count": len(cp.get("completed_reports", [])),
                        "last_error_codes": codes[-10:], "quantities": quantities, "reconciliation": reconciliation})
    template_results = []
    for tid in sorted(selected):
        jobs = [r for r in results if r["template"] == tid]
        provider = registry.get_template(tid)["provider"]
        related = [r for r in connections if r[2] == provider]
        reason = "BLOCKED_NO_CONNECTION" if not related else "BLOCKED_DEPENDENCY"
        if tid == "OZ-05" and not jobs:
            reason = "BLOCKED_NO_REAL_POSTING"
        if any(cid in connection_blockers for cid, _, _, _ in related):
            reason = "BLOCKED_TOKEN_CLASS_OR_EXPIRY"
        reconciliation_bad = any(j["reconciliation"]["status"] in ("MISMATCH", "UNSUPPORTED_WIRE_SCHEMA", "NO_COMPARABLE_COUNTERS") for j in jobs)
        complete = bool(jobs) and all(j["state"] in q.TERMINAL for j in jobs) and not reconciliation_bad
        template_results.append({"template": tid, "result": "OBSERVED_COMPLETE" if complete and all(j["http_requests_this_run"] for j in jobs) else "CACHED_COMPLETE" if complete else "BLOCKED",
                                 "reason": None if complete else "BLOCKED_API_LOCAL_RECONCILIATION" if reconciliation_bad else reason if not jobs else "BLOCKED_"+"_".join(sorted({j["state"].upper() for j in jobs if j["state"] not in q.TERMINAL})),
                                 "api_local_reconciliation": sorted({j["reconciliation"]["status"] for j in jobs}),
                                 "jobs": len(jobs), "real_http_requests_this_run": sum(j["http_requests_this_run"] for j in jobs)})
    hashes_at_end = source_hashes()
    result = {"schema": SCHEMA, "run": run_id, "started_at": started, "finished_at": time.time(), "live": True,
              "synthetic_responses": 0, "model_calls": 0, "billing_calls": 0, "source_hashes": hashes_at_start,
              "source_files_unchanged_during_run": hashes_at_start == hashes_at_end,
              "source_hashes_after_run": hashes_at_end,
              "budgets": {"seconds": max_seconds, "requests": max_requests}, "real_http_requests": backend.calls,
              "http_status_counts": dict(Counter(str(e.get("status", e.get("exception_type"))) for e in backend.events)),
              "credential_preservation": {"connection_count": originals[0], "encrypted_rows_unchanged": encrypted_snapshot(state.identity._db) == originals,
                  "key_file_unchanged": sha256(state.market_links.path.read_bytes()).digest() == key_fingerprint_before,
                  "decryptable_connections_before": cipher_valid_before, "decryptable_connections_after": cipher_valid_after},
              "integrity": state.identity._db.execute("PRAGMA integrity_check").fetchone()[0],
              "templates": template_results, "jobs": results,
              "limits": ["Completion covers the specified live window, not maximum available history.",
                         "Observed provider responses do not replace reconciliation with seller account exports.",
                         "A queued or delayed stage remains BLOCKED; the clock and quotas are never bypassed."]}
    atomic_json(evidence/("summary-"+run_id+".json"), result)
    atomic_json(evidence/"latest.json", result)
    print(json.dumps({"live_result": {"run": run_id, "real_http_requests": backend.calls,
        "templates": template_results, "credential_preservation": result["credential_preservation"]}}, ensure_ascii=False), flush=True)
    return result


async def main_async(args):
    dbpath, private = private_paths(args.state)
    with IdentityStore(dbpath) as identity:
        domain.init(identity)
        async with httpx.AsyncClient(timeout=55, trust_env=False, follow_redirects=False) as client:
            state = SimpleNamespace(identity=identity, market_links=Store(identity, private),
                                    worker=SimpleNamespace(database_path=dbpath), http=client)
            return await run(state, args.evidence, templates=args.templates, max_seconds=args.max_seconds,
                             max_requests=args.max_requests, from_=args.from_date, to=args.to_date)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="private-live directory or its state.sqlite3")
    parser.add_argument("--evidence", required=True, help="Sanitized evidence directory")
    parser.add_argument("--max-seconds", type=int, default=600)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--templates", nargs="+", choices=sorted(ALL_IDS))
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    args = parser.parse_args()
    try:
        result = asyncio.run(main_async(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(json.dumps({"live_stopped": "interrupted; durable checkpoint and report IDs remain in private state"}), flush=True)
        return 130
    except Exception as exc:
        # Exception messages can contain a URL or an upstream credential echo.
        print(json.dumps({"live_error_type": type(exc).__name__, "live": True}), flush=True)
        return 2
    return 0 if all(t["result"] in ("OBSERVED_COMPLETE", "CACHED_COMPLETE") for t in result["templates"]) else 3


if __name__ == "__main__":
    raise SystemExit(main())
