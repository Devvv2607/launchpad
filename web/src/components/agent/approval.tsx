"use client";

import { Check, Loader2, Pencil, Undo2, X } from "lucide-react";
import { useState } from "react";

import { AIErrorState } from "@/components/ai-error";
import { ContentEditor, type Content } from "@/components/content/editor";
import { type Brand, ContentPreview } from "@/components/content/previews";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { DraftRef } from "@/lib/agent/events";
import { type Decision, useContentItem, useResumeRun } from "@/lib/api/agent";
import { cn } from "@/lib/utils";

type Choice = { action: Decision["action"]; content?: Content };

function ApprovalCard({
  ws,
  draft,
  brand,
  choice,
  onChoose,
}: {
  ws: string;
  draft: DraftRef;
  brand: Brand;
  choice?: Choice;
  onChoose: (c: Choice | undefined) => void;
}) {
  const item = useContentItem(ws, draft.item_id);
  const [editing, setEditing] = useState(false);
  const content = choice?.content ?? (item.data?.payload as Content | undefined);
  const blocked = draft.blocked || item.data?.blocked;

  return (
    <article
      className={cn(
        "rounded-lg border bg-card p-3",
        choice?.action === "approve" || choice?.action === "edit"
          ? "border-leaf/60"
          : choice?.action === "reject"
            ? "border-rose/40 opacity-70"
            : "",
      )}
      aria-label={`Draft ${draft.label ?? ""} ${draft.angle ?? ""}`}
    >
      <header className="mb-2 flex items-center gap-2">
        {draft.label && (
          <span className="grid size-6 place-items-center rounded-full bg-primary text-xs text-primary-foreground">
            {draft.label}
          </span>
        )}
        <p className="min-w-0 flex-1 truncate text-sm font-medium">{draft.angle ?? "Draft"}</p>
        {choice && (
          <Badge variant="outline" className="capitalize">
            {choice.action === "edit" ? "Edited · approve" : choice.action}
          </Badge>
        )}
      </header>

      {item.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : item.isError ? (
        <AIErrorState error={item.error} onRetry={() => void item.refetch()} />
      ) : editing && content ? (
        <ContentEditor
          channel={draft.channel}
          initial={content}
          saving={false}
          onCancel={() => setEditing(false)}
          onSave={(edited) => {
            onChoose({ action: "edit", content: edited });
            setEditing(false);
          }}
        />
      ) : content ? (
        <div className="max-h-[28rem] overflow-auto">
          <ContentPreview channel={draft.channel} content={content} brand={brand} />
        </div>
      ) : null}

      {blocked && (
        <p className="mt-2 text-xs text-rose">
          Breaks a platform limit, so it can&apos;t be approved as is. Edit it first.
        </p>
      )}

      {!editing && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={choice?.action === "approve" ? "default" : "outline"}
            disabled={!!blocked}
            onClick={() => onChoose({ action: "approve" })}
          >
            <Check aria-hidden /> Approve
          </Button>
          <Button size="sm" variant="outline" disabled={!content} onClick={() => setEditing(true)}>
            <Pencil aria-hidden /> Edit
          </Button>
          <Button
            size="sm"
            variant={choice?.action === "reject" ? "destructive" : "outline"}
            onClick={() => onChoose({ action: "reject" })}
          >
            <X aria-hidden /> Reject
          </Button>
          {choice && (
            <Button size="sm" variant="ghost" onClick={() => onChoose(undefined)}>
              <Undo2 aria-hidden /> Undo
            </Button>
          )}
        </div>
      )}
    </article>
  );
}

export function ApprovalPanel({
  ws,
  runId,
  drafts,
  brand,
}: {
  ws: string;
  runId: string;
  drafts: DraftRef[];
  brand: Brand;
}) {
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const resume = useResumeRun(ws);
  const decided = Object.keys(choices).length;

  function submit() {
    const decisions: Decision[] = Object.entries(choices).map(([item_id, c]) => ({
      item_id,
      action: c.action,
      content: c.action === "edit" ? (c.content ?? null) : null,
    }));
    resume.mutate({ runId, decisions });
  }

  return (
    <section
      aria-labelledby={`approve-${runId}`}
      className="space-y-3 rounded-xl border border-marigold/50 bg-marigold-soft/40 p-4"
    >
      <div>
        <h3 id={`approve-${runId}`} className="font-medium">
          Review {drafts.length} draft{drafts.length === 1 ? "" : "s"}
        </h3>
        <p className="text-sm text-muted-foreground">
          Nothing is published. Approved drafts wait in your queue; anything you don&apos;t decide
          on stays a draft.
        </p>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {drafts.map((d) => (
          <ApprovalCard
            key={d.item_id}
            ws={ws}
            draft={d}
            brand={brand}
            choice={choices[d.item_id]}
            onChoose={(c) =>
              setChoices((prev) => {
                const next = { ...prev };
                if (c) next[d.item_id] = c;
                else delete next[d.item_id];
                return next;
              })
            }
          />
        ))}
      </div>
      {resume.isError && <AIErrorState error={resume.error} />}
      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={decided === 0 || resume.isPending}>
          {resume.isPending && <Loader2 className="animate-spin" aria-hidden />}
          Submit {decided || ""} decision{decided === 1 ? "" : "s"}
        </Button>
        <span className="text-sm text-muted-foreground">
          {decided}/{drafts.length} decided
        </span>
      </div>
    </section>
  );
}
