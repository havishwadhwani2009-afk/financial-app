import pytest
from fastapi.testclient import TestClient

from app.forecasting.service import forecast_instrument
from app.main import app
from app.models import Instrument, IngestionRun
from tests.synthetic import make_prices
from tests.test_forecasting import _load_db

H = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture()
def client(db):
    from app.api_common import limiter
    limiter.reset()
    return TestClient(app)


def test_health_and_empty_status(client):
    assert client.get("/api/health").json() == {"status": "ok", "database": "ok"}
    s = client.get("/api/status").json()
    assert s["empty"] is True and "No market data" in s["message"]


def test_consistent_error_shape(client):
    r = client.get("/api/assets/9999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.get("/api/assets?limit=9999")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_admin_requires_token(client):
    assert client.post("/api/admin/ingest", json={"kind": "macro"}).status_code == 401
    assert client.post("/api/admin/ingest", json={"kind": "macro"}, headers={"X-Admin-Token": "bad"}).status_code == 401
    assert client.post("/api/admin/ingest", json={"kind": "nope"}, headers=H).status_code == 422


def test_admin_disabled_without_configured_token(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_token", None)
    r = client.post("/api/admin/forecast", json={}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_disabled"


def test_search_prices_forecasts_screener_backtests(client, db):
    inst = _load_db(db, make_prices(1300, seed=7), symbol="SYN")
    inst.name = "Synthetic ETF (test)"
    db.commit()
    forecast_instrument(db, inst, horizons=(21,))
    a = client.get("/api/assets", params={"q": "syn"}).json()
    assert a["total"] == 1 and a["items"][0]["symbol"] == "SYN"
    p = client.get(f"/api/assets/{inst.id}/prices", params={"limit": 50}).json()
    assert p["count"] == 50 and p["stale"] is True  # synthetic dates are in the past -> flagged stale
    f = client.get(f"/api/assets/{inst.id}/forecasts").json()
    assert len(f) == 1 and f[0]["horizon_label"] == "1 month" and f[0]["model_name"] == "linear"
    assert f[0]["evidence"]["limitations"] and f[0]["data_cutoff"]
    sc = client.get("/api/screener", params={"horizon": 21, "sort": "prob_up", "order": "desc"}).json()
    assert sc["items"][0]["symbol"] == "SYN" and sc["items"][0]["prob_up"] is not None
    assert client.get("/api/screener", params={"horizon": 7}).status_code == 422
    bt = client.get("/api/backtests", params={"model": "linear"}).json()
    assert bt["total"] == 1
    d = client.get(f"/api/backtests/{bt['items'][0]['id']}").json()
    assert d["out_of_sample"] is True and d["predictions"] and d["calibration"]
    assert client.get("/api/backtests/summary").json()["horizons"]["21"]["n_assets"] == 1
    assert client.get("/api/forecasts", params={"history": True}).json()["total"] == 1
    etf = client.get(f"/api/assets/{inst.id}/etf").json()
    assert etf["holdings"] is None and "not guessed" in etf["unavailable_reason"]


def test_status_reports_failed_provider(client, db):
    db.add(IngestionRun(provider="yahoo", job="prices", target="SPY", status="failed", error="HTTP 403"))
    db.commit()
    p = client.get("/api/status").json()["providers"][0]
    assert p["provider"] == "yahoo" and p["last_error"] == "HTTP 403" and p["failures_24h"] == 1


def test_fundamentals_for_unknown_data_explains_absence(client, db):
    i = Instrument(symbol="AAA", exchange="US", instrument_type="stock")
    db.add(i)
    db.commit()
    r = client.get(f"/api/assets/{i.id}/fundamentals").json()
    assert r["periods"] == [] and any("No annual SEC filings" in w for w in r["warnings"])
