from __future__ import annotations

from cryptography.fernet import Fernet, MultiFernet


class TokenCipher:
    """Fernet/MultiFernet envelope encryption for secrets at rest.

    Pass one or more Fernet keys. The first key encrypts; every key can
    decrypt, which enables key rotation (add the new key first, keep the
    old one until all tokens are re-encrypted via rotate()).
    """

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("TokenCipher requires at least one Fernet key")
        self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()

    def rotate(self, token: bytes) -> bytes:
        """Re-encrypt an existing token under the current primary key."""
        return self._fernet.rotate(token)

    def __repr__(self) -> str:
        return "TokenCipher(keys=<hidden>)"
