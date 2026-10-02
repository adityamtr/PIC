import unittest

from app.assistant import IntentUpdates, _run_tool, _validated_updates


class AssistantTests(unittest.TestCase):
    def test_intent_updates_are_limited_to_available_funds_and_sectors(self):
        updates = IntentUpdates(
            fund_id="UNKNOWN-FUND",
            targets=["information technology", "Made-up Sector"],
            action="increase",
            amount_cr=50,
            manual_selections=[{"ticker": "aaa", "side": "BUY", "amount_cr": 10},
                               {"ticker": "UNKNOWN", "side": "SELL", "amount_cr": 5}],
        )

        result = _validated_updates(
            updates,
            [{"fund_id": "FUND-1", "name": "Example Fund"}],
            ["Information Technology", "Healthcare"],
            ["AAA", "BBB"],
        )

        self.assertNotIn("fund_id", result)
        self.assertEqual(result["targets"], ["Information Technology"])
        self.assertEqual(result["action"], "increase")
        self.assertEqual(result["amount_cr"], 50)
        self.assertEqual(result["manual_selections"], [
            {"ticker": "AAA", "side": "BUY", "amount_cr": 10},
        ])
        self.assertEqual(result["method"], "manual")

    def test_read_tools_return_only_plan_information_and_do_not_mutate(self):
        plan = {
            "plan_id": "PLAN-1",
            "orders": [
                {"ticker": "AAA", "side": "BUY", "est_value": 100},
                {"ticker": "BBB", "side": "SELL", "est_value": 50},
            ],
            "policy_checks": [{"code": "POLICY-1", "status": "BLOCK"}],
            "compliance_checks": [{"code": "LIMIT-1", "status": "FAIL"}],
            "summary": {"compliance_status": "FAIL", "order_count": 2},
        }
        original = {key: value.copy() if isinstance(value, list) else value for key, value in plan.items()}

        orders = _run_tool("get_order_details", {"ticker": "aaa"}, plan)
        checks = _run_tool("get_policy_results", {}, plan)
        summary = _run_tool("get_plan_summary", {}, plan)

        self.assertEqual(orders["total_matching"], 1)
        self.assertEqual(orders["orders"][0]["ticker"], "AAA")
        self.assertEqual(checks["policy_checks"][0]["status"], "BLOCK")
        self.assertEqual(checks["compliance_checks"][0]["status"], "FAIL")
        self.assertEqual(summary["summary"]["order_count"], 2)
        self.assertEqual(plan, original)


if __name__ == "__main__":
    unittest.main()