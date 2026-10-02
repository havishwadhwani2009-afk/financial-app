"""Fundamental analysis from SEC XBRL facts. Annual (10-K, ~12-month duration) figures only.

Design rules
 - Only USD / USD-per-share / share-count units are used; other reporting currencies are flagged, never mixed.
 - Restatements: for each fiscal period the most recently FILED value wins; first_filed is kept.
 - A ratio is computed only when all of its inputs exist for the same fiscal period.
 - No composite "quality score" is produced.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fundamental, Price

FLOW = {"revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "cfo", "capex",
        "interest_expense", "shares_diluted_wavg"}
STOCK = {"total_assets", "total_liabilities", "equity", "cash", "debt_long_term", "debt_current"}
OK_UNITS = {"USD", "USD/shares", "shares"}

DEFINITIONS = {
    "revenue_growth": "Revenue(FY) / Revenue(prior FY) - 1, consecutive fiscal years only.",
    "net_income_growth": "Net income(FY)/Net income(prior FY) - 1; undefined when prior value <= 0.",
    "gross_margin": "Gross profit / Revenue.", "operating_margin": "Operating income / Revenue.",
    "net_margin": "Net income / Revenue.",
    "fcf": "Cash from operations - capital expenditure (PP&E purchases).",
    "roe": "Net income / average of opening and closing shareholders' equity (closing only if no prior year).",
    "debt_to_equity": "(Long-term debt + current debt) / shareholders' equity. Debt omitted components are flagged.",
    "interest_coverage": "Operating income / interest expense.",
    "pe": "Latest close / latest annual diluted EPS (annual EPS can be up to ~12 months old).",
    "ps": "Market cap / latest annual revenue.", "fcf_yield": "Latest annual FCF / market cap.",
    "market_cap": "Latest close x latest cover-page shares outstanding (SEC dei). Excludes other share classes if not reported.",
    "ev_revenue": "(Market cap + total debt - cash) / latest annual revenue.",
}


def _annual(db: Session, instrument_id: int, as_of: date | None = None) -> tuple[dict, list[str]]:
    q = select(Fundamental).where(Fundamental.instrument_id == instrument_id)
    if as_of:
        q = q.where(Fundamental.filed <= as_of)  # point-in-time view
    rows = db.scalars(q).all()
    warnings: list[str] = []
    nonusd = {r.unit for r in rows if r.unit not in OK_UNITS}
    if nonusd:
        warnings.append(f"Facts reported in non-USD units {sorted(nonusd)} were excluded; no currency conversion is done.")
    best: dict[tuple[str, date], Fundamental] = {}
    first_filed: dict[tuple[str, date], date] = {}
    for r in rows:
        if r.unit not in OK_UNITS or r.concept in ("shares_outstanding",):
            continue
        if r.concept in FLOW:
            if r.period_start is None or not 340 <= (r.period_end - r.period_start).days <= 380:
                continue
        elif r.concept in STOCK:
            if r.form not in ("10-K", "10-K/A"):
                continue
        else:
            continue
        k = (r.concept, r.period_end)
        first_filed[k] = min(first_filed.get(k, r.filed), r.filed)
        # prefer a higher-priority source tag only implicitly via recency of filing
        if k not in best or r.filed > best[k].filed:
            best[k] = r
    by_period: dict[date, dict] = {}
    for (concept, end), r in best.items():
        p = by_period.setdefault(end, {"period_end": end, "values": {}, "filed": {}, "tags": {}})
        p["values"][concept] = r.value
        p["filed"][concept] = r.filed
        p["tags"][concept] = r.source_tag
        p.setdefault("first_filed", {})[concept] = first_filed[(concept, end)]
    return by_period, warnings


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def annual_metrics(db: Session, instrument_id: int, as_of: date | None = None) -> dict:
    by_period, warnings = _annual(db, instrument_id, as_of)
    periods = []
    ends = sorted(by_period)
    for i, end in enumerate(ends):
        v = by_period[end]["values"]
        prev = by_period[ends[i - 1]] if i > 0 and 350 <= (end - ends[i - 1]).days <= 380 else None
        pv = prev["values"] if prev else {}
        debt_parts = [v.get("debt_long_term"), v.get("debt_current")]
        debt = sum(x for x in debt_parts if x is not None) if any(x is not None for x in debt_parts) else None
        fcf = v["cfo"] - v["capex"] if "cfo" in v and "capex" in v else None
        eq_avg = (v["equity"] + pv["equity"]) / 2 if "equity" in v and "equity" in pv else v.get("equity")
        m = {
            "revenue_growth": _div(v["revenue"] - pv["revenue"], abs(pv["revenue"])) if "revenue" in v and "revenue" in pv else None,
            "net_income_growth": _div(v["net_income"] - pv["net_income"], pv["net_income"]) if "net_income" in v and pv.get("net_income", 0) > 0 else None,
            "gross_margin": _div(v.get("gross_profit"), v.get("revenue")),
            "operating_margin": _div(v.get("operating_income"), v.get("revenue")),
            "net_margin": _div(v.get("net_income"), v.get("revenue")),
            "fcf": fcf,
            "roe": _div(v.get("net_income"), eq_avg),
            "debt_to_equity": _div(debt, v.get("equity")) if debt is not None else None,
            "interest_coverage": _div(v.get("operating_income"), v.get("interest_expense")),
            "total_debt": debt,
        }
        periods.append({"period_end": end.isoformat(),
                        "fiscal_year": end.year if end.month > 1 else end.year - 1,
                        "publicly_available_from": max(by_period[end]["filed"].values()).isoformat(),
                        "values": v, "metrics": m,
                        "restated": any(by_period[end]["filed"][c] != by_period[end]["first_filed"][c]
                                        for c in v)})
    if not periods:
        warnings.append("No annual SEC filings ingested for this instrument (non-US filer, fund, or not yet ingested).")
    return {"periods": periods, "warnings": warnings, "definitions": DEFINITIONS,
            "source": "SEC EDGAR XBRL company facts", "currency": "USD (non-USD facts excluded)"}


def latest_shares(db: Session, instrument_id: int) -> tuple[float | None, date | None]:
    r = db.scalars(select(Fundamental).where(Fundamental.instrument_id == instrument_id,
                                             Fundamental.concept == "shares_outstanding")
                   .order_by(Fundamental.period_end.desc(), Fundamental.filed.desc()).limit(1)).first()
    return (r.value, r.period_end) if r else (None, None)


def valuation(db: Session, instrument_id: int, metrics: dict | None = None) -> dict:
    metrics = metrics or annual_metrics(db, instrument_id)
    px = db.execute(select(Price.date, Price.close).where(Price.instrument_id == instrument_id)
                    .order_by(Price.date.desc()).limit(1)).first()
    out = {"price_date": None, "price": None, "market_cap": None, "pe": None, "ps": None, "fcf_yield": None,
           "ev_revenue": None, "inputs": {}, "notes": []}
    if not px or not metrics["periods"]:
        out["notes"].append("Valuation needs both a price and annual fundamentals.")
        return out
    price, pdate = px[1], px[0]
    last = metrics["periods"][-1]
    v, m = last["values"], last["metrics"]
    shares, sdate = latest_shares(db, instrument_id)
    out.update(price=price, price_date=pdate.isoformat(),
               inputs={"fiscal_period_end": last["period_end"], "shares_as_of": sdate.isoformat() if sdate else None})
    if (date.today() - date.fromisoformat(last["period_end"])) > timedelta(days=500):
        out["notes"].append("Latest annual filing is over ~16 months old; valuation ratios may be stale.")
    if "eps_diluted" in v and v["eps_diluted"] > 0:
        out["pe"] = price / v["eps_diluted"]
    elif "eps_diluted" in v:
        out["notes"].append("P/E not meaningful: non-positive EPS.")
    if shares:
        mc = price * shares
        out["market_cap"] = mc
        out["ps"] = _div(mc, v.get("revenue"))
        out["fcf_yield"] = _div(m.get("fcf"), mc)
        if v.get("revenue") and m.get("total_debt") is not None and "cash" in v:
            out["ev_revenue"] = (mc + m["total_debt"] - v["cash"]) / v["revenue"]
    else:
        out["notes"].append("Shares outstanding unavailable: market-cap-based ratios not computed.")
    out["notes"].append("Not compared with peers: no validated peer group is available.")
    return out
