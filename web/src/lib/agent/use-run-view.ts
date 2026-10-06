"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/lib/api/client";
import { runStreamUrl } from "@/lib/api/agent";
import { getSSE } from "@/lib/api/stream";

import { applyEvent, emptyRun, type RunView } from "./events";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });

/**
 * Follows one run: replays its event log from the start, then live events, reconnecting from the
 * last seen event after network drops or an API restart. Stops once the run is over.
 * Mount with `key={runId}` so a new run starts from a clean view.
 */
export function useRunView(ws: string, runId: string) {
  const qc = useQueryClient();
  const [view, setView] = useState<RunView>(emptyRun);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    let last = 0;
    let failures = 0;

    async function follow() {
      while (!ctrl.signal.aborted) {
        let finished = false;
        try {
          await getSSE(
            runStreamUrl(ws, runId, last),
            (type, data, id) => {
              if (id !== null) last = Math.max(last, id);
              setView((v) => applyEvent(v, type, data as Record<string, unknown>, id));
              if (type === "run_finished") finished = true;
              if (type === "approval_required" || type === "run_finished")
                void qc.invalidateQueries({ queryKey: ["workspaces", ws, "agent", "runs"] });
            },
            ctrl.signal,
            () => {
              failures = 0;
              setReconnecting(false);
            },
          );
          if (finished) return;
          // The server closed without run_finished: the run ended some other way (e.g. cancelled
          // before it started) or the stream hit its max duration. Check before reconnecting.
          const run = await unwrap(
            api.GET("/api/v1/workspaces/{workspace_id}/agent/runs/{run_id}", {
              params: { path: { workspace_id: ws, run_id: runId } },
            }),
          );
          if (TERMINAL.has(run.status)) {
            void qc.invalidateQueries({ queryKey: ["workspaces", ws, "agent", "runs"] });
            return;
          }
        } catch {
          if (ctrl.signal.aborted) return;
          failures += 1;
          setReconnecting(true);
          await sleep(Math.min(1000 * 2 ** failures, 15_000), ctrl.signal);
        }
      }
    }

    void follow();
    return () => ctrl.abort();
  }, [ws, runId, qc]);

  return { view, reconnecting };
}
