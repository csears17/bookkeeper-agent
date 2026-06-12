from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    VendorAccountStat,
    Vendor,
)
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent
from bookkeeper_agent.llm.client import FakeLlmClient
from bookkeeper_agent.llm.types import BillExtraction, CategorySuggestion
from bookkeeper_agent.pipeline.intake import BillIntake
from bookkeeper_agent.pipeline.process import BillsPipeline, IntakeOutcome
from bookkeeper_agent.pipeline.store import PendingBillRepo

REALM = "111"


def _intake(**over):
    base = dict(
        source="email", source_id="m1", source_ref="habit@unionstreet.io",
        client_key="habit-pilates", client_display="Habit Pilates", company_realm=REALM,
        sender="v@acme.com", subject="Invoice 100", body_text="amount due",
        attachments=(Attachment("invoice.pdf", "application/pdf", b"%PDF-bytes"),),
        skip_classification=False,
    )
    base.update(over)
    return BillIntake(**base)


def _extraction(**over):
    base = dict(is_bill=True, classification_confidence=0.95, vendor_name="ACME",
                doc_number="INV-100", txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
                total=Decimal("250.00"), currency="USD", line_hint="Supplies")
    base.update(over)
    return BillExtraction(**base)


def _suggestion():
    return CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="precedent")


def _pipeline(engine, llm, qbo, slack):
    return BillsPipeline(llm=llm, qbo=qbo, slack=slack,
                         pending_repo=PendingBillRepo(engine), engine=engine,
                         approval_channel="C-APPROVALS")


def test_proposes_bill_for_existing_vendor(engine):
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    qbo.seed_account_history(REALM, "V1", [VendorAccountStat("A1", "Supplies", 3)])
    llm = FakeLlmClient(extraction=_extraction(), suggestion=_suggestion())
    slack = FakeSlackConnector()
    result = _pipeline(engine, llm, qbo, slack).process(_intake())

    assert result.outcome == IntakeOutcome.PROPOSED
    row = PendingBillRepo(engine).get(result.pending_id)
    assert row.company_realm == REALM
    assert row.total == Decimal("250.00")
    assert row.is_new_vendor is False
    assert row.vendor_id == "V1"
    assert row.pdf_bytes == b"%PDF-bytes"
    assert row.proposed_account_name == "Supplies"
    assert row.slack_ts
    channel, proposal = slack.posted[0]
    assert channel == "C-APPROVALS"
    assert proposal.company_realm == REALM
    assert proposal.vendor_name == "ACME"
    cctx = llm.categorize_calls[0]
    assert "Supplies: 3 prior bill(s)" in cctx.precedents
    assert cctx.accounts[0].id == "A1"


def test_proposes_with_new_vendor_flag(engine):
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    llm = FakeLlmClient(extraction=_extraction(vendor_name="Brand New Co"), suggestion=_suggestion())
    slack = FakeSlackConnector()
    result = _pipeline(engine, llm, qbo, slack).process(_intake())
    assert result.outcome == IntakeOutcome.PROPOSED
    row = PendingBillRepo(engine).get(result.pending_id)
    assert row.is_new_vendor is True
    assert row.vendor_id is None


def test_not_candidate_is_dropped_without_content_in_audit(engine):
    qbo = FakeQboConnector()
    llm = FakeLlmClient()  # never called
    slack = FakeSlackConnector()
    intake = _intake(subject="Lunch tomorrow?", body_text="see you at noon", attachments=())
    result = _pipeline(engine, llm, qbo, slack).process(intake)

    assert result.outcome == IntakeOutcome.NOT_CANDIDATE
    assert llm.classify_calls == []
    assert slack.posted == []
    assert PendingBillRepo(engine).list_pending() == []
    with session_scope(engine) as s:
        blob = " ".join(e.summary + (e.detail_json or "") for e in s.query(AuditEvent).all())
    assert "Lunch tomorrow" not in blob and "see you at noon" not in blob


def test_classified_not_a_bill_is_dropped(engine):
    qbo = FakeQboConnector()
    llm = FakeLlmClient(extraction=_extraction(is_bill=False, vendor_name=None))
    slack = FakeSlackConnector()
    result = _pipeline(engine, llm, qbo, slack).process(_intake())
    assert result.outcome == IntakeOutcome.NOT_A_BILL
    assert slack.posted == []
    assert PendingBillRepo(engine).list_pending() == []


def test_duplicate_is_blocked(engine):
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    qbo.seed_bill(REALM, Bill(id="B9", vendor_id="V1", total=Decimal("250.00"), doc_number="INV-100"))
    llm = FakeLlmClient(extraction=_extraction(), suggestion=_suggestion())
    slack = FakeSlackConnector()
    result = _pipeline(engine, llm, qbo, slack).process(_intake())
    assert result.outcome == IntakeOutcome.DUPLICATE
    assert slack.posted == []
    assert PendingBillRepo(engine).list_pending() == []


def test_idempotent_second_run_is_already_seen(engine):
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    llm = FakeLlmClient(extraction=_extraction(), suggestion=_suggestion())
    slack = FakeSlackConnector()
    pipe = _pipeline(engine, llm, qbo, slack)
    first = pipe.process(_intake())
    second = pipe.process(_intake())
    assert first.outcome == IntakeOutcome.PROPOSED
    assert second.outcome == IntakeOutcome.ALREADY_SEEN
    assert len(slack.posted) == 1


def test_slack_drop_skips_gates_and_proposes_even_if_model_unsure(engine):
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    llm = FakeLlmClient(extraction=_extraction(is_bill=False), suggestion=_suggestion())
    slack = FakeSlackConnector()
    drop = _intake(source="slack-drop", source_id="F123", source_ref="C-DROPS",
                   subject="", body_text="", skip_classification=True)
    result = _pipeline(engine, llm, qbo, slack).process(drop)
    assert result.outcome == IntakeOutcome.PROPOSED
    assert len(slack.posted) == 1
