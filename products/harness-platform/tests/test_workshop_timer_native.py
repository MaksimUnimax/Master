"""Real installed Harness journal: timer publication, restart, replay and isolation.

No provider gateway or credentials are used. Set HARNESS_NODE_MODULES to the
accepted installed Harness dependencies; this is a native integration check,
not a replacement model or an implementation-only assertion.
"""
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from platform_core.chat_worker import ChatWorker, WorkerError
from platform_core.guest_registration import RegistrationStore
from platform_core import podmasterye_domain as domain, podmasterye_workshops as workshops


@unittest.skipUnless(os.getenv("HARNESS_NODE_MODULES"), "An accepted native Harness runtime must be supplied")
class NativeTimer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/"identity.db"
        self.identity=RegistrationStore(self.path);domain.init(self.identity)
        self.identity.create_account("timer-owner","pw");self.identity.create_account("timer-other","pw")
        self.scope=[]
        for login in ("timer-owner","timer-other"):
            token=self.identity.login(login,"pw");chat=workshops.choose_chat(self.identity,token)["chatId"]
            self.scope.append(self.identity.resolve_chat(token,chat))
        self.env=patch.dict(os.environ,{"HARNESS_OFFLINE_MODEL":"0","HARNESS_DIALOG_ENGINE":"native"})
        self.env.start();self.gateway=os.environ.pop("HARNESS_MODEL_GATEWAY_URL",None)
        self.worker=ChatWorker(self.path,self.root/"chats")
    async def asyncTearDown(self):
        await self.worker.close();self.identity.close();self.env.stop();self.tmp.cleanup()
        if self.gateway is not None:os.environ["HARNESS_MODEL_GATEWAY_URL"]=self.gateway

    async def test_native_restart_replay_context_and_other_account(self):
        request="timer_0123456789abcdef0123456789abcdef"
        text="Прибыль и расходы\nВыручка: 1500.00 ₽\nЧистая прибыль: 1000.00 ₽"
        first=await self.worker.request(self.scope[0],"timerExchange",requestId=request,text="",answer=text)
        self.assertEqual(first["text"],text)
        await self.worker.close()
        self.worker=ChatWorker(self.path,self.root/"chats")
        replay=await self.worker.request(self.scope[0],"timerExchange",requestId=request,text="",answer=text)
        self.assertEqual(replay,first)
        history=await self.worker.request(self.scope[0],"history",limit=50)
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]["role"],"assistant")
        self.assertEqual(history[0]["text"],text)
        self.assertEqual(await self.worker.request(self.scope[1],"history",limit=50),[])
        with self.assertRaises(WorkerError):
            await self.worker.request(self.scope[0],"timerExchange",requestId=request,text="",answer="Изменённый результат")
        with sqlite3.connect(self.worker.journal) as db:
            rows=db.execute("SELECT action,events FROM native_batches WHERE request_id=?",(request,)).fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][0],"timerExchange")
            self.assertIn("workshop-timer",rows[0][1])
            self.assertNotIn('"type":"user/message"',rows[0][1])


if __name__=="__main__":unittest.main()
