"""Transparent macro-condition indicators.

Formula (identical for every pillar):
  score_pillar = mean over available inputs of  sign_i * z_i
  z_i = (x_i - mean) / std of the input's transform, over the trailing 10 years (min 3 years), using only
        observations PUBLISHED on or before `as_of` (point-in-time).
  Missing inputs are dropped (equal weights over the rest); a pillar with no inputs is 'unavailable'.
Labels: score >= +0.5 'elevated', <= -0.5 'subdued', otherwise 'neutral'.
These describe conditions; they are not forecasts and carry no assumed market impact.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecasting.features import known_as_of
from app.models import MacroObservation, MacroSeries

# pillar -> [(series, transform, sign, description)]  transform: level | pct{n} | diff{n} (n in observations)
PILLARS: dict[str, dict] = {
    "liquidity": {"title": "Liquidity conditions (higher = looser)", "inputs": [
        ("WALCL", "pct26", +1, "Fed balance sheet, 26-week % change"),
        ("M2SL", "pct12", +1, "M2 money stock, 12-month % change"),
        ("NFCI", "level", -1, "Chicago Fed financial conditions index (higher = tighter)"),
        ("DTWEXBGS", "pct63", -1, "Broad dollar index, ~3-month % change (stronger dollar = tighter)")]},
    "growth": {"title": "Growth conditions (higher = stronger)", "inputs": [
        ("GDPC1", "pct4", +1, "Real GDP, 4-quarter % change"),
        ("UNRATE", "diff6", -1, "Unemployment rate, 6-month change"),
        ("T10Y2Y", "level", +1, "10Y-2Y Treasury spread")]},
    "inflation": {"title": "Inflation pressure (higher = hotter)", "inputs": [
        ("CPIAUCSL", "pct12", +1, "CPI, 12-month % change"),
        ("PCEPILFE", "pct12", +1, "Core PCE, 12-month % change"),
        ("T10YIE", "level", +1, "10Y breakeven inflation")]},
    "rates": {"title": "Interest-rate conditions (higher = tighter)", "inputs": [
        ("DFF", "level", +1, "Fed funds effective rate"),
        ("DGS10", "level", +1, "10Y Treasury yield"),
        ("DFII10", "level", +1, "10Y real yield")]},
    "credit": {"title": "Credit stress (higher = more stress)", "inputs": [
        ("BAMLH0A0HYM2", "level", +1, "High-yield option-adjusted spread"),
        ("NFCI", "level", +1, "Financial conditions index")]},
    "volatility": {"title": "Market volatility / risk aversion (higher = more fear)", "inputs": [
        ("VIXCLS", "level", +1, "VIX")]},
}


def _series(db: Session, sid: str, as_of: date) -> pd.DataFrame | None:
    rows = db.execute(select(MacroObservation.observation_date, MacroObservation.published_date,
                             MacroObservation.value).where(MacroObservation.series_id == sid,
                                                           MacroObservation.published_date <= as_of)).all()
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["observation_date", "published_date", "value"])


def _latest_vintage(df: pd.DataFrame) -> pd.DataFrame:
    """One row per observation date using the latest vintage published by as_of."""
    return df.sort_values("published_date").groupby("observation_date", as_index=False).last() \
             .sort_values("observation_date")


def _transform(s: pd.Series, t: str) -> pd.Series:
    if t == "level":
        return s
    n = int("".join(c for c in t if c.isdigit()))
    return s.pct_change(n) * 100 if t.startswith("pct") else s.diff(n)


def pillar_scores(db: Session, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    out = {}
    for name, spec in PILLARS.items():
        used, zs = [], []
        for sid, tr, sign, desc in spec["inputs"]:
            raw = _series(db, sid, as_of)
            if raw is None:
                used.append({"series": sid, "description": desc, "status": "missing"})
                continue
            lv = _latest_vintage(raw)
            vals = pd.Series(lv["value"].values, index=pd.to_datetime(lv["observation_date"]))
            x = _transform(vals, tr).dropna()
            win = x[x.index >= x.index[-1] - pd.Timedelta(days=3650)] if len(x) else x
            if len(win) < 24 or (win.index[-1] - win.index[0]).days < 3 * 365 or win.std() == 0:
                used.append({"series": sid, "description": desc, "status": "insufficient_history"})
                continue
            z = float((x.iloc[-1] - win.mean()) / win.std())
            pub = raw.sort_values("published_date")["published_date"].iloc[-1]
            used.append({"series": sid, "description": desc, "transform": tr, "sign": sign, "status": "ok",
                         "latest_transformed": float(x.iloc[-1]), "z": z, "weight": None,
                         "observation_date": x.index[-1].date().isoformat(), "published_date": str(pub)})
            zs.append(sign * z)
        ok = [u for u in used if u["status"] == "ok"]
        for u in ok:
            u["weight"] = 1 / len(ok)
        score = float(np.mean(zs)) if zs else None
        label = None if score is None else ("elevated" if score >= 0.5 else "subdued" if score <= -0.5 else "neutral")
        out[name] = {"title": spec["title"], "score": score, "label": label, "inputs": used}
    return {"as_of": as_of.isoformat(), "pillars": out, "method": __doc__.strip()}


def latest_values(db: Session, ids: list[str]) -> list[dict]:
    res = []
    meta = {m.series_id: m for m in db.scalars(select(MacroSeries)).all()}
    for sid in ids:
        raw = _series(db, sid, date.today())
        if raw is None:
            res.append({"series_id": sid, "available": False})
            continue
        lv = _latest_vintage(raw).iloc[-1]
        pub = raw[raw["observation_date"] == lv["observation_date"]]["published_date"].min()
        res.append({"series_id": sid, "available": True, "title": meta[sid].title if sid in meta else sid,
                    "units": meta[sid].units if sid in meta else None, "value": float(lv["value"]),
                    "observation_date": lv["observation_date"].isoformat() if hasattr(lv["observation_date"], "isoformat") else str(lv["observation_date"]),
                    "first_published": str(pub)})
    return res
