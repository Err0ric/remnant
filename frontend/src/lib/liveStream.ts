import { ApiError, type Cell } from "@/lib/api";

/** One server-sent event from `/api/search/live` (ADR-0036). */
export type LiveEvent =
  | { type: "start"; stream_id: string; since: string; limit_s: number; poll_s: number }
  | {
      type: "rows";
      columns: string[];
      rows: Cell[][];
      cursor: { t: string; ids: string[] };
    }
  | {
      type: "lag";
      sources: {
        source: string;
        newest: string | null;
        age_s: number | null;
        pull_every_s: number | null;
      }[];
    }
  | { type: "notice"; message: string }
  | { type: "end"; reason: string; message: string };

export interface LiveOptions {
  sql: string;
  sources?: string[];
  /** Resume: start after this cursor (Pause ends the stream on the server, row 12). */
  since?: string;
  after?: string[];
  signal: AbortSignal;
  onEvent: (e: LiveEvent) => void;
}

/** Split an SSE body into (event, data) pairs; comments (keep-alives) are skipped. */
export function parseSse(chunk: string): { rest: string; events: [string, string][] } {
  const events: [string, string][] = [];
  const blocks = chunk.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let name = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7);
      else if (line.startsWith("data: ")) data.push(line.slice(6));
    }
    if (data.length) events.push([name, data.join("\n")]);
  }
  return { rest, events };
}

/** Follow a row query. Resolves when the stream ends (an `end` event, a dropped
 * connection, or Pause/Stop aborting it); rejects with ApiError when it never starts
 * (a group query, or a third live search). Uses fetch so a refusal's reason is readable. */
export async function followLive(o: LiveOptions): Promise<void> {
  const q = new URLSearchParams({ q: o.sql, client: "browser" });
  for (const s of o.sources ?? []) q.append("sources", s);
  if (o.since) q.set("since", o.since);
  for (const id of o.after ?? []) q.append("after", id);
  const res = await fetch(`/api/search/live?${q.toString()}`, {
    credentials: "same-origin",
    headers: { Accept: "text/event-stream" },
    signal: o.signal,
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown; code?: string };
      if (typeof body.detail === "string") detail = body.detail;
      code = body.code;
    } catch {
      // keep the status line
    }
    throw new ApiError(res.status, detail, code);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch {
      return; // aborted or dropped: a stop (row 3)
    }
    if (chunk.done) return;
    const parsed = parseSse(buffer + decoder.decode(chunk.value, { stream: true }));
    buffer = parsed.rest;
    for (const [name, data] of parsed.events) {
      try {
        o.onEvent({ type: name, ...(JSON.parse(data) as object) } as LiveEvent);
      } catch {
        // a malformed event is skipped
      }
    }
  }
}
