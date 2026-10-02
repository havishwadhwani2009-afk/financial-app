from datetime import date

import pytest
from sqlalchemy import func, select

from app.ingestion import jobs
from app.ingestion.common import upsert
from app.models import (CorporateAction, Fundamental, IngestionRun, Instrument, MacroObservation, Price)
from app.providers import fred, sec_edgar, yahoo
from app.providers.base import ProviderError
from tests.test_providers import SEC, YAHOO


def _inst(db, sym="TST"):
    i = Instrument(symbol=sym, exchange="US", instrument_type="stock")
    db.add(i)
    db.commit()
    return i


def test_price_ingestion_is_idempotent_and_logged(db, monkeypatch):
    _inst(db)
    monkeypatch.setattr(yahoo, "fetch_prices", lambda s: yahoo.parse_chart(s, YAHOO))
    for _ in range(2):
        jobs.ingest_prices(db, "TST")
    assert db.scalar(select(func.count()).select_from(Price)) == 3
    assert db.scalar(select(func.count()).select_from(CorporateAction)) == 2
    runs = db.scalars(select(IngestionRun)).all()
    assert [r.status for r in runs] == ["partial", "partial"] and runs[0].rows_rejected == 1
    assert db.scalar(select(Instrument.name)) == "Test Corp"


def test_provider_failure_is_recorded_not_raised(db, monkeypatch):
    _inst(db)

    def boom(s):
        raise ProviderError("HTTP 403")
    monkeypatch.setattr(yahoo, "fetch_prices", boom)
    jobs.ingest_prices(db, "TST")
    r = db.scalar(select(IngestionRun))
    assert r.status == "failed" and "403" in r.error


def test_macro_ingestion_stores_dates_separately_and_is_idempotent(db, monkeypatch):
    text = "observation_date,UNRATE\n2024-01-01,3.7\n2024-02-01,3.9\n"
    monkeypatch.setattr(fred, "fetch_series", lambda sid: fred.parse_csv(sid, text, 38))
    for _ in range(2):
        jobs.ingest_macro(db, "UNRATE")
    rows = db.scalars(select(MacroObservation).order_by(MacroObservation.observation_date)).all()
    assert len(rows) == 2
    assert rows[0].observation_date == date(2024, 1, 1) and rows[0].published_date == date(2024, 2, 8)
    assert rows[0].pit_quality == "assumed_lag" and rows[0].ingested_at is not None


def test_fundamentals_ingestion_resolves_cik_and_dedupes(db, monkeypatch):
    _inst(db)
    monkeypatch.setattr(jobs, "_ticker_map", {"TST": {"cik": "0000320193", "name": "Test Inc"}})
    monkeypatch.setattr(sec_edgar, "fetch_sic_description", lambda c: "Electronic Computers")
    monkeypatch.setattr(sec_edgar, "fetch_company_facts", lambda s, c: sec_edgar.parse_company_facts(s, SEC))
    for _ in range(2):
        jobs.ingest_fundamentals(db, "TST")
    assert db.scalar(select(func.count()).select_from(Fundamental)) == 1
    i = db.scalar(select(Instrument))
    assert i.cik == "0000320193" and i.sector == "Electronic Computers"


def test_upsert_updates_when_requested(db):
    i = _inst(db)
    row = dict(instrument_id=i.id, date=date(2024, 1, 2), provider="yahoo", close=1.0)
    upsert(db, Price.__table__, [row], ["instrument_id", "date", "provider"], ["close"])
    upsert(db, Price.__table__, [{**row, "close": 2.0}], ["instrument_id", "date", "provider"], ["close"])
    db.commit()
    assert db.scalar(select(Price.close)) == 2.0
