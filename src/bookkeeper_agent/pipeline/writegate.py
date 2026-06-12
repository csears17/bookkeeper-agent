from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from sqlalchemy.engine import Engine

from bookkeeper_agent.audit import record_event
from bookkeeper_agent.connectors.qbo import QboConnector
from bookkeeper_agent.connectors.slack import SlackConnector
from bookkeeper_agent.connectors.slack_events import ApprovalAction
from bookkeeper_agent.connectors.types import Attachment, BillDraft, BillLine, VendorDraft
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.pipeline.store import PendingBillRepo

_MIME_BY_EXT = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
}


def _mime_for(filename: str | None) -> str:
    name = (filename or "").lower()
    for ext, mime in _MIME_BY_EXT.items():
        if name.endswith(ext):
            return mime
    return "application/pdf"


class WriteOutcome(str, Enum):
    POSTED = "posted"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"
    ALREADY_RESOLVED = "already_resolved"
    ERROR = "error"


@dataclass(frozen=True)
class WriteResult:
    outcome: WriteOutcome
    bill_id: str | None = None
    detail: str | None = None


class ApprovalGate:
    """Turns a Slack Approve/Reject click into the real QBO write (or rejection).
    Idempotent (acts only on a still-pending bill), company-bound (every write uses
    the pending bill's fixed company_realm), and audited."""

    def __init__(self, *, qbo: QboConnector, slack: SlackConnector,
                 pending_repo: PendingBillRepo, engine: Engine):
        self._qbo = qbo
        self._slack = slack
        self._repo = pending_repo
        self._engine = engine

    def _audit(self, kind, summary, pending, detail=None):
        with session_scope(self._engine) as s:
            record_event(s, kind=kind, summary=summary,
                         client_key=pending.client_key, company_realm=pending.company_realm,
                         detail=detail)

    def handle(self, action: ApprovalAction) -> WriteResult:
        pending = self._repo.find_by_slack(action.channel, action.message_ts)
        if pending is None:
            return WriteResult(WriteOutcome.NOT_FOUND)
        if pending.status != "pending":
            return WriteResult(WriteOutcome.ALREADY_RESOLVED, detail=pending.status)
        if action.action == "reject":
            return self._reject(pending, action.user)
        return self._approve(pending, action.user)

    def _reject(self, pending, user) -> WriteResult:
        self._repo.set_status(pending.id, "rejected", resolved=True)
        self._slack.update_resolved(
            pending.slack_channel, pending.slack_ts,
            f":x: Rejected by <@{user}> — {pending.vendor_name} {pending.total} "
            f"{pending.currency} (not posted).",
        )
        self._audit("rejection", f"rejected proposal {pending.id} ({pending.vendor_name})",
                    pending, detail={"by": user})
        return WriteResult(WriteOutcome.REJECTED)

    def _approve(self, pending, user) -> WriteResult:
        realm = pending.company_realm
        if not pending.proposed_account_id:
            self._repo.set_status(pending.id, "error", resolved=True, error="no account selected")
            self._slack.update_resolved(
                pending.slack_channel, pending.slack_ts,
                f":warning: Couldn't post {pending.vendor_name} — no account selected. "
                "Handle this one in QBO.",
            )
            self._audit("write", f"approve failed (no account) for {pending.id}", pending)
            return WriteResult(WriteOutcome.ERROR, detail="no account")

        try:
            vendor_id = pending.vendor_id
            if pending.is_new_vendor or not vendor_id:
                vendor = self._qbo.create_vendor(realm, VendorDraft(display_name=pending.vendor_name))
                vendor_id = vendor.id

            draft = BillDraft(
                vendor_id=vendor_id,
                txn_date=pending.txn_date or date.today(),
                total=pending.total,
                lines=(BillLine(amount=pending.total, account_id=pending.proposed_account_id,
                                description=pending.vendor_name),),
                due_date=pending.due_date,
                doc_number=pending.doc_number,
                currency=pending.currency,
            )
            bill = self._qbo.create_bill(realm, draft)

            if pending.pdf_bytes:
                self._qbo.attach_pdf(realm, bill.id, Attachment(
                    pending.pdf_filename or "invoice.pdf", _mime_for(pending.pdf_filename),
                    pending.pdf_bytes))
        except Exception as exc:  # noqa: BLE001 — surface any QBO failure, don't lose the bill
            self._repo.set_status(pending.id, "error", resolved=True, error=str(exc))
            self._slack.update_resolved(
                pending.slack_channel, pending.slack_ts,
                f":warning: Failed to post {pending.vendor_name}: {exc}",
            )
            self._audit("write", f"approve failed for {pending.id}: {exc}", pending)
            return WriteResult(WriteOutcome.ERROR, detail=str(exc))

        self._repo.set_status(pending.id, "posted", resolved=True, posted_bill_id=bill.id)
        self._slack.update_resolved(
            pending.slack_channel, pending.slack_ts,
            f":white_check_mark: Approved by <@{user}> — posted bill {bill.id} "
            f"({pending.vendor_name} {pending.total} {pending.currency}) to {pending.client_key}.",
        )
        self._audit("write", f"posted bill {bill.id} ({pending.vendor_name} {pending.total}) "
                    f"to realm {realm}", pending, detail={"bill_id": bill.id, "by": user})
        return WriteResult(WriteOutcome.POSTED, bill_id=bill.id)
