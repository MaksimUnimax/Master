"""Agent-first acceptance. All provider traffic stays in the local fixture."""
import json,sqlite3
from pathlib import Path
from tests.test_podmasterye_foundation import Foundation

class AgentFirst(Foundation):
    def payloads(self):
        return [json.loads(x) for x in Path(str(self.journal)+".requests").read_text().splitlines()]
    def native(self,chat):
        with sqlite3.connect(self.root/"chats/native-chats.sqlite3") as db:
            return [(rid,action,json.loads(events)) for rid,action,events in db.execute(
                "SELECT request_id,action,events FROM native_batches ORDER BY revision")]

    def test_local_and_model_share_one_context(self):
        h,c=self.actor("admin")
        a=self.turn(h,c,"local-first","Что ты умеешь7")
        self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(a.json()["route"],"local")
        self.assertIn("себестоимость",a.json()["text"])
        self.assertFalse(self.journal.exists())
        rows=self.native(c)
        self.assertEqual([(r[0],r[1]) for r in rows],[("local-first","localExchange")])
        events=json.dumps(rows[0][2],ensure_ascii=False)
        self.assertIn("Что ты умеешь7",events)
        self.assertIn(a.json()["text"],events.replace("\\n","\n"))
        for rid,text in [("free-first","Расскажи подробнее, что из этого пригодится мне?"),("free-topic","Какая погода завтра?"),("free-short","Почему?")]:
            r=self.turn(h,c,rid,text)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["route"],"model")
        second=self.turn(h,c,"local-second","покажи чистую прибыль")
        self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(second.json()["route"],"local")
        self.assertEqual(self.turn(h,c,"local-second","покажи чистую прибыль").json(),second.json())
        r=self.turn(h,c,"free-after","Что означает полученная цифра?")
        self.assertEqual(r.status_code,200,r.text)
        payloads=self.payloads()
        self.assertEqual(len(payloads),4)
        self.assertEqual([p["tools"] for p in payloads],[payloads[0]["tools"]]*4)
        self.assertEqual([p.get("system") for p in payloads],[payloads[0].get("system")]*4)
        # Look at the actual model payload, not the chat UI or a duplicated note.
        for p in payloads:
            text=json.dumps(p["messages"],ensure_ascii=False)
            self.assertIn("Что ты умеешь7",text)
            self.assertIn("себестоимость",text)
        self.assertIn("покажи чистую прибыль",json.dumps(payloads[-1]["messages"],ensure_ascii=False))
        self.assertIn("Чистая прибыль:",json.dumps(payloads[-1]["messages"],ensure_ascii=False))
        self.assertEqual([r[0] for r in self.native(c)],["local-first","free-first","free-topic","free-short","local-second","free-after"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM coin_attempts").fetchone()[0],4)
            plans=[json.loads(r[0]) for r in db.execute("SELECT plan FROM pm_route_decisions WHERE kind='model'")]
            self.assertEqual(len({p["prefixId"] for p in plans}),1)
    def test_guest_keeps_strict_gate(self):
        from tests.test_podmasterye_foundation import ORIGIN
        g=self.c.post("/guest/session",headers={"origin":ORIGIN}).json()["chat"]
        r=self.c.post(f"/guest/chats/{g}/turns",headers={"origin":ORIGIN,"accept":"application/json"},data={"request_id":"guest-unrelated","text":"Какая погода завтра? Расскажи анекдот."})
        self.assertEqual(r.status_code,200,r.text)
        turns=self.c.get(f"/guest/chats/{g}/events").json()["turns"]
        self.assertEqual(turns[-1]["answer"],self.app.state.identity.faq.template("scope"))
        self.assertFalse(self.journal.exists())
    def test_native_compaction_is_metered_and_history_remains(self):
        h,c=self.actor("admin")
        # Real durable turns, synthetic provider usage representing a cache hit.
        # The native Harness pressure engine, not a project summarizer, chooses the region.
        for i in range(10):
            t=("Материал для проверки памяти. " * 140)+f" Контрольная запись {i}."
            r=self.turn(h,c,"history-"+str(i),t)
            self.assertEqual(r.status_code,200,r.text)
        r=self.turn(h,c,"pressure","fixture-pressure: продолжи анализ материала")
        self.assertEqual(r.status_code,200,r.text)
        r=self.turn(h,c,"after-pressure","Продолжи работу по предыдущим сообщениям.")
        self.assertEqual(r.status_code,200,r.text)
        admissions=[json.loads(l) for l in self.journal.read_text().splitlines()]
        self.assertTrue(any(x.get("purpose")=="compaction" for x in admissions),admissions[-4:])
        rows=self.native(c)
        self.assertEqual(len(rows),12)
        self.assertTrue(any(e["type"].startswith("compaction/") for _,_,es in rows for e in es))
        hist=self.c.get(f"/api/chats/{c}/messages",headers=h).json()
        self.assertEqual(len(hist),24)
        self.assertIn("Контрольная запись 0",hist[0]["text"])
        with sqlite3.connect(self.db) as db:self.assertGreater(db.execute("SELECT count(*) FROM coin_attempts WHERE charge IS NOT NULL").fetchone()[0],12)
