"""Historical-sensitivity scenario analysis (descriptive, NOT a forecast).

Regresses an asset's weekly log returns on weekly changes in market, 10Y yield, dollar and VIX over up to 5
years (OLS, HAC standard errors), then applies user-chosen shocks. Co-movement is not causation, betas are
unstable across regimes, and shocks are applied independently.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecasting.service import load_macro, load_prices
from app.models import Instrument

FACTORS = {"market": "Broad US equities (SPY weekly return)", "yield10": "10Y Treasury yield (weekly change, pp)",
           "dollar": "Broad USD index (weekly % change)", "vix": "VIX (weekly change, points)"}
PRESETS = {"Rates +100bp": {"yield10": 1.0}, "Rates -100bp": {"yield10": -1.0},
           "US dollar +5%": {"dollar": 0.05}, "Equity market -10%": {"market": -0.10},
           "VIX +10 points": {"vix": 10.0}}


def _weekly(s: pd.Series) -> pd.Series:
    return s.resample("W-FRI").last().ffill()


def sensitivities(db: Session, inst: Instrument) -> dict:
    px = load_prices(db, inst.id)["adj_close"]
    spy = db.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    macro = load_macro(db)
    if len(px) < 400 or spy is None or macro.empty:
        return {"available": False, "reason": "Needs >= 400 daily prices for the asset, SPY prices and ingested macro series."}
    from app.forecasting.features import known_as_of
    cols = {"asset": np.log(_weekly(px)).diff()}
    cols["market"] = np.log(_weekly(load_prices(db, spy.id)["adj_close"])).diff()
    for key, sid, kind in (("yield10", "DGS10", "diff"), ("dollar", "DTWEXBGS", "pct"), ("vix", "VIXCLS", "diff")):
        s = macro[macro["series_id"] == sid]
        if s.empty:
            continue
        step = known_as_of(s).set_index("published_date")["value"]
        w = _weekly(step)
        cols[key] = w.diff() if kind == "diff" else np.log(w).diff()
    df = pd.DataFrame(cols).dropna().iloc[-260:]
    facs = [f for f in FACTORS if f in df.columns and not (inst.symbol == "SPY" and f == "market")]
    if len(df) < 104 or not facs:
        return {"available": False, "reason": f"Only {len(df)} aligned weekly observations (need >= 104)."}
    m = sm.OLS(df["asset"], sm.add_constant(df[facs])).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    betas = {f: {"beta": float(m.params[f]), "t_stat": float(m.tvalues[f]), "significant_95": bool(abs(m.tvalues[f]) > 1.96),
                 "description": FACTORS[f]} for f in facs}
    scen = []
    for name, shock in PRESETS.items():
        if not set(shock) <= set(facs):
            continue
        est = sum(betas[f]["beta"] * x for f, x in shock.items())
        se = float(np.sqrt(sum((m.bse[f] * x) ** 2 for f, x in shock.items())))
        # weekly-horizon co-movement scaled as a one-off shock; interval is +/-1.96 se of beta uncertainty only
        scen.append({"scenario": name, "shock": shock, "implied_asset_move": float(est),
                     "beta_uncertainty_95": [float(est - 1.96 * se), float(est + 1.96 * se)],
                     "reliable": all(betas[f]["significant_95"] for f in shock)})
    return {"available": True, "n_weeks": int(len(df)), "window": [str(df.index[0].date()), str(df.index[-1].date())],
            "r_squared": float(m.rsquared), "betas": betas, "scenarios": scen,
            "caveats": ["Descriptive historical co-movement, not causal and not a forecast.",
                        "Betas are estimated on weekly data and vary across regimes.",
                        "Intervals reflect coefficient uncertainty only; actual outcomes can be far larger.",
                        "Scenarios marked reliable=false rest on statistically insignificant coefficients."]}
