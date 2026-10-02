"""Brand knowledge (RAG docs, retrieval test) and voice profile endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import select

from launchpad.api.deps import DB, CurrentUser, CurrentWorkspace
from launchpad.api.errors import AppError, NotFound
from launchpad.api.ratelimit import rate_limit
from launchpad.config import get_settings
from launchpad.domain.enums import DocumentStatus, JobKind
from launchpad.jobs.queue import enqueue
from launchpad.llm.service import CallContext, llm
from launchpad.llm.types import Purpose
from launchpad.models import BrandDocument, BrandKit, Workspace
from launchpad.prompts import load_prompt
from launchpad.rag.crawl import CrawlError, assert_public_url
from launchpad.rag.service import retrieve_brand_context, stale_documents
from launchpad.schemas.brand import (
    BrandDocumentOut,
    BrandUrlIn,
    IndexStatusOut,
    RetrievalOut,
    RetrievalQueryIn,
    RetrievedChunkOut,
    VoiceFromSamplesIn,
    VoiceProfile,
)
from launchpad.services.uploads import DOC_TYPES, MAX_DOC_BYTES, sniff_document, storage_key
from launchpad.storage import get_storage

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["brand"])
MAX_DOCS_PER_WORKSPACE = 50


def _out(doc: BrandDocument, stale: set[uuid.UUID]) -> BrandDocumentOut:
    out = BrandDocumentOut.model_validate(doc)
    out.embedding_model = (doc.meta or {}).get("embedding_model")
    out.needs_reindex = doc.id in stale
    return out


async def _doc(db: DB, ws: Workspace, doc_id: uuid.UUID) -> BrandDocument:
    doc = await db.get(BrandDocument, doc_id)
    if doc is None or doc.workspace_id != ws.id:
        raise NotFound("Document not found.")
    return doc


async def _check_quota(db: DB, ws: Workspace) -> None:
    count = len(
        list(await db.scalars(select(BrandDocument.id).where(BrandDocument.workspace_id == ws.id)))
    )
    if count >= MAX_DOCS_PER_WORKSPACE:
        raise AppError(f"A workspace can hold up to {MAX_DOCS_PER_WORKSPACE} brand documents.")


@router.get("/brand-docs", response_model=list[BrandDocumentOut])
async def list_brand_docs(ws: CurrentWorkspace, db: DB) -> list[BrandDocumentOut]:
    docs = await db.scalars(
        select(BrandDocument)
        .where(BrandDocument.workspace_id == ws.id)
        .order_by(BrandDocument.created_at.desc())
    )
    stale = await stale_documents(db, ws.id)
    return [_out(d, stale) for d in docs]


@router.post("/brand-docs", response_model=BrandDocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_brand_doc(
    ws: CurrentWorkspace, user: CurrentUser, db: DB, file: UploadFile = File(...)
) -> BrandDocumentOut:
    await _check_quota(db, ws)
    data = await file.read(MAX_DOC_BYTES + 1)
    filename = (file.filename or "document")[:255]
    mime = sniff_document(data, filename)
    key = storage_key(ws.id, "brand-docs", DOC_TYPES[mime])
    await get_storage().put(key, data, mime)
    doc = BrandDocument(
        workspace_id=ws.id, filename=filename, mime_type=mime, size_bytes=len(data), storage_key=key
    )
    db.add(doc)
    await db.flush()
    await enqueue(
        db, workspace_id=ws.id, kind=JobKind.INGEST_DOCUMENT,
        payload={"document_id": str(doc.id), "user_id": str(user.id)},
    )  # fmt: skip
    await db.refresh(doc)
    return _out(doc, set())


@router.post(
    "/brand-docs/url", response_model=BrandDocumentOut, status_code=status.HTTP_202_ACCEPTED
)
async def import_brand_url(
    body: BrandUrlIn, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> BrandDocumentOut:
    await _check_quota(db, ws)
    url = str(body.url)
    try:
        await assert_public_url(url)  # fail fast; every hop is re-checked during the crawl
    except CrawlError as exc:
        raise AppError(str(exc)) from exc
    doc = BrandDocument(
        workspace_id=ws.id, source_type="url", filename=body.url.host or url, source_url=url,
        mime_type="text/html", meta={"max_pages": body.max_pages},
    )  # fmt: skip
    db.add(doc)
    await db.flush()
    await enqueue(
        db, workspace_id=ws.id, kind=JobKind.INGEST_DOCUMENT,
        payload={"document_id": str(doc.id), "user_id": str(user.id)},
    )  # fmt: skip
    await db.refresh(doc)
    return _out(doc, set())


@router.delete("/brand-docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_doc(doc_id: uuid.UUID, ws: CurrentWorkspace, db: DB) -> None:
    doc = await _doc(db, ws, doc_id)
    if doc.storage_key:
        await get_storage().delete(doc.storage_key)
    await db.delete(doc)  # chunks cascade
    await db.commit()


@router.post(
    "/brand-docs/{doc_id}/reindex",
    response_model=BrandDocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_brand_doc(
    doc_id: uuid.UUID, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> BrandDocumentOut:
    doc = await _doc(db, ws, doc_id)
    doc.status, doc.error = DocumentStatus.PENDING, None
    await enqueue(
        db, workspace_id=ws.id, kind=JobKind.INGEST_DOCUMENT,
        payload={"document_id": str(doc.id), "user_id": str(user.id)},
    )  # fmt: skip
    await db.refresh(doc)
    return _out(doc, set())


@router.get("/brand-index", response_model=IndexStatusOut)
async def brand_index_status(ws: CurrentWorkspace, db: DB) -> IndexStatusOut:
    s = get_settings()
    stale = await stale_documents(db, ws.id)
    return IndexStatusOut(
        configured_model=s.embedding_model,
        configured_dim=s.embedding_dim,
        stale_documents=len(stale),
        needs_reindex=bool(stale),
    )


@router.post(
    "/brand-index/reindex",
    response_model=list[BrandDocumentOut],
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_stale(ws: CurrentWorkspace, user: CurrentUser, db: DB) -> list[BrandDocumentOut]:
    stale = await stale_documents(db, ws.id)
    out = []
    for doc_id in stale:
        doc = await _doc(db, ws, doc_id)
        doc.status, doc.error = DocumentStatus.PENDING, None
        await enqueue(
            db, workspace_id=ws.id, kind=JobKind.INGEST_DOCUMENT,
            payload={"document_id": str(doc.id), "user_id": str(user.id)},
        )  # fmt: skip
        await db.refresh(doc)
        out.append(_out(doc, set()))
    return out


@router.post(
    "/brand-docs/search",
    response_model=RetrievalOut,
    dependencies=[Depends(rate_limit("retrieval", 30, 60))],
)
async def test_retrieval(
    body: RetrievalQueryIn, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> RetrievalOut:
    ctx = CallContext.for_workspace(ws, user.id)
    hits, dropped = await retrieve_brand_context(db, ctx, body.query, k=body.k)
    return RetrievalOut(
        query=body.query,
        min_score=get_settings().rag_min_score,
        chunks=[RetrievedChunkOut.model_validate(h, from_attributes=True) for h in hits],
        dropped_below_threshold=dropped,
    )


@router.post(
    "/brand-kit/voice-profile",
    response_model=VoiceProfile,
    dependencies=[Depends(rate_limit("voice", 10, 60))],
)
async def voice_from_samples(
    body: VoiceFromSamplesIn, ws: CurrentWorkspace, user: CurrentUser, db: DB
) -> VoiceProfile:
    samples = [s.strip() for s in body.samples if s.strip()]
    if len(samples) < 3:
        raise AppError("Paste at least 3 non-empty posts.")
    prompt = load_prompt("voice_profile").render(
        business_name=ws.name, industry=ws.industry.value, audience=ws.audience, samples=samples
    )
    result, _ = await llm.generate(
        CallContext.for_workspace(ws, user.id), Purpose.WRITING, prompt,
        task="voice_profile", schema=VoiceProfile, temperature=0.2,
    )  # fmt: skip
    assert result.parsed is not None
    kit = await db.scalar(select(BrandKit).where(BrandKit.workspace_id == ws.id))
    assert kit is not None
    kit.sample_posts = samples
    kit.voice_profile = result.parsed.model_dump(mode="json")
    await db.commit()
    return result.parsed
