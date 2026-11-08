import pytest

from app.security import (create_access_token, decode_access_token, decrypt_secret, encrypt_secret, hash_password,
                          validate_password_strength, verify_password)


def test_password_hashing():
    h = hash_password("Correct-horse-1")
    assert h != "Correct-horse-1"
    assert verify_password("Correct-horse-1", h)
    assert not verify_password("wrong", h)


@pytest.mark.parametrize("pw", ["short1", "onlyletterslong", "1234567890123"])
def test_weak_passwords(pw):
    with pytest.raises(ValueError):
        validate_password_strength(pw)


def test_secret_encryption_roundtrip():
    enc = encrypt_secret("broker-pass")
    assert enc and "broker-pass" not in enc
    assert decrypt_secret(enc) == "broker-pass"
    assert encrypt_secret("") is None and decrypt_secret(None) is None


def test_jwt_roundtrip_and_tamper():
    t = create_access_token(5, "trader", 3)
    p = decode_access_token(t)
    assert p["sub"] == "5" and p["role"] == "trader" and p["tv"] == 3
    with pytest.raises(Exception):
        decode_access_token(t[:-2] + ("A" if t[-1] != "A" else "B") + t[-1])
