"""Ingestion jobs: provider -> validate -> normalise -> idempotent store, with run history."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.common import Run, upsert
from app.ingestion.universe import ETFS, INDICES, STOCKS
from app.models import (CorporateAction, DataProvider, Fundamental, Instrument, MacroObservation,
                        MacroSeries, Price)
from app.providers import fred, sec_edgar, stooq, yahoo
from app.providers.base import PriceResult

log = logging.getLogger(__name__)

PROVIDERS = [
    ("yahoo", "prices", "https://query1.finance.yahoo.com", False,
     "UNOFFICIAL endpoint; may change or be restricted without notice."),
    ("stooq", "prices", "https://stooq.com", False, "Secondary price source; access conditions may require a key."),
    ("fred", "macro", "https://api.stlouisfed.org", True,
     "Official St. Louis Fed. API key enables real-time vintages (point-in-time)."),
    ("sec_edgar", "fundamentals", "https://data.sec.gov", True,
     "Official SEC XBRL company facts; US filers only; requires contact User-Agent."),
]


def seed_providers(db: Session) -> None:
    rows = [dict(name=n, kind=k, base_url=u, official=o, notes=t) for n, k, u, o, t in PROVIDERS]
    upsert(db, DataProvider.__table__, rows, ["name"], ["kind", "base_url", "official", "notes"])
    db.commit()


def seed_universe(db: Session) -> int:
    rows = [dict(symbol=s, exchange="US", instrument_type="stock", metadata_source="seed") for s in STOCKS]
    rows += [dict(symbol=s, exchange="US", instrument_type="etf", name=n, sector=cat, metadata_source="seed")
             for s, (n, cat) in ETFS.items()]
    rows += [dict(symbol=s, exchange="INDEX", instrument_type="index", name=n, metadata_source="seed")
             for s, n in INDICES.items()]
    # insert-only: never clobber metadata later enriched from providers
    n = upsert(db, Instrument.__table__, rows, ["symbol", "exchange"])
    db.commit()
    return n


def get_instrument(db: Session, symbol: str) -> Instrument | None:
    return db.scalar(select(Instrument).where(Instrument.symbol == symbol).limit(1))


def store_prices(db: Session, inst: Instrument, res: PriceResult) -> int:
    now = datetime.now(timezone.utc)
    rows = [dict(instrument_id=inst.id, date=b.date, provider=res.provider, open=b.open, high=b.high,
                 low=b.low, close=b.close, adj_close=b.adj_close, volume=b.volume,
                 source_ts=res.source_ts, ingested_at=now) for b in res.bars]
    n = upsert(db, Price.__table__, rows, ["instrument_id", "date", "provider"],
               ["open", "high", "low", "close", "adj_close", "volume", "source_ts", "ingested_at"])
    acts = [dict(instrument_id=inst.id, ex_date=a.ex_date, action_type=a.action_type, value=a.value,
                 provider=res.provider, ingested_at=now) for a in res.actions]
    upsert(db, CorporateAction.__table__, acts, ["instrument_id", "ex_date", "action_type"], ["value"])
    # enrich metadata from provider without overwriting curated names
    m = res.meta
    if m.get("currency") and not inst.currency:
        inst.currency = m["currency"]
    if m.get("name") and not inst.name:
        inst.name = m["name"]
    if m.get("instrument_type") and inst.instrument_type == "other":
        inst.instrument_type = {"EQUITY": "stock", "ETF": "etf", "MUTUALFUND": "mutual_fund",
                               "INDEX": "index"}.get(m["instrument_type"], "other")
    db.commit()
    return n


def ingest_prices(db: Session, symbol: str, provider: str = "yahoo") -> None:
    inst = get_instrument(db, symbol)
    if inst is None:
        raise ValueError(f"unknown symbol {symbol}; seed the universe first")
    with Run(db, provider, "prices", symbol) as run:
        res = (yahoo.fetch_prices if provider == "yahoo" else stooq.fetch_prices)(symbol)
        run.written = store_prices(db, inst, res)
        run.rejected = res.rejected


def ingest_macro(db: Session, series_id: str) -> None:
    title, cat, units, freq, lag = fred.SERIES[series_id]
    upsert(db, MacroSeries.__table__, [dict(series_id=series_id, title=title, category=cat, units=units,
                                            frequency=freq, provider="fred", assumed_lag_days=lag)],
           ["series_id"], ["title", "category", "units", "frequency", "assumed_lag_days"])
    db.commit()
    with Run(db, "fred", "macro", series_id) as run:
        res = fred.fetch_series(series_id)
        now = datetime.now(timezone.utc)
        rows = [dict(series_id=series_id, observation_date=p.observation_date, published_date=p.published_date,
                     value=p.value, pit_quality=p.pit_quality, provider="fred", ingested_at=now)
                for p in res.points]
        run.written = upsert(db, MacroObservation.__table__, rows,
                             ["series_id", "observation_date", "published_date"], ["value"])
        run.rejected = res.rejected


_ticker_map: dict[str, dict] | None = None


def ingest_fundamentals(db: Session, symbol: str) -> None:
    global _ticker_map
    inst = get_instrument(db, symbol)
    if inst is None or inst.instrument_type != "stock":
        raise ValueError(f"{symbol} is not a stock in the universe")
    with Run(db, "sec_edgar", "fundamentals", symbol) as run:
        if inst.cik is None:
            if _ticker_map is None:
                _ticker_map = sec_edgar.fetch_ticker_map()
            hit = _ticker_map.get(symbol.upper())
            if not hit:
                raise ValueError(f"{symbol} not found in SEC ticker map (non-US filer or delisted?)")
            inst.cik = hit["cik"]
            inst.name = inst.name or hit["name"]
            inst.country = "US"
            try:
                inst.sector = sec_edgar.fetch_sic_description(inst.cik)
                inst.metadata_source = "sec_edgar"
            except Exception as e:  # sector is optional
                log.info("sic lookup failed for %s: %s", symbol, e)
            db.commit()
        res = sec_edgar.fetch_company_facts(symbol, inst.cik)
        now = datetime.now(timezone.utc)
        rows = [dict(instrument_id=inst.id, concept=f.concept, source_tag=f.source_tag,
                     period_start=f.period_start, period_end=f.period_end, fiscal_year=f.fiscal_year,
                     fiscal_period=f.fiscal_period, form=f.form, filed=f.filed, accession=f.accession,
                     value=f.value, unit=f.unit, provider="sec_edgar", ingested_at=now) for f in res.facts]
        run.written = upsert(db, Fundamental.__table__, rows,
                             ["instrument_id", "concept", "source_tag", "period_start", "period_end", "accession"])
        run.rejected = res.rejected


def ingest_all(db: Session, include_fundamentals: bool = True) -> dict:
    seed_providers(db)
    seed_universe(db)
    for sid in fred.SERIES:
        ingest_macro(db, sid)
    for s in db.scalars(select(Instrument.symbol)).all():
        ingest_prices(db, s)
    if include_fundamentals:
        for s in STOCKS:
            ingest_fundamentals(db, s)
    return {"ok": True}
