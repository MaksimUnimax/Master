"""Real native Harness/MCP with a local deterministic model protocol fixture.

These checks prove tool dispatch, proposals and accounting of model calls. They
are deliberately separate from live-provider evidence and zero-model UI tests.
"""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_podmasterye_foundation as foundation
from tests import test_podmasterye_owner_v21 as owner_fixture
from tests import test_market_dual_contract as dual_fixture
from platform_core import podmasterye_workshops as workshops


class MarketDualNative(unittest.TestCase):
    headers=dual_fixture.MarketDual.headers
    connection=dual_fixture.MarketDual.connection
    verified=dual_fixture.MarketDual.verified
    fixture_catalog=dual_fixture.MarketDual.fixture_catalog
    actor=foundation.Foundation.actor
    turn=foundation.Foundation.turn
    action=owner_fixture.OwnerV21.action

    def setUp(self):
        self.enterContext(patch.dict(os.environ,{"PODMASTERYE_MARKET_WORKER":"0","HARNESS_DIALOG_ENGINE":"native"}))
        foundation.Foundation.setUp(self)
        self.client=self.c
        self.tokens={"owner":self.app.state.identity.login("buyer",foundation.P),"other":self.app.state.identity.login("other",foundation.P)}
        self.chats={name:self.c.post("/api/chats",headers=self.headers(name),json={}).json()["chatId"] for name in self.tokens}
        self.scopes={name:self.app.state.identity.resolve_chat(token,self.chats[name]) for name,token in self.tokens.items()}
        with self.app.state.identity._write() as db:
            self.workshops={name:workshops.chat_workspace(db,scope) for name,scope in self.scopes.items()}

    def read_tool(self,result):
        value=json.loads(result["text"])
        if isinstance(value,list):
            self.assertEqual(len(value),1,value)
            value=json.loads(value[0]["text"])
        if isinstance(value,str):value=json.loads(value)
        return value["result"]

    def test_mcp_report_shared_handler_and_secure_card(self):
        self.fixture_catalog()
        args={"source":"ozon","from":"2026-09-29","to":"2026-09-29","group_by":"product"}
        ui=self.c.post(dual_fixture.API+"/operations",headers=self.headers(),json={"operation":"market_sales","arguments":args,"requestId":"ui-sales"})
        self.assertEqual(ui.status_code,200,ui.text)
        result=self.action(self.headers(),self.chats["owner"],"native-sales","mcp__platform__market_sales",args)
        actual=self.read_tool(result);expected=ui.json()
        # Different native processes observe distinct wall-clock instants.
        # All quantities, coverage, source data and freshness decisions agree.
        self.assertLessEqual(datetime.fromisoformat(expected["calculated_at"]),datetime.fromisoformat(actual["calculated_at"]))
        def presentation_clock(value):
            if isinstance(value,dict):return {k:presentation_clock(v) for k,v in value.items() if k not in ("calculated_at","age_seconds")}
            if isinstance(value,list):return [presentation_clock(v) for v in value]
            return value
        self.assertEqual(presentation_clock(actual),presentation_clock(expected))
        card=self.action(self.headers(),self.chats["owner"],"native-connect","mcp__platform__market_connection",{"action":"connect","provider":"wb"})
        self.assertEqual(card["marketCard"]["provider"],"wb")
        self.assertEqual(card["ui"],{})
        requests=self.journal.with_suffix(self.journal.suffix+".requests").read_text()
        self.assertNotIn("secret-fixture-never-model",requests)
        self.assertNotIn("api-seller.ozon.ru",requests)
        self.assertNotIn("/v1/report/postings/create",requests)

    def test_mcp_mapping_requires_confirmation_and_export_is_local(self):
        _,sid,product=self.fixture_catalog()
        args={"source":sid,"sku":"100","product":product}
        result=self.action(self.headers(),self.chats["owner"],"native-mapping","mcp__platform__market_mapping",args)
        self.assertEqual(result["confirmation"]["kind"],"market")
        with self.app.state.identity._lock:
            self.assertIsNone(self.app.state.identity._db.execute("SELECT product FROM market_quantity_links WHERE store=? AND sku='100'",(sid,)).fetchone())
        saved=self.c.post("/api/chats/"+self.chats["owner"]+"/confirm",headers=self.headers(),json={"draftId":"native-mapping"})
        self.assertEqual(saved.status_code,200,saved.text)
        replay=self.c.post("/api/chats/"+self.chats["owner"]+"/confirm",headers=self.headers(),json={"draftId":"native-mapping"})
        self.assertEqual(replay.json(),saved.json())
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT product FROM market_quantity_links WHERE store=? AND sku='100'",(sid,)).fetchone()[0],product)
        export_args={"operation":"market_sales","arguments":{"source":"ozon","from":"2026-09-29","to":"2026-09-29"}}
        card=self.action(self.headers(),self.chats["owner"],"native-export","mcp__platform__market_export",export_args)
        self.assertEqual(card["marketCard"]["kind"],"export")
        with self.app.state.identity._lock:
            before=self.app.state.identity._db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0]
        exported=self.c.post(dual_fixture.API+"/export",headers=self.headers(),json=export_args)
        self.assertEqual(exported.status_code,200)
        self.assertEqual(exported.headers["content-type"],"application/zip")
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],before)

    def test_native_sync_card_uses_same_job_and_preserves_mixed_accounting_draft(self):
        self.verified()
        requested=self.c.post(dual_fixture.API+"/operations",headers=self.headers(),json={"operation":"market_sync_request","arguments":{"source":"ozon","from":"2026-09-01","to":"2026-09-02"},"requestId":"ui-group"})
        self.assertEqual(requested.status_code,200,requested.text);gid=requested.json()["job_id"]
        status=self.action(self.headers(),self.chats["owner"],"native-status-card","mcp__platform__market_sync_status",{"job_id":gid})
        self.assertEqual(status["marketCard"]["kind"],"sync")
        self.assertEqual(status["marketCard"]["arguments"],{"job_id":gid})
        self.assertEqual(status["ui"],{})
        requests=[json.loads(line) for line in self.journal.with_suffix(self.journal.suffix+".requests").read_text().splitlines()]
        tool_output=next(b for b in requests[-1]["messages"][-1]["content"] if b["type"]=="tool_result")
        raw=json.dumps(tool_output["content"])
        self.assertIn(gid,raw)
        for internal in ('"template_id"','"jobs"','"checkpoint"','"report_id"','secret-fixture-never-model'):
            self.assertNotIn(internal,raw.replace('\\"','"'))
        prepare={"name":"mcp__platform__prepare_accounting","input":{"operation":"quality_policy","arguments":{"return_defect_percent":"25","production_scrap_percent":"10"}}}
        sync={"name":"mcp__platform__market_sync_status","input":{"job_id":gid}}
        for rid,calls in (("mixed-prepare-first",[prepare,sync]),("mixed-sync-first",[sync,prepare])):
            result=self.turn(self.headers(),self.chats["owner"],rid,"fixture-dual-sequence:"+json.dumps(calls,ensure_ascii=False))
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()["accountingDraft"]["operation"],"quality_policy")
            self.assertEqual(result.json()["confirmation"]["status"],"pending")
            with self.app.state.identity._lock:
                from platform_core import podmasterye_quality as quality
                self.assertIsNone(quality.policy(self.app.state.identity._db,self.workshops["owner"])["return_defect_percent"])
