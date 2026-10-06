"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Circle,
  ExternalLink,
  Loader2,
  XCircle,
} from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { RunView, ToolStep } from "@/lib/agent/events";
import { cn } from "@/lib/utils";

export const TOOL_LABELS: Record<string, string> = {
  get_brand_context: "Read the brand kit",
  research_trends: "Researched trends",
  plan_campaign: "Planned the calendar",
  write_content: "Wrote drafts",
  critique_content: "Reviewed a draft",
  suggest_hashtags: "Chose hashtags",
  build_email: "Built an email",
  get_analytics: "Checked analytics",
  generate_image: "Image generation",
  create_poster: "Poster rendering",
  schedule_content: "Scheduling",
  respond: "Reply",
};

const toolLabel = (t: string) => TOOL_LABELS[t] ?? t;

function StatusIcon({ status }: { status: string }) {
  if (status === "done" || status === "ok")
    return <CheckCircle2 className="size-4 shrink-0 text-leaf" aria-label="Done" />;
  if (status === "failed" || status === "error")
    return <XCircle className="size-4 shrink-0 text-rose" aria-label="Failed" />;
  if (status === "running")
    return <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-label="Running" />;
  return <Circle className="size-4 shrink-0 text-muted-foreground/50" aria-label="Pending" />;
}

function ToolRow({ step }: { step: ToolStep }) {
  const input = Object.keys(step.input).length ? JSON.stringify(step.input, null, 1) : null;
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted/60">
        <StatusIcon status={step.status} />
        <span className="min-w-0 flex-1 truncate">{toolLabel(step.tool)}</span>
        {step.durationMs !== undefined && (
          <span className="text-xs text-muted-foreground tabular-nums">
            {(step.durationMs / 1000).toFixed(1)}s
          </span>
        )}
        <ChevronDown
          className="size-3.5 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
          aria-hidden
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 px-2 pb-2 pl-8 text-xs">
        {input && (
          <div>
            <p className="font-medium text-muted-foreground">Input</p>
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted/60 p-2 whitespace-pre-wrap">
              {input}
            </pre>
          </div>
        )}
        {step.output && (
          <div>
            <p className="font-medium text-muted-foreground">Result</p>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted/60 p-2 whitespace-pre-wrap">
              {step.output}
            </pre>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function Timeline({ view, reconnecting }: { view: RunView; reconnecting?: boolean }) {
  const active = view.status === "running";
  return (
    <div className="space-y-6 text-sm">
      {reconnecting && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Reconnecting… the run keeps going
          on the server.
        </p>
      )}

      {view.plan.length > 0 && (
        <section aria-labelledby="tl-plan">
          <h3 id="tl-plan" className="mb-2 text-xs font-medium text-muted-foreground uppercase">
            Plan
          </h3>
          {view.goal && <p className="mb-2 text-foreground/80">{view.goal}</p>}
          <ol className="space-y-1.5">
            {view.plan.map((s) => (
              <li key={s.id} className="flex items-start gap-2">
                <span className="mt-0.5">
                  <StatusIcon status={s.status} />
                </span>
                <span className={cn(s.status === "done" && "text-muted-foreground")}>
                  {s.title}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {(view.tools.length > 0 || (active && view.thinking)) && (
        <section aria-labelledby="tl-steps">
          <h3 id="tl-steps" className="mb-1 text-xs font-medium text-muted-foreground uppercase">
            Steps
          </h3>
          <div className="-mx-2">
            {view.tools.map((t) => (
              <ToolRow key={t.id} step={t} />
            ))}
          </div>
          {active && view.thinking && (
            <p className="mt-1 flex items-center gap-2 text-muted-foreground" role="status">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> {view.thinking}
            </p>
          )}
        </section>
      )}

      {view.sources.some((s) => s.sources.length) && (
        <section aria-labelledby="tl-sources">
          <h3 id="tl-sources" className="mb-2 text-xs font-medium text-muted-foreground uppercase">
            Sources
          </h3>
          <ol className="space-y-1.5">
            {view.sources
              .flatMap((s) => s.sources)
              .map((s, i) => (
                <li key={`${s.url}-${i}`} className="flex gap-2">
                  <span className="text-muted-foreground tabular-nums">[{i + 1}]</span>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-w-0 items-center gap-1 text-primary underline-offset-2 hover:underline"
                  >
                    <span className="truncate">{s.title}</span>
                    <ExternalLink className="size-3 shrink-0" aria-hidden />
                  </a>
                </li>
              ))}
          </ol>
        </section>
      )}

      {view.error && (
        <p className="flex items-start gap-2 text-rose" role="alert">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {view.error.message}
            {view.error.hint && <span className="block text-foreground/70">{view.error.hint}</span>}
          </span>
        </p>
      )}

      {!active && view.costUsd !== undefined && (
        <p className="text-xs text-muted-foreground tabular-nums">
          {view.tools.length} tool call{view.tools.length === 1 ? "" : "s"} ·{" "}
          {(view.tokens ?? 0).toLocaleString("en-IN")} tokens ·{" "}
          {view.costComplete === false
            ? Number(view.costUsd) > 0
              ? `at least $${Number(view.costUsd).toFixed(4)} (some model prices unknown)`
              : "cost unknown (model price not listed)"
            : `$${Number(view.costUsd).toFixed(4)}`}
        </p>
      )}
    </div>
  );
}
