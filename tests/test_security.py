import pytest
from cryptography.fernet import Fernet

from bookkeeper_agent.security import TokenCipher


def test_round_trip():
    cipher = TokenCipher([Fernet.generate_key().decode()])
    token = cipher.encrypt("super-secret-refresh-token")
    assert token != b"super-secret-refresh-token"
    assert cipher.decrypt(token) == "super-secret-refresh-token"


def test_multifernet_decrypts_with_old_key_after_rotation():
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = TokenCipher([old_key])
    token = old_cipher.encrypt("value")

    # New cipher lists new key first, old key second: must still decrypt old token.
    rotated = TokenCipher([new_key, old_key])
    assert rotated.decrypt(token) == "value"


def test_requires_at_least_one_key():
    with pytest.raises(ValueError):
        TokenCipher([])


def test_repr_hides_keys():
    cipher = TokenCipher([Fernet.generate_key().decode()])
    assert "key" not in repr(cipher).lower() or "hidden" in repr(cipher).lower()
    assert "<hidden>" in repr(cipher)
