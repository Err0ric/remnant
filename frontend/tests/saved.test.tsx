import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";
import { setSql } from "./sqlEditor";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "analyst" },
) {
  window.history.replaceState(null, "", path);
  window.localStorage.setItem("search-tab", "sql");
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

function bodies(spy: ReturnType<typeof mockApi>, test: (url: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === "POST")
    .map(([, init]) => init?.body);
}

afterEach(() => vi.restoreAllMocks());

describe("Saving a search", () => {
  it("turns {{placeholders}} into typed parameters", async () => {
    const spy = await renderAt("/search");
    await screen.findByRole("heading", { name: "Search", level: 1 });
    setSql("SELECT * FROM events WHERE time > {{start}} LIMIT {{top}}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const form = screen.getByRole("form", { name: "Save search" });
    await userEvent.type(within(form).getByLabelText("Name"), "Recent Events!");
    expect(within(form).getByText("Id: recent_events")).toBeInTheDocument();
    expect(within(form).queryByLabelText("Type of start")).not.toBeInTheDocument();
    await userEvent.selectOptions(within(form).getByLabelText("Type of top"), "int");
    await userEvent.type(within(form).getByLabelText("Default for top"), "5");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved as recent_events");
    const sent = JSON.parse(String(bodies(spy, (u) => u.endsWith("/api/searches"))[0])) as {
      id: string;
      params: unknown[];
      visibility: string;
    };
    expect(sent.id).toBe("recent_events");
    expect(sent.visibility).toBe("private");
    expect(sent.params).toEqual([{ name: "top", type: "int", default: 5 }]);
  });

  it("is not offered to auditors", async () => {
    await renderAt("/search", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("heading", { name: "Search", level: 1 });
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });
});

describe("Saved searches page", () => {
  it("shows the Ask question a search came from, as text", async () => {
    await renderAt("/saved");
    expect(await screen.findByText("From Ask: which IPs failed SSH the most?")).toBeInTheDocument();
  });

  it("runs a search with its default parameters", async () => {
    const spy = await renderAt("/saved");
    await userEvent.click(await screen.findByRole("button", { name: "Run Failed SSH by source" }));
    const runner = screen.getByRole("region", { name: "Run Failed SSH by source" });
    expect(within(runner).getByLabelText("top")).toHaveValue("25");
    await userEvent.click(within(runner).getByRole("button", { name: "Run" }));
    expect(await within(runner).findByText("203.0.113.9")).toBeInTheDocument();
    const sent = JSON.parse(String(bodies(spy, (u) => u.endsWith("/run"))[0])) as {
      params: Record<string, string>;
      start: string;
    };
    expect(sent.params).toEqual({ top: "25" });
    expect(sent.start).toBeTruthy();
  });

  it("only offers delete on your own searches unless you are an admin", async () => {
    await renderAt("/saved");
    await screen.findByText("Failed SSH by source");
    expect(
      screen.queryByRole("button", { name: "Delete Failed SSH by source" }),
    ).not.toBeInTheDocument();
  });

  it("lets admins delete after confirming", async () => {
    await renderAt("/saved", { mode: "login", signedIn: true, role: "admin" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete Failed SSH by source" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText("Failed SSH by source")).not.toBeInTheDocument());
  });

  it("imports a YAML file as a private search", async () => {
    const spy = await renderAt("/saved");
    await screen.findByText("Failed SSH by source");
    const input = screen.getByLabelText("Import file");
    await userEvent.upload(
      input,
      new File(["schema_version: 1\nid: x\n"], "x.yaml", { type: "application/yaml" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported imported_one as a private search",
    );
    const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/searches/import"));
    expect((call?.[1]?.headers as Record<string, string>)["Content-Type"]).toBe("application/yaml");
  });

  it("lets admins mark shared searches verified", async () => {
    await renderAt("/saved", { mode: "login", signedIn: true, role: "admin" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Verify Failed SSH by source" }),
    );
    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Unverify Failed SSH by source" }),
    ).toBeInTheDocument();
  });

  it("does not offer verification to analysts", async () => {
    await renderAt("/saved");
    await screen.findByRole("button", { name: "Run Failed SSH by source" });
    expect(screen.queryByRole("button", { name: /^Verify/ })).not.toBeInTheDocument();
  });
});
