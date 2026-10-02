import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from app import db, main, planner


class PlanEmailTrackingTests(unittest.TestCase):
    def approved_plan(self):
        return {
            "plan_id": "PLAN-1",
            "status": "Approved — sent to Trading",
            "intent": {
                "trade_date": "2026-10-01",
                "settlement_date": "2026-10-03",
            },
            "orders": [{
                "ticker": "TEST",
                "side": "BUY",
                "shares": 2,
                "price": 10,
            }],
        }

    def test_approved_plan_is_unsettled_once_even_with_multiple_sent_emails(self):
        plan = self.approved_plan()
        with (
            patch.object(planner.db, "list_plans", return_value=[plan]),
            patch.object(planner.db, "list_sent_emails", return_value=[{}, {}]),
            patch.object(planner.data, "universe_entry", return_value=None),
        ):
            first_read = planner._augment_pending_trades_from_approved_plans("TEST-FUND")
            second_read = planner._augment_pending_trades_from_approved_plans("TEST-FUND")

        self.assertEqual(len(first_read), 1)
        self.assertEqual(first_read, second_read)
        self.assertEqual(first_read[0]["trade_id"], "PLAN-1-TEST")
        self.assertEqual(first_read[0]["trade_date"], "2026-10-01")
        self.assertEqual(first_read[0]["settlement_date"], "2026-10-03")

    def test_approved_plan_is_not_unsettled_until_an_email_is_sent(self):
        with (
            patch.object(planner.db, "list_plans", return_value=[self.approved_plan()]),
            patch.object(planner.db, "list_sent_emails", return_value=[]),
        ):
            trades = planner._augment_pending_trades_from_approved_plans("TEST-FUND")

        self.assertEqual(trades, [])

    def test_sent_email_summary_counts_sends_and_reports_latest_timestamp(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with (
                patch.object(db, "available", return_value=True),
                patch.object(db, "connect", return_value=connection),
            ):
                with connection:
                    connection.execute("CREATE TABLE plans (plan_id TEXT PRIMARY KEY)")
                    connection.execute("INSERT INTO plans (plan_id) VALUES (?)", ("PLAN-1",))

                for email_id, sent_at in (
                    ("EMAIL-1", "2026-10-01T10:00:00+00:00"),
                    ("EMAIL-2", "2026-10-02T10:00:00+00:00"),
                ):
                    db.create_sent_email({
                        "email_id": email_id,
                        "plan_id": "PLAN-1",
                        "subject": "Plan update",
                        "body": "Plan details",
                        "model": "test",
                        "sent_at": sent_at,
                    })

                summaries = db.list_sent_email_summaries()

        self.assertEqual(summaries["PLAN-1"]["sent_email_count"], 2)
        self.assertEqual(
            summaries["PLAN-1"]["last_sent_email_at"],
            "2026-10-02T10:00:00+00:00",
        )

    def test_plan_history_includes_sent_email_summary(self):
        plan = self.approved_plan()
        with (
            patch.object(main.db, "list_plans", return_value=[plan]),
            patch.object(main.db, "list_sent_email_summaries", return_value={
                "PLAN-1": {
                    "sent_email_count": 1,
                    "last_sent_email_at": "2026-10-02T10:00:00+00:00",
                },
            }),
        ):
            result = main.list_trade_plans("TEST-FUND")

        self.assertEqual(result["plans"][0]["sent_email_count"], 1)
        self.assertEqual(
            result["plans"][0]["last_sent_email_at"],
            "2026-10-02T10:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()