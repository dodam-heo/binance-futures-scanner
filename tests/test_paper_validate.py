import unittest
from paper_validate import simulate

BASE={"direction":"LONG","entry":100,"take_profit":105,"stop_loss":98,
      "created_ms":1000,"expires_ms":20000000,"cost_notional_pct":0.2}
def bar(t,h,l):return [t,100,h,l,100]

class PaperValidatorTests(unittest.TestCase):
    def test_entry_then_tp_next_bar(self):
        r=simulate(BASE,[bar(1000,101,99),bar(3601000,106,99)])
        self.assertEqual(r["status"],"TP")
        self.assertAlmostEqual(r["net_margin_pct"],14.4)
    def test_same_bar_tp_not_assumed(self):
        r=simulate(BASE,[bar(1000,106,99)])
        self.assertEqual(r["status"],"OPEN")
    def test_same_bar_stop_is_conservative(self):
        r=simulate(BASE,[bar(1000,106,97)])
        self.assertEqual(r["status"],"STOP")
    def test_both_tp_stop_later_bar_stop_first(self):
        r=simulate(BASE,[bar(1000,101,99),bar(3601000,106,97)])
        self.assertEqual(r["status"],"STOP")
    def test_no_entry(self):
        r=simulate(BASE,[bar(1000,110,106)])
        self.assertEqual(r["status"],"UNFILLED")
    def test_short(self):
        x=dict(BASE,direction="SHORT",take_profit=95,stop_loss=102)
        r=simulate(x,[bar(1000,101,99),bar(3601000,101,94)])
        self.assertEqual(r["status"],"TP")
    def test_invalid_geometry(self):
        with self.assertRaises(ValueError):
            simulate(dict(BASE,stop_loss=101),[])
if __name__=="__main__":unittest.main()
