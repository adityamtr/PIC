"""
Return-forecasting layer — serves predictions from the pinned v13 model.

Consumes precomputed predictions stored under `backend/predictions/v13/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import data

# Root directory for backend TFT models
MODELS_DIR = Path(__file__).resolve().parent.parent / "models" / "tft"
PREDICTIONS_DIR = Path(__file__).resolve().parent.parent / "predictions"
ACTIVE_MODEL_VERSION = "v13"

# In-memory model cache
_CURRENT_VERSION: str | None = None
_MODEL_METADATA: dict[str, Any] = {}
_PREDICTIONS: dict[str, float] = {}


def list_available_versions() -> list[str]:
    """Return the sole model version enabled for application forecasts."""
    prediction_file = PREDICTIONS_DIR / ACTIVE_MODEL_VERSION / "predictions.json"
    return [ACTIVE_MODEL_VERSION] if prediction_file.is_file() else []


def resolve_model_version(requested_version: str | None = None) -> str:
    """
    Resolve the only enabled model version, rejecting attempts to select older models.
    """
    requested = requested_version.strip().lower() if requested_version else "latest"
    if requested not in {"latest", ACTIVE_MODEL_VERSION, ACTIVE_MODEL_VERSION[1:]}:
        raise ValueError(
            f"Only {ACTIVE_MODEL_VERSION} predictions are enabled; got {requested_version!r}"
        )
    prediction_file = PREDICTIONS_DIR / ACTIVE_MODEL_VERSION / "predictions.json"
    if not prediction_file.is_file():
        raise FileNotFoundError(
            f"Required {ACTIVE_MODEL_VERSION} predictions are missing: {prediction_file}"
        )
    return ACTIVE_MODEL_VERSION


def load_model(version: str | None = None) -> str:
    """
    Load metadata and predictions for the target model version into memory.
    Can be called to switch model versions with one go.
    """
    global _CURRENT_VERSION, _MODEL_METADATA, _PREDICTIONS

    target_version = resolve_model_version(version)
    version_dir = MODELS_DIR / target_version

    metadata: dict[str, Any] = {
        "version": target_version,
        "model_type": "TemporalFusionTransformer",
        "framework": "pytorch-forecasting",
    }
    predictions: dict[str, float] = {}

    meta_file = version_dir / "model_metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata.update(json.load(f))
        except Exception:
            pass
    prediction_metadata_file = (
        PREDICTIONS_DIR / target_version / "prediction_metadata.json"
    )
    if prediction_metadata_file.exists():
        try:
            with open(prediction_metadata_file, "r", encoding="utf-8") as f:
                metadata.update(json.load(f))
        except Exception:
            pass

    prediction_file = PREDICTIONS_DIR / target_version / "predictions.json"
    with open(prediction_file, "r", encoding="utf-8") as f:
        predictions = json.load(f)

    _CURRENT_VERSION = target_version
    _MODEL_METADATA = metadata
    _PREDICTIONS = predictions
    return target_version


def set_active_model_version(version: str) -> str:
    """Select the only enabled model version."""
    return load_model(version)


def get_active_model_info() -> dict[str, Any]:
    """Return info about the active model version. Reloads from the DB each
    call so a reseeded DB is reflected without a server restart."""
    load_model(_CURRENT_VERSION)
    return {
        "version": _CURRENT_VERSION,
        "model_name": f"TemporalFusionTransformer ({_CURRENT_VERSION})",
        "available_versions": list_available_versions(),
        "metadata": _MODEL_METADATA,
        "predictions_count": len(_PREDICTIONS),
        "is_placeholder": False if len(_PREDICTIONS) > 0 else True,
    }


def expected_return(ticker: str) -> float:
    """Return a model forecast, failing explicitly for unsupported tickers."""
    if _CURRENT_VERSION is None:
        load_model()
    try:
        return _PREDICTIONS[ticker]
    except KeyError as exc:
        raise KeyError(f"No {ACTIVE_MODEL_VERSION} forecast is available for {ticker}") from exc


def predict_returns(tickers) -> dict[str, float]:
    """Predicted 1-month returns (fraction) for a list of tickers from active model.

    Reloads the active version's predictions from the DB first (once per plan,
    not per ticker) so a reseeded DB (e.g. `init_db.py --reset`) is picked up by
    an already-running server without requiring a restart.
    """
    load_model(_CURRENT_VERSION)
    return {ticker: _PREDICTIONS[ticker] for ticker in tickers if ticker in _PREDICTIONS}


def _name_sector(ds, ticker):
    u = data.universe_entry(ticker)
    if u:
        return u["name"], u["sector"]
    h = data.holding(ds, ticker)
    if h:
        return h["name"], h["sector"]
    return ticker, "Unknown"


def forecast_rows(ds, tickers=None) -> list[dict]:
    """
    Build a display-ready, return-sorted forecast table.
    """
    if tickers is None:
        relevant = {h["ticker"] for h in ds["holdings"]}
        relevant |= {u["ticker"] for u in data.UNIVERSE}
    else:
        relevant = set(tickers)

    rows = []
    for tk in relevant.intersection(_PREDICTIONS):
        name, sector = _name_sector(ds, tk)
        rows.append({
            "ticker": tk,
            "name": name,
            "sector": sector,
            "expected_return_1m": round(expected_return(tk), 4),
        })
    rows.sort(key=lambda r: r["expected_return_1m"], reverse=True)
    return rows


def summary(ds, tickers=None) -> dict:
    """Forecast block attached to a plan, for the UI to render."""
    info = get_active_model_info()
    version = info["version"]
    model_name = info["model_name"]
    is_placeholder = info["is_placeholder"]
    requested_tickers = (
        {h["ticker"] for h in ds["holdings"]}
        | {u["ticker"] for u in data.UNIVERSE}
        if tickers is None
        else set(tickers)
    )
    uncovered_count = len(requested_tickers - _PREDICTIONS.keys())
    note = (
        f"Predicted 1-month returns generated by {model_name}."
        if not is_placeholder
        else "Dummy returns — placeholder until TFT predictions are loaded."
    )
    if not is_placeholder and info["metadata"].get("moving_average_fallback_count"):
        note += (
            f" {info['metadata']['moving_average_fallback_count']} covered tickers use "
            "three-month moving-average fallbacks."
        )
    if uncovered_count:
        note += f" No v13 forecast is available for {uncovered_count} requested tickers; they are omitted."

    return {
        "model": model_name,
        "version": version,
        "horizon": "1 month",
        "as_of": info["metadata"].get(
            "prediction_as_of",
            info["metadata"].get("saved_at_utc", data.TODAY.isoformat()),
        ),
        "is_placeholder": is_placeholder,
        "note": note,
        "rows": forecast_rows(ds, tickers),
    }


# Initial load at import time
load_model()
