"""Publish/snapshot boundaries using real adapters and isolated SQLite stores.

Synthetic documented HTTP shapes are explicit fixtures, not live-shop evidence.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import unittest
from unittest.mock import patch

from tests import test_podmasterye_market_planning as planning
from tests.fixtures import market_quantity_cases as cases
from platform_core import market_quantity as q, market_quantity_providers as providers, market_data
from platform_core.market_quantity_runtime import Backend
from platform_core import podmasterye_market_analytics as analytics


class DomainBoundaries(unittest.TestCase):
    setUp=planning.MarketplacePlanning.setUp
    actor=planning.MarketplacePlanning.actor
    call=planning.MarketplacePlanning.call
    prepare=planning.MarketplacePlanning.prepare
    commit=planning.MarketplacePlanning.commit
    op=planning.MarketplacePlanning.op
    report=planning.MarketplacePlanning.report
    recipe=planning.MarketplacePlanning.recipe
    add_store=planning.MarketplacePlanning.add_store

    def fixture_store(self,provider="wb"):
        pid=self.recipe()["product_id"]
        sid=self.add_store(provider,[],[],{"101" if provider!="yandex_market" else "item-a":pid})
        cid=self.store._db.execute("SELECT cid FROM market_data_links WHERE store=?",(sid,)).fetchone()[0]
        return sid,cid,pid

    def publish_fixture(self,sid,cid,tid,*,from_="2026-10-01",to="2026-10-30",alter=None,job_context=None,refresh=False,legacy_window=False):
        extra=job_context or {}
        if tid=="OZ-05":
            defaults=cases.context_for(tid)
            extra={"posting_number":defaults["posting_number"],"scheme":defaults["scheme"],**extra}
        with self.store._write() as db:
            jid=q.enqueue(db,sid,tid,from_,to,cid=cid,version=1,context={"reason":"isolated-contract",**extra},refresh=refresh,now=cases.NOW)
            if legacy_window:
                # Already persisted point-lookup jobs may retain the older
                # dated window; their replacement must still be posting scoped.
                db.execute("UPDATE market_data_tasks SET since=?,until=? WHERE id=?",(from_,to,jid))
        backend=Backend(self.app.state,clock=lambda:cases.NOW)
        context=cases.context_for(tid,store=sid,cid=cid,version=1,**{"from":from_,"to":to,**extra})
        cp={}
        for _ in range(20):
            job=backend.claim(job_id=jid)
            self.assertIsNotNone(job)
            request=providers.request(tid,cp,context)
            response=cases.response_for(tid,request,context)
            if alter:alter(response)
            out=providers.consume(tid,cp,context,response)
            with self.store._write() as db:
                receipt=backend._publish(db,job,out)
                backend._ack(db,job,receipt)
            cp=out["checkpoint"]
            if out["complete"]:return jid
        self.fail("Fixture did not finish")

    def test_calendar_publication_indexes_event_date_not_original_order_date(self):
        sid,cid,pid=self.fixture_store()
        def late_return(response):
            if isinstance(response.get("payload"),list):
                for row in response["payload"]:row["orderDt"]="2025-01-01T10:00:00+03:00"
        self.publish_fixture(sid,cid,"WB-04",alter=late_return)
        with self.store._lock:
            snap=q.quantity_snapshot(self.store._db,self.workspace,sid,start="2026-10-01",end="2026-10-30")
        self.assertEqual(len(snap["rows"]),2)
        self.assertEqual({r["event_date"][:10] for r in snap["rows"]},{"2026-10-01"})
        with q.local(self.store._db,self.workspace,"wb") as dest:
            self.assertEqual({r[0] for r in dest.execute("SELECT since FROM quantity_rows WHERE store=?",(sid,))},{"2026-10-01"})
            text=" ".join(r[0] for r in dest.execute("SELECT body FROM quantity_rows WHERE store=?",(sid,)))
            for prohibited in ("retailAmount","999999","buyer-data-must-not-survive"):
                self.assertNotIn(prohibited,text)

    def test_verified_store_missing_file_has_explicit_incomplete_coverage(self):
        sid,cid,pid=self.fixture_store()
        path=market_data.path_for(q.main_path(self.store._db),self.workspace,"wb")
        path.unlink()
        with self.store._lock:
            snap=q.quantity_snapshot(self.store._db,self.workspace,sid)
        self.assertTrue(snap["coverage"],"Missing required store must not disappear from coverage")
        self.assertTrue(all(not c["complete"] for c in snap["coverage"]))
        report=analytics.sales_snapshot(snap,from_="2026-10-01",to="2026-10-30",as_of="2026-11-28")
        self.assertFalse(report["complete"])
        self.assertIsNone(report["totals"]["net"])

    def test_reverified_key_can_resume_same_store_without_duplicate_fact_identity(self):
        sid,cid,pid=self.fixture_store()
        with self.store._write() as db:
            jid=q.enqueue(db,sid,"WB-03","2026-10-01","2026-10-30",cid=cid,version=1,now=cases.NOW)
            q.invalidate_connection(db,cid)
            db.execute("UPDATE pm_market_connections SET version=2 WHERE id=?",(cid,))
            rebound=q.bind_verified(db,self.workspace,cid,2,"wb",cid,{},now=cases.NOW)
            self.assertEqual(rebound,sid)
            q._request_window(db,q.selected_stores(db,self.workspace,sid)[0],"WB-03","2026-10-01","2026-10-30",reason="revalidated-key")
            state,version=db.execute("SELECT state,key_version FROM market_data_tasks WHERE id=?",(jid,)).fetchone()
        self.assertEqual(version,2)
        self.assertIn(state,q.ACTIVE)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM market_data_stores WHERE verified=1").fetchone()[0],1)

    def test_manual_stop_remains_stopped_when_the_key_is_rotated(self):
        sid,cid,pid=self.fixture_store()
        with self.store._write() as db:
            jid=q.enqueue(db,sid,"WB-03","2026-10-01","2026-10-30",cid=cid,version=1,now=cases.NOW)
            q.market_sync_control(db,self.workspace,jid,"stop")
            q.invalidate_connection(db,cid)
            db.execute("UPDATE pm_market_connections SET version=2 WHERE id=?",(cid,))
            q.bind_verified(db,self.workspace,cid,2,"wb",cid,{},now=cases.NOW)
            self.assertEqual(db.execute("SELECT state FROM market_data_tasks WHERE id=?",(jid,)).fetchone()[0],"stopped")

    def test_typed_market_result_does_not_claim_a_failed_book_write(self):
        from platform_core import workshop_write_permissions as permissions
        with patch.object(permissions,"turn_mode",return_value=("automatic",False)):
            before=self.store._db.total_changes
            for key in ("marketCard","marketResult","marketJob"):
                message={"text":"Сбор поставлен в очередь.",key:{"job_id":"fixture-job","state":"collecting"}}
                result=permissions.finalize(self.store._db,None,"fixture-turn",message)
                self.assertEqual(result["text"],"Сбор поставлен в очередь.")
            book_result=permissions.finalize(self.store._db,None,"fixture-turn",{"text":"Запрос обработан.","accountingDraft":{},"marketResult":{}})
            self.assertIn("Учётная запись не проведена",book_result["text"])
            self.assertEqual(self.store._db.total_changes,before)

    def test_aggregate_legacy_migration_cannot_publish_a_false_zero(self):
        sid,cid,pid=self.fixture_store("yandex_market")
        data={"kind":"realization","month":"2025-05","products":[{"sku":"item-a","name":"Изделие","delivered":100,"returned":20,"net":80,"unredeemed":0}],
              "totals":{"delivered":100,"returned":20,"net":80,"unredeemed":0},"rows":[],"collected":1}
        with self.store._write() as db:
            db.execute("INSERT INTO pm_ym_realization VALUES(?,1,123,'2025-05','ready',NULL,1,1,?,NULL)",(cid,json.dumps(data)))
            Backend(self.app.state,clock=lambda:cases.NOW)._migrate_yandex(db,self.workspace,cid,1,sid,{"businessId":12,"campaignId":123})
        with self.store._lock:snap=q.quantity_snapshot(self.store._db,self.workspace,sid)
        report=analytics.sales_snapshot(snap,from_="2025-05-01",to="2025-05-31",as_of="2026-11-28")
        self.assertFalse(report["complete"] and report["totals"]["net"]==0,"Nonzero legacy aggregate was declared a confirmed zero")
        if report["complete"]:self.assertEqual(report["totals"]["net"],80)

    def test_cross_database_receipt_recovers_without_second_provider_request(self):
        sid,cid,pid=self.fixture_store()
        with self.store._write() as db:
            jid=q.enqueue(db,sid,"WB-03","2026-10-01","2026-10-30",cid=cid,version=1,now=cases.NOW)
        clock=[cases.NOW];backend=Backend(self.app.state,clock=lambda:clock[0]);job=backend.claim(job_id=jid)
        ctx=cases.context_for("WB-03",store=sid,cid=cid,version=1)
        req=providers.request("WB-03",{},ctx)
        out=providers.consume("WB-03",{},ctx,cases.response_for("WB-03",req,ctx))
        # Simulate process loss after local commit, before the main receipt ack.
        with self.store._write() as db:backend._publish(db,job,out)
        clock[0]+=91;recovered=backend.claim(job_id=jid)
        with self.store._write() as db:self.assertTrue(backend._recover(db,recovered))
        with self.store._lock:
            self.assertEqual(q.job_public(self.store._db,jid,self.workspace)["state"],"ready")
            snap=q.quantity_snapshot(self.store._db,self.workspace,sid)
        self.assertEqual(len(snap["rows"]),1)
        self.assertEqual(snap["rows"][0]["ordered_qty"],12)
        self.assertEqual(self.store._db.execute("SELECT count(*) FROM market_data_events WHERE kind='http_attempt'").fetchone()[0],0)

    def test_quantity_rows_and_coverage_are_one_sqlite_read_snapshot(self):
        sid,cid,pid=self.fixture_store()
        self.publish_fixture(sid,cid,"WB-03")
        original=q.local;committed=[]
        @contextmanager
        def interleaved(db,w,provider,create=False):
            with original(db,w,provider,create) as dest:
                class Reader:
                    def execute(inner,sql,args=()):
                        if not create and "SELECT body,observed,source,since,until FROM quantity_coverage" in sql and not committed:
                            # A real concurrent publisher commits a newer full
                            # generation after rows were read, before coverage.
                            with original(db,w,provider,True) as writer:
                                raw=writer.execute("SELECT body FROM quantity_rows WHERE store=?",(sid,)).fetchone()[0]
                                row=json.loads(raw);row["ordered_qty"]=24
                                writer.execute("UPDATE quantity_rows SET body=?,observed=? WHERE store=?",(json.dumps(row),cases.NOW+1,sid))
                                writer.execute("UPDATE quantity_coverage SET observed=? WHERE store=?",(cases.NOW+1,sid))
                            committed.append(True)
                        return dest.execute(sql,args)
                yield Reader()
        with patch.object(q,"local",interleaved):
            first=q.quantity_snapshot(self.store._db,self.workspace,sid)
        self.assertEqual(first["rows"][0]["ordered_qty"],12)
        first_proof=next(c for c in first["coverage"] if c["source_id"]=="WB-03")
        self.assertEqual(first_proof["observed_at"],cases.NOW,"Old rows were combined with a newer coverage commit")
        second=q.quantity_snapshot(self.store._db,self.workspace,sid)
        self.assertEqual(second["rows"][0]["ordered_qty"],24)
        self.assertEqual(next(c for c in second["coverage"] if c["source_id"]=="WB-03")["observed_at"],cases.NOW+1)

    def test_single_posting_publish_is_not_complete_order_history(self):
        sid,cid,pid=self.fixture_store("ozon")
        self.publish_fixture(sid,cid,"OZ-05")
        snap=q.quantity_snapshot(self.store._db,self.workspace,sid)
        report=analytics.sales_snapshot(snap,from_="2026-10-01",to="2026-10-30",as_of="2026-11-28")
        self.assertEqual(report["totals"]["ordered"],3)
        self.assertFalse(report["complete"])
        self.assertIn("orders",report["coverage"][0]["missing_roles"])

    def test_two_posting_lookups_and_single_refresh_preserve_other_posting_receipt(self):
        sid,cid,pid=self.fixture_store("ozon")
        first={"posting_number":"111111-0001-1","scheme":"FBO"}
        second={"posting_number":"222222-0002-1","scheme":"FBS"}
        def saved_rows():
            with q.local(self.store._db,self.workspace,"ozon") as dest:
                return {(r["scheme"],r["posting_number"]):(r["ordered_qty"],receipt)
                    for body,receipt in dest.execute("SELECT body,receipt FROM quantity_rows WHERE store=? AND source='OZ-05'",(sid,))
                    for r in (json.loads(body),)}
        jid1=self.publish_fixture(sid,cid,"OZ-05",job_context=first,legacy_window=True)
        original_first=saved_rows()[("FBO",first["posting_number"])]
        jid2=self.publish_fixture(sid,cid,"OZ-05",job_context=second,legacy_window=True)
        self.assertNotEqual(jid1,jid2)
        before=saved_rows()
        self.assertEqual(set(before),{("FBO",first["posting_number"]),("FBS",second["posting_number"])})
        self.assertEqual(before[("FBO",first["posting_number"])],original_first)
        self.assertEqual([r[0] for r in before.values()],[3,3])
        second_job_receipt=self.store._db.execute("SELECT receipt FROM market_data_tasks WHERE id=?",(jid2,)).fetchone()[0]
        def corrected_quantity(response):response["payload"]["result"]["products"][0]["quantity"]=4
        again=self.publish_fixture(sid,cid,"OZ-05",job_context=first,refresh=True,legacy_window=True,alter=corrected_quantity)
        self.assertEqual(again,jid1)
        after=saved_rows()
        self.assertEqual(set(after),set(before))
        self.assertEqual(after[("FBS",second["posting_number"])],before[("FBS",second["posting_number"])])
        self.assertEqual(self.store._db.execute("SELECT receipt FROM market_data_tasks WHERE id=?",(jid2,)).fetchone()[0],second_job_receipt)
        self.assertEqual(after[("FBO",first["posting_number"])][0],4)
        self.assertNotEqual(after[("FBO",first["posting_number"])][1],before[("FBO",first["posting_number"])][1])
        snap=q.quantity_snapshot(self.store._db,self.workspace,sid)
        report=analytics.sales_snapshot(snap,from_="2026-10-01",to="2026-10-30",as_of="2026-11-28")
        self.assertEqual(report["totals"]["ordered"],7)
        self.assertFalse(report["complete"])
        self.assertIn("orders",report["coverage"][0]["missing_roles"])

    def test_wb_aggregate_nested_windows_and_independent_refresh_keep_receipts(self):
        sid,cid,_=self.fixture_store("wb")
        inner=("2026-10-29","2026-11-05")
        outer=("2026-10-29","2026-11-27")
        def saved():
            with q.local(self.store._db,self.workspace,"wb") as dest:
                rows={(a,b):(json.loads(body)["ordered_qty"],receipt)
                    for a,b,body,receipt in dest.execute("SELECT since,until,body,receipt FROM quantity_rows WHERE store=? AND source='WB-03'",(sid,))}
                coverage={(a,b):(json.loads(body),receipt)
                    for a,b,body,receipt in dest.execute("SELECT since,until,body,receipt FROM quantity_coverage WHERE store=? AND source='WB-03'",(sid,))}
            return rows,coverage
        self.publish_fixture(sid,cid,"WB-03",from_=inner[0],to=inner[1])
        inner_row,inner_coverage=saved()
        self.publish_fixture(sid,cid,"WB-03",from_=outer[0],to=outer[1])
        before,proofs=saved()
        self.assertEqual(set(before),{inner,outer})
        self.assertEqual(before[inner],inner_row[inner])
        self.assertEqual(proofs[inner],inner_coverage[inner])
        def corrected(response):
            for item in response["payload"]["data"]["products"]:
                item["statistic"]["selected"]["orderCount"]=24
        self.publish_fixture(sid,cid,"WB-03",from_=inner[0],to=inner[1],refresh=True,alter=corrected)
        refreshed,refreshed_proofs=saved()
        self.assertEqual(set(refreshed),{inner,outer})
        self.assertEqual(refreshed[outer],before[outer])
        self.assertEqual(refreshed_proofs[outer],proofs[outer])
        self.assertEqual(refreshed[inner][0],24)
        self.assertNotEqual(refreshed[inner][1],before[inner][1])
        self.assertEqual(refreshed[inner][1],refreshed_proofs[inner][1])
        # A confirmed empty refresh replaces only its own interval too.
        def empty(response):response["payload"]["data"]["products"]=[]
        self.publish_fixture(sid,cid,"WB-03",from_=outer[0],to=outer[1],refresh=True,alter=empty)
        final,final_proofs=saved()
        self.assertEqual(set(final),{inner})
        self.assertEqual(final[inner],refreshed[inner])
        self.assertEqual(final_proofs[inner],refreshed_proofs[inner])
        self.assertTrue(final_proofs[outer][0]["complete"])
        self.assertTrue(final_proofs[outer][0]["zero_confirmed"])

    def test_orphan_return_schedules_one_durable_posting_lookup(self):
        sid,cid,pid=self.fixture_store("ozon")
        jid=self.publish_fixture(sid,cid,"OZ-04")
        def lookup():
            rows=self.store._db.execute("SELECT id,owner_cid,key_version,context FROM market_data_tasks WHERE store=? AND source='OZ-05'",(sid,)).fetchall()
            self.assertEqual(len(rows),1,"Missing original posting must have exactly one shared durable lookup")
            task,owner,version,raw=rows[0];ctx=json.loads(raw)
            self.assertEqual((owner,version),(cid,1))
            self.assertEqual((ctx["posting_number"],ctx["scheme"]),("111111-0001-1","FBO"))
            return task
        first=lookup()
        with self.store._write() as db:q.market_sync_control(db,self.workspace,jid,"retry")
        self.publish_fixture(sid,cid,"OZ-04")
        self.assertEqual(lookup(),first)


if __name__=="__main__":unittest.main()
