from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import IngestionRun

log = logging.getLogger(__name__)


def upsert(db: Session, table, rows: list[dict], index_elements: list[str],
           update_cols: list[str] | None = None, chunk: int = 2000) -> int:
    """Idempotent bulk insert. Existing keys are updated (update_cols) or left untouched.
    A multi-row INSERT takes its column list from the first row, so rows are grouped by key set to make sure
    no optional column is silently dropped (and column defaults still apply to omitted keys)."""
    if not rows:
        return 0
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dinsert
    else:
        from sqlalchemy.dialects.sqlite import insert as dinsert
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(sorted(r)), []).append(r)
    n = 0
    for grp in groups.values():
        for i in range(0, len(grp), chunk):
            part = grp[i:i + chunk]
            stmt = dinsert(table).values(part)
            if update_cols:
                cols = [c for c in update_cols if c in part[0]]
                stmt = stmt.on_conflict_do_update(index_elements=index_elements,
                                                  set_={c: getattr(stmt.excluded, c) for c in cols}) if cols \
                    else stmt.on_conflict_do_nothing(index_elements=index_elements)
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
            db.execute(stmt)
            n += len(part)
    return n


class Run:
    """Context manager recording an ingestion run (status, counts, error) in ingestion_runs."""

    def __init__(self, db: Session, provider: str, job: str, target: str | None = None):
        self.db, self.rec = db, IngestionRun(provider=provider, job=job, target=target, status="running")
        self.written = self.rejected = 0

    def __enter__(self) -> "Run":
        self.db.add(self.rec)
        self.db.commit()
        return self

    def __exit__(self, et, ev, tb) -> bool:
        self.db.rollback() if et else None
        rec = self.db.merge(self.rec)
        rec.finished_at = datetime.now(timezone.utc)
        rec.rows_written, rec.rows_rejected = self.written, self.rejected
        if et:
            rec.status, rec.error = "failed", f"{et.__name__}: {ev}"[:2000]
            log.warning("ingestion %s/%s %s failed: %s", rec.provider, rec.job, rec.target, ev)
        else:
            rec.status = "partial" if self.rejected else "ok"
        self.db.commit()
        return et is None or issubclass(et, Exception)  # record failures; never swallow Ctrl-C
