import { QueryClient } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { needsYouRows } from "@/features/dashboard/NeedsYou";
import type { Overview, Source } from "@/lib/api";
import { SOURCE, mockApi } from "./mockApi";

/** Fix list 2026-11-16 item 19: Settings > Sources and Health say the same status, in the
 * same words and dot, for the same source, from the server's one condition. A file being
 * followed (the reader "reading") that has sent nothing for days is quiet on both. */
const NOW = "2026-10-10T12:30:00+00:00";
const RECENT = "2026-10-10T12:29:00+00:00";
const OLD = "2026-10-05T12:30:00+00:00"; // 5 days ago
const HOURS = Array.from({ length: 24 }, (_, i) =>
  new Date(Date.UTC(2026, 9, 9, 13 + i)).toISOString().replace(".000Z", "+00:00"),
);

interface Case {
  id: string;
  reader: "reading" | "waiting" | "error" | "disabled";
  judged: Record<string, unknown>;
  enabled?: boolean;
  quietOkDays?: number | null;
  word: string;
  dot: string;
}

const CASES: Case[] = [
  {
    id: "healthy_src",
    reader: "reading",
    judged: { condition: "healthy" },
    word: "Flowing",
    dot: "bg-ok",
  },
  {
    id: "quiet_src",
    reader: "reading",
    judged: {
      condition: "quiet",
      problem: "attention",
      last_event_at: OLD,
      newest_event_at: OLD,
      quiet_since: OLD, // its quiet alert is firing
    },
    word: "Quiet 5 d",
    dot: "bg-text-muted",
  },
  {
    // Marked "Quiet is normal" and silent inside its days: the alert is held (D260, D262).
    id: "held_src",
    reader: "reading",
    quietOkDays: 7,
    judged: {
      condition: "healthy",
      quiet_ok: true,
      idle: true,
      last_event_at: OLD,
      newest_event_at: OLD,
    },
    word: "Idle",
    dot: "bg-text-muted",
  },
  {
    // server_events: quiet is expected, never quiet.
    id: "server_events",
    reader: "reading",
    judged: {
      condition: "healthy",
      quiet_expected: true,
      last_event_at: OLD,
      newest_event_at: OLD,
    },
    word: "Flowing",
    dot: "bg-ok",
  },
  {
    id: "paused_src",
    reader: "disabled",
    enabled: false,
    judged: { condition: "paused", state: "disabled" },
    word: "Paused",
    dot: "bg-text-muted",
  },
  {
    id: "error_src",
    reader: "error",
    judged: {
      condition: "error",
      problem: "unhealthy",
      state: "error",
      error: "Cannot open the file",
    },
    word: "Unhealthy",
    dot: "bg-danger",
  },
  {
    id: "never_src",
    reader: "reading",
    judged: {
      condition: "quiet",
      problem: "attention",
      last_event_at: null,
      newest_event_at: null,
    },
    word: "Never sent",
    dot: "bg-text-muted",
  },
];

const OVERVIEW = {
  generated_at: NOW,
  hours: HOURS,
  volume: [],
  sources: CASES.map((c) => ({
    source_id: c.id,
    state: "reading",
    last_event_at: RECENT,
    newest_event_at: RECENT,
    files_waiting: 0,
    records_skipped: 0,
    error: null,
    rate_per_min: 0,
    ...c.judged,
  })),
  source_summary: { total: 7, healthy: 3, quiet: [], gaps: 0, longest_wait: null, idle: 1 },
  detections: [],
  paused: [],
  alerts: null,
  events_24h: 0,
  history_days: 7,
  events_compared_24h: 0,
  events_usual_24h: null,
  new_sources: [],
};

const SOURCES = CASES.map((c) => ({
  ...SOURCE,
  source_id: c.id,
  enabled: c.enabled ?? true,
  quiet_ok_days: c.quietOkDays ?? null,
  // The reader is following the file in every case but paused and error.
  status: {
    ...SOURCE.status,
    state: c.reader,
    last_event_at: RECENT,
    error: c.reader === "error" ? "Cannot open the file" : null,
  },
}));

async function renderAt(
  path: string,
  answer: { overview?: () => Promise<Response> | Response; sources?: unknown } = {},
) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  const base = spy.getMockImplementation() as typeof fetch;
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  spy.mockImplementation(async (input, init) => {
    const u = String(input);
    if ((init?.method ?? "GET") === "GET") {
      if (u.endsWith("/api/overview")) return answer.overview ? answer.overview() : json(OVERVIEW);
      if (u.endsWith("/api/sources")) return json(answer.sources ?? SOURCES);
    }
    return base(input, init);
  });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
}

/** Each case's status word and dot class as the page draws them. */
async function statuses(rowOf: (id: string) => HTMLElement | null) {
  const out: Record<string, { word: string; dot: string }> = {};
  for (const c of CASES) {
    const row = await vi.waitFor(() => {
      const el = rowOf(c.id);
      if (!el || !el.querySelector("[data-status-word]")) throw new Error("not yet");
      return el;
    });
    await vi.waitFor(() => {
      if (row.querySelector("[data-status-word]")?.textContent !== c.word)
        throw new Error("not yet");
    });
    const dot = row.querySelector("[data-dot]")?.className ?? "";
    out[c.id] = {
      word: row.querySelector("[data-status-word]")?.textContent ?? "",
      dot: dot.split(" ").find((k) => k.startsWith("bg-")) ?? "",
    };
  }
  return out;
}

afterEach(() => vi.restoreAllMocks());

describe("one status for a source on Health and Settings > Sources (item 19)", () => {
  it("draws the same word and dot in every case", async () => {
    await renderAt("/health");
    const health = await statuses((id) => document.getElementById(`flow-${id}`));
    cleanup();
    await renderAt("/sources");
    const settings = await statuses((id) => document.getElementById(`source-${id}`));
    for (const c of CASES) {
      expect(health[c.id], c.id).toEqual({ word: c.word, dot: c.dot });
      expect(settings[c.id], c.id).toEqual(health[c.id]);
    }
    // The reader's own fact is a separate line, never the status.
    const quiet = document.getElementById("source-quiet_src") as HTMLElement;
    expect(within(quiet).getByText("Reader: following the files")).toBeInTheDocument();
    expect(screen.queryByText("Reading")).toBeNull();
  });

  it("names a source in Needs you by the same word, and not at all when it is no problem", () => {
    const rows = needsYouRows(undefined, SOURCES as Source[], OVERVIEW as unknown as Overview);
    const kinds = new Map(rows.map((r) => [r.subject?.value, r.kind]));
    expect(kinds.get("quiet_src")).toBe("Quiet 5 d");
    expect(rows.find((r) => r.key === "source:quiet_src")?.title).toBe(
      "quiet_src: nothing received for 5 d",
    );
    expect(kinds.get("error_src")).toBe("Unhealthy");
    // Quiet is normal inside its days, and paused: Health counts neither, so no row.
    expect(kinds.has("held_src")).toBe(false);
    expect(kinds.has("paused_src")).toBe(false);
  });

  it("never takes the status from the reader: a placeholder while the Overview loads", async () => {
    await renderAt("/sources", { overview: () => new Promise<Response>(() => {}) });
    const row = await vi.waitFor(() => {
      const el = document.getElementById("source-quiet_src");
      if (!el) throw new Error("not yet");
      return el;
    });
    expect(within(row).getByRole("status", { name: "Loading status" })).toBeInTheDocument();
    expect(within(row).queryByText("Flowing")).toBeNull();
    expect(within(row).getByText("Reader: following the files")).toBeInTheDocument();
  });

  it("says Status unavailable without the Overview, with the reader line still shown", async () => {
    await renderAt("/sources", {
      overview: () => new Response(JSON.stringify({ detail: "down" }), { status: 500 }),
    });
    const row = await vi.waitFor(() => {
      const el = document.getElementById("source-quiet_src");
      if (!el || !within(el).queryByText("Status unavailable")) throw new Error("not yet");
      return el;
    });
    expect(row.querySelector("[data-dot]")).toBeNull(); // no dot color
    expect(within(row).queryByText("Flowing")).toBeNull();
    expect(within(row).getByText("Reader: following the files")).toBeInTheDocument();
  });

  it("reads Unhealthy at once when the reader stops on an error, before the Overview says so", async () => {
    // The Overview (every 60 s) still says healthy; the reader (every 5 s) has an error.
    const stopped = SOURCES.map((x) =>
      x.source_id === "healthy_src"
        ? { ...x, status: { ...x.status, state: "error", error: "Cannot open the file" } }
        : x,
    );
    await renderAt("/sources", { sources: stopped });
    const row = await vi.waitFor(() => {
      const el = document.getElementById("source-healthy_src");
      const word = el?.querySelector("[data-status-word]")?.textContent;
      if (!el || word !== "Unhealthy") throw new Error(`not yet: ${word}`);
      return el;
    });
    expect(row.querySelector("[data-dot]")).toHaveClass("bg-danger");
    expect(within(row).getByText("Reader: stopped on an error")).toBeInTheDocument();
    const rows = needsYouRows(undefined, stopped as Source[], OVERVIEW as unknown as Overview);
    expect(rows.find((r) => r.key === "source:healthy_src")?.kind).toBe("Unhealthy");
  });
});
