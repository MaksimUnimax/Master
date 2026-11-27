"""Timer HTTP authority, typed bodies and immutable confirmation on fresh DBs."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient
from platform_core.chat_api import create_app
from platform_core import podmasterye_workshops as workshops


class TimerHttp(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "HARNESS_PROVIDER_KEYS_DIR": str(self.root / "keys"),
            "HARNESS_OPENROUTER_KEY_FILE": "", "HARNESS_OPENROUTER_ENABLED": "0",
            "HARNESS_MODEL_GATEWAY_URL": "http://127.0.0.1:9", "HARNESS_OFFLINE_MODEL": "0", "HARNESS_WEB_ENABLED": "0",
            "HARNESS_DIALOG_ENGINE": "native", "HARNESS_USAGE_JOURNAL": str(self.root / "usage.jsonl"),
        }))
        self.app = create_app(self.root / "identity.sqlite3", self.root / "chats")
        self.client = self.enterContext(TestClient(self.app, base_url="https://fixture.test"))
        self.store = self.app.state.identity
        self.tokens = {}; self.headers = {}; self.bases = {}
        for name in ("owner", "other", "admin"):
            self.store.create_account(name, "fixture password")
        self.store.set_admin("admin", True)
        for name in ("owner", "other", "admin"):
            token = self.store.login(name, "fixture password")
            self.tokens[name] = token
            self.headers[name] = {"Authorization": "Bearer " + token}
            chat = workshops.choose_chat(self.store, token)["chatId"]
            self.bases[name] = "/api/chats/" + chat + "/timer"

    def raw(self):
        return {"title": "Личный отчёт", "kind": "report", "schedule": {"kind": "once", "zone": "UTC", "at": "2099-01-01T12:00:00Z"},
                "channels": ["chat", "telegram"], "report": {"report": "profit", "period": "today"}}

    def post(self, suffix, value, user="owner", expected=200, *, base=None):
        path = (base or self.bases["owner"]) + suffix
        response = self.client.post(path, json=value, headers=self.headers[user])
        self.assertEqual(response.status_code, expected, response.text[:500])
        return response.json()

    def create(self):
        p = self.post("/preview", {"requestId": uuid4().hex, "definition": self.raw()})
        return self.post("/confirm", {"requestId": uuid4().hex, "draftId": p["id"], "revision": p["revision"], "receipt": p["receipt"]})

    def test_no_plugin_guest_and_cross_account_cannot_read_or_mutate(self):
        self.assertEqual(self.client.get(self.bases["owner"]).status_code, 401)
        event = self.create()
        self.assertEqual(self.client.get(self.bases["owner"], headers=self.headers["other"]).status_code, 404)
        self.post("/events/" + event["id"], {"requestId": "foreign", "operation": "pause", "revision": 1}, user="other", expected=404)
        own = self.client.get(self.bases["other"], headers=self.headers["other"])
        self.assertEqual(own.json()["events"], [])
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM chat_plugins").fetchone()[0], 0)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0], 0)

    def test_bad_bodies_do_not_create_partial_schedule_or_return_server_error(self):
        for definition in ({**self.raw(), "channels": [{}]}, {**self.raw(), "report": {"report": []}},
                           {**self.raw(), "schedule": {"kind": "monthly", "zone": "UTC", "times": ["09:00"], "monthdays": [True]}}):
            self.post("/preview", {"requestId": uuid4().hex, "definition": definition}, expected=400)
        self.post("/preview", {"requestId": "empty-target", "definition": self.raw(), "eventId": ""}, expected=400)
        self.post("/preview", {"requestId": "injected", "definition": self.raw(), "workspace": "other"}, expected=400)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM timer_events").fetchone()[0], 0)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM timer_drafts").fetchone()[0], 0)
        event = self.create()
        for revision in (True, "1", []):
            self.post("/events/" + event["id"], {"requestId": uuid4().hex, "operation": "pause", "revision": revision}, expected=400)
        response = self.client.get(self.bases["owner"] + "/events/" + event["id"] + "/history?before=" + str(2**100), headers=self.headers["owner"])
        self.assertEqual(response.status_code, 400)

    def test_confirmation_revision_replay_and_cookie_origin(self):
        p = self.post("/preview", {"requestId": "preview", "definition": self.raw()})
        args = {"requestId": "save", "draftId": p["id"], "revision": p["revision"], "receipt": p["receipt"]}
        self.post("/confirm", {**args, "requestId": "wrong-receipt", "receipt": "forged"}, expected=409)
        event = self.post("/confirm", args)
        self.assertEqual(event, self.post("/confirm", args))
        self.client.cookies.set("podmaster_local_session", self.tokens["owner"])
        response = self.client.post(self.bases["owner"] + "/events/" + event["id"],
            json={"requestId": "cross-site", "operation": "cancel", "revision": 1}, headers={"Origin": "https://evil.test"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM timer_events WHERE cancelled=1").fetchone()[0], 0)

    def test_admin_pause_validates_revision_and_is_audited_once(self):
        event = self.create(); path = "/api/admin/timer/pause"
        args = {"requestId": "pause", "eventId": event["id"], "revision": 1}
        self.assertEqual(self.client.post(path, json=args, headers=self.headers["owner"]).status_code, 403)
        for altered in ({**args, "revision": True}, {**args, "eventId": []}):
            response = self.client.post(path, json=altered, headers=self.headers["admin"])
            self.assertEqual(response.status_code, 400, response.text)
        for _ in range(2):
            response = self.client.post(path, json=args, headers=self.headers["admin"])
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM timer_admin_actions").fetchone()[0], 1)
        self.post("/events/" + event["id"], {"requestId": "stale", "operation": "resume", "revision": 1}, expected=409)
        listing = self.client.get("/api/admin/timer", headers=self.headers["admin"]).json()
        self.assertNotIn("Личный отчёт", str(listing))
        self.assertEqual(listing["events"][0]["status"], "paused")

    def test_action_proposal_after_event_pause_is_conflict_not_server_error(self):
        raw = self.raw(); raw.pop("report")
        raw.update(kind="action", operation="expense", arguments={"category": "Прочее", "total": "12.34"})
        p = self.post("/preview", {"requestId": "action-preview", "definition": raw})
        event = self.post("/confirm", {"requestId": "action-save", "draftId": p["id"], "revision": p["revision"], "receipt": p["receipt"]})
        run = self.post("/events/" + event["id"], {"requestId": "action-run", "operation": "run", "revision": 1})["runId"]
        deadline = time.monotonic() + 10
        while True:
            history = self.client.get(self.bases["owner"] + "/events/" + event["id"] + "/history", headers=self.headers["owner"]).json()
            if history["runs"][0]["outcome"] == "awaiting_confirmation":
                break
            if time.monotonic() >= deadline:
                self.fail(str(history))
            time.sleep(.05)
        self.post("/events/" + event["id"], {"requestId": "action-pause", "operation": "pause", "revision": 1})
        self.post("/runs/" + run + "/confirm", {}, expected=409)
        self.assertEqual(self.store._db.execute("SELECT COUNT(*) FROM pm_book_events WHERE rid=?", ("timer-action-" + run,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
