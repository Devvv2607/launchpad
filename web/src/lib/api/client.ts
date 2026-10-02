import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** Error envelope returned by the API: {"error": {code, message, request_id, details?}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string | null,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Field-level messages from a 422, keyed by the last path segment. */
  fieldErrors(): Record<string, string> {
    if (this.code !== "validation_error" || !Array.isArray(this.details)) return {};
    const out: Record<string, string> = {};
    for (const d of this.details as { loc: (string | number)[]; msg: string }[]) {
      const key = String(d.loc[d.loc.length - 1]);
      out[key] ??= d.msg
        .replace(/^Value error, /, "")
        .replace(/^value is not a valid email address:.*/, "Enter a valid email address.");
    }
    return out;
  }
}

const handleUnauthorized: Middleware = {
  onResponse({ response, request }) {
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !new URL(request.url).pathname.startsWith("/api/v1/auth/")
    ) {
      const next = window.location.pathname + window.location.search;
      // Hard navigation on purpose: drops all cached client state for the old session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(handleUnauthorized);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Unwraps an openapi-fetch result: returns data or throws a typed ApiError. Never swallows. */
export async function unwrap<T>(promise: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await promise;
  if (response.ok) return data as T;
  const env = (
    error as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } }
  )?.error;
  throw new ApiError(
    response.status,
    env?.code ?? "http_error",
    env?.message ?? `Request failed with status ${response.status}`,
    env?.request_id ?? response.headers.get("x-request-id"),
    env?.details,
  );
}

/** Multipart upload (openapi-fetch's JSON serializer doesn't cover files). */
export async function uploadFile<T>(url: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(url, { method: "POST", body: form, credentials: "same-origin" });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON response; handled below.
  }
  if (response.ok) return body as T;
  const env = (
    body as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } }
  )?.error;
  throw new ApiError(
    response.status,
    env?.code ?? "http_error",
    env?.message ?? `Upload failed with status ${response.status}`,
    env?.request_id ?? response.headers.get("x-request-id"),
    env?.details,
  );
}
