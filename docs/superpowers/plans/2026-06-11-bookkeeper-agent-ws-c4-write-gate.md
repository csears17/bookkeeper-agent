# Bookkeeper Agent — WS-C4 Write-Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an Approve/Reject click into the real outcome — on Approve, create the vendor if new, create the bill (bound to the pending bill's company), attach the PDF, mark the pending bill posted, and update the Slack card; on Reject, mark it rejected and update the card. Idempotent (a resolved bill is never re-posted), company-bound, and audited. Tested end-to-end on Fakes.

**Architecture:** `ApprovalGate.handle(action)` takes the `ApprovalAction` parsed from a Slack button click (WS-B4), looks up the `PendingBill` by its stored `(slack_channel, slack_ts)`, and acts only if it's still `pending` (the status-transition guard → idempotency). It uses the `QboConnector` (create vendor/bill/attach) and a Slack card-updater. Every QBO write uses `pending.company_realm` — the fixed binding — so the model never chooses the book. Requires two small extensions: `SlackConnector.update_resolved` (to swap the card's buttons for a result line; already on the real `HttpxSlackConnector`) and `PendingBillRepo.find_by_slack`.

**Tech Stack:** Python 3.12, existing deps. Builds on WS-B1/B3/B4 connectors, WS-C2 repo, WS-C3 pipeline.

This is WS-C4 of the WS-C pipeline group. With it + the Slack-drop adapter + the Socket Mode runner, the drop→approve→QBO loop is live. Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md` (§4, §5).

---

## File structure (created/modified by this plan)

```
src/bookkeeper_agent/connectors/
  slack.py        # MODIFIED: add update_resolved to the SlackConnector Protocol + FakeSlackConnector
pipeline/
  store.py        # MODIFIED: add PendingBillRepo.find_by_slack
  writegate.py    # NEW: ApprovalGate, WriteOutcome, WriteResult
tests/
  test_connector_conformance.py  # MODIFIED: add update_resolved to the Slack method list
  test_fake_slack.py             # MODIFIED: cover update_resolved on the Fake
  test_pending_repo.py           # MODIFIED: cover find_by_slack
  test_write_gate.py             # NEW
```

---

## Task 1: Contract extensions (Slack update_resolved + repo find_by_slack)

**Files:**
- Modify: `src/bookkeeper_agent/connectors/slack.py`
- Modify: `src/bookkeeper_agent/pipeline/store.py`
- Modify: `tests/test_connector_conformance.py`, `tests/test_fake_slack.py`, `tests/test_pending_repo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fake_slack.py`:
```python
def test_update_resolved_records():
    slack = FakeSlackConnector()
    slack.update_resolved("C-APPROVALS", "1.0001", "Approved by Cole")
    assert slack.updates == [("C-APPROVALS", "1.0001", "Approved by Cole")]
```

Append to `tests/test_pending_repo.py`:
```python
def test_find_by_slack(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields(source_message_id="ms"))
    repo.set_status(pid, "pending", slack_channel="C1", slack_ts="9.9")
    found = repo.find_by_slack("C1", "9.9")
    assert found is not None and found.id == pid
    assert repo.find_by_slack("C1", "0.0") is None
```

In `tests/test_connector_conformance.py`, add `"update_resolved"` to the Slack method list (the `SlackConnector` / `FakeSlackConnector` entry becomes `["post_proposal", "post_receipt", "update_resolved"]`).

- [ ] **Step 2: Run to verify they fail**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_slack.py tests/test_pending_repo.py tests/test_connector_conformance.py -v`
Expected: FAIL (no `updates` attr / no `find_by_slack` / conformance signature mismatch).

- [ ] **Step 3: Implement**

In `src/bookkeeper_agent/connectors/slack.py`, add to the `SlackConnector` Protocol (after `post_receipt`):
```python
    def update_resolved(self, channel: str, ts: str, text: str) -> None:
        """Replace a posted card's buttons with a resolution line."""
        ...
```
And to `FakeSlackConnector.__init__` add `self.updates: list[tuple[str, str, str]] = []`, plus the method:
```python
    def update_resolved(self, channel: str, ts: str, text: str) -> None:
        self.updates.append((channel, ts, text))
```

In `src/bookkeeper_agent/pipeline/store.py`, add to `PendingBillRepo` (after `find_by_message`):
```python
    def find_by_slack(self, channel: str, ts: str) -> PendingBill | None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(PendingBill).where(
                    PendingBill.slack_channel == channel,
                    PendingBill.slack_ts == ts,
                )
            ).scalar_one_or_none()
            if row is not None:
                s.expunge(row)
            return row
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_slack.py tests/test_pending_repo.py tests/test_connector_conformance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/slack.py src/bookkeeper_agent/pipeline/store.py tests/test_connector_conformance.py tests/test_fake_slack.py tests/test_pending_repo.py
git -c commit.gpgsign=false commit -m "feat(ws-c4): SlackConnector.update_resolved + PendingBillRepo.find_by_slack"
```

---

## Task 2: ApprovalGate

**Files:**
- Create: `src/bookkeeper_agent/pipeline/writegate.py`
- Test: `tests/test_write_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_write_gate.py`:
```python
from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.slack_events import ApprovalAction
from bookkeeper_agent.connectors.types import Vendor
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import AuditEvent
from bookkeeper_agent.pipeline.store import PendingBillRepo
from bookkeeper_agent.pipeline.writegate import ApprovalGate, WriteOutcome

REALM = "111"


def _seed_pending(engine, **over):
    repo = PendingBillRepo(engine)
    fields = dict(
        client_key="habit-pilates", company_realm=REALM,
        source_mailbox="habit@unionstreet.io", source_message_id="m1",
        vendor_name="ACME", is_new_vendor=False, vendor_id="V1",
        doc_number="INV-100", txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
        total=Decimal("250.00"), currency="USD",
        proposed_account_id="A1", proposed_account_name="Supplies",
        confidence=0.9, reasoning="precedent", pdf_filename="invoice.pdf", pdf_bytes=b"%PDF",
    )
    fields.update(over)
    pid = repo.create(**fields)
    repo.set_status(pid, "pending", slack_channel="C-APPROVALS", slack_ts="1.0001")
    return repo, pid


def _gate(engine, qbo, slack):
    return ApprovalGate(qbo=qbo, slack=slack, pending_repo=PendingBillRepo(engine), engine=engine)


def _approve_action():
    return ApprovalAction(action="approve", channel="C-APPROVALS", message_ts="1.0001", user="U1")


def test_approve_existing_vendor_posts_bill_attaches_pdf_updates_card(engine):
    repo, pid = _seed_pending(engine)
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())

    assert result.outcome == WriteOutcome.POSTED and result.bill_id
    # bill created in the RIGHT company, single line on the proposed account
    realm, draft = qbo.created_bills[0]
    assert realm == REALM
    assert draft.vendor_id == "V1"
    assert draft.lines[0].account_id == "A1" and draft.lines[0].amount == Decimal("250.00")
    # PDF attached to the new bill
    assert qbo.attachments and qbo.attachments[0][0] == REALM
    # pending marked posted with the QBO bill id
    row = repo.get(pid)
    assert row.status == "posted" and row.posted_bill_id == result.bill_id
    # card updated (buttons replaced)
    assert slack.updates and slack.updates[0][0] == "C-APPROVALS" and slack.updates[0][1] == "1.0001"
    # audited as a write
    with session_scope(engine) as s:
        kinds = {e.kind for e in s.query(AuditEvent).all()}
    assert "write" in kinds


def test_approve_new_vendor_creates_vendor_first(engine):
    repo, pid = _seed_pending(engine, is_new_vendor=True, vendor_id=None, vendor_name="Brand New Co")
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.POSTED
    assert qbo.created_vendors and qbo.created_vendors[0][0] == REALM
    # the bill used the newly-created vendor's id
    _realm, draft = qbo.created_bills[0]
    assert draft.vendor_id == qbo.find_vendor(REALM, "Brand New Co").id


def test_reject_marks_rejected_no_qbo_write(engine):
    repo, pid = _seed_pending(engine)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    action = ApprovalAction(action="reject", channel="C-APPROVALS", message_ts="1.0001", user="U1")
    result = _gate(engine, qbo, slack).handle(action)
    assert result.outcome == WriteOutcome.REJECTED
    assert qbo.created_bills == []
    assert repo.get(pid).status == "rejected"
    assert slack.updates  # card updated


def test_already_resolved_is_noop(engine):
    repo, pid = _seed_pending(engine)
    repo.set_status(pid, "posted", resolved=True, posted_bill_id="B9")
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.ALREADY_RESOLVED
    assert qbo.created_bills == []  # not re-posted


def test_not_found_for_unknown_message(engine):
    _seed_pending(engine)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    action = ApprovalAction(action="approve", channel="C-APPROVALS", message_ts="9.9", user="U1")
    assert _gate(engine, qbo, slack).handle(action).outcome == WriteOutcome.NOT_FOUND


def test_missing_account_errors_without_posting(engine):
    repo, pid = _seed_pending(engine, proposed_account_id=None)
    qbo = FakeQboConnector()
    slack = FakeSlackConnector()
    result = _gate(engine, qbo, slack).handle(_approve_action())
    assert result.outcome == WriteOutcome.ERROR
    assert qbo.created_bills == []
    assert repo.get(pid).status == "error"
    assert slack.updates  # warned on the card
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_write_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.pipeline.writegate'`

- [ ] **Step 3: Write the implementation**

`src/bookkeeper_agent/pipeline/writegate.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_write_gate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/writegate.py tests/test_write_gate.py
git -c commit.gpgsign=false commit -m "feat(ws-c4): ApprovalGate — Approve/Reject click -> QBO write + card update"
```

---

## Task 3: Full-suite green + WS-C4 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — prior 166 + WS-C4 new tests (1 + 1 + conformance + 6 ≈ 9). All pass.

- [ ] **Step 2: Confirm no live call in the suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && grep -rnE 'httpx\.(post|get|request)\(' tests/ ; echo "exit $?"`
Expected: no matches.

- [ ] **Step 3: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 4: Tag the workstream**

```bash
git tag ws-c4
```

---

## Self-review against the spec

- **§4 Approve → create vendor (if new) → create bill → attach PDF** → `_approve` does exactly this, building a single-line `BillDraft` on the stored `proposed_account_id`. ✓
- **§5 company binding (model never picks the book)** → every QBO call uses `pending.company_realm`; a test asserts `created_bills[0][0] == REALM`. ✓
- **§4 idempotency (one bill once)** → `handle` acts only when `status == "pending"`; a resolved bill returns `ALREADY_RESOLVED` with no re-post (tested). The status guard is the transition gate the prior review asked for. (Assumes a single Socket Mode runner processes events serially — documented; a multi-runner setup would need an atomic claim.) ✓
- **null-account guard** → `_approve` short-circuits to `ERROR` (no post) when `proposed_account_id` is missing, warns on the card (tested). ✓
- **QBO failure handling** → writes wrapped in try/except → `error` status + card warning + audit, so a failed post never silently looks done. ✓
- **card update after decision** → `update_resolved` swaps the buttons for an Approved/Rejected/error line (tested on all paths). ✓
- **audit** → approve→`write`, reject→`rejection`, each stamped with client + realm. ✓
- **money is Decimal** → totals flow as `Decimal` into the `BillDraft`. ✓

**Deferred (out of scope here):** the **Slack-drop adapter** (FileDrop + resolved client → `BillIntake(skip_classification=True)` → `BillsPipeline.process`) and the **Socket Mode runner** (live websocket streaming `block_actions` → `parse_block_action` → `ApprovalGate.handle`, and file events → the drop adapter) + the app entrypoint/config wiring. Those are the final glue to go live; WS-C4 is the logic they call.

**Placeholder scan:** none — complete code throughout.

**Type consistency:** `ApprovalGate.handle(ApprovalAction) -> WriteResult`; `WriteOutcome` enum matches the tests; uses `QboConnector` (`create_vendor`/`create_bill`/`attach_pdf`), `SlackConnector.update_resolved` (Task 1), and `PendingBillRepo.find_by_slack`/`set_status` (WS-C2 + Task 1). `BillDraft`/`BillLine`/`VendorDraft`/`Attachment` are the WS-B1 types.
```
