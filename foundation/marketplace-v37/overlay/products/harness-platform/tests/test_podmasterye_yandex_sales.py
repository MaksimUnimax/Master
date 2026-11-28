"""Sales counts and durable report jobs through the authenticated integration."""
import csv,io,json,sqlite3,unittest,zipfile
from unittest.mock import patch,AsyncMock
import httpx
from starlette.exceptions import HTTPException
from tests import test_podmasterye_market_links as base
from platform_core import podmasterye_yandex_sales as sales
from tests.test_podmasterye_yandex_market import auth,campaign,SECRET

MARKET=base.MARKET
MONTH="2026-10"
SHOP=campaign(123)
def archive(duplicate=False,missing=False,wrong_date=False):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z:
        fields=[("delivered","DELIVERED_COUNT","DELIVERY_DATE",[
            ["100","A","Изделие A","3","2026-10-05"],["101","A","Изделие A","2","2026-10-06"],["102","B","Изделие B","1","2026-10-05"]]),
            ("returned","RETURNED_COUNT","RETURN_WAREHOUSE_OR_SC_ACCEPT_DATE",[["99","A","Изделие A","1","2026-10-06"]]),
            ("unredeemed","UNREDEEMED_COUNT","UNREDEEMED_WAREHOUSE_OR_SC_ACCEPT_DATE",[["103","B","Изделие B","2","2026-10-06"]])]
        for name,qty,day,rows in fields:
            if missing and name=="returned":continue
            w=io.StringIO();writer=csv.writer(w,delimiter=";")
            writer.writerow(["ORDER_ID","YOUR_SKU","OFFER_NAME",qty,day,"ORGANIZATION"])
            if duplicate and name=="delivered":rows=rows+rows[:1]
            if wrong_date and name=="delivered":rows[0][-1]="2026-09-01"
            for r in rows:writer.writerow(r+["not-retained-buyer"])
            z.writestr(name+".csv",w.getvalue().encode("utf-8-sig"))
    return b.getvalue()
def order(oid,status,units,counts=None,fake=False):
    i={"id":oid,"offerId":"A","offerName":"Изделие A","count":units}
    if counts is not None:i["itemStatuses"]=[{"status":k,"count":v} for k,v in counts.items()]
    return {"orderId":oid,"campaignId":123,"creationDate":"2026-10-05T10:00:00+03:00","status":status,"fake":fake,"items":[i],
        "delivery":{"address":{"street":"not-retained-buyer"}}}
class Parse(unittest.TestCase):
    def test_actual_quantities_and_no_buyer_data(self):
        d=sales.parse_report(archive(),MONTH,SECRET)
        self.assertEqual(d["totals"],{"delivered":6,"returned":1,"unredeemed":2,"net":5})
        self.assertEqual(d["orders"],3)
        self.assertEqual(d["products"][0]["net"],4)
        self.assertEqual(d["days"][1]["net"],1)
        self.assertNotIn("not-retained-buyer",json.dumps(d))
    def test_bad_archive_fails_closed(self):
        for data in (b"not-a-zip",archive(duplicate=True),archive(missing=True),archive(wrong_date=True)):
            with self.subTest(size=len(data)):
                with self.assertRaises(HTTPException):sales.parse_report(data,MONTH,SECRET)
class Collect(unittest.IsolatedAsyncioTestCase):
    async def test_orders_page_counts_and_unknown(self):
        calls=[]
        def reply(req):
            calls.append(req)
            self.assertEqual(req.url.host,"api.partner.market.yandex.ru")
            self.assertEqual(req.url.path,"/v1/businesses/12/orders")
            self.assertEqual(req.headers["Api-Key"],SECRET)
            if "pageToken" not in req.url.params:
                return httpx.Response(200,json={"orders":[order(111,"PARTIALLY_RETURNED",5,{"DELIVERED_TO_BUYER":3,"RETURNED":1,"REJECTED":1}),order(112,"DELIVERED",2)],"paging":{"nextPageToken":"next"}})
            return httpx.Response(200,json={"orders":[order(113,"DELIVERED",1,{"DELIVERED_TO_BUYER":1}),order(114,"DELIVERED",7,{"DELIVERED_TO_BUYER":7},True)]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
            d=await sales.orders(c,{"api_key":SECRET},{"businessId":12,"campaignId":123},"2026-10-01","2026-10-27")
        self.assertEqual(d["totals"],{"ordered":8,"delivered":5,"returned":1,"net":4,"unknown":2})
        self.assertEqual((d["orders"],d["skipped"],d["pages"]),(3,1,2))
        self.assertNotIn("not-retained-buyer",json.dumps(d))
    async def test_duplicate_and_bad_scope_not_saved(self):
        for bad in ("dup","scope","page-fail"):
            def reply(req):
                o=order(1,"DELIVERED",1,{"DELIVERED_TO_BUYER":1})
                if "pageToken" in req.url.params:
                    if bad=="scope":o["campaignId"]=456
                    if bad=="page-fail":return httpx.Response(429)
                    return httpx.Response(200,json={"orders":[o]})
                return httpx.Response(200,json={"orders":[o],"paging":{"nextPageToken":"next"}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
                with self.assertRaises(HTTPException):await sales.orders(c,{"api_key":SECRET},{"businessId":12,"campaignId":123},"2026-10-01","2026-10-27")
    async def test_download_host_and_no_credentials(self):
        def reply(req):
            self.assertNotIn("Api-Key",req.headers)
            return httpx.Response(200,content=archive())
        with patch.object(sales,"check_dns",new_callable=AsyncMock):
            async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as c:
                raw=await sales.download(c,"https://storage.yandexcloud.net/report.zip?signature=fixture")
                self.assertEqual(sales.parse_report(raw,MONTH,SECRET)["totals"]["net"],5)
                for u in ("http://storage.yandexcloud.net/file","https://storage.yandexcloud.net.evil.example/file","https://localhost/file"):
                    with self.assertRaises(HTTPException):await sales.download(c,u)
class Routes(unittest.TestCase):
    setUp=base.Integrations.setUp
    h=base.Integrations.h
    def test_collection_lifecycle(self):
        r=self.c.post(MARKET,headers=self.h(),json={"provider":"yandex_market","name":"Маркет","fields":{"api_key":SECRET}})
        self.assertEqual(r.status_code,200,r.text);url=MARKET+"/"+r.json()["id"]
        from tests.fixtures.market_dual import finish_fixture_job
        from platform_core import market_quantity as q
        cid=r.json()["id"]
        order_req={"campaignId":123,"from":"2026-10-01","to":"2026-10-27","refresh":True}
        report_req={"campaignId":123,"month":MONTH,"refresh":True}
        self.assertEqual(self.c.post(url+"/orders",headers=self.h(),json=order_req).status_code,409)
        check=self.c.post(url+"/check",headers=self.h(),json={})
        self.assertEqual(check.status_code,200,check.text)
        verified,events=finish_fixture_job(self,check.json()["job_id"])
        self.assertEqual(verified["state"],"ready")
        self.assertEqual(self.c.post(url+"/orders",headers=self.h("other"),json=order_req).status_code,404)
        self.assertEqual(self.c.post(url+"/orders",headers=self.h(),json={**order_req,"campaignId":999}).status_code,409)
        with patch.object(self.app.state.http,"request",side_effect=AssertionError("Route performed provider HTTP")):
            first=self.c.post(url+"/orders",headers=self.h(),json=order_req)
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(first.json()["state"],"collecting")
            second=self.c.post(url+"/orders",headers=self.h(),json=order_req)
            self.assertEqual(first.json()["job_id"],second.json()["job_id"])
        jobs=first.json()["jobs"]
        order_job=next(j["id"] for j in jobs if j["template_id"]=="YM-03")
        def orders_response(event):
            if event["template"]=="YM-03":return {"status_code":200,"headers":{},"payload":{"orders":[order(123,"DELIVERED",3,{"DELIVERED_TO_BUYER":3})],"paging":{}}}
        done,events=finish_fixture_job(self,order_job,fault=orders_response)
        self.assertEqual(done["state"],"ready")
        local=self.c.post(url+"/orders",headers=self.h(),json={**order_req,"refresh":False})
        self.assertEqual(local.status_code,200,local.text)
        self.assertEqual(local.json()["totals"]["delivered"],3)
        self.assertEqual(local.json()["totals"]["net"],3)
        self.assertLessEqual(len(local.json()["rows"]),30)
        self.assertNotIn("not-retained-buyer",local.text)
        self.assertEqual(self.c.post(url+"/realization",headers=self.h("other"),json=report_req).status_code,404)
        calendar=self.c.post(url+"/realization",headers=self.h(),json=report_req)
        self.assertEqual(calendar.status_code,200,calendar.text)
        report_job=next(j["id"] for j in calendar.json()["jobs"] if j["template_id"]=="YM-05")
        done,events=finish_fixture_job(self,report_job,fault=lambda e:{"status_code":200,"headers":{},"content":archive()} if e["download"] else None)
        self.assertEqual(done["state"],"ready")
        self.assertEqual(sum(e["generate"] for e in events),1)
        result=self.c.post(url+"/realization",headers=self.h(),json={**report_req,"refresh":False})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["totals"]["net"],5)
        with self.app.state.identity._lock:
            db=self.app.state.identity._db;w=db.execute("SELECT workspace FROM pm_market_connections WHERE id=?",(cid,)).fetchone()[0]
            self.assertEqual(db.execute("SELECT count(*) FROM pm_ym_order_snapshots").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM pm_ym_realization").fetchone()[0],0)
            with q.local(db,w,"yandex_market") as dest:
                rows=dest.execute("SELECT body FROM quantity_rows").fetchall()
                self.assertGreater(len(rows),0)
                self.assertNotIn("not-retained-buyer",str(rows))
                before_count=len(rows)
        self.assertEqual(self.c.post(url+"/keys",headers=self.h(),json={"version":1,"fields":{"api_key":"fixture-rotated"}}).status_code,200)
        self.assertEqual(self.c.post(url+"/realization",headers=self.h(),json={**report_req,"refresh":False}).status_code,409)
        self.assertEqual(self.c.post(url+"/remove",headers=self.h(),json={"version":2}).status_code,200)
        with self.app.state.identity._lock:
            self.assertEqual(q.selected_stores(self.app.state.identity._db,w),[])
            with q.local(self.app.state.identity._db,w,"yandex_market") as dest:
                self.assertEqual(dest.execute("SELECT count(*) FROM quantity_rows").fetchone()[0],before_count)
