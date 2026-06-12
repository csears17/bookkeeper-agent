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
