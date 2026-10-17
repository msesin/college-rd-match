"""Encryption for student identity fields (names, emails).

Uses Fernet (AES with an integrity check) from the `cryptography` package. The key lives
only in .env as STUDENT_DATA_KEY. Without the key, the stored values are unreadable, so
a copy of the database or a backup does not reveal names. Lose the key and the names are
gone for good: keep a copy of it in a password manager, separate from the backups.

Generate a key:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class MissingKey(Exception):
    pass


def _fernet():
    key = os.environ.get("STUDENT_DATA_KEY")
    if not key:
        raise MissingKey("STUDENT_DATA_KEY is not set in .env")
    return Fernet(key.encode())


def encrypt(text):
    if not text:
        return ""
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token):
    """Plain text, or a placeholder when the key is missing or wrong (never raises in views)."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (MissingKey, InvalidToken):
        return "[encrypted]"


def normalise_email(email):
    return (email or "").strip().lower()


def email_fingerprint(email):
    """Keyed hash of an email, so a student can be found at sign-up without decrypting every record.

    Without STUDENT_DATA_KEY the fingerprint cannot be recomputed or reversed.
    """
    import hashlib
    import hmac

    key = os.environ.get("STUDENT_DATA_KEY")
    if not key:
        raise MissingKey("STUDENT_DATA_KEY is not set in .env")
    return hmac.new(key.encode(), normalise_email(email).encode(), hashlib.sha256).hexdigest()
