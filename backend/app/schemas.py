from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    exchange: str
    name: str | None
    instrument_type: str
    currency: str | None
    country: str | None
    sector: str | None
    industry: str | None
    cik: str | None
    metadata_source: str | None


class PricePoint(BaseModel):
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: int | None
    provider: str


class PriceSeries(BaseModel):
    instrument_id: int
    symbol: str
    count: int
    last_date: date | None
    last_ingested_at: datetime | None
    stale: bool
    prices: list[PricePoint]


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    instrument_id: int
    symbol: str | None = None
    horizon_days: int
    horizon_label: str
    model_name: str
    model_version: str
    feature_version: str
    created_at: datetime
    data_cutoff: date
    expected_return: float | None
    prob_up: float | None
    prob_down: float | None
    interval_low: float | None
    interval_high: float | None
    interval_level: float | None
    interval_method: str | None
    hist_vol_ann: float | None
    est_vol_ann: float | None
    validation_status: str
    evidence: dict | None = None


class ScreenerRow(BaseModel):
    id: int
    symbol: str
    name: str | None
    instrument_type: str
    sector: str | None
    price: float | None
    price_date: date | None
    ret_1d: float | None
    ret_1m: float | None
    ret_3m: float | None
    ret_1y: float | None
    pe: float | None
    ps: float | None
    revenue_growth: float | None
    net_income_growth: float | None
    forecast_horizon_days: int
    forecast_id: int | None
    prob_up: float | None
    expected_return: float | None
    interval_low: float | None
    interval_high: float | None
    validation_status: str | None
    data_cutoff: date | None


class BacktestSummary(BaseModel):
    id: int
    instrument_id: int
    symbol: str
    model_name: str
    model_version: str
    horizon_days: int
    created_at: datetime
    data_cutoff: date
    n_obs: int
    start_date: date | None
    end_date: date | None
    validation_status: str
    validation_reasons: list[str] | None
    brier: float | None
    brier_baseline: float | None
    brier_skill: float | None
    log_loss: float | None
    ece: float | None
    balanced_accuracy: float | None
    directional_accuracy: float | None
    mae: float | None
    mae_baseline: float | None
    rmse: float | None


class JobOut(BaseModel):
    job_id: str
    kind: str
    status: str
    detail: str | None = None
