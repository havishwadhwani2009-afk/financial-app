from __future__ import annotations

import numpy as np
from sklearn.metrics import balanced_accuracy_score, log_loss

EPS = 0.01


def clip_p(p):
    return np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)


def brier(y, p) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def logloss(y, p) -> float:
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        p = clip_p(p)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    return float(log_loss(y, clip_p(p), labels=[0, 1]))


def calibration_table(y, p, bins: int = 10) -> list[dict]:
    y, p = np.asarray(y, float), np.asarray(p, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.sum() == 0:
            continue
        out.append({"bin_low": float(edges[b]), "bin_high": float(edges[b + 1]), "n": int(m.sum()),
                    "mean_pred": float(p[m].mean()), "frac_positive": float(y[m].mean())})
    return out


def ece(table: list[dict]) -> float:
    n = sum(r["n"] for r in table)
    return float(sum(r["n"] / n * abs(r["mean_pred"] - r["frac_positive"]) for r in table)) if n else float("nan")


def classification_metrics(y, p, p_base) -> dict:
    y = np.asarray(y, int)
    p, p_base = clip_p(p), clip_p(p_base)
    bs, bs0 = brier(y, p), brier(y, p_base)
    ll, ll0 = logloss(y, p), logloss(y, p_base)
    cal = calibration_table(y, p)
    pred = (p > 0.5).astype(int)
    ba = float(balanced_accuracy_score(y, pred)) if len(np.unique(y)) > 1 else float("nan")
    return {"brier": bs, "brier_baseline": bs0, "brier_skill": 1 - bs / bs0 if bs0 > 0 else float("nan"),
            "log_loss": ll, "log_loss_baseline": ll0,
            "balanced_accuracy": ba, "directional_accuracy": float(np.mean(pred == y)),
            "directional_accuracy_baseline": float(np.mean((p_base > 0.5).astype(int) == y)),
            "ece": ece(cal), "base_rate_positive": float(y.mean())}, cal


def regression_metrics(actual, pred, base) -> dict:
    a, p, b = (np.asarray(x, float) for x in (actual, pred, base))
    mae, mae0 = float(np.mean(np.abs(a - p))), float(np.mean(np.abs(a - b)))
    rmse, rmse0 = float(np.sqrt(np.mean((a - p) ** 2))), float(np.sqrt(np.mean((a - b) ** 2)))
    # out-of-sample R^2 relative to the expanding-mean baseline
    r2 = 1 - np.sum((a - p) ** 2) / np.sum((a - b) ** 2) if np.sum((a - b) ** 2) > 0 else float("nan")
    return {"mae": mae, "mae_baseline": mae0, "rmse": rmse, "rmse_baseline": rmse0, "oos_r2_vs_baseline": float(r2)}
