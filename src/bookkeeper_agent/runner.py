"""Event routing + the live Socket Mode loop.

The `on_*` dispatch functions are pure and unit-tested with Fakes. `run()` is the
thin live glue: it connects to Slack via Socket Mode (app-level token), acks each
event within Slack's 3s window, then routes it under a lock so approval writes are
serialized (defense-in-depth alongside the atomic claim in the write-gate).
"""
from __future__ import annotations

import threading

from bookkeeper_agent.connectors.slack_events import (
    FileDrop,
    parse_block_action,
    parse_client_pick,
    parse_file_share,
    resolve_client,
)
from bookkeeper_agent.pipeline.slack_drop import build_drop_intake


def on_block_action(payload, gate):
    """Approve/Reject button click -> write-gate. Returns the WriteResult, or None
    if the action isn't an approve/reject (e.g. the client picker)."""
    action = parse_block_action(payload)
    if action is None:
        return None
    return gate.handle(action)


def on_file_drop(event, clients, slack, pipeline) -> str:
    """A file dropped in Slack -> propose a bill if the client is clear, else post
    the client picker. Returns an outcome label."""
    drop = parse_file_share(event)
    if drop is None:
        return "no_file"
    client = resolve_client(drop.text, clients)
    if client is None:
        slack.post_picker(drop.channel, drop.file_id,
                          [(c.key, c.display_name) for c in clients.values()])
        return "picker_posted"
    pipeline.process(build_drop_intake(drop, client, slack.download_file))
    return "processed"


def on_client_pick(payload, clients, slack, pipeline) -> str:
    """The user picked the client for a previously-dropped file -> propose the bill."""
    pick = parse_client_pick(payload)
    if pick is None:
        return "ignored"
    client = clients.get(pick.client_key)
    if client is None:
        return "unknown_client"
    info = slack.file_info(pick.file_id)
    drop = FileDrop(
        file_id=pick.file_id, filename=info.get("name", ""),
        mime_type=info.get("mimetype", ""), url_private=info.get("url_private", ""),
        channel=pick.channel, user=pick.user, text="",
    )
    pipeline.process(build_drop_intake(drop, client, slack.download_file))
    return "processed"


def run(app) -> None:  # pragma: no cover - live Socket Mode glue
    """Connect to Slack Socket Mode and route events. Blocks forever."""
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web import WebClient

    lock = threading.Lock()
    sm = SocketModeClient(app_token=app.slack_app_token,
                          web_client=WebClient(token=app.slack_bot_token))

    def _handle(client: SocketModeClient, req: SocketModeRequest):
        # Ack first (Slack requires < 3s), then process serially under the lock.
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            with lock:
                if req.type == "interactive":
                    payload = req.payload
                    if on_block_action(payload, app.gate) is not None:
                        return
                    on_client_pick(payload, app.clients, app.slack, app.pipeline)
                elif req.type == "events_api":
                    event = (req.payload or {}).get("event", {})
                    if event.get("type") == "message" and event.get("files"):
                        on_file_drop(event, app.clients, app.slack, app.pipeline)
        except Exception as exc:  # noqa: BLE001 - never let one event kill the loop
            print(f"[runner] error handling {req.type}: {exc}")

    sm.socket_mode_request_listeners.append(_handle)
    sm.connect()
    print("[runner] connected to Slack Socket Mode. Watching for file drops + approvals…")
    threading.Event().wait()
