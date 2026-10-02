from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from launchpad.domain.enums import DocumentStatus
from launchpad.schemas.common import Schema


class VoiceProfile(Schema):
    """Structured brand voice, produced from sample posts by the LLM and editable by users."""

    summary: str = Field(
        min_length=10, max_length=600, description="Two-sentence description of the voice."
    )
    tone_adjectives: list[str] = Field(min_length=3, max_length=8)
    formality: int = Field(ge=1, le=5, description="1 = very casual, 5 = very formal")
    sentence_length: Literal["short", "medium", "long", "mixed"]
    emoji_usage: Literal["none", "rare", "moderate", "frequent"]
    do_words: list[str] = Field(default_factory=list, max_length=20)
    dont_words: list[str] = Field(default_factory=list, max_length=20)
    signature_phrases: list[str] = Field(default_factory=list, max_length=10)


class VoiceFromSamplesIn(Schema):
    samples: list[str] = Field(min_length=3, max_length=10)


class BrandDocumentOut(Schema):
    id: uuid.UUID
    source_type: Literal["file", "url"]
    filename: str
    source_url: str | None
    mime_type: str
    size_bytes: int | None
    status: DocumentStatus
    error: str | None
    chunk_count: int
    embedding_model: str | None = None
    needs_reindex: bool = False
    created_at: datetime
    updated_at: datetime


class BrandUrlIn(Schema):
    url: HttpUrl
    max_pages: int = Field(default=10, ge=1, le=10)


class RetrievalQueryIn(Schema):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=6, ge=1, le=20)


class RetrievedChunkOut(Schema):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float  # cosine similarity, 0..1
    source: str
    page: int | None
    heading: str | None


class RetrievalOut(Schema):
    query: str
    min_score: float
    chunks: list[RetrievedChunkOut]
    dropped_below_threshold: int


class IndexStatusOut(Schema):
    configured_model: str | None
    configured_dim: int
    stale_documents: int
    needs_reindex: bool
