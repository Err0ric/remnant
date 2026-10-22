import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

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

describe("Overview", () => {
  it("shows volume, ingest health, detections, and pauses", async () => {
    await renderAt("/overview");
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
    const volume = await screen.findByRole("region", { name: "Event volume" });
    expect(within(volume).getByText("88 events · last 24 hours")).toBeVisible();
    const rows = within(volume).getAllByRole("row");
    // Sources with unusual hours come first, then the busiest.
    expect(within(rows[1]!).getByText("win_dc")).toBeVisible();
    expect(within(rows[1]!).getByText("1 busy")).toBeVisible();
    expect(within(rows[2]!).getByText("linux_sshd")).toBeVisible();
    // Each hour is a cell that says its count, its usual count, and its mark.
    const cell = within(volume).getByRole("button", {
      name: /^win_dc, .* UTC: 40 events, usually 2, busier than usual\. Open in Search$/,
    });
    await userEvent.hover(cell);
    expect(await within(volume).findByRole("tooltip")).toHaveTextContent(
      /UTC 40 events, usually 2, busier than usual/,
    );
    const ingest = screen.getByRole("region", { name: "Ingest health" });
    expect(within(ingest).getByText("1 with errors · 1 quiet")).toBeVisible();
    expect(within(ingest).getByText("Quiet")).toBeVisible(); // win_dc's quiet-source alert
    expect(within(ingest).getByText("Received 4 min ago")).toBeVisible();
    expect(within(ingest).getByText("Nothing received in 7 days")).toBeVisible();
    const paused = screen.getByRole("region", { name: "Paused schedules" });
    expect(within(paused).getByText(/saved search changed/)).toBeVisible();
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens a rule detection's matches in Search", async () => {
    await renderAt("/overview");
    const detections = await screen.findByRole("region", { name: "Detections" });
    await userEvent.click(within(detections).getByRole("button", { name: "Failed logon" }));
    expect(await screen.findByRole("heading", { name: "Search", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/search");
  });

  it("opens a source and hour from the heatmap in Search", async () => {
    await renderAt("/overview");
    const volume = await screen.findByRole("region", { name: "Event volume" });
    await userEvent.click(within(volume).getByRole("button", { name: /^win_dc, .*busier/ }));
    expect(await screen.findByRole("heading", { name: "Search", level: 1 })).toBeVisible();
    expect(document.body.textContent).toContain("source_id = 'win_dc'");
  });

  it("shows alert delivery to admins only", async () => {
    await renderAt("/overview");
    const alerts = await screen.findByRole("region", { name: "Alert delivery" });
    expect(within(alerts).getByText("Failing")).toBeVisible();
    expect(within(alerts).getByText("2 deliveries failed after every retry")).toBeVisible();
  });

  it("hides alert delivery from analysts", async () => {
    await renderAt("/overview", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("region", { name: "Detections" });
    expect(screen.queryByRole("region", { name: "Alert delivery" })).toBeNull();
  });

  it("goes home from the product mark: the Dashboard when there are panels", async () => {
    await renderAt("/schedules");
    await userEvent.click(await screen.findByRole("link", { name: "Codename home" }));
    expect(await screen.findByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/dashboard");
  });

  it("keeps the setup checklist in Settings, not on the Overview", async () => {
    await renderAt("/overview");
    await screen.findByRole("region", { name: "Event volume" });
    expect(screen.queryByRole("region", { name: "Required steps" })).toBeNull();
  });

  it("lists setup steps in Settings, with optional steps kept apart", async () => {
    // No alert targets yet: one core step is left.
    await renderAt("/setup", undefined, (spy) => {
      const real = spy.getMockImplementation();
      spy.mockImplementation((url, init) =>
        String(url).endsWith("/api/alert-targets") && (init?.method ?? "GET") === "GET"
          ? Promise.resolve(new Response("[]", { headers: { "Content-Type": "application/json" } }))
          : (real as typeof fetch)(url, init),
      );
    });
    const core = await screen.findByRole("region", { name: "Required steps" });
    expect(await within(core).findByText(/ of 7 left$/)).toBeVisible();
    // AI usage is the lead feature, so its setup steps are core steps (QA F13).
    for (const name of ["Collect AI telemetry", "Review AI services", "Turn on the AI watch"]) {
      expect(within(core).getByRole("button", { name })).toBeVisible();
    }
    const add = within(core).getByRole("button", { name: "Add a log source" });
    expect(add.closest("li")).toHaveTextContent("(done)");
    const alerts = within(core).getByRole("button", { name: "Add an alert target" });
    expect(alerts.closest("li")).toHaveTextContent("(to do)");
    expect(screen.getByText("Optional").closest("details")).toHaveTextContent(
      "Connect Microsoft 365",
    );
  });

  it("keeps the setup checklist from analysts", async () => {
    await renderAt("/setup", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("region", { name: "Required steps" })).toBeNull();
  });
});

function noSchedules(spy: ReturnType<typeof mockApi>) {
  const real = spy.getMockImplementation();
  spy.mockImplementation((url, init) =>
    String(url).endsWith("/api/schedules") && (init?.method ?? "GET") === "GET"
      ? Promise.resolve(new Response("[]", { headers: { "Content-Type": "application/json" } }))
      : (real as typeof fetch)(url, init),
  );
}

describe("Landing page (ADR-0031)", () => {
  it("opens the Dashboard first when there is a panel, with health on the first screen", async () => {
    await renderAt("/");
    expect(await screen.findByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/dashboard");
    const health = await screen.findByRole("region", { name: "Health" });
    expect(health).toHaveTextContent("1 source with errors");
    expect(health).toHaveTextContent("1 quiet source");
    await userEvent.click(within(health).getByRole("button", { name: "Open Overview" }));
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  });

  it("opens the Overview when there are no panels", async () => {
    await renderAt("/", undefined, noSchedules);
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/overview");
  });

  it("lists Dashboard first in the nav, once", async () => {
    await renderAt("/overview");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    const links = within(nav)
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(links[0]).toBe("Dashboard");
    expect(links.filter((t) => t === "Dashboard")).toHaveLength(1);
  });
});
