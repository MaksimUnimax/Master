"""Integrated timer contract checks on isolated databases; outbound adapters are controlled."""
import asyncio
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4
from unittest.mock import patch
from starlette.exceptions import HTTPException
from platform_core.guest_registration import RegistrationStore
from platform_core import podmasterye_domain as domain, podmasterye_book as book, podmasterye_workshops as workshops
from platform_core import podmasterye_timer as timer, podmasterye_timer_reports as reports, account_lifecycle
from platform_core.telegram_api import DeliveryError
from platform_core.user_plugins.timer import jobs, schedule, store


def instant(value):
    return schedule.instant(datetime.fromisoformat(value))


class Schedules(unittest.TestCase):
    def test_monthly_missing_day_and_leap_year(self):
        rule={"kind":"monthly","zone":"Asia/Qyzylorda","monthdays":[31],"times":["09:00"]}
        self.assertEqual(schedule.next_after(rule,instant("2026-01-31T09:00:00+05:00"),0),instant("2026-03-31T09:00:00+05:00"))
        rule["monthdays"]=[29]
        self.assertEqual(schedule.next_after(rule,instant("2028-01-30T09:00:00+05:00"),0),instant("2028-02-29T09:00:00+05:00"))

    def test_once_daily_weekly_interval_and_timezone(self):
        start=instant("2026-11-27T08:00:00+05:00")
        cases=[({"kind":"once","zone":"Asia/Qyzylorda","at":"2026-11-27T09:00:00+05:00"},"2026-11-27T09:00:00+05:00"),
               ({"kind":"calendar","zone":"Asia/Qyzylorda","weekdays":list(range(1,8)),"times":["08:00"]},"2026-11-28T08:00:00+05:00"),
               ({"kind":"calendar","zone":"Asia/Qyzylorda","weekdays":[1],"times":["08:00"]},"2026-11-30T08:00:00+05:00"),
               ({"kind":"interval","zone":"Asia/Qyzylorda","every_us":37_000_000},"2026-11-27T08:00:37+05:00")]
        for rule,expected in cases:
            with self.subTest(rule=rule):self.assertEqual(schedule.next_after(rule,start,start),instant(expected))

    def test_dst_gap_and_fold(self):
        rule={"kind":"calendar","zone":"Europe/Berlin","weekdays":list(range(1,8)),"times":["02:30"]}
        self.assertEqual(schedule.next_after(rule,instant("2026-03-28T23:00:00Z"),0),instant("2026-03-30T00:30:00Z"))
        first=instant("2026-10-25T00:30:00Z")
        self.assertEqual(schedule.next_after(rule,first-1,0),first)
        self.assertEqual(schedule.next_after(rule,first,0),instant("2026-10-26T01:30:00Z"))

    def test_invalid_schedule_has_no_silent_default(self):
        for rule in ({"kind":"monthly","zone":"UTC","monthdays":[0],"times":["12:00"]},
                     {"kind":"monthly","zone":"UTC","monthdays":[True],"times":["12:00"]},
                     {"kind":"monthly","zone":"Unknown/City","monthdays":[1],"times":["12:00"]},
                     {"kind":"once","zone":"UTC","at":"2026-11-28T09:00"}):
            with self.subTest(rule=rule),self.assertRaises(ValueError):schedule.validate(rule)


class Fixture:
    def setup_fixture(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/"timer.db"
        self.identity=RegistrationStore(self.path);domain.init(self.identity)
        self.identity.create_account("owner","password");self.identity.create_account("other","password")
        self.token=self.identity.login("owner","password");self.other_token=self.identity.login("other","password")
        chat=workshops.choose_chat(self.identity,self.token)["chatId"];other=workshops.choose_chat(self.identity,self.other_token)["chatId"]
        self.scope=self.identity.resolve_chat(self.token,chat);self.other=self.identity.resolve_chat(self.other_token,other)
        with self.identity._write() as db:timer.initialize(db);account_lifecycle.initialize(db)
    def teardown_fixture(self):
        self.identity.close();self.tmp.cleanup()
    def call(self,fn,*args,scope=None,**kwargs):
        with self.identity._write() as db:return fn(db,scope or self.scope,*args,**kwargs)
    def definition(self,report="profit",channels=None,**kwargs):
        return {"title":"Мой отчёт","kind":"report","schedule":{"kind":"interval","zone":"UTC","every_us":60_000_000},
                "channels":channels or ["chat"],"report":{"report":report,"period":"today"},**kwargs}
    def create(self,raw=None,scope=None,now=None):
        args={} if now is None else {"now":now}
        preview=self.call(timer.prepare,uuid4().hex,raw or self.definition(),scope=scope,**args)
        return self.call(timer.confirm,uuid4().hex,preview["id"],preview["revision"],preview["receipt"],scope=scope,**args)
    def seed(self):
        with self.identity._write() as db:
            workshops.seed_demo(db,self.scope.workspace_id)
            book.execute(db,self.scope.workspace_id,"task-seed","task",{"name":"Проверить закупку","due":book.today().isoformat(),"remind_days":1})


class StoreContract(Fixture,unittest.TestCase):
    def setUp(self):self.setup_fixture()
    def tearDown(self):self.teardown_fixture()

    def test_new_account_has_timer_without_plugin_installation(self):
        with self.identity._write() as db:
            db.execute("DELETE FROM coin_grants WHERE workspace_id=?",(self.scope.workspace_id,))
        self.assertEqual(self.identity._db.execute("SELECT available FROM coin_wallet_balances WHERE workspace_id=?",(self.scope.workspace_id,)).fetchone()[0],0)
        value=self.call(timer.listing)
        self.assertEqual(len(value["reports"]),6)
        event=self.create()
        self.assertEqual(event["status"],"active")
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM chat_plugins").fetchone()[0],0)

    def test_assistant_uses_existing_grant_and_only_prepares_owner_confirmation(self):
        from platform_core.operation_grants import issue_grant
        from platform_core.podmasterye_mcp import ProductionTools
        from platform_core.dispatch import InvalidToolInput
        from platform_core.identity import _secret_digest
        grant=issue_grant(self.path,self.scope,source="chat.turn",run_key="timer-agent",session_digest=_secret_digest(self.token))
        tools=ProductionTools(self.identity,self.scope,"timer-agent",grant.token)
        args={"title":"От помощника","schedule":{"kind":"calendar","zone":"UTC","weekdays":[1],"times":["09:00"]},
              "channels":["chat"],"report":{"report":"tasks","period":"today","filters":{"task_categories":["Закупки"]}}}
        first=tools.call_tool("timer_prepare",args)
        self.assertEqual(first,tools.call_tool("timer_prepare",args))
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM timer_events").fetchone()[0],0)
        self.assertEqual(len(tools.call_tool("timer_list",{})["drafts"]),1)
        with self.assertRaises(InvalidToolInput):tools.call_tool("timer_prepare",{**args,"shell":"touch unsafe"})
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0],0)

    def test_creation_confirm_replay_and_conflict(self):
        raw=self.definition();p=self.call(timer.prepare,"same",raw)
        self.assertEqual(p,self.call(timer.prepare,"same",raw))
        with self.assertRaises(HTTPException):self.call(timer.prepare,"same",dict(raw,title="Other"))
        e=self.call(timer.confirm,"save",p["id"],p["revision"],p["receipt"])
        self.assertEqual(e,self.call(timer.confirm,"save",p["id"],p["revision"],p["receipt"]))
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM timer_events").fetchone()[0],1)

    def test_expired_preview_and_stale_revision(self):
        now=int(__import__('time').time());p=self.call(timer.prepare,"preview",self.definition(),now=now)
        with self.assertRaises(HTTPException):self.call(timer.confirm,"expired",p["id"],p["revision"],p["receipt"],now=now+1800)
        event=self.create();a=self.call(timer.prepare,"edit-a",dict(self.definition(),title="A"),event["id"],event["revision"])
        b=self.call(timer.prepare,"edit-b",dict(self.definition(),title="B"),event["id"],event["revision"])
        self.call(timer.confirm,"save-a",a["id"],a["revision"],a["receipt"])
        with self.assertRaises(HTTPException):self.call(timer.confirm,"save-b",b["id"],b["revision"],b["receipt"])

    def test_pause_resume_cancel_preserves_history_and_version(self):
        event=self.create();paused=self.call(timer.control,"pause",event["id"],"pause",event["revision"])
        self.assertEqual((paused["status"],paused["nextAt"]),("paused",None))
        with self.assertRaises(HTTPException):self.call(timer.control,"old-resume",event["id"],"resume",event["revision"])
        resumed=self.call(timer.control,"resume",event["id"],"resume",paused["revision"])
        self.assertEqual(resumed["status"],"active")
        cancelled=self.call(timer.control,"cancel",event["id"],"cancel",resumed["revision"])
        self.assertEqual(cancelled["status"],"cancelled")
        with self.assertRaises(HTTPException):self.call(timer.control,"run-cancelled",event["id"],"run",cancelled["revision"])
        self.assertEqual(self.call(timer.history,event["id"])["runs"],[])

    def test_cross_account_operations_are_denied(self):
        event=self.create()
        for fn,args in ((timer.history,(event["id"],)),(timer.control,("bad",event["id"],"run",1))):
            with self.assertRaises((HTTPException,PermissionError)):self.call(fn,*args,scope=self.other)
        self.assertEqual(self.call(timer.listing,scope=self.other)["events"],[])

    def test_manual_request_is_idempotent(self):
        event=self.create();a=self.call(timer.control,"manual",event["id"],"run",1)
        self.assertEqual(a,self.call(timer.control,"manual",event["id"],"run",1))
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM timer_runs").fetchone()[0],1)

    def test_upgrade_and_repeat_preserve_existing_data(self):
        self.seed();event=self.create()
        before=self.identity._db.execute("SELECT COUNT(*),SUM(CAST(json_extract(finance,'$.revenue') AS INTEGER)) FROM pm_book_events").fetchone()
        with self.identity._write() as db:timer.initialize(db);timer.initialize(db)
        self.assertEqual(before,self.identity._db.execute("SELECT COUNT(*),SUM(CAST(json_extract(finance,'$.revenue') AS INTEGER)) FROM pm_book_events").fetchone())
        self.assertEqual(self.call(timer.listing)["events"][0]["id"],event["id"])

    def test_all_six_reports_match_authoritative_book_without_coin_debit(self):
        self.seed()
        with self.identity._lock:
            db=self.identity._db;before=db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0]
            expected=book.report(db,self.scope.workspace_id,start=book.today().isoformat())
            results={name:reports.build(db,self.scope.workspace_id,{"report":name,"period":"today"},book.today()) for name in reports.REPORTS}
            self.assertEqual(results["profit"]["summary"]["net_profit"],expected["summary"]["net_profit"])
            self.assertEqual(results["sales"]["summary"]["revenue"],expected["summary"]["revenue"])
            self.assertEqual(results["stock"]["materials"],expected["materials"])
            self.assertEqual(results["purchases"]["planning"],expected["planning"])
            self.assertEqual(len(results["production"]["operations"]),1)
            self.assertEqual(results["tasks"]["tasks"],expected["tasks"])
            self.assertEqual(before,db.execute("SELECT COUNT(*) FROM coin_attempts").fetchone()[0])
            for result in results.values():self.assertIn("0 монет",reports.render(result))

    def test_relative_report_period_uses_occurrence_day(self):
        self.assertEqual(reports.period({"period":"previous_month"},date(2028,3,1)),("2028-02-01","2028-02-29"))
        self.assertEqual(reports.period({"period":"yesterday"},date(2026,1,1)),("2025-12-31","2025-12-31"))

    def test_missed_interval_is_coalesced_without_backlog(self):
        now=int(__import__('time').time());event=self.create(now=now-3600)
        with self.identity._write() as db:
            self.assertEqual(jobs.materialize(db,now*1_000_000,coalesce=True),1)
            self.assertEqual(jobs.materialize(db,now*1_000_000,coalesce=True),0)
            self.assertGreater(db.execute("SELECT next_us FROM timer_events WHERE id=?",(event["id"],)).fetchone()[0],now*1_000_000)

    def test_filters_use_existing_grouped_accounting_and_reject_ignored_filter(self):
        self.seed()
        with self.identity._lock:
            db=self.identity._db;w=self.scope.workspace_id
            base=book.report(db,w,start=book.today().isoformat())
            pid=base["products"][0]["id"]
            result=reports.build(db,w,{"report":"profit","period":"today","filters":{"products":[pid]}},book.today())
            grouped=next(r for r in base["by_product"] if r["key"]==pid)
            self.assertEqual(result["summary"]["net_profit"],grouped["net_profit"])
            self.assertIn("filterNote",result)
        with self.assertRaises(ValueError):reports.validate({"report":"tasks","filters":{"products":[pid]}})

    def test_cancel_draft_preserves_event_and_is_idempotent(self):
        event=self.create();p=self.call(timer.prepare,"draft-cancel",dict(self.definition(),title="Изменение"),event["id"],1)
        a=self.call(timer.cancel_draft,"cancel-draft",p["id"],p["revision"])
        self.assertEqual(a,self.call(timer.cancel_draft,"cancel-draft",p["id"],p["revision"]))
        self.assertEqual(self.call(timer.listing)["events"][0]["title"],event["title"])
        with self.assertRaises(HTTPException):self.call(timer.confirm,"deleted-preview",p["id"],p["revision"],p["receipt"])

    def test_invalid_typed_inputs_do_not_reach_storage(self):
        for raw in (dict(self.definition(),channels=[{}]),dict(self.definition(),report={"report":[]}),
                    dict(self.definition(),kind="action",operation={}),dict(self.definition(),schedule={"kind":"interval","zone":"UTC","every_us":True})):
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.call(timer.prepare,uuid4().hex,raw)
        event=self.create()
        with self.assertRaises(ValueError):self.call(timer.control,"bool-version",event["id"],"pause",True)

    def test_migration_failure_rolls_back_and_retry_succeeds(self):
        other=Path(self.root/"legacy.db")
        with RegistrationStore(other) as legacy:
            domain.init(legacy)
            with legacy._write() as db:
                store.initialize(db)
                for statement in jobs.SCHEMA:db.execute(statement)
            def authorizer(action,arg1,arg2,*rest):
                return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_ALTER_TABLE and arg2=="timer_runs" else sqlite3.SQLITE_OK
            legacy._db.set_authorizer(authorizer)
            with self.assertRaises(sqlite3.DatabaseError):
                with legacy._write() as db:timer.initialize(db)
            legacy._db.set_authorizer(None)
            self.assertNotIn("domain",{r[1] for r in legacy._db.execute("PRAGMA table_info(timer_events)")})
            with legacy._write() as db:timer.initialize(db);timer.initialize(db)
            self.assertIn("lease_token",{r[1] for r in legacy._db.execute("PRAGMA table_info(timer_runs)")})


class Outbound:
    def __init__(self,path):self.database_path=path;self.messages={};self.calls=0;self.fail=None
    async def request(self,scope,action,**kwargs):
        self.calls+=1
        if self.fail:raise self.fail
        self.messages.setdefault(kwargs["requestId"],kwargs["answer"])
        return {"role":"assistant","text":kwargs["answer"]}


class Telegram:
    def __init__(self):self.messages=[];self.fail=None
    async def send(self,workspace,text):
        if self.fail:raise self.fail
        self.messages.append((workspace,text))


class Execution(Fixture,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_fixture()
        self.worker=Outbound(self.path);self.telegram=Telegram()
        self.state=SimpleNamespace(identity=self.identity,worker=self.worker,telegram=self.telegram)
        # Exercise the real executor with deterministic queue draining. No
        # background timer or network stub can manufacture the business result.
        self.runtime=timer.Runtime(self.state)
        self.scheduler=object.__new__(jobs.Scheduler);self.scheduler.state=self.state;self.scheduler.runtime=self.runtime
    async def asyncTearDown(self):self.teardown_fixture()
    async def run_event(self,event):
        value=self.call(timer.control,uuid4().hex,event["id"],"run",event["revision"])
        run=value["runId"];due=self.identity._db.execute("SELECT due FROM timer_runs WHERE id=?",(run,)).fetchone()[0]
        await self.scheduler.execute(run,self.scope,due)
        return run,due
    def row(self,run):
        c=self.identity._db.execute("SELECT * FROM timer_runs WHERE id=?",(run,));return dict(zip([x[0] for x in c.description],c.fetchone()))

    async def test_report_runs_without_llm_and_delivers_both_once(self):
        self.seed();event=self.create(self.definition(channels=["chat","telegram"]))
        run,_=await self.run_event(event)
        self.assertEqual(self.row(run)["outcome"],"report")
        await asyncio.gather(self.scheduler.deliver_runtime(),self.scheduler.deliver_runtime())
        await self.scheduler.deliver_runtime()
        self.assertEqual(len(self.worker.messages),1);self.assertEqual(len(self.telegram.messages),1)
        history=domain.history(self.identity,self.token,self.scope,50)
        self.assertEqual(len(history),1);self.assertEqual(history[0]["role"],"assistant")
        self.assertEqual(self.row(run)["telegram_delivery"],"sent")

    async def test_concurrent_claim_executes_once(self):
        event=self.create();v=self.call(timer.control,"race",event["id"],"run",1);run=v["runId"];due=self.row(run)["due"]
        await asyncio.gather(*(self.scheduler.execute(run,self.scope,due) for _ in range(8)))
        self.assertEqual(self.row(run)["attempts"],1);self.assertEqual(self.row(run)["state"],"done")

    async def test_restart_replays_expired_read_not_external_write(self):
        event=self.create();v=self.call(timer.control,"crash",event["id"],"run",1);run=v["runId"]
        with self.identity._write() as db:
            db.execute("UPDATE timer_runs SET state='reading',lease_token='dead',lease_until=1,attempts=1 WHERE id=?",(run,))
            jobs.recover_expired(db,jobs.now_us())
        await self.scheduler.execute(run,self.scope,self.row(run)["due"])
        self.assertEqual(self.row(run)["state"],"done");self.assertEqual(self.row(run)["attempts"],2)
        with self.identity._write() as db:
            db.execute("UPDATE timer_runs SET state='writing',lease_until=1 WHERE id=?",(run,))
            jobs.recover_expired(db,jobs.now_us())
        self.assertEqual(self.row(run)["outcome"],"unknown")
        self.assertEqual(self.identity._db.execute("SELECT status FROM timer_events WHERE id=?",(event["id"],)).fetchone()[0],"paused")

    async def test_unexpired_claim_is_not_recovered(self):
        event=self.create();v=self.call(timer.control,"live",event["id"],"run",1);run=v["runId"]
        with self.identity._write() as db:
            db.execute("UPDATE timer_runs SET state='reading',lease_token='live',lease_until=? WHERE id=?",(jobs.now_us()+120_000_000,run))
            jobs.recover_expired(db,jobs.now_us())
        self.assertEqual(self.row(run)["state"],"reading")

    async def test_telegram_unknown_has_no_blind_retry(self):
        event=self.create(self.definition(channels=["telegram"]));run,_=await self.run_event(event)
        self.telegram.fail=TimeoutError()
        await self.scheduler.deliver_runtime();self.assertEqual(self.row(run)["telegram_delivery"],"unknown")
        with self.assertRaises(HTTPException):self.call(timer.retry_delivery,"retry",run,"telegram")
        self.assertEqual(self.row(run)["outcome"],"report")

    async def test_disconnected_delivery_can_resume_without_new_report(self):
        event=self.create(self.definition(channels=["chat","telegram"]));run,_=await self.run_event(event)
        self.telegram.fail=DeliveryError("disconnected")
        await self.scheduler.deliver_runtime();original=self.row(run)["result"]
        self.assertEqual(self.row(run)["chat_delivery"],"sent")
        self.telegram.fail=None;self.call(timer.retry_delivery,"retry",run,"telegram")
        await self.scheduler.deliver_runtime()
        self.assertEqual(len(self.telegram.messages),1);self.assertEqual(self.row(run)["result"],original)
        self.assertEqual(self.row(run)["attempts"],1)

    async def test_telegram_rate_limit_respects_retry_time_and_bound(self):
        event=self.create(self.definition(channels=["telegram"]));run,_=await self.run_event(event)
        self.telegram.fail=DeliveryError("limited",delay=61)
        await self.scheduler.deliver_runtime()
        row=self.row(run);self.assertEqual(row["telegram_delivery"],"pending")
        self.assertGreaterEqual(row["retry_at"],int(__import__('time').time())+60)
        await self.scheduler.deliver_runtime();self.assertEqual(self.row(run)["telegram_attempts"],1)

    async def test_revoked_account_neither_executes_nor_sends(self):
        event=self.create();run,_=await self.run_event(event)
        with self.identity._write() as db:db.execute("UPDATE account_lifecycle SET status='blocked' WHERE actor_id=?",(self.scope.actor_id,))
        await self.scheduler.deliver_runtime()
        self.assertEqual(self.row(run)["chat_delivery"],"revoked");self.assertEqual(self.worker.messages,{})

    async def test_block_then_restore_revokes_queued_manual_and_saved_delivery(self):
        event=self.create(self.definition(channels=["chat","telegram"]))
        paused=self.call(timer.control,"pause-first",event["id"],"pause",1)
        completed,due=await self.run_event(paused)
        pending=self.call(timer.control,"pending-manual",event["id"],"run",paused["revision"])["runId"]
        draft=self.call(timer.prepare,"before-block-draft",self.definition())
        self.identity.set_admin("other",True)
        admin=self.identity.login("other","password")
        for action in ("block","restore"):
            item=account_lifecycle.preview(self.identity,admin,[self.scope.actor_id],action)["items"][0]
            result=account_lifecycle.change(self.identity,admin,"lifecycle-"+action,
                [{"actor":item["actor"],"expected":item["expected"]}],action,"Проверка timer revocation")
            self.assertEqual(result["changed"],1)
        # Restoring access does not silently revive a manual request authorised
        # before the account was blocked, even on an already paused event.
        await self.scheduler.execute(pending,self.scope,self.row(pending)["due"])
        await self.scheduler.deliver_runtime()
        self.assertEqual(self.row(pending)["state"],"cancelled")
        self.assertEqual(self.row(completed)["chat_delivery"],"revoked")
        self.assertEqual(self.row(completed)["telegram_delivery"],"revoked")
        self.assertEqual(self.worker.messages,{})
        self.assertEqual(self.telegram.messages,[])
        self.assertEqual(self.identity._db.execute("SELECT status FROM timer_events WHERE id=?",(event["id"],)).fetchone()[0],"paused")
        with self.assertRaises(HTTPException):
            self.call(timer.confirm,"old-new-draft",draft["id"],draft["revision"],draft["receipt"])
        self.assertEqual(self.call(timer.listing)["drafts"],[])
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM timer_events").fetchone()[0],1)

    async def test_manual_run_of_paused_event_is_explicit(self):
        event=self.create();paused=self.call(timer.control,"pause",event["id"],"pause",1)
        run,_=await self.run_event(paused)
        self.assertEqual(self.row(run)["outcome"],"report")
        self.assertEqual(self.identity._db.execute("SELECT status FROM timer_events WHERE id=?",(event["id"],)).fetchone()[0],"paused")

    async def test_archived_workshop_restore_revokes_only_its_timer_authority(self):
        with patch.dict("os.environ", {"PODMASTERYE_MULTI_WORKSHOP": "1"}):
            additional=workshops.change(self.identity,self.token,"second-workshop","create",{"name":"Дополнительная мастерская"})
            chat=workshops.choose_chat(self.identity,self.token,additional["id"])["chatId"]
            scope=self.identity.resolve_chat(self.token,chat)
            main=self.create();extra=self.create(scope=scope)
            main_run=self.call(timer.control,"main-pending",main["id"],"run",main["revision"])["runId"]
            saved=self.call(timer.control,"extra-saved",extra["id"],"run",extra["revision"],scope=scope)["runId"]
            await self.scheduler.execute(saved,scope,self.row(saved)["due"])
            pending=self.call(timer.control,"extra-pending",extra["id"],"run",extra["revision"],scope=scope)["runId"]
            draft=self.call(timer.prepare,"extra-draft",self.definition(),scope=scope)
            for action in ("archive","restore"):
                workshops.change(self.identity,self.token,"extra-"+action,action,{"id":additional["id"]})
            await self.scheduler.execute(pending,scope,self.row(pending)["due"])
            await self.scheduler.deliver_runtime()
            self.assertEqual(self.row(pending)["state"],"cancelled")
            self.assertEqual(self.row(saved)["chat_delivery"],"revoked")
            self.assertEqual(self.worker.messages,{})
            with self.assertRaises(HTTPException):
                self.call(timer.confirm,"extra-stale-draft",draft["id"],draft["revision"],draft["receipt"],scope=scope)
            current=self.identity._db.execute("SELECT revision,status,next_us FROM timer_events WHERE id=?",(extra["id"],)).fetchone()
            self.assertEqual(tuple(current),(extra["revision"]+1,"paused",None))
            current=self.identity._db.execute("SELECT revision,status,next_us FROM timer_events WHERE id=?",(main["id"],)).fetchone()
            self.assertEqual(tuple(current[:2]),(main["revision"],"active"));self.assertIsNotNone(current[2])
            self.assertEqual(self.row(main_run)["state"],"queued")
            await self.scheduler.execute(main_run,self.scope,self.row(main_run)["due"])
            await self.scheduler.deliver_runtime()
            self.assertEqual(self.row(main_run)["outcome"],"report")
            self.assertEqual(self.row(main_run)["chat_delivery"],"sent")
            self.assertEqual(len(self.worker.messages),1)

    async def test_action_waits_then_shared_confirmation_is_atomic_idempotent(self):
        raw=self.definition();raw.pop("report");raw.update(kind="action",operation="expense",arguments={"category":"Прочее","total":"12.34"})
        event=self.create(raw);before=book.read(self.identity,self.token)["summary"]["expenses"]
        run,_=await self.run_event(event)
        self.assertEqual(self.row(run)["outcome"],"awaiting_confirmation")
        self.assertEqual(book.read(self.identity,self.token)["summary"]["expenses"],before)
        timer.confirm_action(self.identity,self.token,self.scope,run)
        timer.confirm_action(self.identity,self.token,self.scope,run)
        self.assertEqual(book.read(self.identity,self.token)["summary"]["expenses"],"12.34")
        self.assertEqual(self.identity._db.execute("SELECT COUNT(*) FROM pm_book_events WHERE rid=?",("timer-action-"+run,)).fetchone()[0],1)

    async def test_stale_action_and_cross_account_confirmation_do_not_write(self):
        raw=self.definition();raw.pop("report");raw.update(kind="action",operation="expense",arguments={"category":"Прочее","total":"12.34"})
        event=self.create(raw);run,_=await self.run_event(event)
        with self.assertRaises((HTTPException,PermissionError)):timer.confirm_action(self.identity,self.other_token,self.other,run)
        with self.identity._write() as db:book.execute(db,self.scope.workspace_id,"changed","expense",{"category":"Прочее","total":"1"})
        with self.assertRaises((HTTPException,ValueError)):timer.confirm_action(self.identity,self.token,self.scope,run)
        self.assertEqual(book.read(self.identity,self.token)["summary"]["expenses"],"1.00")

    async def test_cancel_during_execution_discards_delivery(self):
        event=self.create();v=self.call(timer.control,"running",event["id"],"run",1);run=v["runId"]
        entered=asyncio.Event();release=asyncio.Event();original=self.runtime.execute_event
        async def held(*args):
            entered.set();await release.wait();return await original(*args)
        self.runtime.execute_event=held
        task=asyncio.create_task(self.scheduler.execute(run,self.scope,self.row(run)["due"]))
        await entered.wait();self.call(timer.control,"cancel-during",event["id"],"cancel",1);release.set();await task
        self.assertEqual(self.row(run)["state"],"cancelled")
        await self.scheduler.deliver_runtime();self.assertEqual(self.worker.messages,{})

    async def test_expired_claim_cannot_overwrite_new_lease_result(self):
        event=self.create();v=self.call(timer.control,"fenced",event["id"],"run",1);run=v["runId"]
        entered=asyncio.Event();release=asyncio.Event();original=self.runtime.execute_event;calls=0
        async def held(*args):
            nonlocal calls
            calls+=1
            if calls==1:
                entered.set();await release.wait()
                return {"outcome":"report","message":"stale result"}
            return await original(*args)
        self.runtime.execute_event=held
        first=asyncio.create_task(self.scheduler.execute(run,self.scope,self.row(run)["due"]))
        await entered.wait()
        with self.identity._write() as db:
            db.execute("UPDATE timer_runs SET lease_until=1 WHERE id=?",(run,));jobs.recover_expired(db,jobs.now_us())
        await self.scheduler.execute(run,self.scope,self.row(run)["due"])
        release.set();await first
        self.assertNotEqual(self.row(run)["message"],"stale result")
        self.assertEqual(self.row(run)["attempts"],2)

    async def test_two_scheduler_process_sessions_and_restart_do_not_duplicate(self):
        event=self.create(self.definition(schedule={"kind":"interval","zone":"UTC","every_us":3_600_000_000}))
        v=self.call(timer.control,"two-workers",event["id"],"run",1);run=v["runId"]
        a=jobs.Scheduler(self.state,self.runtime);b=jobs.Scheduler(self.state,self.runtime)
        try:
            async with asyncio.timeout(5):
                while self.row(run)["chat_delivery"]!="sent":await asyncio.sleep(.02)
            self.assertEqual(self.row(run)["attempts"],1)
            await a.close()
            async with asyncio.timeout(3):
                while not b.delivery_task:await asyncio.sleep(.02)
            self.assertEqual(len(self.worker.messages),1)
        finally:
            await a.close();await b.close()


if __name__=="__main__":unittest.main()
