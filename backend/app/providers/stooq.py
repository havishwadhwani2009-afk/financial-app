"""Stooq daily CSV (secondary / fallback price source).

NOTE: Stooq has been tightening access to its CSV endpoint (may require an API key / captcha token).
Configure STOOQ_API_KEY if required. Stooq provides unadjusted-for-dividends closes, so adj_close is left
empty rather than guessed.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from app.config import get_settings
from app.providers.base import PriceBar, PriceResult, ProviderError, http_get

NAME = "stooq"


def parse_csv(symbol: str, text: str) -> PriceResult:
    if not text.strip() or text.lstrip().lower().startswith(("no data", "<!doctype", "<html")):
        raise ProviderError(f"stooq returned no usable CSV for {symbol}")
    bars, rejected = [], 0
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = date.fromisoformat(row["Date"])
            close = float(row["Close"])
            if close <= 0:
                raise ValueError
            vol = row.get("Volume")
            bars.append(PriceBar(d, float(row["Open"]), float(row["High"]), float(row["Low"]), close,
                                 None, int(float(vol)) if vol else None))
        except (KeyError, ValueError, TypeError):
            rejected += 1
    if not bars:
        raise ProviderError(f"stooq CSV for {symbol} had no valid rows")
    return PriceResult(symbol=symbol, provider=NAME, bars=bars, rejected=rejected)


def fetch_prices(symbol: str) -> PriceResult:
    params = {"s": f"{symbol.lower()}.us", "i": "d"}
    if get_settings().stooq_api_key:
        params["apikey"] = get_settings().stooq_api_key
    r = http_get("https://stooq.com/q/d/l/", params=params)
    return parse_csv(symbol, r.text)
