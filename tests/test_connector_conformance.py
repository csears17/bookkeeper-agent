"""Pin the Protocol <-> Fake contract that WS-B1 exists to guarantee.

If a Fake's method set or parameter names drift from its Protocol, WS-C would
compile against the Fake but break on the real connector. These tests catch that.
"""
from __future__ import annotations

import inspect

import pytest

from bookkeeper_agent.connectors.email import EmailConnector, FakeEmailConnector
from bookkeeper_agent.connectors.qbo import QboConnector, FakeQboConnector
from bookkeeper_agent.connectors.slack import SlackConnector, FakeSlackConnector

CASES = [
    (EmailConnector, FakeEmailConnector, ["list_message_ids", "get_message"]),
    (
        QboConnector,
        FakeQboConnector,
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
    ),
    (SlackConnector, FakeSlackConnector, ["post_proposal", "post_receipt"]),
]


def _params(fn) -> list[str]:
    return [p for p in inspect.signature(fn).parameters if p != "self"]


@pytest.mark.parametrize("protocol, fake, methods", CASES)
def test_fake_satisfies_protocol(protocol, fake, methods):
    assert isinstance(fake(), protocol)


@pytest.mark.parametrize("protocol, fake, methods", CASES)
def test_fake_method_signatures_match_protocol(protocol, fake, methods):
    for name in methods:
        assert hasattr(fake, name), f"{fake.__name__} missing {name}"
        assert _params(getattr(protocol, name)) == _params(getattr(fake, name)), name
