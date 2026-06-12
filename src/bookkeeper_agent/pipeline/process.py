from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sqlalchemy.engine import Engine

from bookkeeper_agent.audit import record_event
from bookkeeper_agent.connectors.qbo import QboConnector
from bookkeeper_agent.connectors.slack import SlackConnector
from bookkeeper_agent.connectors.types import Attachment, BillProposal, VendorAccountStat
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.llm.client import LlmClient
from bookkeeper_agent.llm.types import CategorizationContext, EmailContext
from bookkeeper_agent.pipeline.intake import BillIntake
from bookkeeper_agent.pipeline.prescreen import is_candidate_fields
from bookkeeper_agent.pipeline.store import PendingBillRepo

_UNKNOWN_VENDOR = "(unknown vendor)"


class IntakeOutcome(str, Enum):
    ALREADY_SEEN = "already_seen"
    NOT_CANDIDATE = "not_candidate"
    NOT_A_BILL = "not_a_bill"
    DUPLICATE = "duplicate"
    PROPOSED = "proposed"


@dataclass(frozen=True)
class IntakeResult:
    outcome: IntakeOutcome
    pending_id: int | None = None
    detail: str | None = None


def _precedent_lines(stats: list[VendorAccountStat]) -> tuple[str, ...]:
    ordered = sorted(stats, key=lambda s: s.count, reverse=True)
    return tuple(f"{s.account_name}: {s.count} prior bill(s)" for s in ordered)


def _invoice_attachment(attachments: tuple[Attachment, ...]) -> Attachment | None:
    for att in attachments:
        if att.mime_type == "application/pdf" or att.mime_type.startswith("image/"):
            return att
    return None


class BillsPipeline:
    """Turns a BillIntake into a Slack approval card + a persisted PendingBill.
    Depends only on Protocols/Fakes — runs end-to-end with no live calls."""

    def __init__(
        self,
        *,
        llm: LlmClient,
        qbo: QboConnector,
        slack: SlackConnector,
        pending_repo: PendingBillRepo,
        engine: Engine,
        approval_channel: str,
    ):
        self._llm = llm
        self._qbo = qbo
        self._slack = slack
        self._repo = pending_repo
        self._engine = engine
        self._channel = approval_channel

    def _audit(self, kind: str, summary: str, intake: BillIntake, detail: dict | None = None) -> None:
        with session_scope(self._engine) as s:
            record_event(
                s, kind=kind, summary=summary,
                client_key=intake.client_key, company_realm=intake.company_realm, detail=detail,
            )

    def process(self, intake: BillIntake) -> IntakeResult:
        # Idempotency: never propose the same source item twice.
        if self._repo.find_by_message(intake.client_key, intake.source_id) is not None:
            return IntakeResult(IntakeOutcome.ALREADY_SEEN)

        # Local pre-screen (skipped for explicit Slack drops). Metadata-only audit; NO content.
        if not intake.skip_classification:
            if not is_candidate_fields(intake.subject, intake.body_text, intake.attachments):
                self._audit("read", "screened: not AP", intake)
                return IntakeResult(IntakeOutcome.NOT_CANDIDATE)

        # Classify + extract via Claude.
        extraction = self._llm.classify_and_extract(EmailContext(
            sender=intake.sender, subject=intake.subject,
            body_text=intake.body_text, attachments=intake.attachments,
        ))
        if not intake.skip_classification and not extraction.is_bill:
            self._audit("read", "classified: not a bill", intake)
            return IntakeResult(IntakeOutcome.NOT_A_BILL)

        # Vendor match (model never picks the book — company_realm is fixed on the intake).
        vendor = (
            self._qbo.find_vendor(intake.company_realm, extraction.vendor_name)
            if extraction.vendor_name else None
        )
        is_new_vendor = vendor is None
        total = extraction.total if extraction.total is not None else Decimal("0.00")

        # Duplicate guard (only when the vendor is known).
        if vendor is not None:
            dup = self._qbo.find_duplicate_bill(
                intake.company_realm, vendor.id, extraction.doc_number, total
            )
            if dup is not None:
                self._audit("read", f"duplicate of bill {dup.id}: skipped", intake,
                            detail={"vendor": extraction.vendor_name, "doc_number": extraction.doc_number})
                return IntakeResult(IntakeOutcome.DUPLICATE, detail=f"duplicate of {dup.id}")

        # History-driven categorization.
        accounts = tuple(self._qbo.list_accounts(intake.company_realm))
        precedents = (
            _precedent_lines(self._qbo.vendor_account_history(intake.company_realm, vendor.id))
            if vendor is not None else ()
        )
        suggestion = self._llm.categorize(CategorizationContext(
            vendor_name=extraction.vendor_name or _UNKNOWN_VENDOR,
            total=total, accounts=accounts, precedents=precedents, line_hint=extraction.line_hint,
        ))

        # Build the approval card (carries the fixed company binding).
        invoice = _invoice_attachment(intake.attachments)
        proposal = BillProposal(
            client_key=intake.client_key, client_display=intake.client_display,
            company_realm=intake.company_realm,
            vendor_name=extraction.vendor_name or _UNKNOWN_VENDOR, is_new_vendor=is_new_vendor,
            total=total, currency=extraction.currency,
            txn_date=extraction.txn_date, due_date=extraction.due_date, doc_number=extraction.doc_number,
            proposed_account_name=suggestion.account_name, confidence=suggestion.confidence,
            reasoning=suggestion.reasoning,
            pdf_filename=(invoice.filename if invoice else None),
        )

        # Persist the durable pending bill (survives restarts; carries the PDF + binding).
        pending_id = self._repo.create(
            client_key=intake.client_key, company_realm=intake.company_realm,
            source_mailbox=intake.source_ref, source_message_id=intake.source_id,
            vendor_name=proposal.vendor_name, is_new_vendor=is_new_vendor,
            vendor_id=(vendor.id if vendor is not None else None),
            doc_number=extraction.doc_number, txn_date=extraction.txn_date, due_date=extraction.due_date,
            total=total, currency=extraction.currency,
            proposed_account_id=suggestion.account_id, proposed_account_name=suggestion.account_name,
            confidence=suggestion.confidence, reasoning=suggestion.reasoning,
            pdf_filename=(invoice.filename if invoice else None),
            pdf_bytes=(invoice.content if invoice else None),
        )

        # Post the Slack card and record its ref on the pending bill.
        ref = self._slack.post_proposal(self._channel, proposal)
        self._repo.set_status(pending_id, "pending", slack_channel=ref.channel, slack_ts=ref.ts)

        self._audit("proposal", f"proposed bill: {proposal.vendor_name} {total} {proposal.currency}",
                    intake, detail={"pending_id": pending_id, "account": suggestion.account_name})
        return IntakeResult(IntakeOutcome.PROPOSED, pending_id=pending_id)
