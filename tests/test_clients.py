import pytest

from bookkeeper_agent.clients import ClientConfigError, load_clients

VALID = """
[[client]]
key = "habit-pilates"
display_name = "Habit Pilates"
provider = "google"
mailbox = "habit@unionstreet.io"
qbo_realm_id = "111"
autonomy_level = 0

[[client]]
key = "2expect"
display_name = "2Expect LLC"
provider = "microsoft"
mailbox = "2expect@unionstreet.io"
qbo_realm_id = "222"
"""


def _write(tmp_path, text):
    p = tmp_path / "clients.toml"
    p.write_text(text)
    return p


def test_loads_valid_clients(tmp_path):
    clients = load_clients(_write(tmp_path, VALID))
    assert set(clients) == {"habit-pilates", "2expect"}
    assert clients["habit-pilates"].mailbox == "habit@unionstreet.io"
    assert clients["2expect"].autonomy_level == 0  # default applied


def test_company_for_mailbox_lookup(tmp_path):
    clients = load_clients(_write(tmp_path, VALID))
    by_mailbox = {c.mailbox: c for c in clients.values()}
    assert by_mailbox["habit@unionstreet.io"].qbo_realm_id == "111"


def test_rejects_duplicate_mailbox(tmp_path):
    dupe = VALID + """
[[client]]
key = "third"
display_name = "Third"
provider = "google"
mailbox = "habit@unionstreet.io"
qbo_realm_id = "333"
"""
    with pytest.raises(ClientConfigError, match="duplicate mailbox"):
        load_clients(_write(tmp_path, dupe))


def test_rejects_bad_provider(tmp_path):
    bad = """
[[client]]
key = "x"
display_name = "X"
provider = "yahoo"
mailbox = "x@unionstreet.io"
qbo_realm_id = "1"
"""
    with pytest.raises(ClientConfigError, match="provider"):
        load_clients(_write(tmp_path, bad))


def test_rejects_bad_autonomy_level(tmp_path):
    bad = """
[[client]]
key = "x"
display_name = "X"
provider = "google"
mailbox = "x@unionstreet.io"
qbo_realm_id = "1"
autonomy_level = 5
"""
    with pytest.raises(ClientConfigError, match="autonomy_level"):
        load_clients(_write(tmp_path, bad))
