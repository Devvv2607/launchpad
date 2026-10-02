"""Upload validation + image processing. Types are sniffed from content, never trusted
from the filename or Content-Type header."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from launchpad.api.errors import AppError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_DOC_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000  # decompression-bomb guard
IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}

DOC_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


class UploadRejected(AppError):
    status_code = 415
    code = "unsupported_upload"


class UploadTooLarge(AppError):
    status_code = 413
    code = "upload_too_large"


@dataclass(frozen=True)
class ProcessedImage:
    original: bytes
    original_mime: str
    normalized_png: bytes
    normalized_size: tuple[int, int]
    thumbnail_png: bytes
    thumbnail_size: tuple[int, int]
    width: int
    height: int
    image: Image.Image


def _too_large(kind: str, limit: int, size: int) -> UploadTooLarge:
    return UploadTooLarge(
        f"{kind} is {size / 1_048_576:.1f} MB; the limit is {limit // 1_048_576} MB.",
        details={"limit_bytes": limit, "size_bytes": size},
    )


def process_image(data: bytes, *, max_side: int = 1024, thumb_side: int = 256) -> ProcessedImage:
    if len(data) > MAX_IMAGE_BYTES:
        raise _too_large("Image", MAX_IMAGE_BYTES, len(data))
    if data.lstrip()[:5].lower() in (b"<?xml", b"<svg ") or b"<svg" in data[:512].lower():
        raise UploadRejected(
            "SVG isn't supported yet. Export your logo as PNG (transparent background works best)."
        )
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # structural check; must reopen afterwards
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UploadRejected("That file isn't a readable PNG, JPEG, WebP or GIF image.") from exc
    if img.format not in IMAGE_FORMATS:
        raise UploadRejected(f"{img.format} images aren't supported. Use PNG, JPEG, WebP or GIF.")

    rgba = img.convert("RGBA")
    normalized = rgba.copy()
    normalized.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    thumb = rgba.copy()
    thumb.thumbnail((thumb_side, thumb_side), Image.Resampling.LANCZOS)
    return ProcessedImage(
        original=data,
        original_mime=IMAGE_FORMATS[img.format],
        normalized_png=_png(normalized),
        normalized_size=normalized.size,
        thumbnail_png=_png(thumb),
        thumbnail_size=thumb.size,
        width=img.width,
        height=img.height,
        image=rgba,
    )


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def sniff_document(data: bytes, filename: str) -> str:
    """Return the document MIME type, from magic bytes (and extension only for text)."""
    if len(data) > MAX_DOC_BYTES:
        raise _too_large("Document", MAX_DOC_BYTES, len(data))
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04") and filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    lower = filename.lower()
    if lower.endswith((".txt", ".md", ".markdown")):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadRejected("Text files must be UTF-8.") from exc
        return "text/markdown" if lower.endswith((".md", ".markdown")) else "text/plain"
    raise UploadRejected("Upload a PDF, DOCX, TXT or Markdown file.")


def storage_key(workspace_id: uuid.UUID, kind: str, ext: str) -> str:
    return f"ws/{workspace_id}/{kind}/{uuid.uuid4().hex}{ext}"
