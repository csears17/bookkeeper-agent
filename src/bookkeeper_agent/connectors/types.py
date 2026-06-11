from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class MessageRef:
    """Lightweight pointer to a message (id + when), for listing before fetch."""

    id: str
    epoch_ms: int


@dataclass(frozen=True)
class EmailMessage:
    id: str
    mailbox: str
    sender: str
    subject: str
    internal_date: datetime
    snippet: str
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class Vendor:
    id: str
    display_name: str


@dataclass(frozen=True)
class VendorDraft:
    display_name: str
    email: str | None = None


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    account_type: str


@dataclass(frozen=True)
class BillLine:
    amount: float
    account_id: str
    description: str | None = None


@dataclass(frozen=True)
class BillDraft:
    vendor_id: str
    txn_date: date
    total: float
    lines: tuple[BillLine, ...]
    due_date: date | None = None
    doc_number: str | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class Bill:
    id: str
    vendor_id: str
    total: float
    doc_number: str | None = None


@dataclass(frozen=True)
class BillProposal:
    """View-model shown on the Slack approval card. Carries the fixed company
    binding (company_realm) so the card can display, and the writer can enforce,
    the target book."""

    client_key: str
    client_display: str
    company_realm: str
    vendor_name: str
    is_new_vendor: bool
    total: float
    currency: str
    txn_date: date
    due_date: date | None
    doc_number: str | None
    proposed_account_name: str
    confidence: float
    reasoning: str
    pdf_filename: str | None


@dataclass(frozen=True)
class SlackMessageRef:
    channel: str
    ts: str
