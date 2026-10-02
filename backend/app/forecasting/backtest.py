"""Purged expanding-window walk-forward evaluation.

At each refit date r the model is trained ONLY on rows j whose label window has fully elapsed by r
(j + h <= r), so no training label overlaps information after r. Predictions are then made for dates
r .. r+step-1 using that frozen model. Nothing is shuffled; nothing is tuned on the evaluated period.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.forecasting import metrics as M
from app.forecasting.models import REGISTRY, BaselineMean

MIN_TRAIN = 504       # ~2 years of labelled rows before the first forecast
REFIT_EVERY = 21      # refit monthly
MIN_OOS = 250
MIN_EFFECTIVE = 20    # overlapping windows => effective independent obs ~ n / h
ECE_LIMIT = 0.10
STRAT_THRESHOLD = 0.55
COST_BPS = 5.0        # one-way transaction cost + slippage assumption


@dataclass
class WalkForwardResult:
    model: str
    horizon: int
    preds: pd.DataFrame  # index asof date; prob_up, pred_return, baseline_prob_up, baseline_return, actual_return
    config: dict = field(default_factory=dict)


def walk_forward(X: pd.DataFrame, y: pd.Series, h: int, model_name: str,
                 min_train: int = MIN_TRAIN, step: int = REFIT_EVERY) -> WalkForwardResult:
    n = len(X)
    yv = y.values
    rows = []
    for r in range(min_train + h, n, step):
        tr = np.arange(0, r - h + 1)           # j + h <= r
        tr = tr[~np.isnan(yv[tr])]
        if len(tr) < min_train:
            continue
        end = min(r + step, n)
        te = np.arange(r, end)
        te = te[~np.isnan(yv[te])]              # evaluate only rows with realised outcome
        if len(te) == 0:
            continue
        model = REGISTRY[model_name]().fit(X.iloc[tr], yv[tr])
        base = BaselineMean().fit(X.iloc[tr], yv[tr])
        p, mu = model.predict(X.iloc[te])
        bp, bmu = base.predict(X.iloc[te])
        rows.append(pd.DataFrame({"prob_up": p, "pred_return": mu, "baseline_prob_up": bp,
                                  "baseline_return": bmu, "actual_return": yv[te]}, index=X.index[te]))
    preds = pd.concat(rows) if rows else pd.DataFrame(
        columns=["prob_up", "pred_return", "baseline_prob_up", "baseline_return", "actual_return"])
    return WalkForwardResult(model_name, h, preds, {"min_train": min_train, "refit_every": step,
                                                    "purged": True, "expanding": True})


def evaluate(res: WalkForwardResult, regime: pd.Series | None = None) -> dict:
    d = res.preds
    n = len(d)
    out: dict = {"n_obs": n, "horizon": res.horizon,
                 "start_date": str(d.index[0].date()) if n else None,
                 "end_date": str(d.index[-1].date()) if n else None,
                 "effective_n": n / res.horizon if n else 0}
    if n < 30:
        return {**out, "classification": None, "regression": None, "calibration": [], "by_regime": {}}
    y = (d["actual_return"] > 0).astype(int)
    cls, cal = M.classification_metrics(y, d["prob_up"], d["baseline_prob_up"])
    reg = M.regression_metrics(d["actual_return"], d["pred_return"], d["baseline_return"])
    by_reg = {}
    if regime is not None:
        rg = regime.reindex(d.index)
        for name in rg.dropna().unique():
            m = (rg == name).values
            if m.sum() >= 100:
                c, _ = M.classification_metrics(y[m], d["prob_up"][m], d["baseline_prob_up"][m])
                by_reg[str(name)] = {"n_obs": int(m.sum()), "brier_skill": c["brier_skill"],
                                     "brier": c["brier"], "ece": c["ece"]}
    half = n // 2
    halves = []
    for sl in (slice(0, half), slice(half, n)):
        c, _ = M.classification_metrics(y.iloc[sl], d["prob_up"].iloc[sl], d["baseline_prob_up"].iloc[sl])
        halves.append(c["brier_skill"])
    out.update({"classification": cls, "regression": reg, "calibration": cal, "by_regime": by_reg,
                "brier_skill_halves": halves})
    return out


def validation_status(ev: dict) -> tuple[str, list[str]]:
    """Explicit, conservative gate. 'validated' means: out-of-sample, calibrated, beats the baseline,
    stable across halves. It does NOT mean the forecast is reliable or profitable."""
    reasons: list[str] = []
    if ev["n_obs"] < MIN_OOS or ev["effective_n"] < MIN_EFFECTIVE or ev["classification"] is None:
        return "insufficient_data", [f"{ev['n_obs']} out-of-sample observations "
                                     f"(~{ev['effective_n']:.0f} independent); need >= {MIN_OOS} (~{MIN_EFFECTIVE})."]
    c = ev["classification"]
    if not (c["brier_skill"] > 0 and c["log_loss"] < c["log_loss_baseline"]):
        reasons.append(f"No edge over unconditional baseline (Brier skill {c['brier_skill']:+.3f}).")
        return "no_edge_over_baseline", reasons
    if c["ece"] > ECE_LIMIT:
        return "poorly_calibrated", [f"Expected calibration error {c['ece']:.3f} > {ECE_LIMIT}."]
    h1, h2 = ev["brier_skill_halves"]
    if not (h1 > 0 and h2 > 0):
        return "unstable", [f"Brier skill differs across halves ({h1:+.3f}, {h2:+.3f})."]
    return "validated", [f"Brier skill {c['brier_skill']:+.3f} over {ev['n_obs']} OOS obs; ECE {c['ece']:.3f}."]


def strategy_backtest(daily_ret: pd.Series, preds: pd.DataFrame, threshold: float = STRAT_THRESHOLD,
                      cost_bps: float = COST_BPS) -> dict | None:
    """Long-or-cash rule: hold when P(up) > threshold at close t, earn the NEXT day's return.
    Includes one-way costs on position changes. Compared with buy-and-hold on the same dates."""
    if len(preds) < 60:
        return None
    pos = (preds["prob_up"] > threshold).astype(float)
    r = daily_ret.reindex(pos.index.union(daily_ret.index)).sort_index()
    pos = pos.reindex(r.index).ffill()
    start = preds.index[0]
    r_next = r.shift(-1)
    sel = r_next.index >= start
    pos, r_next = pos[sel].dropna(), r_next[sel]
    r_next = r_next.reindex(pos.index).dropna()
    pos = pos.reindex(r_next.index)
    turnover = pos.diff().abs().fillna(pos.iloc[0])
    strat = pos * r_next - turnover * cost_bps / 1e4
    return {"threshold": threshold, "cost_bps_one_way": cost_bps, "n_days": int(len(strat)),
            "strategy": _perf(strat), "buy_and_hold": _perf(r_next),
            "exposure": float(pos.mean()), "annual_turnover": float(turnover.sum() / len(strat) * 252),
            "note": "Long/cash on out-of-sample probabilities; excludes taxes, financing, market impact."}


def _perf(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    vol = float(r.std() * np.sqrt(252))
    ann = float(eq.iloc[-1] ** (252 / len(r)) - 1) if len(r) else float("nan")
    dd = float((eq / eq.cummax() - 1).min())
    return {"total_return": float(eq.iloc[-1] - 1), "ann_return": ann, "ann_vol": vol,
            "sharpe_rf0": ann / vol if vol > 0 else None, "max_drawdown": dd}
