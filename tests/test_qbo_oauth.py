from urllib.parse import parse_qs, urlparse

import pytest

from bookkeeper_agent.connectors.qbo_oauth import QboOAuth, QboOAuthConfig, QboTokens

CFG = QboOAuthConfig(
    client_id="ABC", client_secret="secret",
    redirect_uri="http://localhost:8000/qbo/callback", environment="sandbox",
)


def test_authorize_url_has_required_params():
    url = QboOAuth(CFG).authorize_url(state="xyz")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["ABC"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == ["com.intuit.quickbooks.accounting"]
    assert q["redirect_uri"] == ["http://localhost:8000/qbo/callback"]
    assert q["state"] == ["xyz"]
    assert url.startswith("https://appcenter.intuit.com/connect/oauth2?")


class _StubHttp:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def __call__(self, url, *, data, auth, headers):
        self.calls.append({"url": url, "data": data, "auth": auth, "headers": headers})
        return self._response


def test_exchange_code_returns_tokens_and_uses_basic_auth():
    http = _StubHttp({"access_token": "AT", "refresh_token": "RT",
                      "expires_in": 3600, "x_refresh_token_expires_in": 8640000})
    tokens = QboOAuth(CFG, http_post=http).exchange_code(code="the-code")
    assert tokens == QboTokens(access_token="AT", refresh_token="RT", expires_in=3600)
    call = http.calls[0]
    assert call["url"] == "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    assert call["auth"] == ("ABC", "secret")
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "the-code"
    assert call["data"]["redirect_uri"] == "http://localhost:8000/qbo/callback"


def test_refresh_uses_refresh_grant():
    http = _StubHttp({"access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600})
    tokens = QboOAuth(CFG, http_post=http).refresh("old-refresh")
    assert tokens.access_token == "AT2" and tokens.refresh_token == "RT2"
    assert http.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}


def test_token_endpoint_error_raises():
    http = _StubHttp({"error": "invalid_grant"})
    with pytest.raises(QboOAuth.OAuthError, match="invalid_grant"):
        QboOAuth(CFG, http_post=http).refresh("bad")
