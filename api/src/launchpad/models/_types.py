from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB


def str_enum(enum_cls: type[StrEnum]) -> SAEnum:
    """Store enums as varchar (easy to evolve without ALTER TYPE), validated in Python."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


JSON: Any = JSONB

# Embedding dimension is part of the schema. Both supported embedding providers
# (Gemini, OpenAI) can emit 768-d vectors; changing this requires a migration.
EMBEDDING_DIM = 768
