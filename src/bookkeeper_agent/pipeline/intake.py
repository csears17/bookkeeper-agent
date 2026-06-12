from __future__ import annotations

from dataclasses import dataclass

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.types import Attachment, EmailMessage


@dataclass(frozen=True)
class BillIntake:
    """A normalized unit of work for the propose pipeline, independent of source.

    source: "email" | "slack-drop"
    source_id: unique id within the source (email message id; Slack file id) — idempotency key.
    source_ref: human-meaningful origin (mailbox address; Slack channel/user).
    company_realm: the FIXED target QBO company. For email it comes from the inbox map;
                   for a Slack drop it comes from Cole's explicit, validated choice.
    skip_classification: True for explicit sources (Slack drop) — skip pre-screen and the
                   is-this-a-bill gate; still run extraction.
    """

    source: str
    source_id: str
    source_ref: str
    client_key: str
    client_display: str
    company_realm: str
    sender: str
    subject: str
    body_text: str
    attachments: tuple[Attachment, ...]
    skip_classification: bool


def intake_from_email(email: EmailMessage, client: ClientConfig) -> BillIntake:
    """Build an intake from an email read from a client's bound mailbox.
    The company binding comes from the fixed client config, never the model."""
    return BillIntake(
        source="email",
        source_id=email.id,
        source_ref=email.mailbox,
        client_key=client.key,
        client_display=client.display_name,
        company_realm=client.qbo_realm_id,
        sender=email.sender,
        subject=email.subject,
        body_text=email.snippet,
        attachments=email.attachments,
        skip_classification=False,
    )
