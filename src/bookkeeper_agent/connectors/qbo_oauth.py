from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

_AUTHORIZE = "https://appcenter.intuit.com/connect/oauth2"
_TOKEN = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_SCOPE = "com.intuit.quickbooks.accounting"


@dataclass(frozen=True)
class QboOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    environment: str = "sandbox"  # "sandbox" | "production"


@dataclass(frozen=True)
class QboTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class QboOAuth:
    """Builds the Connect-to-QuickBooks login URL and exchanges/refreshes tokens.
    The token-endpoint HTTP poster is injected for offline testing."""

    class OAuthError(RuntimeError):
        pass

    def __init__(self, config: QboOAuthConfig, *, http_post: Callable[..., dict] | None = None):
        self._cfg = config
        self._http_post = http_post or self._default_post

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._cfg.client_id,
            "response_type": "code",
            "scope": _SCOPE,
            "redirect_uri": self._cfg.redirect_uri,
            "state": state,
        }
        return f"{_AUTHORIZE}?{urlencode(params)}"

    def exchange_code(self, code: str) -> QboTokens:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
        })

    def refresh(self, refresh_token: str) -> QboTokens:
        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def _token_request(self, data: dict) -> QboTokens:
        resp = self._http_post(
            _TOKEN,
            data=data,
            auth=(self._cfg.client_id, self._cfg.client_secret),
            headers={"Accept": "application/json"},
        )
        if "access_token" not in resp:
            raise self.OAuthError(resp.get("error", "unknown_error"))
        return QboTokens(
            access_token=resp["access_token"],
            refresh_token=resp["refresh_token"],
            expires_in=int(resp.get("expires_in", 3600)),
        )

    def _default_post(self, url, *, data, auth, headers) -> dict:
        import httpx

        resp = httpx.post(url, data=data, auth=auth, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
