"use client";

import { AlertTriangle, Check, ChevronDown, Copy, Loader2, Pencil, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AIErrorState } from "@/components/ai-error";
import { ContentEditor } from "@/components/content/editor";
import { type Brand, ContentPreview, contentText } from "@/components/content/previews";
import { ErrorState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Schemas } from "@/lib/api/client";
import { useEditContent, useRegenerate } from "@/lib/api/hooks";
import { diffWords } from "@/lib/text";
import { cn } from "@/lib/utils";

type Item = Schemas["ContentItemOut"];
type Iteration = {
  round: number;
  content: Record<string, unknown>;
  scores?: Record<string, number> | null;
  issues?: string[];
};
type Violation = { rule: string; severity: string; message: string };

// Quality checks that survived review: not blocking, but a human should look before approving.
const FACT_RULES = new Set(["unsupported_fact", "critic_added_facts"]);

const SCORE_LABELS: [string, string][] = [
  ["brand_voice", "Brand voice"],
  ["clarity", "Clarity"],
  ["hook", "Hook"],
  ["cta", "Call to action"],
  ["platform_fit", "Platform fit"],
];

function ScoreBars({ scores, title }: { scores: Record<string, number>; title: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      {SCORE_LABELS.map(([key, label]) => {
        const v = scores[key] ?? 0;
        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-24 shrink-0 text-muted-foreground">{label}</span>
            <div
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
              role="img"
              aria-label={`${label} ${v} out of 10`}
            >
              <div
                className={cn(
                  "h-full rounded-full",
                  v >= 8 ? "bg-leaf" : v >= 6 ? "bg-marigold" : "bg-rose",
                )}
                style={{ width: `${v * 10}%` }}
              />
            </div>
            <span className="w-4 text-right tabular-nums">{v}</span>
          </div>
        );
      })}
    </div>
  );
}

function Diff({ before, after }: { before: string; after: string }) {
  const parts = diffWords(before, after);
  if (!parts.some((p) => p.kind !== "same"))
    return <p className="text-xs text-muted-foreground">No changes after review.</p>;
  return (
    <p className="rounded-md border bg-muted/40 p-3 text-xs leading-relaxed whitespace-pre-wrap">
      {parts.map((p, i) =>
        p.kind === "same" ? (
          <span key={i}>{p.text}</span>
        ) : p.kind === "added" ? (
          <ins key={i} className="bg-leaf-soft text-leaf no-underline">
            {p.text}
          </ins>
        ) : (
          <del key={i} className="bg-rose-soft text-rose">
            {p.text}
          </del>
        ),
      )}
    </p>
  );
}

export function VariantCard({
  workspaceId,
  channel,
  label,
  angle,
  content,
  item,
  brand,
  pending,
}: {
  workspaceId: string;
  channel: string;
  label: string;
  angle: string;
  content: Record<string, unknown>;
  item?: Item;
  brand: Brand;
  pending?: boolean; // still being reviewed (streaming)
}) {
  const [editing, setEditing] = useState(false);
  const edit = useEditContent(workspaceId);
  const regen = useRegenerate(workspaceId);
  const [current, setCurrent] = useState<Item | undefined>(item);
  const shown = current ?? item;
  const data = (shown?.payload as Record<string, unknown> | undefined) ?? content;
  const iterations = ((shown?.generation as { iterations?: Iteration[] } | undefined)?.iterations ??
    []) as Iteration[];
  const scored = iterations.filter((it) => it.scores);
  const first = scored[0]?.scores;
  const latest = scored[scored.length - 1]?.scores;
  const issues = scored[0]?.issues ?? [];
  const violations = (shown?.violations ?? []) as Violation[];
  const blocked = shown?.blocked ?? false;
  const factFlag = violations.some((v) => FACT_RULES.has(v.rule));
  const needsLook = violations.some((v) => v.severity !== "error");
  const original = iterations[0]?.content;

  async function copy() {
    await navigator.clipboard.writeText(contentText(channel, data));
    toast.success("Copied to clipboard");
  }

  return (
    <article className="flex flex-col gap-4 rounded-xl border bg-card p-4 shadow-xs">
      <header className="flex flex-wrap items-center gap-2">
        <span className="grid size-6 place-items-center rounded-full bg-primary font-heading text-xs font-semibold text-primary-foreground">
          {label}
        </span>
        <p className="min-w-0 flex-1 truncate font-medium">{shown?.title ?? angle}</p>
        {pending ? (
          <Badge variant="outline" className="gap-1">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Reviewing
          </Badge>
        ) : blocked ? (
          <Badge variant="outline" className="bg-rose-soft text-rose">
            Can&apos;t publish yet
          </Badge>
        ) : shown && (factFlag || needsLook) ? (
          <Badge variant="outline" className="bg-marigold-soft text-marigold">
            <AlertTriangle className="size-3" aria-hidden />{" "}
            {factFlag ? "Check facts" : "Needs a look"}
          </Badge>
        ) : shown ? (
          <Badge variant="outline" className="bg-leaf-soft text-leaf">
            <Check className="size-3" aria-hidden /> Saved draft
          </Badge>
        ) : null}
      </header>

      {editing && shown ? (
        <ContentEditor
          channel={channel}
          initial={data}
          saving={edit.isPending}
          onCancel={() => setEditing(false)}
          onSave={(c) =>
            edit.mutate(
              { itemId: shown.id, content: c },
              {
                onSuccess: (updated) => {
                  setCurrent(updated);
                  setEditing(false);
                  toast.success(
                    updated.blocked
                      ? "Saved — fix the flagged limits before publishing"
                      : "Saved draft",
                  );
                },
              },
            )
          }
        />
      ) : (
        <ContentPreview channel={channel} content={data} brand={brand} />
      )}
      {edit.error && <ErrorState error={edit.error} />}
      {regen.error && (
        <AIErrorState error={regen.error} onRetry={() => shown && regen.mutate(shown.id)} />
      )}

      {violations.length > 0 && (
        <ul className="space-y-1 text-xs">
          {violations.map((v, i) => (
            <li
              key={i}
              className={cn(
                "flex items-start gap-1.5",
                v.severity === "error" ? "text-rose" : "text-marigold",
              )}
            >
              <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
              {v.message}
            </li>
          ))}
        </ul>
      )}

      {latest && (
        <div className="grid gap-4 sm:grid-cols-2">
          <ScoreBars
            scores={latest}
            title={scored.length > 1 ? `Review, round ${scored.length}` : "Review"}
          />
          {first && scored.length > 1 ? (
            <ScoreBars scores={first} title="First draft" />
          ) : (
            issues.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">Reviewer notes</p>
                <ul className="list-disc space-y-1 pl-4 text-xs">
                  {issues.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            )
          )}
        </div>
      )}

      {original && iterations.length > 1 && (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1 text-sm font-medium hover:underline">
            <ChevronDown
              className="size-4 transition-transform group-data-[state=open]:rotate-180"
              aria-hidden
            />
            What changed after review
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2">
            <Diff
              before={contentText(channel, original)}
              after={contentText(channel, iterations[iterations.length - 1].content)}
            />
            {issues.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {issues.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            )}
          </CollapsibleContent>
        </Collapsible>
      )}

      {shown && !editing && (
        <footer className="mt-auto flex flex-wrap gap-2 border-t pt-3">
          <Button size="sm" variant="outline" onClick={copy}>
            <Copy className="size-3.5" /> Copy
          </Button>
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" /> Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={regen.isPending}
            onClick={() =>
              regen.mutate(shown.id, {
                onSuccess: (u) => {
                  setCurrent(u);
                  toast.success(`Variant ${label} regenerated`);
                },
              })
            }
          >
            <RefreshCw className={cn("size-3.5", regen.isPending && "animate-spin")} />
            {regen.isPending ? "Regenerating…" : "Regenerate this variant"}
          </Button>
        </footer>
      )}
    </article>
  );
}
