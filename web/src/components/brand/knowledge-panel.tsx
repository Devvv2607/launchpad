"use client";

import {
  AlertTriangle,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";

import { AIErrorState } from "@/components/ai-error";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Schemas } from "@/lib/api/client";
import {
  useBrandDocs,
  useBrandIndex,
  useDeleteDoc,
  useImportUrl,
  useReindexAll,
  useReindexDoc,
  useRetrieval,
  useUploadDoc,
} from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

const STATUS: Record<Schemas["DocumentStatus"], { label: string; className: string }> = {
  pending: { label: "Queued", className: "bg-muted text-muted-foreground" },
  processing: { label: "Processing", className: "bg-marigold-soft text-foreground" },
  ready: { label: "Ready", className: "bg-leaf-soft text-leaf" },
  failed: { label: "Failed", className: "bg-rose-soft text-rose" },
};

function size(bytes: number | null | undefined) {
  if (!bytes) return null;
  return bytes > 1_048_576
    ? `${(bytes / 1_048_576).toFixed(1)} MB`
    : `${Math.ceil(bytes / 1024)} KB`;
}

export function KnowledgePanel({ workspaceId }: { workspaceId: string }) {
  const docs = useBrandDocs(workspaceId);
  const index = useBrandIndex(workspaceId);
  const upload = useUploadDoc(workspaceId);
  const importUrl = useImportUrl(workspaceId);
  const reindexAll = useReindexAll(workspaceId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");

  async function uploadFiles(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      await upload.mutateAsync(file).catch(() => undefined); // error shown below
    }
  }

  return (
    <div className="space-y-8">
      {index.data?.needs_reindex && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-marigold/40 bg-marigold-soft px-5 py-4">
          <AlertTriangle className="size-4 text-foreground" aria-hidden />
          <p className="flex-1 text-sm">
            <span className="font-medium">Re-index needed.</span> {index.data.stale_documents}{" "}
            document{index.data.stale_documents === 1 ? " was" : "s were"} indexed with a different
            embedding model than <code>{index.data.configured_model ?? "the configured one"}</code>,
            so {index.data.stale_documents === 1 ? "it's" : "they're"} skipped when writing.
          </p>
          <Button
            size="sm"
            variant="outline"
            disabled={reindexAll.isPending}
            onClick={() => reindexAll.mutate()}
          >
            <RefreshCw
              className={cn("size-4", reindexAll.isPending && "animate-spin")}
              aria-hidden
            />
            Re-index now
          </Button>
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-dashed bg-card p-5">
          <p className="font-medium">Upload documents</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Menus, brand guidelines, FAQs, price lists. PDF, DOCX, TXT or Markdown up to 20 MB.
          </p>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.markdown"
            className="sr-only"
            aria-label="Brand documents"
            onChange={(e) => {
              void uploadFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <Button
            className="mt-4"
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
          >
            {upload.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <Upload className="size-4" aria-hidden />
            )}
            {upload.isPending ? "Uploading…" : "Choose files"}
          </Button>
        </div>
        <form
          className="rounded-lg border border-dashed bg-card p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (url.trim()) importUrl.mutate(url.trim(), { onSuccess: () => setUrl("") });
          }}
        >
          <label htmlFor="brand-url" className="font-medium">
            Import your website
          </label>
          <p className="mt-1 text-sm text-muted-foreground">
            We read the homepage and up to 10 pages on the same site, respecting robots.txt.
          </p>
          <div className="mt-4 flex gap-2">
            <Input
              id="brand-url"
              type="url"
              placeholder="https://yourbusiness.in"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <Button type="submit" variant="outline" disabled={importUrl.isPending || !url.trim()}>
              {importUrl.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Globe className="size-4" aria-hidden />
              )}
              Import
            </Button>
          </div>
        </form>
      </section>
      {upload.error && <ErrorState error={upload.error} />}
      {importUrl.error && <ErrorState error={importUrl.error} />}

      <section>
        <h3 className="mb-3 font-heading text-base font-semibold">Documents</h3>
        {docs.error ? (
          <ErrorState error={docs.error} onRetry={() => docs.refetch()} />
        ) : docs.isLoading ? (
          <ListSkeleton rows={2} />
        ) : !docs.data?.length ? (
          <EmptyState icon={FileText} title="No brand documents yet">
            Add a menu, a brand guide or your website. The agent quotes facts from these instead of
            guessing prices, dates or offers.
          </EmptyState>
        ) : (
          <ul className="divide-y rounded-lg border bg-card">
            {docs.data.map((d) => (
              <DocRow key={d.id} doc={d} workspaceId={workspaceId} />
            ))}
          </ul>
        )}
      </section>

      <RetrievalTester
        workspaceId={workspaceId}
        disabled={!docs.data?.some((d) => d.status === "ready")}
      />
    </div>
  );
}

function DocRow({ doc, workspaceId }: { doc: Schemas["BrandDocumentOut"]; workspaceId: string }) {
  const del = useDeleteDoc(workspaceId);
  const reindex = useReindexDoc(workspaceId);
  const s = STATUS[doc.status];
  const busy = doc.status === "pending" || doc.status === "processing";
  return (
    <li className="flex flex-wrap items-start gap-3 p-4">
      {doc.source_type === "url" ? (
        <Globe className="mt-0.5 size-4 text-muted-foreground" aria-hidden />
      ) : (
        <FileText className="mt-0.5 size-4 text-muted-foreground" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-medium">{doc.filename}</span>
          <Badge variant="outline" className={s.className}>
            {busy && <Loader2 className="size-3 animate-spin" aria-hidden />}
            {s.label}
          </Badge>
          {doc.needs_reindex && (
            <Badge variant="outline" className="bg-marigold-soft text-foreground">
              Re-index needed
            </Badge>
          )}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[
            doc.status === "ready" && `${doc.chunk_count} passages`,
            size(doc.size_bytes),
            doc.embedding_model,
            new Date(doc.created_at).toLocaleDateString(),
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {doc.error && (
          <p
            className={cn(
              "mt-1 text-sm",
              doc.status === "failed" ? "text-rose" : "text-muted-foreground",
            )}
          >
            {doc.error}
          </p>
        )}
      </div>
      <div className="flex gap-1">
        {(doc.status === "failed" || doc.needs_reindex) && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => reindex.mutate(doc.id)}
            disabled={reindex.isPending}
          >
            <RefreshCw className="size-4" aria-hidden /> Retry
          </Button>
        )}
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`Delete ${doc.filename}`}
          onClick={() => del.mutate(doc.id)}
          disabled={del.isPending}
        >
          <Trash2 className="size-4" aria-hidden />
        </Button>
      </div>
    </li>
  );
}

function RetrievalTester({ workspaceId, disabled }: { workspaceId: string; disabled: boolean }) {
  const search = useRetrieval(workspaceId);
  const [q, setQ] = useState("");
  return (
    <section className="space-y-3">
      <div>
        <h3 className="font-heading text-base font-semibold">Test retrieval</h3>
        <p className="text-sm text-muted-foreground">
          Ask a question to see exactly which passages the writer would get, and how closely they
          match.
        </p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) search.mutate(q.trim());
        }}
      >
        <Input
          aria-label="Question"
          placeholder={disabled ? "Add a document first" : "e.g. What's on the monsoon menu?"}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          disabled={disabled}
        />
        <Button
          type="submit"
          variant="outline"
          disabled={disabled || search.isPending || q.trim().length < 2}
        >
          {search.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Search className="size-4" aria-hidden />
          )}
          Search
        </Button>
      </form>
      {search.error && <AIErrorState error={search.error} />}
      {search.data && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {search.data.chunks.length} match{search.data.chunks.length === 1 ? "" : "es"} above{" "}
            {search.data.min_score} similarity
            {search.data.dropped_below_threshold > 0 &&
              ` · ${search.data.dropped_below_threshold} weaker passage${search.data.dropped_below_threshold === 1 ? "" : "s"} left out`}
          </p>
          {search.data.chunks.length === 0 ? (
            <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
              Nothing in your documents answers that. The writer won&apos;t invent it either.
            </p>
          ) : (
            <ol className="space-y-2">
              {search.data.chunks.map((c, i) => (
                <li key={c.chunk_id} className="rounded-lg border bg-card p-4">
                  <div className="mb-2 flex items-center gap-3 text-xs">
                    <span className="font-medium">#{i + 1}</span>
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted" aria-hidden>
                      <div
                        className="h-full bg-leaf"
                        style={{ width: `${Math.round(c.score * 100)}%` }}
                      />
                    </div>
                    <span className="tabular-nums">{c.score.toFixed(2)}</span>
                    <span className="truncate text-muted-foreground">
                      {c.source}
                      {c.page ? ` · p.${c.page}` : ""}
                      {c.heading ? ` · ${c.heading}` : ""}
                    </span>
                  </div>
                  <p className="text-sm whitespace-pre-line">{c.content}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
