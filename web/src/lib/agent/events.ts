// Folds an agent run's event log (replayed or live) into what the chat and timeline render.
// Pure and framework-free so it can be unit-tested with node:test. Event shapes mirror the API
// (documented in the README under "Agent event stream").

export type PlanStep = { id: number; title: string; tool: string; status: string };
export type Source = { title: string; url: string };
export type DraftRef = {
  item_id: string;
  label?: string | null;
  channel: string;
  angle?: string | null;
  preview: string;
  avg_score?: number | null;
  blocked?: boolean;
};
export type ToolStep = {
  id: string;
  tool: string;
  label: string;
  input: Record<string, unknown>;
  status: "running" | "ok" | "error";
  durationMs?: number;
  output?: string;
};
export type RunError = { code: string; message: string; hint?: string | null };
export type ApprovalSummary = {
  approved: number;
  rejected: number;
  edited: number;
  skipped: number;
};

export type RunView = {
  lastSeq: number;
  status: "running" | "awaiting_approval" | "finished" | "failed" | "cancelled";
  outcome?: string; // finished | refused | tool_cap | budget_exceeded | ...
  goal?: string;
  plan: PlanStep[];
  refused?: string;
  thinking?: string; // label of the step in progress, if any
  tools: ToolStep[];
  messages: string[]; // assistant text, in order
  drafts: DraftRef[];
  sources: { query: string; sources: Source[] }[];
  approval?: DraftRef[]; // pending review, when status is awaiting_approval
  applied?: ApprovalSummary;
  error?: RunError;
  final?: string | null;
  costUsd?: string;
  costComplete?: boolean; // false: some model had no known price, so the total is a floor
  tokens?: number;
};

export const emptyRun = (): RunView => ({
  lastSeq: 0,
  status: "running",
  plan: [],
  tools: [],
  messages: [],
  drafts: [],
  sources: [],
});

type Data = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : "");

/** Apply one event. Events at or below `lastSeq` are ignored, so replay + live never double up. */
export function applyEvent(view: RunView, type: string, data: Data, seq: number | null): RunView {
  if (seq !== null && seq <= view.lastSeq) return view;
  const v: RunView = { ...view, lastSeq: seq ?? view.lastSeq };
  switch (type) {
    case "run_started":
      return { ...v, status: "running", error: undefined };
    case "plan":
      if (data.refused) return { ...v, refused: str(data.reply), outcome: "refused" };
      return {
        ...v,
        goal: str(data.goal),
        plan: Array.isArray(data.steps) ? (data.steps as PlanStep[]) : v.plan,
      };
    case "step_started":
      return { ...v, status: "running", thinking: str(data.label) };
    case "tool_call":
      return {
        ...v,
        tools: [
          ...v.tools,
          {
            id: str(data.id),
            tool: str(data.tool),
            label: str(data.tool),
            input: (data.input as Record<string, unknown>) ?? {},
            status: "running",
          },
        ],
      };
    case "tool_result": {
      const id = str(data.id);
      return {
        ...v,
        thinking: undefined,
        tools: v.tools.map((t) =>
          t.id === id
            ? {
                ...t,
                status: data.ok ? "ok" : "error",
                durationMs: typeof data.duration_ms === "number" ? data.duration_ms : undefined,
                output: str(data.output),
              }
            : t,
        ),
      };
    }
    case "token":
      return str(data.text) ? { ...v, messages: [...v.messages, str(data.text)] } : v;
    case "item_created":
      return { ...v, drafts: [...v.drafts, data as unknown as DraftRef] };
    case "research":
      return {
        ...v,
        sources: [
          ...v.sources,
          { query: str(data.query), sources: (data.sources as Source[]) ?? [] },
        ],
      };
    case "approval_required":
      return {
        ...v,
        status: "awaiting_approval",
        thinking: undefined,
        approval: (data.items as DraftRef[]) ?? [],
        final: (data.final as string | null) ?? v.final,
      };
    case "approvals_applied":
      return {
        ...v,
        status: "running",
        approval: undefined,
        applied: data as unknown as ApprovalSummary,
      };
    case "error":
      return {
        ...v,
        error: {
          code: str(data.code),
          message: str(data.message),
          hint: (data.hint as string | null) ?? null,
        },
      };
    case "run_finished": {
      const status = str(data.status);
      return {
        ...v,
        status: status === "failed" ? "failed" : status === "cancelled" ? "cancelled" : "finished",
        outcome: status,
        thinking: undefined,
        approval: undefined,
        final: (data.final as string | null | undefined) ?? v.final,
        costUsd: str(data.cost_usd) || v.costUsd,
        costComplete: typeof data.cost_complete === "boolean" ? data.cost_complete : v.costComplete,
        tokens: typeof data.tokens === "number" ? data.tokens : v.tokens,
        // A tool still "running" when the run ended never finished.
        tools: v.tools.map((t) => (t.status === "running" ? { ...t, status: "error" } : t)),
      };
    }
    default:
      return v;
  }
}

export function foldEvents(events: { seq: number; type: string; data: Data }[]): RunView {
  return events.reduce((v, e) => applyEvent(v, e.type, e.data, e.seq), emptyRun());
}

/** The assistant's reply for the chat bubble. `final` wins: it carries stop reasons (budget,
 * tool cap) that never arrive as model text. Interim notes show in the timeline instead. */
export function replyText(view: RunView): string | undefined {
  return view.refused ?? view.final ?? view.messages.at(-1) ?? undefined;
}
