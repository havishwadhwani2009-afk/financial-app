"""Command-line tasks (use these from cron / a scheduler; long jobs never run inside web requests).

  python -m app.cli migrate            apply Alembic migrations
  python -m app.cli seed               register providers + seed instrument universe
  python -m app.cli ingest [--kind all|prices|macro|fundamentals] [--symbols AAPL SPY]
  python -m app.cli forecast [--symbols SPY] [--horizons 21 63]
  python -m app.cli check-providers    live reachability / parsing check of every provider
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from sqlalchemy import select

from app.db import session_scope
from app.forecasting.features import HORIZONS
from app.forecasting.service import forecast_all
from app.ingestion import jobs
from app.ingestion.universe import STOCKS
from app.models import Instrument
from app.providers import fred, sec_edgar, stooq, yahoo


def check_providers() -> int:
    checks = {
        "yahoo (prices, unofficial)": lambda: len(yahoo.fetch_prices("SPY", "5d").bars),
        "stooq (prices, secondary)": lambda: len(stooq.fetch_prices("SPY").bars),
        "fred (macro, official)": lambda: len(fred.fetch_series("DGS10").points),
        "sec_edgar (fundamentals, official)": lambda: len(sec_edgar.fetch_company_facts("AAPL", "0000320193").facts),
    }
    bad = 0
    for name, fn in checks.items():
        try:
            print(f"OK    {name}: {fn()} records")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL  {name}: {e}")
    return 1 if bad else 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("check-providers")
    i = sub.add_parser("ingest")
    i.add_argument("--kind", default="all", choices=["all", "prices", "macro", "fundamentals"])
    i.add_argument("--symbols", nargs="*")
    f = sub.add_parser("forecast")
    f.add_argument("--symbols", nargs="*")
    f.add_argument("--horizons", nargs="*", type=int, default=list(HORIZONS))
    a = ap.parse_args(argv)

    if a.cmd == "migrate":
        return subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"])
    if a.cmd == "check-providers":
        return check_providers()
    with session_scope() as db:
        if a.cmd == "seed":
            jobs.seed_providers(db)
            print("seeded", jobs.seed_universe(db), "instruments")
        elif a.cmd == "ingest":
            jobs.seed_providers(db)
            jobs.seed_universe(db)
            syms = [s.upper() for s in a.symbols] if a.symbols else None
            if a.kind in ("all", "macro"):
                for sid in fred.SERIES:
                    jobs.ingest_macro(db, sid)
            if a.kind in ("all", "prices"):
                for s in syms or db.scalars(select(Instrument.symbol)).all():
                    jobs.ingest_prices(db, s)
            if a.kind in ("all", "fundamentals"):
                for s in syms or STOCKS:
                    jobs.ingest_fundamentals(db, s)
            print("ingestion finished; see ingestion_runs / GET /api/status for per-job outcomes")
        elif a.cmd == "forecast":
            for h in a.horizons:
                if h not in HORIZONS:
                    ap.error(f"horizon must be in {sorted(HORIZONS)}")
            print("forecasts written:", forecast_all(db, [s.upper() for s in a.symbols] if a.symbols else None, tuple(a.horizons)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
