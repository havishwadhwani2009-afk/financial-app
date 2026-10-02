"""Point-in-time feature construction.

Rule: every feature at row t may use only information public at the close of trading day t.
 - price features: rolling windows that end at t (no centering, no look-ahead)
 - macro features: values are aligned by *publication date* (merge_asof on published_date <= t)
 - the label (forward return) lives in a separate function and is never part of X
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "f1"
HORIZONS = {5: "1 week", 21: "1 month", 63: "3 months", 126: "6 months", 252: "12 months"}
TRADING_DAYS = 252


def price_features(px: pd.DataFrame, market: pd.Series | None = None) -> pd.DataFrame:
    """px: index=date (ascending), columns adj_close (required), volume (optional)."""
    p = px["adj_close"].astype(float)
    lr = np.log(p).diff()
    f = pd.DataFrame(index=px.index)
    for k in (5, 21, 63, 126, 252):
        f[f"ret_{k}"] = np.log(p).diff(k)
    f["vol_21"] = lr.rolling(21).std() * np.sqrt(TRADING_DAYS)
    f["vol_63"] = lr.rolling(63).std() * np.sqrt(TRADING_DAYS)
    f["ma50_ratio"] = p / p.rolling(50).mean() - 1
    f["ma200_ratio"] = p / p.rolling(200).mean() - 1
    f["drawdown_252"] = p / p.rolling(252, min_periods=60).max() - 1
    if "volume" in px and px["volume"].fillna(0).gt(0).mean() > 0.8:
        v = np.log1p(px["volume"].astype(float).clip(lower=0))
        f["volume_z_63"] = (v - v.rolling(63).mean()) / v.rolling(63).std()
    if market is not None:
        m = np.log(market.reindex(px.index).ffill())
        f["mkt_ret_21"] = m.diff(21)
        f["mkt_ret_63"] = m.diff(63)
        f["rel_ret_63"] = f["ret_63"] - f["mkt_ret_63"]
    return f.replace([np.inf, -np.inf], np.nan)


def forward_log_return(p: pd.Series, h: int) -> pd.Series:
    """Label: log(P[t+h]/P[t]) -- uses the future by design; only ever used as y."""
    lp = np.log(p.astype(float))
    return lp.shift(-h) - lp


def known_as_of(obs: pd.DataFrame) -> pd.DataFrame:
    """obs columns: observation_date, published_date, value (may hold several vintages per observation).
    Returns step series indexed by published_date: the value of the LATEST observation known on that date
    (using the vintage known on that date), so revisions published later never leak backwards."""
    obs = obs.sort_values(["published_date", "observation_date"])
    known: dict = {}
    out_d, out_v = [], []
    cur_pub = None
    for pub, od, v in zip(obs["published_date"], obs["observation_date"], obs["value"]):
        if cur_pub is not None and pub != cur_pub:
            out_d.append(cur_pub)
            out_v.append(known[max(known)])
        known[od] = v
        cur_pub = pub
    if cur_pub is not None:
        out_d.append(cur_pub)
        out_v.append(known[max(known)])
    return pd.DataFrame({"published_date": pd.to_datetime(out_d), "value": out_v})


# (transform, window in trading days): level | diff | pct
MACRO_SPEC: dict[str, list[tuple[str, int]]] = {
    "DGS10": [("level", 0), ("diff", 63)],
    "T10Y2Y": [("level", 0)],
    "DFII10": [("level", 0), ("diff", 63)],
    "DFF": [("level", 0), ("diff", 126)],
    "BAMLH0A0HYM2": [("level", 0), ("diff", 63)],
    "VIXCLS": [("level", 0)],
    "DTWEXBGS": [("pct", 63)],
    "CPIAUCSL": [("pct", 252)],
    "UNRATE": [("level", 0), ("diff", 126)],
    "M2SL": [("pct", 252)],
}


def macro_features(obs: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """obs: long frame with series_id, observation_date, published_date, value."""
    out = pd.DataFrame(index=index)
    if obs.empty:
        return out
    idx = pd.DataFrame({"date": index})
    for sid, spec in MACRO_SPEC.items():
        s = obs[obs["series_id"] == sid]
        if s.empty:
            continue
        step = known_as_of(s)
        aligned = pd.merge_asof(idx, step, left_on="date", right_on="published_date")
        v = pd.Series(aligned["value"].values, index=index)
        for kind, w in spec:
            if kind == "level":
                out[f"{sid}_lvl"] = v
            elif kind == "diff":
                out[f"{sid}_d{w}"] = v.diff(w)
            else:
                out[f"{sid}_p{w}"] = v.pct_change(w, fill_method=None)
    return out.replace([np.inf, -np.inf], np.nan)


def build_features(px: pd.DataFrame, macro_obs: pd.DataFrame | None = None,
                   market: pd.Series | None = None) -> pd.DataFrame:
    f = price_features(px, market)
    if macro_obs is not None and not macro_obs.empty:
        f = f.join(macro_features(macro_obs, f.index))
    return f
