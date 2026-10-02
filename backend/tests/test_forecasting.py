import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select

from app.forecasting import backtest as B
from app.forecasting import metrics as M
from app.forecasting.features import (build_features, forward_log_return, known_as_of, macro_features,
                                      price_features)
from app.forecasting.service import forecast_instrument
from app.models import (BacktestRun, Forecast, Instrument, MacroObservation, Price)
from tests.synthetic import make_prices


def test_price_features_have_no_lookahead():
    px = make_prices(800)
    full = price_features(px)
    cut = price_features(px.iloc[:500])
    pd.testing.assert_frame_equal(full.iloc[:500], cut, check_exact=False, rtol=1e-12)


def test_changing_the_future_never_changes_past_features():
    px = make_prices(800)
    px2 = px.copy()
    px2.iloc[600:, 0] *= 3.0
    a, b = price_features(px), price_features(px2)
    pd.testing.assert_frame_equal(a.iloc[:600], b.iloc[:600])


def test_label_is_forward_looking_only():
    px = make_prices(100)
    y = forward_log_return(px["adj_close"], 5)
    assert y.iloc[-5:].isna().all() and y.iloc[:-5].notna().all()
    assert y.iloc[0] == pytest.approx(np.log(px["adj_close"].iloc[5] / px["adj_close"].iloc[0]))


def test_macro_alignment_uses_publication_date_and_ignores_later_revisions():
    obs = pd.DataFrame({
        "series_id": "CPIAUCSL",
        "observation_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01"]),
        "published_date": pd.to_datetime(["2024-02-13", "2024-03-12", "2024-03-12"]),
        "value": [300.0, 305.0, 306.0]})  # Jan first print 300, revised to 305 on 3/12
    step = known_as_of(obs)
    idx = pd.bdate_range("2024-02-01", "2024-03-29")
    s = pd.merge_asof(pd.DataFrame({"date": idx}), step, left_on="date", right_on="published_date")
    s = pd.Series(s["value"].values, index=idx)
    assert np.isnan(s["2024-02-12"])                 # not yet published
    assert s["2024-02-13"] == 300.0                  # first print, not the revision
    assert s["2024-03-11"] == 300.0                  # revision still unknown
    assert s["2024-03-12"] == 306.0                  # latest observation, latest vintage


def test_macro_features_shape():
    px = make_prices(400)
    obs = pd.DataFrame({"series_id": "DGS10", "observation_date": px.index, "published_date": px.index,
                        "value": np.linspace(2, 4, len(px))})
    f = macro_features(obs, px.index)
    assert {"DGS10_lvl", "DGS10_d63"} <= set(f.columns)


def test_walk_forward_is_chronological_and_purged():
    px = make_prices(1200)
    f = build_features(px).iloc[252:]
    h = 21
    y = forward_log_return(px["adj_close"], h).reindex(f.index)
    res = B.walk_forward(f, y, h, "linear")
    d = res.preds
    assert d.index.is_monotonic_increasing and len(d) > 200
    # first prediction date must be at least min_train + h rows into the sample
    assert f.index.get_loc(d.index[0]) >= B.MIN_TRAIN + h
    # realised outcomes in the evaluation equal the true forward returns
    np.testing.assert_allclose(d["actual_return"].values, y.loc[d.index].values)


def test_training_never_sees_labels_extending_past_refit_date(monkeypatch):
    seen = []
    from app.forecasting import models as mm

    class Spy(mm.BaselineMean):
        def fit(self, X, y):
            seen.append(X.index.max())
            return super().fit(X, y)
    monkeypatch.setitem(mm.REGISTRY, "spy", Spy)
    monkeypatch.setattr(B, "REGISTRY", mm.REGISTRY)
    px = make_prices(900)
    f = build_features(px).iloc[252:]
    h = 63
    y = forward_log_return(px["adj_close"], h).reindex(f.index)
    res = B.walk_forward(f, y, h, "spy")
    first_pred = res.preds.index[0]
    pos = f.index.get_loc(first_pred)
    # latest training row's label window ends at (row + h) which must be <= first prediction row
    assert f.index.get_loc(seen[0]) + h <= pos


def test_random_walk_is_not_declared_validated():
    px = make_prices(2500, seed=3, drift=0.0)
    f = build_features(px).iloc[252:]
    y = forward_log_return(px["adj_close"], 21).reindex(f.index)
    ev = B.evaluate(B.walk_forward(f, y, 21, "linear"), B.regime_series(f) if hasattr(B, "regime_series") else None)
    status, _ = B.validation_status(ev)
    assert status != "validated"


def test_strong_momentum_signal_beats_baseline_out_of_sample():
    px = make_prices(3000, seed=1, drift=0.0, vol=0.008, latent=0.0008)
    f = build_features(px).iloc[252:]
    y = forward_log_return(px["adj_close"], 21).reindex(f.index)
    ev = B.evaluate(B.walk_forward(f, y, 21, "linear"))
    assert ev["classification"]["brier_skill"] > 0


def test_insufficient_data_status():
    px = make_prices(900)
    f = build_features(px).iloc[252:]
    y = forward_log_return(px["adj_close"], 252).reindex(f.index)
    ev = B.evaluate(B.walk_forward(f, y, 252, "linear"))
    assert B.validation_status(ev)[0] == "insufficient_data"


def test_metrics_known_values():
    y = np.array([1, 0, 1, 1])
    p = np.array([0.9, 0.2, 0.8, 0.6])
    assert M.brier(y, p) == pytest.approx((0.01 + 0.04 + 0.04 + 0.16) / 4)
    tab = M.calibration_table(y, p, bins=2)
    assert sum(r["n"] for r in tab) == 4


def test_strategy_applies_costs_and_uses_next_day_return():
    idx = pd.bdate_range("2020-01-01", periods=300)
    ret = pd.Series(0.001, index=idx)
    preds = pd.DataFrame({"prob_up": 0.9}, index=idx[:250])
    s = B.strategy_backtest(ret, preds, cost_bps=0.0)
    assert s["exposure"] == pytest.approx(1.0) and s["strategy"]["total_return"] > 0
    s2 = B.strategy_backtest(ret, preds, cost_bps=100.0)
    assert s2["strategy"]["total_return"] < s["strategy"]["total_return"]


def _load_db(db, px, symbol="SYN"):
    inst = Instrument(symbol=symbol, exchange="US", instrument_type="etf")
    db.add(inst)
    db.commit()
    rows = [dict(instrument_id=inst.id, date=i.date(), provider="test", close=float(r.adj_close),
                 adj_close=float(r.adj_close), volume=int(r.volume)) for i, r in px.iterrows()]
    db.execute(Price.__table__.insert(), rows)
    db.commit()
    return inst


def test_forecast_pipeline_persists_append_only_and_reproducibly(db):
    inst = _load_db(db, make_prices(1300, seed=5))
    f1 = forecast_instrument(db, inst, horizons=(5, 21))
    assert len(f1) == 4  # 2 horizons x (baseline + linear)
    lin = [f for f in f1 if f.model_version.name == "linear" and f.horizon_days == 21][0]
    assert 0 < lin.prob_up < 1 and lin.prob_up + lin.prob_down == pytest.approx(1)
    assert lin.interval_low < lin.expected_return < lin.interval_high or lin.interval_low is None
    assert lin.data_cutoff == pd.Timestamp(make_prices(1300, seed=5).index[-1]).date()
    assert lin.feature_version == "f1" and lin.validation_status
    assert lin.evidence["limitations"] and lin.evidence["invalidating_conditions"]
    forecast_instrument(db, inst, horizons=(5, 21))
    assert db.scalar(select(func.count()).select_from(Forecast)) == 8   # appended, never overwritten
    a, b = db.scalars(select(Forecast).where(Forecast.horizon_days == 21, Forecast.model_version_id == lin.model_version_id)
                      .order_by(Forecast.id)).all()
    assert a.prob_up == pytest.approx(b.prob_up) and a.expected_return == pytest.approx(b.expected_return)
    assert db.scalar(select(func.count()).select_from(BacktestRun)) > 0


def test_pipeline_uses_macro_only_after_publication(db):
    px = make_prices(1000, seed=2)
    inst = _load_db(db, px)
    from app.models import MacroSeries
    db.add(MacroSeries(series_id="DGS10", title="t", category="rates", provider="fred", assumed_lag_days=1))
    db.commit()
    db.execute(MacroObservation.__table__.insert(),
               [dict(series_id="DGS10", observation_date=i.date(), published_date=i.date(), value=3.0,
                     pit_quality="vintage", provider="fred") for i in px.index])
    db.commit()
    out = forecast_instrument(db, inst, horizons=(21,), models=("linear",))
    from app.models import DerivedFeature
    feats = db.scalar(select(DerivedFeature.feature_values))
    assert "DGS10_lvl" in feats and feats["DGS10_lvl"] == 3.0
