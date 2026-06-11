from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    BillLine,
    BillProposal,
    EmailMessage,
    MessageRef,
    SlackMessageRef,
    Vendor,
    VendorDraft,
)


def test_email_message_holds_attachments():
    att = Attachment(filename="invoice.pdf", mime_type="application/pdf", content=b"%PDF-1.4")
    msg = EmailMessage(
        id="m1",
        mailbox="habit@unionstreet.io",
        sender="vendor@acme.com",
        subject="Invoice 100",
        internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        snippet="Please find attached",
        attachments=(att,),
    )
    assert msg.attachments[0].filename == "invoice.pdf"
    assert msg.attachments[0].content == b"%PDF-1.4"


def test_message_ref():
    ref = MessageRef(id="m1", epoch_ms=1_000)
    assert ref.id == "m1" and ref.epoch_ms == 1_000


def test_bill_draft_and_lines():
    draft = BillDraft(
        vendor_id="V1",
        txn_date=date(2026, 6, 1),
        total=Decimal("250.00"),
        lines=(BillLine(amount=Decimal("250.00"), account_id="A1", description="Supplies"),),
        due_date=date(2026, 6, 30),
        doc_number="INV-100",
    )
    assert draft.currency == "USD"
    assert draft.lines[0].account_id == "A1"
    assert draft.due_date == date(2026, 6, 30)


def test_simple_value_objects():
    assert Vendor(id="V1", display_name="ACME").display_name == "ACME"
    assert VendorDraft(display_name="ACME").email is None
    assert Account(id="A1", name="Supplies", account_type="Expense").account_type == "Expense"
    assert Bill(id="B1", vendor_id="V1", total=Decimal("250.00")).doc_number is None
    assert SlackMessageRef(channel="C1", ts="1.0001").ts == "1.0001"


def test_bill_proposal_is_view_model():
    p = BillProposal(
        client_key="habit-pilates",
        client_display="Habit Pilates",
        company_realm="111",
        vendor_name="ACME",
        is_new_vendor=True,
        total=Decimal("250.00"),
        currency="USD",
        txn_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        doc_number="INV-100",
        proposed_account_name="Supplies",
        confidence=0.92,
        reasoning="Prior ACME bills booked to Supplies",
        pdf_filename="invoice.pdf",
    )
    assert p.is_new_vendor is True
    assert p.proposed_account_name == "Supplies"


def test_frozen():
    v = Vendor(id="V1", display_name="ACME")
    with pytest.raises(Exception):
        v.display_name = "x"  # type: ignore[misc]
