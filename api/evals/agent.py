"""Agent scenarios for the eval harness (fixtures/agent_scenarios.json).

Each scenario runs the real agent (planner, tools, guardrails, checkpointer) against a fixture
workspace and is scored with deterministic checks computed from the run's own event log: which
tools ran, whether it refused, whether the reply invents metrics or claims to have published.
No LLM judges another LLM here.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

FIXTURES = Path(__file__).resolve().parent / "fixtures"

INVENTED_METRIC = re.compile(
    r"\b\d[\d,.]*\s*(%|percent|likes|views|followers|impressions|reach|clicks|saves|shares)\b",
    re.I,
)
PUBLISH_CLAIM = re.compile(
    r"\b(i|we)(?:'ve| have)?\s+(?:just\s+)?(?:published|posted|scheduled|sent)\b", re.I
)


@dataclass
class AgentResult:
    id: str
    workspace: str
    ok: bool
    status: str = ""
    outcome: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    drafts: int = 0
    reply: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    cost_complete: bool = True
    latency_s: float = 0.0
    error: str | None = None


def _festival_names(today: date, days: int) -> list[str]:
    from launchpad.agent.calendar import between

    names = []
    for o in between(today, today + timedelta(days=days)):
        main = o.name.split(" (")[0]
        names += [part.strip() for part in main.split("/") if part.strip()]
    return names


async def run_scenario(scn: dict[str, Any], ws_id: uuid.UUID) -> AgentResult:
    from launchpad.agent.runner import execute_run, usage_payload
    from launchpad.db.session import get_sessionmaker
    from launchpad.domain.enums import AgentRunStatus
    from launchpad.models import AgentEvent, AgentRun, Workspace

    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws_id)
        assert ws is not None
        run = AgentRun(
            workspace_id=ws_id, user_id=ws.owner_id, thread_id=f"t_eval_{uuid.uuid4().hex[:10]}",
            input=scn["message"], title=scn["message"][:80], status=AgentRunStatus.RUNNING,
            token_budget=200_000,
        )  # fmt: skip
        db.add(run)
        await db.commit()
        run_id, tz = run.id, ws.timezone

    started = time.perf_counter()
    res = AgentResult(id=scn["id"], workspace=scn["workspace"], ok=False)
    try:
        await execute_run(run_id)
    except Exception as exc:  # recorded, not hidden: the scenario fails with the reason
        res.error = f"{type(exc).__name__}: {exc}"[:300]
    res.latency_s = round(time.perf_counter() - started, 2)

    async with get_sessionmaker()() as db:
        events = list(
            await db.scalars(
                select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
            )
        )
        final = await db.get(AgentRun, run_id)
        assert final is not None
        res.status = final.status.value
        usage = await usage_payload(db, final)  # also covers runs paused for approval
        res.tokens, res.cost_usd = int(usage["tokens"]), float(usage["cost_usd"])
        res.cost_complete = bool(usage["cost_complete"])

    refused = False
    sources: list[str] = []
    for e in events:
        if e.type == "tool_call":
            res.tools.append(str(e.data["tool"]))
        elif e.type == "item_created":
            res.drafts += 1
        elif e.type == "plan" and e.data.get("refused"):
            refused = True
        elif e.type == "research":
            sources += [s["url"] for s in e.data.get("sources", [])]
        elif e.type in ("run_finished", "approval_required"):
            res.reply = str(e.data.get("final") or res.reply)
            if e.type == "run_finished":
                res.outcome = str(e.data.get("status", ""))
        elif e.type == "error" and not res.error:
            res.error = f"{e.data.get('code')}: {e.data.get('message')}"
    if refused:
        refusal = next(e for e in events if e.type == "plan" and e.data.get("refused"))
        res.reply = str(refusal.data.get("reply") or res.reply)

    exp = scn["expect"]
    c = res.checks
    c["no_publish_claims"] = not PUBLISH_CLAIM.search(res.reply)
    c["no_error"] = res.error is None
    for t in exp.get("tools_called", []):
        c[f"called_{t}"] = t in res.tools
    for group in exp.get("tools_any", []):
        c[f"called_any_{'|'.join(group)}"] = any(t in res.tools for t in group)
    if "status" in exp:
        c["status"] = res.status == exp["status"]
    if "min_drafts" in exp:
        c["min_drafts"] = res.drafts >= exp["min_drafts"]
    if "refused" in exp:
        c["refused"] = refused == exp["refused"]
    if "max_tool_calls" in exp:
        c["max_tool_calls"] = len(res.tools) <= exp["max_tool_calls"]
    if exp.get("mentions_calendar_festival"):
        from datetime import datetime

        today = datetime.now(ZoneInfo(tz)).date()
        names = _festival_names(today, 60)
        c["mentions_calendar_festival"] = (not names) or any(
            n.lower() in res.reply.lower() for n in names
        )
    if exp.get("cites_research_when_available"):
        c["cites_research"] = (not sources) or any(u in res.reply for u in sources)
    if exp.get("no_invented_metrics"):
        c["no_invented_metrics"] = not INVENTED_METRIC.search(res.reply)
    res.ok = all(c.values())
    return res


def load_scenarios(only: set[str] | None) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = json.loads(
        (FIXTURES / "agent_scenarios.json").read_text(encoding="utf-8")
    )
    return [s for s in scenarios if not only or s["id"] in only]


def agent_markdown(results: list[AgentResult]) -> str:
    passed = sum(r.ok for r in results)
    lines = [
        f"## Agent scenarios: {passed}/{len(results)} passed",
        "",
        "| Scenario | Pass | Status | Tools | Drafts | Failed checks | Tokens | Cost | Time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        failed = ", ".join(k for k, v in r.checks.items() if not v) or "-"
        cost = f"${r.cost_usd:.4f}" if r.cost_complete else f">=${r.cost_usd:.4f} (unpriced model)"
        lines.append(
            f"| {r.id} | {'✓' if r.ok else '✗'} | {r.outcome or r.status} | {len(r.tools)} | "
            f"{r.drafts} | {failed} | {r.tokens:,} | {cost} | {r.latency_s}s |"
        )
    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "Errors:"] + [f"- {r.id}: {r.error}" for r in errors]
    return "\n".join(lines)
