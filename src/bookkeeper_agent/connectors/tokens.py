from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import OAuthToken
from bookkeeper_agent.security import TokenCipher


class TokenStore:
    """Typed access to encrypted service secrets in the OAuthToken table.

    Real connectors (WS-B2/3/4) read/write their refresh tokens and keys
    exclusively through here, so encryption happens in exactly one place.
    """

    def __init__(self, engine: Engine, cipher: TokenCipher):
        self._engine = engine
        self._cipher = cipher

    def get_secret(self, service: str, ref: str = "default") -> str | None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._cipher.decrypt(row.secret_ciphertext)

    def put_secret(self, service: str, ref: str, plaintext: str) -> None:
        ciphertext = self._cipher.encrypt(plaintext)
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is None:
                s.add(OAuthToken(service=service, ref=ref, secret_ciphertext=ciphertext))
            else:
                row.secret_ciphertext = ciphertext

    def delete_secret(self, service: str, ref: str = "default") -> None:
        with session_scope(self._engine) as s:
            row = s.execute(
                select(OAuthToken).where(OAuthToken.service == service, OAuthToken.ref == ref)
            ).scalar_one_or_none()
            if row is not None:
                s.delete(row)
