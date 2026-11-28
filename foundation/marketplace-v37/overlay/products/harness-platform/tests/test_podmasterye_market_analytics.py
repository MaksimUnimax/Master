"""Quantity contracts: original denominators, maturity and local planning.

These are deterministic domain/integration fixtures, not live API evidence.
"""
import ast
import calendar as cal
from copy import deepcopy
from datetime import date,datetime,timedelta
from decimal import Decimal
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from platform_core import podmasterye_market_analytics as a

ASOF=date(2026,11,28)
START,END=a._training_period(ASOF)


def order(ident="old",*,provider="ozon",store="store-a",sku="100",product="product-a",units=1000,losses=100,days=60,**changes):
    row={"provider":provider,"store_id":store,"sku":sku,"product_id":product,"product":"Изделие","name":"Артикул",
         "category_id":"category-a","quantity_basis":"order_cohort","natural_key":"order:"+ident,"order_id":ident,
         "scheme":"FBO","ordered_at":(ASOF-timedelta(days=days)).isoformat(),"ordered_qty":units,"delivered_qty":units,
         "cancelled_qty":0,"nonbuyout_qty":0,"physical_return_qty":losses,"lost_qty":losses,
         "terminal":True,"original_order_known":True,"physical_returns_known":True,"complete":True,
         "observed_at":ASOF.isoformat(),"source_id":"OZ-03"}
    row.update(changes);return row


def proof(provider="ozon",store="store-a",basis="order_cohort",start=START,end=ASOF):
    return [{"provider":provider,"store_id":store,"quantity_basis":basis,"role":role,"source_id":tid,
             "from":start.isoformat(),"to":end.isoformat(),"complete":True,"state":"ready","observed_through":ASOF.isoformat(),"observed_at":ASOF.isoformat()}
            for role,tid in (("orders","WB-03" if provider=="wb" else "YM-03" if provider=="yandex_market" else "OZ-03"),
                             ("returns","YM-04" if provider=="yandex_market" else "OZ-04"))]


def snapshot(rows,coverage=None):
    return {"rows":rows,"coverage":proof() if coverage is None else coverage,"stores":[],"observed_at":ASOF.isoformat()}


def calendar(ident="sale",*,provider="yandex_market",store="market",sku="200",product="product-a",day="2025-05-15",delivered=100,returned=20):
    row={"provider":provider,"store_id":store,"sku":sku,"product_id":product,"product":"Изделие","name":"Артикул",
         "quantity_basis":"calendar_event","natural_key":ident,"event_date":day,"delivered_qty":delivered,
         "physical_return_qty":returned,"physical_returns_known":True,"complete":True,"observed_at":ASOF.isoformat()}
    cov=[{"provider":provider,"store_id":store,"quantity_basis":"calendar_event","role":"realization","source_id":"YM-05",
          "from":day[:7]+"-01","to":day[:7]+"-"+str(cal.monthrange(int(day[:4]),int(day[5:7]))[1]),"complete":True,"state":"ready","observed_at":ASOF.isoformat()}]
    return row,cov


class QuantityAnalytics(unittest.TestCase):
    def test_recent_stale_snapshot_remains_visible_but_cannot_be_used_as_fresh(self):
        now=datetime.fromisoformat("2026-11-28T12:00:00+03:00")
        recent=order("recent",units=100,losses=10,days=5,terminal=False)
        cov=proof()
        for c in cov:c["observed_at"]="2026-11-27T11:59:59+03:00"
        s=snapshot([order(),recent],cov);s["observed_at"]="2026-11-27T11:59:59+03:00"
        result=a.sales_snapshot(s,from_="2026-11-23",to="2026-11-28",as_of=now)
        self.assertEqual(result["totals"]["ordered"],100)
        self.assertEqual(result["observed_at"],s["observed_at"])
        self.assertTrue(result["stale"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["forecast_complete"])
        self.assertEqual(result["coverage"][0]["proofs"][0]["observed_at"],s["observed_at"])
        rate=a.loss_rates_snapshot(s,as_of=now)["rows"][0]
        self.assertTrue(rate["stale"])
        self.assertIsNone(rate["value"])
        for c in cov:c["observed_at"]="2026-11-27T12:00:00+03:00"
        fresh=a.sales_snapshot(snapshot([order(),recent],cov),from_="2026-11-23",to="2026-11-28",as_of=now)
        self.assertFalse(fresh["stale"])
        self.assertTrue(fresh["complete"])

    def test_closed_historical_window_is_not_invalidated_by_daily_ttl(self):
        row,cov=calendar()
        cov[0]["observed_at"]="2025-06-01T12:00:00+03:00"
        old=a.sales_snapshot(snapshot([row],cov),from_="2025-05-01",to="2025-05-31",as_of="2026-11-28T12:00:00+03:00")
        self.assertTrue(old["complete"])
        self.assertFalse(old["stale"])
        self.assertEqual(old["freshness"]["status"],"closed")
        self.assertEqual(old["totals"]["net"],80)
        unresolved=order("pending",days=120,terminal=False)
        proofs=proof()
        for c in proofs:c["observed_at"]="2026-11-25T12:00:00+03:00"
        pending=a.sales_snapshot(snapshot([unresolved],proofs),from_=unresolved["ordered_at"],to=unresolved["ordered_at"],as_of="2026-11-28T12:00:00+03:00")
        self.assertTrue(pending["stale"])
        self.assertFalse(pending["complete"])

    def test_orders_without_required_return_source_are_not_a_complete_report(self):
        s=snapshot([order()],proof()[:1])
        result=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertFalse(result["complete"])
        self.assertIn("returns",result["coverage"][0]["missing_roles"])

    def test_single_posting_lookup_does_not_prove_all_orders_in_a_day(self):
        row=order(source_id="OZ-05");day=row["ordered_at"]
        cov=proof();cov[0].update(source_id="OZ-05",role="orders",**{"from":day,"to":day})
        result=a.sales_snapshot(snapshot([row],cov),from_=day,to=day,as_of=ASOF)
        self.assertEqual(result["totals"]["ordered"],1000)
        self.assertFalse(result["complete"])
        self.assertIn("orders",result["coverage"][0]["missing_roles"])

    def test_wb_realization_return_is_not_fabricated_physical_receipt(self):
        from tests.fixtures import market_quantity_cases as cases
        rows=[]
        sequence=cases.success_sequence("WB-04")
        for step in sequence:rows.extend(step["outcome"].get("rows",[]))
        rows=[{**r,"provider":"wb","store_id":"wb-real","product_id":"product-a"} for r in rows]
        cov=[{**sequence[-1]["outcome"]["coverage"],"provider":"wb","store_id":"wb-real","source_id":"WB-04","role":"realization","state":"ready"}]
        result=a.sales_snapshot(snapshot(rows,cov),from_="2026-10-01",to="2026-10-30",as_of=ASOF)
        self.assertEqual((result["totals"]["delivered"],result["totals"]["calendar_returns"],result["totals"]["net"]),(3,1,2))
        self.assertIsNone(result["totals"]["physical_returns"])
        self.assertIsNone(result["totals"]["estimated_physical_returns"])
        self.assertEqual(result["totals"]["estimated_delivered"],3)
        self.assertFalse(result["rows"][0]["material_net_supported"])
        self.assertTrue(result["warnings"])

    def test_fresh_overlap_updates_changing_suffix_without_expiring_closed_history(self):
        now="2026-11-28T12:00:00+03:00";cov=proof()
        for c in cov:c["observed_at"]="2026-09-01T12:00:00+03:00"
        fresh=[]
        for c in cov:
            fresh.append({**c,"from":"2026-09-30","observed_at":now})
        result=a.loss_rates_snapshot(snapshot([order()],cov+fresh),as_of=now)["rows"][0]
        self.assertFalse(result["stale"])
        self.assertEqual(result["value"],"0.1")
        # A day older than the rolling refresh remains mutable if unfinished.
        old_pending=order("unfinished",days=120,terminal=False)
        result=a.loss_rates_snapshot(snapshot([order(),old_pending],cov+fresh),as_of=now)["rows"][0]
        self.assertTrue(result["stale"])
        self.assertIsNone(result["value"])

    def test_original_denominator_and_known_losses_floor(self):
        fresh=order("fresh",units=100,losses=25,days=5,delivered_qty=20,cancelled_qty=25,
                    physical_return_qty=0,terminal=False)
        s=snapshot([order(),fresh])
        r=a.sales_snapshot(s,from_="2026-11-23",to=ASOF.isoformat(),as_of=ASOF)
        self.assertEqual(r["totals"]["ordered"],100)
        self.assertEqual(r["totals"]["net"],20)
        self.assertEqual(r["totals"]["estimated_losses"],25)
        self.assertEqual(r["totals"]["estimated_net"],75)
        # The known25 cancellations already consume the25 expected lost units.
        # They cannot simultaneously be forecast as10 physical buyer returns.
        self.assertEqual(r["totals"]["estimated_physical_returns"],0)
        self.assertEqual(r["totals"]["estimated_delivered"],75)
        self.assertEqual(r["totals"]["estimated_delivered"]+r["totals"]["cancelled"],100)
        self.assertTrue(r["forecast_complete"])
        rate=a.loss_rates_snapshot(s,as_of=ASOF)["rows"][0]
        self.assertEqual((rate["numerator"],rate["denominator"],rate["value"]),(100,1000,"0.1"))

    def test_maturity_29_30_31_days_and_unfinished_status(self):
        rows=[order("base")]
        for days in (29,30,31):
            rows.append(order(str(days),sku=str(days),units=100,losses=10,days=days,delivered_qty=100))
        rows.append(order("unresolved",sku="99",units=100,losses=10,days=90,terminal=False))
        normalized,_=a._rows(snapshot(rows),ASOF)
        mature={r["sku"]:r["_mature"] for r in normalized}
        self.assertEqual((mature["29"],mature["30"],mature["31"],mature["99"]),(False,True,True,False))
        rate=a.loss_rates_snapshot(snapshot(rows),as_of=ASOF)["rows"]
        pending=next(r for r in rate if r["sku"]=="99")
        self.assertEqual(pending["source_level"],"category")
        self.assertEqual(pending["denominator"],1200)
        self.assertEqual(pending["excluded_rows"],1)

    def test_fallback_sku_category_store_and_unknown(self):
        rows=[order("tiny",sku="1",units=1,losses=0),order("cat",sku="2",units=1000,losses=100),
              order("other-cat",sku="3",category_id="empty",units=1,losses=0)]
        rates={r["sku"]:r for r in a.loss_rates_snapshot(snapshot(rows),as_of=ASOF)["rows"]}
        self.assertEqual(rates["1"]["source_level"],"category")
        self.assertEqual(rates["2"]["source_level"],"sku")
        self.assertEqual(rates["3"]["source_level"],"store")
        r=a.loss_rates_snapshot(snapshot([rows[0]]),as_of=ASOF)["rows"][0]
        self.assertIsNone(r["value"])
        self.assertFalse(r["sample_sufficient"])
        self.assertEqual(r["numerator"],0)

    def test_coverage_gap_and_stale_returns_cannot_be_hidden(self):
        cov=proof();cov[0]["from"]=(START+timedelta(days=1)).isoformat()
        r=a.loss_rates_snapshot(snapshot([order()],cov),as_of=ASOF)["rows"][0]
        self.assertIsNone(r["value"])
        self.assertIn("orders",r["coverage"]["missing_roles"])
        cov=proof();cov[1]["observed_through"]=(ASOF-timedelta(days=1)).isoformat()
        r=a.loss_rates_snapshot(snapshot([order()],cov),as_of=ASOF)["rows"][0]
        self.assertIn("returns",r["coverage"]["missing_roles"])
        self.assertEqual(r["observed_ratio"],"0.1")
        self.assertIsNone(r["value"])

    def test_physical_union_reuses_octoport_semantics_and_duplicate_ids(self):
        orders=[{"scheme":"FBO","posting":"p1","sku":"100","day":"2026-09-29","units":3,"state":"cancelled"},
                {"scheme":"FBS","posting":"p2","sku":"200","day":"2026-09-29","units":3,"state":"delivered"}]
        returns=[{"scheme":"FBO","posting":"p1","sku":"100","exemplars":["11","12"],"type":"Cancellation"},
                 {"scheme":"FBS","posting":"p2","sku":"200","exemplars":["21"],"type":"ClientReturn"},
                 {"scheme":"FBS","posting":"p2","sku":"200","exemplars":["21"],"type":"ClientReturn"}]
        result=a.physical_outcome_union([*orders,orders[0]],returns)
        self.assertEqual((result["ordered_units"],result["failed_units"],result["returned_units"]),(6,4,3))
        self.assertEqual((result["duplicate_order_rows"],result["duplicate_return_exemplars"]),(1,1))
        # Compare directly with the already shipped pure reducer in the pinned
        # runtime archive. No provider or financial execution is involved.
        archive=Path(a.__file__).parent/"marketplace_matrix/runtime.tar.gz"
        with tarfile.open(archive) as t:
            tree=ast.parse(t.extractfile("parameter_support/parameter_producers.py").read())
        wanted={"physical_cohort","physical_outcomes"}
        code=compile(ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in wanted],type_ignores=[]),"octoport_quantity_reference","exec")
        def need(value,message):
            if not value:raise ValueError(message)
        def exact(value,keys):need(set(value)==set(keys),"schema")
        from collections import defaultdict
        ns={"deepcopy":deepcopy,"defaultdict":defaultdict,"date":date,"integer":a._integer,"text":a._text,"need":need,"exact":exact,
            "CATALOG":{"sources":{"returns":{"types":["Cancellation","ClientReturn","FullReturn","PartialReturn"]}}}}
        exec(code,ns)
        expected=ns["physical_outcomes"]([*orders,orders[0]],returns,{"scope":{"kind":"store"}},
                  {"actual":{"from":"2026-01-01","to":"2026-11-01"}},{})
        self.assertEqual(result,expected)
        with self.assertRaises(a.QuantityError):
            a.physical_outcome_union(orders,[{**returns[0],"exemplars":["1","2","3","4"]}])

    def test_late_return_updates_original_cohort_not_current_sales(self):
        original=order(units=100,losses=0)
        returned={"provider":"ozon","store_id":"store-a","sku":"100","quantity_basis":"calendar_event", "natural_key":"return:1",
                  "order_id":"old","scheme":"FBO","event_date":"2026-11-27","loss_event_qty":2,"physical_return_qty":2,
                  "physical_returns_known":True,"unit_ids":["1","2"],"return_type":"ClientReturn","terminal":True,"complete":True,"observed_at":ASOF.isoformat()}
        s=snapshot([original,returned,deepcopy(returned)])
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual((r["totals"]["ordered"],r["totals"]["physical_returns"],r["totals"]["losses"],r["totals"]["net"]),(100,2,2,98))
        now=a.sales_snapshot(s,from_="2026-11-01",to=ASOF.isoformat(),as_of=ASOF)
        self.assertEqual(now["totals"]["ordered"],0)
        self.assertEqual(now["totals"]["net"],0)

    def test_wb_funnel_preserves_intervals_and_does_not_invent_returns(self):
        row=order(provider="wb",units=1000,losses=200,delivered_qty=None,physical_return_qty=None,
                  physical_returns_known=False,quantity_basis="funnel_interval",interval_from=START.isoformat(),interval_to=END.isoformat(),source_id="WB-03")
        s=snapshot([row],proof("wb",basis="funnel_interval",start=START,end=END)[:1])
        rate=a.loss_rates_snapshot(s,as_of=ASOF)["rows"][0]
        self.assertEqual((rate["method"],rate["value"]),("cancelCount/orderCount","0.2"))
        self.assertIsNone(rate["physical_return_rate"])
        r=a.sales_snapshot(s,from_=START.isoformat(),to=END.isoformat(),as_of=ASOF)
        self.assertEqual(r["totals"]["net"],800)
        self.assertIsNone(r["totals"]["delivered"])
        self.assertIsNone(r["totals"]["physical_returns"])
        r=a.sales_snapshot(s,from_=START.isoformat(),to=END.isoformat(),as_of=ASOF,group_by="day")
        self.assertFalse(r["complete"])
        self.assertTrue(r["problems"])
        # Neither overlapping report alone covers the requested period. Keep
        # the fail-closed assertion without conflating it with an exact proof.
        left={**row,"interval_to":(END-timedelta(days=5)).isoformat()}
        overlap={**row,"natural_key":"overlap","interval_from":(START+timedelta(days=5)).isoformat()}
        cov=[*proof("wb",basis="funnel_interval",start=START,end=END-timedelta(days=5))[:1],
             *proof("wb",basis="funnel_interval",start=START+timedelta(days=5),end=END)[:1]]
        rate=a.loss_rates_snapshot(snapshot([left,overlap],cov),as_of=ASOF)["rows"][0]
        self.assertIsNone(rate["value"])
        self.assertTrue(rate["overlapping_intervals"])
        r=a.sales_snapshot(snapshot([left,overlap],cov),from_=START.isoformat(),to=END.isoformat(),as_of=ASOF)
        self.assertFalse(r["complete"])
        self.assertIsNone(r["totals"]["ordered"])

    def test_all_platforms_dedupe_projection_and_full_totals_before_paging(self):
        rows=[];cov=[]
        for provider in a.PROVIDERS:
            r=order(provider=provider,store=provider,sku="100",units=100,losses=10)
            rows.extend([r,deepcopy(r)]);cov.extend(proof(provider,provider))
        s=snapshot(rows,cov)
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF,group_by="marketplace",limit=1)
        self.assertEqual(r["total"],3)
        self.assertEqual(len(r["rows"]),1)
        self.assertEqual((r["totals"]["ordered"],r["totals"]["net"]),(300,270))
        mapped=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(mapped["total"],1)
        self.assertEqual(mapped["rows"][0]["providers"],["ozon","wb","yandex_market"])

    def test_aggregate_realization_never_duplicates_cohort_or_supplies_denominator(self):
        original=order()
        realized,cov=calendar(provider="ozon",store="store-a",sku="100",day="2026-09-29",delivered=1000,returned=100)
        s=snapshot([original,realized],[*proof(),*cov])
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["totals"]["net"],900)
        isolated=snapshot([realized],cov)
        r=a.loss_rates_snapshot(isolated,as_of=ASOF)["rows"][0]
        self.assertIsNone(r["value"])
        self.assertEqual(r["denominator"],0)

    def test_confirmed_zero_is_distinct_from_missing_data(self):
        s=snapshot([],proof())
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["status"],"no_data_confirmed")
        self.assertEqual(r["totals"]["ordered"],0)
        r=a.sales_snapshot(snapshot([],[]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["status"],"partial")
        self.assertIsNone(r["totals"]["ordered"])

    def test_unmapped_and_invalid_quantity_are_visible(self):
        s=snapshot([order(product=None)])
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["unmapped_count"],1)
        self.assertEqual(r["totals"]["net"],900)
        bad=order(units=5,losses=6)
        r=a.sales_snapshot(snapshot([bad]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertFalse(r["complete"])
        self.assertIsNone(r["totals"]["ordered"])

    def test_calendar_returns_exceed_deliveries_without_virtual_stock(self):
        row,cov=calendar(delivered=10,returned=20)
        r=a.sales_snapshot(snapshot([row],cov),from_="2025-05-01",to="2025-05-31",as_of=ASOF)
        self.assertEqual(r["totals"]["net"],-10)
        self.assertTrue(r["complete"])
        row=order(units=100,losses=20,delivered_qty=10)
        r=a.sales_snapshot(snapshot([row]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertFalse(r["complete"])

    def test_same_natural_fact_key_survives_key_generation_change(self):
        row=order(generation=1,observed_at="2026-11-27")
        new={**row,"generation":2,"observed_at":"2026-11-28"}
        r=a.sales_snapshot(snapshot([row,new]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["totals"]["ordered"],1000)

    def test_real_adapter_contract_joins_postings_and_return_events(self):
        from tests.fixtures.market_quantity_cases import success_sequence,context_for
        rows=[]
        for tid in ("OZ-03","OZ-06","OZ-04"):
            for step in success_sequence(tid):rows.extend(step["outcome"]["rows"])
        cov=proof("ozon","test-store")
        r=a.sales_snapshot(snapshot(rows,cov),from_="2026-10-01",to="2026-10-30",as_of=ASOF)
        self.assertTrue(r["complete"],r["problems"])
        self.assertEqual((r["totals"]["ordered"],r["totals"]["delivered"],r["totals"]["physical_returns"],r["totals"]["net"]),(6,6,1,5))
        self.assertEqual(r["totals"]["losses"],1)
        rows=[]
        for tid in ("YM-03","YM-04"):
            for step in success_sequence(tid):rows.extend(step["outcome"]["rows"])
        r=a.sales_snapshot(snapshot(rows,proof("yandex_market","test-store")),from_="2026-10-01",to="2026-10-30",as_of=ASOF)
        self.assertTrue(r["complete"],r["problems"])
        self.assertEqual((r["totals"]["ordered"],r["totals"]["delivered"],r["totals"]["physical_returns"],r["totals"]["nonbuyout"],r["totals"]["net"]),(5,4,1,1,3))

    def test_empty_return_history_is_not_a_zero_without_complete_proof(self):
        row=order(units=100,losses=None,physical_return_qty=None,physical_returns_known=False,nonbuyout_qty=None)
        covered=a.sales_snapshot(snapshot([row]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual((covered["totals"]["physical_returns"],covered["totals"]["net"]),(0,100))
        cov=proof();cov.pop()
        partial=a.sales_snapshot(snapshot([row],cov),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertIsNone(partial["totals"]["physical_returns"])
        self.assertIsNone(partial["totals"]["net"])

    def _yandex_return_report(self,statuses,events,extra_items=()):
        from platform_core import market_quantity_providers as provider
        from tests.fixtures import market_quantity_cases as cases
        context=cases.context_for("YM-03")
        original=cases.yandex_order(context)
        original["items"][0]["itemStatuses"]=[{"status":status,"count":count} for status,count in statuses]
        original["items"].extend(deepcopy(extra_items))
        rows=[]
        for tid,payload in (("YM-03",{"orders":[original]}),("YM-04",{"result":{"returns":events}})):
            rows.extend(provider.consume(tid,{},context,{"status_code":200,"headers":{},"payload":payload})["rows"])
        snap=snapshot(rows,proof("yandex_market","test-store"))
        return a.sales_snapshot(snap,from_="2026-10-01",to="2026-10-30",as_of=ASOF),a._rows(snap,ASOF)[0]

    def test_yandex_fast_refund_does_not_change_material_sales_or_maturity(self):
        from tests.fixtures import market_quantity_cases as cases
        event=cases.yandex_return(cases.context_for("YM-04"),fastReturn=True,shipmentStatus="CREATED",refundStatus="STARTED")
        result,rows=self._yandex_return_report([("DELIVERED_TO_BUYER",5)],[event])
        self.assertTrue(result["complete"],result["problems"])
        self.assertEqual(tuple(result["totals"][x] for x in ("ordered","delivered","physical_returns","losses","net","estimated_net")),(5,5,0,0,5,5))
        self.assertTrue(rows[0]["terminal"])
        self.assertTrue(rows[0]["_mature"])

    def test_yandex_fast_refund_preserves_normal_return_for_same_or_other_sku(self):
        from tests.fixtures import market_quantity_cases as cases
        context=cases.context_for("YM-04")
        normal=cases.yandex_return(context)
        for same_sku in (True,False):
            with self.subTest(same_sku=same_sku):
                extra=[] if same_sku else [{"id":2,"offerId":"item-b","offerName":"Изделие B","count":3,
                    "itemStatuses":[{"status":"DELIVERED_TO_BUYER","count":3}]}]
                fast=cases.yandex_return(context,id=8002,fastReturn=True,shipmentStatus="CREATED",refundStatus="STARTED",
                    items=[{"shopSku":"item-a" if same_sku else "item-b","count":1,"instances":[]}])
                result,rows=self._yandex_return_report([("DELIVERED_TO_BUYER",4),("RETURNED",1)],[normal,fast],extra)
                self.assertTrue(result["complete"],result["problems"])
                n=5 if same_sku else 8
                self.assertEqual(tuple(result["totals"][x] for x in ("ordered","delivered","physical_returns","losses","net")),(n,n,1,1,n-1))
                self.assertTrue(all(r["_mature"] for r in rows))

    def test_yandex_ambiguous_returned_with_fast_refund_does_not_invent_unit_split(self):
        from tests.fixtures import market_quantity_cases as cases
        event=cases.yandex_return(cases.context_for("YM-04"),fastReturn=True)
        result,rows=self._yandex_return_report([("DELIVERED_TO_BUYER",4),("RETURNED",1)],[event])
        self.assertFalse(result["complete"])
        self.assertFalse(result["forecast_complete"])
        self.assertEqual(result["totals"]["ordered"],5)
        self.assertEqual(result["totals"]["delivered"],5)
        for field in ("physical_returns","losses","net","estimated_net"):
            self.assertIsNone(result["totals"][field],field)
        self.assertFalse(rows[0]["_mature"])
        self.assertTrue(any("fastReturn" in p["reason"] for p in result["problems"]))

    def test_yandex_unconfirmed_ordinary_return_remains_partial(self):
        from tests.fixtures import market_quantity_cases as cases
        event=cases.yandex_return(cases.context_for("YM-04"),shipmentStatus="CREATED",refundStatus="STARTED")
        result,rows=self._yandex_return_report([("DELIVERED_TO_BUYER",5)],[event])
        self.assertFalse(result["complete"])
        self.assertFalse(result["forecast_complete"])
        self.assertIsNone(result["totals"]["physical_returns"])
        self.assertFalse(rows[0]["_mature"])

    def test_missing_store_and_exact_fragmented_return_coverage(self):
        s=snapshot([order()]);s["stores"]=[{"provider":"ozon","store_id":"store-a"},{"provider":"wb","store_id":"store-empty"}]
        r=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertFalse(r["complete"])
        self.assertEqual(len(r["coverage"]),2)
        cov=proof();first_return=cov.pop()
        mid=ASOF-timedelta(days=30)
        cov.extend([{**first_return,"to":mid.isoformat(),"observed_through":mid.isoformat()},
                    {**first_return,"from":(mid+timedelta(days=1)).isoformat()}])
        rate=a.loss_rates_snapshot(snapshot([order()],cov),as_of=ASOF)["rows"][0]
        self.assertEqual(rate["value"],"0.1")
        # An old interval observed today still does not cover the missing days.
        cov[-1]["from"]=(mid+timedelta(days=2)).isoformat()
        rate=a.loss_rates_snapshot(snapshot([order()],cov),as_of=ASOF)["rows"][0]
        self.assertIsNone(rate["value"])

    def test_utc_timestamps_use_the_declared_moscow_calendar_axis(self):
        row=order(ordered_at="2026-09-30T21:30:00Z")
        s=snapshot([row])
        september=a.sales_snapshot(s,from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        october=a.sales_snapshot(s,from_="2026-10-01",to="2026-10-31",as_of=ASOF,group_by="day")
        self.assertEqual(september["totals"]["ordered"],0)
        self.assertEqual(october["totals"]["ordered"],1000)
        self.assertEqual(october["rows"][0]["day"],"2026-10-01")

    def test_physical_loss_union_does_not_make_nonbuyout_a_customer_return(self):
        row=order(units=100,losses=0,physical_return_qty=None,physical_returns_known=False)
        event={"provider":"ozon","store_id":"store-a","sku":"100","quantity_basis":"return_event","natural_key":"nonbuyout:1",
               "posting_number":"old","order_id":"different-order-reference","scheme":"FBO","event_date":"2026-11-27", "loss_event_qty":2,
               "physical_return_qty":None,"physical_returns_known":False,"nonbuyout_qty":2,
               "unit_ids":["1","2"],"return_type":"FullReturn","terminal":False,"complete":True,"observed_at":ASOF.isoformat()}
        r=a.sales_snapshot(snapshot([row,event]),from_="2026-09-01",to="2026-09-30",as_of=ASOF)
        self.assertEqual(r["totals"]["losses"],2)
        self.assertIsNone(r["totals"]["physical_returns"])
        self.assertFalse(r["rows"][0]["mature"])


if __name__=="__main__":unittest.main()
