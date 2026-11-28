"""Provider wire contracts with synthetic data; live acceptance is separate.

The real queue, limiter, credentials, lease and restart fault matrix lives in
test_market_quantity_runtime. These tests exercise the pure adapters, their
request boundaries, state machines, normalization and non-financial projection.
"""
from copy import deepcopy
import base64
import io
import json
import unittest
import zipfile

from platform_core import market_quantity_providers as p
from platform_core import market_quantity_registry as reg
from tests.fixtures import market_quantity_cases as f


def reply(payload, code=200):
    return {"status_code": code, "headers": {}, "payload": payload}


def advance(tid, cp, context, payload):
    return p.consume(tid, cp, context, reply(payload))


def generated_checkpoint(tid, context):
    return deepcopy(next(step["outcome"]["checkpoint"] for step in f.success_sequence(tid, context)
                         if step["request"]["generate"]))


class ProviderContracts(unittest.TestCase):
    def test_all_eighteen_passports_are_complete_and_private(self):
        self.assertTrue(reg.validate_registry())
        self.assertEqual({t["id"] for t in reg.templates()}, set(f.TEMPLATES))
        for t in reg.templates():
            self.assertFalse(t["live_verified"])
            self.assertTrue(t["source"].startswith("https://"))
            self.assertFalse(t["history"]["empty_window_is_history_boundary"])
            for error in ("429", "420", "401", "403", "timeout", "invalid_json", "unknown_schema", "generate_unknown"):
                self.assertIn(error, t["error_policy"])
            self.assertIn("posting_number", t["server_input_schema"]["properties"])
            self.assertNotIn("posting_number", t["input_schema"]["properties"])
            for stage in t["stages"]:
                q = reg.quota_profile(t["id"], stage)
                self.assertGreater(q["min_interval"], 0)
                self.assertLessEqual(q["max_active_retries"], 5)
                self.assertGreater(q["max_cycle_seconds"], 0)
        copied = reg.get_template("WB-03")
        copied["history"]["max_lookback_days"] = 0
        self.assertEqual(reg.get_template("WB-03")["history"]["max_lookback_days"], 365)

    def test_documented_history_boundaries_never_invent_earliest_date(self):
        self.assertEqual(reg.get_template("WB-04")["history"]["earliest"], "2024-01-29")
        self.assertEqual(reg.get_template("WB-03")["history"]["max_lookback_days"], 365)
        for tid in ("OZ-03", "OZ-04", "OZ-06", "YM-03", "YM-04", "YM-05"):
            history = reg.get_template(tid)["history"]
            self.assertIsNone(history["earliest"])
            self.assertEqual(history["boundary_evidence"], "unknown")
        self.assertEqual(reg.get_template("YM-03")["history"]["max_window_days"], 30)

    def test_basic_wb_limits_and_shared_yandex_poll(self):
        expected = {"WB-01": 86400, "WB-03": 1800, "WB-04": 43200, "WB-05": 900}
        for tid, seconds in expected.items():
            stage = reg.get_template(tid)["initial_stage"]
            self.assertEqual(reg.quota_profile(tid, stage)["min_interval"], seconds)
            self.assertLess(reg.quota_profile(tid, stage, {"token_class": "personal"})["min_interval"], seconds)
        self.assertEqual(reg.quota_profile("YM-05", "poll")["key"], reg.quota_profile("YM-06", "poll")["key"])
        self.assertEqual(reg.quota_profile("YM-03", "list")["rate_limit_statuses"], [420, 429])

    def test_documented_wb_token_claims_require_authenticated_seller(self):
        def token(**changes):
            claims = {"acc": 3, "for": "self", "t": False, "sid": "test-seller-uuid", "exp": f.NOW+86400,
                      "s": (1 << 1) | (1 << 2) | (1 << 13) | (1 << 30)}
            claims.update(changes)
            encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            return "header."+encoded+".synthetic-signature"
        private = token()
        self.assertEqual(reg.wb_token_profile(private, now=f.NOW)["token_class"], "base")
        self.assertEqual(reg.wb_token_profile(private, authenticated_seller="other-seller", now=f.NOW)["token_class"], "base")
        actual = reg.wb_token_profile(private, authenticated_seller="test-seller-uuid", now=f.NOW)
        self.assertEqual(actual["token_class"], "personal")
        self.assertEqual(actual["classification"], "authenticated")
        self.assertEqual(actual["categories"], ["Content", "Analytics", "Finance"])
        self.assertTrue(actual["read_only"])
        self.assertNotIn(private, json.dumps(actual))
        service = reg.wb_token_profile(token(acc=4, **{"for": "asid:service-one"}), authenticated_seller="test-seller-uuid", now=f.NOW)
        self.assertEqual((service["token_class"], service["service_id"]), ("service", "service-one"))
        for raw in ("", "opaque-old-token", "header.evil*.sig", token(acc=99), token(t=True), token(exp=f.NOW-1)):
            self.assertEqual(reg.wb_token_profile(raw, authenticated_seller="test-seller-uuid", now=f.NOW)["token_class"], "base")
        sandbox = reg.wb_token_profile(token(acc=2, t=True, **{"for": None}), now=f.NOW)
        self.assertEqual(sandbox["classification"], "sandbox")

    def test_service_limit_is_a_separate_shared_scope(self):
        c = f.context_for("WB-03", token_class="service", service_id="service-one")
        req = p.request("WB-03", {}, c)
        self.assertEqual({q["scope"] for q in req["quota_scopes"]}, {"seller", "service"})
        c.pop("service_id")
        with self.assertRaises(p.AdapterError):
            p.request("WB-03", {}, c)

    def test_wb_get_generation_is_non_idempotent_and_no_duplicate_quota(self):
        request = p.request("WB-05", {}, f.context_for("WB-05"))
        self.assertEqual(request["method"], "GET")
        self.assertTrue(request["generate"])
        self.assertFalse(request["idempotent"])
        self.assertEqual(len(request["quota_scopes"]), 1)

    def test_current_ozon_posting_versions_and_safe_quantity_flags(self):
        c = f.context_for("OZ-06")
        a = p.request("OZ-06", {}, c)
        self.assertTrue(a["url"].endswith("/v3/posting/fbo/list"))
        out = p.consume("OZ-06", {}, c, reply({"postings": [], "has_next": False, "cursor": ""}))
        b = p.request("OZ-06", out["checkpoint"], c)
        self.assertTrue(b["url"].endswith("/v4/posting/fbs/list"))
        for req in (a, b):
            self.assertEqual(req["json"]["limit"], 100)
            self.assertFalse(req["json"]["with"]["financial_data"])
            self.assertNotIn("offset", req["json"])

    def test_yandex_modern_date_parameters_and_half_open_order_interval(self):
        c = f.context_for("YM-03")
        req = p.request("YM-03", {}, c)
        self.assertEqual(req["json"]["dates"], {"creationDateFrom": "2026-10-01", "creationDateTo": "2026-10-31"})
        self.assertFalse(req["json"]["fake"])
        self.assertEqual(req["json"]["sourcePlatforms"], ["MARKET"])
        req = p.request("YM-04", {}, c)
        self.assertEqual(req["params"]["fromDate"], "2026-10-01")
        self.assertNotIn("from_date", req["params"])
        for tid, changes in (("YM-03", {"to": "2026-10-31"}), ("WB-03", {"from": "2025-01-01"}), ("WB-04", {"from": "2024-01-01"})):
            with self.assertRaises(p.AdapterError):
                p.request(tid, {}, f.context_for(tid, **changes))

    def test_yandex_laas_foreign_source_orders_cannot_double_count_marketplaces(self):
        c = f.context_for("YM-03")
        for source in ("OZON", "WILDBERRIES", "OTHER", "UNKNOWN"):
            with self.subTest(source=source), self.assertRaises(p.AdapterError):
                advance("YM-03", {}, c, {"orders": [f.yandex_order(c, sourcePlatform=source)]})

    def test_wb_finance_quantity_fields_not_economic_fields(self):
        req = p.request("WB-04", {}, f.context_for("WB-04"))
        fields = req["json"]["fields"]
        self.assertIn("sellerOperName", fields)
        for field in fields:
            self.assertFalse(any(x in field.lower() for x in ("price", "commission", "amount", "deliveryrub", "paid")))

    def test_report_ids_survive_pending_restart_and_expired_url(self):
        for tid in ("OZ-03", "WB-05", "YM-05", "YM-06"):
            with self.subTest(tid=tid):
                c = f.context_for(tid)
                cp = json.loads(json.dumps(generated_checkpoint(tid, c)))
                report_id = cp["report_id"]
                pending = {"data": {"id": report_id, "status": "processing"}} if tid == "WB-05" else {"result": {"status": "PROCESSING"}}
                wait = advance(tid, cp, c, pending)
                self.assertEqual(wait["checkpoint"]["report_id"], report_id)
                self.assertFalse(wait["complete"])
                self.assertGreater(wait["next_due"], c["now"])
                req = p.request(tid, wait["checkpoint"], c)
                self.assertFalse(req["generate"])
                done = p.consume(tid, wait["checkpoint"], c, f.response_for(tid, req, c))
                self.assertEqual(done["checkpoint"]["stage"], "download")
                if tid != "WB-05":
                    self.assertEqual(p.request(tid, done["checkpoint"], c)["auth"], "none")
                    later = dict(c, now=done["checkpoint"]["url_expires_at"]+1)
                    refresh = p.request(tid, done["checkpoint"], later)
                    self.assertEqual(refresh["stage"], "poll")
                    self.assertFalse(refresh["generate"])
                    renewed = p.consume(tid, done["checkpoint"], later, f.response_for(tid, refresh, later))
                    self.assertEqual(renewed["checkpoint"]["report_id"], report_id)

    def test_report_failures_and_unknown_status_are_not_zero_success(self):
        for tid in ("OZ-03", "WB-05", "YM-05", "YM-06"):
            c = f.context_for(tid)
            cp = generated_checkpoint(tid, c)
            for status in ("failed", "FAILED", "purged", "unknown"):
                payload = {"data": {"id": cp["report_id"], "status": status}} if tid == "WB-05" else {"result": {"status": status}}
                with self.subTest(tid=tid, status=status), self.assertRaises(p.AdapterError):
                    advance(tid, cp, c, payload)
        for tid in ("YM-05", "YM-06"):
            c = f.context_for(tid)
            cp = generated_checkpoint(tid, c)
            for status in ("FAILED", "DONE"):
                zero = advance(tid, cp, c, {"result": {"status": status, "subStatus": "NO_DATA"}})
                self.assertTrue(zero["complete"])
                self.assertTrue(zero["coverage"]["zero_confirmed"])
                self.assertEqual(zero["coverage"]["from"], c["from"])
                self.assertEqual(zero["coverage"]["to"], c["to"])
            waiting = advance(tid, cp, c, {"result": {"status": "PROCESSING", "subStatus": "NO_DATA"}})
            self.assertFalse(waiting["complete"])
            with self.assertRaises(p.AdapterError):
                advance(tid, cp, c, {"result": {"status": "DONE"}})

    def test_report_ids_cannot_be_urls_or_unstructured_payloads(self):
        for tid in ("OZ-03", "WB-05", "YM-05", "YM-06"):
            c = f.context_for(tid)
            step = next(x for x in f.success_sequence(tid, c) if x["request"]["generate"])
            previous = {} if tid != "YM-06" else f.success_sequence(tid, c)[0]["outcome"]["checkpoint"]
            for bad in ("https://provider.invalid/file?secret=value", "report id", "key=value", "bad\nvalue"):
                response = deepcopy(step["response"])
                if tid == "WB-05":
                    response["payload"]["data"]["taskId"] = bad
                elif tid == "OZ-03":
                    response["payload"]["result"]["code"] = bad
                else:
                    response["payload"]["result"]["reportId"] = bad
                with self.subTest(tid=tid), self.assertRaises(p.AdapterError):
                    p.consume(tid, previous, c, response)

    def test_report_download_urls_are_private_and_cannot_escape(self):
        c = f.context_for("YM-05")
        seq = f.success_sequence("YM-05", c)
        cp = seq[0]["outcome"]["checkpoint"]
        for url in ("http://storage.yandexcloud.net/a", "https://evil.invalid/a", "https://storage.yandexcloud.net.evil.invalid/a",
                    "https://user:pass@storage.yandexcloud.net/a", "https://storage.yandexcloud.net:444/a", "https://storage.yandexcloud.net/a#fragment",
                    "https://storage.yandexcloud.net/\\evil"):
            with self.subTest(url=url), self.assertRaises(p.AdapterError):
                advance("YM-05", cp, c, {"result": {"status": "DONE", "file": url}})
        final = seq[-1]["outcome"]
        self.assertNotIn("grant_url", final["checkpoint"])
        self.assertNotIn("https://", json.dumps(final["rows"]))

    def test_live_ozon_report_origin_is_allowed_without_authentication(self):
        c = f.context_for("OZ-03")
        cp = generated_checkpoint("OZ-03", c)
        out = advance("OZ-03", cp, c, {"result": {"status": "success", "file": "https://ir.ozone.ru/s3/synthetic.csv?signature=test"}})
        req = p.request("OZ-03", out["checkpoint"], c)
        self.assertEqual(req["auth"], "none")
        self.assertTrue(req["download"])
        for url in ("https://ir.ozone.ru.evil.invalid/test.csv", "http://ir.ozone.ru/test.csv", "https://ir.ozone.ru:444/test.csv"):
            with self.assertRaises(p.AdapterError):
                advance("OZ-03", cp, c, {"result": {"status": "success", "file": url}})

    def test_live_yandex_private_mds_report_origin_is_allowed_without_authentication(self):
        c = f.context_for("YM-06")
        cp = generated_checkpoint("YM-06", c)
        url = "https://market-mbi-prod.s3-private.mds.yandex.net/synthetic.zip?signature=test"
        out = advance("YM-06", cp, c, {"result": {"status": "DONE", "file": url}})
        req = p.request("YM-06", out["checkpoint"], c)
        self.assertEqual(req["url"], url)
        self.assertEqual(req["auth"], "none")
        with self.assertRaises(p.AdapterError):
            p._grant_url(url.replace("mds.yandex.net", "mds.yandex.net.evil.invalid"), "yandex_market")

    def test_ozon_fbo_and_fbs_reports_are_both_required(self):
        seq = f.success_sequence("OZ-03")
        self.assertEqual([s["request"]["stage"] for s in seq], ["generate", "poll", "download"]*2)
        self.assertFalse(seq[2]["outcome"]["complete"])
        self.assertTrue(seq[5]["outcome"]["complete"])
        self.assertEqual({r["scheme"] for s in seq for r in s["outcome"]["rows"]}, {"FBO", "FBS"})
        self.assertEqual(seq[3]["request"]["json"]["filter"]["delivery_schema"], ["fbs"])

    def test_wb_finance_short_page_is_not_terminal(self):
        c = f.context_for("WB-04")
        out = advance("WB-04", {}, c, [f.wb_realization()])
        self.assertFalse(out["complete"])
        self.assertEqual(out["checkpoint"]["cursor"], 1)
        with self.assertRaises(p.AdapterError):
            advance("WB-04", out["checkpoint"], c, [])
        done = p.consume("WB-04", out["checkpoint"], c, reply(None, 204))
        self.assertTrue(done["complete"])
        self.assertFalse(done["coverage"]["zero_confirmed"])
        self.assertEqual(out["rows"][0]["report_id"], "2259007199254740993")

    def test_wb_finance_ignores_nonquantity_adjustments(self):
        c = f.context_for("WB-04")
        adjustment = f.wb_realization()
        adjustment.update(sellerOperName="Логистика", quantity=9999, nmId=0)
        out = advance("WB-04", {}, c, [adjustment])
        self.assertEqual(out["rows"], [])
        self.assertFalse(out["complete"])
        self.assertEqual(out["checkpoint"]["cursor"], 1)

    def test_wb_realization_return_is_not_physical_logistics_evidence(self):
        c = f.context_for("WB-04")
        rows = advance("WB-04", {}, c, [f.wb_realization(), f.wb_realization(2, "Возврат")])["rows"]
        self.assertEqual(sum(r["delivered_qty"] for r in rows), 3)
        self.assertEqual(sum(r["calendar_return_qty"] for r in rows), 1)
        self.assertIsNone(rows[1]["physical_return_qty"])
        self.assertTrue(all(not row["physical_returns_known"] for row in rows))

    def test_wb_funnel_is_not_gross_delivery_or_physical_returns(self):
        c = f.context_for("WB-03")
        out = advance("WB-03", {}, c, {"data": {"products": [f.wb_funnel(c, ordered=100, lost=30, buyout=70)]}})
        row = out["rows"][0]
        self.assertEqual(row["quantity_basis"], "funnel_interval")
        self.assertEqual((row["ordered_qty"], row["lost_qty"], row["buyout_qty"]), (100, 30, 70))
        self.assertIsNone(row["delivered_qty"])
        self.assertIsNone(row["physical_return_qty"])
        self.assertFalse(row["physical_returns_known"])
        self.assertTrue(row["terminal"])
        bad = f.wb_funnel(c)
        bad["statistic"]["selected"]["period"]["start"] = "2026-09-01"
        with self.assertRaises(p.AdapterError):
            advance("WB-03", {}, c, {"data": {"products": [bad]}})

    def test_wb_funnel_offset_and_known_unknown_units(self):
        c = f.context_for("WB-03")
        batch = [f.wb_funnel(c, n=n+1, ordered=10, lost=1, buyout=8) for n in range(1000)]
        out = advance("WB-03", {}, c, {"data": {"products": batch}})
        self.assertFalse(out["complete"])
        self.assertEqual(p.request("WB-03", out["checkpoint"], c)["json"]["offset"], 1000)
        self.assertEqual(out["rows"][0]["unresolved_qty"], 1)
        self.assertFalse(out["rows"][0]["terminal"])
        with self.assertRaises(p.AdapterError):
            advance("WB-03", out["checkpoint"], c, {"data": {"products": batch}})
        done = advance("WB-03", out["checkpoint"], c, {"data": {"products": []}})
        self.assertTrue(done["complete"])
        self.assertEqual(done["coverage"]["rows"], 1000)

    def test_wb_oldest_365_day_window_has_explicit_preceding_comparison_and_preserves_selected_units(self):
        for end in ("2025-12-27", "2026-11-27"):
            with self.subTest(end=end):
                c = f.context_for("WB-03", **{"from": "2025-11-28", "to": end})
                requested = p.request("WB-03", {}, c)
                period = {"start": "2025-11-28", "end": end}
                past = {"start": "2025-11-27", "end": "2025-11-27"}
                self.assertEqual(requested["json"]["selectedPeriod"], period)
                self.assertEqual(requested["json"]["pastPeriod"], past)
                product = f.wb_funnel(c, ordered=123, lost=17, buyout=100)
                product["statistic"]["past"] = {"period": past, "orderCount": 999, "cancelCount": 888, "buyoutCount": 777}
                row = advance("WB-03", {}, c, {"data": {"products": [product]}})["rows"][0]
                self.assertEqual((row["ordered_qty"], row["lost_qty"], row["buyout_qty"], row["unresolved_qty"]), (123, 17, 100, 6))
                self.assertEqual((row["interval_from"], row["interval_to"]), (period["start"], period["end"]))
                self.assertIsNone(row["physical_return_qty"])
                self.assertFalse(row["physical_returns_known"])

    def test_ozon_returns_exact_exemplars_and_physical_classification(self):
        c = f.context_for("OZ-04")
        one = advance("OZ-04", {}, c, {"returns": [f.ozon_return()], "has_next": False})["rows"][0]
        self.assertEqual(one["physical_return_qty"], 1)
        self.assertEqual(one["unit_ids"], ["6001"])
        nonbuyout = f.ozon_return(type="FullReturn")
        r = advance("OZ-04", {}, c, {"returns": [nonbuyout], "has_next": False})["rows"][0]
        self.assertIsNone(r["physical_return_qty"])
        self.assertFalse(r["physical_returns_known"])
        cancelled = f.ozon_return(visual={"status": {"sys_name": "Cancelled"}})
        r = advance("OZ-04", {}, c, {"returns": [cancelled], "has_next": False})["rows"][0]
        self.assertTrue(r["complete"])
        self.assertEqual(r["loss_event_qty"], 0)
        for units in ([], [{"exemplar_id": 1}, {"exemplar_id": 1}], [{"exemplar_id": 1}, {"exemplar_id": 2}]):
            with self.assertRaises(p.AdapterError):
                advance("OZ-04", {}, c, {"returns": [f.ozon_return(exemplars=units)], "has_next": False})

    def test_ozon_return_cursor_restart_does_not_repeat_first_page(self):
        c = f.context_for("OZ-04")
        out = advance("OZ-04", {}, c, {"returns": [f.ozon_return()], "has_next": True})
        cp = json.loads(json.dumps(out["checkpoint"]))
        self.assertEqual(p.request("OZ-04", cp, c)["json"]["last_id"], 8001)
        done = advance("OZ-04", cp, c, {"returns": [f.ozon_return(id=8002, exemplars=[{"exemplar_id": 6002}])], "has_next": False})
        self.assertTrue(done["complete"])
        with self.assertRaises(p.AdapterError):
            advance("OZ-04", cp, c, {"returns": [f.ozon_return()], "has_next": True})

    def test_yandex_unit_outcomes_preserve_original_denominator(self):
        c = f.context_for("YM-03")
        row = advance("YM-03", {}, c, {"orders": [f.yandex_order(c)]})["rows"][0]
        self.assertEqual((row["ordered_qty"], row["delivered_qty"], row["physical_return_qty"], row["nonbuyout_qty"], row["lost_qty"]), (5, 4, 1, 1, 2))
        self.assertTrue(row["complete"])
        unknown = f.yandex_order(c)
        unknown["items"][0].pop("itemStatuses")
        row = advance("YM-03", {}, c, {"orders": [unknown]})["rows"][0]
        self.assertEqual(row["ordered_qty"], 5)
        self.assertFalse(row["complete"])
        self.assertFalse(row["terminal"])
        self.assertIsNone(row["delivered_qty"])
        self.assertIsNone(row["lost_qty"])
        for changes in ({"fake": True}, {"campaignId": 456}, {"creationDate": "2026-09-01T10:00:00Z"}):
            with self.assertRaises(p.AdapterError):
                advance("YM-03", {}, c, {"orders": [f.yandex_order(c, **changes)]})

    def test_yandex_unknown_unit_status_rejected_and_partial_count_explicit(self):
        c = f.context_for("YM-03")
        bad = f.yandex_order(c)
        bad["items"][0]["itemStatuses"][0]["status"] = "NEW_STATUS_2027"
        with self.assertRaises(p.AdapterError):
            advance("YM-03", {}, c, {"orders": [bad]})
        bad = f.yandex_order(c)
        bad["items"][0]["count"] = 10
        row = advance("YM-03", {}, c, {"orders": [bad]})["rows"][0]
        self.assertFalse(row["complete"])
        self.assertEqual(row["ordered_qty"], 10)
        self.assertIsNone(row["lost_qty"])

    def test_yandex_fast_return_refund_never_proves_physical_return(self):
        c = f.context_for("YM-04")
        for changes, expected in (({}, 1), ({"fastReturn": True}, 0), ({"shipmentStatus": "CREATED"}, None),
                                  ({"returnType": "UNREDEEMED"}, 0), ({"shipmentStatus": "CANCELLED"}, 0)):
            with self.subTest(changes=changes):
                row = advance("YM-04", {}, c, {"result": {"returns": [f.yandex_return(c, **changes)]}})["rows"][0]
                self.assertEqual(row["physical_return_qty"], expected)
                if changes.get("returnType") == "UNREDEEMED":
                    self.assertEqual(row["nonbuyout_qty"], 1)
                if changes.get("shipmentStatus") == "CREATED":
                    self.assertFalse(row["physical_returns_known"])

    def test_yandex_fast_return_is_complete_zero_material_event_during_refund(self):
        c = f.context_for("YM-04")
        for shipment in ("CREATED", "IN_TRANSIT", "PICKED", None):
            with self.subTest(shipment=shipment):
                event = f.yandex_return(c, fastReturn=True, shipmentStatus=shipment, refundStatus="STARTED_BY_USER")
                row = advance("YM-04", {}, c, {"result": {"returns": [event]}})["rows"][0]
                self.assertEqual((row["physical_return_qty"], row["nonbuyout_qty"], row["loss_event_qty"]), (0, 0, 0))
                self.assertTrue(row["physical_returns_known"])
                self.assertTrue(row["terminal"])
                self.assertTrue(row["complete"])

    def test_yandex_monthly_report_remains_calendar_basis(self):
        seq = f.success_sequence("YM-05")
        rows = seq[-1]["outcome"]["rows"]
        self.assertEqual(sum(r["delivered_qty"] for r in rows), 5)
        self.assertEqual(sum(r["physical_return_qty"] for r in rows), 1)
        self.assertEqual(sum(r["nonbuyout_qty"] for r in rows), 2)
        for row in rows:
            self.assertEqual(row["quantity_basis"], "calendar_event")
            self.assertIsNone(row["ordered_qty"])
            self.assertFalse(row["original_order_known"])
            self.assertNotIn("ordered_at", row)

    def test_stocks_distinguish_aggregate_transit_available_and_physical(self):
        rows = f.success_sequence("WB-05")[-1]["outcome"]["rows"]
        self.assertEqual({r["stock_kind"] for r in rows}, {"aggregate", "warehouse", "in_transit"})
        self.assertEqual(sum(r["stock_qty"] for r in rows if r["stock_kind"] == "warehouse"), 10)
        for fby in (False, True):
            c = f.context_for("YM-06", placementType="FBY" if fby else "FBS")
            seq = f.success_sequence("YM-06", c)
            req, row = next(step["request"] for step in seq if step["request"]["generate"]), seq[-1]["outcome"]["rows"][0]
            self.assertNotIn("hasStocks", req["json"])
            self.assertEqual(row["stock_kind"], "physical_valid" if fby else "available")
            self.assertEqual(row["available_qty"], 8)
            self.assertEqual(row["reserved_qty"], 2)
            self.assertEqual(row["stock_qty"], 10 if fby else 8)
            self.assertEqual("campaignId" in req["json"], fby)
            self.assertEqual("partnerWarehouseIds" in req["json"], not fby)
        c = f.context_for("OZ-07")
        bad = f.response_for("OZ-07", p.request("OZ-07", {}, c), c)
        bad["payload"]["items"][0]["stocks"][0].pop("sku")
        with self.assertRaises(p.AdapterError):
            p.consume("OZ-07", {}, c, bad)

    def test_wb_stock_barcodes_share_sku_without_losing_or_duplicating_units(self):
        c = f.context_for("WB-05")
        cp = f.success_sequence("WB-05", c)[1]["outcome"]["checkpoint"]
        items = [{"nmId": 101, "barcode": barcode, "warehouses": [{"warehouseName": "Коледино", "quantity": n}]}
                 for barcode, n in (("size-s", 3), ("size-m", 7))]
        out = advance("WB-05", cp, c, items)
        self.assertTrue(out["complete"])
        self.assertEqual(len({r["natural_key"] for r in out["rows"]}), 2)
        self.assertEqual(sum(r["stock_qty"] for r in out["rows"]), 10)
        self.assertEqual({r["sku"] for r in out["rows"]}, {"101"})

    def test_yandex_stock_report_does_not_sum_different_report_representations(self):
        c = f.context_for("YM-06")
        cp = next(step["outcome"]["checkpoint"] for step in f.success_sequence("YM-06", c) if step["request"]["stage"] == "poll")
        raw = f.zip_bytes({name: f.csv_bytes(["SHOP_SKU", "COUNT", "WAREHOUSE_AND_SHOP"], [["A", 10, "warehouse"]])
                           for name in ("stocks_business.csv", "mass_shared_stocks.csv")})
        with self.assertRaises(p.AdapterError):
            p.consume("YM-06", cp, c, {"status_code": 200, "content": raw})

    def test_yandex_stock_variants_use_proven_campaign_scope_and_quotas(self):
        for groups in (False, True):
            c = f.context_for("YM-06", warehouse_groups=groups)
            seq = f.success_sequence("YM-06", c)
            expected = (["warehouses_current", "warehouses_legacy", "generate"] if groups else
                        ["warehouses_current", "generate_current"]) + ["poll", "download"]
            self.assertEqual([step["request"]["stage"] for step in seq], expected)
            req = next(step["request"] for step in seq if step["request"]["generate"])
            self.assertEqual(req["quota_profile"]["min_interval"], 120)
            self.assertEqual(req["json"], {"businessId": 12, "campaignIds": [123]} if groups else {"partnerWarehouseIds": [501]})
            self.assertEqual(seq[0]["request"]["quota_profile"]["min_interval"], 36)
            self.assertNotIn("components", seq[0]["request"]["json"])
            self.assertEqual(seq[-1]["outcome"]["coverage"]["rows"], 1)

    def test_yandex_warehouse_discovery_paginates_and_cannot_bind_unknown_campaign(self):
        c = f.context_for("YM-06")
        first = {"result": {"warehouses": [{"id": 501, "models": [{"placementType": "FBS", "campaignId": 123}]}],
                            "paging": {"nextPageToken": "page-two"}}}
        out = advance("YM-06", {}, c, first)
        self.assertEqual(p.request("YM-06", out["checkpoint"], c)["params"]["pageToken"], "page-two")
        self.assertEqual(out["coverage"]["rows"], 0)
        with self.assertRaises(p.AdapterError):
            advance("YM-06", out["checkpoint"], c, first)
        second = {"result": {"warehouses": [{"id": 502, "models": [{"placementType": "FBS", "campaignId": 123}]}]}}
        done = advance("YM-06", out["checkpoint"], c, second)
        self.assertEqual(p.request("YM-06", done["checkpoint"], c)["json"], {"partnerWarehouseIds": [501, 502]})
        unknown = advance("YM-06", {}, c, {"result": {"warehouses": [{"id": 501, "models": [{"placementType": "FBS"}]}]}})
        self.assertEqual(unknown["checkpoint"]["stage"], "warehouses_legacy")
        self.assertFalse(unknown["coverage"]["zero_confirmed"])
        with self.assertRaises(p.AdapterError):
            advance("YM-06", unknown["checkpoint"], c, {"result": {"warehouses": []}})
        with self.assertRaises(p.AdapterError):
            advance("YM-06", unknown["checkpoint"], c, {"result": {"warehouses": [{"id": 601, "campaignId": 999, "groupInfo": {"id": 701}}]}})

    def test_failed_unqualified_legacy_stock_report_is_retained_before_discovery(self):
        c = f.context_for("YM-06")
        old = {"stage": "poll", "report_id": "known-failed-legacy-id"}
        out = advance("YM-06", old, c, {"result": {"status": "FAILED"}})
        self.assertEqual(out["checkpoint"]["failed_legacy_report"]["id"], old["report_id"])
        self.assertEqual(out["checkpoint"]["stage"], "warehouses_current")
        self.assertFalse(out["complete"])
        req = p.request("YM-06", out["checkpoint"], c)
        self.assertFalse(req["generate"])
        scoped = p.consume("YM-06", out["checkpoint"], c, f.response_for("YM-06", req, c))
        self.assertEqual(scoped["checkpoint"]["stage"], "generate_current")
        self.assertEqual(scoped["checkpoint"]["failed_legacy_report"]["id"], old["report_id"])
        with self.assertRaises(p.AdapterError):
            advance("YM-06", old, c, {"result": {"status": "DONE", "subStatus": "NO_DATA"}})
        cp = dict(scoped["checkpoint"], stage="generate", warehouse_groups_verified=True)
        with self.assertRaises(p.AdapterError):
            p.request("YM-06", cp, c)

    def test_current_stock_report_requires_and_filters_placement_column(self):
        c = f.context_for("YM-06")
        cp = next(step["outcome"]["checkpoint"] for step in f.success_sequence("YM-06", c) if step["request"]["stage"] == "poll")
        columns = ["SHOP_SKU", "COUNT", "WAREHOUSE_AND_SHOP", "PLACEMENT_TYPE", "PRODUCT_NAME", "ERRORS", "RESERVE"]
        raw = f.zip_bytes({"stocks_business.csv": f.csv_bytes(columns, [["A", 4, "w", "FBS", "A", "", 0], ["A", 9, "w", "DBS", "A", "", 0]])})
        out = p.consume("YM-06", cp, c, {"status_code": 200, "content": raw})
        self.assertEqual(sum(row["stock_qty"] for row in out["rows"]), 4)
        raw = f.zip_bytes({"stocks_business.csv": f.csv_bytes(["SHOP_SKU", "COUNT", "WAREHOUSE_AND_SHOP"], [["A", 4, "w"]])})
        with self.assertRaises(p.AdapterError):
            p.consume("YM-06", cp, c, {"status_code": 200, "content": raw})

    def test_live_current_stock_header_without_placement_requires_single_campaign(self):
        c = f.context_for("YM-06")
        cp = next(step["outcome"]["checkpoint"] for step in f.success_sequence("YM-06", c) if step["request"]["stage"] == "poll")
        columns = ["ERRORS", "SHOP_SKU", "PRODUCT_NAME", "WAREHOUSE", "COUNT", "RESERVE", "PRICE", "STATUS", "COMMENT"]
        content = f.csv_bytes(columns, [["", "A", "Product", "w", 7, 2, "999999", "ACTIVE", "not-retained"]])
        raw = f.zip_bytes({"provider-current-stock.csv": content})
        out = p.consume("YM-06", cp, c, {"status_code": 200, "content": raw})
        self.assertEqual(out["rows"][0]["stock_qty"], 7)
        self.assertEqual(out["rows"][0]["reserved_qty"], 2)
        self.assertNotIn("999999", json.dumps(out["rows"]))
        for unsafe in ({**cp, "warehouse_scope_single_campaign": False},):
            with self.assertRaises(p.AdapterError):
                p.consume("YM-06", unsafe, c, {"status_code": 200, "content": raw})
        with self.assertRaises(p.AdapterError):
            p.consume("YM-06", cp, c, {"status_code": 200, "content": f.zip_bytes({"one.csv": content, "two.csv": content})})

    def test_old_current_report_rechecks_scope_without_recreating_report(self):
        c = f.context_for("YM-06")
        cp = deepcopy(next(step["outcome"]["checkpoint"] for step in f.success_sequence("YM-06", c) if step["request"]["stage"] == "poll"))
        cp.pop("warehouse_scope_single_campaign")
        req = p.request("YM-06", cp, c)
        self.assertEqual(req["stage"], "warehouses_current")
        self.assertFalse(req["generate"])
        out = p.consume("YM-06", cp, c, f.response_for("YM-06", req, c))
        self.assertEqual(out["checkpoint"]["report_id"], cp["report_id"])
        self.assertEqual(out["checkpoint"]["grant_url"], cp["grant_url"])
        self.assertEqual(out["checkpoint"]["stage"], "download")
        self.assertTrue(out["checkpoint"]["warehouse_scope_single_campaign"])

    def test_live_evidence_redacts_values_and_unrecognized_keys(self):
        from acceptance import market_quantity_live as live
        raw = {"result": {"items": [{"sku": 100, "name": "buyer-secret", "secret-customer-key": "private"}],
                          "file": "https://storage.yandexcloud.net/a?signature=secret"}}
        encoded = json.dumps(live.structure(raw))
        for value in ("buyer-secret", "secret-customer-key", "signature=secret", "private"):
            self.assertNotIn(value, encoded)
        self.assertIn("unretained_key_count", encoded)
        self.assertEqual(live.safe_headers({"Authorization": "private", "Retry-After": "60"}, {"vendor_headers": []}), {"retry-after": "60"})
        with self.assertRaises(ValueError):
            live.private_paths("/opt/harness-prod/current/state.sqlite3")

    def test_independent_wire_counters_match_all_eighteen_quantity_projections(self):
        from collections import Counter
        from acceptance import market_quantity_live as live
        for tid in f.TEMPLATES:
            with self.subTest(tid=tid):
                context = f.context_for(tid)
                totals, rows, cards = Counter(), [], []
                for step in f.success_sequence(tid, context):
                    observed = live.wire_quantities(tid, step["request"], step["response"], context)
                    self.assertNotEqual(observed["status"], "UNSUPPORTED_WIRE_SCHEMA")
                    for field, value in observed["metrics"].items():
                        totals[field] += value
                    rows.extend(step["outcome"]["rows"])
                    cards.extend(step["outcome"]["catalog"])
                local = live.normalized_metrics(rows, len(cards))
                for field, value in totals.items():
                    self.assertEqual(value, local.get(field, 0), field)
                serialized = json.dumps(dict(totals))
                self.assertNotIn("999999", serialized)
                self.assertNotIn("buyer-data", serialized)
                if tid not in ("OZ-01", "WB-01", "YM-01"):
                    self.assertTrue(totals)

    def test_wire_observer_preserves_bad_response_for_the_actual_executor(self):
        from acceptance import market_quantity_live as live
        c = f.context_for("YM-06")
        self.assertEqual(live.warehouse_observation({"result": {"warehouses": [{"models": None}]}}, c)["models_with_campaign"], 0)
        self.assertEqual(live.wire_quantities("WB-03", {"stage": "list"}, {"status_code": 200, "payload": {}}, c)["status"], "UNSUPPORTED_WIRE_SCHEMA")
        shape = live.csv_header_structure(("SHOP_SKU;COUNT\n"+"Я"*10000).encode())
        self.assertEqual(shape["known_quantity_columns"], ["COUNT", "SHOP_SKU"])

    def test_wire_observer_ozon_empty_catalog_accepts_both_total_contracts(self):
        from acceptance import market_quantity_live as live
        c = f.context_for("OZ-02")
        request = p.request("OZ-02", {}, c)
        for totals in ({"total_items": 0}, {"total": 0}, {"total_items": 0, "total": 0},
                       {"total_items": "0", "total": 0}, {"total_items": 0, "total": "0"}):
            with self.subTest(totals=totals):
                response = reply({"result": {"items": [], "last_id": "", **totals}})
                before = deepcopy(response)
                observed = live.wire_quantities("OZ-02", request, response, c)
                self.assertEqual(observed, {"status": "OBSERVED", "metrics": {"catalog.rows": 0}})
                out = p.consume("OZ-02", {}, c, response)
                self.assertTrue(out["complete"])
                self.assertEqual(out["state"], "no_data_confirmed")
                self.assertEqual(observed["metrics"], live.normalized_metrics(out["rows"], len(out["catalog"])))
                self.assertEqual(response, before)
        for totals in ({"total_items": 1}, {"total": 1}, {"total_items": 1, "total": 1}):
            with self.subTest(nonzero=totals):
                observed = live.wire_quantities("OZ-02", request, reply({"result": {"items": [], **totals}}), c)
                self.assertEqual(observed, {"status": "NO_QUANTITY_DATA_STAGE", "metrics": {}})

    def test_wire_observer_ozon_invalid_totals_cannot_certify_empty_catalog(self):
        from acceptance import market_quantity_live as live
        c = f.context_for("OZ-02")
        request = p.request("OZ-02", {}, c)
        cases = [{}, {"total_items": 0, "total": 1}, {"total_items": 1, "total": 0}]
        for invalid in (True, False, -1, 0.0, None, "", "00", "0.0", "NaN", [], {}, "10000000000000"):
            cases.extend(({"total_items": invalid}, {"total": invalid},
                          {"total_items": invalid, "total": 0}, {"total_items": 0, "total": invalid}))
        for totals in cases:
            with self.subTest(totals=totals):
                response = reply({"result": {"items": [], "last_id": "", **totals}})
                before = deepcopy(response)
                self.assertEqual(live.wire_quantities("OZ-02", request, response, c),
                                 {"status": "UNSUPPORTED_WIRE_SCHEMA", "metrics": {}})
                with self.assertRaises(p.AdapterError):
                    p.consume("OZ-02", {}, c, response)
                self.assertEqual(response, before)

    def test_catalog_count_change_details_mismatch_and_archive_pass(self):
        c = f.context_for("OZ-02")
        start = advance("OZ-02", {}, c, {"result": {"items": [{"product_id": 1001}], "total": 1, "last_id": ""}})
        bad = f.response_for("OZ-02", p.request("OZ-02", start["checkpoint"], c), c)
        bad["payload"]["items"][0]["id"] = 1002
        with self.assertRaises(p.AdapterError):
            p.consume("OZ-02", start["checkpoint"], c, bad)
        ym = f.success_sequence("YM-02")
        self.assertFalse(ym[0]["request"]["json"]["archived"])
        self.assertTrue(ym[1]["request"]["json"]["archived"])
        self.assertFalse(ym[0]["outcome"]["complete"])
        self.assertTrue(ym[1]["outcome"]["complete"])

    def test_ozon_total_items_and_legacy_total_have_identical_results(self):
        for tid in ("OZ-02", "OZ-07"):
            c = f.context_for(tid)
            expected = f.success_sequence(tid, c)
            for totals in ({"total": 1}, {"total_items": 1},
                           {"total_items": 1, "total": 1}, {"total_items": "1", "total": 1}):
                with self.subTest(tid=tid, totals=totals):
                    cp, current = {}, dict(c)
                    for step in expected:
                        self.assertEqual(p.request(tid, cp, current), step["request"])
                        response = deepcopy(step["response"])
                        if step["request"]["stage"] == "list":
                            page = response["payload"]["result"] if tid == "OZ-02" else response["payload"]
                            page.pop("total")
                            page.update(totals)
                        out = p.consume(tid, cp, current, response)
                        self.assertEqual(out, step["outcome"])
                        cp = json.loads(json.dumps(out["checkpoint"]))
                        self.assertIs(type(cp["total"]), int)
                        self.assertNotIn("total_items", cp)
                        current["now"] = max(current["now"]+1, out.get("next_due") or 0)
                    self.assertTrue(out["complete"])

    def test_ozon_total_items_zero_requires_explicit_valid_count(self):
        for tid in ("OZ-02", "OZ-07"):
            for totals in ({"total": 0}, {"total_items": 0},
                           {"total_items": 0, "total": 0}, {"total_items": "0", "total": 0}):
                with self.subTest(tid=tid, totals=totals):
                    page = {"items": [], "last_id" if tid == "OZ-02" else "cursor": "", **totals}
                    payload = {"result": page} if tid == "OZ-02" else page
                    out = advance(tid, {}, f.context_for(tid), payload)
                    self.assertTrue(out["complete"])
                    self.assertTrue(out["coverage"]["zero_confirmed"])
                    self.assertEqual(out["state"], "no_data_confirmed")
                    self.assertEqual(out["rows"], [])
                    self.assertEqual(out["catalog"], [])
                    self.assertEqual(out["checkpoint"]["total"], 0)
                    self.assertIs(type(out["checkpoint"]["total"]), int)

    def test_ozon_missing_conflicting_or_invalid_totals_fail_closed(self):
        cases = [({}, "QUANTITY_TOTAL_MISSING"),
                 ({"total_items": 1, "total": 2}, "QUANTITY_TOTAL_CONFLICT"),
                 ({"total_items": 0, "total": 1}, "QUANTITY_TOTAL_CONFLICT")]
        for invalid in (True, False, -1, 1.0, None, "", "01", "1.0", "NaN", [], {}, "10000000000000"):
            cases.extend((totals, "QUANTITY_UNITS") for totals in (
                {"total_items": invalid}, {"total": invalid},
                {"total_items": invalid, "total": 1}, {"total_items": 1, "total": invalid}))
        for tid in ("OZ-02", "OZ-07"):
            c = f.context_for(tid)
            for totals, code in cases:
                with self.subTest(tid=tid, totals=totals):
                    cp = {}
                    response = f.response_for(tid, p.request(tid, cp, c), c)
                    page = response["payload"]["result"] if tid == "OZ-02" else response["payload"]
                    page.pop("total")
                    page.update(totals)
                    before = deepcopy(response)
                    with self.assertRaises(p.AdapterError) as caught:
                        p.consume(tid, cp, c, response)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(cp, {})
                    self.assertEqual(response, before)

    def test_ozon_total_aliases_resume_across_multiple_pages(self):
        for tid in ("OZ-02", "OZ-07"):
            with self.subTest(tid=tid):
                c, cp, collected = f.context_for(tid), {}, []
                for index, totals in enumerate(({"total": 3}, {"total_items": "3"},
                                                 {"total_items": 3, "total": 3}), 1):
                    request = p.request(tid, cp, c)
                    cursor_key = "last_id" if tid == "OZ-02" else "cursor"
                    self.assertEqual(request["json"][cursor_key], "" if index == 1 else f"page-{index-1}")
                    response = f.response_for(tid, request, c)
                    page = response["payload"]["result"] if tid == "OZ-02" else response["payload"]
                    page.pop("total")
                    page.update(totals)
                    page[cursor_key] = f"page-{index}" if index < 3 else ""
                    item = page["items"][0]
                    item.update(product_id=1000+index, offer_id=f"item-{index}")
                    if tid == "OZ-07":
                        item["stocks"][0].update(sku=100+index, present=10+index, reserved=index)
                    out = p.consume(tid, cp, c, response)
                    cp = json.loads(json.dumps(out["checkpoint"]))
                    if tid == "OZ-02":
                        self.assertFalse(out["complete"])
                        details = p.request(tid, cp, c)
                        self.assertEqual(details["json"], {"product_id": [str(1000+index)]})
                        response = f.response_for(tid, details, c)
                        response["payload"]["items"][0].update(
                            id=1000+index, sku=100+index, sources=[{"sku": 100+index}], offer_id=f"item-{index}")
                        out = p.consume(tid, cp, c, response)
                    cp = json.loads(json.dumps(out["checkpoint"]))
                    collected.extend(out["catalog"] if tid == "OZ-02" else out["rows"])
                    self.assertEqual(cp["total"], 3)
                    self.assertIs(type(cp["total"]), int)
                    self.assertNotIn("total_items", cp)
                    self.assertEqual(cp["count"], index)
                    self.assertEqual(cp["row_count"], index)
                    self.assertEqual(out["complete"], index == 3)
                self.assertEqual([row["sku"] for row in collected], ["101", "102", "103"])
                self.assertEqual([row["offer_id"] for row in collected], ["item-1", "item-2", "item-3"])
                if tid == "OZ-07":
                    self.assertEqual([row["stock_qty"] for row in collected], [11, 12, 13])
                    self.assertEqual([row["reserved_qty"] for row in collected], [1, 2, 3])

    def test_ozon_new_totals_preserve_restart_completeness_guards(self):
        for tid in ("OZ-02", "OZ-07"):
            c = f.context_for(tid)
            response = f.response_for(tid, p.request(tid, {}, c), c)
            page = response["payload"]["result"] if tid == "OZ-02" else response["payload"]
            page["total"] = 2
            page["last_id" if tid == "OZ-02" else "cursor"] = "next-page"
            out = p.consume(tid, {}, c, response)
            if tid == "OZ-02":
                cp = out["checkpoint"]
                out = p.consume(tid, cp, c, f.response_for(tid, p.request(tid, cp, c), c))
            self.assertFalse(out["complete"])
            cp = json.loads(json.dumps(out["checkpoint"]))
            for case in ("changed", "empty", "conflict"):
                with self.subTest(tid=tid, case=case):
                    response = f.response_for(tid, p.request(tid, cp, c), c)
                    page = response["payload"]["result"] if tid == "OZ-02" else response["payload"]
                    page.pop("total")
                    page["total_items"] = 3 if case == "changed" else 2
                    if case == "empty":
                        page["items"] = []
                    elif case == "conflict":
                        page["total"] = 1
                    before = deepcopy(cp)
                    with self.assertRaises(p.AdapterError) as caught:
                        p.consume(tid, cp, c, response)
                    expected = ("QUANTITY_TOTAL_CONFLICT" if case == "conflict" else
                                ("QUANTITY_TOTAL_CHANGED" if tid == "OZ-02" else "QUANTITY_STOCK_TOTAL")
                                if case == "changed" else
                                "QUANTITY_CATALOG_INCOMPLETE" if tid == "OZ-02" else "QUANTITY_STOCK_INCOMPLETE")
                    self.assertEqual(caught.exception.code, expected)
                    self.assertEqual(cp, before)

    def test_wb_catalog_cursor_must_advance_and_total_match(self):
        c = f.context_for("WB-02")
        payload = {"cards": [f.wb_card(n+1) for n in range(100)], "cursor": {"updatedAt": "2026-10-01T10:00:00Z", "nmID": 100, "total": 100}}
        out = advance("WB-02", {}, c, payload)
        req = p.request("WB-02", out["checkpoint"], c)
        self.assertEqual(req["json"]["settings"]["cursor"]["nmID"], 100)
        with self.assertRaises(p.AdapterError):
            advance("WB-02", out["checkpoint"], c, payload)
        bad = deepcopy(payload)
        bad["cursor"]["total"] = 99
        with self.assertRaises(p.AdapterError):
            advance("WB-02", {}, c, bad)

    def test_unrecognized_or_looped_cursor_is_rejected(self):
        c = f.context_for("YM-03")
        response = {"orders": [f.yandex_order(c)], "paging": {"nextPageToken": "next-1"}}
        out = advance("YM-03", {}, c, response)
        changed = deepcopy(response)
        changed["orders"][0]["orderId"] = 9002
        with self.assertRaises(p.AdapterError):
            advance("YM-03", out["checkpoint"], c, changed)
        response["paging"]["nextPageToken"] = {"arbitrary_provider_blob": "must-not-be-checkpointed"}
        with self.assertRaises(p.AdapterError):
            advance("YM-03", {}, c, response)

    def test_checkpoint_bound_to_connection_generation_and_all_selectors(self):
        c = f.context_for("YM-05")
        cp = f.success_sequence("YM-05", c)[0]["outcome"]["checkpoint"]
        for field, value in (("cid", "another"), ("store", "another"), ("version", 8), ("seller", "another"),
                             ("campaignId", 999), ("businessId", 999), ("from", "2026-09-01"), ("month", "2026-09")):
            with self.subTest(field=field), self.assertRaises(p.AdapterError):
                p.request("YM-05", cp, dict(c, **{field: value}))
        bad = dict(cp, schema="foreign")
        with self.assertRaises(p.AdapterError):
            p.request("YM-05", bad, c)
        self.assertEqual(p.request("YM-05", cp, dict(c, now=c["now"]+100))["stage"], "poll")

    def test_invalid_units_do_not_become_zero(self):
        c = f.context_for("YM-03")
        for invalid in (-1, True, 1.5, None, "", "1.0", "NaN", "1000000000000000"):
            bad = f.yandex_order(c)
            bad["items"][0]["count"] = invalid
            with self.subTest(value=invalid), self.assertRaises(p.AdapterError):
                advance("YM-03", {}, c, {"orders": [bad]})

    def test_timezones_and_ozon_csv_period_are_checked(self):
        c = f.context_for("OZ-06")
        for stamp in ("2026-10-01T10:00:00", "2026-13-01T10:00:00Z", "2026-09-01T10:00:00Z"):
            with self.subTest(stamp=stamp), self.assertRaises(p.AdapterError):
                advance("OZ-06", {}, c, {"postings": [f.posting(in_process_at=stamp)], "has_next": False})
        seq = f.success_sequence("OZ-03")
        cp = seq[1]["outcome"]["checkpoint"]
        with self.assertRaises(p.AdapterError):
            p.consume("OZ-03", cp, c, {"status_code": 200, "content": f.ozon_csv(day="2026-09-01")})

    def test_bad_archives_missing_sheets_and_bad_csv_fail_closed(self):
        c = f.context_for("YM-05")
        cp = f.success_sequence("YM-05", c)[1]["outcome"]["checkpoint"]
        values = [b"not-zip", f.zip_bytes({"delivered.csv": b"x;y\n1;2\n"}),
                  f.zip_bytes({"../delivered.csv": b"x;y\n1;2\n"}),
                  f.zip_bytes({"/absolute.csv": b"x;y\n1;2\n"})]
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            link = zipfile.ZipInfo("link.csv")
            link.external_attr = (0o120777 << 16)
            z.writestr(link, "../../private")
        values.append(stream.getvalue())
        for raw in values:
            with self.subTest(size=len(raw)), self.assertRaises(p.AdapterError):
                p.consume("YM-05", cp, c, {"status_code": 200, "content": raw})
        c = f.context_for("OZ-03")
        cp = f.success_sequence("OZ-03", c)[1]["outcome"]["checkpoint"]
        for raw in (b"", b"<html>temporary error</html>", f.csv_bytes(["SKU", "SKU"], [[1, 2]]),
                    f.ozon_csv().rsplit(b";", 1)[0]):
            with self.subTest(size=len(raw)), self.assertRaises(p.AdapterError):
                p.consume("OZ-03", cp, c, {"status_code": 200, "content": raw})

    def test_empty_arrays_are_zero_only_after_documented_completion(self):
        cases = {"OZ-04": {"returns": [], "has_next": False}, "WB-03": {"data": {"products": []}},
                 "YM-03": {"orders": []}, "YM-04": {"result": {"returns": []}}}
        for tid, payload in cases.items():
            out = advance(tid, {}, f.context_for(tid), payload)
            self.assertTrue(out["complete"])
            self.assertTrue(out["coverage"]["zero_confirmed"])
            self.assertEqual(out["state"], "no_data_confirmed")
        with self.assertRaises(p.AdapterError):
            advance("OZ-04", {}, f.context_for("OZ-04"), {"returns": [], "has_next": True})
        with self.assertRaises(p.AdapterError):
            advance("WB-04", {}, f.context_for("WB-04"), [])


def _full_success(tid):
    def test(self):
        sequence = f.success_sequence(tid)
        self.assertTrue(sequence[-1]["outcome"]["complete"])
        self.assertEqual(sequence[-1]["outcome"]["state"], "ready")
        outputs = json.dumps([s["outcome"] for s in sequence], ensure_ascii=False)
        self.assertNotIn("buyer-data-must-not-survive", outputs)
        self.assertNotIn("999999", outputs)
        for step in sequence:
            self.assertGreater(len(step["request"]["quota_scopes"]), 0)
            self.assertNotIn("Authorization", json.dumps(step["request"]))
            self.assertIn(step["request"]["method"], ("GET", "POST"))
            self.assertEqual(json.loads(json.dumps(step["outcome"]["checkpoint"])), step["outcome"]["checkpoint"])
    return test


def _fault_boundary(tid):
    def test(self):
        c = f.context_for(tid)
        cp = {}
        for response in [reply({"unrecognized": True}), reply({"status": "ERROR", "errors": [{"message": "secret-not-for-user"}]}),
                         {"status_code": 200, "content": b"{truncated"},
                         *[reply({"body": "secret-not-for-user"}, code) for code in (400, 401, 402, 403, 404, 408, 409, 410, 420, 429, 500, 502, 503, 504)]]:
            with self.subTest(status=response.get("status_code")):
                with self.assertRaises(p.AdapterError) as caught:
                    p.consume(tid, cp, c, response)
                self.assertNotIn("secret-not-for-user", str(caught.exception))
                self.assertEqual(cp, {})
    return test


for _tid in f.TEMPLATES:
    setattr(ProviderContracts, "test_success_"+_tid.replace("-", "_"), _full_success(_tid))
    setattr(ProviderContracts, "test_fail_closed_"+_tid.replace("-", "_"), _fault_boundary(_tid))


if __name__ == "__main__":
    unittest.main()
