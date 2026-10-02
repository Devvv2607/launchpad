"""Brand knowledge: ingest documents into pgvector and retrieve cited context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.config import get_settings
from launchpad.domain.enums import DocumentStatus
from launchpad.llm.service import CallContext, llm
from launchpad.models import BrandChunk, BrandDocument
from launchpad.rag.chunk import chunk_sections
from launchpad.rag.crawl import crawl
from launchpad.rag.extract import ExtractionError, Section, from_docx, from_pdf, from_text
from launchpad.storage import get_storage

log = structlog.get_logger(__name__)
EMBED_BATCH = 64


async def extract_document(doc: BrandDocument) -> tuple[list[Section], dict[str, object]]:
    if doc.source_type == "url":
        assert doc.source_url
        max_pages = int(doc.meta.get("max_pages", 10)) if isinstance(doc.meta, dict) else 10
        result = await crawl(doc.source_url, max_pages=max_pages)
        return result.sections, {
            "pages": result.pages,
            "skipped": result.skipped,
            "title": result.title,
        }
    assert doc.storage_key
    data = await get_storage().get(doc.storage_key)
    if doc.mime_type == "application/pdf":
        return from_pdf(data, doc.filename), {}
    if doc.mime_type.endswith("wordprocessingml.document"):
        return from_docx(data, doc.filename), {}
    text = data.decode("utf-8")
    return from_text(text, doc.filename, markdown=doc.mime_type == "text/markdown"), {}


async def ingest(db: AsyncSession, doc: BrandDocument, ctx: CallContext) -> int:
    """Extract → chunk → embed → store. Replaces any previous chunks atomically."""
    s = get_settings()
    from launchpad.models._types import EMBEDDING_DIM

    if s.embedding_dim != EMBEDDING_DIM:
        raise ExtractionError(
            f"EMBEDDING_DIM={s.embedding_dim} doesn't match the database (vector({EMBEDDING_DIM}))."
        )
    sections, meta = await extract_document(doc)
    chunks = chunk_sections(sections)
    if not chunks:
        raise ExtractionError("No text could be extracted from this document.")

    vectors: list[list[float]] = []
    model = ""
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vecs, route = await llm.embed(ctx, [c.text for c in batch], task="document")
        vectors.extend(vecs)
        model = route.model

    await db.execute(delete(BrandChunk).where(BrandChunk.document_id == doc.id))
    for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
        db.add(
            BrandChunk(
                workspace_id=doc.workspace_id,
                document_id=doc.id,
                ordinal=i,
                content=chunk.text,
                embedding=vec,
                embedding_model=model,
                embedding_dim=len(vec),
                token_count=chunk.tokens,
                meta={
                    "source": chunk.source or doc.filename,
                    "page": chunk.page,
                    "heading": chunk.heading,
                },
            )
        )
    doc.chunk_count = len(chunks)
    doc.status = DocumentStatus.READY
    doc.error = None
    doc.meta = {**(doc.meta or {}), **meta, "embedding_model": model}
    await db.commit()
    log.info("brand_doc_ingested", document_id=str(doc.id), chunks=len(chunks), model=model)
    return len(chunks)


@dataclass
class Retrieved:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    source: str
    page: int | None
    heading: str | None


async def retrieve_brand_context(
    db: AsyncSession, ctx: CallContext, query: str, k: int = 6, min_score: float | None = None
) -> tuple[list[Retrieved], int]:
    """Top-k chunks by cosine similarity above `min_score`. Returns (hits, dropped_count).

    Only chunks embedded with the *currently configured* model are searched — vectors from
    different models aren't comparable. Stale docs show up as "Re-index needed" in the UI.
    """
    threshold = get_settings().rag_min_score if min_score is None else min_score
    has_chunks = await db.scalar(
        select(func.count())
        .select_from(BrandChunk)
        .where(BrandChunk.workspace_id == ctx.workspace_id)
    )
    if not has_chunks:
        return [], 0
    [qvec], route = await llm.embed(ctx, [query], task="query")
    distance = BrandChunk.embedding.cosine_distance(qvec)
    rows = (
        await db.execute(
            select(BrandChunk, distance.label("distance"))
            .where(
                BrandChunk.workspace_id == ctx.workspace_id,
                BrandChunk.embedding_model == route.model,
            )
            .order_by(distance)
            .limit(k * 2)
        )
    ).all()
    hits: list[Retrieved] = []
    dropped = 0
    for chunk, dist in rows:
        score = round(1 - float(dist), 4)
        if score < threshold:
            dropped += 1
            continue
        if len(hits) < k:
            meta = chunk.meta or {}
            hits.append(
                Retrieved(
                    chunk.id, chunk.document_id, chunk.content, score,
                    str(meta.get("source") or ""), meta.get("page"), meta.get("heading"),
                )
            )  # fmt: skip
    return hits, dropped


async def stale_documents(db: AsyncSession, workspace_id: uuid.UUID) -> set[uuid.UUID]:
    """Ready documents whose chunks weren't embedded with the configured model/dimension."""
    s = get_settings()
    rows = await db.execute(
        select(BrandChunk.document_id)
        .where(
            BrandChunk.workspace_id == workspace_id,
            (BrandChunk.embedding_model != (s.embedding_model or ""))
            | (BrandChunk.embedding_dim != s.embedding_dim),
        )
        .distinct()
    )
    return {r[0] for r in rows}
