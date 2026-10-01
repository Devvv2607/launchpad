from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import DocumentStatus
from launchpad.models._types import EMBEDDING_DIM, JSON, str_enum

if TYPE_CHECKING:
    from launchpad.models.workspace import Workspace


class BrandKit(UUIDPk, Timestamps, Base):
    __tablename__ = "brand_kits"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL", use_alter=True)
    )
    primary_color: Mapped[str | None] = mapped_column(String(9))
    secondary_color: Mapped[str | None] = mapped_column(String(9))
    accent_colors: Mapped[list[str]] = mapped_column(JSON, default=list)
    heading_font: Mapped[str | None] = mapped_column(String(80))
    body_font: Mapped[str | None] = mapped_column(String(80))
    voice_tone: Mapped[str | None] = mapped_column(Text)
    do_words: Mapped[list[str]] = mapped_column(JSON, default=list)
    dont_words: Mapped[list[str]] = mapped_column(JSON, default=list)
    sample_posts: Mapped[list[str]] = mapped_column(JSON, default=list)

    workspace: Mapped[Workspace] = relationship(back_populates="brand_kit", lazy="raise")


class BrandDocument(UUIDPk, Timestamps, Base):
    """An uploaded brand doc (PDF/MD/TXT). Chunked + embedded into BrandChunk."""

    __tablename__ = "brand_documents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus), default=DocumentStatus.PENDING
    )
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class BrandChunk(UUIDPk, Timestamps, Base):
    __tablename__ = "brand_chunks"
    __table_args__ = (
        Index(
            "ix_brand_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("brand_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(120))
