from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bookkeeper_agent.db.base import Base
from bookkeeper_agent.db.types import DecimalText


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthToken(Base):
    """Encrypted secret for a service connection.

    service: "qbo" | "slack" | "google" | "microsoft"
    ref: discriminator within a service (e.g. QBO realm_id; "default" for app-level).
    secret_ciphertext: TokenCipher-encrypted bytes.
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("service", "ref", name="uq_service_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(128), default="default")
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class CostRecord(Base):
    """One row per Claude API call, used for spend tracking and usage audit."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_utcnow)
    ym: Mapped[str] = mapped_column(String(7))  # "YYYY-MM"
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0)
    usd: Mapped[float] = mapped_column(default=0.0)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEvent(Base):
    """Append-only forensic record. Never updated or deleted in code."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=_utcnow)
    kind: Mapped[str] = mapped_column(String(32))  # read|proposal|approval|rejection|write|system
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    company_realm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(nullable=True)


class PendingBill(Base):
    """A proposed bill awaiting Slack approval. The restart-surviving queue.
    Unique on (client_key, source_message_id) so one email proposes one bill."""

    __tablename__ = "pending_bills"
    __table_args__ = (UniqueConstraint("client_key", "source_message_id", name="uq_pending_msg"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected|posted|error

    client_key: Mapped[str] = mapped_column(String(64))
    company_realm: Mapped[str] = mapped_column(String(64))
    source_mailbox: Mapped[str] = mapped_column(String(255))
    source_message_id: Mapped[str] = mapped_column(String(255))

    vendor_name: Mapped[str] = mapped_column(String(255))
    is_new_vendor: Mapped[bool] = mapped_column(default=False)
    vendor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doc_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    txn_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    total: Mapped[Decimal] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    proposed_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposed_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.0)
    reasoning: Mapped[str | None] = mapped_column(nullable=True)

    pdf_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    slack_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(64), nullable=True)
    posted_bill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)


class Checkpoint(Base):
    """Per-mailbox 'last processed' marker the poller advances after handling."""

    __tablename__ = "checkpoints"

    mailbox: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_epoch_ms: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
