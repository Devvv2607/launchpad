"""Encryption at rest for third-party credentials (OAuth tokens).

Uses MultiFernet so keys can be rotated: TOKEN_ENCRYPTION_KEYS="new_key,old_key".
The first key encrypts; all keys can decrypt.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from launchpad.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    raw = get_settings().token_encryption_keys.get_secret_value()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise EncryptionNotConfigured(
            "TOKEN_ENCRYPTION_KEYS is not set. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


class EncryptedText(TypeDecorator[str]):
    """Transparently encrypts on write and decrypts on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else decrypt(str(value))
