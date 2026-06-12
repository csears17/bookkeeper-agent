from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.types import Account, Attachment
from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


def test_email_context_defaults():
    ctx = EmailContext(sender="v@acme.com", subject="Invoice", body_text="hi")
    assert ctx.attachments == ()


def test_email_context_with_attachment():
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    ctx = EmailContext(sender="v@acme.com", subject="Invoice", body_text="hi", attachments=(att,))
    assert ctx.attachments[0].filename == "invoice.pdf"


def test_bill_extraction_not_a_bill():
    ex = BillExtraction(is_bill=False, classification_confidence=0.97)
    assert ex.is_bill is False
    assert ex.vendor_name is None
    assert ex.total is None
    assert ex.currency == "USD"


def test_bill_extraction_full():
    ex = BillExtraction(
        is_bill=True,
        classification_confidence=0.95,
        vendor_name="ACME",
        doc_number="INV-100",
        txn_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        total=Decimal("250.00"),
        currency="USD",
        line_hint="Cleaning supplies",
    )
    assert ex.total == Decimal("250.00")
    assert ex.line_hint == "Cleaning supplies"


def test_categorization_context_and_suggestion():
    ctx = CategorizationContext(
        vendor_name="ACME",
        total=Decimal("250.00"),
        accounts=(Account(id="A1", name="Supplies", account_type="Expense"),),
        precedents=("ACME -> Supplies (3 prior bills)",),
        line_hint="Cleaning supplies",
    )
    assert ctx.accounts[0].id == "A1"
    sug = CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="precedent")
    assert sug.account_id == "A1"


def test_frozen():
    sug = CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="x")
    with pytest.raises(Exception):
        sug.confidence = 0.1  # type: ignore[misc]
