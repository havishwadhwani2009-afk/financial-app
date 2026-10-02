"""Provider plumbing: retrying HTTP client, typed errors, normalised records."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Provider call failed after retries or returned unusable data."""


class RateLimited(ProviderError):
    pass


@dataclass
class PriceBar:
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: int | None


@dataclass
class ActionRecord:
    ex_date: date
    action_type: str  # dividend | split
    value: float


@dataclass
class PriceResult:
    symbol: str
    provider: str
    bars: list[PriceBar]
    actions: list[ActionRecord] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    rejected: int = 0
    source_ts: datetime | None = None


@dataclass
class MacroPoint:
    observation_date: date
    published_date: date
    value: float
    pit_quality: str  # vintage | assumed_lag


@dataclass
class MacroResult:
    series_id: str
    provider: str
    points: list[MacroPoint]
    rejected: int = 0


@dataclass
class FactRecord:
    concept: str
    source_tag: str
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    filed: date
    accession: str
    value: float
    unit: str


@dataclass
class FundamentalsResult:
    symbol: str
    cik: str
    provider: str
    facts: list[FactRecord]
    entity_name: str | None = None
    rejected: int = 0


def http_get(url: str, *, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """GET with bounded retries + exponential backoff on 429/5xx/network errors."""
    s = get_settings()
    last: Exception | None = None
    for attempt in range(s.http_max_retries + 1):
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=s.http_timeout_s,
                          follow_redirects=True)
            if r.status_code == 429 or r.status_code >= 500:
                last = RateLimited(f"{url} -> HTTP {r.status_code}") if r.status_code == 429 \
                    else ProviderError(f"{url} -> HTTP {r.status_code}")
            elif r.status_code >= 400:
                raise ProviderError(f"{url} -> HTTP {r.status_code}")  # not retryable
            else:
                return r
        except httpx.HTTPError as e:
            last = ProviderError(f"{url} -> {type(e).__name__}: {e}")
        if attempt < s.http_max_retries:
            time.sleep(min(2 ** attempt, 8) * (0.01 if _TESTING else 1))
    assert last is not None
    raise last


_TESTING = False  # tests flip this to skip real sleeping
