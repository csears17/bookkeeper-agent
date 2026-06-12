# Bookkeeper Agent — WS-C3 Propose Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the pieces into the source-agnostic propose pipeline — take a normalized `BillIntake` (from email or a Slack drop), and run pre-screen → Claude classify/extract → QBO vendor-match + duplicate-check + account history → Claude categorize → build a `BillProposal` → persist a `PendingBill` + post the Slack approval card — all provable end-to-end against the Fakes.

**Architecture:** A `BillsPipeline` orchestrator with a single `process(intake) -> IntakeResult` method, depending only on the WS-B1 connector Protocols, the WS-C1 `LlmClient`, the WS-C2 repo + pre-screen, and the WS-A audit + cost layers (so the whole pipeline runs on Fakes with no live calls). `BillIntake` normalizes both sources; an email adapter builds one from an `EmailMessage` + `ClientConfig`. The Slack-drop adapter is deferred to the Slack-drop slice but `BillIntake` already supports it (`skip_classification=True`). To enable history-driven categorization, the QBO connector gains a `vendor_account_history` read.

**Tech Stack:** Python 3.12, existing deps only. Builds on WS-A/B1/C1/C2.

This is WS-C3 of the WS-C pipeline group. Per the reprioritized roadmap (spec §9b), the next slices are WS-B4 (real Slack incl. file-drop receive), WS-B3 (real QBO), then the Slack-drop adapter + WS-C4 write-gate. Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`.

---

## File structure (created/modified by this plan)

```
src/bookkeeper_agent/
  connectors/
    types.py        # MODIFIED: add VendorAccountStat
    qbo.py          # MODIFIED: add vendor_account_history to Protocol + Fake (+ seed helper)
  pipeline/
    prescreen.py    # MODIFIED: add is_candidate_fields (field-based core)
    intake.py       # NEW: BillIntake + intake_from_email adapter
    process.py      # NEW: BillsPipeline, IntakeOutcome, IntakeResult
tests/
  test_connector_conformance.py   # MODIFIED: add vendor_account_history to QBO method list
  test_qbo_history.py             # NEW
  test_intake.py                  # NEW
  test_process_pipeline.py        # NEW
```

---

## Task 1: QBO vendor account history (connector extension)

**Files:**
- Modify: `src/bookkeeper_agent/connectors/types.py` (add `VendorAccountStat`)
- Modify: `src/bookkeeper_agent/connectors/qbo.py` (Protocol method + Fake method + seed helper)
- Modify: `tests/test_connector_conformance.py` (add the new method to the QBO list)
- Test: `tests/test_qbo_history.py`

- [ ] **Step 1: Write the failing test**

`tests/test_qbo_history.py`:
```python
from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.types import VendorAccountStat


def test_vendor_account_history_empty_by_default():
    qbo = FakeQboConnector()
    assert qbo.vendor_account_history("111", "V1") == []


def test_seed_and_read_account_history():
    qbo = FakeQboConnector()
    qbo.seed_account_history("111", "V1", [
        VendorAccountStat(account_id="A1", account_name="Supplies", count=3),
        VendorAccountStat(account_id="A2", account_name="Office", count=1),
    ])
    stats = qbo.vendor_account_history("111", "V1")
    assert [s.account_name for s in stats] == ["Supplies", "Office"]
    assert stats[0].count == 3
    # realm-scoped
    assert qbo.vendor_account_history("222", "V1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_history.py -v`
Expected: FAIL — `ImportError: cannot import name 'VendorAccountStat'`

- [ ] **Step 3: Implement**

In `src/bookkeeper_agent/connectors/types.py`, add this dataclass (alongside the others):
```python
@dataclass(frozen=True)
class VendorAccountStat:
    """How often a vendor's prior bills were booked to a given account.
    Feeds history-driven categorization."""

    account_id: str
    account_name: str
    count: int
```

In `src/bookkeeper_agent/connectors/qbo.py`:
- Add `VendorAccountStat` to the import from `bookkeeper_agent.connectors.types`.
- Add this method to the `QboConnector` Protocol (after `recent_bills_for_vendor`):
```python
    def vendor_account_history(self, realm: str, vendor_id: str) -> list["VendorAccountStat"]: ...
```
- In `FakeQboConnector.__init__`, add: `self._account_history: dict[tuple[str, str], list[VendorAccountStat]] = {}`
- Add a seed helper (next to the other `seed_*` methods):
```python
    def seed_account_history(self, realm: str, vendor_id: str, stats: list[VendorAccountStat]) -> None:
        self._account_history[(realm, vendor_id)] = list(stats)
```
- Add the protocol method implementation (next to `recent_bills_for_vendor`):
```python
    def vendor_account_history(self, realm: str, vendor_id: str) -> list[VendorAccountStat]:
        return list(self._account_history.get((realm, vendor_id), []))
```

In `tests/test_connector_conformance.py`, add `"vendor_account_history"` to the QBO method list (the list passed for `QboConnector` / `FakeQboConnector`). The QBO entry's method list becomes:
```python
        [
            "find_vendor",
            "list_accounts",
            "recent_bills_for_vendor",
            "vendor_account_history",
            "find_duplicate_bill",
            "create_vendor",
            "create_bill",
            "attach_pdf",
        ],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_history.py tests/test_connector_conformance.py -v`
Expected: PASS (3 + 6 = 9)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/types.py src/bookkeeper_agent/connectors/qbo.py tests/test_connector_conformance.py tests/test_qbo_history.py
git -c commit.gpgsign=false commit -m "feat(ws-c3): QBO vendor_account_history for history-driven categorization"
```

---

## Task 2: BillIntake + email adapter + field-based pre-screen

**Files:**
- Modify: `src/bookkeeper_agent/pipeline/prescreen.py` (add `is_candidate_fields`)
- Create: `src/bookkeeper_agent/pipeline/intake.py`
- Test: `tests/test_intake.py`

- [ ] **Step 1: Write the failing test**

`tests/test_intake.py`:
```python
from datetime import datetime, timezone

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.types import Attachment, EmailMessage
from bookkeeper_agent.pipeline.intake import BillIntake, intake_from_email
from bookkeeper_agent.pipeline.prescreen import is_candidate, is_candidate_fields


def test_is_candidate_fields_matches_is_candidate():
    atts = (Attachment("a.pdf", "application/pdf", b"%PDF"),)
    assert is_candidate_fields("hi", "there", atts) is True
    assert is_candidate_fields("invoice", "", ()) is True
    assert is_candidate_fields("lunch", "noon", ()) is False
    # the EmailMessage wrapper delegates to the same logic
    e = EmailMessage(id="m", mailbox="b", sender="s", subject="lunch",
                     internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                     snippet="noon", attachments=())
    assert is_candidate(e) is False


def test_intake_from_email_binds_company_and_skips_nothing():
    client = ClientConfig(key="habit-pilates", display_name="Habit Pilates",
                          provider="google", mailbox="habit@unionstreet.io",
                          qbo_realm_id="111", autonomy_level=0)
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    email = EmailMessage(id="m1", mailbox="habit@unionstreet.io", sender="v@acme.com",
                         subject="Invoice 100", internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                         snippet="amount due", attachments=(att,))
    intake = intake_from_email(email, client)
    assert isinstance(intake, BillIntake)
    assert intake.source == "email"
    assert intake.source_id == "m1"
    assert intake.source_ref == "habit@unionstreet.io"
    assert intake.client_key == "habit-pilates"
    assert intake.client_display == "Habit Pilates"
    assert intake.company_realm == "111"
    assert intake.sender == "v@acme.com"
    assert intake.subject == "Invoice 100"
    assert intake.body_text == "amount due"
    assert intake.attachments == (att,)
    assert intake.skip_classification is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_intake.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_candidate_fields'` (or the intake module missing)

- [ ] **Step 3: Implement**

In `src/bookkeeper_agent/pipeline/prescreen.py`, refactor so the keyword/attachment logic is field-based and `is_candidate` delegates to it. Replace the `is_candidate` function with:
```python
def is_candidate_fields(subject: str, snippet: str, attachments) -> bool:
    """Field-based pre-screen used by both the EmailMessage wrapper and the
    pipeline (which works on a normalized BillIntake, not an EmailMessage)."""
    for att in attachments:
        if att.mime_type == "application/pdf" or att.mime_type.startswith("image/"):
            return True
    text = f"{subject}\n{snippet}".lower()
    return any(keyword in text for keyword in _AP_KEYWORDS)


def is_candidate(email: EmailMessage) -> bool:
    """Cheap, local, no-AI gate on an email. See is_candidate_fields."""
    return is_candidate_fields(email.subject, email.snippet, email.attachments)
```
(Keep the `_AP_KEYWORDS` tuple and the `EmailMessage` import unchanged.)

`src/bookkeeper_agent/pipeline/intake.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.types import Attachment, EmailMessage


@dataclass(frozen=True)
class BillIntake:
    """A normalized unit of work for the propose pipeline, independent of source.

    source: "email" | "slack-drop"
    source_id: unique id within the source (email message id; Slack file id) — idempotency key.
    source_ref: human-meaningful origin (mailbox address; Slack channel/user).
    company_realm: the FIXED target QBO company. For email it comes from the inbox map;
                   for a Slack drop it comes from Cole's explicit, validated choice.
    skip_classification: True for explicit sources (Slack drop) — skip pre-screen and the
                   is-this-a-bill gate; still run extraction.
    """

    source: str
    source_id: str
    source_ref: str
    client_key: str
    client_display: str
    company_realm: str
    sender: str
    subject: str
    body_text: str
    attachments: tuple[Attachment, ...]
    skip_classification: bool


def intake_from_email(email: EmailMessage, client: ClientConfig) -> BillIntake:
    """Build an intake from an email read from a client's bound mailbox.
    The company binding comes from the fixed client config, never the model."""
    return BillIntake(
        source="email",
        source_id=email.id,
        source_ref=email.mailbox,
        client_key=client.key,
        client_display=client.display_name,
        company_realm=client.qbo_realm_id,
        sender=email.sender,
        subject=email.subject,
        body_text=email.snippet,
        attachments=email.attachments,
        skip_classification=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_intake.py tests/test_prescreen.py -v`
Expected: PASS (2 + 6 = 8)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/prescreen.py src/bookkeeper_agent/pipeline/intake.py tests/test_intake.py
git -c commit.gpgsign=false commit -m "feat(ws-c3): BillIntake + email adapter + field-based pre-screen"
```

---

## Task 3: BillsPipeline.process orchestration

**Files:**
- Create: `src/bookkeeper_agent/pipeline/process.py`
- Test: `tests/test_process_pipeline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_process_pipeline.py`:
```python
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
    # PendingBill persisted, bound to the right company, with exact money + PDF
    row = PendingBillRepo(engine).get(result.pending_id)
    assert row.company_realm == REALM
    assert row.total == Decimal("250.00")
    assert row.is_new_vendor is False
    assert row.vendor_id == "V1"
    assert row.pdf_bytes == b"%PDF-bytes"
    assert row.proposed_account_name == "Supplies"
    assert row.slack_ts  # slack ref recorded
    # Slack card posted to the right channel, carrying the company binding
    channel, proposal = slack.posted[0]
    assert channel == "C-APPROVALS"
    assert proposal.company_realm == REALM
    assert proposal.vendor_name == "ACME"
    # categorizer saw the precedent + accounts
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
    assert llm.classify_calls == []  # never sent to the model
    assert slack.posted == []
    assert PendingBillRepo(engine).list_pending() == []
    # PRIVACY: the dropped email's subject/body must not appear in the audit log
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
    second = pipe.process(_intake())  # same source_id
    assert first.outcome == IntakeOutcome.PROPOSED
    assert second.outcome == IntakeOutcome.ALREADY_SEEN
    assert len(slack.posted) == 1  # not re-posted


def test_slack_drop_skips_gates_and_proposes_even_if_model_unsure(engine):
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    # is_bill False AND no AP keyword/attachment would normally drop — but skip_classification bypasses both
    llm = FakeLlmClient(extraction=_extraction(is_bill=False), suggestion=_suggestion())
    slack = FakeSlackConnector()
    drop = _intake(source="slack-drop", source_id="F123", source_ref="C-DROPS",
                   subject="", body_text="", skip_classification=True)
    result = _pipeline(engine, llm, qbo, slack).process(drop)
    assert result.outcome == IntakeOutcome.PROPOSED
    assert len(slack.posted) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_process_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.pipeline.process'`

- [ ] **Step 3: Write the implementation**

`src/bookkeeper_agent/pipeline/process.py`:
```python
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

        self._audit("proposal", f"proposed bill: {proposal.vendor_name} {total} {extraction.currency}",
                    intake, detail={"pending_id": pending_id, "account": suggestion.account_name})
        return IntakeResult(IntakeOutcome.PROPOSED, pending_id=pending_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_process_pipeline.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/process.py tests/test_process_pipeline.py
git -c commit.gpgsign=false commit -m "feat(ws-c3): BillsPipeline.process — source-agnostic propose pipeline"
```

---

## Task 4: Full-suite green + WS-C3 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — WS-A/B1/C1/C2 + guard (107) plus WS-C3 (3 + 2 + 7 = 12 new, minus none), i.e. ~119 total. (Exact count may vary slightly; all must pass.)

- [ ] **Step 2: Confirm no live calls in the suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && grep -rnE 'Anthropic\(|requests\.|httpx\.|urllib\.request' tests/ ; echo "exit $?"`
Expected: no matches (whole pipeline runs on Fakes).

- [ ] **Step 3: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` (expect clean) and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 4: Tag the workstream**

```bash
git tag ws-c3
```

---

## Self-review against the spec

- **§9b source-agnostic pipeline** → `BillIntake` + `BillsPipeline.process` consume a normalized intake; the email adapter binds company from config; `skip_classification` supports Slack drops. ✓
- **§4 pre-screen → classify → vendor/dup/history → categorize → proposal → PendingBill → Slack card** → `process` runs exactly this order. ✓
- **§4 history-driven categorization** → `vendor_account_history` (Task 1) feeds precedent lines into `categorize`; a test asserts the precedent reaches the model. ✓
- **§4 duplicate detection blocks the bill** → `find_duplicate_bill` short-circuits to `DUPLICATE`, no Slack post, no PendingBill. ✓
- **§4 vendor match / new-vendor flag** → `is_new_vendor` set + carried to proposal + PendingBill. ✓
- **§5 multi-book binding (model never picks the book)** → `company_realm` is fixed on the intake (from config for email; from Cole's validated pick for Slack drop) and flows unchanged into the QBO reads, `BillProposal`, and `PendingBill`; a test asserts the proposal/row carry the intake realm. ✓
- **§5 privacy "forget non-bill content"** → dropped emails (NOT_CANDIDATE / NOT_A_BILL) write a metadata-only audit line with no subject/body; a test asserts the dropped subject/body never appear in the audit log. ✓
- **§4 idempotency (one source item → one bill)** → `find_by_message` short-circuits to `ALREADY_SEEN`; a test proves a second run doesn't re-post. ✓
- **§4 attach PDF** → the invoice attachment's bytes are stored on the PendingBill for the write step (WS-C4). ✓
- **money is Decimal** → totals stay Decimal end-to-end; missing total defaults to `Decimal("0.00")`. ✓

**Deferred to later slices (correctly out of scope here):** the Slack-drop *adapter* + Slack file-receive + client-dropdown (WS-B4 + Slack-drop slice); the approve/reject **write-gate** that turns a PendingBill into a real QBO bill, with status-transition guard + idempotent writes (WS-C4); the real connectors (WS-B3 QBO, WS-B4 Slack, WS-B2 email); the poller (WS-C5). The `AnthropicLlmClient` already enforces the spend cap, so live runs are gated; the Fake LLM used in these tests does not call the cap (no live cost).

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** `process(BillIntake) -> IntakeResult`; `IntakeOutcome` enum values match the tests; `vendor_account_history(realm, vendor_id) -> list[VendorAccountStat]` matches Protocol/Fake/conformance; `intake_from_email(EmailMessage, ClientConfig) -> BillIntake`; `is_candidate_fields(subject, snippet, attachments) -> bool`. `PendingBillRepo.create(**fields)` is called with the model's column names; `set_status(pending_id, "pending", slack_channel=, slack_ts=)` matches WS-C2.
```
