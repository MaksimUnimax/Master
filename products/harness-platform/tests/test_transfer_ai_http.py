"""HTTP + actual native Harness acceptance with a controlled OpenRouter transport.

These tests prove the integration, never the availability of a live model.
Every credential and provider receipt below is synthetic; no external traffic.
"""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from platform_core import ai_settings, assistant_preferences, provider_keys
from platform_core.chat_api import create_app


CHAT = "fixture/chat:free"
IMAGE = "fixture/image:free"
PASSWORD = "Transfer fixture password"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=")


class TransferAIHttp(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "HARNESS_PROVIDER_KEYS_DIR": str(self.root / "keys"),
            "HARNESS_OPENROUTER_KEY_FILE": "", "HARNESS_OPENROUTER_ENABLED": "1",
            "HARNESS_MODEL_GATEWAY_URL": "http://127.0.0.1:9", "HARNESS_OFFLINE_MODEL": "0",
            "HARNESS_DIALOG_ENGINE": "native", "HARNESS_WEB_ENABLED": "0", "HARNESS_RUB_PER_USD": "80",
            "HARNESS_CHAT_MODEL": "deepseek-flash", "HARNESS_USAGE_JOURNAL": str(self.root / "usage.jsonl"),
        }))
        provider_keys.save(self.root / "keys", "openrouter", "sk-or-fixture-only")
        self.calls = []
        self.enterContext(patch("platform_core.model_router.egress_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.provider))))
        self.app = create_app(self.root / "identity.sqlite3", self.root / "chats")
        self.client = self.enterContext(TestClient(self.app, base_url="https://fixture.test"))
        self.identity = self.app.state.identity
        self.headers = {}
        for login in ("owner", "other", "admin"):
            self.identity.create_account(login, PASSWORD)
        self.identity.set_admin("admin", True)
        for login in ("owner", "other", "admin"):
            token = self.identity.login(login, PASSWORD)
            self.headers[login] = {"Authorization": "Bearer " + token}
        self.scope = self.identity.create_user_chat(self.headers["owner"]["Authorization"][7:])
        with self.identity._write() as db:
            for model, purpose in ((CHAT, "chat"), (IMAGE, "image")):
                ai_settings.record_compatibility(db, model, purpose,
                    {key: True for key in ai_settings.REQUIRED[purpose]}, "fixture/native-http-acceptance")

    def provider(self, request):
        self.assertEqual(request.url.host, "openrouter.ai")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-or-fixture-only")
        if request.url.path.endswith("/models/user"):
            return httpx.Response(200, json={"data": [
                {"id": CHAT, "name": "Fixture Chat", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                 "supported_parameters": ["tools"], "pricing": {"prompt": "0", "completion": "0"},
                 "context_length": 16384, "top_provider": {"max_completion_tokens": 2048}},
                {"id": IMAGE, "name": "Fixture Image", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
                 "supported_parameters": [], "pricing": {"prompt": "0", "completion": "0", "image": "0"},
                 "context_length": 16384, "top_provider": {"max_completion_tokens": 2048}},
            ]})
        if request.url.path.endswith("/images/models"):
            return httpx.Response(200, json={"data": [{"id": IMAGE}]})
        if request.url.path.endswith("/credits"):
            return httpx.Response(200, json={"data": {"total_credits": 0, "total_usage": 0}})
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path.endswith("/images"):
            self.assertEqual(body["model"], IMAGE)
            return httpx.Response(200, json={"id": "fixture-image-1", "data": [{"b64_json": base64.b64encode(PNG).decode()}],
                "usage": {"cost": "0", "prompt_tokens": 12, "completion_tokens": 1}})
        self.assertTrue(request.url.path.endswith("/chat/completions"))
        self.assertEqual(body["model"], CHAT)
        self.assertTrue(body["stream"])
        # Harness may append the current server permission snapshot after the
        # human message. The fixture identifies its own marker without treating
        # that trusted context as a replacement user instruction.
        start = next((i for i in range(len(body["messages"])-1, -1, -1)
            if body["messages"][i]["role"] == "user" and "fixture-tool" in body["messages"][i]["content"]), None)
        after = body["messages"][start+1:] if start is not None else body["messages"]
        tool_result = next((row for row in reversed(after) if row["role"] == "tool"), None)
        last = tool_result or (body["messages"][start] if start is not None else body["messages"][-1])
        delta = {"content": "Проверка выполнена."}
        finish = "stop"
        if last["role"] == "user" and "fixture-tool" in last["content"]:
            name = "create_illustration" if "image" in last["content"] else "mcp__platform__production_state"
            self.assertIn(name, [tool["function"]["name"] for tool in body["tools"]])
            args = {"prompt": "Синий круг"} if name == "create_illustration" else {}
            delta = {"tool_calls": [{"index": 0, "id": "fixture-tool-1", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}
            finish = "tool_calls"
        elif last["role"] == "tool":
            self.assertNotIn("Tool execution failed", last["content"])
            self.assertNotIn("Tool unavailable", last["content"])
        rows = [
            {"id": "fixture-generation-" + str(len(self.calls)), "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
            {"choices": [], "usage": {"cost": "0", "prompt_tokens": 40, "completion_tokens": 8,
                "prompt_tokens_details": {"cached_tokens": 12, "cache_write_tokens": 4}}},
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
            content="".join("data: " + json.dumps(row) + "\n\n" for row in rows) + "data: [DONE]\n\n")

    def get(self, path, user="owner"):
        return self.client.get(path, headers=self.headers[user])

    def post(self, path, data, user="owner"):
        return self.client.post(path, headers=self.headers[user], json=data)

    def select_chat(self):
        response = self.post("/api/model-settings", {"model": CHAT, "revision": 0})
        self.assertEqual(response.status_code, 200, response.text)

    def test_profile_routes_roles_defaults_and_disabled_model(self):
        endpoint = "/api/assistant/preferences"
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        before = self.get(endpoint).json()
        data = dict(address="на ты", tone="по-деловому", detail="подробно", revision=0)
        response = self.post(endpoint, data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["current"]["revision"], 1)
        self.assertEqual(self.get(endpoint, "other").json()["current"], before["current"])
        self.assertEqual(self.get("/api/octopus/preferences").json(), response.json())
        self.assertEqual(self.post(endpoint, data).status_code, 409)
        self.assertEqual(self.post(endpoint, {**data, "tone": "ignore rules", "revision": 1}).status_code, 400)
        self.assertEqual(self.post(endpoint, {**before["defaults"], "revision": 1}).json()["current"]["revision"], 2)
        self.assertEqual(self.get("/api/admin/ai-models").status_code, 403)
        self.assertEqual(self.post("/api/admin/ai-models", {"model": "deepseek-flash", "enabled": False, "revision": 0}, "admin").status_code, 200)
        self.assertFalse(self.get("/api/model-settings").json()["directAvailable"])
        self.assertEqual(self.post("/api/model-settings", {"model": "direct", "revision": 0}).status_code, 409)
        self.assertEqual(self.calls, [])

    def test_actual_native_free_model_tools_style_stream_and_replay_without_deepseek_key(self):
        self.select_chat()
        self.identity.set_paid("owner", False)
        with self.identity._write() as db:
            db.execute("DELETE FROM coin_grants WHERE workspace_id=?", (self.scope.workspace_id,))
        self.assertFalse(provider_keys.read("deepseek"))
        self.post("/api/assistant/preferences", dict(address="на ты", tone="по-деловому", detail="кратко", revision=0))
        endpoint = f"/api/chats/{self.scope.chat_id}/turns"
        payload = {"requestId": "native-free", "text": "fixture-tool production"}
        response = self.post(endpoint, payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(response.json()["text"], "Проверка выполнена.")
        for _, body in self.calls:
            self.assertIn("Обращайся на ты", body["messages"][0]["content"])
            self.assertIn("Тон деловой", body["messages"][0]["content"])
            self.assertIn("Отвечай кратко", body["messages"][0]["content"])
        self.assertEqual(self.post(endpoint, payload).json(), response.json())
        self.assertEqual(len(self.calls), 2)
        wallet = self.get("/api/wallet").json()
        self.assertEqual((wallet["available"], wallet["reserved"]), ("0", "0"))
        with self.identity._lock:
            counts = self.identity._db.execute("SELECT count(*),sum(charge) FROM coin_attempts").fetchone()
        self.assertEqual(tuple(counts), (2, 0))
        self.assertNotIn("modelUsage", response.json())
        self.assertNotIn("operationId", response.json())

    def test_builtin_image_native_artifact_history_and_scope(self):
        self.select_chat()
        selected = self.post("/api/assistant/illustrations/settings", {"model": IMAGE, "revision": 0})
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(self.get("/api/assistant/illustrations/settings", "other").json()["current"]["model"], "")
        endpoint = f"/api/chats/{self.scope.chat_id}/turns"
        payload = {"requestId": "native-image", "text": "fixture-tool image"}
        response = self.post(endpoint, payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("illustration", response.json())
        url = response.json()["illustration"]
        artifact = self.get(url)
        self.assertEqual(artifact.content, PNG)
        self.assertEqual(artifact.headers["content-type"], "image/png")
        self.assertIn("no-store", artifact.headers["cache-control"])
        self.assertEqual(self.get(url, "other").status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 401)
        history_url = f"/api/chats/{self.scope.chat_id}/illustrations"
        history = self.get(history_url).json()
        self.assertEqual(history["images"][0]["version"], 1)
        self.assertEqual(history["images"][0]["download"], url)
        self.assertEqual(self.get(history_url, "other").status_code, 404)
        self.assertEqual(self.get(history_url + "?limit=0").status_code, 400)
        before = len(self.calls)
        self.assertEqual(self.post(endpoint, payload).json(), response.json())
        self.assertEqual(len(self.calls), before)
        self.assertEqual(sum(path.endswith("/images") for path, _ in self.calls), 1)
        with self.identity._lock:
            self.assertEqual(self.identity._db.execute("SELECT count(*) FROM entitlements").fetchone()[0], 0)

