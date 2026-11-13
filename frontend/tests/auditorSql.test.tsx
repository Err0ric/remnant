import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

const auditor: MockAuth = { mode: "login", signedIn: true, role: "auditor" };

async function renderAt(path: string, auth: MockAuth = { mode: "login", signedIn: true }) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", auth);
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

function calls(spy: ReturnType<typeof mockApi>, path: string) {
  return spy.mock.calls.filter(([url]) => String(url).endsWith(path));
}

afterEach(() => vi.restoreAllMocks());

describe("Auditors and SQL (D220)", () => {
  it("shows an Auditor a plain explanation on Logs, with no editor, while it is off", async () => {
    const spy = await renderAt("/search", auditor);
    const notice = await screen.findByRole("region", { name: "SQL not available" });
    expect(notice).toHaveTextContent("Auditors cannot run SQL on this install");
    expect(within(notice).getByRole("button", { name: "Open the audit log" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export CSV" })).not.toBeInTheDocument();
    expect(calls(spy, "/api/query")).toHaveLength(0);
  });

  it("hides Ask from an Auditor while it is off", async () => {
    await renderAt("/search", auditor);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await screen.findByRole("region", { name: "SQL not available" });
    expect(within(nav).queryByText("Ask AI")).not.toBeInTheDocument();
  });

  it("disables Run on saved searches for an Auditor and says why", async () => {
    await renderAt("/saved", auditor);
    const run = await screen.findByRole("button", { name: "Run Failed SSH by source" });
    expect(run).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("Auditors cannot run SQL");
  });

  it("gives an Auditor Logs, Ask, and Run once an admin turns it on", async () => {
    await renderAt("/saved", { ...auditor, auditorSql: true });
    const run = await screen.findByRole("button", { name: "Run Failed SSH by source" });
    await waitFor(() => expect(run).toBeEnabled());
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Ask AI")).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("does not ask an analyst's browser for the setting", async () => {
    const spy = await renderAt("/saved", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("button", { name: "Run Failed SSH by source" });
    expect(calls(spy, "/api/settings/auditor-sql")).toHaveLength(0);
  });
});

describe("Auditor access setting", () => {
  it("lets an admin turn it on from Users and access", async () => {
    const spy = await renderAt("/users");
    const section = await screen.findByRole("region", { name: "Auditor access" });
    const box = within(section).getByRole("checkbox", { name: /Let Auditors run SQL/ });
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(box).toBeChecked());
    const put = calls(spy, "/api/settings/auditor-sql").find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ enabled: true });
  });

  it("is not on any page an analyst or Auditor can open", async () => {
    await renderAt("/users", auditor);
    await screen.findByRole("navigation", { name: "Primary" });
    expect(screen.queryByRole("region", { name: "Auditor access" })).not.toBeInTheDocument();
  });
});
