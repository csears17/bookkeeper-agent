from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.slack import SlackConnector
from bookkeeper_agent.connectors.slack_http import HttpxSlackConnector, SlackApiError
from bookkeeper_agent.connectors.types import BillProposal


def _proposal():
    return BillProposal(
        client_key="habit-pilates", client_display="Habit Pilates", company_realm="111",
        vendor_name="ACME", is_new_vendor=False, total=Decimal("250.00"), currency="USD",
        txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30), doc_number="INV-100",
        proposed_account_name="Supplies", confidence=0.9, reasoning="precedent", pdf_filename="invoice.pdf",
    )


class _StubApi:
    def __init__(self, response):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        return self._response


def test_satisfies_protocol():
    conn = HttpxSlackConnector("xoxb-token", api_post=_StubApi({"ok": True}))
    assert isinstance(conn, SlackConnector)


def test_post_proposal_calls_chat_postmessage_and_returns_ref():
    api = _StubApi({"ok": True, "channel": "C1", "ts": "1717.0001"})
    conn = HttpxSlackConnector("xoxb-token", api_post=api)
    ref = conn.post_proposal("C-APPROVALS", _proposal())
    assert ref.channel == "C1" and ref.ts == "1717.0001"
    method, payload = api.calls[0]
    assert method == "chat.postMessage"
    assert payload["channel"] == "C-APPROVALS"
    assert payload["blocks"]
    assert "Habit Pilates" in payload["text"]


def test_post_receipt_threads():
    api = _StubApi({"ok": True, "channel": "C1", "ts": "2.0"})
    conn = HttpxSlackConnector("xoxb-token", api_post=api)
    conn.post_receipt("C1", "done", thread_ts="1.0")
    _, payload = api.calls[0]
    assert payload["thread_ts"] == "1.0" and payload["text"] == "done"


def test_update_resolved_uses_chat_update():
    import json

    api = _StubApi({"ok": True})
    conn = HttpxSlackConnector("xoxb-token", api_post=api)
    conn.update_resolved("C1", "1.0", "Approved by Cole")
    method, payload = api.calls[0]
    assert method == "chat.update"
    assert payload["channel"] == "C1" and payload["ts"] == "1.0"
    assert "Approved by Cole" in json.dumps(payload)


def test_api_error_raises():
    conn = HttpxSlackConnector("xoxb-token", api_post=_StubApi({"ok": False, "error": "channel_not_found"}))
    with pytest.raises(SlackApiError, match="channel_not_found"):
        conn.post_proposal("C-bad", _proposal())


def test_download_file_uses_injected_getter():
    conn = HttpxSlackConnector("xoxb-token", api_post=_StubApi({"ok": True}),
                               file_get=lambda url: b"%PDF-bytes")
    assert conn.download_file("https://files.slack.com/x") == b"%PDF-bytes"
