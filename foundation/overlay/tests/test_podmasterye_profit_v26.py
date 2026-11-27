"""Authoritative unit-profit arithmetic, schema, matrix and public scope checks."""
from decimal import Decimal
from tests import test_podmasterye_public_v22 as base
from platform_core import guest_selector

class ProfitV26(base.PublicV22):
    example={"mode":"units","units":"100","unit_price":"500","unit_cost":"180","commission_percent":"10",
             "delivery_unit":"40","packing_unit":"10","other_unit":"0","advertising":"2000","fixed_expenses":"3000","taxes":"0"}
    def calc(self,**changes):
        r=self.c.post("/api/calculator/profit",json={**self.example,**changes})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_unit_example_and_break_even(self):
        d=self.calc()
        expected={"revenue_rub":"50000.00","cost_rub":"18000.00","commission_rub":"5000.00","delivery_rub":"4000.00",
                  "packing_rub":"1000.00","gross_profit_rub":"32000.00","contribution_rub":"22000.00",
                  "fixed_total_rub":"5000.00","total_cost_rub":"33000.00","profit_rub":"17000.00","unit_profit_rub":"170.00",
                  "margin_percent":"34.00","return_on_cost_percent":"51.52","break_even_units":"23","break_even_price_rub":"311.12"}
        for k,v in expected.items():self.assertEqual(d[k],v,k)
        self.assertLess(Decimal(self.calc(units="22")["profit_rub"]),0)
        self.assertGreaterEqual(Decimal(self.calc(units="23")["profit_rub"]),0)
        self.assertLess(Decimal(self.calc(unit_price="311.11")["profit_rub"]),0)
        self.assertGreaterEqual(Decimal(self.calc(unit_price="311.12")["profit_rub"]),0)
        d=self.calc(other_unit="5",taxes="1000")
        self.assertEqual(d["profit_rub"],"15500.00");self.assertEqual(d["total_cost_rub"],"34500.00")
    def test_loss_zero_and_boundary_commission(self):
        d=self.calc(units="0")
        self.assertEqual(d["profit_rub"],"-5000.00")
        self.assertIsNone(d["unit_profit_rub"]);self.assertIsNone(d["margin_percent"]);self.assertIsNone(d["break_even_price_rub"])
        d=self.calc(commission_percent="100")
        self.assertEqual(d["commission_rub"],"50000.00");self.assertEqual(d["profit_rub"],"-28000.00")
        self.assertIsNone(d["break_even_units"]);self.assertIsNone(d["break_even_price_rub"])
        d=self.calc(unit_price="100")
        self.assertLess(Decimal(d["profit_rub"]),0);self.assertIsNone(d["break_even_units"])
        d=self.calc(units="1",unit_price="0.01",unit_cost="0",commission_percent="50",delivery_unit="0",packing_unit="0",advertising="0",fixed_expenses="0")
        self.assertEqual(d["commission_rub"],"0.01");self.assertEqual(d["profit_rub"],"0.00")
        d=self.calc(unit_price="0",unit_cost="0",units="0",delivery_unit="0",packing_unit="0",advertising="0",fixed_expenses="0")
        self.assertIsNone(d["return_on_cost_percent"]);self.assertIsNone(d["margin_percent"])
    def test_invalid_and_precision(self):
        for key,value in [("units","1.5"),("units","1000000001"),("units","-1"),("units",True),("commission_percent","100.01"),("commission_percent","-1"),("unit_price","1.001"),("delivery_unit","-2"),("taxes",""),("mode","period"),("unit_cost",[])]:
            with self.subTest(key=key,value=value):
                self.assertEqual(self.c.post("/api/calculator/profit",json={**self.example,key:value}).status_code,400)
        self.assertEqual(self.c.post("/api/calculator/profit",json={**self.example,"revenue":"10"}).status_code,400)
        a={**self.example};del a["unit_cost"];self.assertEqual(self.c.post("/api/calculator/profit",json=a).status_code,400)
        d=self.calc(units="1000000000",unit_price="999999999999.99",unit_cost="0",commission_percent="0",delivery_unit="0",packing_unit="0",advertising="0",fixed_expenses="0")
        self.assertEqual(d["profit_rub"],"999999999999990000000.00")
    def test_new_matrix_zero_provider_and_strict_actions(self):
        h={"Origin":"https://master.example","Accept":"application/json"}
        self.c.post("/guest/session",headers=h)
        token=self.c.cookies.get("__Host-podmaster_guest");chat=self.identity.guest_chat(token)
        initial=guest_selector.totals(self.identity._db)[-1][1]
        def deny(*args):raise AssertionError("paid classifier forbidden")
        for i,(msg,field,value) in enumerate([("Количество продаж: 100","units","100"),("Цена за штуку: 500","unit_price","500.00"),("Себестоимость единицы: 180","unit_cost","180.00"),("Комиссия: 10%","commission_percent","10"),("Доставка за штуку: 40","delivery_unit","40.00"),("Налоги: 1000","taxes","1000.00"),("Комиссия: 120%",None,None),("Количество продаж: 1.5",None,None)]):
            self.identity.guest_turn(token,chat,"profit-"+str(i),msg,select=deny)
            row=self.c.get("/guest/chats/"+chat+"/events").json()["turns"][-1]
            a=row.get("calculatorAction")
            if field:self.assertEqual((a["mode"],a["field"],a["value"]),("units",field,value))
            else:self.assertIsNone(a)
        self.assertEqual(guest_selector.totals(self.identity._db)[-1][1],initial)
    def test_ssr_profit_modes_and_seo(self):
        r=self.c.get("/kalkulyator-pribyli/")
        self.assertEqual(r.status_code,200);self.assertIn("Калькулятор прибыли",r.text)
        for text in ("По изделиям","По выручке","Расходы на продажу","Расходы за период","Взять себестоимость из калькулятора","Как рассчитать прибыль от продаж","name=\"taxes\""):
            self.assertIn(text,r.text)
        self.assertIn("noindex",r.headers["X-Robots-Tag"])
