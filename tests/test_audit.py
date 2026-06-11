import json

from bookkeeper_agent.audit import list_events, record_event
from bookkeeper_agent.db.base import session_scope


def test_record_and_list(engine):
    with session_scope(engine) as s:
        record_event(s, kind="proposal", summary="Proposed bill for ACME",
                     client_key="habit-pilates", company_realm="111",
                     request_id="req_1", detail={"amount": 250.0})
        record_event(s, kind="write", summary="Created bill 42",
                     client_key="habit-pilates", company_realm="111")

    events = list_events(engine)
    assert len(events) == 2
    kinds = {e.kind for e in events}
    assert kinds == {"proposal", "write"}
    proposal = next(e for e in events if e.kind == "proposal")
    assert json.loads(proposal.detail_json)["amount"] == 250.0


def test_list_filter_by_client(engine):
    with session_scope(engine) as s:
        record_event(s, kind="write", summary="a", client_key="habit-pilates", company_realm="111")
        record_event(s, kind="write", summary="b", client_key="2expect", company_realm="222")

    only = list_events(engine, client_key="2expect")
    assert len(only) == 1
    assert only[0].company_realm == "222"
