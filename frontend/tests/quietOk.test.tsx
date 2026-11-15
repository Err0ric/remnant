import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { needsYouRows } from "@/features/dashboard/NeedsYou";
import {
  idleText,
  openGaps,
  quietFrom,
  quietWord,
  shownGaps,
  sourcesSummaryText,
} from "@/features/health/flow";
import { SourceFlow, type FlowSource } from "@/features/health/SourceFlow";
import { QuietOkEditor } from "@/features/sources/QuietOkEditor";
import type { Overview } from "@/lib/api";

const NOW = "2026-11-14T12:30:00+00:00";
const TWO_DAYS_AGO = "2026-11-12T12:30:00+00:00";
const HOURS = Array.from({ length: 24 }, (_, i) =>
  new Date(Date.parse("2026-11-13T13:00:00+00:00") + i * 3600_000).toISOString(),
);

afterEach(() => vi.restoreAllMocks());

function editor(props: Partial<Parameters<typeof QuietOkEditor>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <QuietOkEditor sourceId="claude_hooks" value={null} canManage idle={null} {...props} />
    </QueryClientProvider>,
  );
}

describe("Quiet is normal (D260): the control on Sources", () => {
  it("lets an admin choose the days and saves them as one change", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ source_id: "claude_hooks", quiet_ok_days: 3 }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    editor();
    await userEvent.click(screen.getByRole("button", { name: "Quiet is normal for claude_hooks" }));
    const box = screen.getByRole("group", { name: "Quiet is normal for claude_hooks" });
    const save = within(box).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet
    expect(within(box).getByText(/its quiet alert waits; errors still count/)).toHaveClass(
      "text-text-muted",
    );
    await userEvent.selectOptions(within(box).getByLabelText("Quiet is normal for up to"), "3");
    await userEvent.click(save);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const [url, init] = spy.mock.calls[0] ?? [];
    expect(String(url)).toMatch(/\/api\/sources\/claude_hooks$/);
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({ quiet_ok_days: 3 });
  });

  it("can turn it off again", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { headers: { "Content-Type": "application/json" } }));
    editor({ value: 7 });
    expect(screen.getByText("Quiet is normal for up to 7 days")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Quiet is normal for claude_hooks" }));
    await userEvent.selectOptions(screen.getByLabelText("Quiet is normal for up to"), "off");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(JSON.parse(String(spy.mock.calls[0]?.[1]?.body))).toEqual({ quiet_ok_days: null });
  });

  it("shows the setting and the idle line to others, with nothing to change", () => {
    editor({ value: 7, canManage: false, idle: idleText(TWO_DAYS_AGO, NOW) });
    expect(screen.getByText("Quiet is normal for up to 7 days")).toBeInTheDocument();
    expect(screen.getByText("Idle: No events for 2 d (normal for this source)")).toHaveClass(
      "text-text-secondary",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows nothing to others when the source is not marked", () => {
    const { container } = editor({ canManage: false });
    expect(container).toBeEmptyDOMElement();
  });
});

const flowOverview = {
  generated_at: NOW,
  hours: HOURS,
  volume: [
    {
      source_id: "claude_hooks",
      counts: HOURS.map((_, i) => (i < 18 ? 4 : 0)),
      typical: HOURS.map(() => null),
      marks: HOURS.map(() => ""),
      total: 72,
      gaps: [{ start: HOURS[18], end: null, hours: 6, ongoing: true, others_flowing: true }],
    },
  ],
  sources: [
    {
      source_id: "claude_hooks",
      state: "reading",
      last_event_at: TWO_DAYS_AGO,
      files_waiting: 0,
      records_skipped: 0,
      error: null,
      rate_per_min: 0,
      condition: "healthy",
      quiet_ok_days: 7,
      quiet_ok: true,
      idle: true,
    },
  ],
} as unknown as Overview;

describe("Quiet is normal (D260): how an idle source reads", () => {
  it("is drawn greyed on Health, with one muted sentence and no gap", () => {
    const rows: FlowSource[] = [
      {
        source_id: "claude_hooks",
        level: "healthy",
        word: "Idle",
        reason: idleText(TWO_DAYS_AGO, NOW),
        last: null,
      },
    ];
    render(<SourceFlow overview={flowOverview} sources={rows} now={NOW} timeZone="UTC" />);
    const row = document.getElementById("flow-claude_hooks") as HTMLElement;
    expect(row).toHaveAttribute("data-quiet");
    expect(row.querySelector("[data-dot]")).toHaveClass("bg-text-muted");
    expect(within(row).getByText("Idle")).toBeInTheDocument();
    expect(row.querySelector("rect.fill-danger")).toBeNull();
    const sentences = [...row.querySelectorAll("p")];
    expect(sentences).toHaveLength(1);
    expect(sentences[0]).toHaveTextContent("No events for 2 d (normal for this source)");
    expect(sentences[0]).toHaveClass("text-text-secondary");
  });

  it("is no blind row on the Dashboard, while the same silence unmarked is", () => {
    const marked = needsYouRows(undefined, [], flowOverview);
    expect(marked).toEqual([]);
    const plain = {
      ...flowOverview,
      sources: flowOverview.sources.map((s) => ({ ...s, quiet_ok: false, idle: false })),
    } as Overview;
    const rows = needsYouRows(undefined, [], plain);
    expect(rows.map((r) => [r.kind, r.title])).toEqual([
      ["Source down", "claude_hooks has sent nothing for 6 h"],
    ]);
  });

  it("is still a blind row when it has errors", () => {
    const failing = {
      ...flowOverview,
      sources: flowOverview.sources.map((s) => ({ ...s, state: "error", condition: "error" })),
    } as Overview;
    expect(needsYouRows(undefined, [], failing).map((r) => r.kind)).toEqual(["Source error"]);
  });

  it("is named in the Sources healthy line as idle", () => {
    const text = sourcesSummaryText(
      { total: 3, healthy: 3, quiet: [], gaps: 0, longest_wait: null, idle: 1 },
      NOW,
    );
    expect(text.headline).toBe("3 of 3 healthy");
    expect(text.details).toContain("1 idle (normal)");
  });
});

describe("Quiet is normal (D260): a marked source sending again after gap hours", () => {
  const sending = {
    ...flowOverview,
    volume: flowOverview.volume.map((v) => ({
      ...v,
      counts: HOURS.map((_, i) => (i >= 8 && i < 14 ? 0 : 4)),
      gaps: [{ start: HOURS[8], end: HOURS[14], hours: 6, ongoing: false, others_flowing: true }],
    })),
    sources: flowOverview.sources.map((s) => ({ ...s, last_event_at: NOW, idle: false })),
  } as unknown as Overview;

  it("is drawn flowing on Health with no gap shading or sentence", () => {
    const rows: FlowSource[] = [
      { source_id: "claude_hooks", level: "healthy", reason: null, last: null },
    ];
    render(<SourceFlow overview={sending} sources={rows} now={NOW} timeZone="UTC" />);
    const row = document.getElementById("flow-claude_hooks") as HTMLElement;
    expect(row).not.toHaveAttribute("data-quiet");
    expect(row.querySelector("rect.fill-danger")).toBeNull();
    expect(row.querySelectorAll("p")).toHaveLength(0);
    expect(within(row).getByText("Flowing")).toBeInTheDocument();
  });

  it("has no gaps to say on Sources either, from the same rule", () => {
    const h = sending.sources[0];
    const gaps = sending.volume[0]?.gaps;
    expect(shownGaps(h, gaps)).toEqual([]);
    expect(shownGaps({ ...h, quiet_ok: false } as typeof h, gaps)).toHaveLength(1);
  });
});

describe("Quiet is normal (D260): a source with a quiet alert on", () => {
  it("says the quiet alert is held for the days, only when one is on", () => {
    const { unmount } = editor({ value: 7, quietAlert: true });
    expect(
      screen.getByText("Its quiet alert is held for these days and fires after them."),
    ).toHaveClass("text-text-muted");
    unmount();
    editor({ value: 7 });
    expect(document.querySelector("[data-quiet-alert-note]")).toBeNull();
  });
});

describe("How long a source has been quiet: from its newest dated event", () => {
  const AGO = (s: number) => new Date(Date.parse(NOW) - s * 1000).toISOString();
  const CASES: [string, string | null, string | null, string | null][] = [
    // case, newest dated event, last received, what Quiet and Idle say
    ["old, received long ago", AGO(2 * 86400), AGO(2 * 86400), "quiet 2 d"],
    ["old, received just now (a queue or an import)", AGO(2 * 86400), AGO(60), "quiet 2 d"],
    ["recent", AGO(3600), AGO(3600), "quiet 60 min"],
    ["never sent", null, null, "never sent"],
  ];
  it.each(CASES)("%s", (_case, newest, received, word) => {
    const h = { newest_event_at: newest, last_event_at: received };
    expect(quietWord(quietFrom(h), NOW)).toBe(word);
    if (newest) expect(idleText(quietFrom(h), NOW)).toMatch(/^No events for (2 d|60 min) \(/);
  });

  it("names the gap by the newest event too", () => {
    const o = {
      generated_at: NOW,
      sources: [
        {
          source_id: "collector_unmarked",
          gap_alert: "g1",
          newest_event_at: AGO(2 * 86400),
          last_event_at: AGO(25),
        },
      ],
    } as unknown as Overview;
    expect(openGaps(o)).toEqual([{ source_id: "collector_unmarked", item_id: "g1", quiet: "2 d" }]);
  });

  it("falls back to the last received time from a server that sends no dated time", () => {
    expect(quietFrom({ last_event_at: AGO(60) } as never)).toBe(AGO(60));
    expect(quietFrom(undefined)).toBeNull();
  });
});
