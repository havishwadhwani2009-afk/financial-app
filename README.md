# FinIntel — financial research & validated forecasting platform

A research and decision-support tool. It stores real provider data, computes point-in-time features,
produces probabilistic forecasts, and **evaluates them out-of-sample** so you can see when they are *not* better
than a naive baseline. Forecasts are model estimates — never facts, advice, or guarantees.

```
frontend/   Next.js 15 + React 19 + TypeScript + Tailwind + TanStack Query + Recharts
backend/    FastAPI + SQLAlchemy 2 + Alembic + pandas/scikit-learn/statsmodels
  app/providers/    one adapter per source (yahoo, stooq, fred, sec_edgar)
  app/ingestion/    idempotent upserts, run history (ingestion_runs)
  app/forecasting/  features (point-in-time), models, purged walk-forward backtest, persistence
  app/analysis/     fundamentals normalisation/ratios, macro indicators, scenario sensitivities
  app/routers/      public API + token-protected admin API
  tests/            pytest suite (providers, ingestion, leakage, walk-forward, API, analysis)
```

## Status — read this first

| Area | State |
|---|---|
| Schema, migrations, FastAPI, 7-page frontend, CLI, tests | **Built; 41 backend tests pass; frontend type-checks and builds** |
| Provider adapters (Yahoo, Stooq, FRED, SEC EDGAR) | **Built and unit-tested against recorded-format payloads. Not yet exercised against the live services** — the development sandbox's network policy blocked all four hosts (HTTP 403 at the proxy). Run `python -m app.cli check-providers` on a networked machine first. |
| Real-data end-to-end verification | **Pending** (needs the step above). No mock data is ever written to the app database; screens show explicit empty states until real data is ingested. |
| Forecast models | Baseline mean, regularised logistic+ridge (primary), random forest. **Honest caveat:** shrinkage was set on synthetic series (≈0 skill on random walks, positive when a signal exists). Real markets are close to random walks at these horizons, so expect many "No edge vs baseline" statuses and read them as the correct answer. |
| Not implemented | News/events feed, AI research assistant, watchlists/auth, ETF holdings/expense ratios (no free provider integrated), Alpha Vantage adapter, regime-conditional macro sensitivities, peer comparisons, TTM fundamentals, market breadth, economic release calendar, Celery/Redis (not needed yet). |

## Data sources and limitations

| Source | Use | Notes |
|---|---|---|
| Yahoo Finance chart endpoint | prices, dividends, splits (primary) | **Unofficial**, undocumented, may change or throttle; delayed quotes; metadata (sector/holdings) not provided. |
| Stooq CSV | secondary prices | Access has been tightening (may need `STOOQ_API_KEY`); unadjusted closes only. Unverified. |
| FRED | macro series (official) | With `FRED_API_KEY` (free) every real-time **vintage** is stored → true point-in-time. Without it, the public CSV is used and publication dates are **assumed** (observation date + typical lag), flagged `pit_quality=assumed_lag`. |
| SEC EDGAR XBRL company facts | fundamentals (official, US filers) | Needs a contact in `SEC_USER_AGENT`. Each fact keeps its `filed` date (public availability). Annual (10-K) metrics only; non-USD facts are excluded rather than converted. |

No single free provider covers every market or period. International equities, funds' holdings and expense ratios are not covered yet.

## Prerequisites
Python 3.11+ (3.12 used), Node 20+, PostgreSQL 14+ (or Docker).

## Setup — local (no Docker)

```bash
cp .env.example .env            # edit: ADMIN_TOKEN, FRED_API_KEY, SEC_USER_AGENT
# PostgreSQL: create the role/db (or point DATABASE_URL elsewhere)
createuser -P finapp   # password: finapp (dev default)
createdb -O finapp finapp

cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m app.cli migrate
python -m pytest                                  # needs DB finapp_test (createdb -O finapp finapp_test)
uvicorn app.main:app --port 8000                  # API docs: http://localhost:8000/docs

cd ../frontend
cp .env.example .env.local
npm install
npm run dev                                       # http://localhost:3000
```

## Setup — Docker Compose
```bash
cp .env.example .env
docker compose up --build      # db + api (:8000) + web (:3000); migrations run on API start
```

## Load data (run on a machine with internet access)

```bash
cd backend && . .venv/bin/activate
python -m app.cli check-providers          # verifies each live provider; fix before continuing
python -m app.cli seed                      # providers + curated universe (26 stocks, 19 ETFs, 5 indices)
python -m app.cli ingest --kind all         # macro (FRED) + prices (Yahoo) + fundamentals (SEC); idempotent
python -m app.cli forecast                  # features -> walk-forward backtests -> forecasts (5 horizons)
```
Per-job outcomes are in `ingestion_runs` and on the Overview page / `GET /api/status`.
Re-running ingestion never duplicates rows. Schedule `ingest` then `forecast` daily with cron or a CI scheduler.
The same jobs are available as `POST /api/admin/ingest` and `POST /api/admin/forecast` with header
`X-Admin-Token: $ADMIN_TOKEN` (disabled entirely if `ADMIN_TOKEN` is unset).

## How forecasts are made and judged

* **Horizons:** 5/21/63/126/252 trading days = 1 week / 1 / 3 / 6 / 12 months.
* **Features (`f1`):** multi-horizon log returns, rolling volatility, moving-average ratios, drawdown, volume z-score,
  market (SPY) and relative returns, and macro levels/changes. Macro values are aligned by **publication date**
  (`merge_asof` on `published_date`) and use the vintage known on that date. Fundamentals are *not* model inputs yet.
* **Targets:** forward log return; never part of X.
* **Models:** `baseline_mean` (historical frequency/mean), `linear` (L2 logistic for P(up) + ridge for return; primary),
  `random_forest`. Imputation and scaling are fitted inside each training window only. Hyper-parameters are fixed a priori.
* **Walk-forward:** expanding window, refit every 21 rows, trained only on rows whose label window has elapsed
  (`j + h <= refit date`, i.e. purged). Predictions use the frozen model until the next refit.
* **Intervals:** 90% interval from empirical quantiles of the walk-forward out-of-sample residuals when ≥100 exist;
  otherwise a volatility-scaled normal approximation labelled **UNVALIDATED**. Overlapping windows make coverage approximate.
* **Validation status** (explicit gate in `backtest.validation_status`): `insufficient_data` (<250 OOS obs or <20
  effective independent obs) → `no_edge_over_baseline` (Brier or log loss not better than the base rate) →
  `poorly_calibrated` (ECE > 0.10) → `unstable` (skill sign differs between halves) → `validated`.
  "Validated" never means profitable or reliable going forward.
* **Persistence:** forecasts, model versions, backtest runs and thinned OOS predictions are append-only, with
  created-at, data cutoff, horizon, model & feature version, interval and status.
* **Strategy test:** long/cash on P(up)>0.55 with 5 bp one-way cost; reports exposure, turnover, vol, drawdown, Sharpe vs buy-and-hold.

## Tests
```bash
cd backend && python -m pytest -q        # providers, idempotent ingestion, no-lookahead features,
                                          # macro point-in-time, purged walk-forward, metrics, API, analysis
cd frontend && npx tsc --noEmit && npm run build
```
Tests use small **synthetic** fixtures that exist only inside the test suite.

## Security & reliability notes
Env-based config, no secrets in git, admin endpoints off by default and token-protected (constant-time compare),
CORS allow-list, per-IP rate limiting (`RATE_LIMIT`), typed/validated inputs, consistent error envelope
`{"error":{"code","message"}}`, bounded retries with backoff, provider responses treated as untrusted
(parsed defensively; bad rows counted as `rows_rejected`), failures recorded rather than raised in batch jobs.
