"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class IntentRequest(BaseModel):
    """A Portfolio Manager's investment intent."""

    action: Literal[
        # portfolio-level (no sector needed)
        "contribution", "redemption", "rebalance",
        # sector / security level
        "increase", "decrease", "buy", "sell", "trim", "add", "raise_cash",
    ] = Field("contribution", description="What to do.")
    target: Optional[str] = Field(
        None, description="Single sector or security (only for increase/decrease actions)."
    )
    targets: Optional[list[str]] = Field(
        None,
        description="One or more sectors to increase/decrease together; the amount is "
                    "split across them. Takes precedence over `target` when provided.",
    )
    amount_cr: Optional[float] = Field(
        None, ge=0, description="Amount in Rs crore (not required for rebalance)."
    )
    horizon_days: int = Field(5, ge=1, le=30, description="Planning horizon (business days).")
    note: Optional[str] = Field(None, description="Free-text note from the PM.")
    fund_id: Optional[str] = Field(None, description="Fund to plan for (defaults to the default fund).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "action": "contribution",
                "amount_cr": 250,
                "horizon_days": 5,
                "fund_id": "HDFC-TOP100-DG",
                "note": "Deploy inflow across the book toward target weights.",
            }
        }
    }


class DecisionRequest(BaseModel):
    """A PIC associate's decision on a generated plan."""

    decision: Literal["Approve", "Modify", "Reject", "Escalate"]
    reviewer: Optional[str] = None
    comment: Optional[str] = None


class DecisionResponse(BaseModel):
    plan_id: str
    status: str
    decision: str
    reviewer: Optional[str] = None
    comment: Optional[str] = None
    decided_at: str


# Plans are dynamic dicts; keep the response permissive.
PlanResponse = dict[str, Any]
