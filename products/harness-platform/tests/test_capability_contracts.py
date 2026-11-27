"""The built-in capability catalog describes actual service contracts."""
import unittest

from jsonschema import Draft202012Validator, ValidationError

from platform_core import capability_registry as registry
from platform_core import assistant_preferences, podmasterye_timer as timer
from platform_core.podmasterye_timer_reports import argument_schema as report_schema
from platform_core.user_plugins.illustrations import CREATE_SCHEMA
from platform_core.user_plugins.timer import schedule


class CapabilityContracts(unittest.TestCase):
    def valid(self, capability, args):
        Draft202012Validator(registry.schema(capability)).validate(args)

    def invalid(self, capability, args):
        with self.assertRaises(ValidationError):
            self.valid(capability, args)

    def test_all_descriptors_have_real_binding_and_valid_schema(self):
        self.assertEqual(set(registry.CAPABILITIES), set(registry.BINDINGS))
        for key, item in registry.CAPABILITIES.items():
            with self.subTest(capability=key):
                Draft202012Validator.check_schema(registry.schema(key))
                self.assertTrue(item.handler)
                self.assertIn(item.scope, ("account", "workshop_chat", "admin_accounts", "admin_service"))
                self.assertTrue(registry.BINDINGS[key][1])
                if key not in ("account.profile", "account.wallet", "admin.system"):
                    self.assertNotEqual(registry.schema(key), registry._object())
        with self.assertRaises(KeyError):
            registry.schema("unimplemented_plugin")

    def test_preferences_and_images_reuse_their_actual_contracts(self):
        self.valid("assistant.preferences", {**assistant_preferences.DEFAULTS, "revision": 0})
        self.invalid("assistant.preferences", {**assistant_preferences.DEFAULTS, "revision": True})
        self.invalid("assistant.preferences", {**assistant_preferences.DEFAULTS, "revision": 0, "actor": "other"})
        self.assertEqual(registry.schema("assistant.illustration"), CREATE_SCHEMA)
        self.valid("assistant.illustration", {"prompt": "Синяя мастерская"})
        self.invalid("assistant.illustration", {"prompt": "", "providerKey": "not-authority"})

    def test_timer_variants_enforce_rule_fields_and_report_filters(self):
        base = {"title": "Отчёт", "channels": ["chat"], "kind": "report", "report": {"report": "profit", "period": "today"}}
        variants = [
            {"kind": "once", "zone": "UTC", "at": "2099-01-01T12:00:00Z"},
            {"kind": "interval", "zone": "UTC", "every_us": 60_000_000},
            {"kind": "calendar", "zone": "Asia/Qyzylorda", "weekdays": [1, 5], "times": ["09:00", "18:30"]},
            {"kind": "monthly", "zone": "UTC", "monthdays": [1, 31], "times": ["09:00"]},
        ]
        for rule in variants:
            definition = {**base, "schedule": rule}
            self.valid("timer.manage", {"requestId": "contract", "definition": definition})
            timer.definition(definition)
            schedule.validate(rule)
        bad = {**base, "schedule": {"kind": "monthly", "zone": "UTC", "times": ["09:00"]}}
        self.invalid("timer.manage", {"requestId": "contract", "definition": bad})
        self.invalid("timer.run", {"requestId": "run", "revision": 1, "operation": "delete"})
        self.invalid("timer.run", {"requestId": "run", "revision": True, "operation": "run"})
        good = {"report": "profit", "period": "custom", "from": "2026-01-01", "to": "2026-01-31", "filters": {"products": ["p"]}}
        validator = Draft202012Validator(report_schema())
        validator.validate(good)
        for bad in ({**good, "period": "today"}, {**good, "report": "tasks"}, {"report": "sales", "period": "custom"}):
            self.assertFalse(validator.is_valid(bad))

    def test_accounting_uses_confirmation_hash_and_native_documents_exact_fields(self):
        payload = {"requestId": "save", "operation": "task", "arguments": {"name": "Проверка"}, "revision": "a" * 64}
        self.valid("accounting.write", payload)
        self.invalid("accounting.write", {**payload, "revision": 1})
        self.valid("files.create", {"format": "xlsx", "name": "Отчёт.xlsx", "content_json": '{"sheets":[]}'})
        self.invalid("files.create", {"format": "exe", "name": "run.exe", "content_json": "{}"})
        self.valid("files.read", {"id": "a" * 32, "action": "range", "sheet": "Лист1", "range": "A1:B4"})
        self.invalid("files.read", {"id": "a" * 32, "serverPath": "/etc/passwd"})

    def test_chat_web_and_lifecycle_do_not_advertise_unimplemented_actions(self):
        self.valid("assistant.chat", {"requestId": "turn", "text": "Покажи итоги", "maxCoins": "0.25"})
        self.invalid("assistant.chat", {"requestId": "turn", "text": "", "workspace": "other"})
        self.valid("assistant.web", {"query": "Публичная тема", "need_content": False, "count": 8})
        self.valid("assistant.web", {"url": "https://example.org/"})
        self.invalid("assistant.web", {"query": "Тема", "need_content": True})
        self.invalid("assistant.web", {"url": "file:///etc/passwd"})
        args = {"requestId": "archive", "items": [{"actor": "test", "expected": "a" * 64}], "action": "archive", "reason": "Тест"}
        self.valid("admin.accounts", args)
        self.invalid("admin.accounts", {**args, "action": "delete"})


if __name__ == "__main__":
    unittest.main()
