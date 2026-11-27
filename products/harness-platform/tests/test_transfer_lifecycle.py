import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from platform_core.identity import IdentityStore, AuthenticationError
from platform_core.storage import Scope
from platform_core import account_lifecycle as life, capability_registry as capabilities
from platform_core import podmasterye_domain as domain, podmasterye_integrations as integrations
from platform_core import schema_migrations as migrations
from platform_core.operation_grants import issue_grant


class AccountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "platform.sqlite3"
        self.store = IdentityStore(self.path)
        domain.init(self.store)
        for name in ("owner", "one", "two"):
            self.store.create_account(name, "strong-password")
        self.store.set_admin("owner", True)
        self.tokens = {name: self.store.login(name, "strong-password") for name in ("owner", "one", "two")}
        self.actors = {r[1]: r[0] for r in self.store._db.execute("SELECT actor_id,login FROM identity_accounts")}
        with self.store._write() as db:
            life.initialize(db)
        self.journal = Path(self.temp.name) / "native.sqlite3"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def perform(self, name, action, request="r1"):
        actor = self.actors[name]
        item = life.preview(self.store, self.tokens["owner"], [actor], action, self.journal)["items"][0]
        return life.change(self.store, self.tokens["owner"], request,
            [{"actor": actor, "expected": item["expected"]}], action, "Проверка владельцем", self.journal)

    def test_block_preserves_money_records_and_revokes_existing_and_new_sessions(self):
        token = self.tokens["one"]
        chat = self.store.create_user_chat(token)
        wallet = self.store.wallet(token)
        domain.save_recipe(self.store, token, "recipe", dict(material="Дерево", product="Рамка",
            pack_quantity=10, usage_quantity=2, pack_price="500"))
        grant = issue_grant(self.path, chat, source="chat.turn", run_key="working")
        result = self.perform("one", "block")
        self.assertEqual(result["changed"], 1)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM pm_products").fetchone()[0], 1)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM usage_grants").fetchone()[0], 0)
        with self.assertRaises(AuthenticationError):
            self.store.account_login(token)
        with self.assertRaises(AuthenticationError):
            self.store.login("one", "strong-password")
        with self.assertRaises(AuthenticationError):
            issue_grant(self.path, chat, source="chat.turn", run_key="new")
        self.perform("one", "restore", "restore")
        fresh = self.store.login("one", "strong-password")
        self.assertEqual(self.store.wallet(fresh)["available"], wallet["available"])
        self.assertTrue(life.integration_paused(self.store._db, chat.workspace_id, "telegram"))
        life.resume_integration(self.store, fresh, "telegram")
        self.assertFalse(life.integration_paused(self.store._db, chat.workspace_id, "telegram"))

    def test_unknown_attempt_keeps_exact_reservation_on_block(self):
        token = self.tokens["one"]
        scope = self.store.create_user_chat(token)
        grant = issue_grant(self.path, scope, source="chat.turn", run_key="pending")
        amount = 123456789123
        with self.store._write() as db:
            db.execute("""INSERT INTO coin_attempts(attempt_id,operation_id,bound,model,started_ms,rate_version,period)
                VALUES(?,?,?,?,?,?,?)""", ("pending", grant.operation_id, amount, "deepseek-flash", 1, "deepseek-v1", "test"))
        self.perform("one", "archive")
        row = self.store._db.execute("SELECT charge,bound FROM coin_attempts WHERE attempt_id='pending'").fetchone()
        self.assertEqual(row, (None, amount))
        self.assertEqual(self.store._db.execute("SELECT held FROM coin_wallet_balances WHERE workspace_id=?",
            (scope.workspace_id,)).fetchone()[0], amount)

    def test_external_source_remains_disabled_after_restore(self):
        token = self.tokens["one"]
        source = integrations.change(self.store, token, None, "create", {"name": "Магазин"})
        self.perform("one", "block")
        self.perform("one", "restore", "r2")
        with self.assertRaises(PermissionError):
            integrations.authenticate(self.store._db, "Bearer " + source["apiKey"])

    def test_batch_partial_failure_and_idempotent_replay(self):
        actors = [self.actors["owner"], self.actors["one"], self.actors["two"]]
        preview = life.preview(self.store, self.tokens["owner"], actors, "archive", self.journal)
        items = [{"actor": x["actor"], "expected": x["expected"]} for x in preview["items"]]
        args = (self.store, self.tokens["owner"], "batch", items, "archive", "Тест", self.journal)
        first = life.change(*args)
        self.assertEqual(first["changed"], 2)
        self.assertFalse(first["items"][0]["ok"])
        self.assertEqual(first, life.change(*args))
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM account_lifecycle_audit").fetchone()[0], 2)

    def test_changed_snapshot_conflict_and_request_parameter_conflict(self):
        actor = self.actors["one"]
        p = life.preview(self.store, self.tokens["owner"], [actor], "block", self.journal)["items"][0]
        self.store.create_user_chat(self.tokens["one"])
        items = [{"actor": actor, "expected": p["expected"]}]
        result = life.change(self.store, self.tokens["owner"], "stale", items, "block", "Тест", self.journal)
        self.assertEqual(result["changed"], 0)
        self.assertIn("изменилось", result["items"][0]["error"])
        with self.assertRaises(domain.Conflict):
            life.change(self.store, self.tokens["owner"], "stale", items, "archive", "Тест", self.journal)

    def test_irreversible_deletion_closed_even_with_exact_preview(self):
        result = self.perform("one", "delete")
        self.assertEqual(result["changed"], 0)
        self.assertIn("политика", result["items"][0]["error"])
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM identity_accounts").fetchone()[0], 3)

    def test_protected_account_and_non_admin(self):
        with self.store._write() as db:
            db.execute("UPDATE account_lifecycle SET protected=1 WHERE actor_id=?", (self.actors["one"],))
        self.assertEqual(self.perform("one", "archive")["changed"], 0)
        with self.assertRaises(PermissionError):
            life.preview(self.store, self.tokens["two"], [self.actors["one"]], "block", self.journal)

    def test_shared_capability_scope_and_revocation(self):
        one = self.store.create_user_chat(self.tokens["one"])
        two = self.store.create_user_chat(self.tokens["two"])
        self.assertTrue(capabilities.permitted(self.store._db, one, "timer.manage"))
        self.assertFalse(capabilities.permitted(self.store._db, one, "admin.finance"))
        self.assertFalse(capabilities.permitted(self.store._db, Scope(one.actor_id, one.workspace_id, two.chat_id), "reports.read"))
        self.perform("one", "block")
        self.assertFalse(capabilities.permitted(self.store._db, one, "timer.manage"))
        self.assertTrue(capabilities.permitted(self.store._db, two, "timer.manage"))


class MigrationTests(unittest.TestCase):
    def test_failure_rolls_back_body_and_version_and_preserves_outer_transaction(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE original(id INTEGER PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO original VALUES(1,'before')")
        with self.assertRaises(sqlite3.OperationalError):
            migrations.apply(db, "broken", ("CREATE TABLE partial(id INTEGER)", "INSERT INTO absent VALUES(1)"))
        self.assertEqual(db.execute("SELECT value FROM original").fetchone()[0], "before")
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_schema WHERE name='partial'").fetchone())
        self.assertTrue(migrations.apply(db, "ok", ("CREATE TABLE added(id INTEGER)",)))
        self.assertFalse(migrations.apply(db, "ok", ("CREATE TABLE added(id INTEGER)",)))
        with self.assertRaises(migrations.MigrationError):
            migrations.apply(db, "ok", ("CREATE TABLE changed(id INTEGER)",))
        db.rollback()
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_schema WHERE name='added'").fetchone())
        db.close()


if __name__ == "__main__":
    unittest.main()
