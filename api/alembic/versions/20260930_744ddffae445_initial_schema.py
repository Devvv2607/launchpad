"""initial schema

Revision ID: 744ddffae445
Revises:
Create Date: 2026-09-30 15:06:31.541652
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "744ddffae445"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("external_auth_id", sa.String(length=128), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("external_auth_id", name=op.f("uq_users_external_auth_id")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "workspaces",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "industry",
            sa.Enum(
                "fashion",
                "food",
                "tech",
                "fitness",
                "beauty",
                "education",
                "finance",
                "real_estate",
                "healthcare",
                "travel",
                "automotive",
                "home",
                "entertainment",
                "pet",
                "retail",
                name="industry",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False)
    op.create_table(
        "brand_documents",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="documentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_brand_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_documents")),
    )
    op.create_index(
        op.f("ix_brand_documents_workspace_id"), "brand_documents", ["workspace_id"], unique=False
    )
    op.create_table(
        "brand_kits",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("logo_asset_id", sa.UUID(), nullable=True),
        sa.Column("primary_color", sa.String(length=9), nullable=True),
        sa.Column("secondary_color", sa.String(length=9), nullable=True),
        sa.Column("accent_colors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("heading_font", sa.String(length=80), nullable=True),
        sa.Column("body_font", sa.String(length=80), nullable=True),
        sa.Column("voice_tone", sa.Text(), nullable=True),
        sa.Column("do_words", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dont_words", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sample_posts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_brand_kits_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_kits")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_brand_kits_workspace_id")),
    )
    op.create_table(
        "campaigns",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "goal",
            sa.Enum(
                "awareness",
                "leads",
                "sales",
                "event",
                name="campaigngoal",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("brief", sa.Text(), nullable=True),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("budget_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "planned",
                "active",
                "completed",
                "archived",
                name="campaignstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_campaigns_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index(op.f("ix_campaigns_workspace_id"), "campaigns", ["workspace_id"], unique=False)
    op.create_table(
        "channel_connections",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum(
                "instagram", "linkedin", "email", name="platform", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "expired",
                "revoked",
                "error",
                name="connectionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_channel_connections_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_connections")),
        sa.UniqueConstraint("workspace_id", "platform", "account_id", name="uq_channel_account"),
    )
    op.create_index(
        op.f("ix_channel_connections_workspace_id"),
        "channel_connections",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "agent_runs",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "awaiting_approval",
                "completed",
                "failed",
                "cancelled",
                name="agentrunstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_agent_runs_campaign_id_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_runs_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(op.f("ix_agent_runs_thread_id"), "agent_runs", ["thread_id"], unique=False)
    op.create_index(
        op.f("ix_agent_runs_workspace_id"), "agent_runs", ["workspace_id"], unique=False
    )
    op.create_table(
        "brand_chunks",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["brand_documents.id"],
            name=op.f("fk_brand_chunks_document_id_brand_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_brand_chunks_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_chunks")),
    )
    op.create_index(
        op.f("ix_brand_chunks_document_id"), "brand_chunks", ["document_id"], unique=False
    )
    op.create_index(
        "ix_brand_chunks_embedding_hnsw",
        "brand_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_brand_chunks_workspace_id"), "brand_chunks", ["workspace_id"], unique=False
    )
    op.create_table(
        "agent_messages",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "system",
                "user",
                "assistant",
                "tool",
                name="messagerole",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_messages_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
    )
    op.create_index("ix_agent_messages_run_seq", "agent_messages", ["run_id", "seq"], unique=True)
    op.create_table(
        "assets",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "image", "poster", "logo", "upload", name="assetkind", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "generated",
                "uploaded",
                "rendered",
                name="assetsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("variant", sa.String(length=32), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_assets_agent_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["assets.id"],
            name=op.f("fk_assets_parent_id_assets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_assets_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_assets_storage_key")),
    )
    op.create_index(op.f("ix_assets_parent_id"), "assets", ["parent_id"], unique=False)
    op.create_index(op.f("ix_assets_workspace_id"), "assets", ["workspace_id"], unique=False)
    op.create_table(
        "content_items",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum(
                "instagram_post",
                "instagram_carousel",
                "linkedin_post",
                "x_post",
                "email",
                "poster",
                name="channel",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hashtags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("variant_group", sa.Uuid(), nullable=True),
        sa.Column("variant_label", sa.String(length=8), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "scheduled",
                "published",
                "failed",
                name="contentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=1000), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("critique_score", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_content_items_agent_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_content_items_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_content_items_campaign_id_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_content_items_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_items")),
    )
    op.create_index(
        op.f("ix_content_items_agent_run_id"), "content_items", ["agent_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_content_items_campaign_id"), "content_items", ["campaign_id"], unique=False
    )
    op.create_index(
        op.f("ix_content_items_variant_group"), "content_items", ["variant_group"], unique=False
    )
    op.create_index(
        op.f("ix_content_items_workspace_id"), "content_items", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_content_items_ws_scheduled",
        "content_items",
        ["workspace_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_content_items_ws_status", "content_items", ["workspace_id", "status"], unique=False
    )
    op.create_table(
        "llm_calls",
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_llm_calls_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_llm_calls_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_run_id"), "llm_calls", ["run_id"], unique=False)
    op.create_index(op.f("ix_llm_calls_workspace_id"), "llm_calls", ["workspace_id"], unique=False)
    op.create_table(
        "content_assets",
        sa.Column("content_item_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_content_assets_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
            name=op.f("fk_content_assets_content_item_id_content_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_item_id", "asset_id", name=op.f("pk_content_assets")),
    )
    op.create_table(
        "metric_snapshots",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("content_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "platform",
            sa.Enum(
                "instagram", "linkedin", "email", name="platform", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["channel_connections.id"],
            name=op.f("fk_metric_snapshots_connection_id_channel_connections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
            name=op.f("fk_metric_snapshots_content_item_id_content_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_metric_snapshots_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_snapshots")),
    )
    op.create_index(
        "ix_metric_snapshots_item_time",
        "metric_snapshots",
        ["content_item_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_metric_snapshots_ws_time",
        "metric_snapshots",
        ["workspace_id", "captured_at"],
        unique=False,
    )
    op.create_table(
        "scheduled_jobs",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "publish",
                "generate",
                "ingest_document",
                "fetch_metrics",
                name="jobkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content_item_id", sa.UUID(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="jobstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("publisher", sa.String(length=32), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
            name=op.f("fk_scheduled_jobs_content_item_id_content_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_scheduled_jobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_jobs")),
    )
    op.create_index(
        op.f("ix_scheduled_jobs_content_item_id"),
        "scheduled_jobs",
        ["content_item_id"],
        unique=False,
    )
    op.create_index("ix_scheduled_jobs_due", "scheduled_jobs", ["status", "run_at"], unique=False)
    op.create_index(
        op.f("ix_scheduled_jobs_workspace_id"), "scheduled_jobs", ["workspace_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_brand_kits_logo_asset_id_assets"),
        "brand_kits",
        "assets",
        ["logo_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_brand_kits_logo_asset_id_assets"), "brand_kits", type_="foreignkey")
    op.drop_index(op.f("ix_scheduled_jobs_workspace_id"), table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_due", table_name="scheduled_jobs")
    op.drop_index(op.f("ix_scheduled_jobs_content_item_id"), table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
    op.drop_index("ix_metric_snapshots_ws_time", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_item_time", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
    op.drop_table("content_assets")
    op.drop_index(op.f("ix_llm_calls_workspace_id"), table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_run_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_content_items_ws_status", table_name="content_items")
    op.drop_index("ix_content_items_ws_scheduled", table_name="content_items")
    op.drop_index(op.f("ix_content_items_workspace_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_variant_group"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_campaign_id"), table_name="content_items")
    op.drop_index(op.f("ix_content_items_agent_run_id"), table_name="content_items")
    op.drop_table("content_items")
    op.drop_index(op.f("ix_assets_workspace_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_parent_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_agent_messages_run_seq", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index(op.f("ix_brand_chunks_workspace_id"), table_name="brand_chunks")
    op.drop_index(
        "ix_brand_chunks_embedding_hnsw",
        table_name="brand_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_brand_chunks_document_id"), table_name="brand_chunks")
    op.drop_table("brand_chunks")
    op.drop_index(op.f("ix_agent_runs_workspace_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_thread_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index(op.f("ix_channel_connections_workspace_id"), table_name="channel_connections")
    op.drop_table("channel_connections")
    op.drop_index(op.f("ix_campaigns_workspace_id"), table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_table("brand_kits")
    op.drop_index(op.f("ix_brand_documents_workspace_id"), table_name="brand_documents")
    op.drop_table("brand_documents")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
