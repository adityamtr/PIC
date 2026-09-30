"""Generate and persist one-month TFT forecasts for supported equity tickers."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
MODELS_DIR = BACKEND_DIR / "models" / "tft"
PREDICTIONS_DIR = BACKEND_DIR / "predictions"
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "processed" / "final" / "stock_macro_monthly_target.csv"

FEATURES = [
    "monthly_volume",
    "oil_price_usd_bbl",
    "oil_return_1m_pct",
    "oil_return_12m_pct",
    "gold_price_inr_10g",
    "gold_return_1m_pct",
    "gold_return_12m_pct",
    "cpi_index",
    "cpi_inflation_yoy_pct",
    "stock_return_1m",
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "volatility_3m",
    "volatility_6m",
    "volume_change_1m",
]


def generate_predictions_for_version(
    version: str,
    data_path: str | Path = DEFAULT_DATA_PATH,
    output_path: str | Path | None = None,
    batch_size: int = 64,
    num_workers: int = 0,
) -> dict[str, Any]:
    """Run one-step inference for each train-supported ticker and save fractions.

    The serialized values are fractional returns, matching ``forecast.py`` and
    its existing ``predictions.json`` contract (0.05 means a 5% return).
    """
    if not re.fullmatch(r"v\d+", version):
        raise ValueError(f"Expected a version like 'v3', got {version!r}")

    version_dir = MODELS_DIR / version
    weights_path = version_dir / "tft_model.pt"
    metadata_path = version_dir / "model_metadata.json"
    if not weights_path.is_file():
        raise FileNotFoundError(f"Model weights not found for {version}: {weights_path}")

    import numpy as np
    import pandas as pd
    import torch
    from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
    from pytorch_forecasting.data import GroupNormalizer
    from pytorch_forecasting.metrics import QuantileLoss

    data_path = Path(data_path)
    if not data_path.is_file():
        raise FileNotFoundError(f"Modeling data not found: {data_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    encoder_length = int(metadata.get("encoder_length", 12))
    prediction_length = int(metadata.get("prediction_length", 1))
    if prediction_length != 1:
        raise ValueError(f"Only one-step prediction is supported, metadata says {prediction_length}")

    df = pd.read_csv(data_path)
    derived_features = {
        "stock_return_1m",
        "momentum_3m",
        "momentum_6m",
        "momentum_12m",
        "volatility_3m",
        "volatility_6m",
        "volume_change_1m",
    }
    required_columns = (
        {"isin", "symbol", "date", "monthly_open"}
        | (set(FEATURES) - derived_features)
    )
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(f"Modeling data is missing required columns: {missing_columns}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["isin", "date"]).reset_index(drop=True)

    df["stock_return_1m"] = df.groupby("isin")["monthly_open"].pct_change() * 100
    df["target_return_1m"] = df.groupby("isin")["stock_return_1m"].shift(-1)
    returns = df.groupby("isin")["stock_return_1m"]
    df["momentum_3m"] = returns.transform(lambda s: s.rolling(3, min_periods=1).sum()).fillna(0).clip(-500, 500)
    df["momentum_6m"] = returns.transform(lambda s: s.rolling(6, min_periods=1).sum()).fillna(0).clip(-500, 500)
    df["momentum_12m"] = returns.transform(lambda s: s.rolling(12, min_periods=1).sum()).fillna(0).clip(-500, 500)
    df["volatility_3m"] = returns.transform(lambda s: s.rolling(3, min_periods=2).std()).fillna(0).clip(0, 200)
    df["volatility_6m"] = returns.transform(lambda s: s.rolling(6, min_periods=2).std()).fillna(0).clip(0, 200)
    df["volume_change_1m"] = df.groupby("isin")["monthly_volume"].transform(
        lambda s: s.pct_change() * 100
    ).fillna(0).clip(-500, 500)

    columns = ["isin", "symbol", "date", *FEATURES, "target_return_1m"]
    df = df[columns].copy()
    labeled = df.dropna(subset=["stock_return_1m", "target_return_1m"]).copy()
    if labeled.empty:
        raise ValueError("No labeled rows available to reconstruct the training dataset")

    train = labeled[labeled["date"] <= pd.Timestamp("2021-08-01")].copy()
    if train.empty:
        raise ValueError("No training rows exist before 2021-08-01")
    impute = {column: train[column].median() for column in FEATURES}

    min_date = labeled["date"].min()
    all_isins = sorted(labeled["isin"].unique())
    isin_to_series = {isin: index for index, isin in enumerate(all_isins)}
    train[FEATURES] = train[FEATURES].fillna(impute)
    train["time_idx"] = (
        (train["date"].dt.year - min_date.year) * 12
        + (train["date"].dt.month - min_date.month)
    )
    train["series_id"] = train["isin"].map(isin_to_series).astype(int)
    train.sort_values(["series_id", "time_idx"], inplace=True)
    train.reset_index(drop=True, inplace=True)

    train = train.groupby("series_id").filter(lambda group: len(group) >= encoder_length + 1)
    train = train.reset_index(drop=True)
    supported_series = set(train["series_id"].unique())
    if not supported_series:
        raise ValueError("No series have enough training history for this model")

    train["series_id"] = train["series_id"].astype(str)
    training_dataset = TimeSeriesDataSet(
        train,
        time_idx="time_idx",
        target="target_return_1m",
        group_ids=["series_id"],
        min_encoder_length=encoder_length,
        max_encoder_length=encoder_length,
        max_prediction_length=prediction_length,
        static_categoricals=["series_id"],
        time_varying_unknown_reals=FEATURES,
        target_normalizer=GroupNormalizer(groups=["series_id"]),
        allow_missing_timesteps=True,
        add_relative_time_idx=True,
    )

    inference = df.dropna(subset=["stock_return_1m"]).copy()
    inference[FEATURES] = inference[FEATURES].fillna(impute)
    inference["time_idx"] = (
        (inference["date"].dt.year - min_date.year) * 12
        + (inference["date"].dt.month - min_date.month)
    )
    inference["series_id"] = inference["isin"].map(isin_to_series)
    unsupported_tickers = sorted(
        inference.loc[~inference["series_id"].isin(supported_series), "symbol"]
        .dropna()
        .astype(str)
        .unique()
    )
    inference = inference[inference["series_id"].isin(supported_series)].copy()
    inference["series_id"] = inference["series_id"].astype(int).astype(str)
    inference["target_return_1m"] = inference["target_return_1m"].fillna(0.0)
    inference.sort_values(["series_id", "time_idx"], inplace=True)
    inference.reset_index(drop=True, inplace=True)

    prediction_dataset = TimeSeriesDataSet.from_dataset(
        training_dataset,
        inference,
        predict=True,
        stop_randomization=True,
    )
    dataloader = prediction_dataset.to_dataloader(
        train=False,
        batch_size=batch_size,
        num_workers=num_workers,
    )

    model = TemporalFusionTransformer.from_dataset(
        training_dataset,
        learning_rate=float(metadata.get("learning_rate", 0.001)),
        hidden_size=int(metadata.get("hidden_size", 64)),
        attention_head_size=int(metadata.get("attention_head_size", 4)),
        hidden_continuous_size=int(metadata.get("hidden_continuous_size", 32)),
        dropout=float(metadata.get("dropout", 0.1)),
        loss=QuantileLoss(),
        reduce_on_plateau_patience=5,
    )
    state = torch.load(weights_path, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    median_index = model.loss.quantiles.index(0.5)
    prediction_values: list[np.ndarray] = []
    prediction_indices: list[pd.DataFrame] = []
    with torch.no_grad():
        for x, _ in dataloader:
            x = {
                name: value.to(device) if torch.is_tensor(value) else value
                for name, value in x.items()
            }
            output = model(x)["prediction"][:, 0, median_index]
            prediction_values.append(output.detach().cpu().numpy())
            prediction_indices.append(prediction_dataset.x_to_index(x))

    if not prediction_values:
        raise ValueError("The prediction dataset produced no forecasts")

    values = np.concatenate(prediction_values).reshape(-1)
    indices = pd.concat(prediction_indices, ignore_index=True)
    if len(indices) != len(values):
        raise RuntimeError(f"Prediction/index length mismatch: {len(values)} vs {len(indices)}")

    latest_metadata = (
        inference.sort_values(["series_id", "time_idx"])
        .drop_duplicates("series_id", keep="last")[["series_id", "time_idx", "symbol", "date"]]
    )
    aligned = indices.merge(
        latest_metadata,
        on=["series_id", "time_idx"],
        how="left",
        validate="one_to_one",
    )
    if aligned["symbol"].isna().any():
        raise RuntimeError("Some model forecasts could not be matched to ticker metadata")

    predictions: dict[str, float] = {}
    for ticker, value in zip(aligned["symbol"], values, strict=True):
        if not math.isfinite(float(value)):
            continue
        predictions[str(ticker)] = round(float(value) / 100.0, 8)

    destination = (
        Path(output_path)
        if output_path is not None
        else PREDICTIONS_DIR / version / "predictions.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(destination.name + ".tmp")
    temporary_path.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(destination)

    from . import forecast

    canonical_destination = (PREDICTIONS_DIR / version / "predictions.json").resolve()
    if destination.resolve() == canonical_destination and forecast.get_active_model_info()["version"] == version:
        forecast.load_model(version)

    return {
        "version": version,
        "predictions_count": len(predictions),
        "supported_training_series": len(supported_series),
        "saved_to": str(destination.resolve()),
        "as_of": str(aligned["date"].max().date()),
        "unsupported_tickers": unsupported_tickers,
        "missing_supported_tickers": sorted(
            set(inference["symbol"].dropna().astype(str)) - set(predictions)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TFT predictions for a saved model version")
    parser.add_argument("version", help="Saved model version, for example v3")
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    result = generate_predictions_for_version(
        args.version,
        data_path=args.data_path,
        output_path=args.output_path,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()