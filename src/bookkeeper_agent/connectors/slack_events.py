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


@dataclass(frozen=True)
class ClientPick:
    file_id: str
    client_key: str
    channel: str
    message_ts: str
    user: str


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


def parse_client_pick(payload: dict) -> ClientPick | None:
    """Parse a `pick_client` dropdown selection. The dropped file's id is encoded
    in the block_id as ``drop:<file_id>``. Returns None for any other action."""
    actions = payload.get("actions") or []
    if not actions or actions[0].get("action_id") != "pick_client":
        return None
    action = actions[0]
    block_id = action.get("block_id", "")
    file_id = block_id[len("drop:"):] if block_id.startswith("drop:") else ""
    client_key = (action.get("selected_option") or {}).get("value", "")
    if not file_id or not client_key:
        return None
    return ClientPick(
        file_id=file_id,
        client_key=client_key,
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
