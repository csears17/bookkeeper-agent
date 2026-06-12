# Bookkeeper Agent — WS-B4 Real Slack Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the real Slack side — render the approval card as Block Kit, post/update/download via the Slack Web API (`HttpxSlackConnector`, satisfying the WS-B1 `SlackConnector` Protocol), and parse the inbound events the agent reacts to (Approve/Reject button clicks, file drops) plus resolve the client a drop names. All offline-testable via dependency injection; the live Socket Mode websocket loop is deferred to the end-to-end wiring slice.

**Architecture:** Three focused modules beside the existing `connectors/slack.py` (Protocol + Fake): `slack_blocks.py` (pure Block Kit builders), `slack_http.py` (`HttpxSlackConnector` with an injectable HTTP poster/getter so tests make no network calls), and `slack_events.py` (pure parsers for `block_actions` and file-share events + a client-name resolver). The approval buttons carry stable `action_id`s; a click is mapped back to its `PendingBill` by the message `ts` (already stored on the pending bill in WS-C3) — so no contract change to `post_proposal` is needed.

**Tech Stack:** Python 3.12, `httpx` (pin explicitly; already installed via anthropic), existing deps. Builds on WS-B1 (`SlackConnector`, `BillProposal`, `SlackMessageRef`) and WS-A (`ClientConfig`).

This is WS-B4 of the reprioritized roadmap (spec §9b). Live Socket Mode runner + the Slack-drop adapter + WS-C4 write-gate follow. Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`.

---

## File structure (created/modified by this plan)

```
src/bookkeeper_agent/connectors/
  slack_blocks.py   # NEW: proposal_blocks / receipt_blocks / client_picker_blocks (pure)
  slack_http.py     # NEW: HttpxSlackConnector (post_proposal/post_receipt/update_resolved/download_file)
  slack_events.py   # NEW: ApprovalAction/FileDrop + parse_block_action/parse_file_share/resolve_client
pyproject.toml      # MODIFIED: pin httpx
tests/
  test_slack_blocks.py
  test_slack_http.py
  test_slack_events.py
```

---

## Task 1: Block Kit builders

**Files:**
- Create: `src/bookkeeper_agent/connectors/slack_blocks.py`
- Test: `tests/test_slack_blocks.py`

- [ ] **Step 1: Write the failing test**

`tests/test_slack_blocks.py`:
```python
import json
from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.slack_blocks import (
    client_picker_blocks,
    proposal_blocks,
    receipt_blocks,
)
from bookkeeper_agent.connectors.types import BillProposal


def _proposal(**over):
    base = dict(
        client_key="habit-pilates", client_display="Habit Pilates", company_realm="111",
        vendor_name="ACME", is_new_vendor=False, total=Decimal("250.00"), currency="USD",
        txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30), doc_number="INV-100",
        proposed_account_name="Supplies", confidence=0.9, reasoning="prior ACME bills booked to Supplies",
        pdf_filename="invoice.pdf",
    )
    base.update(over)
    return BillProposal(**base)


def test_proposal_blocks_shows_company_in_bold_and_has_buttons():
    blocks = proposal_blocks(_proposal())
    text = json.dumps(blocks)
    # company shown in bold for visual confirmation
    assert "*Habit Pilates*" in text
    assert "ACME" in text and "250.00" in text and "Supplies" in text and "INV-100" in text
    # exactly one actions block with approve + reject buttons carrying stable action_ids
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions) == 1
    action_ids = {e["action_id"] for e in actions[0]["elements"]}
    assert action_ids == {"approve_bill", "reject_bill"}


def test_proposal_blocks_marks_new_vendor():
    text = json.dumps(proposal_blocks(_proposal(is_new_vendor=True)))
    assert "NEW" in text


def test_receipt_blocks_is_plain_section():
    blocks = receipt_blocks("Posted bill B1 to Habit Pilates")
    assert blocks[0]["type"] == "section"
    assert "Posted bill B1" in json.dumps(blocks)


def test_client_picker_blocks_lists_clients():
    blocks = client_picker_blocks([("habit-pilates", "Habit Pilates"), ("2expect", "2Expect LLC")])
    text = json.dumps(blocks)
    assert "Habit Pilates" in text and "2Expect LLC" in text
    # a static_select with one option per client
    selects = [e for b in blocks if b.get("type") in ("actions", "section")
               for e in (b.get("elements", []) + ([b.get("accessory")] if b.get("accessory") else []))
               if isinstance(e, dict) and e.get("type") == "static_select"]
    assert selects, "expected a static_select"
    assert len(selects[0]["options"]) == 2
    assert selects[0]["action_id"] == "pick_client"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_blocks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.slack_blocks'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/slack_blocks.py`:
```python
from __future__ import annotations

from bookkeeper_agent.connectors.types import BillProposal


def _field(label: str, value: str) -> dict:
    return {"type": "mrkdwn", "text": f"*{label}*\n{value}"}


def proposal_blocks(p: BillProposal) -> list[dict]:
    """Approval card. The target company is shown in bold for visual confirmation;
    Approve/Reject buttons carry stable action_ids (resolved to the pending bill by
    message ts on click)."""
    vendor = p.vendor_name + ("  (NEW)" if p.is_new_vendor else "")
    fields = [
        _field("Company", f"*{p.client_display}*"),
        _field("Vendor", vendor),
        _field("Amount", f"{p.total} {p.currency}"),
        _field("Invoice #", p.doc_number or "—"),
        _field("Date", p.txn_date.isoformat() if p.txn_date else "—"),
        _field("Due", p.due_date.isoformat() if p.due_date else "—"),
    ]
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "New bill to approve"}},
        {"type": "section", "fields": fields},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*Suggested account:* {p.proposed_account_name}  "
                    f"({round(p.confidence * 100)}% confidence)\n_{p.reasoning}_"}},
    ]
    if p.pdf_filename:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f":paperclip: {p.pdf_filename}"}]})
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "action_id": "approve_bill", "style": "primary",
         "text": {"type": "plain_text", "text": "Approve"}},
        {"type": "button", "action_id": "reject_bill", "style": "danger",
         "text": {"type": "plain_text", "text": "Reject"}},
    ]})
    return blocks


def receipt_blocks(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def client_picker_blocks(clients: list[tuple[str, str]]) -> list[dict]:
    """clients: list of (key, display_name). Renders a dropdown to choose the
    target company for a Slack-dropped file when the typed client was unclear."""
    options = [
        {"text": {"type": "plain_text", "text": display}, "value": key}
        for key, display in clients
    ]
    return [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": "Which client is this bill for?"},
        "accessory": {"type": "static_select", "action_id": "pick_client",
                      "placeholder": {"type": "plain_text", "text": "Choose a client"},
                      "options": options},
    }]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_blocks.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/slack_blocks.py tests/test_slack_blocks.py
git -c commit.gpgsign=false commit -m "feat(ws-b4): Slack Block Kit builders (approval card, receipt, client picker)"
```

---

## Task 2: HttpxSlackConnector

**Files:**
- Modify: `pyproject.toml` (pin `httpx`)
- Create: `src/bookkeeper_agent/connectors/slack_http.py`
- Test: `tests/test_slack_http.py`

- [ ] **Step 1: Write the failing test**

`tests/test_slack_http.py`:
```python
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
    assert payload["blocks"]  # Block Kit attached
    assert "Habit Pilates" in payload["text"]  # fallback text


def test_post_receipt_threads():
    api = _StubApi({"ok": True, "channel": "C1", "ts": "2.0"})
    conn = HttpxSlackConnector("xoxb-token", api_post=api)
    conn.post_receipt("C1", "done", thread_ts="1.0")
    _, payload = api.calls[0]
    assert payload["thread_ts"] == "1.0" and payload["text"] == "done"


def test_update_resolved_uses_chat_update():
    api = _StubApi({"ok": True})
    conn = HttpxSlackConnector("xoxb-token", api_post=api)
    conn.update_resolved("C1", "1.0", "Approved by Cole")
    method, payload = api.calls[0]
    assert method == "chat.update"
    assert payload["channel"] == "C1" and payload["ts"] == "1.0"
    assert "Approved by Cole" in __import__("json").dumps(payload)


def test_api_error_raises():
    conn = HttpxSlackConnector("xoxb-token", api_post=_StubApi({"ok": False, "error": "channel_not_found"}))
    with pytest.raises(SlackApiError, match="channel_not_found"):
        conn.post_proposal("C-bad", _proposal())


def test_download_file_uses_injected_getter():
    conn = HttpxSlackConnector("xoxb-token", api_post=_StubApi({"ok": True}),
                               file_get=lambda url: b"%PDF-bytes")
    assert conn.download_file("https://files.slack.com/x") == b"%PDF-bytes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.slack_http'`

- [ ] **Step 3a: Pin httpx in pyproject.toml**

Add `"httpx>=0.27"` to the `dependencies` list in `pyproject.toml` (already installed via anthropic; make it explicit).

- [ ] **Step 3b: Write the implementation**

`src/bookkeeper_agent/connectors/slack_http.py`:
```python
from __future__ import annotations

from typing import Callable

from bookkeeper_agent.connectors.slack_blocks import proposal_blocks, receipt_blocks
from bookkeeper_agent.connectors.types import BillProposal, SlackMessageRef

_SLACK_API = "https://slack.com/api"


class SlackApiError(RuntimeError):
    """Raised when the Slack Web API returns ok=false."""


class HttpxSlackConnector:
    """Real SlackConnector over the Slack Web API. The HTTP poster/getter are
    injectable so this is unit-tested with no network calls."""

    def __init__(
        self,
        bot_token: str,
        *,
        api_post: Callable[[str, dict], dict] | None = None,
        file_get: Callable[[str], bytes] | None = None,
    ):
        self._token = bot_token
        self._api_post = api_post or self._default_post
        self._file_get = file_get or self._default_get

    def _default_post(self, method: str, payload: dict) -> dict:
        import httpx

        resp = httpx.post(
            f"{_SLACK_API}/{method}",
            headers={"Authorization": f"Bearer {self._token}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _default_get(self, url: str) -> bytes:
        import httpx

        resp = httpx.get(url, headers={"Authorization": f"Bearer {self._token}"}, timeout=30)
        resp.raise_for_status()
        return resp.content

    def _call(self, method: str, payload: dict) -> dict:
        resp = self._api_post(method, payload)
        if not resp.get("ok"):
            raise SlackApiError(resp.get("error", "unknown_error"))
        return resp

    def post_proposal(self, channel: str, proposal: BillProposal) -> SlackMessageRef:
        resp = self._call("chat.postMessage", {
            "channel": channel,
            "blocks": proposal_blocks(proposal),
            "text": f"New bill to approve for {proposal.client_display}",
        })
        return SlackMessageRef(channel=resp["channel"], ts=resp["ts"])

    def post_receipt(self, channel: str, text: str, thread_ts: str | None = None) -> SlackMessageRef:
        payload: dict = {"channel": channel, "text": text, "blocks": receipt_blocks(text)}
        if thread_ts is not None:
            payload["thread_ts"] = thread_ts
        resp = self._call("chat.postMessage", payload)
        return SlackMessageRef(channel=resp["channel"], ts=resp["ts"])

    def update_resolved(self, channel: str, ts: str, text: str) -> None:
        """Replace an approval card's buttons with a resolution line (WS-C4)."""
        self._call("chat.update", {
            "channel": channel, "ts": ts, "text": text, "blocks": receipt_blocks(text),
        })

    def download_file(self, url_private: str) -> bytes:
        return self._file_get(url_private)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_http.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/bookkeeper_agent/connectors/slack_http.py tests/test_slack_http.py
git -c commit.gpgsign=false commit -m "feat(ws-b4): HttpxSlackConnector (post/update/download, injected HTTP)"
```

---

## Task 3: Inbound event parsers + client resolver

**Files:**
- Create: `src/bookkeeper_agent/connectors/slack_events.py`
- Test: `tests/test_slack_events.py`

- [ ] **Step 1: Write the failing test**

`tests/test_slack_events.py`:
```python
from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.slack_events import (
    ApprovalAction,
    FileDrop,
    parse_block_action,
    parse_file_share,
    resolve_client,
)


def _client(key, display):
    return ClientConfig(key=key, display_name=display, provider="google",
                        mailbox=f"{key}@unionstreet.io", qbo_realm_id="1", autonomy_level=0)


CLIENTS = {
    "habit-pilates": _client("habit-pilates", "Habit Pilates"),
    "2expect": _client("2expect", "2Expect LLC"),
}


def test_parse_block_action_approve():
    payload = {
        "user": {"id": "U1"},
        "channel": {"id": "C1"},
        "message": {"ts": "1717.0001"},
        "actions": [{"action_id": "approve_bill"}],
    }
    action = parse_block_action(payload)
    assert action == ApprovalAction(action="approve", channel="C1", message_ts="1717.0001", user="U1")


def test_parse_block_action_reject():
    payload = {"user": {"id": "U1"}, "channel": {"id": "C1"}, "message": {"ts": "9.9"},
               "actions": [{"action_id": "reject_bill"}]}
    assert parse_block_action(payload).action == "reject"


def test_parse_block_action_ignores_other_actions():
    payload = {"user": {"id": "U1"}, "channel": {"id": "C1"}, "message": {"ts": "9.9"},
               "actions": [{"action_id": "pick_client"}]}
    assert parse_block_action(payload) is None


def test_parse_file_share():
    event = {
        "channel": "C-DROPS", "user": "U1", "text": "this is for habit pilates",
        "files": [{"id": "F123", "name": "invoice.pdf", "mimetype": "application/pdf",
                   "url_private": "https://files.slack.com/x"}],
    }
    drop = parse_file_share(event)
    assert drop == FileDrop(file_id="F123", filename="invoice.pdf", mime_type="application/pdf",
                            url_private="https://files.slack.com/x", channel="C-DROPS",
                            user="U1", text="this is for habit pilates")


def test_parse_file_share_no_files_returns_none():
    assert parse_file_share({"channel": "C", "text": "hi"}) is None


def test_resolve_client_matches_display_name():
    res = resolve_client("this is for Habit Pilates please", CLIENTS)
    assert res is not None and res.key == "habit-pilates"


def test_resolve_client_matches_key():
    res = resolve_client("client: 2expect", CLIENTS)
    assert res is not None and res.key == "2expect"


def test_resolve_client_no_match_returns_none():
    assert resolve_client("no client named here", CLIENTS) is None


def test_resolve_client_ambiguous_returns_none():
    # mentions both -> not confident, force the dropdown
    assert resolve_client("habit pilates and 2expect", CLIENTS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.slack_events'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/slack_events.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from bookkeeper_agent.clients import ClientConfig

_ACTION_MAP = {"approve_bill": "approve", "reject_bill": "reject"}


@dataclass(frozen=True)
class ApprovalAction:
    action: str  # "approve" | "reject"
    channel: str
    message_ts: str
    user: str


@dataclass(frozen=True)
class FileDrop:
    file_id: str
    filename: str
    mime_type: str
    url_private: str
    channel: str
    user: str
    text: str


def parse_block_action(payload: dict) -> ApprovalAction | None:
    """Parse a Slack block_actions interaction for our approve/reject buttons.
    Returns None for any other action (e.g. the client picker)."""
    actions = payload.get("actions") or []
    if not actions:
        return None
    action_id = actions[0].get("action_id")
    mapped = _ACTION_MAP.get(action_id)
    if mapped is None:
        return None
    return ApprovalAction(
        action=mapped,
        channel=payload.get("channel", {}).get("id", ""),
        message_ts=payload.get("message", {}).get("ts", ""),
        user=payload.get("user", {}).get("id", ""),
    )


def parse_file_share(event: dict) -> FileDrop | None:
    """Parse a message event carrying a file into a FileDrop. Returns None if no file."""
    files = event.get("files") or []
    if not files:
        return None
    f = files[0]
    return FileDrop(
        file_id=f.get("id", ""),
        filename=f.get("name", ""),
        mime_type=f.get("mimetype", ""),
        url_private=f.get("url_private", ""),
        channel=event.get("channel", ""),
        user=event.get("user", ""),
        text=event.get("text", ""),
    )


def resolve_client(text: str, clients: dict[str, ClientConfig]) -> ClientConfig | None:
    """Match a Slack-drop message's text against the client registry. Returns the
    single confident match, or None when there's no match OR more than one (so the
    caller falls back to the dropdown picker). The model never picks the book —
    this is a deterministic match against Cole's configured clients."""
    low = text.lower()
    hits = [
        c for c in clients.values()
        if c.key.lower() in low or c.display_name.lower() in low
    ]
    return hits[0] if len(hits) == 1 else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_slack_events.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/slack_events.py tests/test_slack_events.py
git -c commit.gpgsign=false commit -m "feat(ws-b4): inbound Slack event parsers + client resolver"
```

---

## Task 4: Full-suite green + WS-B4 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — WS-A/B1/C1/C2/C3 + guard (119) plus WS-B4 (4 + 6 + 9 = 19), i.e. ~138 total. All must pass.

- [ ] **Step 2: Confirm the real connector satisfies the Protocol**

Run:
```bash
cd /c/Users/Cole/bookkeeper-agent && PYTHONPATH=src ./.venv/Scripts/python.exe -c "from bookkeeper_agent.connectors.slack import SlackConnector; from bookkeeper_agent.connectors.slack_http import HttpxSlackConnector; print(isinstance(HttpxSlackConnector('xoxb', api_post=lambda m,p: {'ok': True}), SlackConnector))"
```
Expected: `True`

- [ ] **Step 3: Confirm no live call in the suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && grep -rnE 'httpx\.(post|get)\(' tests/ ; echo "exit $?"`
Expected: no matches (tests inject `api_post`/`file_get`; the real httpx path is never exercised in tests).

- [ ] **Step 4: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` (expect clean) and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 5: Tag the workstream**

```bash
git tag ws-b4
```

---

## Self-review against the spec

- **§4 Slack approval card (target company in bold)** → `proposal_blocks` renders the company in bold + Approve/Reject buttons; a test asserts `*Habit Pilates*` and the two `action_id`s. ✓
- **§9b client dropdown fallback** → `client_picker_blocks` renders a `static_select` of configured clients (`action_id="pick_client"`). ✓
- **§9b drop receive + client typed/dropdown** → `parse_file_share` extracts the dropped file + message text; `resolve_client` deterministically matches the typed client (single confident match) or returns None to force the dropdown — the model never picks the book. ✓
- **WS-B1 `SlackConnector` Protocol satisfied by the real impl** → `HttpxSlackConnector` implements `post_proposal`/`post_receipt`; Task 4 step 2 asserts `isinstance(..., SlackConnector)`. ✓
- **Button click → which pending bill** → buttons carry stable `action_id`s; `parse_block_action` returns the `message_ts`, which WS-C4 maps to the `PendingBill.slack_ts` stored in WS-C3 (no `post_proposal` contract change). ✓
- **card update after decision** → `update_resolved` (chat.update) swaps the buttons for a resolution line — WS-C4 calls it on approve/reject. ✓
- **offline-testable (no live calls)** → HTTP poster/getter injected; Task 4 step 3 confirms tests never call real httpx. ✓

**Deferred (correctly out of scope here):** the live **Socket Mode websocket runner** (connects with the app-level `xapp-` token, streams `block_actions` + file events to these parsers) — thin glue, verified live; the **Slack-drop adapter** (FileDrop + resolved client → `BillIntake(skip_classification=True)` → `BillsPipeline.process`) and the **WS-C4 write-gate** (ApprovalAction → look up PendingBill by `slack_ts` → QBO write → `update_resolved`); the real QBO connector (WS-B3).

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** `HttpxSlackConnector.post_proposal/post_receipt` match the `SlackConnector` Protocol and return `SlackMessageRef`; `proposal_blocks(BillProposal) -> list[dict]`; `parse_block_action(dict) -> ApprovalAction | None`; `parse_file_share(dict) -> FileDrop | None`; `resolve_client(str, dict[str, ClientConfig]) -> ClientConfig | None`. Button `action_id`s (`approve_bill`/`reject_bill`/`pick_client`) are consistent across `slack_blocks` and `slack_events`.
```
