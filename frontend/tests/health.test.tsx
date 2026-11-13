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

    // Three tabs (ADR-0052 section 3.3); Collectors holds the agents and the devices.
    const tabs = await screen.findByRole("navigation", { name: "Health tabs" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((a) => a.textContent?.replace(/\d+$/g, "").trim()),
    ).toEqual(["Sources", "Collectors", "Delivery"]);
    await userEvent.click(within(tabs).getByRole("link", { name: /Collectors/ }));
    expect(window.location.pathname).toBe("/health/collectors");
    const agents = await screen.findByRole("table", { name: "Endpoint agents" });
    expect(within(agents).getByText("ws-0042")).toBeVisible();
    expect(within(agents).getByText("Last reported 2 d ago")).toBeVisible();

    // The Type filter of the tab, in the address.
    const type = screen.getByRole("group", { name: "Type" });
    expect(within(type).getByRole("button", { name: /^Endpoint agents/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(within(type).getByRole("button", { name: /^Watched devices/ }));
    expect(window.location.pathname + window.location.hash).toBe("/health/collectors#type=devices");
    const devices = await screen.findByRole("table", { name: "Watched devices" });
    expect(within(devices).getByText("Site B network sensor")).toBeVisible();
    expect(within(devices).getByText("Silent 47 min (allowed 15 min)")).toBeVisible();
    // The filter counts the open type: here, the silent sensor.
    const show = screen.getByRole("group", { name: "Show" });
    const unhealthy = within(show).getByRole("button", { name: /Unhealthy/ });
    expect(within(unhealthy).getByText("1")).toBeVisible();
  });

  it("shows each page rollup with days still to build and the last today build", async () => {
    // Page rollups, Backups, and Speed are Settings > System; the old tab address lands there.
    await renderAt("/health/rollups");
    await vi.waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe("/system#type=rollups"),
    );
    expect(await screen.findByRole("heading", { name: "System", level: 1 })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Health tabs" })).toBeNull();
    const table = await screen.findByRole("table", { name: "Page rollups" });
    expect(within(table).getByText("Attacks and access")).toBeVisible();
    expect(within(table).getByText(/33 days built · 0 still to build/)).toBeVisible();
    expect(within(table).getAllByText(/today up to Oct 10, 8:54 AM/)).toHaveLength(2); // local (tests run in UTC)
    expect(within(table).getByText("4 closed days still to build")).toBeVisible();
  });

  it("shows page speed per route to administrators (Speed tab)", async () => {
    await renderAt("/health#speed");
    await vi.waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe("/system#type=speed"),
    );
    const table = await screen.findByRole("table", { name: "Page speed by route" });
    expect(within(table).getByText("GET /api/m365/overview")).toBeVisible();
    expect(within(table).getByText("2.40 s")).toBeVisible();
    expect(within(table).getByText("75%")).toBeInTheDocument();
  });

  it("lets administrators watch a device", async () => {
    // The old Watched devices address opens Collectors on that type.
    const spy = await renderAt("/health/devices");
    await vi.waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe(
        "/health/collectors#type=devices",
      ),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Watch a device" }));
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
    await renderAt("/health/collectors#type=devices", {
      mode: "login",
      signedIn: true,
      role: "analyst",
    });
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
              condition: p.source_id === "paloalto_fw" ? "gap" : "healthy",
            })),
            source_summary: {
              total: 4,
              healthy: 3,
              quiet: [],
              gaps: 1,
              longest_wait: { source_id: "dns", last_event_at: "2026-10-10T12:26:00+00:00" },
            },
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
    const tab = await within(
      await screen.findByRole("navigation", { name: "Health tabs" }),
    ).findByRole("link", { name: /^Sources/ });
    await within(tab).findByText("4");
    const flow = await screen.findByRole("list", { name: "Sources" });
    for (const id of ["paloalto_fw", "unifi", "dns", "m365"])
      expect(within(flow).getByText(id)).toBeVisible();
    const fw = within(flow).getByText("paloalto_fw").closest("li") as HTMLElement;
    expect(
      within(fw).getByText(/^No events .+\(5 h\)\. Other sources kept flowing\.$/),
    ).toBeVisible();
    expect(screen.queryByText(/No sources yet/)).toBeNull();
    // Enrichment feeds are a Type of Sources, with their own count; the tab counts log
    // sources only, as the Dashboard's Sources tile does.
    const type = screen.getByRole("group", { name: "Type" });
    expect(within(type).getByRole("button", { name: /^Log sources/ })).toHaveTextContent(/4$/);
    expect(within(type).getByRole("button", { name: /^Enrichment feeds/ })).not.toHaveTextContent(
      /4$/,
    );
    const events = screen.getByRole("button", { name: /^Events, last 24 hours/ });
    expect(events).toHaveTextContent("Not enough history yet (2 of 7 days)");
  });
});

describe("Health in three tabs, and Settings > System (ADR-0052 section 3.3, redesign build row 12)", () => {
  it.each([
    ["/health/enrichment", "/health#type=enrichment"],
    ["/health#enrichment", "/health#type=enrichment"],
    ["/health/agents", "/health/collectors"],
    ["/health/devices", "/health/collectors#type=devices"],
    ["/health/alerts", "/health/delivery"],
    ["/health#alerts", "/health/delivery"],
    ["/health/backups", "/system"],
    ["/health/rollups", "/system#type=rollups"],
    ["/health/speed", "/system#type=speed"],
    ["/health/sources", "/health"],
    ["/health/alerts?from=mail", "/health/delivery?from=mail"],
  ])("sends the old address %s to %s", async (old, now) => {
    const { canonical } = await import("@/lib/route");
    window.history.replaceState(null, "", old);
    expect(canonical()).toBe(now);
  });

  it("leaves a link to one source alone", async () => {
    const { canonical } = await import("@/lib/route");
    window.history.replaceState(null, "", "/health#source=linux_sshd");
    expect(canonical()).toBeNull();
  });

  it("lists enrichment feeds as a Type of Sources", async () => {
    await renderAt("/health/enrichment");
    const type = await screen.findByRole("group", { name: "Type" });
    expect(within(type).getByRole("button", { name: /^Enrichment feeds/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(await screen.findByRole("region", { name: "Enrichment feeds" })).toBeVisible();
    await userEvent.click(within(type).getByRole("button", { name: /^Log sources/ }));
    expect(window.location.pathname + window.location.hash).toBe("/health");
  });

  it("puts System in Settings for administrators only, with Backups first", async () => {
    await renderAt("/system");
    expect(await screen.findByRole("heading", { name: "System", level: 1 })).toBeVisible();
    const type = screen.getByRole("group", { name: "Type" });
    expect(
      within(type)
        .getAllByRole("button")
        .map((b) => b.textContent?.replace(/\d+$/g, "").trim()),
    ).toEqual(["Backups", "Page rollups", "Speed"]);
    expect(within(type).getByRole("button", { name: /^Backups/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // No Health strip here.
    expect(screen.queryByRole("button", { name: /^Events, last 24 hours/ })).toBeNull();
    const settings = screen.getByRole("navigation", { name: "Settings" });
    expect(within(settings).getByRole("link", { name: "System" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it.each(["analyst", "auditor"] as const)(
    "tells an %s that System is for administrators, also from an old Health address",
    async (role) => {
      const spy = await renderAt("/health/backups", { mode: "login", signedIn: true, role });
      await vi.waitFor(() => expect(window.location.pathname).toBe("/system"));
      expect(await screen.findByRole("heading", { name: "System", level: 1 })).toBeVisible();
      const box = (await screen.findByText("For administrators")).closest(
        "[data-empty]",
      ) as HTMLElement;
      expect(box).toHaveAttribute("data-empty", "restricted");
      expect(box).toHaveTextContent("A failed backup raises an alert that everyone sees.");
      // None of the lists, no way in from the menus, and nothing asked of the server for them.
      expect(screen.queryByRole("group", { name: "Type" })).toBeNull();
      expect(screen.queryByRole("link", { name: "System" })).toBeNull();
      expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/health-checks"))).toBe(false);
    },
  );

  it("asks only for the checks on System: none of Health's other reads", async () => {
    const spy = await renderAt("/system");
    await screen.findByRole("table", { name: "Backups" });
    const asked = spy.mock.calls.map(([u]) => String(u));
    expect(asked.some((u) => u.endsWith("/api/health-checks"))).toBe(true);
    for (const path of [
      "/api/overview",
      "/api/alerts/lines",
      "/api/enrichment",
      "/api/alert-targets",
    ])
      expect(
        asked.some((u) => u.includes(path)),
        path,
      ).toBe(false);
  });

  it.each(["/health#constructor", "/health/toString", "/health#__proto__", "/ai#constructor"])(
    "opens the page for an address that names no tab (%s)",
    async (address) => {
      const { canonical, pageFromPath } = await import("@/lib/route");
      window.history.replaceState(null, "", address);
      expect(() => canonical()).not.toThrow();
      expect(["health", "ai", "overview"]).toContain(pageFromPath(address.split("#")[0] as string));
      await renderAt(address);
      expect(await screen.findByRole("navigation", { name: "Primary" })).toBeVisible();
      expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
    },
  );

  it("counts sources as the Dashboard does when quarantined files add a notice", async () => {
    await renderAt("/health", undefined, (s) => {
      const real = s.getMockImplementation() as typeof fetch;
      s.mockImplementation(async (url, init) => {
        const res = await real(url, init);
        if (!String(url).endsWith("/api/health-checks")) return res;
        const body = await res.json();
        return new Response(JSON.stringify({ ...body, quarantined_files: 2 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      });
    });
    const flow = await screen.findByRole("list", { name: "Sources" });
    const tab = within(await screen.findByRole("navigation", { name: "Health tabs" })).getByRole(
      "link",
      { name: /^Sources/ },
    );
    const type = within(screen.getByRole("group", { name: "Type" })).getByRole("button", {
      name: /^Log sources/,
    });
    // The count is of sources: the quarantine notice is not one.
    await vi.waitFor(() => {
      const listed = within(flow).getAllByRole("listitem").length;
      expect(type.textContent).toBe(`Log sources ${listed}`);
      expect(tab.textContent).toMatch(new RegExp(`^Sources${listed}`));
    });
  });
});
