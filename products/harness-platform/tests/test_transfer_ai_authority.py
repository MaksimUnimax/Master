"""An archived business workshop cannot retain a DS/OR provider capability."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from starlette.exceptions import HTTPException
from platform_core import podmasterye_workshops as workshops
from platform_core.guest_registration import RegistrationStore
from platform_core.identity import _secret_digest
from platform_core.operation_grants import active_chat_grant, issue_grant, renew_marketplace_grant
from tests import test_openrouter_operations as fixture


RESOLVER = Path(__file__).resolve().parents[3] / "integrations/harness-native-lab/gateway/operation-resolver.mjs"


def native(database, token, extra=""):
    source = """import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {openOperationResolver} from %s;
const input=JSON.parse(readFileSync(0,'utf8'));
const resolver=openOperationResolver(input.database);
const results=[Boolean(resolver.resolve(input.token))];
%s
resolver.close();
console.log(JSON.stringify(results));
""" % (json.dumps(RESOLVER.as_uri()), extra)
    result = subprocess.run(["node", "--input-type=module", "-e", source],
        input=json.dumps({"database": str(database), "token": token}), text=True,
        capture_output=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class ArchiveProviderAuthority(unittest.TestCase):
    def setUp(self):
        self.case = fixture.RouterOperations("test_zero_balance_retry_same_operation_and_attempt")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.enterContext(patch.dict(os.environ, {"PODMASTERYE_MULTI_WORKSHOP": "1"}))
        c = self.case
        self.workshop = workshops.change(c.state.identity, c.token, "create-extra", "create", {"name": "Scoped fixture"})["id"]
        c.chat = workshops.choose_chat(c.state.identity, c.token, self.workshop)["chatId"]
        c.scope = c.state.identity.resolve_chat(c.token, c.chat)
        # The direct DS resolver always requires a paid-model authorization,
        # even though this fixture's OR model has a free tariff.
        c.state.identity.set_paid("owner", True)

    def active(self, grant):
        with self.case.state.identity._lock:
            return active_chat_grant(self.case.state.identity._db,
                                     hashlib.sha256(grant.token.encode()).hexdigest())

    def test_legacy_archived_binding_blocks_existing_or_attempt_ds_and_renew(self):
        c = self.case
        grant = c.grant()
        workspace, attempt = c.router.reserve(grant.token, {"messages": [{"role": "user", "content": "fixture"}]})
        self.assertEqual(native(c.path, grant.token), [True])
        # Simulates an old archived database that did not revoke its grants.
        with c.state.identity._write() as db:
            db.execute("UPDATE pm_workshops SET archived=1 WHERE id=?", (self.workshop,))
        self.assertFalse(self.active(grant))
        self.assertFalse(c.router.can_send(grant.token, workspace, attempt))
        self.assertEqual(native(c.path, grant.token), [False])
        self.assertFalse(renew_marketplace_grant(c.path, hashlib.sha256(grant.token.encode()).hexdigest(), int(time.time())))
        self.assertEqual(c.complete(grant).status_code, 403)
        with self.assertRaises(PermissionError):
            issue_grant(c.path, c.scope, source="chat.turn", run_key="new-archived", bind_model=c.router.bind,
                        session_digest=_secret_digest(c.token))
        self.assertEqual(c.seen, [])

    def test_archive_and_restore_do_not_revive_old_token(self):
        c = self.case
        grant = c.grant()
        self.assertTrue(self.active(grant))
        workshops.change(c.state.identity, c.token, "archive", "archive", {"id": self.workshop})
        self.assertFalse(self.active(grant))
        workshops.change(c.state.identity, c.token, "restore", "restore", {"id": self.workshop})
        self.assertFalse(self.active(grant))
        self.assertEqual(native(c.path, grant.token), [False])
        self.assertEqual(c.complete(grant).status_code, 403)
        self.assertEqual(c.seen, [])
        fresh = issue_grant(c.path, c.scope, source="chat.turn", run_key="after-restore", bind_model=c.router.bind,
                            session_digest=_secret_digest(c.token))
        self.assertEqual(c.complete(fresh).status_code, 200)
        self.assertEqual(len(c.seen), 1)


class LateInstalledAuthority(unittest.TestCase):
    def test_shared_core_then_late_workshop_schema_fail_closed(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        database = root / "core.sqlite3"
        store = self.enterContext(RegistrationStore(database))
        store.create_account("owner", "test registration password")
        store.set_paid("owner", True)
        token = store.login("owner", "test registration password")
        scope = store.create_user_chat(token)
        grant = issue_grant(database, scope, source="chat.turn", run_key="generic", direct_fallback="deepseek-flash",
                            session_digest=_secret_digest(token))
        with store._lock:
            self.assertTrue(active_chat_grant(store._db, hashlib.sha256(grant.token.encode()).hexdigest()))
        # Start a real resolver before the optional product tables exist, then
        # add policy while it is alive. This matches launcher startup ordering.
        rows = native(database, grant.token, """
const db=new DatabaseSync(input.database);
const scope=resolver.resolve(input.token);
db.exec(`CREATE TABLE pm_workshops(id TEXT PRIMARY KEY,account TEXT,archived INTEGER);
CREATE TABLE pm_workshop_chats(chat TEXT PRIMARY KEY,account TEXT,workshop TEXT)`);
db.prepare('INSERT INTO pm_workshops VALUES(?,?,1)').run(scope.workspace_id,scope.workspace_id);
results.push(Boolean(resolver.resolve(input.token)));
db.prepare('UPDATE pm_workshops SET archived=0').run();
results.push(Boolean(resolver.resolve(input.token)));
db.prepare('INSERT INTO pm_workshop_chats VALUES(?,?,?)').run(scope.chat_id,'foreign-account',scope.workspace_id);
results.push(Boolean(resolver.resolve(input.token)));
db.exec('DROP TABLE pm_workshop_chats');
results.push(Boolean(resolver.resolve(input.token)));
db.close();
""")
        self.assertEqual(rows, [True, False, True, False, False])
        with store._lock:
            self.assertFalse(active_chat_grant(store._db, hashlib.sha256(grant.token.encode()).hexdigest()))
        self.assertFalse(renew_marketplace_grant(database, hashlib.sha256(grant.token.encode()).hexdigest(), int(time.time())))
