import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResultsTable } from "@/features/search/ResultsTable";
import type { QueryResult } from "@/lib/api";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

function calls(spy: ReturnType<typeof mockApi>, part: string, method = "GET"): number {
  return spy.mock.calls.filter(
    ([u, init]) => String(u).includes(part) && (init?.method ?? "GET").toUpperCase() === method,
  ).length;
}

describe("Enrichment (ADR-0023)", () => {
  it("lists feeds, turns on automatic updates, updates and uploads", async () => {
    const spy = await renderAt("/enrichment");
    const feeds = await screen.findByRole("region", { name: "GeoIP" });
    expect(await within(feeds).findByText("GeoIP country")).toBeVisible();
    expect(within(feeds).getByText("Current")).toBeVisible();
    expect(within(feeds).getByText("Not installed")).toBeVisible();
    const box = screen.getByRole("checkbox", { name: /Keep these lists and files current/ });
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await vi.waitFor(() => expect(calls(spy, "/api/enrichment/settings", "PUT")).toBe(1));
    await vi.waitFor(() => expect(box).toBeChecked());
    await userEvent.click(within(feeds).getAllByRole("button", { name: "Update now" })[0]!);
    await vi.waitFor(() =>
      expect(calls(spy, "/api/enrichment/feeds/geoip_country/update", "POST")).toBe(1),
    );
    const file = new File([new Uint8Array([1, 2, 3])], "dbip-asn-lite-2026-10.mmdb.gz");
    await userEvent.upload(screen.getByLabelText("Upload a file for GeoIP ASN"), file);
    await vi.waitFor(() =>
      expect(calls(spy, "/api/enrichment/feeds/geoip_asn/upload", "POST")).toBe(1),
    );
  });
});

describe("Threat intel settings", () => {
  it("shows lists, asks for the ThreatFox key, and switches a list off", async () => {
    const spy = await renderAt("/enrichment");
    const lists = await screen.findByRole("region", { name: "Threat intel" });
    expect(await within(lists).findByText("Botnet C2 addresses")).toBeVisible();
    expect(within(lists).getByText("Needs a key")).toBeVisible();
    expect(within(lists).getByText("Upload only")).toBeVisible();
    await userEvent.click(within(lists).getByRole("button", { name: "Add key" }));
    await userEvent.type(within(lists).getByLabelText(/Auth-Key for/), "abc123");
    await userEvent.click(within(lists).getByRole("button", { name: "Save key" }));
    await vi.waitFor(() =>
      expect(calls(spy, "/api/enrichment/feeds/intel_threatfox", "PUT")).toBe(1),
    );
    const put = spy.mock.calls.find(([u]) => String(u).endsWith("/feeds/intel_threatfox"));
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ key: "abc123" });
    await userEvent.click(within(lists).getByRole("checkbox", { name: "Use Botnet C2 addresses" }));
    await vi.waitFor(() => expect(calls(spy, "/api/enrichment/feeds/intel_feodo", "PUT")).toBe(1));
  });
});

describe("Location in results", () => {
  const result: QueryResult = {
    columns: ["time", "src_endpoint_ip", "event_id"],
    rows: [
      ["2026-10-10T11:00:00+00:00", "203.0.113.9", "e1"],
      ["2026-10-10T11:01:00+00:00", "10.0.0.5", "e2"],
    ],
    row_count: 2,
    truncated: false,
    elapsed_ms: 3,
    executed_sql: "SELECT 1",
    sources: ["fw"],
    geo: {
      "203.0.113.9": { country: "NL", country_name: "Netherlands", asn: 64500, org: "Example Net" },
    },
  };

  it("shows a muted country and network after public addresses only", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    render(<ResultsTable result={result} view="parsed" geo={result.geo} />);
    const label = screen.getByText("NL · AS64500");
    expect(label).toHaveClass("text-text-muted");
    expect(screen.getAllByText(/AS64500/)).toHaveLength(1); // nothing on the private address
  });

  it("credits DB-IP once, quietly, below the table (F52)", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    render(<ResultsTable result={result} view="parsed" geo={result.geo} />);
    const credit = screen.getAllByRole("link", { name: "IP Geolocation by DB-IP" });
    expect(credit).toHaveLength(1);
    expect(credit[0]).not.toHaveClass("text-accent");
  });

  it("does not credit DB-IP when no location is shown", () => {
    render(<ResultsTable result={result} view="parsed" />);
    expect(screen.queryByText(/IP Geolocation by DB-IP/)).toBeNull();
  });

  it("marks listed values with one small dot and nothing else", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    render(
      <ResultsTable
        result={{
          ...result,
          intel: {
            "203.0.113.9": [
              { feed: "Feodo Tracker", type: "ip", threat: "QakBot botnet C2", last_seen: null },
            ],
          },
        }}
        view="parsed"
      />,
    );
    const dots = screen.getAllByRole("img", { name: "Listed in threat intel" });
    expect(dots).toHaveLength(1);
    expect(dots[0]).toHaveAttribute("title", "Listed by Feodo Tracker: QakBot botnet C2");
  });

  it("shows nothing when the viewer hides it", () => {
    render(<ResultsTable result={result} view="parsed" />);
    expect(screen.queryByText("NL · AS64500")).toBeNull();
  });
});

describe("About and licenses", () => {
  it("lists the version, licence, and each outside data source with its attribution", async () => {
    await renderAt("/about");
    expect(await screen.findByRole("heading", { name: "About and licenses" })).toBeInTheDocument();
    expect(screen.getByText("Apache License 2.0")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("link", { name: "IP Geolocation by DB-IP" })).toHaveAttribute(
      "href",
      "https://db-ip.com",
    );
    expect(within(table).getByText(/Feodo Tracker and ThreatFox/)).toBeInTheDocument();
    expect(within(table).getByText(/Detection Rule License/)).toBeInTheDocument();
  });
});
