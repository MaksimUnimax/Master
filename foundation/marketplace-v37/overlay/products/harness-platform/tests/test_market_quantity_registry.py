"""Fail-closed startup/CI validation of actual marketplace passports.

These tests corrupt declarations, not the validator's schema. Provider/network
behavior remains covered by the existing adapter and durable-runtime suites.
"""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from platform_core import market_quantity_registry as registry
from platform_core import market_quantity_providers as providers
from platform_core import market_quantity_runtime as runtime
from platform_core import market_rate_limit as limiter
from tests.fixtures import market_quantity_cases as fixtures


class PassportValidation(unittest.TestCase):
    def reject(self, mutate, tid="OZ-02"):
        # Populate the success cache first; changing one nested field must
        # invalidate it even when the same module/callables remain loaded.
        self.assertTrue(registry.validate_registry())
        passport = registry.get_template(tid)
        mutate(passport)
        with patch.dict(registry._TEMPLATES, {tid: passport}):
            with self.assertRaisesRegex(ValueError, "Invalid quantity passport"):
                registry.validate_registry()

    def test_complete_registry_validates_at_backend_startup_without_io(self):
        self.assertEqual(len(registry.templates()), 18)
        self.assertTrue(registry.validate_registry())
        backend = runtime.Backend(SimpleNamespace(), clock=lambda: 0)
        self.assertIsNotNone(backend)
        Draft202012Validator.check_schema(registry._PASSPORT_SCHEMA)
        Draft202012Validator.check_schema(registry._QUOTA_SCHEMA)

    def test_missing_required_passport_sections_are_rejected(self):
        for key in ("id", "stable_id", "version", "kind", "provider", "purpose", "handler", "role", "effect",
                    "required_scope", "store_binding", "input_schema", "server_input_schema", "output_schema",
                    "stages", "initial_stage", "source", "verified_at", "history", "pagination", "terminal",
                    "normalization", "deduplication", "minimal_fields", "excluded_fields", "error_policy",
                    "progress_policy", "tests", "quota_profile"):
            with self.subTest(field=key):
                self.reject(lambda p, key=key: p.pop(key))

    def test_wrong_identity_version_types_scope_and_unknown_fields_are_rejected(self):
        mutations = (("id", "OZ-03"), ("stable_id", "OZ-01"), ("version", "unreviewed"),
                     ("provider", "wb"), ("kind", "user_operation"), ("role", "guest"),
                     ("effect", "write_marketplace"), ("purpose", "   "), ("required", "true"),
                     ("required_scope", []), ("required_scope", ["*"]), ("required_scope", ["Content"]),
                     ("pagination", {}), ("verified_at", "2026-02-30"), ("live_verified", True),
                     ("api_key", "must-not-appear-in-error"))
        for key, value in mutations:
            with self.subTest(field=key, value=value):
                self.reject(lambda p, key=key, value=value: p.__setitem__(key, value))
        with patch.dict(registry._TEMPLATES, {"EXTRA": registry.get_template("OZ-02")}):
            with self.assertRaisesRegex(ValueError, "all 18"):
                registry.validate_registry()

    def test_embedded_schemas_are_checked_and_cannot_resolve_external_references(self):
        for key in ("input_schema", "server_input_schema", "output_schema"):
            with self.subTest(schema=key):
                self.reject(lambda p, key=key: p[key].update(properties={"x": {"type": "not-a-json-type"}}))
                self.reject(lambda p, key=key: p[key].update(properties={"x": {"$ref": "https://private.example/schema"}}))
                self.reject(lambda p, key=key: p[key].update(properties={"x": {"$ref": "#/$defs/missing"}}))
                self.reject(lambda p, key=key: p[key].update({"$id": "https://private.example/"}))
                self.reject(lambda p, key=key: p[key].update({"$schema": "http://json-schema.org/draft-07/schema#"}))
        passport = registry.get_template("OZ-02")
        passport["server_input_schema"]["$defs"] = {"safe": {"type": "string"}}
        passport["server_input_schema"]["properties"]["safe"] = {"$ref": "#/$defs/safe"}
        self.assertIn("guard", passport["server_input_schema"])
        with patch.dict(registry._TEMPLATES, {"OZ-02": passport}):
            self.assertTrue(registry.validate_registry())

    def test_unregistered_or_unavailable_callables_fail_closed(self):
        self.reject(lambda p: p.update(handler="os.system"))
        for module, name in ((providers, "consume"), (limiter, "classify"), (runtime.Backend, "_failure")):
            with self.subTest(callable=name), patch.object(module, name, None):
                with self.assertRaisesRegex(ValueError, "callable handler"):
                    registry.validate_registry()

    def test_endpoint_method_origin_authentication_and_stage_effects_are_enforced(self):
        for key, value in (("method", "DELETE"), ("path", "/v1/product/import"),
                           ("path", "//private.example/collect"), ("origin", "http://api-seller.ozon.ru"),
                           ("origin", "https://api.partner.market.yandex.ru"), ("auth", "none"),
                           ("generate", True), ("download", True), ("idempotent", False)):
            with self.subTest(field=key):
                self.reject(lambda p, key=key, value=value: p["stages"]["list"].__setitem__(key, value))
        self.reject(lambda p: p["stages"].pop("fbs"), "OZ-06")
        self.reject(lambda p: p.update(initial_stage="details"))
        self.reject(lambda p: p["stages"]["generate"].update(idempotent=True), "WB-05")
        self.reject(lambda p: p["stages"]["download"].update(auth="ozon"), "OZ-03")
        self.reject(lambda p: p["stages"]["download"].update(origin="https://private.example"), "YM-05")

    def test_history_requires_valid_dates_bounds_and_honest_provenance(self):
        for key, value in (("earliest", "2024-02-31"), ("max_lookback_days", -1),
                           ("max_window_days", True), ("window_months", 13), ("timezone", "UTC"),
                           ("empty_window_is_history_boundary", True), ("boundary_evidence", "documented"),
                           ("window_evidence", "documented")):
            with self.subTest(field=key):
                self.reject(lambda p, key=key, value=value: p["history"].__setitem__(key, value), "OZ-04")
        self.reject(lambda p: p["history"].update(earliest="2020-01-01"), "WB-03")
        self.reject(lambda p: p["history"].update(max_lookback_days=365, boundary_evidence="documented"), "OZ-02")

    def test_sources_must_be_primary_https_provenance_without_credentials(self):
        for source in ("http://docs.ozon.ru/api/seller/", "https://docs.ozon.ru.evil.test/", "https://user:secret@docs.ozon.ru/",
                       "https://docs.ozon.ru:8000/", "https://docs.ozon.ru/?token=secret", "https://docs.ozon.ru/#fragment"):
            with self.subTest(source=source):
                self.reject(lambda p, source=source: p.update(source=source))
        self.reject(lambda p: p.update(sources=["https://private.example/contract"]))

    def test_policy_version_actions_handlers_and_progress_cannot_be_silently_changed(self):
        for key in ("429", "unknown", "database", "classifier", "failure_handler"):
            with self.subTest(missing=key):
                self.reject(lambda p, key=key: p["error_policy"].pop(key))
        for key, value in (("version", "old"), ("429", "retry_immediately"), ("unknown", "success"),
                           ("classifier", "os.system"), ("failure_handler", "other_runtime.retry")):
            with self.subTest(field=key):
                self.reject(lambda p, key=key, value=value: p["error_policy"].__setitem__(key, value))
        self.reject(lambda p: p["error_policy"].update(ignore_errors=True))
        for key in ("lease", "checkpoint", "cancel", "publish", "previous_snapshot", "unknown_generate"):
            with self.subTest(progress=key):
                self.reject(lambda p, key=key: p["progress_policy"].pop(key))
        self.reject(lambda p: p["progress_policy"].update(cancel="continue_anyway"))

    def test_quota_resolver_and_every_resolved_token_class_are_validated(self):
        self.reject(lambda p: p["quota_profile"].update(resolver="other_scheduler.allow"))
        self.reject(lambda p: p["quota_profile"].update(scope="individual browser"))
        original = registry.quota_profile
        mutations = (("min_interval", 0), ("max_concurrency", 0), ("max_active_retries", 0),
                     ("max_cycle_seconds", -1), ("backoff_cap", 1), ("interval", float("nan")),
                     ("scope", "api_key"), ("vendor_headers", []), ("rate_limit_statuses", [200]),
                     ("source", "http://dev.wildberries.ru/"), ("token_class", "base"))
        for key, value in mutations:
            def corrupt(tid, stage, context=None, key=key, value=value):
                result = original(tid, stage, context)
                if tid == "WB-03" and (context or {}).get("token_class") == "service":
                    result[key] = value
                return result
            with self.subTest(field=key), patch.object(registry, "quota_profile", corrupt):
                with self.assertRaisesRegex(ValueError, "resolved quota profile"):
                    registry.validate_registry()

    def test_test_inventory_and_na_explanations_are_complete(self):
        self.reject(lambda p: p["tests"]["required"].remove("live_verification"))
        self.reject(lambda p: p["tests"]["cases"].pop("scope"))
        self.reject(lambda p: p["tests"]["cases"].update(success=[]))
        self.reject(lambda p: p["tests"]["cases"].update(success=["https://example.test/not-a-test"]))
        self.reject(lambda p: p["tests"]["na"].pop("generate_unknown"))
        self.reject(lambda p: p["tests"]["na"].update(generate_unknown=" "))
        self.reject(lambda p: p["tests"]["na"].update(generate_unknown="Pretend this cannot happen"), "OZ-03")

    def test_quantity_projection_excludes_credentials_economics_and_pii(self):
        self.reject(lambda p: p["minimal_fields"].append("buyer_email"))
        self.reject(lambda p: p["excluded_fields"].remove("credentials"))
        self.reject(lambda p: p["excluded_fields"].remove("payments"))
        passport = registry.get_template("OZ-02")
        passport["purpose"] = {"key": "must-not-appear-in-error"}
        with patch.dict(registry._TEMPLATES, {"OZ-02": passport}):
            with self.assertRaises(ValueError) as exc:
                registry.validate_registry()
            self.assertNotIn("must-not-appear-in-error", str(exc.exception))

    def test_evidence_references_resolve_to_existing_test_or_live_runner_definitions(self):
        root = Path(__file__).resolve().parents[1]
        references = {ref for p in registry.templates() for refs in p["tests"]["cases"].values() for ref in refs}
        for ref in references:
            with self.subTest(reference=ref):
                package, module, *names = ref.split(".")
                tree = ast.parse((root / package / (module + ".py")).read_text())
                for name in names:
                    tree = next(node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
                self.assertIsInstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef))

    def test_declared_output_schema_accepts_every_real_adapter_fixture_stage(self):
        for passport in registry.templates():
            validator = Draft202012Validator(passport["output_schema"])
            for step in fixtures.success_sequence(passport["id"]):
                with self.subTest(template=passport["id"], stage=step["request"]["stage"]):
                    validator.validate(step["outcome"])

    def test_registered_error_classifier_is_the_executed_shared_classifier(self):
        for tid in fixtures.TEMPLATES:
            with self.subTest(template=tid), patch.object(limiter, "classify", wraps=limiter.classify) as shared:
                self.assertEqual(registry.classify_error(tid, 429, provider=registry.get_template(tid)["provider"]), "rate_limited")
                shared.assert_called_once_with(429, provider=registry.get_template(tid)["provider"])
        passport = registry.get_template("OZ-02")
        passport["error_policy"]["classifier"] = "os.system"
        with patch.dict(registry._TEMPLATES, {"OZ-02": passport}), patch.object(limiter, "classify") as shared:
            with self.assertRaises(ValueError):
                registry.classify_error("OZ-02", 429)
            shared.assert_not_called()

    def test_backend_startup_rejects_corrupt_passport_before_dispatch(self):
        passport = registry.get_template("WB-05")
        passport["stages"]["generate"]["idempotent"] = True
        with patch.dict(registry._TEMPLATES, {"WB-05": passport}):
            with self.assertRaisesRegex(ValueError, "stage effects"):
                runtime.Backend(SimpleNamespace(), clock=lambda: 0)


if __name__ == "__main__":
    unittest.main()
