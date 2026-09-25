"""Exercise generated plans across all real-data funds and allocation modes.

Run from the backend directory:

    python tests/plan_generation_matrix.py

The script is intentionally observational. It does not assert that every plan
passes; it reports policy outcomes and suggests which controls should be
adjusted versus which should remain hard blocks.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import data_v2, planner


FUNDS = tuple(data_v2.FUNDS_V2)
MODES = ("manual", "rules", "optimize")
AMOUNTS_CR = (0.0, 10.0, 50.0, 250.0)


@dataclass
class Result:
    fund_id: str
    method: str
    case: str
    action: str
    amount_cr: float | None
    plan_status: str
    execution_allowed: bool
    order_count: int
    policy_status: str
    compliance_status: str
    block_codes: tuple[str, ...]
    escalation_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    error: str | None = None


def _first_holding(ds: dict, sellable: bool = False) -> dict:
    holdings = ds["holdings"]
    if sellable:
        holdings = [h for h in holdings if h.get("sellable_shares", 0) > 0]
    return holdings[0]


def _manual_request(ds: dict, action: str, target: str | None,
                    amount_cr: float | None) -> dict:
    if action == "rebalance":
        return {"action": action, "amount_cr": None, "method": "manual", "horizon_days": 5}

    if action == "redemption":
        holding = _first_holding(ds, sellable=True)
        return {
            "action": action, "amount_cr": amount_cr, "method": "manual",
            "horizon_days": 5,
            "manual_selections": [{
                "ticker": holding["ticker"], "side": "SELL", "amount_cr": amount_cr,
            }],
        }

    if action == "increase":
        candidates = [u for u in data_v2.FUNDS_V2[ds["id"]]["holdings"]
                      if u.get("sector") == target]
        if not candidates:
            candidates = [h for h in ds["holdings"] if h.get("sector") == target]
        if candidates:
            ticker = candidates[0]["ticker"]
        else:
            ticker = ds["holdings"][0]["ticker"]
        return {
            "action": action, "target": target, "amount_cr": amount_cr,
            "method": "manual", "horizon_days": 5,
            "manual_selections": [{"ticker": ticker, "side": "BUY", "amount_cr": amount_cr}],
        }

    holding = _first_holding(ds)
    return {
        "action": "contribution", "amount_cr": amount_cr, "method": "manual",
        "horizon_days": 5,
        "manual_selections": [{
            "ticker": holding["ticker"], "side": "BUY", "amount_cr": amount_cr,
        }],
    }


def _requests(ds: dict, method: str) -> list[tuple[str, dict]]:
    requests = []
    for amount_cr in AMOUNTS_CR:
        action = "contribution"
        request = {"action": action, "amount_cr": amount_cr, "method": method, "horizon_days": 5}
        if method == "manual":
            request = _manual_request(ds, action, None, amount_cr)
        requests.append((f"contribution-{amount_cr:g}Cr", request))

    for action, target, amount_cr in (
        ("increase", "technology", 10.0),
        ("increase", "financial services", 50.0),
        ("redemption", None, 50.0),
        ("rebalance", None, None),
    ):
        request = {
            "action": action, "amount_cr": amount_cr, "method": method,
            "horizon_days": 5,
        }
        if target:
            request["target"] = target
        if method == "manual":
            request = _manual_request(ds, action, target, amount_cr)
        requests.append((f"{action}-{target or 'book'}-{amount_cr or 0:g}Cr", request))
    return requests


def _run_one(fund_id: str, method: str, case: str, request: dict) -> Result:
    try:
        plan = planner.generate_plan(fund_id, request)
        checks = plan.get("policy_checks", [])
        return Result(
            fund_id=fund_id,
            method=method,
            case=case,
            action=request["action"],
            amount_cr=request.get("amount_cr"),
            plan_status=plan.get("status", "unknown"),
            execution_allowed=plan.get("execution_allowed", False),
            order_count=len(plan.get("orders", [])),
            policy_status=plan.get("policy_status", "unknown"),
            compliance_status=plan.get("summary", {}).get("compliance_status", "unknown"),
            block_codes=tuple(sorted({c["code"] for c in checks if c.get("status") == "BLOCK"})),
            escalation_codes=tuple(sorted({c["code"] for c in checks if c.get("status") == "ESCALATE"})),
            warning_codes=tuple(sorted({c["code"] for c in checks if c.get("status") == "WARN"})),
        )
    except Exception as exc:  # keep the matrix running for other funds/cases
        return Result(
            fund_id=fund_id, method=method, case=case, action=request["action"],
            amount_cr=request.get("amount_cr"), plan_status="ERROR",
            execution_allowed=False, order_count=0, policy_status="ERROR",
            compliance_status="ERROR", block_codes=(), escalation_codes=(),
            warning_codes=(), error=f"{type(exc).__name__}: {exc}",
        )


def run_matrix() -> list[Result]:
    results = []
    for fund_id in FUNDS:
        ds = data_v2.get_ds(fund_id)
        for method in MODES:
            for case, request in _requests(ds, method):
                results.append(_run_one(fund_id, method, case, request))
    return results


def _suggestions(results: list[Result]) -> list[str]:
    blocked = Counter(code for result in results for code in result.block_codes)
    escalated = Counter(code for result in results for code in result.escalation_codes)
    total = len(results)
    executable = sum(result.execution_allowed for result in results)
    suggestions = [
        f"Executable plans: {executable}/{total} ({executable / total:.1%}).",
    ]
    if blocked["MANDATE-ISSUER"] or blocked["MANDATE-GROUP"] or blocked["MANDATE-SECTOR"]:
        suggestions.append(
            "Do not raise mandate caps. Evaluate incremental exposure: grandfather existing "
            "breaches and block only orders that worsen them."
        )
    if blocked["UCITS-5-40"]:
        suggestions.append(
            "Do not relax the 5/40 diversification rule. Calculate the delta caused by the "
            "new orders instead of blocking plans because of inherited holdings."
        )
    if blocked["CASH-DEPLOYMENT"]:
        suggestions.append(
            "For normal contributions, allow up to 95% of investable cash; require funding "
            "sells or escalation for the remaining amount."
        )
    if blocked["LIQUIDITY-ADV"] or blocked["LIQUIDITY-SPREAD"]:
        suggestions.append(
            "Keep the 5% ADV warning and 10% single-day participation target; allow a "
            "scheduled parent plan up to 75% ADV, split across sessions, and hard-block "
            "only above 75%."
        )
    if blocked["ESG-EXCLUSION"]:
        suggestions.append(
            "Keep ESG exclusions hard. Replace excluded names with eligible alternatives "
            "instead of relaxing the tobacco/coal thresholds."
        )
    if blocked["LIQUIDITY-ADV"] or escalated["PLAN-ORDER-COUNT"]:
        suggestions.append(
            "UI operating profile: default to <=10 Cr tickets, allow one generated plan up "
            "to 50 Cr, and split larger requests into child plans with separate execution "
            "windows."
        )
    if blocked["RESTRICTED-SELL"]:
        suggestions.append(
            "Keep restricted sells as hard failures; show the sellable quantity and create "
            "a funding alternative rather than relaxing lock-in or pending-settlement rules."
        )
    if escalated["LIQUIDITY-DATA"]:
        suggestions.append(
            "Populate ADV, median ADV, and spread metadata for every candidate; do not treat "
            "missing liquidity data as a normal pass."
        )
    return suggestions


def report(results: list[Result], full: bool = False) -> None:
    total = len(results)
    status_counts = Counter(result.policy_status for result in results)
    print(f"Plan matrix: {total} cases ({len(FUNDS)} funds x {len(MODES)} modes)")
    print("Policy status: " + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())))
    print()

    print("By fund and mode")
    grouped = defaultdict(list)
    for result in results:
        grouped[(result.fund_id, result.method)].append(result)
    for (fund_id, method), items in grouped.items():
        counts = Counter(item.policy_status for item in items)
        executable = sum(item.execution_allowed for item in items)
        print(f"  {fund_id:28} {method:8} executable={executable}/{len(items)} "
              + " ".join(f"{key}={value}" for key, value in sorted(counts.items())))

    block_counts = Counter(code for result in results for code in result.block_codes)
    escalation_counts = Counter(code for result in results for code in result.escalation_codes)
    print("\nDominant block codes")
    print("  " + (", ".join(f"{key}={value}" for key, value in block_counts.most_common()) or "none"))
    print("Dominant escalation codes")
    print("  " + (", ".join(f"{key}={value}" for key, value in escalation_counts.most_common()) or "none"))

    print("\nSuggested adjustments")
    for suggestion in _suggestions(results):
        print(f"  - {suggestion}")

    if full:
        print("\nCase details")
        for result in results:
            codes = ",".join(result.block_codes + result.escalation_codes + result.warning_codes) or "-"
            print(f"  {result.fund_id:28} {result.method:8} {result.case:38} "
                  f"{result.policy_status:9} allowed={str(result.execution_allowed):5} rules={codes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Print every matrix case.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results.")
    args = parser.parse_args()
    results = run_matrix()
    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        report(results, full=args.full)


if __name__ == "__main__":
    main()