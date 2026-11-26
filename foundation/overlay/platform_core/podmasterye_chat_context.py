"""Podmasterye adapter to the copied native Harness transcript and attachment journal.

No file parsing, billing, vision or ASR implementation lives here.
"""
import asyncio
import json
import sqlite3
import weakref
from contextlib import closing
from starlette.concurrency import run_in_threadpool
from . import chat_attachments, podmasterye_domain as domain

class ChatContext:
    def __init__(self,state):
        self.state=state
        self._locks=weakref.WeakValueDictionary()

    def lock(self,scope):
        key=chat_attachments.scope_key(scope)
        lock=self._locks.get(key)
        if lock is None:
            lock=asyncio.Lock();self._locks[key]=lock
        return lock

    def has_files(self,scope):
        journal=self.state.worker.journal
        if not journal.is_file():return False
        with closing(sqlite3.connect(journal)) as db:
            if not db.execute("SELECT 1 FROM sqlite_schema WHERE name='native_batches'").fetchone():return False
            return bool(db.execute("""SELECT 1 FROM chat_files f JOIN native_batches b USING(scope_key,request_id)
                WHERE f.scope_key=? AND f.actor_id=? AND (f.position IS NOT NULL OR instr(b.events,f.id)>0) LIMIT 1""",
                (chat_attachments.scope_key(scope),scope.actor_id)).fetchone())

    def _local(self,scope,token,rid):
        identity=self.state.identity
        with identity._lock:
            db=identity._db
            domain.assert_scope(db,token,scope)
            rows=db.execute("""SELECT rid,text,result FROM pm_turns WHERE workspace=? AND chat=?
                AND route='local' AND result IS NOT NULL AND rowid<=(SELECT rowid FROM pm_turns WHERE workspace=? AND chat=? AND rid=?) ORDER BY rowid""",
                (scope.workspace_id,scope.chat_id,scope.workspace_id,scope.chat_id,rid)).fetchall()
        seen=set()
        journal=self.state.worker.journal
        if journal.is_file():
            with closing(sqlite3.connect(journal)) as db:
                if db.execute("SELECT 1 FROM sqlite_schema WHERE name='native_batches'").fetchone():
                    seen={r[0] for r in db.execute("SELECT request_id FROM native_batches WHERE scope_key=?",(chat_attachments.scope_key(scope),))}
        return [(k,t,json.loads(r)["text"]) for k,t,r in rows if k not in seen]

    async def sync_local(self,scope,token,rid):
        rows=await run_in_threadpool(self._local,scope,token,rid)
        # Import the frozen guest prefix before the first member exchange.
        claimed=await run_in_threadpool(self.state.identity.has_claimed_guest_turns,scope)
        for k,text,answer in rows:
            await self.state.worker.request(scope,"localExchange",requestId=k,text=text,answer=answer,claimedGuest=claimed)

    async def enrich(self,scope,messages):
        # Native history is authoritative for the lifetime and publication of files.
        if not await run_in_threadpool(self.has_files,scope):
            for m in messages:m.pop("attachments",None)
            return
        native=await self.state.worker.request(scope,"history",limit=50)
        files={(m["requestId"],m["role"]):m["attachments"] for m in native if m.get("attachments")}
        for m in messages:
            a=files.get((m.get("requestId"),m.get("role")))
            m.pop("attachments",None)
            if a:m["attachments"]=a
