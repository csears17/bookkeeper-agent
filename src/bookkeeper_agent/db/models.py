from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bookkeeper_agent.db.base import Base


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
