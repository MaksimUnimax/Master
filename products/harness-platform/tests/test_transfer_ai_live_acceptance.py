"""Live acceptance must remain offline until exact source and budget checks pass."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "acceptance/ai_live_acceptance.py"


class LiveAcceptanceGuards(unittest.TestCase):
    def setUp(self):
        self.output = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def invoke(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), "--output", str(self.output), *arguments],
                              text=True, capture_output=True, timeout=10)

    def test_default_is_inventory_only_and_requires_exact_digest_to_execute(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["networkRequests"], 0)
        manifest = json.loads((self.output / "source-manifest.json").read_text())
        self.assertIn("products/harness-platform/platform_core/web_access.py", manifest["files"])
        self.assertIn("integrations/harness-native-lab/gateway/server.mjs", manifest["files"])
        denied = self.invoke("--execute", "--expected-source-sha256", "unapproved")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("Exact approved candidate source digest", denied.stderr)
        self.assertFalse((self.output / "results.json").exists())

    def test_external_url_and_budget_over_five_are_rejected_before_process_or_session(self):
        prepared = self.invoke()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        digest = json.loads(prepared.stdout)["sourceSha256"]
        common = ["--execute", "--expected-source-sha256", digest, "--server-pid", "1",
                  "--database", str(self.output / "missing.sqlite3"),
                  "--session-file", str(self.output / "missing-session"), "--chat-id", "unused"]
        denied = self.invoke(*common, "--base-url", "https://example.com")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("loopback candidate URL", denied.stderr)
        denied = self.invoke(*common, "--base-url", "http://127.0.0.1:1", "--budget-rub", "5.01")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("no greater than 5 RUB", denied.stderr)
        self.assertFalse((self.output / "results.json").exists())
