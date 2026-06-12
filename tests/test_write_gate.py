from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.slack_events import ApprovalAction
from bookkeeper_agent.connectors.types import Vendor
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent
from bookkeeper_agent.pipeline.store import PendingBillRepo
from bookkeeper_agent.pipeline.writegate import ApprovalGate, WriteOutcome

REALM = "111"


def _seed_pending(engine, **over):
    repo = PendingBillRepo(engine)
    fields = dict(
        client_key="habit-pilates", company_realm=REALM,
        source_mailbox="habit@unionstreet.io", source_message_id="m1",
        vendor_name="ACME", is_new_vendor=False, vendor_id="V1",
        doc_number="INV-100", txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
        total=Decimal("250.00"), currency="USD",
        proposed_account_id="A1", proposed_account_name="Supplies",
        confidence=0.9, reasoning="precedent", pdf_filename="invoice.pdf", pdf_bytes=b"%PDF",
    )
    fields.update(over)
    pid = repo.create(**fields)
    repo.set_status(pid, "pending", slack_channel="C-APPROVALS", slack_ts="1.0001")
    return repo, pid


def _gate(engine, qbo, slack):
    return ApprovalGate(qbo=qbo, slack=slack, pending_repo=PendingBillRepo(engine), engine=engine)


def _approve_action():
    return ApprovalAction(action="approve", channel="C-APPROVALS", message_ts="1.0001", user="U1")


def test_approve_existing_vendor_posts_bill_attaches_pdf_updates_card(engine):
    repo, pid = _seed_pending(engine)
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())

    assert result.outcome == WriteOutcome.POSTED and result.bill_id
    realm, draft = qbo.created_bills[0]
    assert realm == REALM
    assert draft.vendor_id == "V1"
    assert draft.lines[0].account_id == "A1" and draft.lines[0].amount == Decimal("250.00")
    assert qbo.attachments and qbo.attachments[0][0] == REALM
    row = repo.get(pid)
    assert row.status == "posted" and row.posted_bill_id == result.bill_id
    assert slack.updates and slack.updates[0][0] == "C-APPROVALS" and slack.updates[0][1] == "1.0001"
    with session_scope(engine) as s:
        kinds = {e.kind for e in s.query(AuditEvent).all()}
    assert "write" in kinds


def test_approve_new_vendor_creates_vendor_first(engine):
    repo, pid = _seed_pending(engine, is_new_vendor=True, vendor_id=None, vendor_name="Brand New Co")
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.POSTED
    assert qbo.created_vendors and qbo.created_vendors[0][0] == REALM
    _realm, draft = qbo.created_bills[0]
    assert draft.vendor_id == qbo.find_vendor(REALM, "Brand New Co").id


def test_reject_marks_rejected_no_qbo_write(engine):
    repo, pid = _seed_pending(engine)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    action = ApprovalAction(action="reject", channel="C-APPROVALS", message_ts="1.0001", user="U1")
    result = _gate(engine, qbo, slack).handle(action)
    assert result.outcome == WriteOutcome.REJECTED
    assert qbo.created_bills == []
    assert repo.get(pid).status == "rejected"
    assert slack.updates


def test_already_resolved_is_noop(engine):
    repo, pid = _seed_pending(engine)
    repo.set_status(pid, "posted", resolved=True, posted_bill_id="B9")
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.ALREADY_RESOLVED
    assert qbo.created_bills == []


def test_not_found_for_unknown_message(engine):
    _seed_pending(engine)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    action = ApprovalAction(action="approve", channel="C-APPROVALS", message_ts="9.9", user="U1")
    assert _gate(engine, qbo, slack).handle(action).outcome == WriteOutcome.NOT_FOUND


def test_missing_account_errors_without_posting(engine):
    repo, pid = _seed_pending(engine, proposed_account_id=None)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.ERROR
    assert qbo.created_bills == []
    assert repo.get(pid).status == "error"
    assert slack.updates


def test_double_approve_does_not_double_post(engine):
    repo, pid = _seed_pending(engine)
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    slack = FakeSlackConnector()
    gate = _gate(engine, qbo, slack)
    first = gate.handle(_approve_action())
    second = gate.handle(_approve_action())  # re-delivered Slack event
    assert first.outcome == WriteOutcome.POSTED
    assert second.outcome == WriteOutcome.ALREADY_RESOLVED
    assert len(qbo.created_bills) == 1  # never double-posted
