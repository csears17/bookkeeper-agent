from __future__ import annotations

from typing import Callable

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.slack_events import FileDrop
from bookkeeper_agent.connectors.types import Attachment
from bookkeeper_agent.pipeline.intake import BillIntake


def build_drop_intake(
    drop: FileDrop, client: ClientConfig, download: Callable[[str], bytes]
) -> BillIntake:
    """Turn a Slack file drop + the (already-resolved) target client into a
    normalized BillIntake. Slack drops are explicit bills, so skip_classification
    is True (the pipeline still extracts fields). The company binding comes from
    the validated client config — never the model."""
    content = download(drop.url_private)
    return BillIntake(
        source="slack-drop",
        source_id=drop.file_id,
        source_ref=drop.channel,
        client_key=client.key,
        client_display=client.display_name,
        company_realm=client.qbo_realm_id,
        sender=drop.user,
        subject=drop.filename,
        body_text=drop.text,
        attachments=(Attachment(drop.filename, drop.mime_type, content),),
        skip_classification=True,
    )
