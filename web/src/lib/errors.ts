import { ApiError } from "@/lib/api/client";

/** Structured error from the API (HTTP error envelope or an SSE `error` event). */
export type ErrorInfo = {
  code: string;
  message: string;
  hint?: string | null;
  requestId?: string | null;
  provider?: string | null;
  model?: string | null;
};

const TITLES: Record<string, string> = {
  llm_model_not_found: "The AI model isn't available",
  llm_auth: "The AI provider rejected the API key",
  llm_rate_limited: "The AI provider is rate-limiting us",
  spend_cap_exceeded: "Today's AI budget is used up",
  llm_invalid_output: "The AI returned something unusable",
  llm_not_configured: "AI isn't set up yet",
  llm_timeout: "The AI provider took too long",
  llm_provider_error: "The AI provider is having problems",
  llm_refusal: "The AI declined this brief",
  llm_bad_request: "The AI provider rejected the request",
  rate_limited: "Too many requests",
  validation_error: "Some fields need fixing",
};

const DEFAULT_HINTS: Record<string, string> = {
  llm_model_not_found: "Check the model ID in .env against the provider's current model list.",
  llm_rate_limited: "Wait a minute and try again.",
  spend_cap_exceeded: "Raise the daily cap in Settings → AI, or try again tomorrow.",
  llm_invalid_output:
    "Try again. If it keeps happening, switch this task to a stronger model in Settings → AI.",
  llm_timeout: "Try again; long briefs and more variants take longer.",
  llm_provider_error: "This is usually temporary. Try again in a moment.",
  llm_refusal: "Rephrase the brief and try again.",
  rate_limited: "Wait a minute before trying again.",
};

export function toErrorInfo(err: unknown): ErrorInfo {
  if (err instanceof ApiError) {
    const details = (err.details ?? {}) as Record<string, unknown>;
    return {
      code: err.code,
      message: err.message,
      hint: (details.hint as string | undefined) ?? null,
      requestId: err.requestId,
      provider: (details.provider as string | undefined) ?? null,
      model: (details.model as string | undefined) ?? null,
    };
  }
  if (err && typeof err === "object" && "code" in err && "message" in err) {
    const e = err as Record<string, unknown>;
    return {
      code: String(e.code),
      message: String(e.message),
      hint: (e.hint as string | null | undefined) ?? null,
      requestId: (e.request_id as string | null | undefined) ?? null,
      provider: (e.provider as string | null | undefined) ?? null,
      model: (e.model as string | null | undefined) ?? null,
    };
  }
  if (err instanceof Error && err.name === "AbortError") {
    return { code: "aborted", message: "Stopped." };
  }
  return { code: "unknown", message: err instanceof Error ? err.message : "Something went wrong." };
}

export function describeError(info: ErrorInfo): { title: string; detail: string; hint?: string } {
  return {
    title: TITLES[info.code] ?? "Something went wrong",
    detail: info.message,
    hint: info.hint ?? DEFAULT_HINTS[info.code],
  };
}
