# Bookkeeper Agent — WS-B1 Connector Contracts & Fakes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the connector layer's contracts (Protocols), shared domain types, in-memory Fakes, and the encrypted-token access layer — so the WS-C agent pipeline can be built and fully tested against Fakes before any real external API exists.

**Architecture:** A `connectors/` package. Each external service (email, QBO, Slack) is described by a `typing.Protocol` plus a `Fake*` in-memory implementation used by tests and by WS-C. Domain types are plain frozen dataclasses (no SDK types leak across the boundary). `TokenStore` is the typed access layer over WS-A's `OAuthToken` table + `TokenCipher`, so real connectors (WS-B2/3/4) read/write their encrypted secrets through one audited path. NO live network calls in this workstream.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (existing), `typing.Protocol`, pytest. No new third-party dependencies.

This is WS-B1 of the WS-B connector group. Real implementations follow: WS-B2 (Gmail + MS Graph), WS-B3 (QBO OAuth + read/write), WS-B4 (Slack). Design spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`. Foundations: WS-A (merged, tag `ws-a`).

---

## File structure (created by this plan)

```
src/bookkeeper_agent/connectors/
  __init__.py
  types.py            # domain dataclasses shared across connectors
  tokens.py           # TokenStore: encrypted secret get/put/delete over OAuthToken + TokenCipher
  email.py            # EmailConnector Protocol + FakeEmailConnector
  qbo.py              # QboConnector Protocol + FakeQboConnector
  slack.py            # SlackConnector Protocol + FakeSlackConnector
tests/
  test_connector_types.py
  test_token_store.py
  test_fake_email.py
  test_fake_qbo.py
  test_fake_slack.py
```

`types.py` holds only data (no behavior). Each connector module holds its Protocol + Fake together (they change together). `TokenStore` is the single place secrets are encrypted/decrypted at the connector boundary.

---

## Task 1: Connector domain types

**Files:**
- Create: `src/bookkeeper_agent/connectors/__init__.py` (empty)
- Create: `src/bookkeeper_agent/connectors/types.py`
- Test: `tests/test_connector_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_connector_types.py`:
```python
from datetime import date, datetime, timezone

import pytest

from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    BillLine,
    BillProposal,
    EmailMessage,
    MessageRef,
    SlackMessageRef,
    Vendor,
    VendorDraft,
)


def test_email_message_holds_attachments():
    att = Attachment(filename="invoice.pdf", mime_type="application/pdf", content=b"%PDF-1.4")
    msg = EmailMessage(
        id="m1",
        mailbox="habit@unionstreet.io",
        sender="vendor@acme.com",
        subject="Invoice 100",
        internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        snippet="Please find attached",
        attachments=(att,),
    )
    assert msg.attachments[0].filename == "invoice.pdf"
    assert msg.attachments[0].content == b"%PDF-1.4"


def test_message_ref():
    ref = MessageRef(id="m1", epoch_ms=1_000)
    assert ref.id == "m1" and ref.epoch_ms == 1_000


def test_bill_draft_and_lines():
    draft = BillDraft(
        vendor_id="V1",
        txn_date=date(2026, 6, 1),
        total=250.0,
        lines=(BillLine(amount=250.0, account_id="A1", description="Supplies"),),
        due_date=date(2026, 6, 30),
        doc_number="INV-100",
    )
    assert draft.currency == "USD"
    assert draft.lines[0].account_id == "A1"
    assert draft.due_date == date(2026, 6, 30)


def test_simple_value_objects():
    assert Vendor(id="V1", display_name="ACME").display_name == "ACME"
    assert VendorDraft(display_name="ACME").email is None
    assert Account(id="A1", name="Supplies", account_type="Expense").account_type == "Expense"
    assert Bill(id="B1", vendor_id="V1", total=250.0).doc_number is None
    assert SlackMessageRef(channel="C1", ts="1.0001").ts == "1.0001"


def test_bill_proposal_is_view_model():
    p = BillProposal(
        client_key="habit-pilates",
        client_display="Habit Pilates",
        company_realm="111",
        vendor_name="ACME",
        is_new_vendor=True,
        total=250.0,
        currency="USD",
        txn_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        doc_number="INV-100",
        proposed_account_name="Supplies",
        confidence=0.92,
        reasoning="Prior ACME bills booked to Supplies",
        pdf_filename="invoice.pdf",
    )
    assert p.is_new_vendor is True
    assert p.proposed_account_name == "Supplies"


def test_frozen():
    v = Vendor(id="V1", display_name="ACME")
    with pytest.raises(Exception):
        v.display_name = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_connector_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/__init__.py`:
```python
```
(empty file)

`src/bookkeeper_agent/connectors/types.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_connector_types.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/__init__.py src/bookkeeper_agent/connectors/types.py tests/test_connector_types.py
git -c commit.gpgsign=false commit -m "feat(ws-b1): connector domain types"
```

---

## Task 2: TokenStore (encrypted secret access)

**Files:**
- Create: `src/bookkeeper_agent/connectors/tokens.py`
- Test: `tests/test_token_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_token_store.py`:
```python
from cryptography.fernet import Fernet

from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import OAuthToken
from bookkeeper_agent.security import TokenCipher


def _store(engine):
    return TokenStore(engine, TokenCipher([Fernet.generate_key().decode()]))


def test_put_then_get_round_trip(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "refresh-token-abc")
    assert store.get_secret("qbo", "111") == "refresh-token-abc"


def test_get_missing_returns_none(engine):
    store = _store(engine)
    assert store.get_secret("qbo", "does-not-exist") is None


def test_put_overwrites_existing(engine):
    store = _store(engine)
    store.put_secret("slack", "default", "xoxb-old")
    store.put_secret("slack", "default", "xoxb-new")
    assert store.get_secret("slack", "default") == "xoxb-new"
    # still only one row for that (service, ref)
    with session_scope(engine) as s:
        rows = s.query(OAuthToken).filter_by(service="slack", ref="default").all()
        assert len(rows) == 1


def test_secret_is_encrypted_at_rest(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "super-secret")
    with session_scope(engine) as s:
        row = s.query(OAuthToken).filter_by(service="qbo", ref="111").one()
        assert b"super-secret" not in row.secret_ciphertext


def test_delete(engine):
    store = _store(engine)
    store.put_secret("google", "default", "json-key-blob")
    store.delete_secret("google", "default")
    assert store.get_secret("google", "default") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_token_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.tokens'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/tokens.py`:
```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import OAuthToken
from bookkeeper_agent.security import TokenCipher


class TokenStore:
    """Typed access to encrypted service secrets in the OAuthToken table.

    Real connectors (WS-B2/3/4) read/write their refresh tokens and keys
    exclusively through here, so encryption happens in exactly one place.
    """

    def __init__(self, engine: Engine, cipher: TokenCipher):
        self._engine = engine
        self._cipher = cipher

    def get_secret(self, service: str, ref: str = "default") -> str | None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._cipher.decrypt(row.secret_ciphertext)

    def put_secret(self, service: str, ref: str, plaintext: str) -> None:
        ciphertext = self._cipher.encrypt(plaintext)
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is None:
                s.add(OAuthToken(service=service, ref=ref, secret_ciphertext=ciphertext))
            else:
                row.secret_ciphertext = ciphertext

    def delete_secret(self, service: str, ref: str = "default") -> None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is not None:
                s.delete(row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_token_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/tokens.py tests/test_token_store.py
git -c commit.gpgsign=false commit -m "feat(ws-b1): TokenStore for encrypted secret access"
```

---

## Task 3: EmailConnector Protocol + FakeEmailConnector

**Files:**
- Create: `src/bookkeeper_agent/connectors/email.py`
- Test: `tests/test_fake_email.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fake_email.py`:
```python
from datetime import datetime, timezone

from bookkeeper_agent.connectors.email import FakeEmailConnector
from bookkeeper_agent.connectors.types import Attachment, EmailMessage


def _msg(mailbox, mid, dt, with_pdf=True):
    atts = (Attachment("invoice.pdf", "application/pdf", b"%PDF"),) if with_pdf else ()
    return EmailMessage(
        id=mid, mailbox=mailbox, sender="v@acme.com", subject="Invoice",
        internal_date=dt, snippet="hi", attachments=atts,
    )


def test_list_message_ids_filters_by_after_and_sorts():
    conn = FakeEmailConnector()
    box = "habit@unionstreet.io"
    conn.add(_msg(box, "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    conn.add(_msg(box, "m2", datetime(2026, 6, 3, tzinfo=timezone.utc)))
    conn.add(_msg(box, "m3", datetime(2026, 6, 2, tzinfo=timezone.utc)))

    after = int(datetime(2026, 6, 1, 12, tzinfo=timezone.utc).timestamp() * 1000)
    refs = conn.list_message_ids(box, after)
    assert [r.id for r in refs] == ["m3", "m2"]  # m1 excluded (before cutoff), sorted ascending


def test_get_message_returns_full_with_attachments():
    conn = FakeEmailConnector()
    box = "habit@unionstreet.io"
    conn.add(_msg(box, "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    msg = conn.get_message(box, "m1")
    assert msg.subject == "Invoice"
    assert msg.attachments[0].filename == "invoice.pdf"


def test_mailbox_isolation():
    conn = FakeEmailConnector()
    conn.add(_msg("a@unionstreet.io", "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    conn.add(_msg("b@unionstreet.io", "m2", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    refs = conn.list_message_ids("a@unionstreet.io", 0)
    assert [r.id for r in refs] == ["m1"]


def test_get_unknown_raises():
    conn = FakeEmailConnector()
    try:
        conn.get_message("a@unionstreet.io", "nope")
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_email.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.email'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/email.py`:
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bookkeeper_agent.connectors.types import EmailMessage, MessageRef


@runtime_checkable
class EmailConnector(Protocol):
    """Read-only access to a mailbox. Real impls: Gmail (WS-B2) and MS Graph (WS-B2)."""

    def list_message_ids(self, mailbox: str, after_epoch_ms: int) -> list[MessageRef]:
        """Message refs newer than the checkpoint, ascending by time."""
        ...

    def get_message(self, mailbox: str, message_id: str) -> EmailMessage:
        """Full message with decoded attachments. Raises KeyError if not found."""
        ...


class FakeEmailConnector:
    """In-memory EmailConnector for tests and WS-C pipeline development."""

    def __init__(self) -> None:
        self._by_mailbox: dict[str, list[EmailMessage]] = {}

    def add(self, message: EmailMessage) -> None:
        self._by_mailbox.setdefault(message.mailbox, []).append(message)

    def list_message_ids(self, mailbox: str, after_epoch_ms: int) -> list[MessageRef]:
        refs = []
        for m in self._by_mailbox.get(mailbox, []):
            epoch_ms = int(m.internal_date.timestamp() * 1000)
            if epoch_ms > after_epoch_ms:
                refs.append(MessageRef(id=m.id, epoch_ms=epoch_ms))
        return sorted(refs, key=lambda r: r.epoch_ms)

    def get_message(self, mailbox: str, message_id: str) -> EmailMessage:
        for m in self._by_mailbox.get(mailbox, []):
            if m.id == message_id:
                return m
        raise KeyError(message_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_email.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/email.py tests/test_fake_email.py
git -c commit.gpgsign=false commit -m "feat(ws-b1): EmailConnector Protocol + Fake"
```

---

## Task 4: QboConnector Protocol + FakeQboConnector

**Files:**
- Create: `src/bookkeeper_agent/connectors/qbo.py`
- Test: `tests/test_fake_qbo.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fake_qbo.py`:
```python
from datetime import date

from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    BillLine,
    Vendor,
    VendorDraft,
)

REALM = "111"


def test_find_vendor_case_insensitive():
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME Supplies"))
    assert qbo.find_vendor(REALM, "acme supplies").id == "V1"
    assert qbo.find_vendor(REALM, "Unknown") is None


def test_list_accounts_and_realm_isolation():
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    qbo.seed_account("222", Account(id="A9", name="Rent", account_type="Expense"))
    names = [a.name for a in qbo.list_accounts(REALM)]
    assert names == ["Supplies"]


def test_recent_bills_for_vendor():
    qbo = FakeQboConnector()
    qbo.seed_bill(REALM, Bill(id="B1", vendor_id="V1", total=100.0, doc_number="1"))
    qbo.seed_bill(REALM, Bill(id="B2", vendor_id="V2", total=50.0, doc_number="2"))
    bills = qbo.recent_bills_for_vendor(REALM, "V1")
    assert [b.id for b in bills] == ["B1"]


def test_find_duplicate_bill_matches_vendor_doc_total():
    qbo = FakeQboConnector()
    qbo.seed_bill(REALM, Bill(id="B1", vendor_id="V1", total=250.0, doc_number="INV-100"))
    dup = qbo.find_duplicate_bill(REALM, "V1", "INV-100", 250.0)
    assert dup is not None and dup.id == "B1"
    assert qbo.find_duplicate_bill(REALM, "V1", "INV-100", 999.0) is None
    assert qbo.find_duplicate_bill(REALM, "V1", "OTHER", 250.0) is None


def test_create_vendor_allocates_id_and_is_findable():
    qbo = FakeQboConnector()
    v = qbo.create_vendor(REALM, VendorDraft(display_name="New Vendor"))
    assert v.id
    assert qbo.find_vendor(REALM, "new vendor").id == v.id


def test_create_bill_records_draft_and_returns_bill():
    qbo = FakeQboConnector()
    draft = BillDraft(
        vendor_id="V1", txn_date=date(2026, 6, 1), total=250.0,
        lines=(BillLine(amount=250.0, account_id="A1"),), doc_number="INV-100",
    )
    bill = qbo.create_bill(REALM, draft)
    assert bill.id and bill.total == 250.0
    assert qbo.created_bills == [(REALM, draft)]
    # the created bill is now duplicate-detectable
    assert qbo.find_duplicate_bill(REALM, "V1", "INV-100", 250.0).id == bill.id


def test_attach_pdf_records():
    qbo = FakeQboConnector()
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    qbo.attach_pdf(REALM, "B1", att)
    assert qbo.attachments == [(REALM, "B1", att)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_qbo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.qbo'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/qbo.py`:
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    Vendor,
    VendorDraft,
)


@runtime_checkable
class QboConnector(Protocol):
    """QuickBooks Online access, scoped per company (realm). Real impl: WS-B3."""

    def find_vendor(self, realm: str, display_name: str) -> Vendor | None: ...

    def list_accounts(self, realm: str) -> list[Account]: ...

    def recent_bills_for_vendor(self, realm: str, vendor_id: str, limit: int = 20) -> list[Bill]: ...

    def find_duplicate_bill(
        self, realm: str, vendor_id: str, doc_number: str | None, total: float
    ) -> Bill | None: ...

    def create_vendor(self, realm: str, draft: VendorDraft) -> Vendor: ...

    def create_bill(self, realm: str, draft: BillDraft) -> Bill: ...

    def attach_pdf(self, realm: str, bill_id: str, attachment: Attachment) -> None: ...


class FakeQboConnector:
    """In-memory QboConnector for tests and WS-C pipeline development.

    State is keyed by realm so cross-book isolation can be asserted. `seed_*`
    methods set up read state; `created_bills` / `created_vendors` / `attachments`
    record writes for assertions.
    """

    def __init__(self) -> None:
        self._vendors: dict[str, dict[str, Vendor]] = {}  # realm -> name.lower() -> Vendor
        self._accounts: dict[str, list[Account]] = {}
        self._bills: dict[str, list[Bill]] = {}
        self.created_vendors: list[tuple[str, VendorDraft]] = []
        self.created_bills: list[tuple[str, BillDraft]] = []
        self.attachments: list[tuple[str, str, Attachment]] = []
        self._counter = 0

    # --- seed helpers (read state) ---
    def seed_vendor(self, realm: str, vendor: Vendor) -> None:
        self._vendors.setdefault(realm, {})[vendor.display_name.lower()] = vendor

    def seed_account(self, realm: str, account: Account) -> None:
        self._accounts.setdefault(realm, []).append(account)

    def seed_bill(self, realm: str, bill: Bill) -> None:
        self._bills.setdefault(realm, []).append(bill)

    def _alloc(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    # --- QboConnector protocol ---
    def find_vendor(self, realm: str, display_name: str) -> Vendor | None:
        return self._vendors.get(realm, {}).get(display_name.lower())

    def list_accounts(self, realm: str) -> list[Account]:
        return list(self._accounts.get(realm, []))

    def recent_bills_for_vendor(self, realm: str, vendor_id: str, limit: int = 20) -> list[Bill]:
        return [b for b in self._bills.get(realm, []) if b.vendor_id == vendor_id][:limit]

    def find_duplicate_bill(
        self, realm: str, vendor_id: str, doc_number: str | None, total: float
    ) -> Bill | None:
        for b in self._bills.get(realm, []):
            if b.vendor_id == vendor_id and b.doc_number == doc_number and abs(b.total - total) < 0.005:
                return b
        return None

    def create_vendor(self, realm: str, draft: VendorDraft) -> Vendor:
        vendor = Vendor(id=self._alloc("V"), display_name=draft.display_name)
        self.seed_vendor(realm, vendor)
        self.created_vendors.append((realm, draft))
        return vendor

    def create_bill(self, realm: str, draft: BillDraft) -> Bill:
        bill = Bill(
            id=self._alloc("B"),
            vendor_id=draft.vendor_id,
            total=draft.total,
            doc_number=draft.doc_number,
        )
        self._bills.setdefault(realm, []).append(bill)
        self.created_bills.append((realm, draft))
        return bill

    def attach_pdf(self, realm: str, bill_id: str, attachment: Attachment) -> None:
        self.attachments.append((realm, bill_id, attachment))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_qbo.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/qbo.py tests/test_fake_qbo.py
git -c commit.gpgsign=false commit -m "feat(ws-b1): QboConnector Protocol + Fake"
```

---

## Task 5: SlackConnector Protocol + FakeSlackConnector

**Files:**
- Create: `src/bookkeeper_agent/connectors/slack.py`
- Test: `tests/test_fake_slack.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fake_slack.py`:
```python
from datetime import date

from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.types import BillProposal


def _proposal():
    return BillProposal(
        client_key="habit-pilates", client_display="Habit Pilates", company_realm="111",
        vendor_name="ACME", is_new_vendor=False, total=250.0, currency="USD",
        txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30), doc_number="INV-100",
        proposed_account_name="Supplies", confidence=0.9, reasoning="precedent",
        pdf_filename="invoice.pdf",
    )


def test_post_proposal_records_and_returns_ref():
    slack = FakeSlackConnector()
    ref = slack.post_proposal("C-APPROVALS", _proposal())
    assert ref.channel == "C-APPROVALS" and ref.ts
    assert len(slack.posted) == 1
    channel, proposal = slack.posted[0]
    assert channel == "C-APPROVALS" and proposal.vendor_name == "ACME"


def test_post_receipt_records_thread():
    slack = FakeSlackConnector()
    parent = slack.post_proposal("C-APPROVALS", _proposal())
    slack.post_receipt("C-APPROVALS", "Posted bill B1 to Habit Pilates", thread_ts=parent.ts)
    assert slack.receipts == [("C-APPROVALS", "Posted bill B1 to Habit Pilates", parent.ts)]


def test_timestamps_are_unique():
    slack = FakeSlackConnector()
    a = slack.post_proposal("C", _proposal())
    b = slack.post_proposal("C", _proposal())
    assert a.ts != b.ts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_slack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.slack'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/slack.py`:
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bookkeeper_agent.connectors.types import BillProposal, SlackMessageRef


@runtime_checkable
class SlackConnector(Protocol):
    """Outbound Slack messaging. Real impl: WS-B4 (Block Kit + Socket Mode).

    Receiving Approve/Reject button clicks is wired in WS-C (the write-gate),
    not here — this Protocol covers sending only.
    """

    def post_proposal(self, channel: str, proposal: BillProposal) -> SlackMessageRef:
        """Post a bill approval card. Returns a ref (channel + message ts)."""
        ...

    def post_receipt(self, channel: str, text: str, thread_ts: str | None = None) -> SlackMessageRef:
        """Post a confirmation/result message, optionally threaded under a card."""
        ...


class FakeSlackConnector:
    """In-memory SlackConnector for tests and WS-C pipeline development."""

    def __init__(self) -> None:
        self.posted: list[tuple[str, BillProposal]] = []
        self.receipts: list[tuple[str, str, str | None]] = []
        self._counter = 0

    def _next_ts(self) -> str:
        self._counter += 1
        return f"{self._counter}.000100"

    def post_proposal(self, channel: str, proposal: BillProposal) -> SlackMessageRef:
        self.posted.append((channel, proposal))
        return SlackMessageRef(channel=channel, ts=self._next_ts())

    def post_receipt(self, channel: str, text: str, thread_ts: str | None = None) -> SlackMessageRef:
        self.receipts.append((channel, text, thread_ts))
        return SlackMessageRef(channel=channel, ts=self._next_ts())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_slack.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/slack.py tests/test_fake_slack.py
git -c commit.gpgsign=false commit -m "feat(ws-b1): SlackConnector Protocol + Fake"
```

---

## Task 6: Full-suite green + WS-B1 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — WS-A's 22 tests plus WS-B1's new tests (6 + 5 + 4 + 7 + 3 = 25), i.e. 47 total.

- [ ] **Step 2: Confirm Fakes satisfy their Protocols at runtime**

Run:
```bash
cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -c "from bookkeeper_agent.connectors.email import EmailConnector, FakeEmailConnector; from bookkeeper_agent.connectors.qbo import QboConnector, FakeQboConnector; from bookkeeper_agent.connectors.slack import SlackConnector, FakeSlackConnector; print(isinstance(FakeEmailConnector(), EmailConnector), isinstance(FakeQboConnector(), QboConnector), isinstance(FakeSlackConnector(), SlackConnector))"
```
Expected: `True True True`

- [ ] **Step 3: Confirm working tree clean / no secrets tracked**

Run: `git status --porcelain` (expect clean) and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 4: Tag the workstream**

```bash
git tag ws-b1
```

---

## Self-review against the spec

- **§3 connectors as a general layer (email, QBO, Slack; later Ramp)** → `connectors/` package with one Protocol per service; new services add a module. ✓
- **§3 connectors behind well-defined interfaces with Fakes (so WS-C is testable without live calls)** → Tasks 3–5 define Protocols + Fakes; Task 6 step 2 proves the Fakes satisfy the Protocols. ✓
- **§5 secrets encrypted at rest via one audited path** → Task 2 `TokenStore` is the only connector-boundary place secrets are encrypted/decrypted (over WS-A `OAuthToken` + `TokenCipher`); `test_secret_is_encrypted_at_rest` proves plaintext never lands in the row. ✓
- **§5 multi-book isolation carried in the data** → `BillProposal.company_realm` (Task 1) carries the fixed binding to the card/writer; `FakeQboConnector` is realm-keyed so WS-C isolation tests can assert a bill can't cross books (`test_list_accounts_and_realm_isolation`). ✓
- **§4 history-driven categorization inputs** → `QboConnector.list_accounts` + `recent_bills_for_vendor` (Task 4) supply the chart of accounts and vendor precedent the categorizer needs. ✓
- **§4 duplicate detection** → `QboConnector.find_duplicate_bill` (vendor + doc_number + total) (Task 4). ✓
- **§4 vendor match / propose-create** → `find_vendor` + `create_vendor` (Task 4). ✓
- **§4 attach PDF to the bill** → `attach_pdf` (Task 4). ✓
- **§4 Slack approval card** → `SlackConnector.post_proposal` + `BillProposal` view-model (Tasks 1, 5). ✓

**Deferred to WS-B2/3/4 (correctly out of scope here):** real Gmail/Graph HTTP (B2), QBO OAuth connect + token refresh + real read/write/attach (B3), real Slack Block Kit rendering + Socket Mode receive (B4 + WS-C write-gate). All implement the Protocols defined here, so WS-C can be built against the Fakes in parallel.

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** Protocol method signatures match their Fake implementations exactly (`list_message_ids`/`get_message`; `find_vendor`/`list_accounts`/`recent_bills_for_vendor`/`find_duplicate_bill`/`create_vendor`/`create_bill`/`attach_pdf`; `post_proposal`/`post_receipt`), and all reference the `types.py` dataclasses defined in Task 1. `TokenStore.get_secret/put_secret/delete_secret` match the tests.
```
