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

describe("Ask (ADR-0042 slice 1a)", () => {
  it("runs the answer by its id, shows the rows, and keeps the SQL under How I got this", async () => {
    const spy = await renderAt("/ask");
    expect(
      await screen.findByRole("button", { name: "Ask in plain English", pressed: true }),
    ).toBeVisible();
    await askQuestion("failed logins by source ip");
    const block = await screen.findByRole("region", {
      name: "Question: failed logins by source ip",
    });
    const table = await within(block).findByRole("table", { name: "Results" });
    // The server runs the answer it holds; the client never sends the SQL back.
    expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/ask/a1/run"))).toBe(true);
    expect(
      (posts(spy, "/api/query") as { sql: string }[]).filter((b) => b.sql.includes("turn 1")),
    ).toHaveLength(0);
    // People, addresses, and hosts are links to their pages.
    expect(within(table).getByRole("link", { name: "203.0.113.9" })).toBeVisible();
    // The SQL is collapsed, one click away.
    const how = within(block).getByText("How I got this").closest("details") as HTMLElement;
    expect(how).not.toHaveAttribute("open");
    expect(within(how).getByLabelText("Generated SQL")).toHaveTextContent("turn 1");
    expect(within(how).getByText("Generated query (not from the library)")).toBeInTheDocument();
    expect(within(how).getByText("linux_sshd")).toBeInTheDocument();
  });

  it("waits for Run query when the install keeps click-to-run", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("click to run failed logins");
    const block = await screen.findByRole("region", {
      name: "Question: click to run failed logins",
    });
    await within(block).findByRole("button", { name: "Run query" });
    const runs = () => spy.mock.calls.filter(([u]) => String(u).includes("/run")).length;
    expect(runs()).toBe(0);
    expect(within(block).queryByRole("table", { name: "Results" })).toBeNull();
    await userEvent.click(within(block).getByRole("button", { name: "Run query" }));
    expect(await within(block).findByRole("table", { name: "Results" })).toBeVisible();
    expect(runs()).toBe(1);
  });

  it("renders model text as plain text, labelled as about the query", async () => {
    await renderAt("/ask");
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    // Slice 1c: model text about the query lives under How I got this, not over the rows.
    await within(block).findByText(/2 addresses with failures/);
    await userEvent.click(within(block).getByText("How I got this"));
    const text = within(block).getByText(/<b>Failed<\/b> logins grouped by source IP\./);
    expect(text.querySelector("b")).toBeNull();
    expect(within(block).getByText("Assumed: Failed means status_id = 2")).toBeVisible();
    expect(within(block).getByText(/about the query, not the rows/)).toBeVisible();
  });

  it("stacks follow-ups below, sends earlier turns, and starts over on New question", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("failed logins");
    await screen.findByRole("region", { name: "Question: failed logins" });
    await askQuestion("only from 203.0.113.9");
    await screen.findByRole("region", { name: "Question: only from 203.0.113.9" });
    const [, second] = posts(spy, "/api/ask") as { history: { question: string }[] }[];
    expect(second?.history.map((t) => t.question)).toEqual(["failed logins"]);
    const answers = screen.getByLabelText("Answers");
    const heads = within(answers).getAllByRole("heading", { level: 3 });
    expect(heads.map((h) => h.textContent)).toEqual(["failed logins", "only from 203.0.113.9"]);

    await userEvent.click(screen.getByRole("button", { name: "New question" }));
    expect(screen.queryByLabelText("Answers")).toBeNull();
    await askQuestion("anything");
    const third = (posts(spy, "/api/ask") as { history: unknown[] }[])[2];
    expect(third?.history).toEqual([]);
  });

  it("says where a question goes when the model is in the cloud, and explains a block", async () => {
    await renderAt("/ask");
    await screen.findByRole("option", { name: /Cloud · gpt-x/ });
    expect(screen.queryByRole("note")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "p2");
    expect(screen.getByRole("note")).toHaveTextContent("Your question is sent to Cloud.");
    await askQuestion("failed logins");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /local-only sources: linux_sshd\. Choose a local provider/,
    );
  });

  it("saves with the question as origin", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("failed logins");
    await screen.findByRole("table", { name: "Results" });
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
    await screen.findByRole("heading", { name: "Investigate", level: 1 });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Ask")).not.toBeInTheDocument();
  });

  it("says the model is busy and retries on click", async () => {
    await renderAt("/ask");
    await askQuestion("while the model is busy");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The model was busy");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table", { name: "Results" })).toBeInTheDocument();
  });

  it("opens beside any page from the command palette, with the typed question", async () => {
    const spy = await renderAt("/dashboard");
    await userEvent.keyboard("{Control>}k{/Control}");
    await userEvent.type(await screen.findByRole("combobox"), "failed logins today");
    await userEvent.click(await screen.findByRole("option", { name: /Ask "failed logins today"/ }));
    const over = await screen.findByRole("dialog", { name: "Ask" });
    expect(within(over).getByLabelText("Question")).toHaveValue("failed logins today");
    await userEvent.click(within(over).getByRole("button", { name: "Ask" }));
    expect(await within(over).findByRole("table", { name: "Results" })).toBeVisible();
    expect(posts(spy, "/api/ask")).toHaveLength(1);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Ask" })).toBeNull();
  });
});

describe("Ask routing (ADR-0042 slice 1b)", () => {
  it("names the library query, its filters, and the time under How I got this", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("ssh logins for dana@example.com today");
    const block = await screen.findByRole("region", {
      name: "Question: ssh logins for dana@example.com today",
    });
    expect(
      (await within(block).findAllByText("SSH logins by user and source", { exact: false }))[0],
    ).toBeVisible();
    const how = within(block).getByText("How I got this").closest("details") as HTMLElement;
    expect(within(how).getByText("linux_auth/ssh_logins@1.0.0")).toBeInTheDocument();
    expect(within(how).getByText("user = dana@example.com (also dana)")).toBeInTheDocument();
    const [sent] = posts(spy, "/api/ask") as { tz?: string }[];
    expect(sent?.tz).toBeTruthy(); // "today" is the asker's day
  });

  it("says when a question was treated as general guidance and switches on click", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("how should I harden sshd?");
    const block = await screen.findByRole("region", {
      name: "Question: how should I harden sshd?",
    });
    const status = await within(block).findByRole("status");
    expect(status).toHaveTextContent("Treated as general guidance.");
    expect(within(block).queryByText("How I got this")).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/run"))).toBe(false);
    await userEvent.click(within(status).getByRole("button", { name: "Check your data instead?" }));
    const again = await screen.findByRole("region", {
      name: "Question: how should I harden sshd?",
    });
    expect(await within(again).findByRole("table", { name: "Results" })).toBeVisible();
    const bodies = posts(spy, "/api/ask") as { route?: string }[];
    expect(bodies.map((b) => b.route)).toEqual([undefined, "data"]);
    // The switched turn replaced the first one; it did not stack a second block.
    expect(screen.getAllByRole("region", { name: /^Question: how should I/ })).toHaveLength(1);
  });

  it("offers library queries by keyword when no AI provider is set up", async () => {
    window.history.replaceState(null, "", "/ask");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const passthrough = spy.getMockImplementation()!;
    spy.mockImplementation((url, init) =>
      String(url).endsWith("/api/ask/providers")
        ? Promise.resolve(
            new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
          )
        : passthrough(url, init),
    );
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(
      <App
        initialTheme="dark"
        queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      />,
    );
    await screen.findByText(/No AI provider is set up/);
    await askQuestion("failed ssh logins by source");
    const found = await screen.findByRole("region", { name: "Library suggestions" });
    const open = within(found).getByRole("button", { name: "SSH failures by source address" });
    expect(posts(spy, "/api/ask")).toHaveLength(0); // no model call at all
    await userEvent.click(open);
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
  });

  it("shows the code headline, then only statements that cite rows (slice 1c)", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("summarize dana's logins");
    const block = await screen.findByRole("region", { name: "Question: summarize dana's logins" });
    expect(await within(block).findByText("2 rows. First row: user dana.")).toBeVisible();
    const summary = await within(block).findByRole("list", { name: "Summary" });
    const item = within(summary).getByText("dana failed twice from <b>203.0.113.9</b>.");
    expect(item.querySelector("b")).toBeNull(); // model text is text, never markup
    expect(within(summary).getByTitle("0190a1b2-0000-7000-8000-00000000000a")).toBeVisible();
    expect(
      within(block).getByText("1 statement removed: it cited no events from these rows."),
    ).toBeVisible();
    expect(posts(spy, "/api/ask/a1/answer")).toHaveLength(1);
  });

  it("shows no summary when nothing cites, and never asks without event ids", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("summarize uncited");
    const block = await screen.findByRole("region", { name: "Question: summarize uncited" });
    expect(
      await within(block).findByText("No summary: the model's statements did not cite these rows."),
    ).toBeVisible();
    expect(within(block).queryByRole("list", { name: "Summary" })).toBeNull();
    await askQuestion("failed logins");
    const second = await screen.findByRole("region", { name: "Question: failed logins" });
    expect(
      await within(second).findByText("No summary: these rows have no event ids to cite."),
    ).toBeVisible();
    expect(spy.mock.calls.filter(([u]) => String(u).endsWith("/a2/answer"))).toHaveLength(0);
  });

  it("opens a row's own events in Search, built by the server (D173)", async () => {
    const spy = await renderAt("/ask");
    await askQuestion("ssh logins for dana@example.com");
    const block = await screen.findByRole("region", {
      name: "Question: ssh logins for dana@example.com",
    });
    await userEvent.click(
      await within(block).findByRole("button", {
        name: "Show events for user dana, client 198.51.100.4",
      }),
    );
    expect(posts(spy, "/api/ask/a1/drill")).toEqual([
      { values: { user: "dana", client: "198.51.100.4" } },
    ]);
    await vi.waitFor(() => expect(window.location.pathname).toMatch(/\/search$/));
  });

  it("offers Show events only when the answer has group keys", async () => {
    await renderAt("/ask");
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    await within(block).findByText(/2 addresses with failures/);
    expect(within(block).queryByRole("button", { name: /^Show events/ })).toBeNull();
  });
});
