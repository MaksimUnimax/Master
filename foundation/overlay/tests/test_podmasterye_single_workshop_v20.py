"""Single-workshop default and reversible multi-workshop capability."""
import os
import sqlite3
from unittest.mock import patch
from tests.test_podmasterye_accounting import Accounting
from platform_core import podmasterye_agent_forms as forms

class SingleWorkshop(Accounting):
    def test_disabled_feature_and_restoration(self):
        self.enterContext(patch.dict(os.environ,{"PODMASTERYE_MULTI_WORKSHOP":"0"}))
        root=self.client.get("/api/workshops",headers=self.h).json()
        self.assertFalse(root["multipleEnabled"])
        self.assertEqual(len(root["workshops"]),1)
        wid=root["default"]
        self.seed()
        with patch.dict(os.environ,{"PODMASTERYE_MULTI_WORKSHOP":"1"}):
            self.assertIn("workshop_create",forms.active_names())
            demo=self.workshop("demo",{}).json()
            self.assertNotEqual(demo["id"],wid)
            ch=self.call("/api/workshops/chat",{"workshop":demo["id"]}).json()["chatId"]
            self.assertEqual(self.report(workshop=demo["id"])["summary"]["net_profit"],"1000.00")
        with sqlite3.connect(self.db) as db:
            before=db.execute("select id,account,name,archived,demo from pm_workshops order by id").fetchall()
        self.assertNotIn("workshop_create",forms.active_names())
        self.assertNotIn("workshop_create",forms.catalog()["other"])
        self.assertNotIn("workshop_create",forms.schema()["properties"]["form"]["enum"])
        self.assertIn("workshop_create",forms.EXTRA)
        for op,args in [
            ("create",{"name":"Вторая"}),
            ("demo",{}),
            ("archive",{"id":demo["id"]}),
            ("restore",{"id":demo["id"]}),
            ("update",{"id":demo["id"],"name":"Другая"}),
        ]:
            r=self.workshop(op,args)
            self.assertEqual(r.status_code,409,r.text)
        listed=self.client.get("/api/workshops",headers=self.h).json()
        self.assertEqual([w["id"] for w in listed["workshops"]],[wid])
        self.assertEqual(self.call("/api/workshops/chat",{"workshop":demo["id"]}).status_code,400)
        self.assertEqual(self.client.get("/api/accounting",headers=self.h,params={"workshop":demo["id"]}).status_code,400)
        self.assertEqual(self.call("/api/chats/"+ch+"/turns",{"requestId":"disabled-secondary","text":"покажи прибыль"}).status_code,400)
        self.assertEqual(self.client.get("/api/chats/"+ch+"/messages",headers=self.h).status_code,400)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("select id,account,name,archived,demo from pm_workshops order by id").fetchall(),before)
        r=self.workshop("update",{"id":wid,"name":"Моя студия","hourly_rate":"450"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.report()["workshop"]["name"],"Моя студия")
        self.assertEqual(len(self.report()["materials"]),1)
        with patch.dict(os.environ,{"PODMASTERYE_MULTI_WORKSHOP":"1"}):
            restored=self.client.get("/api/workshops",headers=self.h).json()
            self.assertTrue(restored["multipleEnabled"])
            self.assertEqual(len(restored["workshops"]),2)
            self.assertEqual(self.report(workshop=demo["id"])["summary"]["net_profit"],"1000.00")
            self.assertEqual(self.call("/api/workshops/chat",{"workshop":demo["id"]}).json()["chatId"],ch)

    def test_creation_commands_answer_locally(self):
        self.enterContext(patch.dict(os.environ,{"PODMASTERYE_MULTI_WORKSHOP":"0"}))
        ch=self.call("/api/workshops/chat",{"workshop":None}).json()["chatId"]
        for i,command in enumerate(("создай новую мастерскую","переключись на другую мастерскую","можно ли создать вторую мастерскую")):
            r=self.call("/api/chats/"+ch+"/turns",{"requestId":f"blocked-{i}","text":command})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["route"],"local")
            self.assertIn("одна мастерская",r.json()["text"])
        r=self.call("/api/chats/"+ch+"/turns",{"requestId":"disabled-draft","text":"название: Новая","formContext":{"form":"workshop_create","arguments":{}}})
        self.assertEqual(r.status_code,400,r.text)
        self.assertFalse((self.tmp/"usage.jsonl").exists())
