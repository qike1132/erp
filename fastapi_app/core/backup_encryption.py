"""Backup file encryption using AES-256-GCM with PBKDF2 key derivation."""

import hashlib
import json
import os
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BackupFileError(Exception):
    """Raised when backup file operations fail (e.g. wrong password, corrupt data)."""

    def __init__(self, message: str, code: str = "BACKUP_FILE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SALT_LEN = 16          # 128-bit salt
_NONCE_LEN = 12         # 96-bit nonce (recommended for GCM)
_TAG_LEN = 16           # 128-bit authentication tag
_KDF_ITERATIONS = 600_000
_KEY_LEN = 32           # 256-bit key


def _derive_key(password: bytearray, salt: bytes) -> bytearray:
    """Derive a 256-bit key from *password* and *salt* using PBKDF2-HMAC-SHA256.

    Returns a ``bytearray`` so the caller can zero it out after use.
    """
    dk = hashlib.pbkdf2_hmac("sha256", bytes(password), salt, _KDF_ITERATIONS, dklen=_KEY_LEN)
    return bytearray(dk)


def _zero(ba: bytearray) -> None:
    """Overwrite a bytearray with zeros to reduce the window where secrets
    reside in memory."""
    for i in range(len(ba)):
        ba[i] = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_backup(
    zip_bytes: bytes,
    password: str | bytearray,
) -> tuple[bytes, dict]:
    """Encrypt *zip_bytes* with AES-256-GCM.

    Returns ``(encrypted_bytes, meta_dict)``.

    File layout::

        salt  (16 B) | nonce (12 B) | ciphertext (variable) | auth_tag (16 B)

    The auth tag is appended by ``AESGCM.encrypt`` as the last 16 bytes of
    the ciphertext output.
    """
    # --- normalise password to bytearray so we can zero it later -----------
    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode("utf-8"))

    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)

    key = _derive_key(pw_bytes, salt)
    _zero(pw_bytes)  # clear password from memory ASAP

    aesgcm = AESGCM(bytes(key))
    _zero(key)  # clear derived key — AESGCM keeps its own internal copy

    # AESGCM.encrypt returns ciphertext || auth_tag (16 bytes at the end)
    ct_with_tag = aesgcm.encrypt(nonce, zip_bytes, None)

    encrypted_bytes = salt + nonce + ct_with_tag

    backup_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    meta_dict = {
        "backup_id": backup_id,
        "created_at": datetime.now(UTC).isoformat(),
        "type": "encrypted",
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": {
            "name": "PBKDF2-HMAC-SHA256",
            "iterations": _KDF_ITERATIONS,
            "salt_len": _SALT_LEN,
        },
    }

    return encrypted_bytes, meta_dict


def decrypt_backup(
    encrypted_bytes: bytes,
    password: str | bytearray,
) -> bytes:
    """Decrypt data produced by :func:`encrypt_backup`.

    Raises :class:`BackupFileError` if the password is wrong or the data is
    corrupt (authentication tag verification failure).
    """
    min_len = _SALT_LEN + _NONCE_LEN + _TAG_LEN
    if len(encrypted_bytes) < min_len:
        raise BackupFileError(
            f"Encrypted data too short ({len(encrypted_bytes)} B, minimum {min_len} B)",
            code="BACKUP_DECRYPT_SHORT",
        )

    salt = encrypted_bytes[:_SALT_LEN]
    nonce = encrypted_bytes[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ct_with_tag = encrypted_bytes[_SALT_LEN + _NONCE_LEN :]

    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode("utf-8"))

    key = _derive_key(pw_bytes, salt)
    _zero(pw_bytes)

    aesgcm = AESGCM(bytes(key))
    _zero(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ct_with_tag, None)
    except (InvalidTag, ValueError) as exc:
        raise BackupFileError(
            "Decryption failed — incorrect password or corrupt data",
            code="BACKUP_DECRYPT_AUTH",
        ) from exc

    return plaintext


def create_meta_file(meta_dict: dict) -> bytes:
    """Serialise *meta_dict* as pretty-printed UTF-8 JSON bytes suitable for
    writing to a ``.meta`` sidecar file."""
    return json.dumps(meta_dict, indent=2, ensure_ascii=False).encode("utf-8")
