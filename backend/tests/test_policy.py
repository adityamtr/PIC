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