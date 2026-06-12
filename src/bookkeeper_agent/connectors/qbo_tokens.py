from __future__ import annotations

import time
from dataclasses import dataclass

from bookkeeper_agent.connectors.tokens import TokenStore

_SERVICE = "qbo"
_EXPIRY_SKEW_SECONDS = 120  # refresh a little early


@dataclass
class _CachedAccess:
    token: str
    expires_at: float


class QboTokenManager:
    """Turns a realm into a current access token. The encrypted refresh token is
    the only persisted secret (via TokenStore); access tokens are short-lived and
    cached in memory. A refresh rotates the refresh token, which is re-persisted."""

    def __init__(self, token_store: TokenStore, oauth, *, now=time.monotonic):
        self._store = token_store
        self._oauth = oauth
        self._now = now
        self._cache: dict[str, _CachedAccess] = {}

    def save_connection(self, realm: str, refresh_token: str) -> None:
        """Called by the Connect flow after a successful authorize."""
        self._store.put_secret(_SERVICE, realm, refresh_token)

    def access_token(self, realm: str) -> str:
        cached = self._cache.get(realm)
        if cached is not None and cached.expires_at - _EXPIRY_SKEW_SECONDS > self._now():
            return cached.token

        refresh_token = self._store.get_secret(_SERVICE, realm)
        if refresh_token is None:
            raise KeyError(f"no QBO connection stored for realm {realm!r} — run Connect first")

        tokens = self._oauth.refresh(refresh_token)
        # Persist the rotated refresh token so the next refresh works.
        self._store.put_secret(_SERVICE, realm, tokens.refresh_token)
        self._cache[realm] = _CachedAccess(
            token=tokens.access_token, expires_at=self._now() + tokens.expires_in
        )
        return tokens.access_token
