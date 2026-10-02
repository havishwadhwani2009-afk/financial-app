from __future__ import annotations

import logging
import threading
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from app.api_common import ApiError, limiter, require_admin
from app.db import session_scope
from app.forecasting.features import HORIZONS
from app.forecasting.service import forecast_all
from app.ingestion import jobs
from app.ingestion.universe import STOCKS
from app.providers import fred
from app.schemas import JobOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
log = logging.getLogger(__name__)
JOBS: dict[str, JobOut] = {}
_lock = threading.Lock()


class IngestRequest(BaseModel):
    kind: str = Field(pattern="^(all|prices|macro|fundamentals)$")
    symbols: list[str] | None = Field(default=None, max_length=100)


class ForecastRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, max_length=100)
    horizons: list[int] | None = None


def _run(job_id: str, fn) -> None:
    try:
        with session_scope() as db:
            fn(db)
        JOBS[job_id].status = "done"
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        JOBS[job_id].status, JOBS[job_id].detail = "failed", f"{type(e).__name__}: {e}"[:500]


def _enqueue(bg: BackgroundTasks, kind: str, fn) -> JobOut:
    with _lock:
        if any(j.status == "running" and j.kind == kind for j in JOBS.values()):
            raise ApiError(409, "job_running", f"A '{kind}' job is already running.")
        job = JobOut(job_id=uuid.uuid4().hex[:12], kind=kind, status="running")
        JOBS[job.job_id] = job
    bg.add_task(_run, job.job_id, fn)
    return job


@router.post("/ingest", response_model=JobOut, status_code=202)
@limiter.limit("6/minute")
def ingest(request: Request, body: IngestRequest, bg: BackgroundTasks):
    def fn(db):
        jobs.seed_providers(db)
        jobs.seed_universe(db)
        syms = [s.upper() for s in body.symbols] if body.symbols else None
        if body.kind == "all" and not syms:
            jobs.ingest_all(db)
            return
        if body.kind in ("macro", "all"):
            for sid in fred.SERIES:
                jobs.ingest_macro(db, sid)
        if body.kind in ("prices", "all"):
            from sqlalchemy import select
            from app.models import Instrument
            for s in syms or db.scalars(select(Instrument.symbol)).all():
                jobs.ingest_prices(db, s)
        if body.kind in ("fundamentals", "all"):
            for s in syms or STOCKS:
                jobs.ingest_fundamentals(db, s)
    return _enqueue(bg, f"ingest:{body.kind}", fn)


@router.post("/forecast", response_model=JobOut, status_code=202)
@limiter.limit("6/minute")
def generate_forecasts(request: Request, body: ForecastRequest, bg: BackgroundTasks):
    hs = tuple(body.horizons or HORIZONS)
    if any(h not in HORIZONS for h in hs):
        raise ApiError(422, "bad_horizon", f"horizons must be among {sorted(HORIZONS)}")
    return _enqueue(bg, "forecast", lambda db: forecast_all(db, [s.upper() for s in body.symbols] if body.symbols else None, hs))


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_status(job_id: str):
    j = JOBS.get(job_id)
    if j is None:
        raise ApiError(404, "not_found", "Unknown job")
    return j
