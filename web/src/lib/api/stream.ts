import { ApiError } from "./client";

export type SSEHandler = (event: string, data: unknown, id: number | null) => void;

async function failure(res: Response): Promise<ApiError> {
  let env: {
    error?: { code?: string; message?: string; request_id?: string; details?: unknown };
  } = {};
  try {
    env = await res.json();
  } catch {
    // Non-JSON error body; fall through to a status-based message.
  }
  return new ApiError(
    res.status,
    env.error?.code ?? "http_error",
    env.error?.message ?? `Request failed with status ${res.status}`,
    env.error?.request_id ?? res.headers.get("x-request-id"),
    env.error?.details,
  );
}

/** Parse a text/event-stream body, calling `onEvent` per event (with its `id:` if any). */
async function readSSE(res: Response, onEvent: SSEHandler, onOpen?: () => void): Promise<void> {
  if (!res.ok || !res.body) throw await failure(res);
  onOpen?.();
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let id: number | null = null;
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue; // keep-alive comment
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("id:")) id = Number(line.slice(3).trim());
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent(event, JSON.parse(data.join("\n")), id);
    }
  }
}

/**
 * POST a JSON body and read a text/event-stream response. Rejects with ApiError when the
 * server answers with a non-2xx (validation, auth, rate limit) before streaming starts.
 */
export async function postSSE(
  url: string,
  body: unknown,
  onEvent: SSEHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    credentials: "same-origin",
    body: JSON.stringify(body),
    signal,
  });
  await readSSE(res, onEvent);
}

/** GET an event stream (e.g. an agent run's replayable log). Resolves when the server ends it.
 * `onOpen` fires once the server has accepted the request and streaming begins. */
export async function getSSE(
  url: string,
  onEvent: SSEHandler,
  signal?: AbortSignal,
  onOpen?: () => void,
) {
  const res = await fetch(url, {
    headers: { accept: "text/event-stream" },
    credentials: "same-origin",
    signal,
  });
  await readSSE(res, onEvent, onOpen);
}
