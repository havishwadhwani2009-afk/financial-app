"""FRED (St. Louis Fed) - official macroeconomic source.

With FRED_API_KEY (free) the API returns every real-time *vintage* of each observation
(realtime_start = date that value became public) => true point-in-time data.
Without a key we fall back to the public fredgraph CSV (latest revised values only); in that case the
publication date is ASSUMED as observation_date + series lag and flagged pit_quality='assumed_lag'.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from app.config import get_settings
from app.providers.base import MacroPoint, MacroResult, ProviderError, http_get

NAME = "fred"
API = "https://api.stlouisfed.org/fred/series/observations"
CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# series_id: (title, category, units, frequency, assumed publication lag in days)
SERIES: dict[str, tuple[str, str, str, str, int]] = {
    "DFF": ("Federal Funds Effective Rate", "rates", "percent", "daily", 1),
    "DGS3MO": ("3-Month Treasury Yield", "rates", "percent", "daily", 1),
    "DGS2": ("2-Year Treasury Yield", "rates", "percent", "daily", 1),
    "DGS10": ("10-Year Treasury Yield", "rates", "percent", "daily", 1),
    "T10Y2Y": ("10Y minus 2Y Treasury Spread", "rates", "percent", "daily", 1),
    "DFII10": ("10-Year Real Yield (TIPS)", "rates", "percent", "daily", 1),
    "T10YIE": ("10-Year Breakeven Inflation", "inflation", "percent", "daily", 1),
    "CPIAUCSL": ("CPI All Urban Consumers (SA)", "inflation", "index 1982-84=100", "monthly", 45),
    "PCEPILFE": ("Core PCE Price Index", "inflation", "index 2017=100", "monthly", 35),
    "UNRATE": ("Unemployment Rate", "growth", "percent", "monthly", 38),
    "GDPC1": ("Real GDP", "growth", "bn chained 2017 USD, SAAR", "quarterly", 95),
    "M2SL": ("M2 Money Stock", "liquidity", "bn USD", "monthly", 30),
    "WALCL": ("Fed Balance Sheet: Total Assets", "liquidity", "mn USD", "weekly", 2),
    "BAMLH0A0HYM2": ("ICE BofA US High Yield OAS", "credit", "percent", "daily", 1),
    "NFCI": ("Chicago Fed National Financial Conditions Index", "credit", "index", "weekly", 5),
    "DTWEXBGS": ("Broad Trade-Weighted US Dollar Index", "dollar", "index Jan2006=100", "daily", 2),
    "VIXCLS": ("CBOE Volatility Index (VIX)", "volatility", "index", "daily", 1),
}


def parse_api(series_id: str, payload: dict) -> MacroResult:
    if "observations" not in payload:
        raise ProviderError(f"FRED API error for {series_id}: {payload.get('error_message', payload)}")
    pts, rej = [], 0
    for o in payload["observations"]:
        try:
            if o["value"] in (".", "", None):
                rej += 1
                continue
            pts.append(MacroPoint(date.fromisoformat(o["date"]), date.fromisoformat(o["realtime_start"]),
                                  float(o["value"]), "vintage"))
        except (KeyError, ValueError):
            rej += 1
    return MacroResult(series_id, NAME, pts, rej)


def parse_csv(series_id: str, text: str, lag_days: int) -> MacroResult:
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise ProviderError(f"FRED CSV for {series_id} returned HTML")
    pts, rej = [], 0
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].lower() in ("date", "observation_date"):
            continue
        try:
            if row[1] in (".", ""):
                rej += 1
                continue
            d = date.fromisoformat(row[0])
            pts.append(MacroPoint(d, d + timedelta(days=lag_days), float(row[1]), "assumed_lag"))
        except (ValueError, IndexError):
            rej += 1
    if not pts:
        raise ProviderError(f"FRED CSV for {series_id} had no valid rows")
    return MacroResult(series_id, NAME, pts, rej)


def fetch_series(series_id: str) -> MacroResult:
    key = get_settings().fred_api_key
    lag = SERIES.get(series_id, ("", "", "", "", 1))[4]
    if key:
        r = http_get(API, params={"series_id": series_id, "api_key": key, "file_type": "json",
                                  "realtime_start": "1776-07-04", "realtime_end": "9999-12-31",
                                  "limit": 100000})
        return parse_api(series_id, r.json())
    r = http_get(CSV, params={"id": series_id})
    return parse_csv(series_id, r.text, lag)
