"""Orchestration: DB -> features -> walk-forward backtest -> final fit -> append-only persistence."""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecasting import backtest as B
from app.forecasting.features import FEATURE_VERSION, HORIZONS, build_features, forward_log_return
from app.forecasting.models import MODEL_VERSION, PRIMARY, REGISTRY
from app.ingestion.common import upsert
from app.models import (BacktestPrediction, BacktestRun, DerivedFeature, Forecast, Instrument,
                        MacroObservation, ModelVersion, Price)

log = logging.getLogger(__name__)
INTERVAL_LEVEL = 0.90
MIN_RESIDUALS = 100


def load_prices(db: Session, instrument_id: int) -> pd.DataFrame:
    rows = db.execute(select(Price.date, Price.provider, Price.adj_close, Price.close, Price.volume)
                      .where(Price.instrument_id == instrument_id)).all()
    if not rows:
        return pd.DataFrame(columns=["adj_close", "volume"])
    df = pd.DataFrame(rows, columns=["date", "provider", "adj_close", "close", "volume"])
    # prefer yahoo (has adjusted close); otherwise fall back to close
    df["pref"] = (df["provider"] != "yahoo").astype(int)
    df = df.sort_values(["date", "pref"]).drop_duplicates("date")
    df["adj_close"] = df["adj_close"].fillna(df["close"])
    df.index = pd.to_datetime(df["date"])
    return df[["adj_close", "volume"]].sort_index()


def load_macro(db: Session) -> pd.DataFrame:
    rows = db.execute(select(MacroObservation.series_id, MacroObservation.observation_date,
                             MacroObservation.published_date, MacroObservation.value)).all()
    df = pd.DataFrame(rows, columns=["series_id", "observation_date", "published_date", "value"])
    for c in ("observation_date", "published_date"):
        df[c] = pd.to_datetime(df[c])
    return df


def get_model_version(db: Session, name: str) -> ModelVersion:
    mv = db.scalar(select(ModelVersion).where(ModelVersion.name == name, ModelVersion.version == MODEL_VERSION,
                                              ModelVersion.feature_version == FEATURE_VERSION))
    if mv is None:
        cls = REGISTRY[name]
        mv = ModelVersion(name=name, version=MODEL_VERSION, feature_version=FEATURE_VERSION,
                          params=dict(cls.params), description=(cls.__doc__ or "").strip().split("\n")[0])
        db.add(mv)
        db.flush()
    return mv


def regime_series(feats: pd.DataFrame) -> pd.Series:
    """Trend regime from the 200-day moving-average ratio (known at t)."""
    r = pd.Series(np.where(feats["ma200_ratio"] >= 0, "uptrend", "downtrend"), index=feats.index)
    return r.where(feats["ma200_ratio"].notna())


def _interval(last_log_mu: float, resid: np.ndarray, est_vol_ann: float | None, h: int):
    lo_q, hi_q = (1 - INTERVAL_LEVEL) / 2, 1 - (1 - INTERVAL_LEVEL) / 2
    if len(resid) >= MIN_RESIDUALS:
        lo, hi = np.quantile(resid, [lo_q, hi_q])
        method = (f"{int(INTERVAL_LEVEL*100)}% interval from empirical quantiles of {len(resid)} walk-forward "
                  "out-of-sample residuals (overlapping windows; approximate coverage)")
        return last_log_mu + lo, last_log_mu + hi, method
    if est_vol_ann and not np.isnan(est_vol_ann):
        from statistics import NormalDist
        z = NormalDist().inv_cdf(hi_q)
        s = est_vol_ann * np.sqrt(h / 252)
        return last_log_mu - z * s, last_log_mu + z * s, \
            "UNVALIDATED volatility-scaled normal approximation (insufficient out-of-sample residuals)"
    return None, None, None


def ewma_vol(px: pd.Series, lam: float = 0.94) -> float | None:
    r = np.log(px).diff().dropna()
    if len(r) < 30:
        return None
    var = r.iloc[:30].var()
    for x in r.iloc[30:]:
        var = lam * var + (1 - lam) * x * x
    return float(np.sqrt(var * 252))


def forecast_instrument(db: Session, inst: Instrument, horizons=tuple(HORIZONS), models=("baseline_mean", PRIMARY),
                        market: pd.Series | None = None, macro: pd.DataFrame | None = None,
                        store_backtest: bool = True) -> list[Forecast]:
    px = load_prices(db, inst.id)
    if len(px) < 300:
        log.info("%s: only %d price rows; skipping", inst.symbol, len(px))
        return []
    macro = load_macro(db) if macro is None else macro
    feats = build_features(px, macro, market if inst.symbol != "SPY" else None)
    feats = feats.iloc[252:] if len(feats) > 600 else feats  # drop warm-up rows lacking long lookbacks
    cutoff: date = px.index[-1].date()
    out: list[Forecast] = []
    daily_ret = px["adj_close"].pct_change()
    for h in horizons:
        y = forward_log_return(px["adj_close"], h).reindex(feats.index)
        runs: dict[str, tuple[dict, str, list[str], B.WalkForwardResult]] = {}
        for m in models:
            wf = B.walk_forward(feats, y, h, m)
            ev = B.evaluate(wf, regime_series(feats))
            status, reasons = B.validation_status(ev)
            runs[m] = (ev, status, reasons, wf)
            if store_backtest and ev["n_obs"]:
                _store_backtest(db, inst, h, m, wf, ev, status, reasons, cutoff, daily_ret if m == PRIMARY else None)
        # final fit on all rows whose label has elapsed
        lab = y.notna()
        x_now = feats.iloc[[-1]]
        vol_hist = float(feats["vol_63"].iloc[-1]) if "vol_63" in feats and not np.isnan(feats["vol_63"].iloc[-1]) else None
        vol_est = ewma_vol(px["adj_close"])
        for m in models:
            ev, status, reasons, wf = runs[m]
            model = REGISTRY[m]().fit(feats[lab], y[lab].values)
            p, mu = model.predict(x_now)
            p, mu = float(np.clip(p[0], 0.01, 0.99)), float(mu[0])
            resid = (wf.preds["actual_return"] - wf.preds["pred_return"]).values if len(wf.preds) else np.array([])
            lo, hi, method = _interval(mu, resid, vol_est, h)
            expl = model.explain(x_now.iloc[0])
            evidence = _evidence(expl, ev, status, reasons, x_now.iloc[0], h)
            mv = get_model_version(db, m)
            f = Forecast(instrument_id=inst.id, model_version_id=mv.id, data_cutoff=cutoff, horizon_days=h,
                         expected_return=float(np.expm1(mu)), prob_up=p, prob_down=1 - p,
                         interval_low=float(np.expm1(lo)) if lo is not None else None,
                         interval_high=float(np.expm1(hi)) if hi is not None else None,
                         interval_level=INTERVAL_LEVEL if lo is not None else None, interval_method=method,
                         hist_vol_ann=vol_hist, est_vol_ann=vol_est, feature_version=FEATURE_VERSION,
                         validation_status=status if m != "baseline_mean" else "baseline",
                         evidence=evidence)
            db.add(f)
            out.append(f)
        upsert(db, DerivedFeature.__table__,
               [dict(instrument_id=inst.id, asof_date=cutoff, feature_version=FEATURE_VERSION,
                     feature_values={k: (None if pd.isna(v) else float(v)) for k, v in x_now.iloc[0].items()})],
               ["instrument_id", "asof_date", "feature_version"], ["feature_values"])
    db.commit()
    return out


def _evidence(expl: list[dict], ev: dict, status: str, reasons: list[str], x: pd.Series, h: int) -> dict:
    bullish = [e for e in expl if (e.get("contribution") or 0) > 0][:4]
    bearish = [e for e in expl if (e.get("contribution") or 0) < 0][:4]
    limits = ["Model uses price/volume and macro features only; fundamentals and news are not model inputs.",
              f"Overlapping {h}-day windows mean ~{ev['effective_n']:.0f} effective independent test observations.",
              "Past out-of-sample behaviour does not guarantee future performance; regimes change."]
    invalid = []
    if "vol_21" in x and not pd.isna(x["vol_21"]):
        invalid.append("A sharp change in realised volatility versus its recent level would make the "
                       "forecast distribution unrepresentative.")
    invalid.append("Material new information (earnings, policy shocks, corporate actions) after the data cutoff.")
    if status != "validated":
        limits.insert(0, f"Validation status '{status}': " + " ".join(reasons))
    return {"bullish": bullish, "bearish": bearish, "limitations": limits, "invalidating_conditions": invalid,
            "validation_reasons": reasons,
            "backtest": {k: ev.get(k) for k in ("n_obs", "start_date", "end_date", "effective_n")}
            | {"brier_skill": (ev["classification"] or {}).get("brier_skill"),
               "ece": (ev["classification"] or {}).get("ece")}}


def _store_backtest(db: Session, inst: Instrument, h: int, model_name: str, wf: B.WalkForwardResult,
                    ev: dict, status: str, reasons: list[str], cutoff: date, daily_ret) -> None:
    mv = get_model_version(db, model_name)
    strat = B.strategy_backtest(daily_ret, wf.preds) if daily_ret is not None else None
    run = BacktestRun(instrument_id=inst.id, model_version_id=mv.id, horizon_days=h, data_cutoff=cutoff,
                      n_obs=ev["n_obs"], start_date=pd.Timestamp(ev["start_date"]).date(),
                      end_date=pd.Timestamp(ev["end_date"]).date(), config=wf.config,
                      metrics={k: ev.get(k) for k in ("classification", "regression", "by_regime",
                                                      "effective_n", "brier_skill_halves")},
                      calibration=ev["calibration"], strategy=strat, validation_status=status,
                      validation_reasons=reasons)
    db.add(run)
    db.flush()
    if daily_ret is not None:  # keep primary-model predictions (thinned: every 5th date) for plotting
        thin = wf.preds.iloc[::5]
        db.add_all([BacktestPrediction(backtest_run_id=run.id, asof_date=i.date(), prob_up=float(r.prob_up),
                                       baseline_prob_up=float(r.baseline_prob_up), pred_return=float(r.pred_return),
                                       baseline_return=float(r.baseline_return), actual_return=float(r.actual_return))
                    for i, r in thin.iterrows()])


def forecast_all(db: Session, symbols: list[str] | None = None, horizons=tuple(HORIZONS)) -> int:
    market = None
    spy = db.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    if spy is not None:
        mp = load_prices(db, spy.id)
        market = mp["adj_close"] if len(mp) else None
    macro = load_macro(db)
    q = select(Instrument).where(Instrument.instrument_type.in_(["stock", "etf"]))
    if symbols:
        q = q.where(Instrument.symbol.in_(symbols))
    n = 0
    for inst in db.scalars(q).all():
        try:
            n += len(forecast_instrument(db, inst, horizons, market=market, macro=macro))
        except Exception:
            db.rollback()
            log.exception("forecast failed for %s", inst.symbol)
    return n
