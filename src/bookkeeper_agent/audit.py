from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent


def record_event(
    session: Session,
    kind: str,
    summary: str,
    client_key: str | None = None,
    company_realm: str | None = None,
    request_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event. Append-only: there is no update/delete API."""
    session.add(AuditEvent(
        kind=kind,
        summary=summary,
        client_key=client_key,
        company_realm=company_realm,
        request_id=request_id,
        detail_json=json.dumps(detail) if detail is not None else None,
    ))


def list_events(
    engine: Engine,
    client_key: str | None = None,
    kind: str | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id)
    if client_key is not None:
        stmt = stmt.where(AuditEvent.client_key == client_key)
    if kind is not None:
        stmt = stmt.where(AuditEvent.kind == kind)
    with session_scope(engine) as s:
        rows = list(s.execute(stmt).scalars().all())
        # Detach so callers can read attributes after the session closes.
        for r in rows:
            s.expunge(r)
        return rows
