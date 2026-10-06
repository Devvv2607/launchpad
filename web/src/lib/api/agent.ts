"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "./client";

export type Run = Schemas["RunOut"];
export type RunDetail = Schemas["RunDetailOut"];
export type Decision = Schemas["DecisionIn"];

export const qkAgent = {
  runs: (ws: string, thread: string | undefined, limit: number) =>
    ["workspaces", ws, "agent", "runs", thread ?? "all", limit] as const,
  run: (ws: string, run: string) => ["workspaces", ws, "agent", "run", run] as const,
  item: (ws: string, item: string) => ["workspaces", ws, "content", "item", item] as const,
};

export function useRuns(
  ws: string,
  opts: { thread?: string; limit?: number; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: qkAgent.runs(ws, opts.thread, opts.limit ?? 30),
    enabled: opts.enabled ?? true,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/agent/runs", {
          params: {
            path: { workspace_id: ws },
            query: { thread_id: opts.thread, limit: opts.limit ?? 30 },
          },
        }),
      ),
  });
}

/** Full event log of a finished run (for replay). Active runs are followed via the stream. */
export function useRunDetail(ws: string, runId: string, enabled = true) {
  return useQuery({
    queryKey: qkAgent.run(ws, runId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/agent/runs/{run_id}", {
          params: { path: { workspace_id: ws, run_id: runId } },
        }),
      ),
  });
}

export function useContentItem(ws: string, itemId: string) {
  return useQuery({
    queryKey: qkAgent.item(ws, itemId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/content/{item_id}", {
          params: { path: { workspace_id: ws, item_id: itemId } },
        }),
      ),
  });
}

export function useStartRun(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    // `key` identifies one user action; a repeat of the same request returns the same run.
    mutationFn: ({ body, key }: { body: Schemas["RunCreateIn"]; key: string }) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/agent/runs", {
          params: { path: { workspace_id: ws }, header: { "idempotency-key": key } },
          body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces", ws, "agent", "runs"] }),
  });
}

export function useResumeRun(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, decisions }: { runId: string; decisions: Decision[] }) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/agent/runs/{run_id}/resume", {
          params: { path: { workspace_id: ws, run_id: runId } },
          body: { decisions },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces", ws, "agent", "runs"] }),
  });
}

export function useCancelRun(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/agent/runs/{run_id}/cancel", {
          params: { path: { workspace_id: ws, run_id: runId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces", ws, "agent", "runs"] }),
  });
}

export const runStreamUrl = (ws: string, runId: string, after: number) =>
  `/api/v1/workspaces/${ws}/agent/runs/${runId}/stream?after=${after}`;
