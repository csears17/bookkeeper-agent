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


def test_parse_decimal_rejects_non_finite_and_garbage():
    from decimal import Decimal

    from bookkeeper_agent.llm.anthropic_client import _parse_decimal

    assert _parse_decimal("250.00") == Decimal("250.00")
    assert _parse_decimal(None) is None
    assert _parse_decimal("") is None
    assert _parse_decimal("abc") is None
    assert _parse_decimal("NaN") is None
    assert _parse_decimal("Infinity") is None
    assert _parse_decimal("-Infinity") is None


def test_spend_cap_blocks_before_calling_model(engine):
    parsed = _ExtractionSchema(is_bill=False)
    stub = _StubClient(parsed)
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=2_000_000)  # $10 -> at cap
    llm = AnthropicLlmClient(stub, "claude-opus-4-8", meter)

    with pytest.raises(SpendCapExceeded):
        llm.classify_and_extract(EmailContext("v", "s", "b"))
    assert stub.messages.calls == []  # model never called
