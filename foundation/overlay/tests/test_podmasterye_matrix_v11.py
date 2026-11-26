"""Deterministic routing acceptance, no model or external credentials."""
from decimal import Decimal
from uuid import uuid4
from platform_core import podmasterye_matrix as matrix, podmasterye_router as router
from tests.test_podmasterye_accounting import Accounting

class MatrixAcceptance(Accounting):
    def setUp(self):
        super().setUp()
        self.chat=self.call("/api/chats",{}).json()["chatId"]
    def ask(self,text,context=None,rid=None,h=None):
        a={"requestId":rid or uuid4().hex,"text":text}
        if context is not None:a["formContext"]=context
        return self.call("/api/chats/"+self.chat+"/turns",a,h)
    def test_all_aliases_and_politeness(self):
        tested=0
        for entry in matrix.ITEMS:
            for alias in entry["aliases"]:
                for text in (alias, "Пожалуйста, "+alias.upper()+"!"):
                    r=self.ask(text)
                    self.assertEqual(r.status_code,200,(entry["id"],text,r.text))
                    self.assertEqual(r.json()["route"],"local")
                    self.assertEqual(r.json()["matrixId"],entry["id"],(entry["id"],text,r.text))
                    tested+=1
        self.assertEqual(tested,444)
        self.assertFalse((self.tmp/"usage.jsonl").exists())
        self.assertEqual(self.client.get("/api/wallet/balance",headers=self.h).json()["available"],"10")
    def test_composite_synonyms_negatives_and_analysis(self):
        self.seed()
        for text,reason in [("Покажите чистую прибыль за этот месяц","lexical"),("покажи прибыль; покажи выручку","composite"),
                            ("почему упала прибыль","analysis"),("не списывай материал","ambiguous"),("какая погода завтра","outside"),("прибыль","clarify")]:
            r=self.ask(text);self.assertEqual(r.status_code,200,(text,r.text))
            self.assertEqual(r.json()["filterReason"],reason,(text,r.text))
        a=self.ask("покажи прибыль; покажи выручку").json()
        self.assertEqual(a["matrixIds"],["A-R01","A-R02"])
        self.assertNotIn("accountingDraft",a)
        self.assertEqual(self.report()["summary"]["purchases"],"0.00")
        self.assertFalse((self.tmp/"usage.jsonl").exists())
    def test_local_form_context_and_confirmation(self):
        ids=self.recipe()
        r=self.ask("сумма: 1600 рублей; количество: 2",{"form":"book.purchase","arguments":{"material":ids["material_id"],"purchase_unit":"pack"}})
        self.assertEqual(r.status_code,200,r.text);d=r.json()["accountingDraft"]
        self.assertEqual(d["arguments"]["quantity"],2)
        self.assertEqual(d["preview"]["value_rub"],"1600.00")
        self.assertEqual(self.report()["materials"][0]["quantity"],0)
        r=self.ask("1600 рублей",{"form":"book.purchase","arguments":{"material":ids["material_id"],"purchase_unit":"pack","quantity":2}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["accountingDraft"]["preview"]["value_rub"],"1600.00")
        bad=self.ask("сумма: -100",{"form":"book.purchase","arguments":{"material":ids["material_id"],"quantity":1}})
        self.assertEqual(bad.json()["filterReason"],"invalid_parameter")
        self.commit(d);self.assertEqual(self.report()["materials"][0]["quantity"],800)
        self.assertFalse((self.tmp/"usage.jsonl").exists())
    def test_admin_versioned_editor_and_route_statistics(self):
        self.assertEqual(self.client.get("/api/admin/matrix",headers=self.h).status_code,403)
        self.app.state.identity.set_admin("owner",True)
        self.h=self.actor("owner")
        url="/api/admin/matrix/A-R01"
        r=self.call(url,{"revision":0,"aliases":["покажи хозяйственный итог"],"negatives":["до налога"]})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["revision"],1)
        a=self.ask("покажи хозяйственный итог");self.assertEqual(a.status_code,200,a.text);self.assertEqual(a.json()["matrixId"],"A-R01")
        self.assertEqual(self.call(url,{"revision":0,"aliases":[],"negatives":[]}).status_code,409)
        self.assertEqual(self.call(url,{"revision":1,"aliases":["покажи выручку"],"negatives":[]}).status_code,409)
        self.assertEqual(self.call(url,{"revision":1,"aliases":[],"negatives":["прибыль"]}).status_code,400)
        self.assertEqual(self.ask("погода в москве").status_code,200)
        stats=self.client.get("/api/admin/matrix/stats",headers=self.h)
        self.assertEqual(stats.status_code,200,stats.text);d=stats.json()
        self.assertEqual(d["local"],2);self.assertEqual(d["zeroLlmPercent"],100);self.assertEqual(d["calls"],0)
        self.assertEqual(d["hits"]["A-R01"],1)
        self.assertEqual(self.call(url,{"revision":1,"aliases":[],"negatives":[]}).status_code,200)
        with self.app.state.identity._lock:
            self.assertEqual(self.app.state.identity._db.execute("SELECT count(*) FROM pm_matrix_edit_history").fetchone()[0],2)

    def test_view_context_period_and_replay(self):
        first=self.ask("покажи чистую прибыль за этот месяц")
        self.assertEqual(first.status_code,200,first.text)
        body={"requestId":"view-followup","text":"а за вчера","viewContext":{"page":"finance","metric":"net_profit"}}
        url="/api/chats/"+self.chat+"/turns"
        r=self.call(url,body);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["filterReason"],"view_context")
        self.assertEqual(r.json()["ui"]["filters"],{"from":self.yesterday,"to":self.yesterday})
        self.assertEqual(self.call(url,body).json(),r.json())
        self.assertEqual(self.call(url,{**body,"viewContext":{"page":"sales"}}).status_code,409)
        for v in ({"page":"admin"},{"page":"finance","password":"fixture"},{"page":"finance","start":"not-a-date"}):
            x=self.call(url,{"requestId":uuid4().hex,"text":"а за вчера","viewContext":v})
            self.assertEqual(x.status_code,400,x.text)
        self.assertFalse((self.tmp/"usage.jsonl").exists())
