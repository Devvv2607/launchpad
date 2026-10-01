from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    # Null for users authenticated by an external provider (Supabase).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    external_auth_id: Mapped[str | None] = mapped_column(String(128), unique=True)
