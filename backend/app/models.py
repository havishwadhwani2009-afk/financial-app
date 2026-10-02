"""Database schema. All timestamps are UTC. Raw observations are kept separate from derived data."""
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts():
    return mapped_column(DateTime(timezone=True), default=utcnow)


class DataProvider(Base):
    __tablename__ = "data_providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    kind: Mapped[str] = mapped_column(String(30))  # prices | fundamentals | macro
    base_url: Mapped[str] = mapped_column(String(200))
    official: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    job: Mapped[str] = mapped_column(String(50))
    target: Mapped[str | None] = mapped_column(String(100))  # symbol / series id
    status: Mapped[str] = mapped_column(String(20))  # running | ok | partial | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Instrument(Base):
    """Internal id is the identity; (symbol, exchange) is only a unique lookup key."""
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    exchange: Mapped[str] = mapped_column(String(20), default="US")
    name: Mapped[str | None] = mapped_column(String(200))
    instrument_type: Mapped[str] = mapped_column(String(20))  # stock | etf | mutual_fund | index | other
    currency: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(40))
    sector: Mapped[str | None] = mapped_column(String(120))
    industry: Mapped[str | None] = mapped_column(String(160))
    cik: Mapped[str | None] = mapped_column(String(10), index=True)
    metadata_source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_instrument_symbol_exchange"),
                      Index("ix_instruments_name", "name"))


class Price(Base):
    __tablename__ = "prices"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    action_type: Mapped[str] = mapped_column(String(12), primary_key=True)  # dividend | split
    value: Mapped[float] = mapped_column(Float)  # cash per share, or split ratio (new/old)
    provider: Mapped[str] = mapped_column(String(50))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Fundamental(Base):
    """One XBRL fact as reported in one filing. `filed` is the public availability date (point-in-time)."""
    __tablename__ = "fundamentals"
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    concept: Mapped[str] = mapped_column(String(40))  # normalised concept, e.g. revenue
    source_tag: Mapped[str] = mapped_column(String(120))  # original taxonomy tag
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(4))  # FY, Q1..Q4
    form: Mapped[str | None] = mapped_column(String(12))
    filed: Mapped[date] = mapped_column(Date)
    accession: Mapped[str] = mapped_column(String(30))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(50))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("instrument_id", "concept", "source_tag", "period_start", "period_end",
                         "accession", name="uq_fundamental_fact"),
        Index("ix_fund_lookup", "instrument_id", "concept", "period_end"),
    )


class MacroSeries(Base):
    __tablename__ = "macro_series"
    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    units: Mapped[str | None] = mapped_column(String(80))
    frequency: Mapped[str | None] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(50))
    # Conservative publication lag (days) used ONLY when no vintage/release date is available.
    assumed_lag_days: Mapped[int] = mapped_column(Integer, default=1)


class MacroObservation(Base):
    """observation_date = period the value describes; published_date = first date value was public
    (FRED real-time start when available, else observation_date + assumed lag); ingested_at = our clock."""
    __tablename__ = "macro_observations"
    series_id: Mapped[str] = mapped_column(ForeignKey("macro_series.series_id"), primary_key=True)
    observation_date: Mapped[date] = mapped_column(Date, primary_key=True)
    published_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    pit_quality: Mapped[str] = mapped_column(String(16))  # vintage | assumed_lag
    provider: Mapped[str] = mapped_column(String(50))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    feature_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("name", "version", "feature_version", name="uq_model_version"),)


class DerivedFeature(Base):
    """Feature snapshot used for a forecast (derived, never source data)."""
    __tablename__ = "derived_features"
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    asof_date: Mapped[date] = mapped_column(Date, primary_key=True)
    feature_version: Mapped[str] = mapped_column(String(20), primary_key=True)
    feature_values: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Forecast(Base):
    """Append-only. A new forecast never overwrites an old one."""
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_cutoff: Mapped[date] = mapped_column(Date)  # last market date used
    horizon_days: Mapped[int] = mapped_column(Integer)
    expected_return: Mapped[float | None] = mapped_column(Float)  # simple return over horizon
    prob_up: Mapped[float | None] = mapped_column(Float)
    prob_down: Mapped[float | None] = mapped_column(Float)
    interval_low: Mapped[float | None] = mapped_column(Float)
    interval_high: Mapped[float | None] = mapped_column(Float)
    interval_level: Mapped[float | None] = mapped_column(Float)
    interval_method: Mapped[str | None] = mapped_column(String(300))
    hist_vol_ann: Mapped[float | None] = mapped_column(Float)
    est_vol_ann: Mapped[float | None] = mapped_column(Float)
    feature_version: Mapped[str] = mapped_column(String(20))
    validation_status: Mapped[str] = mapped_column(String(24))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    model_version: Mapped[ModelVersion] = relationship()
    __table_args__ = (Index("ix_forecast_lookup", "instrument_id", "horizon_days", "created_at"),)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    horizon_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_cutoff: Mapped[date] = mapped_column(Date)
    n_obs: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    config: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    calibration: Mapped[list | None] = mapped_column(JSON)
    strategy: Mapped[dict | None] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(24))
    validation_reasons: Mapped[list | None] = mapped_column(JSON)
    model_version: Mapped[ModelVersion] = relationship()


class BacktestPrediction(Base):
    """Walk-forward out-of-sample prediction vs realised outcome."""
    __tablename__ = "backtest_predictions"
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), primary_key=True)
    asof_date: Mapped[date] = mapped_column(Date, primary_key=True)
    prob_up: Mapped[float] = mapped_column(Float)
    baseline_prob_up: Mapped[float] = mapped_column(Float)
    pred_return: Mapped[float] = mapped_column(Float)
    baseline_return: Mapped[float] = mapped_column(Float)
    actual_return: Mapped[float] = mapped_column(Float)
