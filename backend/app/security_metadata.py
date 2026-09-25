"""Curated security metadata used by the POC pre-trade policy layer."""

from __future__ import annotations

from datetime import date


def _esg_profile(ticker: str) -> dict:
    profiles = {
        "ITC": {
            "tobacco_exposure_pct": 35.0,
            "esg_excluded": True,
            "esg_exclusion_reason": "Tobacco production exposure",
        },
        "COALINDIA": {
            "thermal_coal_mining_pct": 100.0,
            "esg_excluded": True,
            "esg_exclusion_reason": "Thermal coal mining exposure",
        },
        "NTPC": {"thermal_power_generation_pct": 100.0},
    }
    return profiles.get(ticker, {})


def curate_security_metadata(ticker: str, sector: str, market_value: float,
                             price: float | None, as_of: date,
                             adv_cr: float | None = None) -> dict:
    """Return conservative, internally consistent POC metadata.

    Real feeds can override these values later. Liquidity is estimated from
    position size only when no observed ADV is available, and is marked as
    estimated so policy output can distinguish it from a market feed value.
    """
    if adv_cr is None:
        adv_cr = max(10.0, round((market_value / 10_000_000) * 0.08, 2))
        adv_source = "estimated_from_position_size"
    else:
        adv_cr = round(float(adv_cr), 2)
        adv_source = "curated_universe"

    median_adv_cr = round(adv_cr * 0.85, 2)
    if adv_cr >= 500:
        spread = 0.15
    elif adv_cr >= 100:
        spread = 0.30
    elif adv_cr >= 25:
        spread = 0.60
    else:
        spread = 0.95

    metadata = {
        "asset_class": "equity",
        "issuer_type": "corporate",
        "country": "India",
        "country_risk_bucket": "standard",
        "emerging_market": False,
        "currency": "INR",
        "fx_exposure_pct": 0.0,
        "currency_hedged": True,
        "adv_cr": adv_cr,
        "median_adv_cr": median_adv_cr,
        "adv_source": adv_source,
        "bid_ask_spread_pct": spread,
        "price_as_of": as_of.isoformat(),
        "price_stale": False,
        "lot_size": 1,
        "restricted": False,
        "watchlist": False,
        "pledged_shares": 0,
        "minimum_holding_shares": 0,
        "corporate_action_restricted_until": None,
        "tobacco_exposure_pct": 0.0,
        "controversial_weapons_exposure_pct": 0.0,
        "thermal_coal_mining_pct": 0.0,
        "thermal_power_generation_pct": 0.0,
        "esg_data_as_of": as_of.isoformat(),
        "esg_excluded": False,
        "esg_exclusion_reason": None,
        "ucits_eligible": True,
    }
    metadata.update(_esg_profile(ticker))
    return metadata