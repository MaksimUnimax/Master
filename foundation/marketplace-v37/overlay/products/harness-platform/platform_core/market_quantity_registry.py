"""Versioned, private service passports for the workshop quantity collector.

This is a projection of the existing marketplace matrix for the workshop's
quantity-only domain. It does not register another executor, queue or model tool.
All requests returned by the adapters must use market_collect's shared transport.
"""
from copy import deepcopy
import base64
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

VERSION = "2026-11-28.1"
VERIFIED_AT = "2026-11-28"
WB_DOC = "https://dev.wildberries.ru/api/swagger/yaml/en/"
YM_DOC = "https://yandex.ru/dev/market/partner-api/doc/ru/"
OZ_DOC = "https://docs.ozon.ru/api/seller/"
OZ_RATE_SOURCE = "https://dev.ozon.ru/news/802-Zagolovki-dlia-upravleniia-reit-limitami-v-Seller-API/"

ERROR_POLICY = {
    "version": VERSION,
    "classifier": "market_rate_limit.classify",
    "failure_handler": "market_quantity_runtime.Backend._failure",
    "400": "invalid_input_no_unchanged_retry", "422": "invalid_input_no_unchanged_retry",
    "401": "denied_pause_connection", "403": "denied_pause_connection",
    "402": "entitlement_or_service_balance_required_no_retry",
    "404": "missing_entity_or_obsolete_endpoint_not_zero",
    "409": "reconcile_generation_lease_and_request",
    "410": "expired_report_refresh_known_id_not_generate",
    "413": "bounded_request_or_report_too_large",
    "420": "provider_rate_limit_if_yandex_otherwise_fail_closed",
    "429": "persist_cooldown_checkpoint_release_worker",
    "408": "safe_read_bounded_retry_generate_uncertain",
    "500": "safe_read_bounded_retry_generate_uncertain",
    "502": "safe_read_bounded_retry_generate_uncertain",
    "503": "safe_read_bounded_retry_generate_uncertain",
    "504": "safe_read_bounded_retry_generate_uncertain",
    "timeout": "safe_read_bounded_retry_generate_uncertain",
    "connection_reset": "safe_read_bounded_retry_generate_uncertain",
    "temporary_dns": "safe_read_bounded_retry_generate_uncertain",
    "tls": "blocked_no_retry_no_bypass", "origin": "blocked_no_redirect_or_credentials",
    "invalid_json": "partial_preserve_last_complete", "unknown_schema": "partial_preserve_last_complete",
    "domain_error_200": "partial_preserve_last_complete", "pagination": "partial_no_publish",
    "report_pending": "persist_report_id_delayed_poll", "report_failed": "needs_attention_not_zero",
    "report_no_data": "zero_only_documented_explicit_no_data",
    "report_corrupt": "partial_preserve_last_complete", "report_too_large": "needs_attention_no_publish",
    "generate_unknown": "uncertain_reconcile_never_blind_regenerate",
    "database": "no_ack_before_commit_idempotent_receipt_recovery",
    "lease_expired": "discard_stale_result", "generation_changed": "discard_stale_result",
    "cancelled": "stop_before_next_dispatch", "unknown": "needs_attention_fail_closed",
}

PROGRESS_POLICY = {
    "version": VERSION, "owner": "market_data_tasks",
    "checkpoint": "JSON after validated page; same receipt transaction as quantity rows",
    "lease": "existing collector lease with fencing and connection generation check before dispatch and commit",
    "idempotency": "owner/provider/confirmed-seller/source/interval/request fingerprint",
    "cancel": "no new dispatch; already dispatched result reconciled under its lease",
    "resume": "same job, confirmed cursor and report ID; persisted cooldown is authoritative",
    "publish": "only after every required page, scheme and report member validates",
    "previous_snapshot": "retain until complete replacement",
    "unknown_generate": "uncertain; no automatic second generation",
    "signed_url": "private checkpoint only; auth-free allowlisted download; never public or log",
}

_REQUIRED_TESTS = ["success", "invalid_input", "scope", "empty_confirmed", "unknown_schema",
    "duplicate_page", "cursor_restart", "first_and_intermediate_429", "three_429_then_success",
    "permanent_429", "retry_after_seconds_date_missing_malformed", "temporary_5xx_timeout",
    "permanent_errors", "lease_generation_cancel", "quota_concurrency", "live_verification"]

# Executable evidence references are separate from their acceptance results.
# Registering the live runner never claims that a real API check has passed.
_TEST_CASES = {
    "success": ["tests.test_market_quantity_runtime.Runtime.test_all_18_templates_real_http_success_and_persisted_quantities"],
    "invalid_input": ["tests.test_market_quantity_providers.ProviderContracts.test_invalid_units_do_not_become_zero"],
    "scope": ["tests.test_market_quantity_runtime.Runtime.test_every_template_every_network_stage_access_and_persistent_429"],
    "empty_confirmed": ["tests.test_market_quantity_providers.ProviderContracts.test_empty_arrays_are_zero_only_after_documented_completion"],
    "unknown_schema": ["tests.test_market_quantity_runtime.Runtime.test_all_templates_invalid_200_cannot_publish_success_or_zero"],
    "duplicate_page": ["tests.test_market_quantity_providers.ProviderContracts.test_unrecognized_or_looped_cursor_is_rejected"],
    "cursor_restart": ["tests.test_market_quantity_providers.ProviderContracts.test_checkpoint_bound_to_connection_generation_and_all_selectors"],
    "first_and_intermediate_429": ["tests.test_market_quantity_runtime.Runtime.test_18_templates_three_429_every_stage_then_restart_resume"],
    "three_429_then_success": ["tests.test_market_quantity_runtime.Runtime.test_18_templates_three_429_every_stage_then_restart_resume"],
    "permanent_429": ["tests.test_market_quantity_runtime.Runtime.test_every_template_every_network_stage_access_and_persistent_429"],
    "retry_after_seconds_date_missing_malformed": ["tests.test_market_quantity_runtime.Runtime.test_every_template_retry_headers_variants_use_real_durable_wait"],
    "temporary_5xx_timeout": ["tests.test_market_quantity_runtime.Runtime.test_read_failures_retry_but_unknown_generate_is_never_repeated", "tests.test_market_quantity_runtime.Runtime.test_every_template_tcp_timeout_reset_and_report_stage_recovery"],
    "permanent_errors": ["tests.test_market_quantity_runtime.Runtime.test_permanent_errors_do_not_retry_or_publish_fake_zero", "tests.test_market_quantity_runtime.Runtime.test_tls_and_origin_fail_closed_for_every_template"],
    "lease_generation_cancel": ["tests.test_market_quantity_runtime.Runtime.test_cancel_cooldown_rotation_and_two_worker_fencing"],
    "quota_concurrency": ["tests.test_market_quantity_runtime.Runtime.test_multiple_processes_share_atomic_lease_and_seller_quota"],
    "live_verification": ["acceptance.market_quantity_live.run"],
}


def _passport(tid, provider, purpose, stages, scope, source, *, axis="snapshot",
              earliest=None, lookback=None, window_days=None, window_months=None,
              pagination="none", terminal="validated response", required=True):
    return {
        "id": tid, "stable_id": tid, "version": VERSION, "kind": "internal_api",
        "provider": provider, "purpose": purpose, "handler": "market_quantity_providers.consume",
        "effect": "read_marketplace_write_local_quantity_projection", "role": "workspace_owner",
        "required_scope": scope,
        "required_scope_evidence": "accepted_runtime_hint_not_independently_documented" if provider == "ozon" else "official_documentation",
        "required": required, "store_binding": "server-confirmed seller and generation",
        "input_schema": {"type": "object", "additionalProperties": False,
            "properties": {"from": {"type": "string", "format": "date"},
                           "to": {"type": "string", "format": "date"},
                           "sku": {"type": "string"}}},
        "server_input_schema": {"type": "object", "required": ["store", "cid", "version", "now"],
            "properties": {"store": {"type": "string"}, "cid": {"type": "string"},
                           "version": {"type": "integer"}, "now": {"type": "number"},
                           "seller": {"type": ["string", "null"]}, "client_id": {"type": "string"},
                           "businessId": {"type": "integer", "minimum": 1}, "campaignId": {"type": "integer", "minimum": 1},
                           "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"},
                           "month": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
                           "scheme": {"enum": ["FBO", "FBS"]}, "posting_number": {"type": "string", "maxLength": 160},
                           "placementType": {"type": "string"}, "token_class": {"enum": ["base", "personal", "service", "base_with_secret"]}},
            "guard": "Trusted server job binding only; never accept provider IDs, report links or credentials from model arguments."},
        "output_schema": {"type": "object", "additionalProperties": False,
            "properties": {"checkpoint": {"type": "object"}, "rows": {"type": "array", "items": {"type": "object"}},
                "catalog": {"type": "array", "items": {"type": "object"}}, "metadata": {"type": "object"},
                "complete": {"type": "boolean"}, "next_due": {"type": "number", "minimum": 0},
                "state": {"enum": ["collecting", "ready", "no_data_confirmed"]}, "coverage": {"type": "object"}},
            "required": ["checkpoint", "rows", "catalog", "metadata", "complete", "next_due", "state", "coverage"]},
        "stages": stages, "initial_stage": next(iter(stages)), "source": source,
        "verified_at": VERIFIED_AT, "live_verified": False,
        "history": {"axis": axis, "earliest": earliest, "max_lookback_days": lookback,
            "max_window_days": window_days, "window_months": window_months,
            "window_evidence": "accepted_donor_conservative_window" if tid == "OZ-03" else "documented" if window_days or window_months else "not_applicable" if axis == "snapshot" else "not_declared",
            "boundary_evidence": "documented" if earliest or lookback else ("not_applicable" if axis == "snapshot" else "unknown"),
            "timezone": "Europe/Moscow", "empty_window_is_history_boundary": False},
        "pagination": pagination, "terminal": terminal,
        "normalization": "market-quantity/v1", "deduplication": "provider/store/natural_key and immutable unit identifiers",
        "minimal_fields": ["IDs", "SKU", "category", "quantities", "dates", "status", "coverage", "schema_version"],
        "excluded_fields": ["credentials", "buyer PII", "commissions", "payments", "advertising", "logistics amounts"],
        "error_policy": deepcopy(ERROR_POLICY), "progress_policy": deepcopy(PROGRESS_POLICY),
        "tests": {"required": list(_REQUIRED_TESTS), "cases": deepcopy(_TEST_CASES), "na": {}},
    }


def _stage(method, path, *, origin=None, generate=False, download=False, auth=None):
    return {"method": method, "path": path, "origin": origin, "generate": generate,
            "download": download, "auth": auth, "idempotent": not generate}


OZ = "https://api-seller.ozon.ru"
YM = "https://api.partner.market.yandex.ru"
_TEMPLATES = {
    "OZ-01": _passport("OZ-01", "ozon", "Проверка Seller API и разрешений", {"identity": _stage("POST", "/v1/roles")}, ["Seller"], OZ_DOC),
    "OZ-02": _passport("OZ-02", "ozon", "Каталог и категории товаров", {
        "list": _stage("POST", "/v3/product/list"), "details": _stage("POST", "/v3/product/info/list")},
        ["Product read-only"], OZ_DOC, pagination="last_id; detail batch exactly equals requested product IDs", terminal="unique product count equals stable total"),
    "OZ-03": _passport("OZ-03", "ozon", "Полная количественная история FBO и FBS", {
        "generate": _stage("POST", "/v1/report/postings/create", generate=True),
        "poll": _stage("POST", "/v1/report/info"), "download": _stage("GET", None, download=True, auth="none")},
        ["Report"], OZ_DOC, axis="in_process_at", window_months=3,
        terminal="validated CSV for both FBO and FBS; no pending/unknown report"),
    "OZ-04": _passport("OZ-04", "ozon", "Возвраты, отмены и уникальные экземпляры", {
        "list": _stage("POST", "/v1/returns/list")}, ["Returns read-only"], OZ_DOC,
        axis="logistic_return_date", pagination="last_id=last return.id", terminal="has_next=false with valid exemplars"),
    "OZ-05": _passport("OZ-05", "ozon", "Уточнение исходного заказа для пограничного возврата", {
        "fbo": _stage("POST", "/v2/posting/fbo/get"), "fbs": _stage("POST", "/v3/posting/fbs/get")},
        ["Posting FBO", "Posting FBS read-only"], OZ_DOC, axis="order_creation", terminal="requested posting identity matches"),
    "OZ-06": _passport("OZ-06", "ozon", "Текущие когорты заказов FBO и FBS", {
        "fbo": _stage("POST", "/v3/posting/fbo/list"), "fbs": _stage("POST", "/v4/posting/fbs/list")},
        ["Posting FBO", "Posting FBS read-only"], "https://dev.ozon.ru/news/734-Otkliuchenie-starykh-metodov-Seller-API-dlia-raboty-s-postingami/",
        axis="order_creation", pagination="cursor per scheme", terminal="has_next=false for both schemes"),
    "OZ-07": _passport("OZ-07", "ozon", "Текущие количественные остатки", {"list": _stage("POST", "/v4/product/info/stocks")},
        ["Product read-only"], OZ_DOC, pagination="cursor and stable total", terminal="all unique items collected", required=False),
    "WB-01": _passport("WB-01", "wb", "Подтверждение профиля продавца", {"identity": _stage("GET", "/api/v1/seller-info", origin="https://common-api.wildberries.ru")},
        ["any category"], WB_DOC + "01-general.yaml"),
    "WB-02": _passport("WB-02", "wb", "Каталог карточек и артикулов", {"list": _stage("POST", "/content/v2/get/cards/list", origin="https://content-api.wildberries.ru")},
        ["Content"], WB_DOC + "02-items.yaml", pagination="updatedAt+nmID; ascending", terminal="cursor.total < requested limit"),
    "WB-03": _passport("WB-03", "wb", "Количественная воронка по исходному периоду заказа", {
        "list": _stage("POST", "/api/analytics/v3/sales-funnel/products", origin="https://seller-analytics-api.wildberries.ru")},
        ["Analytics"], WB_DOC + "11-analytics.yaml", axis="order_cohort_interval", lookback=365, window_days=365,
        pagination="offset; <=1000 products; stable SKU membership", terminal="products count < requested limit"),
    "WB-04": _passport("WB-04", "wb", "Количественная проекция реализации", {
        "list": _stage("POST", "/api/finance/v1/sales-reports/detailed", origin="https://finance-api.wildberries.ru")},
        ["Finance"], WB_DOC + "13-finances.yaml", axis="realization_event", earliest="2024-01-29",
        pagination="rrdId from last row; quantity fields only", terminal="explicit HTTP 204, never short-page heuristic"),
    "WB-05": _passport("WB-05", "wb", "Остатки на складах и в пути", {
        "generate": _stage("GET", "/api/v1/warehouse_remains", origin="https://seller-analytics-api.wildberries.ru", generate=True),
        "poll": _stage("GET", "/api/v1/warehouse_remains/tasks/{report_id}/status", origin="https://seller-analytics-api.wildberries.ru"),
        "download": _stage("GET", "/api/v1/warehouse_remains/tasks/{report_id}/download", origin="https://seller-analytics-api.wildberries.ru", download=True)},
        ["Analytics"], WB_DOC + "12-reports.yaml", terminal="known task done and valid JSON report or explicit 204", required=False),
    "YM-01": _passport("YM-01", "yandex_market", "Токен, кабинеты и магазины", {
        "identity": _stage("POST", "/v2/auth/token"), "campaigns": _stage("GET", "/v2/campaigns")},
        ["any valid Api-Key scope"], YM_DOC + "reference/auth/getAuthTokenInfo", pagination="pageToken", terminal="no nextPageToken and unique campaigns"),
    "YM-02": _passport("YM-02", "yandex_market", "Каталог товаров кабинета", {"list": _stage("POST", "/v2/businesses/{businessId}/offer-mappings")},
        ["offers-and-cards-management:read-only"], YM_DOC + "reference/business-offer-mappings/getOfferMappings",
        pagination="pageToken; 100 items", terminal="no nextPageToken"),
    "YM-03": _passport("YM-03", "yandex_market", "Когорты заказов и статусы единиц", {"list": _stage("POST", "/v1/businesses/{businessId}/orders")},
        ["inventory-and-order-processing:read-only"], YM_DOC + "reference/orders/getBusinessOrders", axis="order_creation", window_days=30,
        pagination="pageToken; 50 orders", terminal="no nextPageToken; item-level status completeness separately recorded"),
    "YM-04": _passport("YM-04", "yandex_market", "Невыкупы и физические возвраты", {"list": _stage("GET", "/v2/campaigns/{campaignId}/returns")},
        ["inventory-and-order-processing:read-only"], YM_DOC + "reference/returns/getReturns", axis="return_update",
        pagination="pageToken; 100 returns", terminal="no nextPageToken; logistics and fastReturn checked"),
    "YM-05": _passport("YM-05", "yandex_market", "Календарная реализация по месяцам", {
        "generate": _stage("POST", "/v2/reports/goods-realization/generate", generate=True),
        "poll": _stage("GET", "/v2/reports/info/{report_id}"), "download": _stage("GET", None, download=True, auth="none")},
        ["finance-and-accounting"], YM_DOC + "reference/reports/generateGoodsRealizationReport", axis="realization_event", window_months=1,
        terminal="all three quantity sheets validated; explicit terminal DONE or FAILED with NO_DATA separately"),
    "YM-06": _passport("YM-06", "yandex_market", "Остатки для материального планирования", {
        "warehouses_current": _stage("POST", "/v3/businesses/{businessId}/warehouses"),
        "warehouses_legacy": _stage("POST", "/v2/businesses/{businessId}/warehouses"),
        "generate_current": _stage("POST", "/v3/businesses/{businessId}/reports/stocks/generate", generate=True),
        "generate": _stage("POST", "/v2/reports/stocks-on-warehouses/generate", generate=True),
        "poll": _stage("GET", "/v2/reports/info/{report_id}"), "download": _stage("GET", None, download=True, auth="none")},
        ["offers-and-cards-management:read-only", "inventory-and-order-processing:read-only"], YM_DOC + "reference/reports/generateStocksReport",
        pagination="warehouse discovery pageToken, 30 warehouses; exact campaign and placement binding",
        terminal="recognized stock sheet and quantity columns for proven warehouse/campaign scope; no financial columns", required=False),
}

_TEMPLATES["YM-06"]["sources"] = [YM_DOC + "reference/warehouses/getPartnerWarehouses",
    YM_DOC + "reference/warehouses/getPagedWarehouses", YM_DOC + "reference/reports/generateStocksReport",
    YM_DOC + "reference/reports/generateStocksOnWarehousesReport", YM_DOC + "reference/reports/getReportInfo"]

for _t in _TEMPLATES.values():
    for _s in _t["stages"].values():
        if _s["origin"] is None and _s["path"] is not None:
            _s["origin"] = OZ if _t["provider"] == "ozon" else YM
        if _s["auth"] is None:
            _s["auth"] = _t["provider"]
    if not any(s["generate"] for s in _t["stages"].values()):
        _t["tests"]["na"]["generate_unknown"] = "Template has no report-generation stage."
    if not any(s["download"] for s in _t["stages"].values()):
        _t["tests"]["na"]["corrupt_archive"] = "JSON-only method; malformed JSON remains mandatory."
    _t["quota_profile"] = {"resolver": "market_quantity_registry.quota_profile", "scope": "confirmed seller, never individual key"}


def templates():
    return [deepcopy(v) for v in _TEMPLATES.values()]


def get_template(template_id):
    try:
        return deepcopy(_TEMPLATES[template_id])
    except KeyError:
        raise ValueError("Unknown quantity template") from None


def wb_token_profile(token, *, authenticated_seller=None, now=None):
    """Read only the documented JWT claims, without treating decode as auth.

    Official 01-general.yaml defines acc/for/t and s/exp/sid. An unsigned local
    decode never grants permissions or increases quotas: seller-info must first
    authenticate this same token and return the same sid. No secret or complete
    JWT payload is returned. Unknown/old token formats keep the base ceilings.
    """
    profile = {"token_class": "base", "classification": "unknown", "service_id": None,
               "categories": [], "source": WB_DOC + "01-general.yaml", "verified_at": VERIFIED_AT}
    try:
        if not isinstance(token, str) or not 10 <= len(token) <= 32768:
            return profile
        parts = token.removeprefix("Bearer ").split(".")
        if len(parts) != 3 or not all(parts):
            return profile
        encoded = parts[1]
        raw = base64.b64decode(encoded + "="*((-len(encoded)) % 4), altchars=b"-_", validate=True)
        if len(raw) > 8192:
            return profile
        value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
        if type(value) is not dict:
            return profile
        acc, target, test = value.get("acc"), value.get("for"), value.get("t")
        sid, exp, bits = value.get("sid"), value.get("exp"), value.get("s")
        if type(acc) is not int or type(test) is not bool or not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", sid):
            return profile
        if type(exp) is not int or exp <= 0 or type(bits) is not int or bits < 0:
            return profile
        if acc == 2 and test is True and target is None:
            return dict(profile, classification="sandbox", expires_at=exp)
        candidate = "base" if acc == 1 and target is None and test is False else "personal" if acc == 3 and target == "self" and test is False else "service" if acc == 4 and isinstance(target, str) and re.fullmatch(r"asid:[A-Za-z0-9_-]{1,128}", target) and test is False else None
        if candidate is None:
            return profile
        if now is not None and exp <= now:
            return dict(profile, classification="expired", expires_at=exp)
        if authenticated_seller is None or str(authenticated_seller) != sid:
            return dict(profile, classification="decoded_unverified", expires_at=exp)
        names = {1: "Content", 2: "Analytics", 3: "Prices and Discounts", 4: "Marketplace", 5: "Statistics",
                 6: "Promotion", 7: "Feedbacks and Questions", 9: "Buyers Chat", 10: "Supplies", 11: "Buyers Returns",
                 12: "Documents", 13: "Finance", 16: "Users"}
        return dict(profile, token_class=candidate, classification="authenticated", expires_at=exp,
                    service_id=target[5:] if candidate == "service" else None,
                    categories=[name for bit, name in names.items() if bits & (1 << bit)], read_only=bool(bits & (1 << 30)))
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return profile


def quota_profile(template_id, stage, context=None):
    """Conservative pacing plus explicit provenance; token classes never multiply scope."""
    context = context or {}
    t = _TEMPLATES[template_id]
    if stage not in t["stages"]:
        raise ValueError("Unknown quantity stage")
    provider = t["provider"]
    interval, scope, documented = 1.0, "seller", True
    key = template_id + ":" + stage
    source = t["source"]
    headers = ["Retry-After"]
    if provider == "wb":
        basic = context.get("token_class", "base") not in ("personal", "service", "base_with_secret")
        intervals = {"WB-01": 86400 if basic else 60, "WB-02": .75,
                     "WB-03": 1800 if basic else 20, "WB-04": 43200 if basic else 60,
                     "WB-05": 900 if basic else (5 if stage == "poll" else 60)}
        interval = intervals[template_id]
        headers += ["X-Ratelimit-Retry", "X-Ratelimit-Reset", "X-Ratelimit-Remaining", "X-Ratelimit-Limit"]
    elif provider == "yandex_market":
        interval = {"YM-01": 36 if stage == "identity" else 3.6, "YM-02": .6,
                    "YM-03": .36, "YM-04": .72, "YM-05": 120 if stage == "generate" else .6,
                    "YM-06": 36 if stage.startswith("warehouses_") else 120 if stage in ("generate", "generate_current") else .6}[template_id]
        scope = "campaign" if template_id == "YM-04" else "business"
        if template_id == "YM-06" and stage.startswith("warehouses_"):
            source = YM_DOC + "reference/warehouses/" + ("getPartnerWarehouses" if stage == "warehouses_current" else "getPagedWarehouses")
        elif template_id == "YM-06" and stage == "generate":
            source = YM_DOC + "reference/reports/generateStocksOnWarehousesReport"
        if stage == "poll":
            key = "yandex:report-info"
            source = YM_DOC + "reference/reports/getReportInfo"
        headers += ["X-RateLimit-Resource-Until", "X-RateLimit-Resource-Remaining", "X-RateLimit-Resource-Limit"]
    else:
        # Public generic limit is 50/sec/Client-Id. The one/sec local ceiling is
        # deliberately stricter; individual method limits still require live
        # contract qualification and are never asserted as documented here.
        interval = 60 if stage == "generate" else 1
        documented = False
        source = OZ_RATE_SOURCE
        headers += ["Ratelimit-Remaining"]
    return {"key": key, "scope": scope, "interval": interval, "min_interval": interval,
            "max_concurrency": 1, "max_active_retries": 5, "max_cycle_seconds": 900,
            "backoff_base": 8, "backoff_cap": 900, "vendor_headers": headers,
            "rate_limit_statuses": [420, 429] if provider == "yandex_market" else [429],
            "source": source, "verified_at": VERIFIED_AT, "documented": documented,
            "token_class": context.get("token_class", "base") if provider == "wb" else None}


# The adapter implements only these read endpoints and report-generation
# endpoints. A structurally valid passport must not silently register a new
# marketplace mutation or omit one required stage of an existing adapter.
_ENDPOINTS = {
    "OZ-01": {"identity": ("POST", "/v1/roles")},
    "OZ-02": {"list": ("POST", "/v3/product/list"), "details": ("POST", "/v3/product/info/list")},
    "OZ-03": {"generate": ("POST", "/v1/report/postings/create"), "poll": ("POST", "/v1/report/info"), "download": ("GET", None)},
    "OZ-04": {"list": ("POST", "/v1/returns/list")},
    "OZ-05": {"fbo": ("POST", "/v2/posting/fbo/get"), "fbs": ("POST", "/v3/posting/fbs/get")},
    "OZ-06": {"fbo": ("POST", "/v3/posting/fbo/list"), "fbs": ("POST", "/v4/posting/fbs/list")},
    "OZ-07": {"list": ("POST", "/v4/product/info/stocks")},
    "WB-01": {"identity": ("GET", "/api/v1/seller-info")},
    "WB-02": {"list": ("POST", "/content/v2/get/cards/list")},
    "WB-03": {"list": ("POST", "/api/analytics/v3/sales-funnel/products")},
    "WB-04": {"list": ("POST", "/api/finance/v1/sales-reports/detailed")},
    "WB-05": {"generate": ("GET", "/api/v1/warehouse_remains"), "poll": ("GET", "/api/v1/warehouse_remains/tasks/{report_id}/status"), "download": ("GET", "/api/v1/warehouse_remains/tasks/{report_id}/download")},
    "YM-01": {"identity": ("POST", "/v2/auth/token"), "campaigns": ("GET", "/v2/campaigns")},
    "YM-02": {"list": ("POST", "/v2/businesses/{businessId}/offer-mappings")},
    "YM-03": {"list": ("POST", "/v1/businesses/{businessId}/orders")},
    "YM-04": {"list": ("GET", "/v2/campaigns/{campaignId}/returns")},
    "YM-05": {"generate": ("POST", "/v2/reports/goods-realization/generate"), "poll": ("GET", "/v2/reports/info/{report_id}"), "download": ("GET", None)},
    "YM-06": {"warehouses_current": ("POST", "/v3/businesses/{businessId}/warehouses"), "warehouses_legacy": ("POST", "/v2/businesses/{businessId}/warehouses"), "generate_current": ("POST", "/v3/businesses/{businessId}/reports/stocks/generate"), "generate": ("POST", "/v2/reports/stocks-on-warehouses/generate"), "poll": ("GET", "/v2/reports/info/{report_id}"), "download": ("GET", None)},
}
_ORIGINS = {"ozon": {OZ}, "yandex_market": {YM}, "wb": {
    "https://common-api.wildberries.ru", "https://content-api.wildberries.ru",
    "https://seller-analytics-api.wildberries.ru", "https://finance-api.wildberries.ru"}}
_DOC_HOSTS = {"ozon": {"docs.ozon.ru", "dev.ozon.ru"}, "wb": {"dev.wildberries.ru"},
              "yandex_market": {"yandex.ru", "www.yandex.ru"}}
_SCOPES = {"ozon": {"Seller", "Product read-only", "Report", "Returns read-only", "Posting FBO", "Posting FBS read-only"},
           "wb": {"any category", "Content", "Analytics", "Finance"},
           "yandex_market": {"any valid Api-Key scope", "offers-and-cards-management:read-only",
                              "inventory-and-order-processing:read-only", "finance-and-accounting"}}
_TEXT = {"type": "string", "minLength": 1, "maxLength": 12000, "pattern": r"\S"}
_TEXTS = {"type": "array", "minItems": 1, "uniqueItems": True, "items": _TEXT}
_DATE = {"type": "string", "format": "date"}
_SCHEMA_DOCUMENT = {"type": "object", "minProperties": 1, "required": ["type"],
                    "properties": {"type": {"const": "object"}}}


def _object(properties, optional=()):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": [key for key in properties if key not in optional]}


_STAGE_SCHEMA = _object({"method": {"enum": ["GET", "POST"]},
    "path": {"anyOf": [_TEXT, {"type": "null"}]}, "origin": {"anyOf": [_TEXT, {"type": "null"}]},
    "generate": {"type": "boolean"}, "download": {"type": "boolean"},
    "auth": {"enum": ["ozon", "wb", "yandex_market", "none"]}, "idempotent": {"type": "boolean"}})
_HISTORY_SCHEMA = _object({"axis": {"enum": ["snapshot", "in_process_at", "logistic_return_date", "order_creation", "order_cohort_interval", "realization_event", "return_update"]},
    "earliest": {"anyOf": [_DATE, {"type": "null"}]},
    "max_lookback_days": {"type": ["integer", "null"], "minimum": 1},
    "max_window_days": {"type": ["integer", "null"], "minimum": 1},
    "window_months": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
    "window_evidence": {"enum": ["accepted_donor_conservative_window", "documented", "not_applicable", "not_declared"]},
    "boundary_evidence": {"enum": ["documented", "not_applicable", "unknown"]},
    "timezone": {"const": "Europe/Moscow"}, "empty_window_is_history_boundary": {"const": False}})
_TEST_REFERENCE = {"type": "string", "pattern": r"^(?:tests|acceptance)\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"}
_TEST_SCHEMA = _object({
    "required": {"type": "array", "minItems": len(_REQUIRED_TESTS), "maxItems": len(_REQUIRED_TESTS),
                 "uniqueItems": True, "items": {"enum": _REQUIRED_TESTS}},
    "cases": _object({key: {"type": "array", "minItems": 1, "uniqueItems": True, "items": _TEST_REFERENCE}
                      for key in _REQUIRED_TESTS}),
    "na": _object({"generate_unknown": _TEXT, "corrupt_archive": _TEXT}, ("generate_unknown", "corrupt_archive"))})
_PASSPORT_SCHEMA = _object({
    "id": {"enum": list(_ENDPOINTS)}, "stable_id": {"enum": list(_ENDPOINTS)}, "version": {"const": VERSION},
    "kind": {"const": "internal_api"}, "provider": {"enum": list(_ORIGINS)}, "purpose": _TEXT,
    "handler": {"const": "market_quantity_providers.consume"},
    "effect": {"const": "read_marketplace_write_local_quantity_projection"}, "role": {"const": "workspace_owner"},
    "required_scope": _TEXTS, "required_scope_evidence": {"enum": ["accepted_runtime_hint_not_independently_documented", "official_documentation"]},
    "required": {"type": "boolean"}, "store_binding": {"const": "server-confirmed seller and generation"},
    "input_schema": _SCHEMA_DOCUMENT, "server_input_schema": _SCHEMA_DOCUMENT, "output_schema": _SCHEMA_DOCUMENT,
    "stages": {"type": "object", "minProperties": 1, "additionalProperties": _STAGE_SCHEMA},
    "initial_stage": _TEXT, "source": _TEXT, "sources": _TEXTS, "verified_at": _DATE, "live_verified": {"const": False},
    "history": _HISTORY_SCHEMA, "pagination": _TEXT, "terminal": _TEXT,
    "normalization": {"const": "market-quantity/v1"}, "deduplication": _TEXT,
    "minimal_fields": _TEXTS, "excluded_fields": _TEXTS,
    "error_policy": _object({key: {"const": value} for key, value in ERROR_POLICY.items()}),
    "progress_policy": _object({key: {"const": value} for key, value in PROGRESS_POLICY.items()}),
    "tests": _TEST_SCHEMA, "quota_profile": _object({"resolver": {"const": "market_quantity_registry.quota_profile"},
        "scope": {"const": "confirmed seller, never individual key"}}),
}, ("sources",))
_QUOTA_SCHEMA = _object({
    "key": _TEXT, "scope": {"enum": ["seller", "business", "campaign", "service"]},
    "interval": {"type": "number", "exclusiveMinimum": 0}, "min_interval": {"type": "number", "exclusiveMinimum": 0},
    "max_concurrency": {"type": "integer", "minimum": 1}, "max_active_retries": {"type": "integer", "minimum": 1, "maximum": 5},
    "max_cycle_seconds": {"type": "number", "exclusiveMinimum": 0}, "backoff_base": {"type": "number", "exclusiveMinimum": 0},
    "backoff_cap": {"type": "number", "exclusiveMinimum": 0}, "vendor_headers": _TEXTS,
    "rate_limit_statuses": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": [420, 429]}},
    "source": _TEXT, "verified_at": _DATE, "documented": {"type": "boolean"},
    "token_class": {"enum": [None, "base", "personal", "service", "base_with_secret"]},
})
_FORMAT_CHECKER = FormatChecker(formats=["date"])
_PASSPORT_VALIDATOR = Draft202012Validator(_PASSPORT_SCHEMA, format_checker=_FORMAT_CHECKER)
_QUOTA_VALIDATOR = Draft202012Validator(_QUOTA_SCHEMA, format_checker=_FORMAT_CHECKER)
_VALIDATED_SIGNATURE = None


def _invalid(tid, area):
    # Schema exceptions can echo arbitrary supplied values. Startup diagnostics
    # identify only the trusted template ID and a fixed section label.
    raise ValueError("Invalid quantity passport " + tid + ": " + area)


def _official_source(value, provider):
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.hostname in _DOC_HOSTS[provider] and
                url.username is None and url.password is None and url.port in (None, 443) and
                not url.fragment and not url.query and "\\" not in value and not any(ord(c) < 33 for c in value))
    except (TypeError, ValueError):
        return False


def _embedded_schema(schema, tid):
    try:
        Draft202012Validator.check_schema(schema)
        pending = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                # Validation must never resolve a network reference. The
                # existing server-schema 'guard' is a local annotation.
                if "$id" in node or "$dynamicRef" in node or "$recursiveRef" in node:
                    _invalid(tid, "schema references")
                if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
                    _invalid(tid, "schema dialect")
                if "$ref" in node:
                    ref = node["$ref"]
                    if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
                        _invalid(tid, "schema references")
                    target = schema
                    for part in ref[2:].split("/") if ref != "#" else ():
                        part = part.replace("~1", "/").replace("~0", "~")
                        target = target[int(part)] if isinstance(target, list) else target[part]
                    if not isinstance(target, (dict, bool)):
                        _invalid(tid, "schema references")
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
    except Exception:
        _invalid(tid, "embedded JSON schema")


def _policy_callables():
    # Lazy, fixed imports: providers import this registry, while runtime calls
    # validate_registry only after its Backend class has finished loading.
    # No string from a passport is ever imported or evaluated.
    from . import market_quantity_providers, market_quantity_runtime, market_rate_limit
    return market_quantity_providers.consume, market_rate_limit.classify, market_quantity_runtime.Backend._failure


def classify_error(template_id, *args, **kwargs):
    """Invoke the registered common policy, never a second decision engine."""
    policy = _TEMPLATES[template_id]["error_policy"]
    if policy.get("version") != VERSION or policy.get("classifier") != "market_rate_limit.classify":
        _invalid(template_id, "error policy")
    from . import market_rate_limit
    return market_rate_limit.classify(*args, **kwargs)


def validate_registry():
    """Fail closed at Backend startup and CI, including embedded contracts.

    Restoring a Backend for each durable step need not repeatedly compile every
    schema. Successful validation is reused only for identical declarations and
    identical registered callables. Corrupted/changed passports revalidate.
    """
    global _VALIDATED_SIGNATURE
    if set(_TEMPLATES) != set(_ENDPOINTS):
        raise ValueError("The quantity registry must contain all 18 templates")
    try:
        canonical = json.dumps(_TEMPLATES, sort_keys=True, ensure_ascii=True, allow_nan=False)
        handlers = _policy_callables()
    except Exception:
        raise ValueError("Invalid quantity registry serialization or handler") from None
    if not all(callable(handler) for handler in (*handlers, quota_profile)):
        raise ValueError("Invalid quantity registry callable handler")
    signature = (sha256(canonical.encode()).hexdigest(), *handlers, quota_profile)
    if signature == _VALIDATED_SIGNATURE:
        return True
    for tid, t in _TEMPLATES.items():
        if next(_PASSPORT_VALIDATOR.iter_errors(t), None):
            _invalid(tid, "passport schema")
        provider = {"OZ": "ozon", "WB": "wb", "YM": "yandex_market"}[tid[:2]]
        if t["id"] != tid or t["stable_id"] != tid or t["provider"] != provider:
            _invalid(tid, "identity")
        if not set(t["required_scope"]) <= _SCOPES[provider]:
            _invalid(tid, "scope")
        if t["required"] != (tid not in {"OZ-07", "WB-05", "YM-06"}):
            _invalid(tid, "required source")
        if any(not _official_source(value, provider) for value in [t["source"], *t.get("sources", [])]):
            _invalid(tid, "source provenance")
        for key in ("input_schema", "server_input_schema", "output_schema"):
            _embedded_schema(t[key], tid)
        if set(t["stages"]) != set(_ENDPOINTS[tid]) or t["initial_stage"] != next(iter(_ENDPOINTS[tid])):
            _invalid(tid, "required stages")
        for name, stage in t["stages"].items():
            if (stage["method"], stage["path"]) != _ENDPOINTS[tid][name]:
                _invalid(tid, "registered endpoint")
            generate = name in {"generate", "generate_current"}
            download = name == "download"
            if stage["generate"] != generate or stage["download"] != download or stage["idempotent"] != (not generate):
                _invalid(tid, "stage effects")
            if stage["path"] is None:
                if stage["origin"] is not None or stage["auth"] != "none" or not download:
                    _invalid(tid, "signed download")
            elif stage["origin"] not in _ORIGINS[provider] or stage["auth"] != provider:
                _invalid(tid, "stage origin or authentication")
            for token_class in ("base", "personal", "service", "base_with_secret") if provider == "wb" else (None,):
                try:
                    profile = quota_profile(tid, name, {"token_class": token_class} if token_class else {})
                    json.dumps(profile, allow_nan=False)
                    valid = not next(_QUOTA_VALIDATOR.iter_errors(profile), None)
                    valid = valid and profile["interval"] == profile["min_interval"] and profile["backoff_cap"] >= profile["backoff_base"]
                    valid = valid and profile["token_class"] == token_class and _official_source(profile["source"], provider)
                    valid = valid and profile["rate_limit_statuses"] == ([420, 429] if provider == "yandex_market" else [429])
                except Exception:
                    valid = False
                if not valid:
                    _invalid(tid, "resolved quota profile")
        history = t["history"]
        bounded = history["earliest"] is not None or history["max_lookback_days"] is not None
        if history["earliest"] is not None and history["max_lookback_days"] is not None:
            _invalid(tid, "history boundary")
        boundary = "documented" if bounded else "not_applicable" if history["axis"] == "snapshot" else "unknown"
        window = "accepted_donor_conservative_window" if tid == "OZ-03" else "documented" if history["max_window_days"] or history["window_months"] else "not_applicable" if history["axis"] == "snapshot" else "not_declared"
        if history["boundary_evidence"] != boundary or history["window_evidence"] != window:
            _invalid(tid, "history provenance")
        if history["axis"] == "snapshot" and (bounded or history["max_window_days"] or history["window_months"]):
            _invalid(tid, "snapshot history")
        expected_na = set()
        if not any(s["generate"] for s in t["stages"].values()):expected_na.add("generate_unknown")
        if not any(s["download"] for s in t["stages"].values()):expected_na.add("corrupt_archive")
        if set(t["tests"]["na"]) != expected_na:
            _invalid(tid, "test applicability")
        if set(t["minimal_fields"]) != {"IDs", "SKU", "category", "quantities", "dates", "status", "coverage", "schema_version"}:
            _invalid(tid, "quantity projection")
        if set(t["excluded_fields"]) != {"credentials", "buyer PII", "commissions", "payments", "advertising", "logistics amounts"}:
            _invalid(tid, "excluded data")
    _VALIDATED_SIGNATURE = signature
    return True
