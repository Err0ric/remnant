import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SOURCE, mockApi, type MockAuth } from "./mockApi";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "admin" },
  tweak?: (spy: ReturnType<typeof mockApi>) => void,
) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", auth);
  tweak?.(spy);
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

afterEach(() => vi.restoreAllMocks());

describe("Health (ADR-0019)", () => {
  it("counts states across tabs and lists sources, agents, and watched devices", async () => {
    await renderAt("/health");
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Health" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const sources = await screen.findByRole("list", { name: "Sources" });
    expect(within(sources).getByText("linux_sshd")).toBeVisible();
    const show = screen.getByRole("group", { name: "Show" });

    await userEvent.click(screen.getByRole("link", { name: /Endpoint agents/ }));
    const agents = await screen.findByRole("table", { name: "Endpoint agents" });
    expect(within(agents).getByText("ws-0042")).toBeVisible();
    expect(within(agents).getByText("Last reported 2 d ago")).toBeVisible();

    await userEvent.click(screen.getByRole("link", { name: /Watched devices/ }));
    const devices = await screen.findByRole("table", { name: "Watched devices" });
    expect(within(devices).getByText("Site B network sensor")).toBeVisible();
    expect(within(devices).getByText("Silent 47 min (allowed 15 min)")).toBeVisible();
    // The filter counts the open tab: here, the silent sensor.
    const unhealthy = within(show).getByRole("button", { name: /Unhealthy/ });
    expect(within(unhealthy).getByText("1")).toBeVisible();
  });

  it("lets administrators watch a device", async () => {
    const spy = await renderAt("/health");
    await userEvent.click(await screen.findByRole("link", { name: /Watched devices/ }));
    await userEvent.click(screen.getByRole("button", { name: "Watch a device" }));
    const form = screen.getByRole("form", { name: "Watch a device" });
    await userEvent.type(within(form).getByLabelText("Name"), "Core firewall");
    await userEvent.type(within(form).getByLabelText("IP address or host name"), "FW-CORE");
    await userEvent.click(within(form).getByRole("button", { name: "Watch device" }));
    expect(await screen.findByText("Core firewall")).toBeVisible();
    const call = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/health-checks/devices") && i?.method === "POST",
    );
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ match: "FW-CORE", silence_s: 900 });
  });

  it("does not offer device changes to analysts", async () => {
    await renderAt("/health", { mode: "login", signedIn: true, role: "analyst" });
    await userEvent.click(await screen.findByRole("link", { name: /Watched devices/ }));
    await screen.findByRole("table", { name: "Watched devices" });
    expect(screen.queryByRole("button", { name: "Watch a device" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Stop watching/ })).toBeNull();
  });
});

/** A real install that only pulls (F59): three Loki sources and one Microsoft 365. */
function pulledOnly(spy: ReturnType<typeof mockApi>) {
  const real = spy.getMockImplementation();
  const hours = Array.from({ length: 24 }, (_, i) =>
    new Date(Date.UTC(2026, 9, 9, 13 + i)).toISOString().replace(".000Z", "+00:00"),
  );
  const pulled = [
    { ...SOURCE, source_id: "paloalto_fw", kind: "loki", path: "" },
    { ...SOURCE, source_id: "unifi", kind: "loki", path: "" },
    { ...SOURCE, source_id: "dns", kind: "loki", path: "" },
    { ...SOURCE, source_id: "m365", kind: "m365", path: "" },
  ];
  const volume = pulled.map((p) => ({
    source_id: p.source_id,
    counts: hours.map((_, i) => (p.source_id === "paloalto_fw" && i >= 15 && i < 20 ? 0 : 9)),
    typical: hours.map(() => null),
    marks: hours.map(() => ""),
    total: p.source_id === "paloalto_fw" ? 171 : 216,
    gaps:
      p.source_id === "paloalto_fw"
        ? [{ start: hours[15], end: hours[20], hours: 5, ongoing: false, others_flowing: true }]
        : [],
  }));
  const json = (body: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }),
    );
  spy.mockImplementation((url, init) => {
    const u = String(url);
    if (u.endsWith("/api/sources") && (init?.method ?? "GET") === "GET") return json(pulled);
    if (u.endsWith("/api/overview"))
      return (real as typeof fetch)(url, init)
        .then((r) => r.json())
        .then((o: Record<string, unknown>) =>
          json({
            ...o,
            hours,
            volume,
            sources: pulled.map((p) => ({
              source_id: p.source_id,
              state: "reading",
              last_event_at: "2026-10-10T12:26:00+00:00",
              files_waiting: 0,
              records_skipped: 0,
              error: null,
              rate_per_min: 0.2,
            })),
            history_days: 2,
            events_usual_24h: null,
          }),
        );
    return (real as typeof fetch)(url, init);
  });
}

describe("Health with pulled sources only (F59, F60)", () => {
  it("lists Loki and Microsoft 365 on the Sources tab with their flow and gaps", async () => {
    await renderAt("/health#sources", undefined, pulledOnly);
    const tab = await screen.findByRole("link", { name: /^Sources/ });
    await within(tab).findByText("4");
    const flow = await screen.findByRole("list", { name: "Sources" });
    for (const id of ["paloalto_fw", "unifi", "dns", "m365"])
      expect(within(flow).getByText(id)).toBeVisible();
    const fw = within(flow).getByText("paloalto_fw").closest("li") as HTMLElement;
    expect(
      within(fw).getByText(/^No events .+\(5 h\)\. Other sources kept flowing\.$/),
    ).toBeVisible();
    expect(screen.queryByText(/No sources yet/)).toBeNull();
    const enrichment = screen.getByRole("link", { name: /Enrichment feeds/ });
    expect(enrichment).not.toHaveTextContent("4");
    const events = screen.getByRole("button", { name: /^Events, last 24 hours/ });
    expect(events).toHaveTextContent("Not enough history yet (2 of 7 days)");
  });
});
