"""Quality policy is one source of truth for planning, costs and agent edits."""
import unittest
from decimal import Decimal
from tests.test_podmasterye_accounting import Accounting
from tests.test_podmasterye_seasonal import Seasonal
from platform_core import podmasterye_quality as q

class Quality(unittest.TestCase):
    setUp=Accounting.setUp
    actor=Accounting.actor
    call=Accounting.call
    prepare=Accounting.prepare
    commit=Accounting.commit
    op=Accounting.op
    report=Accounting.report
    recipe=Accounting.recipe
    request=Seasonal.request
    plan=Seasonal.plan
    setup_market=Seasonal.setup_market
    snapshot=Seasonal.snapshot

    def test_distinct_coefficients_and_validation(self):
        self.assertEqual(q.replacement_demand(100,20,Decimal(".25")),Decimal(85))
        self.assertEqual(q.material_input(90,Decimal(".10")),Decimal(100))
        self.assertEqual(q.replacement_demand(100,20,Decimal(0)),Decimal(80))
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":None,"production_scrap_percent":None})
        for field,value in [("return_defect_percent","100.01"),("return_defect_percent","-1"),("production_scrap_percent","100"),("production_scrap_percent","2.001"),("production_scrap_percent",True)]:
            self.prepare("quality_policy",{field:value},expect=400)
        self.op("quality_policy",return_defect_percent="100",production_scrap_percent="0")
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":"100.00","production_scrap_percent":"0.00"})
        self.assertEqual(self.report(self.other)["quality_policy"],{"return_defect_percent":None,"production_scrap_percent":None})
        self.op("quality_policy",return_defect_percent=None,production_scrap_percent=None)
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":None,"production_scrap_percent":None})

    def test_market_forecast_costs_and_no_actual_movements(self):
        ids=self.recipe(pack=100,usage=9,price="100");p=ids["product_id"];m=ids["material_id"]
        self.op("opening",material=m,quantity=100,total="100",day=self.day)
        cid,source=self.setup_market()
        self.snapshot(cid,"2025-05",100,20)
        self.request("map",{"source":source,"sku":"SKU-A","product":p})
        args=dict(source=source,history_from="2025-05",history_to="2025-05",target_from="2027-05")
        before=self.report();d=self.plan(**args)
        self.assertEqual(d["months"][0]["products"][0]["forecastSales"],80)
        self.assertEqual(d["totals"][0]["need"],720)
        self.op("quality_policy",return_defect_percent="25",production_scrap_percent="10")
        d=self.plan(**args);prod=d["months"][0]["products"][0];mat=d["totals"][0]
        self.assertEqual((prod["forecastSales"],prod["returnDefectReplacements"],prod["replacementDemand"],prod["produce"]),(80,5,85,85))
        self.assertEqual((mat["nominalNeed"],mat["productionScrap"],mat["need"],mat["buyPacks"]),(765,85,850,8))
        self.assertEqual(d["qualityPolicy"],{"return_defect_percent":"25.00","production_scrap_percent":"10.00"})
        actual=self.report()
        self.assertEqual(actual["products"][0]["estimated_material_cost_rub"],"9.00")
        self.assertEqual(actual["products"][0]["planned_material_cost_with_scrap_rub"],"10.00")
        self.assertEqual(actual["materials"],before["materials"])
        self.assertEqual(actual["summary"],before["summary"])
        self.assertEqual(actual["event_count"],before["event_count"])
        self.assertEqual(self.plan(**args,metric="delivered")["totals"][0]["need"],1000)
        self.assertEqual(self.plan(**args,metric="delivered")["months"][0]["products"][0]["returnDefectReplacements"],0)
        self.op("quality_policy",return_defect_percent="0",production_scrap_percent="10")
        self.assertEqual(self.plan(**args)["totals"][0]["need"],800)

    def test_partial_policy_update_reset_and_retry(self):
        self.op("quality_policy",return_defect_percent="25",production_scrap_percent="10")
        draft=self.prepare("quality_policy",{"return_defect_percent":"30"})
        self.assertEqual(draft["arguments"],{"return_defect_percent":"30.00"})
        first=self.commit(draft,rid="partial-quality-update")
        self.assertEqual(self.commit(draft,rid="partial-quality-update"),first)
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":"30.00","production_scrap_percent":"10.00"})
        self.op("quality_policy",return_defect_percent=None)
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":None,"production_scrap_percent":"10.00"})
        self.op("quality_policy",production_scrap_percent="99.99")
        self.assertEqual(self.report()["quality_policy"],{"return_defect_percent":None,"production_scrap_percent":"99.99"})
        self.prepare("quality_policy",{},expect=400)

    def test_quality_export_values_and_other_workshop_isolation(self):
        import csv,io,zipfile
        from openpyxl import load_workbook
        self.op("quality_policy",return_defect_percent="25.25",production_scrap_percent="10.5")
        x=self.client.get("/api/accounting/export/xlsx",headers=self.h)
        self.assertEqual(x.status_code,200)
        sheet=load_workbook(io.BytesIO(x.content))["Коэффициенты брака"]
        self.assertEqual([sheet.cell(2,i).value for i in (1,2)],[25.25,10.5])
        z=self.client.get("/api/accounting/export/csv-zip",headers=self.h)
        self.assertEqual(z.status_code,200)
        with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
            rows=list(csv.reader(io.StringIO(archive.read("Коэффициенты брака.csv").decode("utf-8-sig")),delimiter=";"))
            self.assertEqual(rows,[["return_defect_percent","production_scrap_percent"],["25.25","10.50"]])
        self.op("quality_policy",return_defect_percent=None)
        x=self.client.get("/api/accounting/export/xlsx",headers=self.h)
        sheet=load_workbook(io.BytesIO(x.content))["Коэффициенты брака"]
        self.assertEqual([sheet.cell(2,i).value for i in (1,2)],[None,10.5])
        x=self.client.get("/api/accounting/export/xlsx",headers=self.other)
        sheet=load_workbook(io.BytesIO(x.content))["Коэффициенты брака"]
        self.assertEqual([sheet.cell(2,i).value for i in (1,2)],[None,None])

    def test_ledger_facts_unchanged_and_policy_revision(self):
        ids=self.recipe(pack=100,usage=9,price="100");m=ids["material_id"];p=ids["product_id"]
        self.op("opening",material=m,quantity=1000,total="1000",day=self.day)
        sale=self.op("sale",product=p,quantity=100,unit_price="10",paid_amount="1000",auto_produce=True,day=self.day)
        self.op("return",sale=sale["id"],quantity=20,refund="200",restock=False,day=self.day)
        before=self.report(horizon=30,lead=0,safety=0)
        draft=self.prepare("quality_policy",{"return_defect_percent":"25","production_scrap_percent":"10"})
        other=self.prepare("quality_policy",{"return_defect_percent":"20","production_scrap_percent":None})
        self.commit(draft)
        self.commit(other,expect=409)
        d=self.report(horizon=30,lead=0,safety=0)
        self.assertEqual(d["summary"],before["summary"])
        self.assertEqual(d["consumption"],before["consumption"])
        self.assertEqual(d["actual_consumption"],before["actual_consumption"])
        self.assertEqual(d["materials"],before["materials"])
        self.assertEqual(Decimal(d["planning"][0]["daily_forecast"]),Decimal("28.333"))
        self.assertEqual(Decimal(d["planning"][0]["nominal_production_need"]),Decimal(765))
        self.assertEqual(Decimal(d["planning"][0]["production_scrap_need"]),Decimal(85))
        self.assertEqual(d["planning"][0]["buy_packs"],8)
        # Planned coefficient must not fabricate a physical defect or extra stock use.
        self.assertEqual(d["actual_consumption"][0]["production_quantity"],900)
        self.assertEqual(d["materials"][0]["quantity"],100)
