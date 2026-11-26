"""Podmasterye composition acceptance with the copied Octoport media pipeline."""
import io,os,sqlite3,wave,json
from datetime import datetime,timezone
from unittest.mock import patch
import httpx
from PIL import Image
from openpyxl import Workbook
from tests.test_podmasterye_foundation import Foundation
from platform_core import provider_keys

class MediaAcceptance(Foundation):
    def upload(self,h,c,name,data):
        r=self.c.post("/api/session/uploadFileBinary",headers={**h,"Content-Type":"application/octet-stream"},params={"sessionId":c,"name":name},content=data)
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["ok"],r.text)
        return r.json()["value"]["receiptId"]
    def file_turn(self,h,c,rid,text,ids=None):
        a={"requestId":rid,"text":text}
        if ids is not None:a["attachments"]=ids
        return self.c.post(f"/api/chats/{c}/turns",headers=h,json=a)
    def test_attachment_context_replay_and_scope(self):
        h,c=self.actor("admin");other,oc=self.actor("other")
        h2,c2=self.actor("admin")
        self.assertEqual(self.turn(h,c,"local-1","покажи чистую прибыль").status_code,200)
        book=Workbook();book.active.append(["Маркер отчёта",714598]);source=io.BytesIO();book.save(source);raw=source.getvalue()
        fid=self.upload(h,c,"отчёт.xlsx",raw)
        path=f"/api/chats/{c}/files/{fid}"
        self.assertEqual(self.c.get(path+"/draft",headers=h).content,raw)
        self.assertEqual(self.c.get(path,headers=h).status_code,404)
        self.assertEqual(self.c.get(path+"/draft",headers=other).status_code,404)
        self.assertEqual(self.c.get(f"/api/chats/{c2}/files/{fid}/draft",headers=h2).status_code,404)
        self.assertEqual(self.c.get(path+"/process/auto",headers=h).json()["upperCoins"],"0")
        for auth,chat in ((h2,c2),(other,oc)):
            r=self.file_turn(auth,chat,"foreign","Прочитай приложенный файл",[fid]);self.assertEqual(r.status_code,404,r.text)
        r=self.file_turn(h,c,"read","Прочитай приложенный файл, учитывая контекст",[fid])
        self.assertEqual(r.status_code,200,r.text);self.assertIn("714598",r.json()["text"])
        self.assertEqual(self.file_turn(h,c,"read","Прочитай приложенный файл, учитывая контекст",[fid]).json(),r.json())
        self.assertEqual(self.file_turn(h,c,"read","Прочитай приложенный файл, учитывая контекст",[]).status_code,409)
        self.assertEqual(self.c.get(path,headers=h).content,raw)
        self.assertEqual(self.c.get(path,headers=other).status_code,404)
        self.assertEqual(self.c.get(path+"/draft",headers=h).status_code,404)
        history=self.c.get(f"/api/chats/{c}/messages",headers=h).json()
        self.assertEqual(len(history),4);self.assertEqual(history[2]["attachments"][0]["attachmentId"],fid)
        self.assertEqual(history[2]["attachments"][0]["download"],path)
        r=self.file_turn(h,c,"follow","Что было в предыдущем файле?")
        self.assertEqual(r.status_code,200,r.text);self.assertIn("714598",r.json()["text"])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM coin_attempts WHERE charge IS NOT NULL AND charge>0").fetchone()[0],6)
        self.assertEqual(self.c.delete(path,headers=h).status_code,204)
        self.assertEqual(self.c.get(path,headers=h).status_code,404)
        self.assertNotIn("attachments",self.c.get(f"/api/chats/{c}/messages",headers=h).json()[2])
    def test_file_only_and_vision_pdf_page(self):
        h,c=self.actor("buyer");b=Workbook();b.active.append(["Маркер",714598]);s=io.BytesIO();b.save(s)
        fid=self.upload(h,c,"data.xlsx",s.getvalue())
        r=self.file_turn(h,c,"only","",[fid]);self.assertEqual(r.status_code,200,r.text);self.assertIn("714598",r.json()["text"])
        h,c=self.actor("buyer")
        s=io.BytesIO();im=Image.new("RGB",(64,64),"#559977");im.save(s,format="PNG")
        fid=self.upload(h,c,"photo.png",s.getvalue())
        r=self.file_turn(h,c,"image","Проверь изображение",[fid]);self.assertEqual(r.status_code,200,r.text);self.assertIn("Изображение получено",r.json()["text"])
        h,c=self.actor("buyer")
        from pathlib import Path
        pdf=(Path(__file__).parent/"fixtures/files_review/visible-annotation.pdf").read_bytes()
        fid=self.upload(h,c,"layout.pdf",pdf)
        r=self.file_turn(h,c,"page","Проверь страницу PDF",[fid]);self.assertEqual(r.status_code,200,r.text);self.assertIn("Пиксели страницы PDF",r.json()["text"])
    def test_media_paid_receipt_cache_and_unknown_outcome(self):
        h,c=self.actor("admin")
        audio=io.BytesIO()
        with wave.open(audio,"wb") as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b"\0\0"*16000)
        png=io.BytesIO();Image.new("RGB",(32,32),"white").save(png,"PNG")
        from pathlib import Path
        pdf=(Path(__file__).parent/"fixtures/files_review/visible-annotation.pdf").read_bytes()
        calls=[]
        def fake(req):
            calls.append(req.url.path)
            if req.url.path=="/anthropic/v1/files":
                return httpx.Response(200,json={"id":"file-fixture-123456789","type":"file","size_bytes":len(pdf),"created_at":datetime.now(timezone.utc).isoformat()})

            if req.url.path=="/v1/tools/asr":
                return httpx.Response(200,json={"duration_ms":1000,"text":"Проверка распознавания речи","request_id":"asr-fixture"})
            if req.url.path=="/v1/tools/ocr":
                return httpx.Response(200,json={"purpose":"text_recognition","page_count":1,"pages":[{"index":0,"text":"Текст скана","finish_reason":"stop"}],"id":"ocr-fixture"})
            raise AssertionError(req.url.path)
        client=httpx.AsyncClient(transport=httpx.MockTransport(fake))
        with patch.object(self.app.state,"http",client),patch.object(provider_keys,"read",side_effect=lambda p:"synthetic-test-key" if p=="deepseek" else ""):
            fid=self.upload(h,c,"voice.wav",audio.getvalue())
            path=f"/api/chats/{c}/files/{fid}/process/asr"
            quote=self.c.get(path,headers=h);self.assertEqual(quote.status_code,200,quote.text)
            cap=quote.json()["upperCoins"]
            self.assertEqual(self.c.post(path,headers=h).status_code,428)
            r=self.c.post(path,headers={**h,"x-octoport-max-coins":cap});self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["text"],"Проверка распознавания речи")
            self.assertEqual(self.c.post(path,headers={**h,"x-octoport-max-coins":"0"}).json(),r.json())
            self.assertEqual(calls,["/v1/tools/asr"])
            duplicate=self.upload(h,c,"duplicate.wav",audio.getvalue())
            path2=f"/api/chats/{c}/files/{duplicate}/process/asr"
            self.assertTrue(self.c.get(path2,headers=h).json()["cached"])
            self.assertEqual(self.c.post(path2,headers={**h,"x-octoport-max-coins":"0"}).json(),r.json())
            fid=self.upload(h,c,"scan.png",png.getvalue());ocr=f"/api/chats/{c}/files/{fid}/process/ocr"
            cap=self.c.get(ocr,headers=h).json()["upperCoins"]
            r=self.c.post(ocr,headers={**h,"x-octoport-max-coins":cap});self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()["pages"][0]["text"],"Текст скана")
            self.assertEqual(calls,["/v1/tools/asr","/v1/tools/ocr"])
            self.assertEqual(self.c.post(ocr,headers={**h,"x-octoport-max-coins":"0"}).json(),r.json())
            doc=self.upload(h,c,"layout.pdf",pdf)
            parse=f"/api/chats/{c}/files/{doc}/process/parse-layout"
            cap=self.c.get(parse,headers=h).json()["upperCoins"]
            result=self.c.post(parse,headers={**h,"x-octoport-max-coins":cap})
            self.assertEqual(result.status_code,200,result.text);self.assertNotIn("mapping",result.json());self.assertNotIn("keyVersion",result.json())
            self.assertEqual(self.c.post(parse,headers={**h,"x-octoport-max-coins":"0"}).json(),result.json())
            self.assertEqual(calls,["/v1/tools/asr","/v1/tools/ocr","/anthropic/v1/files"])
            # A distinct file with an unknown provider outcome must not dispatch twice.
            other=io.BytesIO();Image.new("RGB",(33,33),"red").save(other,"PNG")
            failed=self.upload(h,c,"other.png",other.getvalue());url=f"/api/chats/{c}/files/{failed}/process/ocr"
            cap=self.c.get(url,headers=h).json()["upperCoins"];unknown=[]
            def timeout(req):
                unknown.append(req.url.path);raise httpx.ReadTimeout("fixture",request=req)
            with patch.object(self.app.state,"http",httpx.AsyncClient(transport=httpx.MockTransport(timeout))):
                for _ in range(2):
                    failure=self.c.post(url,headers={**h,"x-octoport-max-coins":cap})
                    self.assertIn(failure.status_code,(409,503),failure.text)
                self.assertEqual(len(unknown),1)
        with sqlite3.connect(self.db) as db:
            rows=db.execute("SELECT model,charge,usage_json FROM coin_attempts ORDER BY started_ms").fetchall()
            self.assertEqual(len(rows),4)
            self.assertEqual({json.loads(r[2])["unit"] for r in rows if r[2]},{"seconds","pages"})
            self.assertEqual(sum(r[1] is None for r in rows),1)
            self.assertTrue(all(r[1]>0 for r in rows if r[1] is not None))
        stats=self.c.get("/api/admin/podmasterye/usage",headers=h).json()
        m={r["mode"]:r for r in stats["media"]}
        self.assertEqual(m["asr"]["quantity"],1)
        self.assertEqual(m["ocr"]["attempts"],2)
        self.assertEqual(m["ocr"]["pending"],1)
        self.assertEqual(m["parse-layout"]["quantity"],2)

