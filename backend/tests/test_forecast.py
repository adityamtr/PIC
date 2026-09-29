from app import forecast, data_v2

def test_available_versions():
    versions = forecast.list_available_versions()
    assert "v1" in versions
    assert "v2" in versions

def test_active_model_info():
    info = forecast.get_active_model_info()
    assert "version" in info
    assert info["model_name"].startswith("TemporalFusionTransformer")
    assert info["is_placeholder"] is False

def test_model_switching_in_one_go():
    # Switch to v1
    forecast.set_active_model_version("v1")
    info_v1 = forecast.get_active_model_info()
    assert info_v1["version"] == "v1"
    
    returns_v1 = forecast.predict_returns(["INFY", "TCS", "RELIANCE"])
    assert "INFY" in returns_v1

    # Switch to v2
    forecast.set_active_model_version("v2")
    info_v2 = forecast.get_active_model_info()
    assert info_v2["version"] == "v2"

    returns_v2 = forecast.predict_returns(["INFY", "TCS", "RELIANCE"])
    assert "INFY" in returns_v2

def test_forecast_summary():
    forecast.set_active_model_version("v2")
    ds = data_v2.get_ds(data_v2.DEFAULT_FUND_ID_V2)
    s = forecast.summary(ds)
    assert s["model"] == "TemporalFusionTransformer (v2)"
    assert s["version"] == "v2"
    assert s["is_placeholder"] is False
    assert len(s["rows"]) > 0
