from app import forecast, data_v2

def test_available_versions():
    versions = forecast.list_available_versions()
    assert "v2" in versions
    assert versions == sorted(versions, key=lambda name: int(name[1:]))

def test_predictions_load_only_from_predictions_directory(tmp_path, monkeypatch):
    active_version = forecast.get_active_model_info()["version"]
    predictions_dir = tmp_path / "predictions"
    models_dir = tmp_path / "models"
    version_dir = predictions_dir / "v3"
    version_dir.mkdir(parents=True)
    (version_dir / "predictions.json").write_text('{"CENTRAL": 0.25}', encoding="utf-8")
    model_dir = models_dir / "v3"
    model_dir.mkdir(parents=True)
    (model_dir / "predictions.json").write_text('{"MODEL_ONLY": 0.75}', encoding="utf-8")

    with monkeypatch.context() as patch:
        patch.setattr(forecast, "PREDICTIONS_DIR", predictions_dir)
        patch.setattr(forecast, "MODELS_DIR", models_dir)
        assert forecast.list_available_versions() == ["v3"]
        forecast.load_model("v3")
        assert forecast.expected_return("CENTRAL") == 0.25
        assert forecast.expected_return("MODEL_ONLY") == 0.010

    forecast.load_model(active_version)

def test_active_model_info():
    info = forecast.get_active_model_info()
    assert "version" in info
    assert info["model_name"].startswith("TemporalFusionTransformer")
    assert info["is_placeholder"] is False

def test_model_switching_in_one_go():
    versions = forecast.list_available_versions()
    assert versions
    
    forecast.set_active_model_version(versions[0])
    first_info = forecast.get_active_model_info()
    assert first_info["version"] == versions[0]
    first_returns = forecast.predict_returns(["INFY", "TCS", "RELIANCE"])
    assert "INFY" in first_returns

    forecast.set_active_model_version(versions[-1])
    last_info = forecast.get_active_model_info()
    assert last_info["version"] == versions[-1]

    last_returns = forecast.predict_returns(["INFY", "TCS", "RELIANCE"])
    assert "INFY" in last_returns

def test_forecast_summary():
    forecast.set_active_model_version("v2")
    ds = data_v2.get_ds(data_v2.DEFAULT_FUND_ID_V2)
    s = forecast.summary(ds)
    assert s["model"] == "TemporalFusionTransformer (v2)"
    assert s["version"] == "v2"
    assert s["is_placeholder"] is False
    assert len(s["rows"]) > 0
