"""agent events run budgets

Revision ID: 1e8383446849
Revises: 4ca56d3d370a
Create Date: 2026-10-06 14:19:11.862329
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1e8383446849"
down_revision: str | None = "4ca56d3d370a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_events",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_events_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
    )
    op.create_index("ix_agent_events_run_seq", "agent_events", ["run_id", "seq"], unique=True)
    op.add_column(
        "agent_runs",
        sa.Column(
            "cost_budget_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="1.00",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_runs", sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("agent_runs", sa.Column("input", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("final", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "final")
    op.drop_column("agent_runs", "input")
    op.drop_column("agent_runs", "tool_calls")
    op.drop_column("agent_runs", "cost_budget_usd")
    op.drop_index("ix_agent_events_run_seq", table_name="agent_events")
    op.drop_table("agent_events")
