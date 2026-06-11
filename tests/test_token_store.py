from cryptography.fernet import Fernet

from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import OAuthToken
from bookkeeper_agent.security import TokenCipher


def _store(engine):
    return TokenStore(engine, TokenCipher([Fernet.generate_key().decode()]))


def test_put_then_get_round_trip(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "refresh-token-abc")
    assert store.get_secret("qbo", "111") == "refresh-token-abc"


def test_get_missing_returns_none(engine):
    store = _store(engine)
    assert store.get_secret("qbo", "does-not-exist") is None


def test_put_overwrites_existing(engine):
    store = _store(engine)
    store.put_secret("slack", "default", "xoxb-old")
    store.put_secret("slack", "default", "xoxb-new")
    assert store.get_secret("slack", "default") == "xoxb-new"
    # still only one row for that (service, ref)
    with session_scope(engine) as s:
        rows = s.query(OAuthToken).filter_by(service="slack", ref="default").all()
        assert len(rows) == 1


def test_secret_is_encrypted_at_rest(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "super-secret")
    with session_scope(engine) as s:
        row = s.query(OAuthToken).filter_by(service="qbo", ref="111").one()
        assert b"super-secret" not in row.secret_ciphertext


def test_delete(engine):
    store = _store(engine)
    store.put_secret("google", "default", "json-key-blob")
    store.delete_secret("google", "default")
    assert store.get_secret("google", "default") is None
