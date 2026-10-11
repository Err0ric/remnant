import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

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

function posts(spy: ReturnType<typeof mockApi>, suffix: string): unknown[] {
  return spy.mock.calls
    .filter(([u, init]) => String(u).endsWith(suffix) && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as unknown);
}

async function askQuestion(text: string) {
  await userEvent.type(await screen.findByLabelText("Question"), text);
  await userEvent.click(screen.getByRole("button", { name: /^(Ask|Refine)$/ }));
}

afterEach(() => vi.restoreAllMocks());

describe("Ask", () => {
  it("shows the generated SQL and does not run it until Run query is clicked", async () => {
    const spy = await renderAt("/ask");
    await screen.findByRole("tab", { name: "Ask in plain English", selected: true });
    await askQuestion("failed logins by source ip");
    expect(await screen.findByText(/Checked: the query runs and returns rows/)).toBeInTheDocument();
    expect(screen.getByText(/turn 1/)).toBeInTheDocument();
    const generated = () =>
      (posts(spy, "/api/query") as { sql: string }[]).filter((b) => b.sql.includes("turn 1"));
    expect(generated()).toHaveLength(0); // only the source picker's own lookup ran

    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByRole("region", { name: "Results" })).toBeInTheDocument();
    expect(generated()).toHaveLength(1);
  });

  it("also runs from the Run button beside the SQL, and only on click", async () => {
    const spy = await renderAt("/ask");
    await screen.findByRole("tab", { name: "Ask in plain English", selected: true });
    await askQuestion("failed logins by source ip");
    await screen.findByText(/Checked: the query runs and returns rows/);
    const generated = () =>
      (posts(spy, "/api/query") as { sql: string }[]).filter((b) => b.sql.includes("turn 1"));
    expect(generated()).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByRole("region", { name: "Results" })).toBeInTheDocument();
    expect(generated()).toHaveLength(1);
  });

  it("renders model text as plain text, labelled as model output", async () => {
    await renderAt("/ask");
    await askQuestion("failed logins");
    const panel = await screen.findByRole("region", { name: "Model explanation" });
    expect(
      within(panel).getByText("<b>Failed</b> logins grouped by source IP."),
    ).toBeInTheDocument();
    expect(panel.querySelector("b")).toBeNull();
    expect(within(panel).getByText("Failed means status_id = 2")).toBeInTheDocument();
    expect(within(panel).getByText(/Written by a model/)).toBeInTheDocument();
  });

  it("sends earlier turns on a follow-up and starts over on New question", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("failed logins");
    await screen.findByText(/turn 1/);
    await askQuestion("only from 203.0.113.9");
    await screen.findByText(/turn 2/);
    const [, second] = posts(spy, "/api/ask") as { history: { question: string }[] }[];
    expect(second?.history.map((t) => t.question)).toEqual(["failed logins"]);
    expect(
      within(screen.getByRole("list", { name: "Earlier questions" })).getAllByRole("listitem"),
    ).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "New question" }));
    expect(screen.queryByRole("region", { name: "Model explanation" })).not.toBeInTheDocument();
    await askQuestion("anything");
    const third = (posts(spy, "/api/ask") as { history: unknown[] }[])[2];
    expect(third?.history).toEqual([]);
  });

  it("explains a classification block", async () => {
    await renderAt("/ask");
    await screen.findByRole("option", { name: /Cloud · gpt-x/ });
    await userEvent.selectOptions(screen.getByLabelText("Model"), "p2");
    expect(screen.getByText("Cloud: local-only sources are blocked")).toBeInTheDocument();
    await askQuestion("failed logins");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /local-only sources: linux_sshd\. Choose a local provider/,
    );
  });

  it("saves with the question as origin", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("failed logins");
    await screen.findByText(/turn 1/);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const form = screen.getByRole("form", { name: "Save search" });
    await userEvent.type(within(form).getByLabelText("Name"), "Failed by IP");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await screen.findByRole("status");
    const [saved] = posts(spy, "/api/searches") as { mode: string; origin: unknown }[];
    expect(saved?.mode).toBe("ask");
    expect(saved?.origin).toEqual({ ask_prompt: "failed logins" });
  });

  it("is hidden from auditors", async () => {
    await renderAt("/ask", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("heading", { name: "Search", level: 1 });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Ask")).not.toBeInTheDocument();
  });
});
