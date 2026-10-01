"""Domain enums shared by models, API schemas and the agent."""

from __future__ import annotations

from enum import StrEnum


class Industry(StrEnum):
    FASHION = "fashion"
    FOOD = "food"
    TECH = "tech"
    FITNESS = "fitness"
    BEAUTY = "beauty"
    EDUCATION = "education"
    FINANCE = "finance"
    REAL_ESTATE = "real_estate"
    HEALTHCARE = "healthcare"
    TRAVEL = "travel"
    AUTOMOTIVE = "automotive"
    HOME = "home"
    ENTERTAINMENT = "entertainment"
    PET = "pet"
    RETAIL = "retail"


class CampaignGoal(StrEnum):
    AWARENESS = "awareness"
    LEADS = "leads"
    SALES = "sales"
    EVENT = "event"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Channel(StrEnum):
    INSTAGRAM_POST = "instagram_post"
    INSTAGRAM_CAROUSEL = "instagram_carousel"
    LINKEDIN_POST = "linkedin_post"
    X_POST = "x_post"
    EMAIL = "email"
    POSTER = "poster"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"


# Allowed status transitions. Anything outbound must pass through APPROVED,
# which only a human can set (see content service).
CONTENT_TRANSITIONS: dict[ContentStatus, frozenset[ContentStatus]] = {
    ContentStatus.DRAFT: frozenset({ContentStatus.IN_REVIEW, ContentStatus.APPROVED}),
    ContentStatus.IN_REVIEW: frozenset({ContentStatus.DRAFT, ContentStatus.APPROVED}),
    ContentStatus.APPROVED: frozenset({ContentStatus.DRAFT, ContentStatus.SCHEDULED}),
    ContentStatus.SCHEDULED: frozenset(
        {ContentStatus.APPROVED, ContentStatus.PUBLISHED, ContentStatus.FAILED}
    ),
    ContentStatus.PUBLISHED: frozenset(),
    ContentStatus.FAILED: frozenset({ContentStatus.DRAFT, ContentStatus.APPROVED}),
}


class AssetKind(StrEnum):
    IMAGE = "image"
    POSTER = "poster"
    LOGO = "logo"
    UPLOAD = "upload"


class AssetSource(StrEnum):
    GENERATED = "generated"
    UPLOADED = "uploaded"
    RENDERED = "rendered"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    EMAIL = "email"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    PUBLISH = "publish"
    GENERATE = "generate"
    INGEST_DOCUMENT = "ingest_document"
    FETCH_METRICS = "fetch_metrics"
