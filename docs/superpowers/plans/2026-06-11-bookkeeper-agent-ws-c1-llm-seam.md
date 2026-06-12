# Bookkeeper Agent — WS-C1 LLM Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM seam — a small `LlmClient` interface with two operations (`classify_and_extract`, `categorize`), a `FakeLlmClient` for tests, and a real `AnthropicLlmClient` that calls Claude (Opus 4.8) via structured outputs, gated by the spend cap and metered for cost — so the rest of the bills pipeline (WS-C2–C5) can be built and tested without the live API.

**Architecture:** A `llm/` package. `types.py` holds plain frozen result/context dataclasses (money is `Decimal`). `client.py` defines the `@runtime_checkable` `LlmClient` Protocol + `FakeLlmClient`. `anthropic_client.py` wraps `anthropic.Anthropic` — `classify_and_extract` sends the email text + the invoice PDF/image to Claude and parses a structured `BillExtraction`; `categorize` sends the chart of accounts + vendor precedent and parses a `CategorySuggestion`. Every call runs `cost_meter.check_cap()` first (raises `SpendCapExceeded` at 100%) and `cost_meter.record(...)` after. The Anthropic client is dependency-injected, so tests stub it and run fully offline.

**Tech Stack:** Python 3.12, `anthropic` SDK (structured outputs via `messages.parse`), `pydantic` (already a transitive dep; pinned here), the WS-A `CostMeter`, the WS-B1 connector types. Model: `claude-opus-4-8`.

This is WS-C1 of the WS-C pipeline group (C2 pre-screen + models, C3 propose pipeline, C4 write-gate, C5 poller). Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`. Builds on WS-A (`ws-a`) and WS-B1 (`ws-b1`).

---

## File structure (created by this plan)

```
src/bookkeeper_agent/llm/
  __init__.py
  types.py             # EmailContext, BillExtraction, CategorizationContext, CategorySuggestion
  client.py            # LlmClient Protocol + FakeLlmClient
  anthropic_client.py  # AnthropicLlmClient (real; structured outputs, cost-metered, spend-cap-gated)
tests/
  test_llm_types.py
  test_fake_llm.py
  test_anthropic_llm_client.py   # offline — stubs the anthropic client
```

`types.py` is data-only. `client.py` is the contract + Fake. `anthropic_client.py` is the only file that imports `anthropic`/`pydantic` and is tested with a stub (no network).

---

## Task 1: LLM result & context types

**Files:**
- Create: `src/bookkeeper_agent/llm/__init__.py` (empty)
- Create: `src/bookkeeper_agent/llm/types.py`
- Test: `tests/test_llm_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm_types.py`:
```python
from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.types import Account, Attachment
from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


def test_email_context_defaults():
    ctx = EmailContext(sender="v@acme.com", subject="Invoice", body_text="hi")
    assert ctx.attachments == ()


def test_email_context_with_attachment():
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    ctx = EmailContext(sender="v@acme.com", subject="Invoice", body_text="hi", attachments=(att,))
    assert ctx.attachments[0].filename == "invoice.pdf"


def test_bill_extraction_not_a_bill():
    ex = BillExtraction(is_bill=False, classification_confidence=0.97)
    assert ex.is_bill is False
    assert ex.vendor_name is None
    assert ex.total is None
    assert ex.currency == "USD"


def test_bill_extraction_full():
    ex = BillExtraction(
        is_bill=True,
        classification_confidence=0.95,
        vendor_name="ACME",
        doc_number="INV-100",
        txn_date=date(2026, 6, 1),
        due_date=date(2026, 6, 30),
        total=Decimal("250.00"),
        currency="USD",
        line_hint="Cleaning supplies",
    )
    assert ex.total == Decimal("250.00")
    assert ex.line_hint == "Cleaning supplies"


def test_categorization_context_and_suggestion():
    ctx = CategorizationContext(
        vendor_name="ACME",
        total=Decimal("250.00"),
        accounts=(Account(id="A1", name="Supplies", account_type="Expense"),),
        precedents=("ACME -> Supplies (3 prior bills)",),
        line_hint="Cleaning supplies",
    )
    assert ctx.accounts[0].id == "A1"
    sug = CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="precedent")
    assert sug.account_id == "A1"


def test_frozen():
    sug = CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="x")
    with pytest.raises(Exception):
        sug.confidence = 0.1  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_llm_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.llm'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/llm/__init__.py`:
```python
```
(empty file)

`src/bookkeeper_agent/llm/types.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_llm_types.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/llm/__init__.py src/bookkeeper_agent/llm/types.py tests/test_llm_types.py
git -c commit.gpgsign=false commit -m "feat(ws-c1): LLM result & context types"
```

---

## Task 2: LlmClient Protocol + FakeLlmClient

**Files:**
- Create: `src/bookkeeper_agent/llm/client.py`
- Test: `tests/test_fake_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fake_llm.py`:
```python
import inspect
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.types import Account
from bookkeeper_agent.llm.client import FakeLlmClient, LlmClient
from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


def test_fake_returns_configured_results_and_records_calls():
    extraction = BillExtraction(is_bill=True, vendor_name="ACME", total=Decimal("250.00"))
    suggestion = CategorySuggestion(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="x")
    fake = FakeLlmClient(extraction=extraction, suggestion=suggestion)

    ectx = EmailContext(sender="v@acme.com", subject="Invoice", body_text="hi")
    assert fake.classify_and_extract(ectx).vendor_name == "ACME"
    assert fake.classify_calls == [ectx]

    cctx = CategorizationContext(vendor_name="ACME", total=Decimal("250.00"),
                                 accounts=(Account(id="A1", name="Supplies", account_type="Expense"),))
    assert fake.categorize(cctx).account_id == "A1"
    assert fake.categorize_calls == [cctx]


def test_fake_unconfigured_raises():
    fake = FakeLlmClient()
    with pytest.raises(AssertionError):
        fake.classify_and_extract(EmailContext(sender="x", subject="y", body_text="z"))


def test_fake_satisfies_protocol():
    assert isinstance(FakeLlmClient(), LlmClient)


def test_fake_signatures_match_protocol():
    def params(fn):
        return [p for p in inspect.signature(fn).parameters if p != "self"]

    for name in ("classify_and_extract", "categorize"):
        assert params(getattr(LlmClient, name)) == params(getattr(FakeLlmClient, name)), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.llm.client'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/llm/client.py`:
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


@runtime_checkable
class LlmClient(Protocol):
    """The two model operations the bills pipeline needs. Real impl:
    AnthropicLlmClient. Fake: FakeLlmClient."""

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction: ...

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion: ...


class FakeLlmClient:
    """In-memory LlmClient for pipeline tests. Returns the configured result
    and records the contexts it was called with."""

    def __init__(
        self,
        extraction: BillExtraction | None = None,
        suggestion: CategorySuggestion | None = None,
    ) -> None:
        self._extraction = extraction
        self._suggestion = suggestion
        self.classify_calls: list[EmailContext] = []
        self.categorize_calls: list[CategorizationContext] = []

    def set_extraction(self, extraction: BillExtraction) -> None:
        self._extraction = extraction

    def set_suggestion(self, suggestion: CategorySuggestion) -> None:
        self._suggestion = suggestion

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction:
        self.classify_calls.append(ctx)
        if self._extraction is None:
            raise AssertionError("FakeLlmClient.classify_and_extract: no extraction configured")
        return self._extraction

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion:
        self.categorize_calls.append(ctx)
        if self._suggestion is None:
            raise AssertionError("FakeLlmClient.categorize: no suggestion configured")
        return self._suggestion
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_fake_llm.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/llm/client.py tests/test_fake_llm.py
git -c commit.gpgsign=false commit -m "feat(ws-c1): LlmClient Protocol + Fake"
```

---

## Task 3: AnthropicLlmClient (real, structured outputs, cost-gated)

**Files:**
- Modify: `pyproject.toml` (pin `pydantic>=2` explicitly — it is already installed transitively via `anthropic`)
- Create: `src/bookkeeper_agent/llm/anthropic_client.py`
- Test: `tests/test_anthropic_llm_client.py`

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_llm_client.py`:
```python
from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.types import Account, Attachment
from bookkeeper_agent.costs import CostMeter, SpendCapExceeded
from bookkeeper_agent.llm.anthropic_client import (
    AnthropicLlmClient,
    _CategorySchema,
    _ExtractionSchema,
)
from bookkeeper_agent.llm.types import CategorizationContext, EmailContext


class _StubUsage:
    input_tokens = 1000
    output_tokens = 200
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _StubResp:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.usage = _StubUsage()
        self._request_id = "req_test"


class _StubMessages:
    def __init__(self, parsed):
        self._parsed = parsed
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _StubResp(self._parsed)


class _StubClient:
    def __init__(self, parsed):
        self.messages = _StubMessages(parsed)


def test_classify_and_extract_converts_and_records_cost(engine):
    parsed = _ExtractionSchema(
        is_bill=True, classification_confidence=0.95, vendor_name="ACME",
        doc_number="INV-100", txn_date="2026-06-01", due_date="2026-06-30",
        total="250.00", currency="USD", line_hint="Supplies",
    )
    stub = _StubClient(parsed)
    meter = CostMeter(engine, monthly_cap=100.0)
    llm = AnthropicLlmClient(stub, "claude-opus-4-8", meter)

    att = Attachment("invoice.pdf", "application/pdf", b"%PDF-1.4 bytes")
    ex = llm.classify_and_extract(EmailContext("v@acme.com", "Invoice", "body", (att,)))

    assert ex.is_bill is True
    assert ex.vendor_name == "ACME"
    assert ex.txn_date == date(2026, 6, 1)
    assert ex.total == Decimal("250.00")  # string -> Decimal
    # cost recorded for this month
    assert meter.month_total() > 0
    # the PDF was sent as a document content block
    content = stub.messages.calls[0]["messages"][0]["content"]
    assert any(b.get("type") == "document" for b in content)


def test_categorize_builds_prompt_with_accounts_and_precedents(engine):
    parsed = _CategorySchema(account_id="A1", account_name="Supplies", confidence=0.9, reasoning="precedent")
    stub = _StubClient(parsed)
    meter = CostMeter(engine, monthly_cap=100.0)
    llm = AnthropicLlmClient(stub, "claude-opus-4-8", meter)

    ctx = CategorizationContext(
        vendor_name="ACME", total=Decimal("250.00"),
        accounts=(Account(id="A1", name="Supplies", account_type="Expense"),),
        precedents=("ACME -> Supplies (3 prior bills)",),
    )
    sug = llm.categorize(ctx)
    assert sug.account_id == "A1"
    prompt = stub.messages.calls[0]["messages"][0]["content"]
    assert "A1: Supplies" in prompt and "ACME -> Supplies (3 prior bills)" in prompt


def test_spend_cap_blocks_before_calling_model(engine):
    parsed = _ExtractionSchema(is_bill=False)
    stub = _StubClient(parsed)
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=2_000_000)  # $10 -> at cap
    llm = AnthropicLlmClient(stub, "claude-opus-4-8", meter)

    with pytest.raises(SpendCapExceeded):
        llm.classify_and_extract(EmailContext("v", "s", "b"))
    assert stub.messages.calls == []  # model never called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_anthropic_llm_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.llm.anthropic_client'`

- [ ] **Step 3a: Pin pydantic in pyproject.toml**

In `pyproject.toml`, add `"pydantic>=2"` to the `dependencies` list (it is already installed transitively via `anthropic`; this just makes it explicit). The list becomes:
```toml
dependencies = [
    "anthropic>=0.49",
    "SQLAlchemy>=2.0",
    "cryptography>=42",
    "python-dotenv>=1.0",
    "pydantic>=2",
]
```

- [ ] **Step 3b: Write the implementation**

`src/bookkeeper_agent/llm/anthropic_client.py`:
```python
from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from bookkeeper_agent.costs import CostMeter
from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


class _ExtractionSchema(BaseModel):
    is_bill: bool
    classification_confidence: float = 0.0
    vendor_name: str | None = None
    doc_number: str | None = None
    txn_date: str | None = None  # ISO date "YYYY-MM-DD"
    due_date: str | None = None
    total: str | None = None  # plain decimal string, e.g. "250.00"
    currency: str = "USD"
    line_hint: str | None = None


class _CategorySchema(BaseModel):
    account_id: str
    account_name: str
    confidence: float
    reasoning: str


_EXTRACT_SYSTEM = (
    "You are an accounts-payable assistant. Decide whether an email is a vendor "
    "bill or invoice (an account payable). If it is, extract the fields from the "
    "email and any attached invoice. If it is NOT a payable (newsletter, receipt "
    "for an already-paid card charge, personal mail, statement), set is_bill=false "
    "and leave the other fields null. Dates must be ISO YYYY-MM-DD. total must be a "
    "plain decimal string like \"250.00\". Never invent values — use null when unsure."
)

_CATEGORIZE_SYSTEM = (
    "You categorize accounts-payable bills using the client's own chart of accounts "
    "and how they booked prior bills. Choose the single best account_id that is "
    "present in the provided chart of accounts. Give a confidence between 0 and 1 and "
    "a brief reasoning, citing precedent when it applies."
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


class AnthropicLlmClient:
    """Real LlmClient backed by Claude. The anthropic client is injected so this
    is unit-testable offline. Every call checks the spend cap first and records
    token cost after."""

    def __init__(self, client, model: str, cost_meter: CostMeter, capability: str = "bills"):
        self._client = client
        self._model = model
        self._cost = cost_meter
        self._capability = capability

    def _email_content(self, ctx: EmailContext) -> list[dict]:
        blocks: list[dict] = []
        for att in ctx.attachments:
            data = base64.standard_b64encode(att.content).decode()
            if att.mime_type == "application/pdf":
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                })
            elif att.mime_type.startswith("image/"):
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": att.mime_type, "data": data},
                })
            # other attachment types are ignored for extraction
        blocks.append({
            "type": "text",
            "text": f"From: {ctx.sender}\nSubject: {ctx.subject}\n\n{ctx.body_text}",
        })
        return blocks

    def _record(self, resp) -> None:
        u = resp.usage
        self._cost.record(
            self._model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(resp, "_request_id", None),
            capability=self._capability,
        )

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction:
        self._cost.check_cap()
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            system=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": self._email_content(ctx)}],
            output_format=_ExtractionSchema,
        )
        self._record(resp)
        p = resp.parsed_output
        return BillExtraction(
            is_bill=p.is_bill,
            classification_confidence=p.classification_confidence,
            vendor_name=p.vendor_name,
            doc_number=p.doc_number,
            txn_date=_parse_date(p.txn_date),
            due_date=_parse_date(p.due_date),
            total=_parse_decimal(p.total),
            currency=p.currency or "USD",
            line_hint=p.line_hint,
        )

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion:
        self._cost.check_cap()
        accounts_txt = "\n".join(f"- {a.id}: {a.name} ({a.account_type})" for a in ctx.accounts)
        precedents_txt = "\n".join(f"- {p}" for p in ctx.precedents) or "(no prior bills for this vendor)"
        prompt = (
            f"Vendor: {ctx.vendor_name}\n"
            f"Amount: {ctx.total}\n"
            f"Line hint: {ctx.line_hint or ''}\n\n"
            f"Chart of accounts:\n{accounts_txt}\n\n"
            f"How this client booked prior bills from this vendor:\n{precedents_txt}\n\n"
            "Choose the single best account_id from the chart for this bill."
        )
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=_CATEGORIZE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=_CategorySchema,
        )
        self._record(resp)
        p = resp.parsed_output
        return CategorySuggestion(
            account_id=p.account_id,
            account_name=p.account_name,
            confidence=p.confidence,
            reasoning=p.reasoning,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_anthropic_llm_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/bookkeeper_agent/llm/anthropic_client.py tests/test_anthropic_llm_client.py
git -c commit.gpgsign=false commit -m "feat(ws-c1): AnthropicLlmClient (structured outputs, cost-gated)"
```

---

## Task 4: Full-suite green + WS-C1 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — WS-A + WS-B1 (53) plus WS-C1's new tests (6 + 4 + 3 = 13), i.e. 66 total.

- [ ] **Step 2: Confirm the Fake satisfies the Protocol**

Run:
```bash
cd /c/Users/Cole/bookkeeper-agent && PYTHONPATH=src ./.venv/Scripts/python.exe -c "from bookkeeper_agent.llm.client import LlmClient, FakeLlmClient; print(isinstance(FakeLlmClient(), LlmClient))"
```
Expected: `True`

- [ ] **Step 3: Confirm no live network call is made by the suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && grep -rn "Anthropic(" tests/ ; echo "exit: $?"`
Expected: no matches (the real anthropic client is never constructed in tests — `AnthropicLlmClient` is given a stub). A non-zero grep exit with no output is correct.

- [ ] **Step 4: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` (expect clean) and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 5: Tag the workstream**

```bash
git tag ws-c1
```

---

## Self-review against the spec

- **§2/§3 "runs off Claude's model"** → `AnthropicLlmClient` (Task 3) calls Claude (`claude-opus-4-8`) via structured outputs. ✓
- **§4 classify "is this an AP bill?" + extract fields** → `classify_and_extract` returns `BillExtraction` (is_bill + vendor/doc/dates/total/line_hint). ✓
- **§4 reads the invoice PDF/image** → `_email_content` sends a `document` block for PDFs and an `image` block for images. ✓
- **§4 history-driven categorization (chart of accounts + vendor precedent, with confidence + reasoning)** → `categorize` takes `CategorizationContext(accounts, precedents)` and returns `CategorySuggestion(account_id, confidence, reasoning)`; the prompt embeds both. ✓
- **§5 spend cap (hard stop at 100%) gates model use** → every method calls `cost_meter.check_cap()` *before* the model call; `test_spend_cap_blocks_before_calling_model` proves the model is never called once capped. ✓
- **§5 cost metering** → every call records token usage via `cost_meter.record(...)`; `test_classify_and_extract_converts_and_records_cost` asserts `month_total() > 0`. ✓
- **§3 testable without live API (so WS-C2–C5 build on Fakes)** → `LlmClient` Protocol + `FakeLlmClient` (Task 2); the real client is dependency-injected and tested with a stub (Task 3). No test constructs a live `anthropic.Anthropic` (Task 4 step 3). ✓
- **money is Decimal** → `BillExtraction.total` / `CategorizationContext.total` are `Decimal`; the extractor parses the model's decimal *string* into `Decimal` (avoids float in the JSON schema). ✓

**Deferred to WS-C2–C5 (correctly out of scope here):** pre-screen heuristic + `PendingBill`/`Checkpoint` models (C2); the `process_message` propose pipeline that wires email→LLM→QBO→Slack and enforces the privacy "drop non-bill content" rule (C3); the approve/reject write-gate with company-binding enforcement and idempotency (C4); the checkpointed poller (C5). All consume the `LlmClient` + connector Protocols defined here and in WS-B1.

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** `LlmClient.classify_and_extract(EmailContext) -> BillExtraction` and `categorize(CategorizationContext) -> CategorySuggestion` match across the Protocol, `FakeLlmClient`, and `AnthropicLlmClient`; the test stub mirrors the `messages.parse(...) -> resp.parsed_output / resp.usage / resp._request_id` shape the SDK returns; `_parse_decimal`/`_parse_date` convert the schema's string fields into the `Decimal`/`date` types the dataclasses declare.
```
