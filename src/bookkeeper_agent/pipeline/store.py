from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import Checkpoint, PendingBill


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PendingBillRepo:
    """CRUD for the PendingBill approval queue. Returned rows are detached so
    callers can read attributes after the session closes."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def create(self, **fields: Any) -> int:
        with session_scope(self._engine) as s:
            row = PendingBill(**fields)
            s.add(row)
            s.flush()
            return row.id

    def get(self, pending_id: int) -> PendingBill | None:
        with session_scope(self._engine) as s:
            row = s.get(PendingBill, pending_id)
            if row is not None:
                s.expunge(row)
            return row

    def list_pending(self) -> list[PendingBill]:
        with session_scope(self._engine) as s:
            rows = list(
                s.execute(
                    select(PendingBill).where(PendingBill.status == "pending").order_by(PendingBill.id)
                ).scalars().all()
            )
            for r in rows:
                s.expunge(r)
            return rows

    def find_by_message(self, client_key: str, source_message_id: str) -> PendingBill | None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(PendingBill).where(
                    PendingBill.client_key == client_key,
                    PendingBill.source_message_id == source_message_id,
                )
            ).scalar_one_or_none()
            if row is not None:
                s.expunge(row)
            return row

    def set_status(
        self,
        pending_id: int,
        status: str,
        *,
        resolved: bool = False,
        posted_bill_id: str | None = None,
        slack_channel: str | None = None,
        slack_ts: str | None = None,
        error: str | None = None,
    ) -> None:
        with session_scope(self._engine) as s:
            row = s.get(PendingBill, pending_id)
            if row is None:
                raise KeyError(pending_id)
            row.status = status
            if resolved:
                row.resolved_at = _utcnow()
            if posted_bill_id is not None:
                row.posted_bill_id = posted_bill_id
            if slack_channel is not None:
                row.slack_channel = slack_channel
            if slack_ts is not None:
                row.slack_ts = slack_ts
            if error is not None:
                row.error = error


class CheckpointRepo:
    """Per-mailbox poller cursor (last processed epoch-ms)."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def get(self, mailbox: str) -> int:
        with session_scope(self._engine) as s:
            row = s.get(Checkpoint, mailbox)
            return row.last_epoch_ms if row is not None else 0

    def set(self, mailbox: str, last_epoch_ms: int) -> None:
        with session_scope(self._engine) as s:
            row = s.get(Checkpoint, mailbox)
            if row is None:
                s.add(Checkpoint(mailbox=mailbox, last_epoch_ms=last_epoch_ms))
            else:
                row.last_epoch_ms = last_epoch_ms
