"use client";

import { Bot, Loader2, Square } from "lucide-react";
import { useEffect } from "react";

import { ApprovalPanel } from "@/components/agent/approval";
import type { Brand } from "@/components/content/previews";
import { Badge } from "@/components/ui/badge";
import { type RunView, replyText } from "@/lib/agent/events";
import { useRunView } from "@/lib/agent/use-run-view";
import type { Run } from "@/lib/api/agent";
import { cn } from "@/lib/utils";

const OUTCOME_NOTES: Record<string, string> = {
  tool_cap: "Stopped at this run's tool-call limit.",
  budget_exceeded: "Stopped at this run's token/cost budget.",
  cancelled: "Stopped by you. Drafts it had already written stay as drafts.",
  failed: "This run failed.",
};

/** Turns [n] markers into links to the run's research sources. */
function withCitations(text: string, view: RunView) {
  const sources = view.sources.flatMap((s) => s.sources);
  if (!sources.length) return text;
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const m = /^\[(\d+)\]$/.exec(part);
    const src = m ? sources[Number(m[1]) - 1] : undefined;
    return src ? (
      <a
        key={i}
        href={src.url}
        target="_blank"
        rel="noopener noreferrer"
        title={src.title}
        className="text-primary underline-offset-2 hover:underline"
      >
        {part}
      </a>
    ) : (
      part
    );
  });
}

export function RunTurn({
  ws,
  run,
  brand,
  onView,
  selected,
  onSelect,
}: {
  ws: string;
  run: Run;
  brand: Brand;
  onView: (runId: string, view: RunView, reconnecting: boolean) => void;
  selected: boolean;
  onSelect: () => void;
}) {
  const { view, reconnecting } = useRunView(ws, run.id);
  useEffect(() => onView(run.id, view, reconnecting), [run.id, view, reconnecting, onView]);

  const reply = replyText(view);
  const working = view.status === "running";
  const note =
    OUTCOME_NOTES[view.outcome ?? ""] ?? (view.status === "failed" ? OUTCOME_NOTES.failed : null);

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 whitespace-pre-wrap text-primary-foreground">
          {run.input}
        </p>
      </div>

      <div
        className={cn(
          "flex gap-3 rounded-xl p-1 transition-colors",
          selected && "bg-muted/40 ring-1 ring-border",
        )}
      >
        <span className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-muted">
          <Bot className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <button
            type="button"
            onClick={onSelect}
            className="block w-full text-left"
            aria-label="Show this run's steps in the timeline"
          >
            {reply ? (
              <p className="leading-relaxed whitespace-pre-wrap">{withCitations(reply, view)}</p>
            ) : working ? (
              <p className="flex items-center gap-2 text-muted-foreground" role="status">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                {view.thinking ?? "Starting…"}
              </p>
            ) : null}
          </button>

          {note && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Square className="size-3" aria-hidden /> {note}
            </p>
          )}
          {view.error && !working && (
            <p className="text-sm text-rose" role="alert">
              {view.error.message} {view.error.hint}
            </p>
          )}

          {view.status === "awaiting_approval" && view.approval?.length ? (
            <ApprovalPanel ws={ws} runId={run.id} drafts={view.approval} brand={brand} />
          ) : view.drafts.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {view.drafts.map((d) => (
                <Badge key={d.item_id} variant="secondary" className="max-w-full truncate">
                  {d.label ? `${d.label} · ` : ""}
                  {d.angle ?? d.channel}
                </Badge>
              ))}
              {view.applied && (
                <span className="text-sm text-muted-foreground">
                  {view.applied.approved} approved · {view.applied.rejected} rejected ·{" "}
                  {view.applied.edited} edited
                </span>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
