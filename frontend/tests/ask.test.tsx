import { QueryClient } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { halted } from "@/features/ask/askJob";
import { mockApi, type MockAuth } from "./mockApi";
import { choose, optionLabels } from "./choose";

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

describe("Old addresses (D206)", () => {
  it("/ask redirects to /ask-ai, replacing the entry", async () => {
    const before = window.history.length;
    await renderAt("/ask");
    expect(await screen.findByLabelText("Question")).toBeVisible();
    await vi.waitFor(() => expect(window.location.pathname).toBe("/ask-ai"));
    expect(window.history.length).toBe(before);
  });

  it("/search redirects to /investigate/logs, keeping the search in the fragment", async () => {
    await renderAt("/search#tab=sql&q=SELECT%2042%20AS%20kept&range=7d");
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
    expect(new URLSearchParams(window.location.hash.slice(1)).get("q")).toBe("SELECT 42 AS kept");
  });

  it("/investigate/search redirects to /investigate/logs with its fragment", async () => {
    await renderAt("/investigate/search#tab=sql&q=SELECT%207&range=24h");
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
    expect(new URLSearchParams(window.location.hash.slice(1)).get("q")).toBe("SELECT 7");
  });
});

describe("Ask (ADR-0042 slice 1a)", () => {
  it("runs the answer by its id, shows the rows, and keeps the SQL under How I got this", async () => {
    const spy = await renderAt("/ask-ai");
    expect(await screen.findByRole("heading", { name: "Ask AI", level: 1 })).toBeVisible();
    // Ask AI is a page of its own with no tabs; the rail marks it.
    expect(screen.queryByRole("navigation", { name: /tabs$/ })).toBeNull();
    const rail = screen.getByRole("navigation", { name: "Primary" });
    expect(within(rail).getByRole("link", { name: "Ask AI" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await askQuestion("failed logins by source ip");
    const block = await screen.findByRole("region", {
      name: "Question: failed logins by source ip",
    });
    const table = await within(block).findByRole("table", { name: "Results" });
    // The server's job runs the answer it holds; the client never sends the SQL back.
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(1);
    expect(spy.mock.calls.some(([u]) => /\/api\/ask\/a1\/(run|answer)$/.test(String(u)))).toBe(
      false,
    );
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

  it("answers an address alone with its page, no query and no Run (D276)", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("10.20.30.40");
    const block = await screen.findByRole("region", { name: "Question: 10.20.30.40" });
    const answer = await within(block).findByRole("status");
    expect(answer).toHaveTextContent("10.20.30.40 is an address.");
    expect(answer).toHaveTextContent("Names looked up:14 names");
    expect(answer).toHaveTextContent("DHCP and VPN history:no source you may read");
    expect(answer).toHaveTextContent(
      "Looked up directly for the last 7 days, the address page's window, not the time chosen above. No AI model was used.",
    );
    // No model badge: no model was used.
    expect(within(block).queryByText("Local")).toBeNull();
    expect(within(block).queryByRole("button", { name: "Run query" })).toBeNull();
    expect(within(block).queryByText("How I got this")).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/run"))).toBe(false);
    // The next question does not send it as an earlier turn: it has no query to refine.
    await askQuestion("failed logins by source ip");
    await screen.findByRole("region", { name: "Question: failed logins by source ip" });
    const last = (posts(spy, "/api/ask/jobs") as { history: unknown[] }[]).at(-1);
    expect(last?.history).toEqual([]);
    // The link names the window the answer read, so the page opens on it.
    const link = within(answer).getByRole("link", { name: "Open the address page" });
    expect(link).toHaveAttribute("href", "/investigate/people#ip=10.20.30.40&range=7d");
    await userEvent.click(link);
    expect(window.location.hash).toBe("#ip=10.20.30.40&range=7d");
  });

  it("waits for Run query when the install keeps click-to-run", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("click to run failed logins");
    const block = await screen.findByRole("region", {
      name: "Question: click to run failed logins",
    });
    await within(block).findByRole("button", { name: "Run query" });
    const runs = () => posts(spy, "/api/ask/a1/jobs").length;
    expect(runs()).toBe(0);
    expect(within(block).queryByRole("table", { name: "Results" })).toBeNull();
    await userEvent.click(within(block).getByRole("button", { name: "Run query" }));
    expect(await within(block).findByRole("table", { name: "Results" })).toBeVisible();
    expect(runs()).toBe(1);
  });

  it("renders model text as plain text, labelled as about the query", async () => {
    await renderAt("/ask-ai");
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

  it("draws answers newest first, sends earlier turns in asked order, and starts over on New question", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("failed logins");
    await screen.findByRole("region", { name: "Question: failed logins" });
    await askQuestion("only from 203.0.113.9");
    await screen.findByRole("region", { name: "Question: only from 203.0.113.9" });
    const [, second] = posts(spy, "/api/ask/jobs") as { history: { question: string }[] }[];
    expect(second?.history.map((t) => t.question)).toEqual(["failed logins"]);
    const answers = screen.getByLabelText("Answers");
    const heads = within(answers).getAllByRole("heading", { level: 3 });
    // D256: the newest answer is directly under the prompt; the follow-up refined it.
    expect(heads.map((h) => h.textContent)).toEqual(["only from 203.0.113.9", "failed logins"]);

    await userEvent.click(screen.getByRole("button", { name: "New question" }));
    expect(screen.queryByLabelText("Answers")).toBeNull();
    await askQuestion("anything");
    const third = (posts(spy, "/api/ask/jobs") as { history: unknown[] }[])[2];
    expect(third?.history).toEqual([]);
  });

  it("says where a question goes when the model is in the cloud, and explains a block", async () => {
    await renderAt("/ask-ai");
    await vi.waitFor(() => expect(optionLabels(screen.getByLabelText("Model"))).toContain("Cloud"));
    expect(screen.queryByRole("note")).toBeNull();
    await choose(screen.getByLabelText("Model"), "p2");
    expect(screen.getByRole("note")).toHaveTextContent("Your question is sent to Cloud.");
    await askQuestion("failed logins");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /local-only sources: linux_sshd\. Choose a local provider/,
    );
  });

  it("asks over a Custom range, start and end, and hands it on to Logs", async () => {
    const spy = await renderAt("/ask-ai");
    await choose(await screen.findByLabelText("Time"), "custom");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01T08:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02T08:00" } });
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    const asked = (posts(spy, "/api/ask/jobs") as { start?: string; end?: string }[]).at(-1);
    expect(asked?.start).toBe(new Date("2026-11-01T08:00").toISOString());
    expect(asked?.end).toBe(new Date("2026-11-02T08:00:59.999").toISOString());
    await within(block).findByRole("table", { name: "Results" });
    await userEvent.click(within(block).getByRole("button", { name: "Open in Logs" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    // Logs opens on the same Custom range, not on everything kept.
    await vi.waitFor(() => expect(screen.getByLabelText("From")).toHaveValue("2026-11-01T08:00"));
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-02T08:00");
    await vi.waitFor(() =>
      expect((posts(spy, "/api/query") as { start?: string }[]).at(-1)?.start).toBe(
        new Date("2026-11-01T08:00").toISOString(),
      ),
    );
  });

  it("Open in Logs opens the answer's SQL in the SQL mode, and Save keeps the question (D206)", async () => {
    const spy = await renderAt("/ask-ai");
    await choose(await screen.findByLabelText("Time"), "7d");
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    await within(block).findByRole("table", { name: "Results" });
    await userEvent.click(within(block).getByRole("button", { name: "Open in Logs" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
    expect(screen.getByText("From Ask AI: failed logins")).toBeVisible();
    // The answer's SQL runs in Logs with the Ask AI page's time range.
    await vi.waitFor(() =>
      expect((posts(spy, "/api/query") as { sql: string }[]).at(-1)?.sql).toContain("turn 1"),
    );
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "7 days" }),
    ).toHaveAttribute("aria-pressed", "true");
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
    await renderAt("/ask-ai", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("heading", { name: "Logs", level: 1 });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Ask AI")).not.toBeInTheDocument();
  });

  it("says the model is busy and retries on click", async () => {
    await renderAt("/ask-ai");
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
    await userEvent.click(
      await screen.findByRole("option", { name: /Ask AI: failed logins today/ }),
    );
    const over = await screen.findByRole("dialog", { name: "Ask AI" });
    expect(within(over).getByLabelText("Question")).toHaveValue("failed logins today");
    await userEvent.click(within(over).getByRole("button", { name: "Ask" }));
    expect(await within(over).findByRole("table", { name: "Results" })).toBeVisible();
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(1);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Ask AI" })).toBeNull();
  });
});

describe("Ask as a background job (D269, owner 2026-11-17)", () => {
  it("shows each step with its time, the rows as soon as the query ran, then the summary", async () => {
    await renderAt("/ask-ai");
    await askQuestion("summarize step by step");
    const block = await screen.findByRole("region", { name: "Question: summarize step by step" });
    const steps = await within(block).findByRole("list", { name: "Progress" });
    await vi.waitFor(
      () => expect(steps).toHaveTextContent(/^Writing query 1\.2 s›Running query… \d+ s$/),
      { timeout: 3000 },
    );
    // The table first; the summary step still runs above the code's headline.
    const table = await within(block).findByRole("table", { name: "Results" }, { timeout: 3000 });
    expect(within(block).getByRole("list", { name: "Progress" })).toHaveTextContent(
      /Running query under 0\.1 s›Summarizing… \d+ s$/,
    );
    expect(within(block).getByText("2 rows. First row: user dana.")).toBeVisible();
    expect(within(block).queryByRole("list", { name: "Summary" })).toBeNull();
    await within(block).findByRole("list", { name: "Summary" }, { timeout: 3000 });
    // The steps stay, each with its time, so nothing above the table moves when it ends.
    expect(within(block).getByRole("list", { name: "Progress" })).toHaveTextContent(
      /^Writing query 1\.2 s›Running query under 0\.1 s›Summarizing 1\.2 s$/,
    );
    expect(table).toBeVisible();
    await userEvent.click(within(block).getByText("How I got this"));
    expect(
      within(block).getByText(
        /Writing the query 1\.2 s, running it under 0\.1 s, summarizing 1\.2 s/,
      ),
    ).toBeVisible();
  });

  it("keeps the table when the summary times out, and says so under it", async () => {
    await renderAt("/ask-ai");
    await askQuestion("summarize, too slow");
    const block = await screen.findByRole("region", { name: "Question: summarize, too slow" });
    const table = await within(block).findByRole("table", { name: "Results" });
    const note = await within(block).findByText(
      "The model took too long to summarize. Results are above.",
    );
    expect(table.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(block).queryByRole("alert")).toBeNull();
    expect(within(block).queryByRole("list", { name: "Summary" })).toBeNull();
  });

  it("says a proxy's 504 took too long, never that the server cannot be reached", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).endsWith("/api/ask/jobs")
        ? new Response("<html>504 Gateway Time-out</html>", { status: 504 })
        : real(url, init),
    );
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    expect(await within(block).findByRole("alert")).toHaveTextContent(
      /^The request took too long\s*Try again$/,
    );
    expect(screen.queryByText(/Can't reach the server|504/)).toBeNull();
  });

  it("tries a poll again when it fails once or twice, and the answer still comes", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    let dropped = 0;
    spy.mockImplementation(async (url, init) =>
      /\/api\/ask\/jobs\/j1$/.test(String(url)) && dropped++ < 2
        ? new Response("Bad Gateway", { status: 502 })
        : real(url, init),
    );
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    expect(
      await within(block).findByRole("table", { name: "Results" }, { timeout: 5000 }),
    ).toBeVisible();
    expect(dropped).toBeGreaterThanOrEqual(2);
    expect(within(block).queryByRole("alert")).toBeNull();
  });

  it("stops every step and every read when the job is gone", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    let gone = false;
    spy.mockImplementation(async (url, init) =>
      gone && /\/api\/ask\/jobs\/j1$/.test(String(url))
        ? new Response(
            JSON.stringify({ detail: "That question has expired. Ask again.", code: "not_found" }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          )
        : real(url, init),
    );
    await askQuestion("this never finishes");
    const block = await screen.findByRole("region", { name: "Question: this never finishes" });
    const steps = await within(block).findByRole("list", { name: "Progress" });
    await vi.waitFor(() => expect(steps).toHaveTextContent(/^Writing query… \d+ s$/));
    gone = true;
    expect(await within(block).findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent(
      "That question has expired. Ask again.",
    );
    expect(steps).toHaveTextContent(/^Writing query stopped at (under 0\.1|\d+\.\d) s$/);
    const reads = () =>
      spy.mock.calls.filter(([u]) => /\/api\/ask\/(jobs\/j1|providers\/p1\/queue)$/.test(String(u)))
        .length;
    const before = reads();
    await new Promise((r) => setTimeout(r, 2500));
    expect(reads()).toBe(before);
  });

  it("stops the Run step when its submit fails", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).endsWith("/api/ask/a1/jobs")
        ? new Response(
            JSON.stringify({ detail: "Something went wrong. Ask again.", code: "internal_error" }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          )
        : real(url, init),
    );
    await askQuestion("click to run failed logins");
    const block = await screen.findByRole("region", {
      name: "Question: click to run failed logins",
    });
    await userEvent.click(await within(block).findByRole("button", { name: "Run query" }));
    expect(await within(block).findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(within(block).getByRole("list", { name: "Progress" })).toHaveTextContent(
      /Running query stopped at (under 0\.1|\d+\.\d) s$/,
    );
    expect(within(block).getByRole("list", { name: "Progress" })).not.toHaveTextContent("…");
  });

  it("keeps Ask off after New question until the server ends the running question", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    let ended = false;
    spy.mockImplementation(async (url, init) =>
      ended && /\/api\/ask\/jobs\/j1$/.test(String(url))
        ? new Response(JSON.stringify({ job_id: "j1", state: "done", steps: [] }), {
            headers: { "Content-Type": "application/json" },
          })
        : real(url, init),
    );
    await askQuestion("this never finishes");
    await screen.findByRole("region", { name: "Question: this never finishes" });
    await userEvent.click(screen.getByRole("button", { name: "New question" }));
    expect(screen.queryByLabelText("Answers")).toBeNull();
    await userEvent.type(screen.getByLabelText("Question"), "anything");
    const askButton = screen.getByRole("button", { name: "Ask" });
    expect(askButton).toHaveAttribute("aria-disabled", "true");
    expect(askButton).toHaveAccessibleDescription("Your previous question is still running");
    expect(
      screen.getByText(/Your previous question is still running\. Ask comes back/),
    ).toBeVisible();
    await userEvent.click(askButton);
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(1); // nothing sent while it runs
    ended = true;
    await vi.waitFor(() => expect(askButton).toHaveAttribute("aria-disabled", "false"), {
      timeout: 3000,
    });
    expect(screen.queryByText(/Ask comes back/)).toBeNull();
  });

  it("turns off Run query, Try again, and Check your data while a question runs", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("how should I harden sshd?");
    await screen.findByRole("button", { name: "Check your data instead?" });
    await askQuestion("hits the output limit");
    await screen.findByRole("button", { name: "Try again" });
    await askQuestion("click to run failed logins");
    await screen.findByRole("button", { name: "Run query" });
    await askQuestion("this never finishes");
    await screen.findByRole("region", { name: "Question: this never finishes" });
    const sent = posts(spy, "/api/ask/jobs").length;
    for (const name of ["Check your data instead?", "Try again", "Run query"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).toHaveAccessibleDescription("Your previous question is still running");
      await userEvent.click(button);
    }
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(sent);
    expect(spy.mock.calls.filter(([u]) => /\/api\/ask\/a\d+\/jobs$/.test(String(u)))).toHaveLength(
      0,
    );
  });

  it("ends the running steps of a question the page stops following", () => {
    const turn = {
      id: 1,
      question: "q",
      phase: "writing" as const,
      steps: [
        { name: "sql" as const, state: "done" as const, ms: 1200 },
        { name: "summary" as const, state: "running" as const, ms: null },
      ],
      seen: { summary: 1000 },
      result: { rows: [] } as never,
    };
    const left = halted(turn, 4000);
    expect(left.phase).toBe("done");
    expect(left.steps?.map((x) => [x.name, x.state, x.ms])).toEqual([
      ["sql", "done", 1200],
      ["summary", "failed", 3000],
    ]);
    expect(halted({ ...turn, result: undefined }, 4000).phase).toBe("failed");
    expect(halted({ ...turn, steps: [turn.steps[0]!] }, 4000)).toEqual({});
  });

  it("keeps an answer and its Run query when the server says a question still runs", async () => {
    const spy = await renderAt("/ask-ai");
    const real = spy.getMockImplementation() as typeof fetch;
    const still = () =>
      new Response(
        JSON.stringify({ detail: "Your previous question is still running", code: "rate_limited" }),
        { status: 429, headers: { "Content-Type": "application/json" } },
      );
    spy.mockImplementation(async (url, init) =>
      /\/api\/ask\/a1\/jobs$/.test(String(url)) ? still() : real(url, init),
    );
    await askQuestion("click to run failed logins");
    const block = await screen.findByRole("region", {
      name: "Question: click to run failed logins",
    });
    await userEvent.click(await within(block).findByRole("button", { name: "Run query" }));
    expect(await screen.findByText("Your previous question is still running")).toBeVisible();
    expect(within(block).queryByRole("alert")).toBeNull();
    expect(within(block).getByRole("button", { name: "Run query" })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(within(block).getByRole("list", { name: "Progress" })).not.toHaveTextContent(
      "Running query",
    );
  });

  it("keeps a failed answer, and the typed question, when Try again or Ask meets a running one", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("hits the output limit");
    const block = await screen.findByRole("region", { name: "Question: hits the output limit" });
    await within(block).findByRole("alert");
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).endsWith("/api/ask/jobs") && init?.method === "POST"
        ? new Response(
            JSON.stringify({
              detail: "Your previous question is still running",
              code: "rate_limited",
            }),
            { status: 429, headers: { "Content-Type": "application/json" } },
          )
        : real(url, init),
    );
    await userEvent.click(within(block).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Your previous question is still running")).toBeVisible();
    const again = screen.getByRole("region", { name: "Question: hits the output limit" });
    expect(within(again).getByRole("alert")).toHaveTextContent("output limit");
    expect(within(again).getByRole("button", { name: "Try again" })).toBeVisible();
    await askQuestion("anything else");
    await vi.waitFor(() => expect(screen.getByLabelText("Question")).toHaveValue("anything else"));
    expect(screen.queryByRole("region", { name: "Question: anything else" })).toBeNull();
    expect(screen.getAllByRole("region", { name: /^Question: / })).toHaveLength(1);
  });

  it("drops the summary placeholder when the job fails or cannot be read while summarizing", async () => {
    for (const how of ["gone", "failed"] as const) {
      const spy = await renderAt("/ask-ai");
      const real = spy.getMockImplementation() as typeof fetch;
      let broken = false;
      spy.mockImplementation(async (url, init) => {
        if (!broken || !/\/api\/ask\/jobs\/j1$/.test(String(url))) return real(url, init);
        if (how === "gone")
          return new Response(
            JSON.stringify({ detail: "That question has expired. Ask again.", code: "not_found" }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          );
        const job = (await (await real(url, init)).json()) as Record<string, unknown>;
        const steps = (job.steps as { name: string }[]).map((st) =>
          st.name === "summary" ? { ...st, state: "failed", ms: 900 } : st,
        );
        const error = { code: "internal_error", message: "Something went wrong. Ask again." };
        return new Response(
          JSON.stringify({ ...job, state: "failed", summary: null, steps, error }),
          { headers: { "Content-Type": "application/json" } },
        );
      });
      await askQuestion("summarize step by step");
      const block = await screen.findByRole("region", { name: "Question: summarize step by step" });
      await within(block).findByRole("table", { name: "Results" }, { timeout: 3000 });
      expect(block.querySelector("[data-skeleton]")).not.toBeNull();
      broken = true;
      await within(block).findByRole("alert", {}, { timeout: 3000 });
      expect(block.querySelector("[data-skeleton]")).toBeNull();
      expect(within(block).getByRole("list", { name: "Progress" })).toHaveTextContent(
        /Summarizing stopped at/,
      );
      cleanup();
      vi.restoreAllMocks();
    }
  });

  it("reads a running job every 0.5 s at first, then every second, and says when the model is busy", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const spy = await renderAt("/ask-ai");
      const real = spy.getMockImplementation() as typeof fetch;
      const at: number[] = [];
      spy.mockImplementation(async (url, init) => {
        const u = String(url);
        if (/\/api\/ask\/jobs\/j1$/.test(u)) at.push(Date.now());
        if (u.endsWith("/api/ask/providers/p1/queue"))
          return new Response(JSON.stringify({ slots: 1, running: 1, waiting: 2 }), {
            headers: { "Content-Type": "application/json" },
          });
        return real(url, init);
      });
      await askQuestion("this never finishes");
      await screen.findByRole("region", { name: "Question: this never finishes" });
      await vi.advanceTimersByTimeAsync(10_000);
      const gaps = at.slice(1).map((t, i) => t - at[i]!);
      expect(gaps.length).toBeGreaterThan(8);
      for (const g of gaps.slice(0, 4)) expect(g).toBeGreaterThanOrEqual(450);
      for (const g of gaps.slice(0, 4)) expect(g).toBeLessThan(700);
      for (const g of gaps.slice(-3)) expect(g).toBeGreaterThanOrEqual(950);
      for (const g of gaps.slice(-3)) expect(g).toBeLessThan(1200);
      expect(screen.getByRole("list", { name: "Progress" })).toHaveTextContent(
        /Writing query… \d+ s · model busy, waiting for a free slot$/,
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Ask AI, search first (D256)", () => {
  it("puts the prompt first in the page body, then the Time, Sources, and Model chips", async () => {
    await renderAt("/ask-ai");
    const title = await screen.findByRole("heading", { name: "Ask AI", level: 1 });
    const prompt = await screen.findByLabelText("Question");
    expect(prompt).toHaveAttribute("placeholder", "Ask about your logs");
    expect(prompt).toHaveAttribute("title", expect.stringMatching(/KQL or SPL/));
    // The first control after the page title is the prompt.
    const after = [
      ...document.querySelectorAll("main textarea, main select, main input, main button"),
    ].filter((n) => title.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after[0]).toBe(prompt);
    const time = screen.getByLabelText("Time");
    const sources = screen.getByRole("button", { name: /^Sources/ });
    const model = screen.getByLabelText("Model");
    for (const chip of [time, sources, model])
      expect(prompt.compareDocumentPosition(chip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // "Name Value": the same five presets, all sources, and the model with its badge.
    expect(optionLabels(time)).toEqual(["1 hour", "24 hours", "7 days", "30 days", "Custom"]);
    expect(time).toHaveValue("24h");
    await vi.waitFor(() => expect(sources).toHaveTextContent(/^Sources\s*All \d+$/));
    await vi.waitFor(() => expect(model).toHaveTextContent("Local Ollama"));
    expect(model).toHaveTextContent(/^Model\s*Local Ollama.*Local$/);
    // The Logs controls are gone from this page: no segmented time strip, no source select.
    expect(screen.queryByRole("group", { name: "Time" })).toBeNull();
    expect(screen.queryByLabelText("Add source filter")).toBeNull();
    // The Ask button is quiet until there is text, still reachable and saying why, then
    // the page's one filled button (fix list 2026-11-16 item 6).
    const ask = screen.getByRole("button", { name: "Ask" });
    expect(ask).toHaveAttribute("aria-disabled", "true");
    expect(ask).toHaveAccessibleDescription("Type a question first");
    expect(ask.className).not.toMatch(/bg-accent|opacity/);
    await userEvent.click(ask);
    expect(screen.queryByRole("region", { name: /^Question:/ })).toBeNull();
    await userEvent.type(prompt, "failed logins");
    expect(ask).toHaveAttribute("aria-disabled", "false");
    expect(ask.className).toMatch(/bg-accent text-on-accent/);
  });

  it("sends the chosen sources, and says when the text reads as a query", async () => {
    const spy = await renderAt("/ask-ai");
    await userEvent.click(await screen.findByRole("button", { name: /^Sources/ }));
    const list = screen.getByRole("group", { name: "Sources" });
    await userEvent.click(await within(list).findByRole("checkbox", { name: "linux_sshd" }));
    expect(screen.getByRole("button", { name: /^Sources/ })).toHaveTextContent("linux_sshd");
    await userEvent.type(screen.getByLabelText("Question"), "index=main | stats count by host");
    expect(screen.getByText(/Reads as a KQL or SPL query/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByRole("region", { name: /^Question: index=main/ });
    expect((posts(spy, "/api/ask/jobs") as { sources?: string[] }[]).at(-1)?.sources).toEqual([
      "linux_sshd",
    ]);
  });

  it("draws a second answer above the first, each heading line with its badge, never a bubble", async () => {
    const spy = await renderAt("/ask-ai");
    const examples = await screen.findByRole("region", { name: "Example questions" });
    await userEvent.click(within(examples).getAllByRole("button")[0] as HTMLElement);
    const first = await screen.findByRole("region", { name: "Question: Who logged in over SSH?" });
    // Suggestions are for the empty page only.
    expect(screen.queryByRole("region", { name: "Example questions" })).toBeNull();
    await within(first).findByRole("table", { name: "Results" });
    const firstSql = within(first).getByLabelText("Generated SQL").textContent;
    await askQuestion("only for dana");
    const second = await screen.findByRole("region", { name: "Question: only for dana" });
    expect(second.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The follow-up is the request the page always sent: the earlier turn, oldest first.
    const [one, two] = posts(spy, "/api/ask/jobs") as Record<string, unknown>[];
    expect(Object.keys(two ?? {}).sort()).toEqual(
      ["history", "provider_id", "question", "start", "tz"].sort(),
    );
    expect(two).toMatchObject({
      question: "only for dana",
      provider_id: one?.provider_id,
      tz: one?.tz,
      // By the answer's id (the server reads its own SQL), with the copy while it fits.
      history: [{ question: "Who logged in over SSH?", ask_id: "a1", sql: firstSql }],
    });
    for (const block of [first, second]) {
      const head = block.querySelector("[data-turn-head]") as HTMLElement;
      expect(within(head).getByText("Local")).toBeVisible();
      expect(within(head).getByRole("heading", { level: 3 })).toBeVisible();
      expect(head.querySelector("time")).not.toBeNull();
      // A block, never a chat bubble: no pill, no tinted or filled box around the turn.
      expect(block.className).not.toMatch(/rounded|bg-/);
      expect(head.className).not.toMatch(/rounded|bg-/);
    }
    const answers = screen.getByLabelText("Answers");
    expect(
      answers.querySelectorAll(".rounded-full, .rounded-chip, .bg-accent-subtle"),
    ).toHaveLength(0);
  });

  it("asks only from the prompt: Enter in a chip sends nothing and keeps the text", async () => {
    const spy = await renderAt("/ask-ai");
    const prompt = await screen.findByLabelText("Question");
    await userEvent.type(prompt, "failed logins");
    await choose(screen.getByLabelText("Time"), "custom");
    await userEvent.click(screen.getByLabelText("From"));
    await userEvent.keyboard("{Enter}");
    await userEvent.click(screen.getByRole("button", { name: /^Sources/ }));
    const box = await within(screen.getByRole("group", { name: "Sources" })).findByRole(
      "checkbox",
      { name: "linux_sshd" },
    );
    box.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(box.closest("form")).toBeNull();
    expect(screen.getByLabelText("From").closest("form")).toBeNull();
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(0);
    expect(prompt).toHaveValue("failed logins");
  });

  it("grows the prompt from two lines to six with the lines typed", async () => {
    const { promptRows } = await import("@/features/ask/AskThread");
    expect([promptRows(""), promptRows("a\nb\nc"), promptRows("1\n2\n3\n4\n5\n6\n7\n8")]).toEqual([
      2, 3, 6,
    ]);
    await renderAt("/ask-ai");
    const prompt = await screen.findByLabelText("Question");
    expect(prompt).toHaveAttribute("rows", "2");
    await userEvent.type(
      prompt,
      "one{Shift>}{Enter}{/Shift}two{Shift>}{Enter}{/Shift}three{Shift>}{Enter}{/Shift}four",
    );
    expect(prompt).toHaveAttribute("rows", "4");
  });

  it("stacks answers newest first in the slide-over, and its New question starts over", async () => {
    await renderAt("/dashboard");
    await userEvent.keyboard("{Control>}k{/Control}");
    await userEvent.type(
      await screen.findByRole("combobox", { name: /^Search pages/ }),
      "failed logins today",
    );
    await userEvent.click(
      await screen.findByRole("option", { name: /Ask AI: failed logins today/ }),
    );
    const over = await screen.findByRole("dialog", { name: "Ask AI" });
    await userEvent.click(within(over).getByRole("button", { name: "Ask" }));
    const first = await within(over).findByRole("region", {
      name: "Question: failed logins today",
    });
    await within(first).findByRole("table", { name: "Results" });
    await userEvent.type(within(over).getByLabelText("Question"), "only from 203.0.113.9");
    await userEvent.click(within(over).getByRole("button", { name: "Refine" }));
    const second = await within(over).findByRole("region", {
      name: "Question: only from 203.0.113.9",
    });
    expect(second.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(within(over).getByRole("button", { name: "New question" }));
    expect(within(over).queryByLabelText("Answers")).toBeNull();
    expect(within(over).queryByRole("button", { name: "New question" })).toBeNull();
  });

  it("starts over from the page header's New question", async () => {
    await renderAt("/ask-ai");
    await screen.findByLabelText("Question");
    expect(screen.queryByRole("button", { name: "New question" })).toBeNull();
    await askQuestion("failed logins");
    await screen.findByRole("region", { name: "Question: failed logins" });
    const header = screen.getByRole("heading", { name: "Ask AI", level: 1 }).parentElement!
      .parentElement as HTMLElement;
    await userEvent.click(within(header).getByRole("button", { name: "New question" }));
    expect(screen.queryByLabelText("Answers")).toBeNull();
    expect(await screen.findByRole("region", { name: "Example questions" })).toBeVisible();
  });
});

describe("Ask routing (ADR-0042 slice 1b)", () => {
  it("names the library query, its filters, and the time under How I got this", async () => {
    const spy = await renderAt("/ask-ai");
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
    const [sent] = posts(spy, "/api/ask/jobs") as { tz?: string }[];
    expect(sent?.tz).toBeTruthy(); // "today" is the asker's day
    // The question's own time wins over the picker, and the line says so (owner, 2026-11-08).
    expect(
      within(block).getByText(/today \(named in the question, not the time range above\)/),
    ).toBeVisible();
  });

  it("shows a library answer at once, with no wait on the model (owner, 2026-11-08)", async () => {
    const seen: string[] = [];
    const watch = new MutationObserver(() => {
      for (const el of document.querySelectorAll('[role="status"]'))
        seen.push(el.textContent ?? "");
    });
    watch.observe(document.body, { subtree: true, childList: true, characterData: true });
    await renderAt("/ask-ai");
    await askQuestion("who uses claude code");
    const block = await screen.findByRole("region", { name: "Question: who uses claude code" });
    expect(await within(block).findByRole("table", { name: "Results" })).toBeVisible();
    watch.disconnect();
    // The model wait ("model busy", shown after 2 s) never appeared.
    expect(seen.filter((t) => t.includes("model busy"))).toEqual([]);
    const how = within(block).getByText("How I got this").closest("details") as HTMLElement;
    expect(within(how).getByText("ai_agents/agents_claude_code_users@1.1.0")).toBeInTheDocument();
    expect(
      within(how).getByText("A data question, matched to the library without the model"),
    ).toBeInTheDocument();
  });

  it("says when a question was treated as general guidance and switches on click", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("how should I harden sshd?");
    const block = await screen.findByRole("region", {
      name: "Question: how should I harden sshd?",
    });
    const status = await within(block).findByRole("status");
    expect(status).toHaveTextContent("Treated as general guidance.");
    expect(within(block).queryByText("How I got this")).toBeNull();
    expect(posts(spy, "/api/ask/a1/jobs")).toHaveLength(0);
    await userEvent.click(within(status).getByRole("button", { name: "Check your data instead?" }));
    const again = await screen.findByRole("region", {
      name: "Question: how should I harden sshd?",
    });
    expect(await within(again).findByRole("table", { name: "Results" })).toBeVisible();
    const bodies = posts(spy, "/api/ask/jobs") as { route?: string }[];
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
    expect(await screen.findByText(/No AI provider is set up/)).toHaveTextContent(
      "No AI provider is set up. Logs works without one.",
    );
    // D256: the Model chip reads "Model None".
    const model = screen.getByLabelText("Model");
    expect(model).toBeDisabled();
    expect(model).toHaveTextContent("None");
    await askQuestion("failed ssh logins by source");
    const found = await screen.findByRole("region", { name: "Library suggestions" });
    const open = within(found).getByRole("button", { name: "SSH failures by source address" });
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(0); // no model call at all
    // Longer than Logs takes: shown, but disabled with the plain reason (review of 636).
    const big = within(found).getByRole("button", { name: "AI services in use" });
    expect(big).toHaveAttribute("aria-disabled", "true");
    expect(big).toHaveAccessibleDescription(/longer than the 20,000 characters Logs takes/);
    await userEvent.click(open);
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
  });

  it("shows the code headline, then only statements that cite rows (slice 1c)", async () => {
    const spy = await renderAt("/ask-ai");
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
    expect(posts(spy, "/api/ask/jobs")).toHaveLength(1); // the job wrote the summary
  });

  it("shows no summary when nothing cites, and never asks without event ids", async () => {
    await renderAt("/ask-ai");
    await askQuestion("summarize uncited");
    const block = await screen.findByRole("region", { name: "Question: summarize uncited" });
    expect(
      await within(block).findByText("No summary: the model's statements did not cite these rows."),
    ).toBeVisible();
    expect(within(block).queryByRole("list", { name: "Summary" })).toBeNull();
    await askQuestion("failed logins");
    const second = await screen.findByRole("region", { name: "Question: failed logins" });
    // What was counted, written by the server from the run, in place of "No summary"
    // (item 21): said once, and the count stays in the headline and the table only.
    const counted = (await within(second).findByText("What was counted:")).parentElement;
    expect(counted).toHaveTextContent(
      "What was counted: Read 1 source for the last 24 hours and counted failures, grouped by address.",
    );
    expect(within(second).queryByText(/^No summary/)).toBeNull();
    // Rows with no event ids to cite: the job wrote no summary.
    expect(within(second).queryByText(/Summarizing/)).toBeNull();
  });

  it("says a library answer with nothing found in one line, and why Logs cannot open it", async () => {
    const spy = await renderAt("/ask-ai");
    await askQuestion("which ai services are in use");
    const block = await screen.findByRole("region", {
      name: "Question: which ai services are in use",
    });
    expect(
      await within(block).findByText("Read 2 sources for the last 24 hours: no AI services."),
    ).toBeVisible();
    for (const said of [
      "No matching rows in this time range.",
      "No rows matched in this time range.",
    ])
      expect(within(block).queryByText(said)).toBeNull();
    expect(within(block).queryByRole("table")).toBeNull();
    // Server-built SQL longer than Logs takes: the link says why instead of failing there.
    const open = within(block).getByRole("button", { name: "Open in Logs" });
    expect(open).toHaveAttribute("aria-disabled", "true");
    expect(open).toHaveAccessibleDescription(/longer than the 20,000 characters Logs takes/);
    // A follow-up names that answer by id and never posts its SQL back (review of 636).
    await askQuestion("only claude");
    const turns = (posts(spy, "/api/ask/jobs") as { history: Record<string, unknown>[] }[]).at(-1);
    expect(turns?.history).toEqual([{ question: "which ai services are in use", ask_id: "a1" }]);
  });

  it("opens a row's own events in Logs, built by the server (D173)", async () => {
    const spy = await renderAt("/ask-ai");
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
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
  });

  it("offers Show events only when the answer has group keys", async () => {
    await renderAt("/ask-ai");
    await askQuestion("failed logins");
    const block = await screen.findByRole("region", { name: "Question: failed logins" });
    await within(block).findByText(/2 addresses with failures/);
    expect(within(block).queryByRole("button", { name: /^Show events/ })).toBeNull();
  });
});

describe("Ask's example questions (D182)", () => {
  it("offers questions from the library and asks one in one click", async () => {
    const spy = await renderAt("/ask-ai");
    const box = await screen.findByRole("region", { name: "Example questions" });
    // The question form of each phrasing, one per query, from what the library offers.
    const buttons = within(box).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Who logged in over SSH?",
      "Who was refused sudo?",
    ]);
    await userEvent.click(buttons[0] as HTMLElement);
    await screen.findByRole("region", { name: "Question: Who logged in over SSH?" });
    expect(posts(spy, "/api/ask/jobs").at(-1)).toMatchObject({
      question: "Who logged in over SSH?",
    });
    // Gone once there is an answer to refine.
    expect(screen.queryByRole("region", { name: "Example questions" })).toBeNull();
  });

  it("are not shown to auditors, who have no Ask", async () => {
    await renderAt("/ask-ai", { mode: "login", signedIn: true, role: "auditor" });
    // Logs explains that Auditors run no SQL until an admin allows it (D220).
    expect(await screen.findByRole("region", { name: "SQL not available" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Example questions" })).toBeNull();
  });
});

describe("pickExamples", () => {
  const q = (id: string, ask: string[], sql = "SELECT 1 WHERE time > {{start}}") => ({
    id,
    name: id,
    group: "",
    description: "",
    why: "",
    normal: "",
    tags: [],
    requires: [],
    sources: [],
    sql,
    pack_sql: sql,
    suggested_schedule: null,
    flag: null,
    ask,
    my_copy: null,
  });
  const pack = (id: string, queries: ReturnType<typeof q>[]) => ({
    id,
    name: id,
    version: "1",
    description: "",
    queries,
  });

  it("spreads across packs, prefers a question, skips queries that need a value", async () => {
    const { pickExamples } = await import("@/features/ask/AskExamples");
    const lib = {
      hidden: 0,
      needs: [],
      packs: [
        pack("a", [
          q("a1", ["A one", "A one?"]),
          q("a2", ["A two?"], "SELECT 1 WHERE u = {{user}}"),
          { ...q("a5", ["A five?"]), pack_sql: "SELECT 1 WHERE ip = {{ip}}" }, // sample default
          q("a3", ["A three"]),
          q("a4", []),
        ]),
        pack("b", [q("b1", ["B one?"]), q("b2", ["B two?"])]),
        pack("c", [q("c1", ["C one?"])]),
      ],
    };
    expect(pickExamples(lib)).toEqual(["A one?", "B one?", "C one?", "A three", "B two?"]);
    expect(pickExamples(lib, 2)).toEqual(["A one?", "B one?"]);
  });
});

describe("A failed Ask answer (D192)", () => {
  it("leaves Results empty: the last search's rows never sit under the failed question", async () => {
    await renderAt("/ask-ai", { mode: "open" });
    // Ask AI is its own page: no search runs on arrival, so no other rows are on it.
    const pageResults = () => document.querySelector("section[aria-label='Results']");
    await screen.findByLabelText("Question");
    expect(pageResults()).toBeNull();
    await askQuestion("hits the output limit");
    const block = await screen.findByRole("region", { name: "Question: hits the output limit" });
    const alert = await within(block).findByRole("alert");
    expect(alert).toHaveTextContent("output limit");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeVisible();
    expect(pageResults()).toBeNull();
    // Admins get a one-click way to the setting.
    await userEvent.click(within(alert).getByRole("button", { name: "Set Thinking to Off" }));
    expect(window.location.pathname + window.location.hash).toMatch(
      /^\/settings\/providers.*#edit=p1$|#edit=p1$/,
    );
  });

  it("offers no Thinking link to analysts", async () => {
    await renderAt("/ask-ai");
    await askQuestion("hits the output limit");
    const block = await screen.findByRole("region", { name: "Question: hits the output limit" });
    const alert = await within(block).findByRole("alert");
    expect(within(alert).queryByRole("button", { name: "Set Thinking to Off" })).toBeNull();
  });
});
