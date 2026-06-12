import pytest
from cryptography.fernet import Fernet

from bookkeeper_agent.connectors.qbo_oauth import QboTokens
from bookkeeper_agent.connectors.qbo_tokens import QboTokenManager
from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.security import TokenCipher


def _store(engine):
    return TokenStore(engine, TokenCipher([Fernet.generate_key().decode()]))


class _FakeOAuth:
    def __init__(self):
        self.refreshes: list[str] = []
        self._n = 0

    def refresh(self, refresh_token):
        self.refreshes.append(refresh_token)
        self._n += 1
        return QboTokens(access_token=f"AT{self._n}", refresh_token=f"RT{self._n}", expires_in=3600)


def test_save_connection_persists_encrypted_refresh(engine):
    store = _store(engine)
    mgr = QboTokenManager(store, _FakeOAuth())
    mgr.save_connection("111", "RT0")
    assert store.get_secret("qbo", "111") == "RT0"


def test_access_token_refreshes_and_persists_rotated_refresh(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "RT0")
    oauth = _FakeOAuth()
    mgr = QboTokenManager(store, oauth)

    at = mgr.access_token("111")
    assert at == "AT1"
    assert oauth.refreshes == ["RT0"]
    assert store.get_secret("qbo", "111") == "RT1"


def test_access_token_is_cached_until_expiry(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "RT0")
    oauth = _FakeOAuth()
    mgr = QboTokenManager(store, oauth)

    first = mgr.access_token("111")
    second = mgr.access_token("111")
    assert first == second == "AT1"
    assert oauth.refreshes == ["RT0"]


def test_unknown_realm_raises(engine):
    mgr = QboTokenManager(_store(engine), _FakeOAuth())
    with pytest.raises(KeyError):
        mgr.access_token("999")
