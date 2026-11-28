"""Whole-window selection with actual provider-shaped synthetic snapshots."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import unittest

from platform_core import podmasterye_market_analytics as a
from platform_core import market_quantity_providers as provider
from tests.fixtures import market_quantity_cases as cases


def window(start,end,products=((101,12,3),),*,observed=None):
    stamp=a._instant(observed).timestamp() if observed is not None else cases.NOW
    # Old complete windows were obtained while still inside the API's rolling
    # availability bound, then retained locally. Do not fabricate a fresh
    # observation or bypass the real adapter's history validation.
    if a._day(start)<a._instant(stamp).date()-timedelta(days=365):
        stamp=datetime.combine(a._day(end)+timedelta(days=1),datetime.min.time(),timezone.utc).timestamp()
    context=cases.context_for("WB-03",**{"from":start,"to":end,"now":stamp})
    batch=[cases.wb_funnel(context,n=sku,ordered=n,lost=lost,buyout=n-lost) for sku,n,lost in products]
    out=provider.consume("WB-03",{},context,{"status_code":200,"headers":{},"payload":{"data":{"products":batch}}})
    rows=out["rows"]
    for row in rows:row["product_id"]="product-"+row["sku"]
    proof={**out["coverage"],"provider":"wb","store_id":"test-store","source_id":"WB-03","role":"orders",
        "quantity_basis":"funnel_interval","state":out["state"]}
    if observed is not None:
        proof["observed_at"]=observed
        for row in rows:row["observed_at"]=observed
    return {"rows":rows,"coverage":[proof],"stores":[]}


def combine(*snapshots):
    return {"rows":[r for s in snapshots for r in s["rows"]],"coverage":[p for s in snapshots for p in s["coverage"]],"stores":[]}


def report(snapshot,start="2026-10-29",end="2026-11-27",**kw):
    return a.sales_snapshot(snapshot,from_=start,to=end,as_of=kw.pop("as_of","2026-11-28T13:00:00+03:00"),**kw)


class IntervalSelection(unittest.TestCase):
    def test_exact_source_window_wins_and_absent_sku_does_not_reappear(self):
        exact=window("2026-10-29","2026-11-27")
        other=window("2026-10-24","2026-11-22",((101,100,20),(202,200,40)))
        result=report(combine(exact,other))
        self.assertTrue(result["complete"],result["problems"])
        self.assertEqual((result["totals"]["ordered"],result["totals"]["net"]),(12,9))
        self.assertEqual(result["total"],1)
        self.assertEqual(result["rows"][0]["skus"],["101"])
        self.assertIsNone(result["totals"]["physical_returns"])
        self.assertIsNone(result["totals"]["estimated_physical_returns"])
        self.assertTrue(any("Физическая приёмка" in message for message in result["warnings"]))
        self.assertTrue(result["coverage"][0]["interval_selection"]["exact"])

    def test_confirmed_empty_exact_window_does_not_resurrect_cached_skus(self):
        exact=window("2026-10-29","2026-11-27",())
        other=window("2026-10-24","2026-11-22",((202,100,20),))
        result=report(combine(exact,other))
        self.assertTrue(result["complete"])
        self.assertEqual(result["status"],"no_data_confirmed")
        self.assertEqual(result["rows"],[])
        self.assertEqual(result["totals"]["ordered"],0)
        broken=deepcopy(exact);broken["coverage"][0].update(complete=False,state="partial",zero_confirmed=False)
        missing=report(combine(broken,other))
        self.assertFalse(missing["complete"])
        self.assertIsNone(missing["totals"]["ordered"])

    def test_nested_exact_window_uses_its_own_quantity(self):
        inner=window("2026-11-01","2026-11-05")
        outer=window("2026-10-29","2026-11-27",((101,100,20),))
        result=report(combine(inner,outer),"2026-11-01","2026-11-05")
        self.assertTrue(result["complete"])
        self.assertEqual(result["totals"]["ordered"],12)

    def test_nonoverlapping_full_partition_is_selected_globally(self):
        left=window("2026-10-29","2026-11-12")
        right=window("2026-11-13","2026-11-27",((101,18,3),))
        crossing=window("2026-11-03","2026-11-21",((101,100,20),(202,200,40)))
        result=report(combine(left,right,crossing))
        self.assertTrue(result["complete"],result["problems"])
        self.assertEqual((result["totals"]["ordered"],result["totals"]["net"]),(30,24))
        self.assertEqual(result["total"],1)
        self.assertEqual(len(result["coverage"][0]["interval_selection"]["windows"]),2)

    def test_gap_or_clipped_boundary_remains_unknown(self):
        left=window("2026-10-29","2026-11-12")
        right=window("2026-11-14","2026-11-27")
        outside=window("2026-10-24","2026-11-22")
        result=report(combine(left,right,outside))
        self.assertFalse(result["complete"])
        self.assertIsNone(result["totals"]["ordered"])
        self.assertIsNone(result["totals"]["physical_returns"])
        self.assertTrue(any("нельзя обрезать" in p["reason"] for p in result["problems"]))

    def test_exact_fresh_report_wins_over_fresh_pieces(self):
        exact=window("2026-10-29","2026-11-27",observed="2026-11-28T10:00:00+03:00")
        left=window("2026-10-29","2026-11-12",((101,100,20),))
        right=window("2026-11-13","2026-11-27",((101,100,20),))
        result=report(combine(exact,left,right))
        self.assertTrue(result["complete"])
        self.assertEqual(result["totals"]["ordered"],12)

    def test_stale_exact_uses_only_a_whole_fresh_partition(self):
        stale=window("2026-10-29","2026-11-27",observed="2026-11-27T12:00:00+03:00")
        left=window("2026-10-29","2026-11-12",((101,100,20),))
        right=window("2026-11-13","2026-11-27",((101,100,20),))
        fresh=report(combine(stale,left,right))
        self.assertTrue(fresh["complete"])
        self.assertEqual(fresh["totals"]["ordered"],200)
        partial=report(combine(stale,left))
        self.assertFalse(partial["complete"])
        self.assertTrue(partial["stale"])
        self.assertEqual(partial["totals"]["ordered"],12)

    def test_missing_projection_is_not_confirmed_zero_from_surviving_coverage(self):
        broken=window("2026-10-29","2026-11-27")
        broken["rows"]=[]
        result=report(broken)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["totals"]["ordered"])
        self.assertEqual(result["coverage"][0]["interval_selection"]["missing_projections"],1)

    def test_mature_coefficient_uses_same_whole_window_selector(self):
        asof=a._day("2026-11-28");start,end=a._training_period(asof)
        split=start+timedelta(days=30)
        archived=window(str(start),str(split),((101,100,20),))
        current=window(str(split+timedelta(days=1)),str(end),((101,900,180),))
        overlapping=window(str(start+timedelta(days=40)),str(end),((101,10000,5000),(202,10000,1000)))
        rate=a.loss_rates_snapshot(combine(archived,current,overlapping),as_of=asof)["rows"]
        target=next(r for r in rate if r["sku"]=="101")
        self.assertEqual((target["value"],target["numerator"],target["denominator"]),("0.2",200,1000))
        self.assertFalse(target["overlapping_intervals"])
        self.assertIsNone(target["physical_return_rate"])
        left=window(str(split+timedelta(days=1)),str(end-timedelta(days=10)),((101,900,180),))
        unsupported=a.loss_rates_snapshot(combine(archived,left,overlapping),as_of=asof)["rows"][0]
        self.assertIsNone(unsupported["value"])
        self.assertTrue(unsupported["overlapping_intervals"])

    def test_month_grouping_uses_complete_month_windows_not_a_cross_month_total(self):
        observed="2027-03-01T13:00:00+03:00"
        october=window("2026-10-01","2026-10-31",observed=observed)
        november=window("2026-11-01","2026-11-30",((101,18,3),),observed=observed)
        combined=window("2026-10-01","2026-11-30",((101,100,20),),observed=observed)
        result=report(combine(october,november,combined),"2026-10-01","2026-11-30",group_by="month",as_of=observed)
        self.assertTrue(result["complete"])
        self.assertEqual([(r["month"],r["ordered"]) for r in result["rows"]],[("2026-10",12),("2026-11",18)])


if __name__=="__main__":unittest.main()
