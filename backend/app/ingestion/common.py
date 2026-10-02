from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import IngestionRun

log = logging.getLogger(__name__)


def upsert(db: Session, table, rows: list[dict], index_elements: list[str],
           update_cols: list[str] | None = None, chunk: int = 2000) -> int:
    """Idempotent bulk insert. Existing keys are updated (update_cols) or left untouched."""
    if not rows:
        return 0
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dinsert
    else:
        from sqlalchemy.dialects.sqlite import insert as dinsert
    n = 0
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        stmt = dinsert(table).values(part)
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=index_elements,
                                              set_={c: getattr(stmt.excluded, c) for c in update_cols})
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
