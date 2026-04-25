import hashlib

from fastapi_app.core.security import hash_password, needs_migration, verify_password


def _legacy_pbkdf2_hash(password: str, salt: str = "testsalt", digest: str = "sha256", iterations: int = 1000000) -> str:
    derived = hashlib.pbkdf2_hmac(
        digest,
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2:{digest}:{iterations}${salt}${derived}"


def _legacy_scrypt_hash(password: str, salt: str = "testsalt", n: int = 32768, r: int = 8, p: int = 1) -> str:
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=n,
        r=r,
        p=p,
        maxmem=max(0, 128 * n * r * p * 2),
    ).hex()
    return f"scrypt:{n}:{r}:{p}${salt}${derived}"


def test_verify_password_supports_argon2():
    password_hash = hash_password("secret123")

    assert verify_password("secret123", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert needs_migration(password_hash) is False


def test_verify_password_supports_legacy_pbkdf2():
    password_hash = _legacy_pbkdf2_hash("legacy-secret")

    assert verify_password("legacy-secret", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert needs_migration(password_hash) is True


def test_verify_password_supports_legacy_scrypt():
    password_hash = _legacy_scrypt_hash("legacy-secret")

    assert verify_password("legacy-secret", password_hash) is True
    assert verify_password("wrong", password_hash) is False
    assert needs_migration(password_hash) is True


def test_verify_password_returns_false_for_unknown_hash():
    assert verify_password("secret123", "sha1$legacy$hash") is False
    assert needs_migration("sha1$legacy$hash") is True
