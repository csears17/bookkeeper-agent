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
