"""Yahoo Finance chart endpoint.

UNOFFICIAL: this is an undocumented public endpoint used by Yahoo's website. Availability, rate limits and
terms may change without notice; do not treat as an SLA-backed source. Used here as the first price source
because it covers US stocks/ETFs/indices with dividends and splits in one call.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.providers.base import (ActionRecord, PriceBar, PriceResult, ProviderError, http_get)

NAME = "yahoo"
BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FinIntel/0.1)"}


def parse_chart(symbol: str, payload: dict) -> PriceResult:
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ProviderError(f"yahoo error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ProviderError(f"yahoo returned no result for {symbol}")
    res = results[0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    gmtoffset = int(meta.get("gmtoffset") or 0)
    bars: list[PriceBar] = []
    rejected = 0
    seen = set()
    for i, t in enumerate(ts):
        try:
            close = quote["close"][i]
            if close is None or close <= 0:
                rejected += 1
                continue
            # exchange-local calendar date of the bar
            d = datetime.fromtimestamp(t + gmtoffset, tz=timezone.utc).date()
            if d in seen:
                rejected += 1
                continue
            seen.add(d)

            def g(k):
                v = quote.get(k, [None] * (i + 1))[i]
                return float(v) if v is not None else None

            vol = quote.get("volume", [None] * (i + 1))[i]
            a = adj[i] if adj and adj[i] is not None else None
            bars.append(PriceBar(d, g("open"), g("high"), g("low"), float(close),
                                 float(a) if a is not None else None,
                                 int(vol) if vol is not None else None))
        except (KeyError, IndexError, TypeError, ValueError):
            rejected += 1
    actions: list[ActionRecord] = []
    ev = res.get("events") or {}
    for e in (ev.get("dividends") or {}).values():
        actions.append(ActionRecord(datetime.fromtimestamp(e["date"], tz=timezone.utc).date(),
                                    "dividend", float(e["amount"])))
    for e in (ev.get("splits") or {}).values():
        if e.get("denominator"):
            actions.append(ActionRecord(datetime.fromtimestamp(e["date"], tz=timezone.utc).date(),
                                        "split", float(e["numerator"]) / float(e["denominator"])))
    src_ts = None
    if meta.get("regularMarketTime"):
        src_ts = datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc)
    return PriceResult(symbol=symbol, provider=NAME, bars=bars, actions=actions, rejected=rejected,
                       source_ts=src_ts,
                       meta={"name": meta.get("longName") or meta.get("shortName"),
                             "currency": meta.get("currency"),
                             "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                             "instrument_type": meta.get("instrumentType")})


def fetch_prices(symbol: str, range_: str = "max") -> PriceResult:
    r = http_get(BASE + symbol, params={"range": range_, "interval": "1d", "events": "div,splits",
                                        "includeAdjustedClose": "true"}, headers=HEADERS)
    try:
        payload = r.json()
    except ValueError as e:
        raise ProviderError(f"yahoo non-JSON response for {symbol}") from e
    return parse_chart(symbol, payload)
