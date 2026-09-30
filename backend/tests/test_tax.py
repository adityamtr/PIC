import unittest
from datetime import date

from app import data, optimizer, policy, tax_lots, tax_rules


class TaxRulesTests(unittest.TestCase):
    def test_classify_term_boundary(self):
        as_of = date(2026, 9, 30)
        # Exactly 12 months back -> LTCG.
        self.assertEqual(tax_rules.classify_term(date(2025, 9, 30), as_of), "LTCG")
        # 11 months back -> still STCG.
        self.assertEqual(tax_rules.classify_term(date(2025, 10, 1), as_of), "STCG")

    def test_ltcg_date_is_twelve_months_after_acquisition(self):
        d = tax_rules.ltcg_date(date(2025, 3, 15))
        self.assertEqual(d, date(2026, 3, 15))

    def test_loss_lot_produces_negative_tax(self):
        lot = {"lot_id": "L1", "acquisition_date": date(2026, 1, 1).isoformat(),
               "cost_price": 200.0, "quantity": 100}
        result = tax_rules.compute_lot_tax(lot, sell_price=150.0, sell_shares=100,
                                           as_of=date(2026, 9, 30))
        self.assertLess(result["gain"], 0)
        self.assertLess(result["cgt"], 0)
        self.assertGreater(result["stt"], 0)  # STT/txn costs still apply to a loss sale

    def test_stcg_rate_applied_below_twelve_months(self):
        lot = {"lot_id": "L1", "acquisition_date": date(2026, 6, 1).isoformat(),
               "cost_price": 100.0, "quantity": 10}
        result = tax_rules.compute_lot_tax(lot, sell_price=150.0, sell_shares=10,
                                           as_of=date(2026, 9, 30))
        self.assertEqual(result["term"], "STCG")
        self.assertAlmostEqual(result["cgt"], 500.0 * tax_rules.STCG_RATE, places=2)

    def test_ltcg_rate_applied_at_or_above_twelve_months(self):
        lot = {"lot_id": "L1", "acquisition_date": date(2024, 1, 1).isoformat(),
               "cost_price": 100.0, "quantity": 10}
        result = tax_rules.compute_lot_tax(lot, sell_price=150.0, sell_shares=10,
                                           as_of=date(2026, 9, 30))
        self.assertEqual(result["term"], "LTCG")
        self.assertAlmostEqual(result["cgt"], 500.0 * tax_rules.LTCG_RATE, places=2)

    def test_attribute_sale_consumes_least_tax_lot_first(self):
        as_of = date(2026, 9, 30)
        lots = [
            {"lot_id": "GAIN-STCG", "acquisition_date": date(2026, 6, 1).isoformat(),
             "cost_price": 50.0, "quantity": 100},
            {"lot_id": "LOSS-LTCG", "acquisition_date": date(2024, 1, 1).isoformat(),
             "cost_price": 300.0, "quantity": 100},
        ]
        result = tax_rules.attribute_sale(lots, sell_price=100.0, sell_shares=100, as_of=as_of)
        # Selling 100 shares should draw entirely from the loss lot (negative
        # tax per rupee), leaving the high-tax gain lot untouched.
        self.assertEqual(result["lots_consumed"][0]["lot_id"], "LOSS-LTCG")
        self.assertLess(result["total_tax"], 0)


class TaxLotsTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        a = tax_lots.generate_lots("INE-TEST-01", "TEST", 10_000, 100.0, date(2026, 9, 30))
        b = tax_lots.generate_lots("INE-TEST-01", "TEST", 10_000, 100.0, date(2026, 9, 30))
        self.assertEqual(a, b)

    def test_generated_lots_sum_to_shares(self):
        lots = tax_lots.generate_lots("INE-TEST-02", "TEST2", 12_345, 250.0, date(2026, 9, 30))
        self.assertEqual(sum(l["quantity"] for l in lots), 12_345)

    def test_generation_produces_mix_of_terms(self):
        # Across a spread of ISINs, both STCG and LTCG lots should appear.
        seen_terms = set()
        for i in range(30):
            lots = tax_lots.generate_lots(f"INE-SEED-{i:03d}", "T", 5_000, 100.0, date(2026, 9, 30))
            for lot in lots:
                acq = date.fromisoformat(lot["acquisition_date"])
                seen_terms.add(tax_rules.classify_term(acq, date(2026, 9, 30)))
        self.assertEqual(seen_terms, {"STCG", "LTCG"})


class OptimizerTaxAwareTests(unittest.TestCase):
    def setUp(self):
        if not optimizer.available():
            self.skipTest("cvxpy not installed")

    def test_sell_prefers_low_tax_over_equal_return_high_tax(self):
        # Two names with identical expected return; A has a large embedded
        # gain (high tax), B is at a loss (negative tax). The optimizer should
        # raise the cash from B first.
        candidates = [
            {"ticker": "A", "price": 100.0, "sellable_shares": 100_000,
             "expected_return": 0.0, "tax_rate": 0.15, "txn_rate": 0.001},
            {"ticker": "B", "price": 100.0, "sellable_shares": 100_000,
             "expected_return": 0.0, "tax_rate": -0.10, "txn_rate": 0.001},
        ]
        sells, meta = optimizer.optimize_sell(candidates, amount=50 * data.CRORE)
        by_ticker = {s["ticker"]: s["shares"] for s in sells}
        self.assertGreater(by_ticker.get("B", 0), by_ticker.get("A", 0))
        self.assertIn("est_tax_cr", meta)

    def test_persistent_loser_sold_despite_high_tax_over_long_horizon(self):
        # A single sellable name with a bad predicted return and high exit
        # tax: over a long horizon the repeated loss should still dominate a
        # one-time tax cost.
        candidates = [
            {"ticker": "A", "price": 100.0, "sellable_shares": 100_000,
             "expected_return": -0.05, "tax_rate": 0.02, "txn_rate": 0.001},
        ]
        sells, meta = optimizer.optimize_sell(candidates, amount=10 * data.CRORE,
                                              horizon_days=21)
        self.assertTrue(sells)
        self.assertEqual(sells[0]["ticker"], "A")

    def test_rebalance_runs_with_tax_fields_on_holdings(self):
        holdings = [
            {"ticker": "A", "price": 100.0, "market_value": 10 * data.CRORE,
             "sellable_shares": 100_000, "expected_return": 0.02,
             "effective_tax_rate_pct": 15.0, "txn_cost_rate_pct": 0.13},
            {"ticker": "B", "price": 100.0, "market_value": 10 * data.CRORE,
             "sellable_shares": 100_000, "expected_return": -0.02,
             "effective_tax_rate_pct": -5.0, "txn_cost_rate_pct": 0.13},
        ]
        targets, meta = optimizer.optimize_rebalance(holdings, aum=100 * data.CRORE,
                                                      issuer_cap_frac=0.5)
        self.assertEqual(meta["status"], "optimal")
        self.assertIn("est_tax_cr", meta)
        self.assertGreaterEqual(meta["est_tax_cr"], 0.0)


class PolicyTaxChecksTests(unittest.TestCase):
    def make_dataset(self):
        holding = {
            "ticker": "TEST", "name": "Test Security", "sector": "Technology",
            "group": "Test Group", "country": "India", "market_value": 9 * data.CRORE,
            "weight": 9.0, "locked_shares": 0, "sellable_shares": 100,
        }
        return {
            "id": "TEST-FUND", "aum": 100 * data.CRORE, "holdings": [holding],
            "holdings_by_ticker": {"TEST": holding},
            "cash": {"total_cash": 100 * data.CRORE, "reserves": 1 * data.CRORE},
            "pending_trades": [], "corporate_actions": [], "event_calendar": [],
        }

    def test_high_tax_drag_warns(self):
        tax_context = {
            "est_total_tax": 2 * data.CRORE, "sell_value": 20 * data.CRORE,
            "tax_drag_bps": 1000.0, "stcg_share_pct": 10.0, "held_due_to_tax": [],
        }
        result = policy.evaluate(self.make_dataset(), [], {"investable_amount": 100 * data.CRORE},
                                 5, tax_context=tax_context)
        self.assertTrue(any(c["code"] == "TAX-DRAG" and c["status"] == "ESCALATE"
                            for c in result["checks"]))

    def test_stcg_heavy_plan_warns(self):
        tax_context = {
            "est_total_tax": 0.1 * data.CRORE, "sell_value": 20 * data.CRORE,
            "tax_drag_bps": 5.0, "stcg_share_pct": 80.0, "held_due_to_tax": [],
        }
        result = policy.evaluate(self.make_dataset(), [], {"investable_amount": 100 * data.CRORE},
                                 5, tax_context=tax_context)
        self.assertTrue(any(c["code"] == "TAX-STCG-SHARE" and c["status"] == "WARN"
                            for c in result["checks"]))

    def test_held_due_to_tax_flag_surfaces(self):
        tax_context = {
            "est_total_tax": 0.0, "sell_value": 0.0, "tax_drag_bps": 0.0,
            "stcg_share_pct": 0.0,
            "held_due_to_tax": [{"ticker": "TEST", "expected_return_pct": -1.2,
                                 "exit_cost_pct": 15.0, "ltcg_maturity": "2027-01-01"}],
        }
        result = policy.evaluate(self.make_dataset(), [], {"investable_amount": 100 * data.CRORE},
                                 5, tax_context=tax_context)
        self.assertTrue(any(c["code"] == "TAX-HOLD" and c["entity"] == "TEST"
                            for c in result["checks"]))


if __name__ == "__main__":
    unittest.main()
