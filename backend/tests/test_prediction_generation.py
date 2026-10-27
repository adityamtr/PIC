import pandas as pd
import unittest

from app.prediction_generation import three_month_moving_average_fallbacks


class MovingAverageFallbackTests(unittest.TestCase):
    def test_three_month_average_returns_fractional_return(self):
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "AAA", "AAA", "AAA"],
                "date": pd.to_datetime(
                    ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]
                ),
                "monthly_open": [10.0, 10.0, 12.0, 15.0],
            }
        )

        predictions, windows = three_month_moving_average_fallbacks(frame)

        self.assertAlmostEqual(
            predictions["AAA"], (10.0 + 12.0 + 15.0) / 3 / 15.0 - 1
        )
        self.assertEqual(windows, {"AAA": 3})

    def test_short_history_uses_two_months_and_skips_one(self):
        frame = pd.DataFrame(
            {
                "symbol": ["TWO", "TWO", "ONE"],
                "date": pd.to_datetime(
                    ["2026-08-01", "2026-09-01", "2026-09-01"]
                ),
                "monthly_open": [90.0, 100.0, 12.0],
            }
        )

        predictions, windows = three_month_moving_average_fallbacks(frame)

        self.assertAlmostEqual(predictions["TWO"], -0.05)
        self.assertEqual(windows, {"TWO": 2})
