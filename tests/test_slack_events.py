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
    assert resolve_client("habit pilates and 2expect", CLIENTS) is None


def test_parse_client_pick_extracts_file_and_client():
    from bookkeeper_agent.connectors.slack_events import ClientPick, parse_client_pick
    payload = {
        "user": {"id": "U1"}, "channel": {"id": "C-DROPS"}, "message": {"ts": "1.0"},
        "actions": [{"action_id": "pick_client", "block_id": "drop:F1",
                     "selected_option": {"value": "habit-pilates"}}],
    }
    pick = parse_client_pick(payload)
    assert pick == ClientPick(file_id="F1", client_key="habit-pilates",
                              channel="C-DROPS", message_ts="1.0", user="U1")


def test_parse_client_pick_ignores_other_actions():
    from bookkeeper_agent.connectors.slack_events import parse_client_pick
    assert parse_client_pick({"actions": [{"action_id": "approve_bill"}]}) is None
