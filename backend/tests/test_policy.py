import unittest

from app import data
from app import policy


class PolicyTests(unittest.TestCase):
    def make_dataset(self):
        aum = 100 * data.CRORE
        holding = {
            "ticker": "TEST",
            "name": "Test Security",
            "sector": "Technology",
            "group": "Test Group",
            "country": "India",
            "market_value": 9 * data.CRORE,
            "weight": 9.0,
            "locked_shares": 0,
            "sellable_shares": 100,
        }
        return {
            "id": "TEST-FUND",
            "aum": aum,
            "holdings": [holding],
            "holdings_by_ticker": {"TEST": holding},
            "cash": {"total_cash": 100 * data.CRORE, "reserves": 1 * data.CRORE},
            "pending_trades": [],
            "corporate_actions": [],
            "event_calendar": [],
        }

    def cash_flow(self):
        return {"investable_amount": 100 * data.CRORE}

    def test_esg_exclusion_blocks_tobacco_purchase(self):
        result = policy.evaluate(
            self.make_dataset(),
            [{"ticker": "ITC", "side": "BUY", "shares": 1, "est_value": data.CRORE}],
            self.cash_flow(),
            5,
        )

        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["execution_allowed"])
        self.assertTrue(any(check["code"] == "ESG-EXCLUSION"
                            for check in result["checks"]))

    def test_issuer_breach_blocks_and_missing_liquidity_escalates(self):
        result = policy.evaluate(
            self.make_dataset(),
            [{"ticker": "TEST", "side": "BUY", "shares": 1,
              "est_value": 3 * data.CRORE}],
            self.cash_flow(),
            5,
        )

        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(any(check["code"] == "MANDATE-ISSUER"
                            and check["status"] == "BLOCK"
                            for check in result["checks"]))
        self.assertTrue(any(check["code"] == "LIQUIDITY-DATA"
                            and check["status"] == "ESCALATE"
                            for check in result["checks"]))

    def test_home_country_exposure_near_100_percent_does_not_warn(self):
        dataset = self.make_dataset()
        holding = dataset["holdings_by_ticker"]["TEST"]
        holding["market_value"] = 94 * data.CRORE
        holding["weight"] = 94.0

        result = policy.evaluate(dataset, [], self.cash_flow(), 5)

        country_check = next(check for check in result["checks"]
                             if check["code"] == "COUNTRY-LIMIT")
        self.assertEqual(country_check["status"], "PASS")
        self.assertEqual(country_check["projected"], 94.0)

    def test_foreign_country_exposure_near_cap_still_warns(self):
        dataset = self.make_dataset()
        holding = dataset["holdings_by_ticker"]["TEST"]
        holding.update({"country": "United States", "market_value": 33 * data.CRORE,
                        "weight": 33.0})

        result = policy.evaluate(dataset, [], self.cash_flow(), 5)

        country_check = next(check for check in result["checks"]
                             if check["code"] == "COUNTRY-LIMIT")
        self.assertEqual(country_check["status"], "WARN")
    def test_spread_review_band_is_less_sensitive_but_block_is_unchanged(self):
        dataset = self.make_dataset()
        holding = dataset["holdings_by_ticker"]["TEST"]
        holding.update({"adv_cr": 100.0, "median_adv_cr": 100.0,
                        "bid_ask_spread_pct": 0.60})
        order = {"ticker": "TEST", "side": "BUY", "shares": 1,
                 "est_value": data.CRORE / 10}

        def spread_status(spread):
            holding["bid_ask_spread_pct"] = spread
            result = policy.evaluate(dataset, [order], self.cash_flow(), 5)
            return next(check["status"] for check in result["checks"]
                        if check["code"] == "LIQUIDITY-SPREAD")

        self.assertEqual(spread_status(0.60), "PASS")
        self.assertEqual(spread_status(0.80), "WARN")
        self.assertEqual(spread_status(1.01), "BLOCK")

    def test_adv_review_band_is_less_sensitive_but_escalation_is_unchanged(self):
        dataset = self.make_dataset()
        holding = dataset["holdings_by_ticker"]["TEST"]
        holding.update({"adv_cr": 1.0, "median_adv_cr": 1.0,
                        "bid_ask_spread_pct": 0.25})

        def adv_check(value_cr):
            result = policy.evaluate(
                dataset,
                [{"ticker": "TEST", "side": "BUY", "shares": 1,
                  "est_value": value_cr * data.CRORE}],
                self.cash_flow(), 1,
            )
            return next(check for check in result["checks"]
                        if check["code"] == "LIQUIDITY-ADV")

        self.assertEqual(adv_check(0.08)["status"], "PASS")
        self.assertEqual(adv_check(0.12)["status"], "WARN")
        escalated = adv_check(0.76)
        self.assertEqual(escalated["status"], "ESCALATE")
        risk_flag = next(flag for flag in policy.evaluate(
            dataset,
            [{"ticker": "TEST", "side": "BUY", "shares": 1,
              "est_value": 0.76 * data.CRORE}],
            self.cash_flow(), 1,
        )["risk_flags"] if flag["code"] == "LIQUIDITY-ADV")
        self.assertEqual(risk_flag["status"], "ESCALATE")

    def test_rebalance_rounding_tolerance_does_not_relax_contribution_cash_limit(self):
        orders = [
            {"ticker": "TEST", "side": "BUY", "shares": 1,
             "est_value": 1.0108 * data.CRORE},
            {"ticker": "TEST", "side": "SELL", "shares": 1,
             "est_value": 1.0 * data.CRORE},
        ]

        rebalance = policy.evaluate(
            self.make_dataset(), orders, {"investable_amount": 0.0}, 5,
            action="rebalance",
        )
        contribution = policy.evaluate(
            self.make_dataset(), orders, {"investable_amount": 0.0}, 5,
            action="contribution",
        )

        rebalance_cash = next(check for check in rebalance["checks"]
                              if check["code"] == "CASH-DEPLOYMENT")
        contribution_cash = next(check for check in contribution["checks"]
                                 if check["code"] == "CASH-DEPLOYMENT")
        self.assertEqual(rebalance_cash["status"], "PASS")
        self.assertEqual(rebalance_cash["limit"], 0.02)
        self.assertEqual(contribution_cash["status"], "BLOCK")

    def test_buy_screen_uses_block_thresholds_not_warning_bands(self):
        dataset = self.make_dataset()
        holding = dataset["holdings_by_ticker"]["TEST"]
        holding.update({
            "adv_cr": 100.0,
            "bid_ask_spread_pct": 0.75,
            "fx_exposure_pct": 12.0,
            "price_stale": False,
        })

        self.assertIsNone(policy.buy_exclusion_reason(dataset, "TEST"))

        holding["bid_ask_spread_pct"] = 1.01
        self.assertIsNotNone(policy.buy_exclusion_reason(dataset, "TEST"))
        holding["bid_ask_spread_pct"] = 0.75
        holding["fx_exposure_pct"] = 15.01
        self.assertIsNotNone(policy.buy_exclusion_reason(dataset, "TEST"))


if __name__ == "__main__":
    unittest.main()