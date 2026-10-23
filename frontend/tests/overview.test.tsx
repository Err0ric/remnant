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

describe("Health: the former Overview (F55, ADR-0034 row 11)", () => {
  it("answers am I blind: totals, every source's flow, and gaps in words", async () => {
    await renderAt("/overview");
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeVisible();
    expect(window.location.pathname + window.location.hash).toBe("/health#sources");
    const events = await screen.findByRole("button", { name: /^Events, last 24 hours/ });
    expect(events).toHaveTextContent("70");
    expect(events).toHaveTextContent("+25% vs a usual day");
    const sources = screen.getByRole("button", { name: /^Sources/ });
    expect(sources).toHaveTextContent("1 gap in 24 hours");
    const delivery = screen.getByRole("button", { name: /^Alert delivery/ });
    expect(delivery).toHaveTextContent("Failing: SOC Slack");
    const flow = await screen.findByRole("list", { name: "Sources" });
    const row = within(flow).getByText("linux_sshd").closest("li") as HTMLElement;
    expect(row).toHaveTextContent("30"); // 24 h total, printed
    expect(row).toHaveTextContent("2.4"); // per minute, printed
    expect(
      within(row).getByText(/^No events .+ \(5 h\)\. Other sources kept flowing\.$/),
    ).toBeVisible();
    expect(within(row).getByRole("img", { name: /linux_sshd: events per hour/ })).toBeVisible();
    const status = screen.getByRole("region", { name: "Detections and schedules" });
    expect(within(status).getByText("Failed logon")).toBeVisible();
    expect(within(status).getByText("Nightly sudo")).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByRole("link", { name: "Overview" })).toBeNull();
  });

  it("opens a rule detection from the status card", async () => {
    await renderAt("/health");
    const status = await screen.findByRole("region", { name: "Detections and schedules" });
    await userEvent.click(within(status).getByRole("button", { name: "Failed logon" }));
    expect(await screen.findByRole("heading", { name: "Detection rules", level: 1 })).toBeVisible();
  });

  it("shows alert delivery to admins only", async () => {
    await renderAt("/health", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("button", { name: /^Events, last 24 hours/ });
    expect(screen.queryByRole("button", { name: /^Alert delivery/ })).toBeNull();
  });

  it("opens a source's Health row from a link, then its settings with the same gap (F61)", async () => {
    await renderAt("/health#source=linux_sshd");
    const flow = await screen.findByRole("list", { name: "Sources" });
    const row = within(flow).getByText("linux_sshd").closest("li") as HTMLElement;
    await vi.waitFor(() => expect(row).toHaveAttribute("aria-current", "true"));
    await userEvent.click(within(row).getByRole("button", { name: "linux_sshd" }));
    expect(window.location.pathname + window.location.hash).toBe("/sources#source=linux_sshd");
    const setting = await vi.waitFor(() => {
      const tr = document.getElementById("source-linux_sshd");
      if (!tr) throw new Error("not yet");
      return tr;
    });
    expect(setting).toHaveAttribute("aria-current", "true");
    expect(
      await within(setting).findByText(/^No events .+ \(5 h\)\. Other sources kept flowing\.$/),
    ).toBeVisible();
    expect(within(setting).getByRole("link", { name: "Show on Health" })).toHaveAttribute(
      "href",
      "/health#source=linux_sshd",
    );
  });

  it("writes gaps in local time, naming the day only when it is not today", async () => {
    const { gapText, changeText } = await import("@/features/health/flow");
    const zone = "America/Los_Angeles";
    const now = "2026-10-22T21:00:00+00:00"; // 2 PM there
    const gap = {
      start: "2026-10-22T09:00:00+00:00",
      end: "2026-10-22T14:00:00+00:00",
      hours: 5,
      ongoing: false,
      others_flowing: true,
    };
    expect(gapText(gap, now, zone)).toBe(
      "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing.",
    );
    expect(gapText({ ...gap, end: null, ongoing: true, others_flowing: false }, now, zone)).toBe(
      "No events since 2:00 AM (5 h so far).",
    );
    expect(gapText({ ...gap, start: "2026-10-22T05:00:00+00:00" }, now, zone)).toBe(
      "No events yesterday 10:00 PM to 7:00 AM (5 h). Other sources kept flowing.",
    );
    expect(changeText(70, 56)).toBe("+25% vs a usual day");
    expect(changeText(70, null)).toBeNull();
  });

  it("goes home from the product mark: the Dashboard when there are panels", async () => {
    await renderAt("/schedules");
    await userEvent.click(await screen.findByRole("link", { name: "Codename home" }));
    expect(await screen.findByRole("heading", { name: "My dashboard", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/dashboard");
  });

  it("keeps the setup checklist in Settings, not on Health", async () => {
    await renderAt("/health");
    await screen.findByRole("button", { name: /^Events, last 24 hours/ });
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
    (String(url).endsWith("/api/schedules") || String(url).endsWith("/api/dashboards")) &&
    (init?.method ?? "GET") === "GET"
      ? Promise.resolve(new Response("[]", { headers: { "Content-Type": "application/json" } }))
      : (real as typeof fetch)(url, init),
  );
}

describe("Landing page (ADR-0031)", () => {
  it("opens the Dashboard first when there is a panel, with sources in the morning answer", async () => {
    await renderAt("/");
    expect(await screen.findByRole("heading", { name: "My dashboard", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/dashboard");
    const health = await screen.findByRole("region", { name: "This morning" });
    expect(await within(health).findByRole("button", { name: /has errors/ })).toBeVisible();
    expect(health).toHaveTextContent("1 gap in 24 hours");
    await userEvent.click(within(health).getByRole("button", { name: "Open Health" }));
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeVisible();
  });

  it("opens Health when there are no panels", async () => {
    await renderAt("/", undefined, noSchedules);
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/health");
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
