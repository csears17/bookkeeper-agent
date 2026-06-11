from datetime import datetime, timezone

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent, CostRecord, OAuthToken


def test_oauth_token_round_trip(engine):
    with session_scope(engine) as s:
        s.add(OAuthToken(service="qbo", ref="1234567890", secret_ciphertext=b"abc"))
    with session_scope(engine) as s:
        row = s.query(OAuthToken).filter_by(service="qbo", ref="1234567890").one()
        assert row.secret_ciphertext == b"abc"


def test_cost_record_and_audit_event_persist(engine):
    with session_scope(engine) as s:
        s.add(CostRecord(
            ym="2026-06", model="claude-opus-4-8", input_tokens=1000,
            output_tokens=500, cache_creation_input_tokens=0,
            cache_read_input_tokens=0, usd=0.0175, request_id="req_1",
            capability="bills",
        ))
        s.add(AuditEvent(kind="system", summary="started"))
    with session_scope(engine) as s:
        assert s.query(CostRecord).count() == 1
        ev = s.query(AuditEvent).one()
        assert ev.kind == "system"
        assert isinstance(ev.ts, datetime)
