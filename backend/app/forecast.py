"""
Return-forecasting layer — powered by versioned TemporalFusionTransformer (TFT) backend models.

Consumes versioned predictions stored under `backend/predictions/{version}/`.
Model versions can be switched dynamically or via environment variables (`TFT_MODEL_VERSION` or `MODEL_VERSION`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import data

# Root directory for backend TFT models
MODELS_DIR = Path(__file__).resolve().parent.parent / "models" / "tft"
PREDICTIONS_DIR = Path(__file__).resolve().parent.parent / "predictions"

# In-memory model cache
_CURRENT_VERSION: str | None = None
_MODEL_METADATA: dict[str, Any] = {}
_PREDICTIONS: dict[str, float] = {}
_DEFAULT_RETURN = 0.010


def list_available_versions() -> list[str]:
    """List model versions that have predictions under backend/predictions."""
    versions = {
        path.name
        for path in PREDICTIONS_DIR.glob("v*")
        if path.is_dir() and path.name[1:].isdigit()
        and (path / "predictions.json").is_file()
    }
    if (PREDICTIONS_DIR / "predictions.json").is_file():
        versions.add("v2")
    return sorted(versions, key=lambda name: int(name[1:]))


def resolve_model_version(requested_version: str | None = None) -> str:
    """
    Resolve requested version string ('latest', 'v2', etc.) to a specific version directory name.
    """
    available = list_available_versions()
    
    if not requested_version:
        requested_version = os.environ.get("TFT_MODEL_VERSION") or os.environ.get("MODEL_VERSION") or "latest"

    requested_version = requested_version.strip().lower()

    if requested_version == "latest":
        if available:
            return available[-1]
        return "v2"  # fallback default if empty

    if not requested_version.startswith("v"):
        requested_version = f"v{requested_version}"

    if available and requested_version not in available:
        # Fallback to latest or standard if requested version doesn't exist
        return available[-1]

    return requested_version


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

    pred_file = PREDICTIONS_DIR / target_version / "predictions.json"
    if target_version == "v2" and not pred_file.exists():
        pred_file = PREDICTIONS_DIR / "predictions.json"
    if pred_file.exists():
        try:
            with open(pred_file, "r", encoding="utf-8") as f:
                predictions = json.load(f)
        except Exception:
            pass

    _CURRENT_VERSION = target_version
    _MODEL_METADATA = metadata
    _PREDICTIONS = predictions
    return target_version


def set_active_model_version(version: str) -> str:
    """Switch the active model version across the whole application in one go."""
    return load_model(version)


def get_active_model_info() -> dict[str, Any]:
    """Return info about the active model version."""
    if _CURRENT_VERSION is None:
        load_model()
    return {
        "version": _CURRENT_VERSION,
        "model_name": f"TemporalFusionTransformer ({_CURRENT_VERSION})",
        "available_versions": list_available_versions(),
        "metadata": _MODEL_METADATA,
        "predictions_count": len(_PREDICTIONS),
        "is_placeholder": False if len(_PREDICTIONS) > 0 else True,
    }


def expected_return(ticker: str) -> float:
    """Predicted 1-month return (fraction) for one ticker from active model."""
    if _CURRENT_VERSION is None:
        load_model()
    return _PREDICTIONS.get(ticker, _DEFAULT_RETURN)


def predict_returns(tickers) -> dict[str, float]:
    """Predicted 1-month returns (fraction) for a list of tickers from active model."""
    if _CURRENT_VERSION is None:
        load_model()
    return {t: expected_return(t) for t in tickers}


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
    for tk in relevant:
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

    return {
        "model": model_name,
        "version": version,
        "horizon": "1 month",
        "as_of": info["metadata"].get("saved_at_utc", data.TODAY.isoformat()),
        "is_placeholder": is_placeholder,
        "note": f"Predicted 1-month returns generated by {model_name}."
                if not is_placeholder
                else "Dummy returns — placeholder until TFT predictions are loaded.",
        "rows": forecast_rows(ds, tickers),
    }


# Initial load at import time
load_model()

