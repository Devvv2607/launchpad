"""Evaluation harness for the content engine.

    python -m evals.run --provider gemini            # uses LLM_MODEL / LLM_FAST_MODEL if gemini is the env provider
    python -m evals.run --provider groq --model openai/gpt-oss-120b --fast-model openai/gpt-oss-20b
    python -m evals.run --fake                       # no network: checks the harness itself (CI)
    python -m evals.run --provider groq --smoke      # quick check: 1 business (Kadak Tees) x 3 briefs

If the provider's quota runs out mid-run (a 429 that survives the client's retries, e.g. a daily
token limit), the run stops cleanly and the report is saved as PARTIAL with what completed.

Runs every brief in fixtures/briefs.json through the real pipeline (brand context + RAG +
write + critique/revise) against fresh fixture workspaces, then writes Markdown + JSON
reports to evals/reports/<date>/. Every number comes from the run itself (llm_calls rows,
validators, critique scores) — nothing is estimated after the fact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


@dataclass
class VariantMetrics:
    label: str
    angle: str
    draft_hard: int
    draft_soft: int
    final_hard: int
    final_soft: int
    score_before: float | None
    score_after: float | None
    rounds: int
    final_text: str = ""


@dataclass
class BriefResult:
    id: str
    workspace: str
    channel: str
    n: int
    ok: bool
    error_code: str | None = None
    error: str | None = None
    latency_s: float = 0.0
    calls: int = 0
    failed_calls: int = 0
    repaired_calls: int = 0
    cost_usd: float = 0.0
    unknown_cost_calls: int = 0
    knowledge_sources: int = 0
    variants: list[VariantMetrics] = field(default_factory=list)


def _avg(scores: dict[str, int] | None) -> float | None:
    return round(sum(scores.values()) / len(scores), 2) if scores else None


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def resolve_models(provider: str, model: str | None, fast: str | None) -> tuple[str, str]:
    from launchpad.config import get_settings

    s = get_settings()
    env_model = os.environ.get(f"EVAL_{provider.upper()}_MODEL")
    env_fast = os.environ.get(f"EVAL_{provider.upper()}_FAST_MODEL")
    same = s.llm_provider == provider
    chosen = model or env_model or (s.llm_model if same else None)
    chosen_fast = (
        fast or env_fast or ((s.llm_fast_model or s.llm_model) if same else None) or chosen
    )
    if not chosen or not chosen_fast:
        sys.exit(
            f"No model configured for {provider}. Pass --model/--fast-model or set "
            f"EVAL_{provider.upper()}_MODEL (model IDs are never guessed)."
        )
    return chosen, chosen_fast


async def setup_workspaces(
    provider: str, model: str, fast: str, run_id: str, only: set[str] | None = None
) -> dict[str, uuid.UUID]:
    from launchpad.db.session import get_sessionmaker
    from launchpad.llm.service import CallContext
    from launchpad.models import BrandDocument, BrandKit, User, Workspace
    from launchpad.rag.service import ingest
    from launchpad.storage import get_storage

    fixtures = json.loads((FIXTURES / "workspaces.json").read_text(encoding="utf-8"))
    ids: dict[str, uuid.UUID] = {}
    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == "evals@launchpad.local"))
        if user is None:
            user = User(email="evals@launchpad.local", name="Eval harness")
            db.add(user)
            await db.flush()
        routes = {
            "writing": {"provider": provider, "model": model},
            "planning": {"provider": provider, "model": model},
            "critique": {"provider": provider, "model": fast},
        }
        for key, fx in fixtures.items():
            if only is not None and key not in only:
                continue
            ws = Workspace(
                owner_id=user.id,
                name=f"[eval {run_id}] {fx['workspace']['name']}",
                ai_settings={"routes": routes, "daily_spend_cap_usd": 50},
                **{k: v for k, v in fx["workspace"].items() if k != "name"},
            )
            ws.brand_kit = BrandKit(**fx["brand_kit"])
            db.add(ws)
            await db.flush()
            text = (FIXTURES / fx["doc"]).read_bytes()
            storage_key = f"ws/{ws.id}/brand-docs/{uuid.uuid4().hex}.md"
            await get_storage().put(storage_key, text, "text/markdown")
            doc = BrandDocument(
                workspace_id=ws.id, filename=Path(fx["doc"]).name, mime_type="text/markdown",
                size_bytes=len(text), storage_key=storage_key,
            )  # fmt: skip
            db.add(doc)
            await db.commit()
            await ingest(db, doc, CallContext.for_workspace(ws, user.id))
            ids[key] = ws.id
    return ids


async def run_brief(brief: dict[str, Any], ws_id: uuid.UUID) -> BriefResult:
    from launchpad.content.context import build_brand_context
    from launchpad.content.engine import critique_content, main_text, write_content
    from launchpad.db.session import get_sessionmaker
    from launchpad.domain.enums import Channel
    from launchpad.llm.errors import LLMError
    from launchpad.llm.service import CallContext
    from launchpad.models import LLMCall, Workspace

    res = BriefResult(
        id=brief["id"],
        workspace=brief["workspace"],
        channel=brief["channel"],
        n=brief["n"],
        ok=False,
    )
    channel = Channel(brief["channel"])
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws_id)
        assert ws is not None
        ctx = CallContext.for_workspace(ws, ws.owner_id)
        try:
            variants = await write_content(
                db,
                ws,
                ctx,
                channel=channel,
                brief=brief["brief"],
                n_variants=brief["n"],
                save=False,
            )
            bctx = await build_brand_context(db, ws, ctx, query=brief["brief"])
            res.knowledge_sources = len(bctx.knowledge)
            for v in variants:
                first, last = v.iterations[0], v.iterations[-1]
                after = _avg(last.scores)
                if (
                    after is None
                ):  # final revision wasn't re-scored by the loop: score it (eval-only)
                    scores, _, _, _ = await critique_content(
                        ctx, bctx, channel=channel, brief=brief["brief"], angle=v.angle,
                        content=last.content, violations=last.violations,
                    )  # fmt: skip
                    after = scores.average()
                res.variants.append(
                    VariantMetrics(
                        label=v.label, angle=v.angle,
                        draft_hard=sum(x["severity"] == "error" for x in first.violations),
                        draft_soft=sum(x["severity"] == "warning" for x in first.violations),
                        final_hard=sum(x["severity"] == "error" for x in v.violations),
                        final_soft=sum(x["severity"] == "warning" for x in v.violations),
                        score_before=_avg(first.scores), score_after=after,
                        rounds=sum(1 for it in v.iterations if it.scores),
                        final_text=main_text(channel, v.content),
                    )
                )  # fmt: skip
            res.ok = True
        except LLMError as exc:
            res.error_code, res.error = exc.code, exc.message
        res.latency_s = round(time.perf_counter() - t0, 2)
        row = (
            await db.execute(
                select(
                    func.count(),
                    func.sum(case((LLMCall.status == "error", 1), else_=0)),
                    func.sum(case((LLMCall.attempts > 1, 1), else_=0)),
                    func.coalesce(func.sum(LLMCall.cost_usd), 0),
                    func.sum(
                        case((LLMCall.cost_usd.is_(None) & (LLMCall.status == "ok"), 1), else_=0)
                    ),
                ).where(LLMCall.workspace_id == ws_id, LLMCall.created_at >= started_at)
            )
        ).one()
    res.calls, res.failed_calls, res.repaired_calls = (
        int(row[0]),
        int(row[1] or 0),
        int(row[2] or 0),
    )
    res.cost_usd, res.unknown_cost_calls = round(float(row[3]), 6), int(row[4] or 0)
    return res


def summarise(results: list[BriefResult]) -> dict[str, Any]:
    variants = [v for r in results for v in r.variants]
    before = [v.score_before for v in variants if v.score_before is not None]
    after = [v.score_after for v in variants if v.score_after is not None]
    latencies = sorted(r.latency_s for r in results)
    calls = sum(r.calls for r in results)
    return {
        "briefs": len(results),
        "schema_valid_rate": round(sum(r.ok for r in results) / len(results), 3) if results else 0,
        "repair_rate": round(sum(r.repaired_calls for r in results) / calls, 3) if calls else 0,
        "variants": len(variants),
        "draft_hard_violations": sum(v.draft_hard for v in variants),
        "final_hard_violations": sum(v.final_hard for v in variants),
        "draft_soft_violations": sum(v.draft_soft for v in variants),
        "final_soft_violations": sum(v.final_soft for v in variants),
        "variants_blocked": sum(v.final_hard > 0 for v in variants),
        "avg_score_before": round(statistics.mean(before), 2) if before else None,
        "avg_score_after": round(statistics.mean(after), 2) if after else None,
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "latency_max_s": latencies[-1] if latencies else None,
        "total_cost_usd": round(sum(r.cost_usd for r in results), 4),
        "unknown_cost_calls": sum(r.unknown_cost_calls for r in results),
        "llm_calls": calls,
        "failed_calls": sum(r.failed_calls for r in results),
    }


def to_markdown(meta: dict[str, Any], summary: dict[str, Any], results: list[BriefResult]) -> str:
    s = summary
    lines = [
        f"# Content engine eval — {'FAKE (offline harness check)' if meta['fake'] else meta['provider']} ({meta['date']})",
        "",
        f"Models: writing `{meta['model']}`, review `{meta['fast_model']}`, embeddings `{meta['embedding_model']}`. "
        f"Git `{meta['git']}`. Prompts: "
        + ", ".join(f"`{k}@{v}`" for k, v in meta["prompts"].items())
        + ".",
        "",
        *(
            [
                f"> **PARTIAL RUN.** The provider's quota ran out at `{meta['partial']['at']}`; "
                f"skipped: {', '.join(meta['partial']['skipped']) or 'nothing else'}. "
                f"Provider said: {meta['partial']['reason']}",
                "",
            ]
            if meta.get("partial")
            else []
        ),
        "| Metric | Value |",
        "| --- | --- |",
        f"| Briefs | {s['briefs']} ({s['variants']} variants) |",
        f"| Schema-valid rate | {s['schema_valid_rate']:.0%} |",
        f"| Calls needing the JSON repair retry | {s['repair_rate']:.0%} |",
        f"| Hard platform violations (draft → final) | {s['draft_hard_violations']} → {s['final_hard_violations']} |",
        f"| Soft platform warnings (draft → final) | {s['draft_soft_violations']} → {s['final_soft_violations']} |",
        f"| Variants still blocked after review | {s['variants_blocked']} |",
        f"| Avg critique score before → after revision | {s['avg_score_before']} → {s['avg_score_after']} |",
        f"| Latency per brief (median / max) | {s['latency_p50_s']}s / {s['latency_max_s']}s |",
        f"| Total cost | ${s['total_cost_usd']} over {s['llm_calls']} calls ({s['failed_calls']} failed, {s['unknown_cost_calls']} unknown-price) |",
        "",
        "| Brief | Channel | OK | Before → after | Hard viol. draft → final | Calls | Cost | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        b = [v.score_before for v in r.variants if v.score_before is not None]
        a = [v.score_after for v in r.variants if v.score_after is not None]
        ba = f"{statistics.mean(b):.1f} → {statistics.mean(a):.1f}" if b and a else "—"
        ok = "✓" if r.ok else f"✗ `{r.error_code}`"
        dh = sum(v.draft_hard for v in r.variants)
        fh = sum(v.final_hard for v in r.variants)
        lines.append(
            f"| {r.id} | {r.channel} | {ok} | {ba} | {dh} → {fh} | {r.calls} | ${r.cost_usd:.4f} | {r.latency_s}s |"
        )
    if any(v.final_text for r in results for v in r.variants):
        lines += ["", "## Final texts", ""]
        for r in results:
            for v in r.variants:
                lines += [f"**{r.id} · {v.label} · {v.angle}** (score {v.score_after})", ""]
                lines += ["> " + ln if ln else ">" for ln in v.final_text.splitlines()] + [""]
    lines += [
        "",
        "Scores are the pipeline's own critique model (1-10, averaged over brand voice, clarity, hook, CTA and",
        "platform fit) — a self-assessment, useful for comparing runs, not an independent judgement.",
    ]
    return "\n".join(lines) + "\n"


async def main_async(args: argparse.Namespace) -> Path:
    from launchpad.config import get_settings
    from launchpad.prompts import load_prompt

    if args.fake:
        from evals.fake import install_fake

        install_fake(getattr(args, "fake_quota_calls", None))
        provider, model, fast = "gemini", "fake-writer", "fake-critic"
    else:
        provider = args.provider
        model, fast = resolve_models(provider, args.model, args.fast_model)

    briefs = json.loads((FIXTURES / "briefs.json").read_text(encoding="utf-8"))
    if args.smoke:
        briefs = [b for b in briefs if b.get("smoke")]
        args.suite = "content"
    if args.only:
        wanted = set(args.only.split(","))
        briefs = [b for b in briefs if b["id"] in wanted]
    run_id = datetime.now(UTC).strftime("%H%M%S")
    print(f"Eval {provider}: writing={model} review={fast} briefs={len(briefs)}", flush=True)
    from evals.agent import agent_markdown, load_scenarios, run_scenario

    if args.suite == "agent":
        briefs = []
    scenarios = (
        load_scenarios(set(args.only.split(",")) if args.only else None)
        if args.suite in ("all", "agent")
        else []
    )
    needed = {b["workspace"] for b in briefs} | {s["workspace"] for s in scenarios}
    ws_ids = await setup_workspaces(provider, model, fast, run_id, only=needed)

    results = []
    stopped: dict[str, Any] | None = None  # set when the provider's quota runs out
    for b in briefs:
        if stopped:
            stopped["skipped"].append(b["id"])
            continue
        r = await run_brief(b, ws_ids[b["workspace"]])
        status = "ok" if r.ok else f"FAILED {r.error_code}"
        print(f"  {b['id']:<22} {status:<28} {r.latency_s:>6}s ${r.cost_usd:.4f}", flush=True)
        if r.error_code == "llm_rate_limited":
            stopped = {"at": b["id"], "reason": r.error, "skipped": []}
            print(
                f"  quota exhausted at {b['id']}; stopping and saving partial results", flush=True
            )
            continue  # the brief didn't really run: report it as skipped, not as a model failure
        results.append(r)

    agent_results = []
    for scn in scenarios:
        if stopped:
            stopped["skipped"].append(scn["id"])
            continue
        ar = await run_scenario(scn, ws_ids[scn["workspace"]])
        if ar.error and "llm_rate_limited" in ar.error:
            stopped = {"at": scn["id"], "reason": ar.error, "skipped": []}
            print(
                f"  quota exhausted at {scn['id']}; stopping and saving partial results", flush=True
            )
            continue
        failed = [k for k, v in ar.checks.items() if not v]
        status = "ok" if ar.ok else f"FAILED {','.join(failed)[:40]}"
        print(f"  {scn['id']:<26} {status:<44} {ar.latency_s:>6}s", flush=True)
        agent_results.append(ar)

    meta = {
        "provider": provider, "model": model, "fast_model": fast,
        "embedding_model": get_settings().embedding_model, "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "git": _git_sha(), "fake": bool(args.fake),
        "prompts": {n: load_prompt(n).version for n in (
            "write_content", "critique_content", "agent_planner", "agent_system", "plan_campaign")},
        "suite": "smoke" if args.smoke else args.suite,
        "partial": stopped,
    }  # fmt: skip
    summary = summarise(results)
    out_dir = Path(args.out) / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{'fake' if args.fake else provider}{'-smoke' if args.smoke else ''}-{run_id}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "summary": summary,
                "results": [asdict(r) for r in results],
                "agent": [asdict(a) for a in agent_results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md = to_markdown(meta, summary, results)
    if agent_results:
        md += "\n\n" + agent_markdown(agent_results) + "\n"
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    return out_dir / f"{stem}.md"


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--provider", choices=["gemini", "groq", "openai", "anthropic"], default=None)
    p.add_argument("--model")
    p.add_argument("--fast-model")
    p.add_argument("--only", help="comma-separated brief / scenario ids")
    p.add_argument(
        "--suite",
        choices=["all", "content", "agent"],
        default="all",
        help="content briefs, agent scenarios, or both (default)",
    )
    p.add_argument("--out", default=str(ROOT / "reports"))
    p.add_argument(
        "--fake", action="store_true", help="scripted LLM; validates the harness offline"
    )
    p.add_argument(
        "--smoke", action="store_true", help="quick check: Kadak Tees x 3 content briefs only"
    )
    args = p.parse_args()
    if not args.fake and not args.provider:
        p.error("--provider is required (or --fake)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.platform == "win32":  # LangGraph's psycopg checkpointer can't use the Proactor loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
