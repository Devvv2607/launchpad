"use client";

import { Bot, History, Loader2, MessageSquarePlus, SearchX, Send, Square } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AIErrorState } from "@/components/ai-error";
import { RunTurn } from "@/components/agent/run-turn";
import { Timeline } from "@/components/agent/timeline";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import type { RunView } from "@/lib/agent/events";
import { starterPrompts } from "@/lib/agent/starters";
import { type Run, useCancelRun, useRuns, useStartRun } from "@/lib/api/agent";
import { useBrandKit, useWorkspace } from "@/lib/api/hooks";
import { useHydrated } from "@/lib/use-hydrated";

const ACTIVE = new Set(["running", "awaiting_approval"]);
const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  awaiting_approval: "Needs review",
  completed: "Done",
  failed: "Failed",
  cancelled: "Stopped",
};

function HistorySheet({ ws, current }: { ws: string; current?: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const runs = useRuns(ws, { limit: 100 });
  // One row per conversation: newest activity first, titled by its first message.
  const threads = useMemo(() => {
    const byThread = new Map<string, Run[]>();
    for (const r of runs.data ?? [])
      byThread.set(r.thread_id, [...(byThread.get(r.thread_id) ?? []), r]);
    return [...byThread.entries()].map(([id, rs]) => ({
      id,
      latest: rs[0],
      first: rs[rs.length - 1],
      count: rs.length,
    }));
  }, [runs.data]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline">
          <History aria-hidden /> History
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Conversations</SheetTitle>
          <SheetDescription>Every run is saved with each step it took.</SheetDescription>
        </SheetHeader>
        <div className="space-y-1 overflow-y-auto px-4 pb-6">
          {runs.isPending ? (
            <ListSkeleton rows={5} />
          ) : runs.isError ? (
            <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
          ) : threads.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">No conversations yet.</p>
          ) : (
            threads.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  router.push(`/w/${ws}/agent?thread=${encodeURIComponent(t.id)}`);
                  setOpen(false);
                }}
                className="flex w-full flex-col gap-1 rounded-lg border p-3 text-left hover:bg-muted/60 aria-[current=true]:border-primary"
                aria-current={t.id === current}
              >
                <span className="line-clamp-2 text-sm font-medium">
                  {t.first.title ?? t.first.input}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant={t.latest.status === "awaiting_approval" ? "default" : "outline"}>
                    {STATUS_LABEL[t.latest.status] ?? t.latest.status}
                  </Badge>
                  {new Date(t.latest.created_at).toLocaleString("en-IN", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                  {t.count > 1 && <span>· {t.count} messages</span>}
                </span>
              </button>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function AgentChat() {
  const { workspaceId: ws } = useParams<{ workspaceId: string }>();
  const router = useRouter();
  const thread = useSearchParams().get("thread") ?? undefined;
  const hydrated = useHydrated();
  const workspace = useWorkspace(ws);
  const kit = useBrandKit(ws);
  const runs = useRuns(ws, { thread, limit: 50, enabled: !!thread });
  const start = useStartRun(ws);
  const cancel = useCancelRun(ws);
  const [message, setMessage] = useState("");
  const [views, setViews] = useState<Record<string, { view: RunView; reconnecting: boolean }>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const ordered = useMemo(
    () =>
      thread ? [...(runs.data ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at)) : [],
    [runs.data, thread],
  );
  const latest = ordered.at(-1);
  const latestStatus = latest ? (views[latest.id]?.view.status ?? latest.status) : undefined;
  const busy =
    latestStatus === "running" ||
    latestStatus === "awaiting_approval" ||
    (latest ? ACTIVE.has(latest.status) && !views[latest.id] : false);
  const shown = (selected && views[selected]) || (latest && views[latest.id]);

  const onView = useCallback((id: string, view: RunView, reconnecting: boolean) => {
    setViews((prev) =>
      prev[id]?.view === view && prev[id]?.reconnecting === reconnecting
        ? prev
        : { ...prev, [id]: { view, reconnecting } },
    );
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [ordered.length]);

  const brand = {
    name: workspace.data?.name ?? "Your business",
    logoUrl: kit.data?.logo_url,
    primary: kit.data?.primary_color,
  };

  function send(text: string) {
    const msg = text.trim();
    if (msg.length < 2 || busy) return;
    start.mutate(
      { message: msg, thread_id: thread ?? null },
      {
        onSuccess: (run) => {
          setMessage("");
          setSelected(run.id);
          if (!thread) router.replace(`/w/${ws}/agent?thread=${encodeURIComponent(run.thread_id)}`);
        },
      },
    );
  }

  return (
    <>
      <PageHeader
        title="Agent"
        description="Ask for campaigns, research or drafts. You review everything it writes; nothing is published without you."
        actions={
          <>
            <HistorySheet ws={ws} current={thread} />
            <Button
              variant="outline"
              onClick={() => {
                setSelected(null);
                router.push(`/w/${ws}/agent`);
              }}
              disabled={!thread}
            >
              <MessageSquarePlus aria-hidden /> New chat
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-label="Conversation" className="flex min-h-[60vh] flex-col gap-6">
          <div className="flex-1 space-y-8">
            {!thread ? (
              <EmptyState icon={Bot} title="What should we work on?">
                <div className="mt-4 flex flex-col gap-2">
                  {starterPrompts(workspace.data?.industry).map((p) => (
                    <Button
                      key={p}
                      variant="outline"
                      className="h-auto justify-start py-2 text-left whitespace-normal"
                      disabled={!hydrated || start.isPending}
                      onClick={() => send(p)}
                    >
                      {p}
                    </Button>
                  ))}
                </div>
              </EmptyState>
            ) : runs.isPending ? (
              <ListSkeleton rows={3} />
            ) : runs.isError ? (
              <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
            ) : ordered.length === 0 ? (
              <EmptyState icon={SearchX} title="Conversation not found">
                It may belong to another workspace. Start a new chat instead.
              </EmptyState>
            ) : (
              ordered.map((r) => (
                <RunTurn
                  key={r.id}
                  ws={ws}
                  run={r}
                  brand={brand}
                  onView={onView}
                  selected={!!selected && selected === r.id && ordered.length > 1}
                  onSelect={() => setSelected(r.id)}
                />
              ))
            )}
            <div ref={bottom} />
          </div>

          <form
            className="sticky bottom-0 space-y-2 rounded-xl border bg-background p-3 shadow-sm"
            onSubmit={(e) => {
              e.preventDefault();
              send(message);
            }}
          >
            {start.isError && <AIErrorState error={start.error} />}
            {cancel.isError && <AIErrorState error={cancel.error} />}
            <label htmlFor="agent-message" className="sr-only">
              Message the agent
            </label>
            <Textarea
              id="agent-message"
              rows={2}
              value={message}
              disabled={!hydrated}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(message);
                }
              }}
              placeholder={
                latestStatus === "awaiting_approval"
                  ? "Review the drafts above first, or stop this run."
                  : "e.g. Plan a 1-week Instagram + email campaign for our new launch"
              }
            />
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                Enter to send · Shift+Enter for a new line
              </p>
              {busy && latest ? (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => cancel.mutate(latest.id)}
                  disabled={cancel.isPending}
                >
                  {cancel.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <Square aria-hidden />
                  )}
                  Stop
                </Button>
              ) : (
                <Button type="submit" disabled={message.trim().length < 2 || start.isPending}>
                  {start.isPending ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <Send aria-hidden />
                  )}
                  Send
                </Button>
              )}
            </div>
          </form>
        </section>

        <aside aria-label="Run steps" className="lg:sticky lg:top-6 lg:self-start">
          <div className="rounded-xl border bg-card p-4">
            <h2 className="mb-3 font-medium">Steps</h2>
            {shown ? (
              <Timeline view={shown.view} reconnecting={shown.reconnecting} />
            ) : (
              <p className="text-sm text-muted-foreground">
                The plan, every tool call and research sources show up here as the agent works.
              </p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

export default function AgentPage() {
  return (
    <Suspense fallback={<ListSkeleton rows={3} />}>
      <AgentChat />
    </Suspense>
  );
}
