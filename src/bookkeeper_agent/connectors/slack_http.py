from __future__ import annotations

from typing import Callable

from bookkeeper_agent.connectors.slack_blocks import (
    client_picker_blocks,
    proposal_blocks,
    receipt_blocks,
)
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

    def post_picker(self, channel: str, file_id: str,
                    clients: list[tuple[str, str]]) -> SlackMessageRef:
        """Ask which client a dropped file belongs to (the file id rides in the
        picker block_id so the selection maps back to the file)."""
        resp = self._call("chat.postMessage", {
            "channel": channel,
            "blocks": client_picker_blocks(clients, file_id),
            "text": "Which client is this bill for?",
        })
        return SlackMessageRef(channel=resp["channel"], ts=resp["ts"])

    def file_info(self, file_id: str) -> dict:
        """Return the Slack file object (name, mimetype, url_private) by id."""
        resp = self._call("files.info", {"file": file_id})
        return resp.get("file", {})

    def download_file(self, url_private: str) -> bytes:
        return self._file_get(url_private)
