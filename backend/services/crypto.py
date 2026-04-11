"""
Fernet-based symmetric encryption for the credential vault.

The encryption key is derived from the application SECRET_KEY at call time
so that the key is never held in module-level state across hot-reloads.

Key derivation: SHA-256(SECRET_KEY) → URL-safe base64 (32 bytes → 44-char Fernet key)
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    """Return a Fernet instance derived from the application SECRET_KEY."""
    from ..config import settings  # late import — matches existing pattern in codebase
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* and return a Fernet token string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet token string and return the plaintext.

    Raises ValueError if the token is invalid (e.g. SECRET_KEY was rotated).
    """
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Cannot decrypt credential — the SECRET_KEY may have changed. "
            "Re-enter the credential secret."
        ) from exc
