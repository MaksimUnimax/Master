"""Credential admission and safe retry regressions; no external provider requests."""
import os,sqlite3
from pathlib import Path
from unittest.mock import patch
from tests.test_podmasterye_foundation import Foundation
from platform_core import provider_keys

class ProviderReadiness(Foundation):
    def counts(self):
        with sqlite3.connect(self.db) as c:
            return tuple(c.execute("SELECT (SELECT count(*) FROM usage_operations),(SELECT count(*) FROM coin_attempts)").fetchone())
    def test_missing_key_preflight_and_same_request_retry(self):
        h,c=self.actor("admin")
        keys=self.root/"provider-keys"
        with patch.dict(os.environ,{"HARNESS_PROVIDER_KEYS_DIR":str(keys)}):
            local=self.turn(h,c,"local","Что ты умеешь?")
            self.assertEqual(local.status_code,200,local.text)
            self.assertEqual(local.json()["route"],"local")
            for _ in range(2):
                r=self.turn(h,c,"who","Кто ты")
                self.assertEqual(r.status_code,503,r.text)
                self.assertEqual(r.json()["error"],"provider_key")
            self.assertEqual(self.counts(),(0,0))
            self.assertEqual(self.wallet(h)["available"],"10")
            self.assertFalse(self.journal.exists())
            self.assertEqual(self.turn(h,c,"who","другой вопрос").status_code,409)
            provider_keys.save(keys,"deepseek","fixture-only-not-a-real-key")
            r=self.turn(h,c,"who","Кто ты")
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["route"],"model")
            self.assertEqual(self.counts(),(1,1))
            (keys/"deepseek").unlink()
            self.assertEqual(self.turn(h,c,"who","Кто ты").json(),r.json())
            self.assertEqual(self.counts(),(1,1))
    def test_gateway_rejection_without_admission_can_resume(self):
        h,c=self.actor("buyer")
        unavailable=Path(str(self.journal)+".unconfigured")
        unavailable.touch()
        try:
            r=self.turn(h,c,"pre-dispatch","Кто ты")
            self.assertEqual(r.status_code,409,r.text)
            self.assertEqual(r.json()["error"],"turn_unconfirmed")
            self.assertEqual(self.counts(),(1,0))
            self.assertEqual(self.wallet(h)["available"],"10")
            self.assertEqual(self.wallet(h)["reserved"],"0")
        finally:
            unavailable.unlink()
        r=self.turn(h,c,"pre-dispatch","Кто ты")
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.counts(),(1,1))
        self.assertEqual(self.turn(h,c,"pre-dispatch","Кто ты").json(),r.json())
        self.assertEqual(self.counts(),(1,1))
