import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reportMarkdown } from "@/features/explain/report";
import type { ExplainResponse } from "@/lib/api";
import { mockApi, type MockAuth } from "./mockApi";

const ID = "01a126d0-7c4f-7012-b6b0-e17359887d5f";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "analyst" },
) {
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

function explainBodies(spy: ReturnType<typeof mockApi>) {
  return spy.mock.calls
    .filter(([u, init]) => String(u).endsWith("/api/explain") && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

afterEach(() => vi.restoreAllMocks());

describe("Explain", () => {
  it("sends only the selected events and labels unverified claims", async () => {
    const spy = await renderAt("/search");
    const results = await screen.findByRole("region", { name: "Results" });
    const rows = await within(results).findAllByRole("row");
    await userEvent.click(rows[1]!); // first data row (row 0 is the header)
    await userEvent.click(await screen.findByRole("button", { name: "Select for Explain" }));
    await userEvent.click(within(results).getByRole("button", { name: "Explain 1 selected" }));
    const panel = await screen.findByRole("region", { name: "Explain events" });
    await userEvent.click(within(panel).getByRole("button", { name: "Explain" }));
    const claims = await within(panel).findByRole("list", { name: "Claims" });
    const items = within(claims).getAllByRole("listitem");
    expect(within(items[0]!).queryByText("unverified")).toBeNull();
    expect(within(items[1]!).getByText("unverified")).toBeInTheDocument();
    expect(items[1]?.querySelector("b")).toBeNull(); // model text is text, never markup
    expect(within(panel).getByText("Some claims are unverified")).toBeInTheDocument();
    expect(explainBodies(spy)).toEqual([{ event_ids: [ID], provider_id: "p1" }]);
  });

  it("explains the first rows when nothing is selected", async () => {
    const spy = await renderAt("/search");
    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findAllByRole("row");
    await userEvent.click(within(results).getByRole("button", { name: "Explain" }));
    const panel = await screen.findByRole("region", { name: "Explain events" });
    expect(within(panel).getByText("Explain 2 events")).toBeInTheDocument();
    await userEvent.type(within(panel).getByPlaceholderText("What happened here?"), "why?");
    await userEvent.click(within(panel).getByRole("button", { name: "Explain" }));
    await within(panel).findByRole("list", { name: "Claims" });
    expect(explainBodies(spy)[0]).toMatchObject({ question: "why?" });
    expect((explainBodies(spy)[0]?.event_ids as string[]).length).toBe(2);
  });

  it("is not offered to auditors", async () => {
    await renderAt("/search", { mode: "login", signedIn: true, role: "auditor" });
    const results = await screen.findByRole("region", { name: "Results" });
    await within(results).findAllByRole("row");
    expect(within(results).queryByRole("button", { name: /^Explain/ })).toBeNull();
  });
});

describe("reportMarkdown", () => {
  it("keeps every event reference and marks unverified claims", () => {
    const r: ExplainResponse = {
      claims: [
        { text: "A happened.", event_ids: ["e1", "e2"], verified: true },
        { text: "B\nhappened.", event_ids: [], verified: false },
      ],
      citation_check: "fail",
      call_id: "c9",
      events_sent: ["e1", "e2"],
      not_found: 0,
      sources: ["fw"],
      provider: { provider_id: "p", name: "Local", model: "m", locality: "local" },
    };
    const md = reportMarkdown(r, "Explanation: test", new Date("2026-10-11T08:00:00Z"));
    expect(md).toContain("1. A happened.\n   Events: `e1`, `e2`");
    expect(md).toContain("2. **Unverified.** B happened.\n   Events: none");
    expect(md).toContain("- `e1`\n- `e2`");
    expect(md).toContain("Model call: `c9`");
    expect(md).not.toContain(String.fromCharCode(0x2014)); // no em dash
  });
});
