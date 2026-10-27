from app import forecast, data_v2

def test_available_versions():
    versions = forecast.list_available_versions()
    assert versions == ["v13"]

def test_predictions_load_only_from_predictions_directory(tmp_path, monkeypatch):
    active_version = forecast.get_active_model_info()["version"]
    predictions_dir = tmp_path / "predictions"
    models_dir = tmp_path / "models"
    version_dir = predictions_dir / "v13"
    version_dir.mkdir(parents=True)
    (version_dir / "predictions.json").write_text('{"CENTRAL": 0.25}', encoding="utf-8")
    model_dir = models_dir / "v13"
    model_dir.mkdir(parents=True)
    (model_dir / "predictions.json").write_text('{"MODEL_ONLY": 0.75}', encoding="utf-8")

    with monkeypatch.context() as patch:
        patch.setattr(forecast, "PREDICTIONS_DIR", predictions_dir)
        patch.setattr(forecast, "MODELS_DIR", models_dir)
        forecast.load_model("v13")
        assert forecast.expected_return("CENTRAL") == 0.25
        try:
            forecast.expected_return("MODEL_ONLY")
        except KeyError as exc:
            assert "No v13 forecast" in str(exc)
        else:
            raise AssertionError("Unsupported ticker must not receive a default return")

    forecast.load_model(active_version)


def test_only_v13_can_be_selected(monkeypatch):
    monkeypatch.setenv("MODEL_VERSION", "v2")
    monkeypatch.setenv("TFT_MODEL_VERSION", "v12")
    assert forecast.resolve_model_version() == "v13"
    assert forecast.resolve_model_version("latest") == "v13"
    assert forecast.resolve_model_version("13") == "v13"
    for version in ("v2", "v12", "v14"):
        try:
            forecast.resolve_model_version(version)
        except ValueError as exc:
            assert "Only v13" in str(exc)
        else:
            raise AssertionError(f"{version} must not be selectable")


def test_prediction_metadata_is_exposed_for_active_version(tmp_path, monkeypatch):
    active_version = forecast.get_active_model_info()["version"]
    predictions_dir = tmp_path / "predictions"
    models_dir = tmp_path / "models"
    version_dir = predictions_dir / "v13"
    version_dir.mkdir(parents=True)
    (version_dir / "predictions.json").write_text('{"CENTRAL": 0.25}', encoding="utf-8")
    (version_dir / "prediction_metadata.json").write_text(
        '{"prediction_as_of":"2026-09-01","moving_average_fallback_count":38}',
        encoding="utf-8",
    )
    (models_dir / "v13").mkdir(parents=True)

    with monkeypatch.context() as patch:
        patch.setattr(forecast, "PREDICTIONS_DIR", predictions_dir)
        patch.setattr(forecast, "MODELS_DIR", models_dir)
        forecast.load_model("v13")

        assert forecast.get_active_model_info()["metadata"]["moving_average_fallback_count"] == 38
        summary = forecast.summary(
            {"holdings": [], "holdings_by_ticker": {}},
            tickers=["CENTRAL"],
        )
        assert summary["as_of"] == "2026-09-01"
        assert "38 covered tickers use three-month moving-average fallbacks" in summary["note"]

    forecast.load_model(active_version)


def test_active_model_info():
    info = forecast.get_active_model_info()
    assert "version" in info
    assert info["model_name"].startswith("TemporalFusionTransformer")
    assert info["is_placeholder"] is False

def test_model_switching_in_one_go():
    versions = forecast.list_available_versions()
    assert versions == ["v13"]

    assert forecast.set_active_model_version("v13") == "v13"
    info = forecast.get_active_model_info()
    assert info["version"] == "v13"
    returns = forecast.predict_returns(["INFY", "TCS", "RELIANCE"])
    assert "INFY" in returns

    try:
        forecast.set_active_model_version("v12")
    except ValueError as exc:
        assert "Only v13" in str(exc)
    else:
        raise AssertionError("Older model versions must not be selectable")

def test_forecast_summary():
    forecast.set_active_model_version("v13")
    ds = data_v2.get_ds(data_v2.DEFAULT_FUND_ID_V2)
    s = forecast.summary(ds)
    assert s["model"] == "TemporalFusionTransformer (v13)"
    assert s["version"] == "v13"
    assert s["is_placeholder"] is False
    assert len(s["rows"]) > 0
