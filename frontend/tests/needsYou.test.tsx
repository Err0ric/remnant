import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NeedsYou, needsYouRows, SHOWN, shownRows } from "@/features/dashboard/NeedsYou";
import type { AlertItem, AlertLines, Overview } from "@/lib/api";

function item(over: Partial<AlertItem>): AlertItem {
  return {
    item_id: "x",
    kind: "rule",
    subject: "rule-x",
    ref_id: null,
    title: "Failed logons",
    detail: "",
    why: null,
    count: null,
    sources: ["win_dc"],
    range_start: null,
    range_end: null,
    created_at: "2026-11-10T12:00:00+00:00",
    state: "open",
    closed_at: null,
    closed_by: null,
    close_reason: null,
    close_reason_label: null,
    note: null,
    resolved: null,
    schedule_id: null,
    severity: null,
    muted_until: null,
    history: [],
    ...over,
  };
}

function lines(items: AlertItem[], over: Partial<AlertLines> = {}): AlertLines {
  return {
    items,
    runs: {},
    groups: items.length,
    gap_sources: [],
    open: items.length,
    restricted: false,
    by_severity: { high: 0, medium: 0, other: 0 },
    ...over,
  } as AlertLines;
}

function overview(over: Partial<Overview>): Overview {
  return {
    generated_at: "2026-11-10T12:30:00+00:00",
    hours: [],
    volume: [],
    sources: [],
    detections: [],
    paused: [],
    alerts: null,
    events_24h: 0,
    history_days: 7,
    events_compared_24h: 0,
    events_usual_24h: null,
    new_sources: [],
    source_summary: { total: 0, healthy: 0, quiet: [], gaps: 0, longest_wait: null },
    ...over,
  } as Overview;
}

const source = (source_id: string, over: Record<string, unknown> = {}) =>
  ({
    source_id,
    state: "reading",
    last_event_at: "2026-11-10T12:00:00+00:00",
    files_waiting: 0,
    records_skipped: 0,
    error: null,
    rate_per_min: 1,
    condition: "healthy",
    ...over,
  }) as Overview["sources"][number];

const DOWN = overview({
  sources: [
    source("fw_main", { condition: "quiet", quiet_since: "2026-11-10T09:00:00+00:00" }),
    source("win_dc"),
  ],
});

const high = (n: number) =>
  item({
    item_id: `h${n}`,
    subject: `rule-${n}`,
    title: `High rule ${n}`,
    severity: "high",
    created_at: `2026-11-10T1${n}:00:00+00:00`,
  });

function show(data: { lines: AlertLines; overview: Overview }) {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(new Response("{}", { status: 404 })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["alerts", "lines", SHOWN, "severity"], data.lines);
  client.setQueryData(["source-list"], []);
  client.setQueryData(["overview"], data.overview);
  return render(
    <QueryClientProvider client={client}>
      <NeedsYou />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Needs you list (ADR-0052 section 3.9, redesign build row 17)", () => {
  it("puts the blind row first, on the warn tint, above three High alerts", () => {
    show({ lines: lines([high(1), high(2), high(3)]), overview: DOWN });
    const list = screen.getByRole("region", { name: "Needs you" });
    const rows = within(list).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    const first = rows[0] as HTMLElement;
    expect(first.dataset.needsYou).toBe("blind");
    expect(first).toHaveClass("bg-warn-tint");
    expect(first).toHaveTextContent("Source down");
    expect(first).toHaveTextContent("fw_main stopped sending");
    // A shape as well as a tint: the 2px bar, and an outlined badge that is not a severity.
    expect(first.querySelector("td")).toHaveClass("border-l-2", "border-l-warn");
    expect(first.querySelector("[data-severity]")).toBeNull();
    // Then the High alerts, newest first, each a solid badge.
    expect(rows.slice(1).map((r) => r.querySelector("a")?.textContent)).toEqual([
      "Rule: High rule 3",
      "Rule: High rule 2",
      "Rule: High rule 1",
    ]);
    for (const r of rows.slice(1)) {
      expect(r).not.toHaveClass("bg-warn-tint");
      expect(r.querySelector("[data-severity]")).toHaveAttribute("data-severity", "high");
    }
  });

  it("never folds a blind row under N more: the cap is for alerts only", () => {
    const many = Array.from({ length: 8 }, (_, n) => high(n));
    const paused = [
      {
        schedule_id: "s1",
        name: "Failed SSH daily",
        kind: "search",
        reason: "Paused after errors",
      },
      { schedule_id: "s2", name: "Rule batch", kind: "rule", reason: null },
    ];
    const o = overview({
      ...DOWN,
      paused,
      sources: [
        ...DOWN.sources,
        source("dns", { state: "error", condition: "error", error: "Cannot read" }),
        source("m365", {
          state: "error",
          condition: "error",
          error:
            "Source m365 is storing events without its parser: template m365_signin is not available. Rules and searches that use its fields miss these events until they are reparsed.",
        }),
      ],
    });
    const rows = needsYouRows(lines(many), [], o);
    const blind = rows.filter((r) => r.order === 1);
    expect(blind.map((r) => r.kind).sort()).toEqual([
      "Detection paused",
      "Detection paused",
      "Source down",
      "Source error",
      "Template missing",
    ]);
    const shown = shownRows(rows);
    expect(shown.filter((r) => r.order === 1)).toHaveLength(5); // every blind row
    expect(shown.filter((r) => r.order !== 1)).toHaveLength(SHOWN);

    show({ lines: lines(many, { groups: 12 }), overview: o });
    const list = screen.getByRole("region", { name: "Needs you" });
    expect(list.querySelectorAll('[data-needs-you="blind"]')).toHaveLength(5);
    expect(list.querySelectorAll('[data-needs-you="alert"]')).toHaveLength(SHOWN);
    // 8 alerts sent, 5 shown, and 4 more the server counted but did not send.
    expect(within(list).getByRole("button", { name: "7 more on Alerts" })).toBeVisible();
  });

  it("orders High alerts, then other alerts, then AI review items", () => {
    const rows = needsYouRows(
      lines([
        item({
          item_id: "rev",
          kind: "ai_watch",
          subject: "service:deepseek",
          title: "AI service not reviewed: DeepSeek",
          why: "Not reviewed yet",
          severity: "medium",
          created_at: "2026-11-10T15:00:00+00:00",
        }),
        item({ item_id: "med", subject: "rule-m", severity: "medium", people: ["alice"] }),
        item({ item_id: "hi", subject: "rule-h", severity: "high", devices: ["ws-0042"] }),
      ]),
      [],
      undefined,
    );
    expect(rows.map((r) => [r.order, r.kind])).toEqual([
      [2, "Rule"],
      [3, "Rule"],
      [4, "AI review"],
    ]);
    // A review item is decided on AI usage > Inventory, not on Alerts.
    expect([rows[2]?.page, rows[2]?.tab]).toEqual(["ai", "inventory"]);
    expect(rows[1]?.subject).toEqual({ kind: "user", value: "alice" });
    expect(rows[0]?.subject).toEqual({ kind: "host", value: "ws-0042" });
  });

  it("keeps the restricted note at the foot as a state notice, with no count", () => {
    show({ lines: lines([high(1)], { restricted: true, groups: 1 }), overview: overview({}) });
    const note = within(screen.getByRole("region", { name: "Needs you" })).getByRole("note");
    expect(note).toHaveTextContent(
      "Some alerts are in sources you can't read. Ask an admin for access.",
    );
    expect(note).not.toHaveTextContent(/\d/);
  });

  it("is hidden entirely when nothing needs anyone", () => {
    const { container } = show({
      lines: lines([]),
      overview: overview({ sources: [source("win_dc")] }),
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("takes which lines are review items from the server, and lists them last", () => {
    const rows = needsYouRows(
      lines(
        [
          item({ item_id: "rule", subject: "rule-m", severity: "medium" }),
          // Its words do not say "not reviewed": only the server knows its service's status.
          item({
            item_id: "svc",
            kind: "ai_watch",
            subject: "service:x",
            title: "New AI service: X",
            severity: "high",
          }),
        ],
        { review: ["svc"] },
      ),
      [],
      undefined,
    );
    expect(rows.map((r) => [r.key, r.order, r.kind])).toEqual([
      ["alert:rule", 3, "Rule"],
      ["alert:svc", 4, "AI review"],
    ]);
  });

  it("does not count a gap alert twice when its source already has its blind row", () => {
    const o = overview({
      sources: [
        source("fw_main", {
          condition: "quiet",
          gap_alert: "g9",
          quiet_since: "2026-11-10T09:00:00+00:00",
        }),
      ],
    });
    // Five High alerts sent; the gap alert on fw_main is the sixth group, not sent.
    show({
      lines: lines([1, 2, 3, 4, 5].map(high), { groups: 6, gap_sources: ["fw_main"] }),
      overview: o,
    });
    const list = screen.getByRole("region", { name: "Needs you" });
    expect(list.querySelectorAll("tbody tr")).toHaveLength(6);
    expect(within(list).queryByRole("button", { name: /more on Alerts/ })).toBeNull();
    expect(within(list).getByRole("heading", { name: "Needs you" }).nextSibling).toHaveTextContent(
      "6",
    );
    // The blind row opens the gap alert the Overview names, though its line was not sent.
    expect(within(list).getByRole("link", { name: /fw_main stopped sending/ })).toHaveAttribute(
      "href",
      "/alerts#item=g9",
    );
  });

  it("opens the source on Health from a blind row with no alert", () => {
    const rows = needsYouRows(undefined, [], DOWN);
    expect([rows[0]?.page, rows[0]?.tab]).toEqual(["health", "source=fw_main"]);
  });

  it("does not pin a gap alert whose source is sending again: it is an alert to close", () => {
    const gap = item({
      item_id: "g1",
      kind: "gap",
      subject: "win_dc",
      title: "win_dc stopped sending",
      severity: "medium",
    });
    // The Overview knows the source and it is flowing.
    // The Overview knows the source and the server calls it healthy.
    const flowing = needsYouRows(lines([gap]), [], overview({ sources: [source("win_dc")] }));
    expect(flowing.map((r) => [r.order, r.kind, r.title])).toEqual([
      [3, "Source gap", "win_dc stopped sending: sending again, close the alert"],
    ]);
    // Or the alert itself says the condition ended.
    const resolved = needsYouRows(lines([{ ...gap, resolved: "Sending again" }]), [], undefined);
    expect(resolved.map((r) => r.order)).toEqual([3]);
    // While nothing says it ended, it stays a blind row.
    expect(needsYouRows(lines([gap]), [], undefined).map((r) => [r.order, r.kind])).toEqual([
      [1, "Source down"],
    ]);
  });

  it("never pins a gap alert that is not about a source: a missed backup, undelivered hooks", () => {
    const backup = item({
      item_id: "b1",
      kind: "gap",
      subject: "backup",
      title: "No successful backup in 48 hours",
      severity: "high",
    });
    const hooks = item({
      item_id: "k1",
      kind: "gap",
      subject: "claude/ws-0042",
      title: "ws-0042: Claude hooks records not delivered",
      severity: "medium",
    });
    for (const o of [overview({ sources: [source("claude")] }), undefined]) {
      const rows = needsYouRows(lines([backup, hooks]), [], o);
      expect(rows.map((r) => [r.order, r.kind, r.severity])).toEqual([
        [2, "Backup", "high"],
        [3, "Collector", "medium"],
      ]);
      // Each opens its alert, and neither links to a source that does not exist.
      expect(rows.map((r) => [r.page, r.tab])).toEqual([
        ["alerts", "item=b1"],
        ["alerts", "item=k1"],
      ]);
      expect(rows[0]?.subject).toBeNull();
      expect(rows[1]?.subject).toEqual(o ? { kind: "source", value: "claude" } : null);
    }
  });

  it("does not call a paused source's old gap alert blind, nor say it is sending again", () => {
    const gap = item({
      item_id: "g2",
      kind: "gap",
      subject: "win_dc",
      title: "win_dc stopped sending",
      severity: "medium",
    });
    const rows = needsYouRows(
      lines([gap]),
      [],
      overview({ sources: [source("win_dc", { state: "disabled", condition: "paused" })] }),
    );
    expect(rows.map((r) => [r.order, r.kind, r.title])).toEqual([
      [3, "Source gap", "win_dc stopped sending"],
    ]);
  });

  it("treats a source that is sending again as recovered, whatever the day's condition says", () => {
    const gap = item({
      item_id: "g3",
      kind: "gap",
      subject: "win_dc",
      title: "win_dc stopped sending",
      severity: "medium",
    });
    // The gap that ended is still in the source's 24 hours ("gap"), or it has skipped
    // records ("attention"): it is sending, so its old alert is one to close, not blind.
    for (const condition of ["gap", "attention", "healthy"]) {
      const rows = needsYouRows(
        lines([gap]),
        [],
        overview({ sources: [source("win_dc", { condition })] }),
      );
      expect(
        rows.map((r) => [r.order, r.kind]),
        condition,
      ).toEqual([[3, "Source gap"]]);
      expect(rows[0]?.title).toMatch(/sending again, close the alert$/);
    }
    // Still down (the Overview names its open gap alert): the source's own blind row.
    const down = needsYouRows(
      lines([gap]),
      [],
      overview({ sources: [source("win_dc", { condition: "quiet", gap_alert: "g3" })] }),
    );
    expect(down.map((r) => [r.order, r.kind])).toEqual([[1, "Source down"]]);
  });

  it("reports detection the system paused, not a schedule someone paused themselves", () => {
    const rows = needsYouRows(
      undefined,
      [],
      overview({
        paused: [
          {
            schedule_id: "s1",
            name: "Failed SSH daily",
            kind: "search",
            reason: "Paused after 3 failed runs",
          },
          {
            schedule_id: "s2",
            name: "Weekly report",
            kind: "search",
            reason: "Paused by a person",
            by_person: true,
          },
        ],
      }),
    );
    expect(rows.map((r) => [r.order, r.kind, r.title])).toEqual([
      [1, "Detection paused", "Failed SSH daily: Paused after 3 failed runs"],
    ]);
  });
});
