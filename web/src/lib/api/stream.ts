import { ApiError } from "./client";

export type SSEHandler = (event: string, data: unknown) => void;

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
  if (!res.ok || !res.body) {
    let env: {
      error?: { code?: string; message?: string; request_id?: string; details?: unknown };
    } = {};
    try {
      env = await res.json();
    } catch {
      // Non-JSON error body; fall through to a status-based message.
    }
    throw new ApiError(
      res.status,
      env.error?.code ?? "http_error",
      env.error?.message ?? `Request failed with status ${res.status}`,
      env.error?.request_id ?? res.headers.get("x-request-id"),
      env.error?.details,
    );
  }

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
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue; // keep-alive comment
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent(event, JSON.parse(data.join("\n")));
    }
  }
}
