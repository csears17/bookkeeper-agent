import pytest
from cryptography.fernet import Fernet

from bookkeeper_agent.connectors.qbo_oauth import QboTokens
from bookkeeper_agent.connectors.qbo_tokens import QboTokenManager
from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.qbo_connect import _base_url, handle_callback
from bookkeeper_agent.security import TokenCipher


def test_base_url_sandbox_vs_production():
    assert _base_url("sandbox") == "https://sandbox-quickbooks.api.intuit.com"
    assert _base_url("production") == "https://quickbooks.api.intuit.com"
    assert _base_url("anything-else") == "https://sandbox-quickbooks.api.intuit.com"  # safe default


class _StubOAuth:
    def __init__(self):
        self.codes = []

    def exchange_code(self, code):
        self.codes.append(code)
        return QboTokens(access_token="AT", refresh_token="RT-stored", expires_in=3600)


def _manager(engine):
    store = TokenStore(engine, TokenCipher([Fernet.generate_key().decode()]))
    return store, QboTokenManager(store, _StubOAuth())


def test_handle_callback_exchanges_and_persists_refresh(engine):
    store, mgr = _manager(engine)
    oauth = _StubOAuth()
    params = {"state": ["xyz"], "code": ["the-code"], "realmId": ["123146"]}
    realm, msg = handle_callback(params, "xyz", oauth, mgr)
    assert realm == "123146"
    assert oauth.codes == ["the-code"]
    # only the encrypted refresh token is stored, keyed by realm
    assert store.get_secret("qbo", "123146") == "RT-stored"


def test_handle_callback_rejects_state_mismatch(engine):
    _store, mgr = _manager(engine)
    params = {"state": ["evil"], "code": ["c"], "realmId": ["1"]}
    with pytest.raises(ValueError, match="state mismatch"):
        handle_callback(params, "expected", _StubOAuth(), mgr)


def test_handle_callback_requires_code_and_realm(engine):
    _store, mgr = _manager(engine)
    with pytest.raises(ValueError, match="missing code"):
        handle_callback({"state": ["s"]}, "s", _StubOAuth(), mgr)
