# Bookkeeper Agent — WS-C2 Pre-screen + Pending/Checkpoint Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the durable state and the cheap local gate the bills pipeline needs: a `DecimalText` SQLite column type that stores money exactly, the `PendingBill` (approval queue) and `Checkpoint` (poller cursor) models with their repositories, and a no-AI `prescreen` function that drops obvious non-bills before anything is sent to Claude.

**Architecture:** Money is stored via a `DecimalText` `TypeDecorator` (Decimal ↔ TEXT) so SQLite can't round it through float. `PendingBill` rows are the restart-surviving queue of proposals (one row per source email, unique on client+message id for idempotency), and carry the original PDF bytes + the fixed `company_realm` binding. `Checkpoint` stores the per-mailbox "last processed" epoch-ms the poller advances. A new `pipeline/` package holds the repositories and the `prescreen` predicate; behavior lives here, schema stays in `db/`.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, pytest. No new third-party dependencies. Builds on WS-A (`ws-a`), WS-B1 (`ws-b1`), WS-C1 (`ws-c1`).

This is WS-C2 of the WS-C pipeline group (C3 propose pipeline, C4 write-gate, C5 poller follow). Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`.

---

## File structure (created/modified by this plan)

```
src/bookkeeper_agent/
  db/
    types.py            # NEW: DecimalText TypeDecorator (exact Decimal on SQLite)
    models.py           # MODIFIED: add PendingBill, Checkpoint
  pipeline/
    __init__.py         # NEW (empty)
    store.py            # NEW: PendingBillRepo, CheckpointRepo
    prescreen.py        # NEW: is_candidate(email) -> bool
tests/
  test_decimal_text.py
  test_pending_models.py
  test_pending_repo.py
  test_checkpoint_repo.py
  test_prescreen.py
```

---

## Task 1: DecimalText column type

**Files:**
- Create: `src/bookkeeper_agent/db/types.py`
- Test: `tests/test_decimal_text.py`

- [ ] **Step 1: Write the failing test**

`tests/test_decimal_text.py`:
```python
from decimal import Decimal

from bookkeeper_agent.db.types import DecimalText


def test_bind_serializes_decimal_to_str():
    t = DecimalText()
    assert t.process_bind_param(Decimal("250.00"), None) == "250.00"
    assert t.process_bind_param(None, None) is None


def test_bind_coerces_non_decimal():
    t = DecimalText()
    assert t.process_bind_param("12.50", None) == "12.50"


def test_result_parses_str_to_decimal_exactly():
    t = DecimalText()
    assert t.process_result_value("250.00", None) == Decimal("250.00")
    assert t.process_result_value("0.1", None) == Decimal("0.1")  # exact, not float 0.1
    assert t.process_result_value(None, None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_decimal_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.db.types'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/db/types.py`:
```python
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator):
    """Store a Decimal exactly as TEXT.

    SQLite has no exact decimal type; SQLAlchemy's Numeric round-trips through
    float there, which would corrupt money. Storing the canonical string keeps
    Decimal values exact across write/read.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_decimal_text.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/db/types.py tests/test_decimal_text.py
git -c commit.gpgsign=false commit -m "feat(ws-c2): DecimalText column type (exact Decimal on SQLite)"
```

---

## Task 2: PendingBill + Checkpoint models

**Files:**
- Modify: `src/bookkeeper_agent/db/models.py` (append two models + imports)
- Test: `tests/test_pending_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pending_models.py`:
```python
from datetime import date
from decimal import Decimal

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import Checkpoint, PendingBill


def test_pending_bill_round_trip_exact_decimal_and_pdf(engine):
    with session_scope(engine) as s:
        s.add(PendingBill(
            client_key="habit-pilates", company_realm="111",
            source_mailbox="habit@unionstreet.io", source_message_id="m1",
            vendor_name="ACME", is_new_vendor=True, doc_number="INV-100",
            txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
            total=Decimal("250.00"), currency="USD",
            proposed_account_id="A1", proposed_account_name="Supplies",
            confidence=0.9, reasoning="precedent",
            pdf_filename="invoice.pdf", pdf_bytes=b"%PDF-1.4 bytes",
        ))
    with session_scope(engine) as s:
        row = s.query(PendingBill).one()
        assert row.status == "pending"  # default
        assert row.total == Decimal("250.00")  # exact, not 250.0 float
        assert isinstance(row.total, Decimal)
        assert row.pdf_bytes == b"%PDF-1.4 bytes"
        assert row.company_realm == "111"


def test_pending_bill_unique_on_client_and_message(engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with session_scope(engine) as s:
        s.add(PendingBill(client_key="c", company_realm="1", source_mailbox="m",
                          source_message_id="dup", vendor_name="V", total=Decimal("1.00")))
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(PendingBill(client_key="c", company_realm="1", source_mailbox="m",
                              source_message_id="dup", vendor_name="V2", total=Decimal("2.00")))


def test_checkpoint_round_trip(engine):
    with session_scope(engine) as s:
        s.add(Checkpoint(mailbox="habit@unionstreet.io", last_epoch_ms=1717200000000))
    with session_scope(engine) as s:
        cp = s.query(Checkpoint).one()
        assert cp.mailbox == "habit@unionstreet.io"
        assert cp.last_epoch_ms == 1717200000000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_pending_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'PendingBill' from 'bookkeeper_agent.db.models'`

- [ ] **Step 3: Modify `src/bookkeeper_agent/db/models.py`**

Add these imports at the top (merge with the existing import lines — `date` joins the existing `datetime` import; `Decimal` and `DecimalText` are new):
```python
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bookkeeper_agent.db.base import Base
from bookkeeper_agent.db.types import DecimalText
```

Append these two model classes to the end of the file:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_pending_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/db/models.py tests/test_pending_models.py
git -c commit.gpgsign=false commit -m "feat(ws-c2): PendingBill + Checkpoint models"
```

---

## Task 3: PendingBillRepo

**Files:**
- Create: `src/bookkeeper_agent/pipeline/__init__.py` (empty)
- Create: `src/bookkeeper_agent/pipeline/store.py`
- Test: `tests/test_pending_repo.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pending_repo.py`:
```python
from datetime import date
from decimal import Decimal

from bookkeeper_agent.pipeline.store import PendingBillRepo


def _fields(**over):
    base = dict(
        client_key="habit-pilates", company_realm="111",
        source_mailbox="habit@unionstreet.io", source_message_id="m1",
        vendor_name="ACME", is_new_vendor=False, vendor_id="V1",
        doc_number="INV-100", txn_date=date(2026, 6, 1), due_date=None,
        total=Decimal("250.00"), currency="USD",
        proposed_account_id="A1", proposed_account_name="Supplies",
        confidence=0.9, reasoning="precedent",
        pdf_filename="invoice.pdf", pdf_bytes=b"%PDF",
    )
    base.update(over)
    return base


def test_create_and_get(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields())
    row = repo.get(pid)
    assert row.vendor_name == "ACME"
    assert row.total == Decimal("250.00")
    assert row.status == "pending"


def test_list_pending_only_returns_pending(engine):
    repo = PendingBillRepo(engine)
    p1 = repo.create(**_fields(source_message_id="m1"))
    p2 = repo.create(**_fields(source_message_id="m2"))
    repo.set_status(p2, "rejected", resolved=True)
    pending = repo.list_pending()
    assert [p.id for p in pending] == [p1]


def test_find_by_message_for_idempotency(engine):
    repo = PendingBillRepo(engine)
    repo.create(**_fields(source_message_id="m9"))
    assert repo.find_by_message("habit-pilates", "m9") is not None
    assert repo.find_by_message("habit-pilates", "nope") is None


def test_set_status_records_resolution_fields(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields())
    repo.set_status(pid, "posted", resolved=True, posted_bill_id="B1",
                    slack_channel="C1", slack_ts="1.0001")
    row = repo.get(pid)
    assert row.status == "posted"
    assert row.posted_bill_id == "B1"
    assert row.slack_channel == "C1" and row.slack_ts == "1.0001"
    assert row.resolved_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_pending_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/pipeline/__init__.py`:
```python
```
(empty file)

`src/bookkeeper_agent/pipeline/store.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import Checkpoint, PendingBill


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PendingBillRepo:
    """CRUD for the PendingBill approval queue. Returned rows are detached so
    callers can read attributes after the session closes."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def create(self, **fields: Any) -> int:
        with session_scope(self._engine) as s:
            row = PendingBill(**fields)
            s.add(row)
            s.flush()
            return row.id

    def get(self, pending_id: int) -> PendingBill | None:
        with session_scope(self._engine) as s:
            row = s.get(PendingBill, pending_id)
            if row is not None:
                s.expunge(row)
            return row

    def list_pending(self) -> list[PendingBill]:
        with session_scope(self._engine) as s:
            rows = list(
                s.execute(
                    select(PendingBill).where(PendingBill.status == "pending").order_by(PendingBill.id)
                ).scalars().all()
            )
            for r in rows:
                s.expunge(r)
            return rows

    def find_by_message(self, client_key: str, source_message_id: str) -> PendingBill | None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(PendingBill).where(
                    PendingBill.client_key == client_key,
                    PendingBill.source_message_id == source_message_id,
                )
            ).scalar_one_or_none()
            if row is not None:
                s.expunge(row)
            return row

    def set_status(
        self,
        pending_id: int,
        status: str,
        *,
        resolved: bool = False,
        posted_bill_id: str | None = None,
        slack_channel: str | None = None,
        slack_ts: str | None = None,
        error: str | None = None,
    ) -> None:
        with session_scope(self._engine) as s:
            row = s.get(PendingBill, pending_id)
            if row is None:
                raise KeyError(pending_id)
            row.status = status
            if resolved:
                row.resolved_at = _utcnow()
            if posted_bill_id is not None:
                row.posted_bill_id = posted_bill_id
            if slack_channel is not None:
                row.slack_channel = slack_channel
            if slack_ts is not None:
                row.slack_ts = slack_ts
            if error is not None:
                row.error = error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_pending_repo.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/__init__.py src/bookkeeper_agent/pipeline/store.py tests/test_pending_repo.py
git -c commit.gpgsign=false commit -m "feat(ws-c2): PendingBillRepo"
```

---

## Task 4: CheckpointRepo

**Files:**
- Modify: `src/bookkeeper_agent/pipeline/store.py` (append `CheckpointRepo`)
- Test: `tests/test_checkpoint_repo.py`

- [ ] **Step 1: Write the failing test**

`tests/test_checkpoint_repo.py`:
```python
from bookkeeper_agent.pipeline.store import CheckpointRepo


def test_get_absent_returns_zero(engine):
    repo = CheckpointRepo(engine)
    assert repo.get("habit@unionstreet.io") == 0


def test_set_then_get(engine):
    repo = CheckpointRepo(engine)
    repo.set("habit@unionstreet.io", 1717200000000)
    assert repo.get("habit@unionstreet.io") == 1717200000000


def test_set_upserts_single_row(engine):
    from bookkeeper_agent.db.base import session_scope
    from bookkeeper_agent.db.models import Checkpoint

    repo = CheckpointRepo(engine)
    repo.set("box", 100)
    repo.set("box", 200)
    assert repo.get("box") == 200
    with session_scope(engine) as s:
        assert s.query(Checkpoint).filter_by(mailbox="box").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_checkpoint_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'CheckpointRepo' from 'bookkeeper_agent.pipeline.store'`

- [ ] **Step 3: Append to `src/bookkeeper_agent/pipeline/store.py`**

Add this class at the end of the file:
```python
class CheckpointRepo:
    """Per-mailbox poller cursor (last processed epoch-ms)."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def get(self, mailbox: str) -> int:
        with session_scope(self._engine) as s:
            row = s.get(Checkpoint, mailbox)
            return row.last_epoch_ms if row is not None else 0

    def set(self, mailbox: str, last_epoch_ms: int) -> None:
        with session_scope(self._engine) as s:
            row = s.get(Checkpoint, mailbox)
            if row is None:
                s.add(Checkpoint(mailbox=mailbox, last_epoch_ms=last_epoch_ms))
            else:
                row.last_epoch_ms = last_epoch_ms
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_checkpoint_repo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/store.py tests/test_checkpoint_repo.py
git -c commit.gpgsign=false commit -m "feat(ws-c2): CheckpointRepo"
```

---

## Task 5: Pre-screen predicate

**Files:**
- Create: `src/bookkeeper_agent/pipeline/prescreen.py`
- Test: `tests/test_prescreen.py`

- [ ] **Step 1: Write the failing test**

`tests/test_prescreen.py`:
```python
from datetime import datetime, timezone

from bookkeeper_agent.connectors.types import Attachment, EmailMessage
from bookkeeper_agent.pipeline.prescreen import is_candidate


def _email(subject, snippet="", attachments=()):
    return EmailMessage(
        id="m1", mailbox="habit@unionstreet.io", sender="x@y.com",
        subject=subject, internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        snippet=snippet, attachments=attachments,
    )


def test_pdf_attachment_is_candidate():
    e = _email("anything", attachments=(Attachment("a.pdf", "application/pdf", b"%PDF"),))
    assert is_candidate(e) is True


def test_image_attachment_is_candidate():
    e = _email("photo", attachments=(Attachment("a.png", "image/png", b"x"),))
    assert is_candidate(e) is True


def test_ap_keyword_in_subject_is_candidate_without_attachment():
    assert is_candidate(_email("Your invoice is ready")) is True
    assert is_candidate(_email("Statement of account")) is True


def test_ap_keyword_in_snippet_is_candidate():
    assert is_candidate(_email("Hello", snippet="Total amount due: $250")) is True


def test_no_attachment_no_keyword_is_not_candidate():
    assert is_candidate(_email("Lunch tomorrow?", snippet="see you at noon")) is False


def test_non_pdf_non_image_attachment_without_keyword_is_not_candidate():
    e = _email("notes", attachments=(Attachment("notes.docx",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"x"),))
    assert is_candidate(e) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_prescreen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.pipeline.prescreen'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/pipeline/prescreen.py`:
```python
from __future__ import annotations

from bookkeeper_agent.connectors.types import EmailMessage

# Words/phrases that suggest an accounts-payable item. Lowercase; matched as substrings.
_AP_KEYWORDS = (
    "invoice",
    "bill",
    "amount due",
    "payment due",
    "balance due",
    "past due",
    "statement",
    "remittance",
    "payable",
    "net 30",
    "net 15",
)


def is_candidate(email: EmailMessage) -> bool:
    """Cheap, local, no-AI gate. An email is a *candidate* bill if it has a
    PDF or image attachment, OR its subject/snippet contains an AP keyword.

    Only obvious non-bills (no PDF/image attachment AND no AP keyword) are
    dropped here — the LLM makes the real is-this-a-bill decision. Conservative
    on purpose: better to let a non-bill through to the model than to drop a bill.
    """
    for att in email.attachments:
        if att.mime_type == "application/pdf" or att.mime_type.startswith("image/"):
            return True
    text = f"{email.subject}\n{email.snippet}".lower()
    return any(keyword in text for keyword in _AP_KEYWORDS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_prescreen.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/pipeline/prescreen.py tests/test_prescreen.py
git -c commit.gpgsign=false commit -m "feat(ws-c2): local pre-screen predicate"
```

---

## Task 6: Full-suite green + WS-C2 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — WS-A+B1+C1 (67) plus WS-C2's new tests (3 + 3 + 4 + 3 + 6 = 19), i.e. 86 total.

- [ ] **Step 2: Confirm money stays exact end-to-end on SQLite**

Run:
```bash
cd /c/Users/Cole/bookkeeper-agent && PYTHONPATH=src ./.venv/Scripts/python.exe -c "from decimal import Decimal; from sqlalchemy import create_engine; from bookkeeper_agent.db.base import init_db, session_scope; from bookkeeper_agent.db.models import PendingBill; e=create_engine('sqlite:///:memory:'); init_db(e);
import datetime
with session_scope(e) as s: s.add(PendingBill(client_key='c',company_realm='1',source_mailbox='m',source_message_id='x',vendor_name='V',total=Decimal('0.1')))
with session_scope(e) as s:
    t=s.query(PendingBill).one().total; print(type(t).__name__, t, t==Decimal('0.1'))"
```
Expected: `Decimal 0.1 True` (exact — not a float 0.1).

- [ ] **Step 3: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` (expect clean) and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 4: Tag the workstream**

```bash
git tag ws-c2
```

---

## Self-review against the spec

- **§4 local pre-screen drops obvious non-bills before sending to Claude** → Task 5 `is_candidate` (PDF/image attachment OR AP keyword; drops only no-attachment + no-keyword). ✓
- **§3/§4 restart-surviving pending-bill queue** → `PendingBill` model (Task 2) + `PendingBillRepo` (Task 3); `list_pending` re-surfaces unresolved proposals after a restart. ✓
- **§4 dedupe / idempotency (one email → one bill)** → `UniqueConstraint(client_key, source_message_id)` (Task 2) + `find_by_message` (Task 3). ✓
- **§5 multi-book binding carried in storage** → `PendingBill.company_realm` (Task 2). ✓
- **§4 attach original PDF to the posted bill** → `PendingBill.pdf_bytes` / `pdf_filename` persist the invoice for the write step. ✓
- **§7 poller checkpointing (advance only after handling)** → `Checkpoint` model + `CheckpointRepo` (Tasks 2, 4); the poller (WS-C5) advances it. ✓
- **money is Decimal, stored exactly** → `DecimalText` (Task 1); `PendingBill.total` uses it; Task 6 step 2 proves `Decimal("0.1")` round-trips exactly on SQLite (no float). ✓

**Deferred to WS-C3–C5 (correctly out of scope here):** the `process_message` orchestration that runs prescreen → LLM classify/extract → QBO vendor/dup/history → LLM categorize → build `BillProposal` → persist `PendingBill` + post Slack, enforcing the "drop non-bill content" rule (C3); the approve/reject write-gate with company-binding enforcement + idempotent QBO writes (C4); the checkpointed poller loop (C5).

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** `PendingBill.total: Decimal` via `DecimalText`; repo `create(**fields)` accepts the model's column names; `set_status(pending_id, status, *, resolved, posted_bill_id, slack_channel, slack_ts, error)` matches its test; `CheckpointRepo.get(mailbox) -> int` (0 default) / `set(mailbox, last_epoch_ms)` match; `is_candidate(EmailMessage) -> bool` matches the connector type from WS-B1.
```
