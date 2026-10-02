from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from launchpad.db.base import Base, Timestamps, UUIDPk
from launchpad.domain.enums import AgentRunStatus, MessageRole
from launchpad.models._types import JSON, str_enum

_COST = Numeric(12, 6)


class AgentRun(UUIDPk, Timestamps, Base):
    """One agent session. LangGraph's checkpointer keys its state on `thread_id`."""

    __tablename__ = "agent_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[AgentRunStatus] = mapped_column(
        str_enum(AgentRunStatus), default=AgentRunStatus.RUNNING
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(120))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, default=Decimal(0))
    token_budget: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentMessage(UUIDPk, Timestamps, Base):
    """Every step of a run: user turns, assistant turns, tool calls and tool results."""

    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_run_seq", "run_id", "seq", unique=True),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole))
    content: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    tool_call_id: Mapped[str | None] = mapped_column(String(128))
    tool_input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tool_output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, default=Decimal(0))
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class LLMCall(UUIDPk, Timestamps, Base):
    """Log of every LLM/embedding/image call, for usage + cost reporting."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_ws_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(64))  # e.g. "write_content", "critique_content"
    route: Mapped[str] = mapped_column(String(32), default="writing")  # Purpose used for routing
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    error_code: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    prompt_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    # NULL = price unknown for this model (never guessed).
    cost_usd: Mapped[Decimal | None] = mapped_column(_COST)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # Prompts/outputs; only stored when LOG_LLM_PAYLOADS=true.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
