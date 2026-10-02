from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis import fundamentals as fa
from app.analysis import macro as ma
from app.analysis import scenarios as sc
from app.api_common import ApiError, horizon_label, is_stale, limiter
from app.db import get_db
from app.forecasting.features import HORIZONS
from app.forecasting.models import PRIMARY
from app.models import (BacktestPrediction, BacktestRun, Forecast, IngestionRun, Instrument, MacroObservation,
                        MacroSeries, ModelVersion, Price)
from app.schemas import (AssetOut, BacktestSummary, ForecastOut, Page, PricePoint, PriceSeries, ScreenerRow)

router = APIRouter()


def _inst(db: Session, asset_id: int) -> Instrument:
    i = db.get(Instrument, asset_id)
    if i is None:
        raise ApiError(404, "not_found", f"Asset {asset_id} not found")
    return i


# ------------------------------------------------------------------ status
@router.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "database": "ok"}


@router.get("/status", tags=["system"])
def status(db: Session = Depends(get_db)):
    """Data freshness and provider health, derived only from recorded ingestion runs and stored data."""
    providers = []
    for (p,) in db.execute(select(IngestionRun.provider).distinct()):
        last_ok = db.scalar(select(func.max(IngestionRun.finished_at)).where(
            IngestionRun.provider == p, IngestionRun.status.in_(["ok", "partial"])))
        last = db.execute(select(IngestionRun).where(IngestionRun.provider == p)
                          .order_by(IngestionRun.id.desc()).limit(1)).scalar_one()
        fails = db.scalar(select(func.count()).select_from(IngestionRun).where(
            IngestionRun.provider == p, IngestionRun.status == "failed",
            IngestionRun.started_at > func.now() - timedelta(days=1)))
        ok24 = db.scalar(select(func.count()).select_from(IngestionRun).where(
            IngestionRun.provider == p, IngestionRun.status.in_(["ok", "partial"]),
            IngestionRun.started_at > func.now() - timedelta(days=1)))
        providers.append({"provider": p, "last_success": last_ok, "last_run_status": last.status,
                          "last_error": last.error if last.status == "failed" else None,
                          "failures_24h": fails, "successes_24h": ok24})
    last_price = db.scalar(select(func.max(Price.date)))
    last_macro = db.scalar(select(func.max(MacroObservation.observation_date)))
    return {"providers": providers,
            "counts": {"instruments": db.scalar(select(func.count()).select_from(Instrument)),
                       "instruments_with_prices": db.scalar(select(func.count(func.distinct(Price.instrument_id)))),
                       "price_rows": db.scalar(select(func.count()).select_from(Price)),
                       "macro_series": db.scalar(select(func.count()).select_from(MacroSeries)),
                       "forecasts": db.scalar(select(func.count()).select_from(Forecast)),
                       "backtests": db.scalar(select(func.count()).select_from(BacktestRun))},
            "latest_price_date": last_price, "latest_macro_observation": last_macro,
            "prices_stale": is_stale(last_price),
            "empty": last_price is None,
            "message": "No market data has been ingested yet. Run the ingestion job (see README)." if last_price is None else None}


# ------------------------------------------------------------------ assets
@router.get("/assets", response_model=Page[AssetOut], tags=["assets"])
def search_assets(q: str | None = None, type: str | None = None, sector: str | None = None,
                  exchange: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    stmt = select(Instrument)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Instrument.symbol.ilike(like), Instrument.name.ilike(like)))
    if type:
        stmt = stmt.where(Instrument.instrument_type == type)
    if sector:
        stmt = stmt.where(Instrument.sector.ilike(f"%{sector}%"))
    if exchange:
        stmt = stmt.where(Instrument.exchange == exchange)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    # exact ticker matches first
    order = [(Instrument.symbol == (q or "").upper()).desc(), Instrument.symbol]
    items = db.scalars(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/assets/{asset_id}", response_model=AssetOut, tags=["assets"])
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    return _inst(db, asset_id)


@router.get("/assets/{asset_id}/prices", response_model=PriceSeries, tags=["assets"])
def get_prices(asset_id: int, start: date | None = None, end: date | None = None,
               limit: int = Query(5000, ge=1, le=20000), db: Session = Depends(get_db)):
    inst = _inst(db, asset_id)
    stmt = select(Price).where(Price.instrument_id == asset_id)
    if start:
        stmt = stmt.where(Price.date >= start)
    if end:
        stmt = stmt.where(Price.date <= end)
    rows = db.scalars(stmt.order_by(Price.date.desc()).limit(limit)).all()[::-1]
    # one row per date (prefer yahoo)
    seen: dict = {}
    for r in rows:
        if r.date not in seen or r.provider == "yahoo":
            seen[r.date] = r
    rows = [seen[k] for k in sorted(seen)]
    last = rows[-1].date if rows else None
    return PriceSeries(instrument_id=asset_id, symbol=inst.symbol, count=len(rows), last_date=last,
                       last_ingested_at=max((r.ingested_at for r in rows), default=None), stale=is_stale(last),
                       prices=[PricePoint.model_validate(r, from_attributes=True) for r in rows])


@router.get("/assets/{asset_id}/fundamentals", tags=["assets"])
def get_fundamentals(asset_id: int, db: Session = Depends(get_db)):
    inst = _inst(db, asset_id)
    m = fa.annual_metrics(db, asset_id)
    if inst.instrument_type != "stock":
        m["warnings"].append(f"Company fundamentals do not apply to instrument type '{inst.instrument_type}'.")
    return {"instrument_id": asset_id, "symbol": inst.symbol, "cik": inst.cik, **m,
            "valuation": fa.valuation(db, asset_id, m) if inst.instrument_type == "stock" else None}


@router.get("/assets/{asset_id}/etf", tags=["assets"])
def get_etf_info(asset_id: int, db: Session = Depends(get_db)):
    inst = _inst(db, asset_id)
    px = pd.DataFrame(db.execute(select(Price.date, Price.adj_close, Price.close).where(
        Price.instrument_id == asset_id).order_by(Price.date)).all(), columns=["date", "adj", "close"])
    risk = None
    if len(px) > 260:
        s = (px["adj"].fillna(px["close"]))
        r = np.log(s).diff().dropna()
        eq = s / s.cummax() - 1
        risk = {"ann_vol_1y": float(r.iloc[-252:].std() * np.sqrt(252)), "max_drawdown_full_history": float(eq.min()),
                "current_drawdown": float(eq.iloc[-1]), "worst_day": float(r.min()), "obs": int(len(r))}
    return {"instrument_id": asset_id, "symbol": inst.symbol, "instrument_type": inst.instrument_type,
            "category": inst.sector, "risk": risk,
            "holdings": None, "sector_exposure": None, "geographic_exposure": None, "expense_ratio": None,
            "unavailable_reason": "Holdings, exposures and expense ratios are not provided by any integrated free "
                                  "provider (Yahoo chart / SEC company facts). Fund issuers publish them; an "
                                  "issuer-file adapter is a planned extension. Values are intentionally not guessed.",
            "currency": inst.currency}


@router.get("/assets/{asset_id}/scenarios", tags=["assets"])
def get_scenarios(asset_id: int, db: Session = Depends(get_db)):
    return sc.sensitivities(db, _inst(db, asset_id))


# ------------------------------------------------------------------ forecasts
def _fc_out(f: Forecast, symbol: str | None = None, with_evidence: bool = False) -> ForecastOut:
    return ForecastOut(id=f.id, instrument_id=f.instrument_id, symbol=symbol, horizon_days=f.horizon_days,
                       horizon_label=horizon_label(f.horizon_days), model_name=f.model_version.name,
                       model_version=f.model_version.version, feature_version=f.feature_version,
                       created_at=f.created_at, data_cutoff=f.data_cutoff, expected_return=f.expected_return,
                       prob_up=f.prob_up, prob_down=f.prob_down, interval_low=f.interval_low,
                       interval_high=f.interval_high, interval_level=f.interval_level,
                       interval_method=f.interval_method, hist_vol_ann=f.hist_vol_ann, est_vol_ann=f.est_vol_ann,
                       validation_status=f.validation_status, evidence=f.evidence if with_evidence else None)


def _latest_forecasts(db: Session, model: str = PRIMARY, horizon: int | None = None):
    mv = db.scalars(select(ModelVersion.id).where(ModelVersion.name == model)).all()
    sub = select(Forecast.instrument_id, Forecast.horizon_days, func.max(Forecast.id).label("mid")) \
        .where(Forecast.model_version_id.in_(mv)).group_by(Forecast.instrument_id, Forecast.horizon_days).subquery()
    stmt = select(Forecast).join(sub, Forecast.id == sub.c.mid)
    if horizon:
        stmt = stmt.where(Forecast.horizon_days == horizon)
    return stmt


@router.get("/assets/{asset_id}/forecasts", response_model=list[ForecastOut], tags=["forecasts"])
def asset_forecasts(asset_id: int, model: str = PRIMARY, db: Session = Depends(get_db)):
    inst = _inst(db, asset_id)
    rows = db.scalars(_latest_forecasts(db, model).where(Forecast.instrument_id == asset_id)
                      .order_by(Forecast.horizon_days)).all()
    return [_fc_out(f, inst.symbol, with_evidence=True) for f in rows]


@router.get("/forecasts", response_model=Page[ForecastOut], tags=["forecasts"])
def list_forecasts(horizon: int | None = None, status: str | None = None, model: str = PRIMARY,
                   symbol: str | None = None, history: bool = False, limit: int = Query(100, ge=1, le=500),
                   offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Latest forecast per asset/horizon by default; history=true lists every stored forecast (append-only)."""
    if history:
        mv = db.scalars(select(ModelVersion.id).where(ModelVersion.name == model)).all()
        stmt = select(Forecast).where(Forecast.model_version_id.in_(mv))
        if horizon:
            stmt = stmt.where(Forecast.horizon_days == horizon)
    else:
        stmt = _latest_forecasts(db, model, horizon)
    if status:
        stmt = stmt.where(Forecast.validation_status == status)
    if symbol:
        stmt = stmt.join(Instrument, Instrument.id == Forecast.instrument_id).where(Instrument.symbol == symbol.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Forecast.created_at.desc(), Forecast.id.desc()).limit(limit).offset(offset)).all()
    syms = {i.id: i.symbol for i in db.scalars(select(Instrument).where(Instrument.id.in_({r.instrument_id for r in rows})))}
    return Page(items=[_fc_out(f, syms.get(f.instrument_id)) for f in rows], total=total, limit=limit, offset=offset)


@router.get("/forecasts/{forecast_id}", response_model=ForecastOut, tags=["forecasts"])
def get_forecast(forecast_id: int, db: Session = Depends(get_db)):
    f = db.get(Forecast, forecast_id)
    if f is None:
        raise ApiError(404, "not_found", f"Forecast {forecast_id} not found")
    return _fc_out(f, db.get(Instrument, f.instrument_id).symbol, with_evidence=True)


# ------------------------------------------------------------------ screener
_cache: dict = {}


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _cache[key] = (time.monotonic(), v)
    return v


@router.get("/screener", response_model=Page[ScreenerRow], tags=["screener"])
def screener(horizon: int = 21, q: str | None = None, type: str | None = None, sector: str | None = None,
             sort: str = "symbol", order: str = "asc", limit: int = Query(100, ge=1, le=300),
             offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Sorting by forecast fields is a convenience, not a ranking of suitability."""
    if horizon not in HORIZONS:
        raise ApiError(422, "bad_horizon", f"horizon must be one of {sorted(HORIZONS)}")
    stmt = select(Instrument).where(Instrument.instrument_type.in_(["stock", "etf", "mutual_fund"]))
    if q:
        stmt = stmt.where(or_(Instrument.symbol.ilike(f"%{q}%"), Instrument.name.ilike(f"%{q}%")))
    if type:
        stmt = stmt.where(Instrument.instrument_type == type)
    if sector:
        stmt = stmt.where(Instrument.sector.ilike(f"%{sector}%"))
    insts = db.scalars(stmt).all()
    ids = [i.id for i in insts]
    since = date.today() - timedelta(days=420)
    pr = pd.DataFrame(db.execute(select(Price.instrument_id, Price.date, Price.close, Price.adj_close, Price.provider)
                                 .where(Price.instrument_id.in_(ids), Price.date >= since)).all(),
                      columns=["id", "date", "close", "adj", "provider"])
    fcs = {f.instrument_id: f for f in db.scalars(_latest_forecasts(db, PRIMARY, horizon).where(Forecast.instrument_id.in_(ids)))}
    rows = []
    for i in insts:
        p = pr[pr["id"] == i.id].sort_values(["date", "provider"]).drop_duplicates("date", keep="first")
        s = p.set_index("date")["adj"].fillna(p.set_index("date")["close"]) if len(p) else pd.Series(dtype=float)

        def ret(n):
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None
        val, g = {}, {}
        if i.instrument_type == "stock":
            m = _cached(("fund", i.id), 120, lambda: fa.annual_metrics(db, i.id))
            if m["periods"]:
                g = m["periods"][-1]["metrics"]
                val = _cached(("val", i.id), 120, lambda: fa.valuation(db, i.id, m))
        f = fcs.get(i.id)
        rows.append(ScreenerRow(
            id=i.id, symbol=i.symbol, name=i.name, instrument_type=i.instrument_type, sector=i.sector,
            price=float(p["close"].iloc[-1]) if len(p) else None, price_date=p["date"].iloc[-1] if len(p) else None,
            ret_1d=ret(1), ret_1m=ret(21), ret_3m=ret(63), ret_1y=ret(252), pe=val.get("pe"), ps=val.get("ps"),
            revenue_growth=g.get("revenue_growth"), net_income_growth=g.get("net_income_growth"),
            forecast_horizon_days=horizon, forecast_id=f.id if f else None, prob_up=f.prob_up if f else None,
            expected_return=f.expected_return if f else None, interval_low=f.interval_low if f else None,
            interval_high=f.interval_high if f else None, validation_status=f.validation_status if f else None,
            data_cutoff=f.data_cutoff if f else None))
    if sort not in ScreenerRow.model_fields:
        raise ApiError(422, "bad_sort", f"unknown sort field {sort}")
    rows.sort(key=lambda r: (getattr(r, sort) is None, getattr(r, sort)), reverse=False)
    if order == "desc":
        have = [r for r in rows if getattr(r, sort) is not None][::-1]
        rows = have + [r for r in rows if getattr(r, sort) is None]
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


# ------------------------------------------------------------------ macro
KEY_OVERVIEW = ["DFF", "DGS2", "DGS10", "T10Y2Y", "DFII10", "T10YIE", "BAMLH0A0HYM2", "DTWEXBGS", "VIXCLS",
                "UNRATE", "CPIAUCSL", "NFCI"]


@router.get("/macro/series", tags=["macro"])
def macro_series(db: Session = Depends(get_db)):
    out = []
    for s in db.scalars(select(MacroSeries).order_by(MacroSeries.category, MacroSeries.series_id)):
        last = db.execute(select(MacroObservation.observation_date, MacroObservation.published_date, MacroObservation.value)
                          .where(MacroObservation.series_id == s.series_id)
                          .order_by(MacroObservation.observation_date.desc(), MacroObservation.published_date.desc()).limit(1)).first()
        out.append({"series_id": s.series_id, "title": s.title, "category": s.category, "units": s.units,
                    "frequency": s.frequency, "latest_observation_date": last[0] if last else None,
                    "latest_published_date": last[1] if last else None, "latest_value": last[2] if last else None})
    return out


@router.get("/macro/series/{series_id}", tags=["macro"])
def macro_observations(series_id: str, start: date | None = None, limit: int = Query(5000, ge=1, le=50000),
                       db: Session = Depends(get_db)):
    s = db.get(MacroSeries, series_id)
    if s is None:
        raise ApiError(404, "not_found", f"Series {series_id} not ingested")
    stmt = select(MacroObservation).where(MacroObservation.series_id == series_id)
    if start:
        stmt = stmt.where(MacroObservation.observation_date >= start)
    rows = db.scalars(stmt.order_by(MacroObservation.observation_date.desc(), MacroObservation.published_date.desc()).limit(limit * 2)).all()
    latest: dict = {}
    for r in rows:  # latest vintage per observation date
        latest.setdefault(r.observation_date, r)
    obs = [{"observation_date": k, "published_date": v.published_date, "value": v.value, "pit_quality": v.pit_quality,
            "ingested_at": v.ingested_at} for k, v in sorted(latest.items())][-limit:]
    return {"series_id": series_id, "title": s.title, "units": s.units, "frequency": s.frequency,
            "provider": s.provider, "note": "Latest vintage per observation. pit_quality='assumed_lag' means the "
            "publication date is estimated, not an official release date.", "observations": obs}


@router.get("/macro/pillars", tags=["macro"])
def macro_pillars(db: Session = Depends(get_db)):
    return ma.pillar_scores(db)


@router.get("/macro/overview", tags=["macro"])
def macro_overview(db: Session = Depends(get_db)):
    return ma.latest_values(db, KEY_OVERVIEW)


@router.get("/overview", tags=["macro"])
def market_overview(db: Session = Depends(get_db)):
    """Indices, gold/silver proxies and bond/credit ETFs with latest close and returns (stored data only)."""
    wanted = ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX", "GLD", "SLV", "TLT", "HYG"]
    out = []
    for sym in wanted:
        i = db.scalar(select(Instrument).where(Instrument.symbol == sym))
        if i is None:
            continue
        rows = db.execute(select(Price.date, Price.close, Price.ingested_at).where(Price.instrument_id == i.id)
                          .order_by(Price.date.desc()).limit(300)).all()
        if not rows:
            out.append({"symbol": sym, "name": i.name, "available": False})
            continue
        c = [r[1] for r in rows]
        def r_(n): return c[0] / c[n] - 1 if len(c) > n else None
        out.append({"symbol": sym, "id": i.id, "name": i.name, "type": i.instrument_type, "available": True,
                    "last": c[0], "date": rows[0][0], "ingested_at": rows[0][2], "stale": is_stale(rows[0][0]),
                    "ret_1d": r_(1), "ret_1m": r_(21), "ret_1y": r_(252)})
    return {"markets": out, "note": "Gold/silver shown via GLD/SLV ETF proxies. Market breadth is not available from integrated providers."}


# ------------------------------------------------------------------ backtests & models
def _bt_summary(b: BacktestRun, sym: str) -> BacktestSummary:
    c = (b.metrics or {}).get("classification") or {}
    r = (b.metrics or {}).get("regression") or {}
    return BacktestSummary(id=b.id, instrument_id=b.instrument_id, symbol=sym, model_name=b.model_version.name,
                           model_version=b.model_version.version, horizon_days=b.horizon_days, created_at=b.created_at,
                           data_cutoff=b.data_cutoff, n_obs=b.n_obs, start_date=b.start_date, end_date=b.end_date,
                           validation_status=b.validation_status, validation_reasons=b.validation_reasons,
                           brier=c.get("brier"), brier_baseline=c.get("brier_baseline"), brier_skill=c.get("brier_skill"),
                           log_loss=c.get("log_loss"), ece=c.get("ece"), balanced_accuracy=c.get("balanced_accuracy"),
                           directional_accuracy=c.get("directional_accuracy"), mae=r.get("mae"),
                           mae_baseline=r.get("mae_baseline"), rmse=r.get("rmse"))


@router.get("/backtests", response_model=Page[BacktestSummary], tags=["backtests"])
def list_backtests(symbol: str | None = None, horizon: int | None = None, model: str | None = None,
                   latest_only: bool = True, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db)):
    stmt = select(BacktestRun).join(ModelVersion, ModelVersion.id == BacktestRun.model_version_id)
    if latest_only:
        sub = select(func.max(BacktestRun.id)).group_by(BacktestRun.instrument_id, BacktestRun.horizon_days,
                                                         BacktestRun.model_version_id)
        stmt = stmt.where(BacktestRun.id.in_(sub))
    if symbol:
        stmt = stmt.join(Instrument, Instrument.id == BacktestRun.instrument_id).where(Instrument.symbol == symbol.upper())
    if horizon:
        stmt = stmt.where(BacktestRun.horizon_days == horizon)
    if model:
        stmt = stmt.where(ModelVersion.name == model)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(BacktestRun.id.desc()).limit(limit).offset(offset)).all()
    syms = {i.id: i.symbol for i in db.scalars(select(Instrument).where(Instrument.id.in_({r.instrument_id for r in rows})))}
    return Page(items=[_bt_summary(b, syms[b.instrument_id]) for b in rows], total=total, limit=limit, offset=offset)


@router.get("/backtests/summary", tags=["backtests"])
def backtest_summary(model: str = PRIMARY, db: Session = Depends(get_db)):
    """Per-horizon aggregate across assets (latest run per asset/horizon), with status counts."""
    sub = select(func.max(BacktestRun.id)).group_by(BacktestRun.instrument_id, BacktestRun.horizon_days,
                                                     BacktestRun.model_version_id)
    runs = db.scalars(select(BacktestRun).join(ModelVersion).where(BacktestRun.id.in_(sub), ModelVersion.name == model)).all()
    out = {}
    for h in sorted({r.horizon_days for r in runs}):
        rs = [r for r in runs if r.horizon_days == h]
        sk = [r.metrics["classification"]["brier_skill"] for r in rs if (r.metrics or {}).get("classification")]
        ece = [r.metrics["classification"]["ece"] for r in rs if (r.metrics or {}).get("classification")]
        counts: dict = {}
        for r in rs:
            counts[r.validation_status] = counts.get(r.validation_status, 0) + 1
        out[h] = {"horizon_label": horizon_label(h), "n_assets": len(rs), "status_counts": counts,
                  "median_brier_skill": float(np.median(sk)) if sk else None,
                  "share_beating_baseline": float(np.mean([s > 0 for s in sk])) if sk else None,
                  "median_ece": float(np.median(ece)) if ece else None,
                  "total_oos_obs": int(sum(r.n_obs for r in rs))}
    return {"model": model, "horizons": out,
            "note": "All figures are out-of-sample walk-forward. 'share_beating_baseline' near 50% indicates no consistent edge."}


@router.get("/backtests/{run_id}", tags=["backtests"])
def get_backtest(run_id: int, db: Session = Depends(get_db)):
    b = db.get(BacktestRun, run_id)
    if b is None:
        raise ApiError(404, "not_found", f"Backtest {run_id} not found")
    preds = db.scalars(select(BacktestPrediction).where(BacktestPrediction.backtest_run_id == run_id)
                       .order_by(BacktestPrediction.asof_date)).all()
    sym = db.get(Instrument, b.instrument_id).symbol
    return {"summary": _bt_summary(b, sym), "config": b.config, "metrics": b.metrics, "calibration": b.calibration,
            "strategy": b.strategy, "out_of_sample": True,
            "predictions": [{"asof_date": p.asof_date, "prob_up": p.prob_up, "baseline_prob_up": p.baseline_prob_up,
                             "pred_return": p.pred_return, "baseline_return": p.baseline_return,
                             "actual_return": p.actual_return} for p in preds],
            "predictions_note": "Thinned to every 5th forecast date for storage; metrics use all dates."}


@router.get("/models", tags=["backtests"])
def model_versions(db: Session = Depends(get_db)):
    return [{"id": m.id, "name": m.name, "version": m.version, "feature_version": m.feature_version,
             "description": m.description, "params": m.params, "created_at": m.created_at}
            for m in db.scalars(select(ModelVersion).order_by(ModelVersion.id))]


@router.get("/horizons", tags=["forecasts"])
def horizons():
    return [{"trading_days": h, "label": l} for h, l in HORIZONS.items()]
