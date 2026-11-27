"""Acceptance through the production native agent with an isolated model fixture."""
import csv,io,json,sqlite3,unittest,zipfile
from xml.etree import ElementTree as ET
from uuid import uuid4
from openpyxl import load_workbook
from pypdf import PdfReader
from native.file_formats import supported_extensions,format_groups
from tests import test_podmasterye_foundation as foundation

class OwnerV21(unittest.TestCase):
    setUp=foundation.Foundation.setUp
    actor=foundation.Foundation.actor
    turn=foundation.Foundation.turn
    wallet=foundation.Foundation.wallet

    def action(self,h,c,rid,name,args):
        msg="fixture-action:"+json.dumps({"name":name,"input":args},ensure_ascii=False)
        r=self.turn(h,c,rid,msg)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()
    def create(self,h,c,rid,fmt,content):
        return self.action(h,c,rid,"create_document",{"format":fmt,"name":rid+"."+fmt,"content_json":json.dumps(content,ensure_ascii=False)})
    def download(self,h,m):
        self.assertEqual(len(m.get("attachments",[])),1,m)
        f=m["attachments"][0]
        self.assertEqual(self.c.get(f["download"],headers=h).status_code,200,m)
        raw=self.c.get(f["download"],headers=h).content
        self.assertEqual(len(raw),f["bytes"])
        return f,raw
    def check_file(self,fmt,raw,value):
        if fmt=="xlsx":
            wb=load_workbook(io.BytesIO(raw));self.assertEqual(wb.active["B2"].value,value)
            self.assertEqual(wb.active["A2"].value,"Бусины");self.assertEqual(wb.active["B3"].value,"=SUM(B2:B2)");wb.close()
        elif fmt=="csv":
            self.assertEqual(list(csv.reader(io.StringIO(raw.decode("utf-8-sig")),delimiter=";")),[["Материал","Шт."],["Бусины",str(value)]])
        elif fmt=="json":
            self.assertEqual(json.loads(raw),{"material":"Бусины","quantity":value})
        elif fmt=="txt":self.assertEqual(raw.decode("utf-8"),f"Бусины: {value}")
        elif fmt=="pdf":
            t=" ".join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
            self.assertIn(str(value),t);self.assertIn("Бусины",t);self.assertIn("Отчёт",t)
        elif fmt in ("docx","pptx"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                member="word/document.xml" if fmt=="docx" else "ppt/slides/slide1.xml"
                t=" ".join(ET.fromstring(z.read(member)).itertext())
                self.assertIn(str(value),t);self.assertIn("Бусины",t);self.assertIn("Отчёт",t)

    def test_01_formats(self):
        extensions=supported_extensions()
        self.assertEqual(len(extensions),56)
        self.assertEqual(set(extensions),set().union(*format_groups().values()))
        h,c=self.actor("buyer")
        page=self.c.get("/app/",cookies={"__Host-podmaster_session":h["Authorization"].split()[1]})
        self.assertEqual(page.status_code,200)
        self.assertIn("Форматы файлов (56)",page.text)
        for ext in extensions:self.assertIn("."+ext,page.text)

    def test_02_business_confirm_edit_and_scope(self):
        h,c=self.actor("buyer");other,oc=self.actor("other")
        r=self.turn(h,c,"seed","Свободная формулировка: подготовьте расчёт.")
        self.assertEqual(r.status_code,200,r.text);m=r.json()
        self.assertEqual(m["confirmation"]["status"],"pending")
        self.assertEqual(self.c.get("/api/production",headers=h).json()["materials"],[])
        def confirm(rid,auth=h,chat=c):
            return self.c.post(f"/api/chats/{chat}/confirm",headers=auth,json={"draftId":rid})
        self.assertEqual(confirm("seed",other).status_code,404)
        self.assertEqual(confirm("seed",other,oc).status_code,400)
        a=confirm("seed");self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(confirm("seed").json(),a.json())
        d=self.c.get("/api/production",headers=h).json()
        self.assertEqual(len(d["materials"]),1);self.assertEqual(len(d["products"]),1)
        self.assertEqual(d["products"][0]["material_cost_rub"],"80.00")
        m=self.action(h,c,"edit","mcp__platform__prepare_edit",{"kind":"material","id":"Бусины","changes":{"pack_price":"1000"}})
        self.assertEqual(m["confirmation"]["status"],"pending",m)
        self.assertEqual(m["accountingDraft"]["arguments"]["pack"],400)
        self.assertEqual(m["accountingDraft"]["arguments"]["unit"],"шт")
        self.assertEqual(self.c.get("/api/production",headers=h).json()["products"][0]["material_cost_rub"],"80.00")
        a=self.turn(h,c,"typed","сохрани")
        self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(a.json()["confirmedDraft"],"edit")
        self.assertEqual(self.c.get("/api/production",headers=h).json()["products"][0]["material_cost_rub"],"100.00")
        self.assertEqual(confirm("edit").status_code,200)
        self.assertEqual(self.c.get("/api/production",headers=other).json()["materials"],[])
        p=self.turn(h,c,"purchase","Тест свободной закупки: оформите покупку материала.")
        self.assertEqual(p.status_code,200,p.text)
        self.assertEqual(self.c.get("/api/accounting",headers=h).json()["materials"][0]["quantity"],0)
        a=confirm("purchase");self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(confirm("purchase").json(),a.json())
        ledger=self.c.get("/api/accounting",headers=h).json()
        self.assertEqual(ledger["materials"][0]["quantity"],400)
        event=next(e for e in ledger["events"] if e["kind"]=="purchase")
        m=self.action(h,c,"history-edit","mcp__platform__prepare_edit",{"kind":"event","id":event["id"],"reason":"Исправление количества по накладной","changes":{"quantity":2,"total":"1600"}})
        self.assertIn("correctionDraft",m,m);self.assertIn("confirmation",m,m)
        self.assertEqual(self.c.get("/api/accounting",headers=h).json()["materials"][0]["quantity"],400)
        a=confirm("history-edit");self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(self.c.get("/api/accounting",headers=h).json()["materials"][0]["quantity"],800)
        self.assertEqual(confirm("history-edit").json(),a.json())
        # A stale draft cannot commit after another accounting change.
        m=self.action(h,c,"stale","mcp__platform__prepare_edit",{"kind":"material","id":"Бусины","changes":{"pack_price":"2000"}})
        self.assertIn("confirmation",m,m)
        m=self.action(h,c,"fresh","mcp__platform__prepare_edit",{"kind":"material","id":"Бусины","changes":{"pack_price":"1200"}})
        self.assertEqual(confirm("fresh").status_code,200)
        self.assertEqual(confirm("stale").status_code,409)
        self.assertEqual(self.c.get("/api/production",headers=h).json()["products"][0]["material_cost_rub"],"120.00")

    def test_03_all_document_types_and_versions(self):
        h,c=self.actor("buyer");other,oc=self.actor("other")
        old={};new={}
        cases={
          "xlsx":({"sheets":[{"name":"Склад","rows":[["Материал","Шт."],["Бусины",400],["Итого",{"formula":"=SUM(B2:B2)"}]]}]},"/sheets/0/rows/1/1",500),
          "docx":({"title":"Отчёт","sections":[{"heading":"Закупки","paragraphs":["Бусины: 400"]}]},"/sections/0/paragraphs/0","Бусины: 500"),
          "pptx":({"title":"Отчёт","slides":[{"title":"Отчёт","bullets":["Бусины: 400"]}]},"/slides/0/bullets/0","Бусины: 500"),
          "pdf":({"title":"Отчёт","sections":[{"heading":"Закупки","paragraphs":["Бусины: 400"]}]},"/sections/0/paragraphs/0","Бусины: 500"),
          "csv":({"rows":[["Материал","Шт."],["Бусины",400]]},"/rows/1/1",500),
          "txt":({"text":"Бусины: 400"},"/text","Бусины: 500"),
          "json":({"data":{"material":"Бусины","quantity":400}},"/data/quantity",500)
        }
        for fmt,(content,pointer,value) in cases.items():
            with self.subTest(format=fmt):
                m=self.create(h,c,"create-"+fmt,fmt,content)
                f,raw=self.download(h,m);self.check_file(fmt,raw,400);old[fmt]=(f,raw)
                self.assertEqual(self.c.get(f["download"],headers=other).status_code,404)
                m=self.action(h,c,"read-"+fmt,"read_document",{"id":f["attachmentId"]})
                self.assertIn("Бусины",m["text"])
                m=self.action(h,c,"edit-"+fmt,"edit_document",{"id":f["attachmentId"],"name":"edited."+fmt,"patch_json":json.dumps([{"op":"replace","path":pointer,"value":value}],ensure_ascii=False)})
                nf,nraw=self.download(h,m);self.check_file(fmt,nraw,500)
                self.assertNotEqual(f["attachmentId"],nf["attachmentId"])
                self.assertEqual(self.c.get(f["download"],headers=h).content,raw)
                new[fmt]=(nf,nraw)
        if "txt" not in old or "json" not in old:return
        m=self.create(h,c,"create-zip","zip",{"files":[old["txt"][0]["attachmentId"],old["json"][0]["attachmentId"]]})
        f,raw=self.download(h,m)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertEqual(z.read(old["txt"][0]["name"]),old["txt"][1]);self.assertEqual(z.read(old["json"][0]["name"]),old["json"][1])
        m=self.action(h,c,"edit-zip","edit_document",{"id":f["attachmentId"],"patch_json":json.dumps([{"op":"replace","path":"/files/0","value":new["txt"][0]["attachmentId"]}])})
        nf,nraw=self.download(h,m)
        with zipfile.ZipFile(io.BytesIO(nraw)) as z:self.assertEqual(z.read(new["txt"][0]["name"]),new["txt"][1])
        self.assertEqual(self.c.get(f["download"],headers=h).content,raw)
        m=self.action(other,oc,"foreign-document","read_document",{"id":f["attachmentId"]})
        self.assertIn("недоступен",m["text"]);self.assertFalse(m.get("attachments"))
        m=self.action(h,c,"invalid-document","create_document",{"format":"txt","name":"../forbidden.txt","content_json":"{\"text\":\"a\"}"})
        self.assertIn("Некорректное имя",m["text"]);self.assertFalse(m.get("attachments"))
        m=self.action(h,c,"invalid-patch","edit_document",{"id":f["attachmentId"],"patch_json":'[{"op":"add","path":"/__proto__","value":{}}]'})
        self.assertIn("Недопустимый путь",m["text"]);self.assertFalse(m.get("attachments"))
        hist=self.c.get(f"/api/chats/{c}/messages",headers=h).json()
        self.assertTrue(any(a["attachmentId"]==nf["attachmentId"] for t in hist for a in t.get("attachments",[])))

