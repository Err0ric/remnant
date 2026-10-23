import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function openInvestigate(path = "/investigations") {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "open" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1, name: "Investigations" });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("Entity picker (F56)", () => {
  it("knows an address, a user, and a host from what is typed", async () => {
    const { kindOf } = await import("@/features/investigate/entityKind");
    expect(kindOf("203.0.113.9")).toBe("ip");
    expect(kindOf("2001:db8::1")).toBe("ip");
    expect(kindOf("alice@example.com")).toBe("user");
    expect(kindOf("EXAMPLE\\alice")).toBe("user");
    expect(kindOf("ws-0042")).toBe("host");
    expect(kindOf("999.1.1.1")).toBe("host");
    expect(kindOf("  ")).toBeNull();
  });

  it("starts on IP address, follows the input, keeps a picked type, and remembers it", async () => {
    window.localStorage.removeItem("investigate.kind");
    await openInvestigate();
    const type = screen.getByRole("combobox", { name: "Entity type" });
    const box = screen.getByRole("textbox", { name: "Entity" });
    expect(type).toHaveValue("ip");
    expect(box).toHaveAttribute("placeholder", "203.0.113.9");
    await userEvent.type(box, "alice@example.com");
    expect(type).toHaveValue("user");
    expect(box).toHaveAttribute("placeholder", "alice@example.com");
    await userEvent.clear(box);
    await userEvent.type(box, "ws-0042");
    expect(type).toHaveValue("host");
    await userEvent.selectOptions(type, "user"); // an override sticks while typing
    await userEvent.type(box, "x");
    expect(type).toHaveValue("user");
    await userEvent.click(screen.getByRole("button", { name: "Investigate" }));
    expect(window.localStorage.getItem("investigate.kind")).toBe("user");
  });
});

describe("Entity pages from a link (product pass step 2)", () => {
  it("opens the entity in the address, and Back to all entities clears it", async () => {
    const spy = await openInvestigate("/investigations#ip=203.0.113.9");
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
      expect(String(call?.[0])).toContain("kind=ip");
      expect(String(call?.[0])).toContain("value=203.0.113.9");
    });
    expect(screen.getByRole("textbox", { name: "Entity" })).toHaveValue("203.0.113.9");
    // The page leads with the answer, then numbers, then what it did with real values.
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(
      await within(summary).findByText(
        "2,619 failed sign-ins against ftp-01 over the last 7 days, 0 succeeded. From Netherlands, AS64500 Example Net.",
      ),
    ).toBeVisible();
    const acts = within(summary).getByRole("list", { name: "Activities" });
    expect(
      within(acts).getByText("Failed password for root from 203.0.113.9 port 52144 ssh2"),
    ).toBeVisible();
    expect(within(acts).getByRole("link", { name: "ftp-01" })).toHaveAttribute(
      "href",
      "/investigations#host=ftp-01",
    );
    expect(within(summary).getByRole("heading", { name: /Users tried/ })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /All entities/ }));
    expect(window.location.hash).toBe("");
  });

  it("opens an AI service in the AI flow", async () => {
    const spy = await openInvestigate("/investigations#service=chatgpt");
    expect(screen.getByRole("radio", { name: "AI flow" })).toHaveAttribute("aria-checked", "true");
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).includes("mode=ai"));
      expect(String(call?.[0])).toContain("value=chatgpt");
    });
  });
});

describe("Investigations (ADR-0016)", () => {
  it("ranks entities with the score's parts and opens one in lanes", async () => {
    const spy = await openInvestigate();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Investigations")).toHaveAttribute("aria-current", "page");
    const table = await screen.findByRole("table", { name: "User" });
    expect(within(table).getByText("4 high")).toBeVisible();
    await userEvent.click(within(table).getByRole("button", { name: "root" }));
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    for (const lane of ["Entity", "Sources", "Activities", "Targets"])
      expect(within(lanes).getByText(lane)).toBeInTheDocument();
    expect(within(lanes).getByText("2 more not shown (smaller ones)")).toBeInTheDocument();
    const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
    expect(String(call?.[0])).toContain("kind=user");
    expect(String(call?.[0])).toContain("value=root");
  });

  it("highlights a card's path and hands its events to Search", async () => {
    await openInvestigate();
    await userEvent.type(screen.getByLabelText("Entity"), "root");
    await userEvent.click(screen.getByRole("button", { name: "Investigate" }));
    const card = await screen.findByRole("button", { name: /Activities: Failed password/ });
    await userEvent.click(card);
    expect(card).toHaveAttribute("aria-pressed", "true");
    const other = screen.getByRole("button", { name: /Activities: Accepted publickey/ });
    expect(other.getAttribute("class")).toContain("opacity-40");
    const detail = screen.getByRole("region", { name: "Selected card" });
    expect(within(detail).getByText("Authentication")).toBeVisible();
    await userEvent.click(within(detail).getByRole("button", { name: "Open in Search" }));
    await screen.findByRole("heading", { level: 1, name: "Search" });
    expect(window.location.pathname).toBe("/search");
    // Search opens over the same range the investigation used (Last 7 days by default).
    expect(screen.getByLabelText("Time range")).toHaveValue("7d");
  });

  it("shows the AI flow with Not approved badges and follows a person", async () => {
    const spy = await openInvestigate();
    await userEvent.click(screen.getByRole("radio", { name: "AI flow" }));
    const lanes = await screen.findByRole("group", { name: /People, AI clients/ });
    const tool = within(lanes).getByRole("button", { name: /paste-share.*Not approved/ });
    expect(tool).toBeInTheDocument();
    await userEvent.click(within(lanes).getByRole("button", { name: /People: alice@example.com/ }));
    await userEvent.click(screen.getByRole("button", { name: "Investigate this" }));
    expect(await screen.findByText("Showing AI flow for")).toBeVisible();
    const last = spy.mock.calls.filter(([u]) => String(u).includes("/api/entities/graph")).at(-1);
    expect(String(last?.[0])).toContain("mode=ai");
    expect(String(last?.[0])).toContain("value=alice%40example.com");
  });

  it("renders attacker-controlled labels as text", async () => {
    await openInvestigate();
    await userEvent.type(screen.getByLabelText("Entity"), "<img src=x onerror=alert(1)>");
    await userEvent.click(screen.getByRole("button", { name: "Investigate" }));
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    expect(lanes.querySelector("img")).toBeNull();
    expect(within(lanes).getAllByText(/<img src=x/).length).toBeGreaterThan(0);
  });
});
