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

    def update_resolved(self, channel: str, ts: str, text: str) -> None:
        """Replace a posted card's buttons with a resolution line (after a decision)."""
        ...


class FakeSlackConnector:
    """In-memory SlackConnector for tests and WS-C pipeline development."""

    def __init__(self) -> None:
        self.posted: list[tuple[str, BillProposal]] = []
        self.receipts: list[tuple[str, str, str | None]] = []
        self.updates: list[tuple[str, str, str]] = []
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

    def update_resolved(self, channel: str, ts: str, text: str) -> None:
        self.updates.append((channel, ts, text))
