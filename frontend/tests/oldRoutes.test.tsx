import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OLD_ADDRESSES, PAGE_TABS, PATHS, canonical, pageFromPath, type PageId } from "@/lib/route";
import { mockApi, type MockAuth } from "./mockApi";

/** Every old address (each key of `OLD_ADDRESSES`) and where it must land, with a query
 * string and a fragment where the old address carried state. */
const OLD: [string, string][] = [
  ["/investigate", "/investigate/people"],
  ["/investigate/", "/investigate/people"],
  ["/investigate?from=mail#user=alice", "/investigate/people?from=mail#user=alice"],
  ["/investigate/ask", "/ask-ai"],
  ["/investigate/ask#q=failed%20logins", "/ask-ai#q=failed%20logins"],
  ["/settings", "/sources"],
  ["/settings#source=fw", "/sources#source=fw"],
  ["/overview", "/health"],
  ["/search", "/investigate/logs"],
  ["/search?tab=sql#q=select", "/investigate/logs?tab=sql#q=select"],
  ["/investigate/search#tab=sql&q=x", "/investigate/logs#tab=sql&q=x"],
  ["/ask", "/ask-ai"],
  ["/saved", "/investigate/saved"],
  ["/rules", "/alerts/rules"],
  ["/schedules", "/alerts/schedules"],
  ["/investigations", "/investigate/people"],
  ["/investigations#ip=203.0.113.9", "/investigate/people#ip=203.0.113.9"],
  ["/alerts/open", "/alerts"],
  ["/alerts/closed", "/alerts#state=closed"],
  ["/alerts/closed?x=1#item=a1", "/alerts?x=1#state=closed&item=a1"],
  ["/alerts/muted", "/alerts#state=muted"],
  ["/alerts#open", "/alerts"],
  ["/alerts#closed", "/alerts#state=closed"],
  ["/alerts#muted", "/alerts#state=muted"],
  ["/ai/settings", "/ai/inventory"],
  ["/ai#settings", "/ai/inventory"],
  ["/ai/watch", "/ai-settings"],
  ["/ai#agents", "/agents"],
  ["/ai#mcp", "/agents/mcp"],
  ["/agents/overview", "/agents"],
  ["/agents#overview", "/agents"],
  ["/agents/tools", "/agents/mcp"],
  ["/agents#tools", "/agents/mcp"],
  ["/health/enrichment", "/health#type=enrichment"],
  ["/health#enrichment", "/health#type=enrichment"],
  ["/health/agents", "/health/collectors"],
  ["/health#agents", "/health/collectors"],
  ["/health/devices", "/health/collectors#type=devices"],
  ["/health#devices", "/health/collectors#type=devices"],
  ["/health/alerts", "/health/delivery"],
  ["/health#alerts", "/health/delivery"],
  ["/health/backups", "/system"],
  ["/health#backups", "/system"],
  ["/health/rollups", "/system#type=rollups"],
  ["/health#rollups", "/system#type=rollups"],
  ["/health/speed", "/system#type=speed"],
  ["/health#speed", "/system#type=speed"],
  ["/health#integrity", "/audit/integrity"],
  ["/m365", "/investigate/views"],
  ["/m365#user=alice", "/investigate/views#user=alice"],
  ["/m365/overview", "/investigate/views"],
  ["/m365#overview", "/investigate/views"],
  ["/m365/sign-ins", "/investigate/views"],
  ["/m365#sign-ins", "/investigate/views"],
  ["/m365/mail", "/investigate/views/mail"],
  ["/m365#mail", "/investigate/views/mail"],
  ["/m365/admin", "/investigate/views/admin"],
  ["/m365#admin", "/investigate/views/admin"],
  ["/m365/apps", "/ai/inventory#type=m365_app"],
  ["/m365#apps", "/ai/inventory#type=m365_app"],
  // Tabs named by their old `#word`, from before tabs had paths: no table entry needed.
  ["/health#delivery", "/health/delivery"],
  ["/health#sources", "/health"],
  ["/audit#integrity", "/audit/integrity"],
  ["/ai#inventory", "/ai/inventory"],
  // A trailing slash on a page of today.
  ["/investigate/people/", "/investigate/people"],
];

/** Every page and tab address of today, with the page it opens. */
const CURRENT: [string, PageId][] = [
  ["/", "home"],
  ["/investigate/logs", "logs"],
  ["/ask-ai", "ask"],
  ["/sources", "sources"],
  ["/templates", "templates"],
  ["/users", "users"],
  ["/providers", "providers"],
  ["/me", "me"],
  ["/investigate/saved", "saved"],
  ["/investigate/library", "library"],
  ["/alerts/rules", "rules"],
  ["/alerts/schedules", "schedules"],
  ["/dashboard", "dashboard"],
  ["/alerts", "alerts"],
  ["/alerts/handling", "handling"],
  ["/alert-targets", "targets"],
  ["/ai", "ai"],
  ["/ai/people", "ai"],
  ["/ai/inventory", "ai"],
  ["/investigate/people", "investigate"],
  ["/agents", "agents"],
  ["/agents/mcp", "agents"],
  ["/agents/accounts", "agents"],
  ["/investigate/views", "m365"],
  ["/investigate/views/mail", "m365"],
  ["/investigate/views/admin", "m365"],
  ["/plugins", "plugins"],
  ["/sso", "sso"],
  ["/identities", "identities"],
  ["/setup", "setup"],
  ["/health", "health"],
  ["/health/collectors", "health"],
  ["/health/delivery", "health"],
  ["/system", "system"],
  ["/ai-settings", "aisettings"],
  ["/mcp-server", "mcp"],
  ["/enrichment", "enrichment"],
  ["/audit", "audit"],
  ["/audit/ai", "audit"],
  ["/audit/integrity", "audit"],
  ["/about", "about"],
  ["/account", "account"],
];

const UNKNOWN = [
  "/no-such-page",
  "/investigate/nothing",
  "/settings/users",
  "/health/constructor",
  "/m365/other",
  "/alerts/someid",
  "/constructor",
  `/${"a".repeat(200)}`,
];

function at(address: string) {
  window.history.replaceState(null, "", address);
}
const address = () => window.location.pathname + window.location.search + window.location.hash;

afterEach(() => {
  vi.restoreAllMocks();
  at("/");
});

describe("Old addresses (ADR-0052 section 3.4; owner, 2026-11-16)", () => {
  it.each(OLD)("%s lands on %s, keeping the query string and the fragment", (from, to) => {
    at(from);
    expect(canonical()).toBe(to);
    at(to);
    expect(canonical()).toBeNull(); // the new address is final: no second hop
    expect(pageFromPath(window.location.pathname)).not.toBe("notfound");
  });

  it("tests every entry of the table, so it cannot go stale", () => {
    const tested = new Set(OLD.map(([from]) => from.replace(/\?[^#]*/, "")));
    const missing = Object.keys(OLD_ADDRESSES).filter(
      (key) => !tested.has(key) && ![...tested].some((t) => t.startsWith(`${key}#`)),
    );
    expect(missing).toEqual([]);
  });
});

describe("Addresses of today", () => {
  it.each(CURRENT)("%s opens its own page (%s) and stays", (path, page) => {
    at(path);
    expect(pageFromPath(path)).toBe(page);
    expect(canonical()).toBeNull();
  });

  it("lists every page and tab of the route table, so a new route needs a case", () => {
    const listed = new Set(CURRENT.map(([path]) => path));
    const routes = (Object.keys(PATHS) as PageId[])
      .filter((id) => id !== "notfound")
      .flatMap((id) => [
        PATHS[id],
        ...(PAGE_TABS[id] ?? []).slice(1).map((tab) => `${PATHS[id]}/${tab}`),
      ]);
    expect(routes.filter((r) => !listed.has(r))).toEqual([]);
    expect([...listed].filter((r) => !routes.includes(r))).toEqual([]);
  });

  it.each(UNKNOWN)("%s is not found, and its address stays as typed", (path) => {
    at(path);
    expect(pageFromPath(path)).toBe("notfound");
    expect(canonical()).toBeNull();
  });
});

async function renderAt(path: string, role: MockAuth["role"] = "admin", auditorSql = false) {
  at(path);
  mockApi("Codename", { mode: "login", signedIn: true, role, auditorSql });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
}

describe("Old addresses in the app (owner, 2026-11-16)", () => {
  it.each([
    ["/investigate", "/investigate/people", "People & devices"],
    ["/investigations#user=alice", "/investigate/people#user=alice", "alice"],
    ["/settings", "/sources", "Sources"],
    ["/investigate/ask", "/ask-ai", "Ask AI"],
  ])("%s opens %s, replacing the old address in history", async (from, to, title) => {
    const before = window.history.length;
    await renderAt(from);
    await screen.findByRole("heading", { level: 1, name: title });
    await waitFor(() => expect(address()).toBe(to));
    expect(window.history.length).toBe(before); // replaced: Back does not bounce
    expect(screen.queryByRole("heading", { level: 1, name: "Health" })).toBeNull();
  });
});

describe("Page not found", () => {
  it.each(["admin", "analyst", "auditor"] as const)(
    "shows the shell, the address as text, and a link home, for an %s",
    async (role) => {
      await renderAt("/no-such-page?x=1#y", role);
      await screen.findByRole("heading", { level: 1, name: "Page not found" });
      expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
      const main = screen.getByRole("main");
      expect(within(main).getByText("There is no page at")).toBeInTheDocument();
      expect(main.querySelector("[data-truncate]")).toHaveAttribute("title", "/no-such-page");
      expect(within(main).getByRole("link", { name: "Go to the Dashboard" })).toHaveAttribute(
        "href",
        "/dashboard",
      );
      expect(address()).toBe("/no-such-page?x=1#y"); // not a redirect
    },
  );

  it("draws a long or hostile address as text, cut in the middle, and goes home on click", async () => {
    const long = `/${"<b>x</b>".repeat(25)}`;
    await renderAt(long);
    await screen.findByRole("heading", { level: 1, name: "Page not found" });
    const main = screen.getByRole("main");
    expect(main.querySelector("b")).toBeNull();
    const cut = main.querySelector("[data-truncate]");
    expect(cut).toHaveAttribute("title", decodeURI(long));
    expect(cut?.querySelector("[data-part='tail']")?.textContent).toBe("<b>x</b>");
    await userEvent.click(within(main).getByRole("link", { name: "Go to the Dashboard" }));
    await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
    expect(window.location.pathname).toBe("/dashboard");
  });
});

describe("Pages a role cannot use keep today's rule (DESIGN.md 6.1)", () => {
  it("an Auditor opening Ask AI, by its address or an old one, lands on Logs", async () => {
    await renderAt("/investigate/ask", "auditor");
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
  });

  it("Logs > Library opens by its address; an Analyst gets every action", async () => {
    await renderAt("/investigate/library", "analyst");
    await screen.findByRole("region", { name: "Linux sign-ins and privilege" });
    expect(
      await screen.findByRole("button", { name: "Save SSH logins by user and source as my own" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add SSH logins by user and source to the dashboard" }),
    ).toBeInTheDocument();
    expect(address()).toBe("/investigate/library");
    // Not an admin: the Needs sources card says whom to ask, with no link to Sources.
    const needs = screen.getByRole("region", { name: "Needs sources you don't have" });
    expect(within(needs).getByText(/Ask an admin to add or share a source\./)).toBeVisible();
    expect(within(needs).queryByRole("link", { name: "Add a source" })).toBeNull();
  });

  it("an Auditor with SQL may open queries from the Library but not save or add them", async () => {
    await renderAt("/investigate/library", "auditor", true);
    expect(
      await screen.findByRole("button", { name: "Run SSH logins by user and source in Logs" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /as my own|to the dashboard/ })).toBeNull();
  });

  it("an Auditor without SQL has no Library tab, and its address says SQL is off", async () => {
    await renderAt("/investigate/library", "auditor");
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(screen.queryByRole("link", { name: "Library" })).toBeNull();
    expect(screen.queryByRole("heading", { level: 1, name: "Page not found" })).toBeNull();
  });

  it("an Analyst opening the audit log sees Logs, not Page not found", async () => {
    await renderAt("/audit", "analyst");
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(screen.queryByRole("heading", { level: 1, name: "Page not found" })).toBeNull();
  });

  it("an Analyst opening an administrators' page sees Logs, not Page not found", async () => {
    await renderAt("/users", "analyst");
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(screen.queryByRole("heading", { level: 1, name: "Page not found" })).toBeNull();
  });
});
