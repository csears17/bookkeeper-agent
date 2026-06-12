from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.types import Account, Attachment


@dataclass(frozen=True)
class EmailContext:
    """What the classifier/extractor sees about one email."""

    sender: str
    subject: str
    body_text: str
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class BillExtraction:
    """Result of classify_and_extract. When is_bill is False the rest is unset."""

    is_bill: bool
    classification_confidence: float = 0.0
    vendor_name: str | None = None
    doc_number: str | None = None
    txn_date: date | None = None
    due_date: date | None = None
    total: Decimal | None = None
    currency: str = "USD"
    line_hint: str | None = None


@dataclass(frozen=True)
class CategorizationContext:
    """Inputs for category selection: the bill, the client's chart of accounts,
    and free-text precedent lines describing how prior bills were booked."""

    vendor_name: str
    total: Decimal
    accounts: tuple[Account, ...]
    precedents: tuple[str, ...] = ()
    line_hint: str | None = None


@dataclass(frozen=True)
class CategorySuggestion:
    account_id: str
    account_name: str
    confidence: float
    reasoning: str
