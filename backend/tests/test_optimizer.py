import unittest

from app import optimizer
from app.data import CRORE


@unittest.skipUnless(optimizer.available(), "cvxpy is not installed")
class OptimizerTests(unittest.TestCase):
    def test_buy_respects_group_limit(self):
        candidates = [
            {"ticker": "A", "price": 10, "current_value": 0,
             "expected_return": 0.20, "sector": "S1"},
            {"ticker": "B", "price": 10, "current_value": 0,
             "expected_return": 0.15, "sector": "S2"},
            {"ticker": "C", "price": 10, "current_value": 0,
             "expected_return": 0.05, "sector": "S3"},
        ]
        exposure_context = {
            "entities": {
                "A": {"sector": "S1", "group": "G", "country": "IN"},
                "B": {"sector": "S2", "group": "G", "country": "IN"},
                "C": {"sector": "S3", "group": "H", "country": "IN"},
            },
            "current_values_crore": {},
            "aum_crore": 100.0,
        }

        allocations, metadata = optimizer.optimize_buy(
            candidates,
            amount=20 * CRORE,
            aum=100 * CRORE,
            issuer_cap_frac=0.5,
            max_name_frac=1.0,
            exposure_context=exposure_context,
            group_cap_frac=0.10,
            country_cap_by_name={"IN": 1.0},
        )

        group_g_total = sum(
            allocation["rupees"] for allocation in allocations
            if allocation["ticker"] in {"A", "B"}
        )
        self.assertEqual(metadata["status"], "optimal")
        self.assertLessEqual(group_g_total, 10 * CRORE + 1_000)
        candidate_prices = {candidate["ticker"]: candidate["price"] for candidate in candidates}
        self.assertTrue(all(allocation["price"] == candidate_prices[allocation["ticker"]]
                            for allocation in allocations))


if __name__ == "__main__":
    unittest.main()