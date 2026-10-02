"""stage b llm calls ai settings rag generation

Revision ID: 4ca56d3d370a
Revises: 744ddffae445
Create Date: 2026-10-02 12:39:30.613543
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4ca56d3d370a"
down_revision: str | None = "744ddffae445"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brand_chunks",
        sa.Column("embedding_dim", sa.Integer(), server_default="768", nullable=False),
    )
    op.add_column(
        "brand_chunks", sa.Column("token_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "brand_chunks",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "brand_documents",
        sa.Column("source_type", sa.String(length=16), server_default="file", nullable=False),
    )
    op.add_column("brand_documents", sa.Column("source_url", sa.String(length=1000), nullable=True))
    op.add_column("brand_documents", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "brand_documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column(
        "brand_documents", "storage_key", existing_type=sa.VARCHAR(length=500), nullable=True
    )
    op.add_column(
        "brand_kits",
        sa.Column("voice_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "brand_kits",
        sa.Column(
            "logo_palette",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "generation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("llm_calls", sa.Column("user_id", sa.UUID(), nullable=True))
    op.add_column(
        "llm_calls",
        sa.Column("route", sa.String(length=32), server_default="writing", nullable=False),
    )
    op.add_column(
        "llm_calls", sa.Column("status", sa.String(length=16), server_default="ok", nullable=False)
    )
    op.add_column("llm_calls", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column("llm_calls", sa.Column("prompt_name", sa.String(length=64), nullable=True))
    op.add_column("llm_calls", sa.Column("prompt_version", sa.String(length=32), nullable=True))
    op.add_column("llm_calls", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.add_column(
        "llm_calls", sa.Column("attempts", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "llm_calls", sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.alter_column(
        "llm_calls", "cost_usd", existing_type=sa.NUMERIC(precision=12, scale=6), nullable=True
    )
    op.create_index(op.f("ix_llm_calls_user_id"), "llm_calls", ["user_id"], unique=False)
    op.create_index(
        "ix_llm_calls_ws_created", "llm_calls", ["workspace_id", "created_at"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_llm_calls_user_id_users"),
        "llm_calls",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "ai_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "ai_settings")
    op.drop_constraint(op.f("fk_llm_calls_user_id_users"), "llm_calls", type_="foreignkey")
    op.drop_index("ix_llm_calls_ws_created", table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_user_id"), table_name="llm_calls")
    op.alter_column(
        "llm_calls", "cost_usd", existing_type=sa.NUMERIC(precision=12, scale=6), nullable=False
    )
    op.drop_column("llm_calls", "payload")
    op.drop_column("llm_calls", "attempts")
    op.drop_column("llm_calls", "request_id")
    op.drop_column("llm_calls", "prompt_version")
    op.drop_column("llm_calls", "prompt_name")
    op.drop_column("llm_calls", "error_code")
    op.drop_column("llm_calls", "status")
    op.drop_column("llm_calls", "route")
    op.drop_column("llm_calls", "user_id")
    op.drop_column("content_items", "generation")
    op.drop_column("brand_kits", "logo_palette")
    op.drop_column("brand_kits", "voice_profile")
    op.alter_column(
        "brand_documents", "storage_key", existing_type=sa.VARCHAR(length=500), nullable=False
    )
    op.drop_column("brand_documents", "metadata")
    op.drop_column("brand_documents", "size_bytes")
    op.drop_column("brand_documents", "source_url")
    op.drop_column("brand_documents", "source_type")
    op.drop_column("brand_chunks", "metadata")
    op.drop_column("brand_chunks", "token_count")
    op.drop_column("brand_chunks", "embedding_dim")
