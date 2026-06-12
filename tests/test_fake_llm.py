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
