import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ReparseJob, type ReparseLast } from "@/lib/api";
import { ReparseRulesControl } from "@/features/sources/ReparseRulesControl";
import { SOURCE, mockApi } from "./mockApi";

const LAST: ReparseLast = {
  job_id: "11111111-1111-4111-8111-111111111111",
  state: "done",
  finished_at: "2026-10-10T12:01:00+00:00",
  rows_rewritten: 1200,
  time_min: "2026-10-09T20:01:06+00:00",
  time_max: "2026-10-10T08:00:00+00:00",
  rules_state: null,
  rules_run_at: null,
  rules_finished_at: null,
  rules_count: 0,
  rules_matched: 0,
  rules_items: 0,
  rules_error: null,
  rules_failed: [],
  rules_ready: true,
};

const STARTED: ReparseJob = {
  job_id: LAST.job_id,
  template_id: "linux_sshd",
  state: "done",
  started_at: "2026-10-10T12:00:00+00:00",
  finished_at: LAST.finished_at,
  rows_found: 1200,
  rows_rewritten: 1200,
  files_rewritten: 3,
  time_min: LAST.time_min,
  time_max: LAST.time_max,
  error: null,
  rules_state: "running",
};

function show(last: ReparseLast | null, canManage = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReparseRulesControl sourceId="edge_fw" canManage={canManage} last={last} />
    </QueryClientProvider>,
  );
}

const LABEL = "Run rules over the reparsed range";

afterEach(() => vi.restoreAllMocks());

describe("Run rules over the reparsed range (ADR-0050 row 7)", () => {
  it("asks first, naming the range, then starts once and shows it running", async () => {
    const start = vi.spyOn(api, "runReparseRules").mockResolvedValue(STARTED);
    show(LAST);
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    expect(start).not.toHaveBeenCalled(); // the first click only asks
    expect(
      screen.getByText(
        /Matches become alerts marked Late, and each rule's usual alert targets get one "Late detection from reparse" message\./,
      ),
    ).toBeInTheDocument();
    const times = document.querySelectorAll("time");
    expect([...times].map((t) => t.getAttribute("datetime"))).toEqual([
      LAST.time_min,
      LAST.time_max,
    ]);
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith("edge_fw", LAST.job_id);
    expect(await screen.findByText("Running rules over the reparsed range…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("Cancel closes the confirm step without starting", async () => {
    const start = vi.spyOn(api, "runReparseRules");
    show(LAST);
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(start).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: LABEL })).toBeInTheDocument();
  });

  it("shows the counts once done, with no button", () => {
    show({
      ...LAST,
      rules_state: "done",
      rules_finished_at: "2026-10-10T12:03:00+00:00",
      rules_count: 4,
      rules_matched: 12,
      rules_items: 1,
    });
    expect(
      screen.getByText(/Rules over the reparsed range: 12 matches from 4 rules, 1 alert/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a failure as text and offers the rest again", () => {
    show({ ...LAST, rules_state: "failed", rules_error: "<b>stopped</b>" });
    expect(
      screen.getByText("Rules over the reparsed range failed: <b>stopped</b>"),
    ).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByRole("button", { name: LABEL })).toBeInTheDocument();
  });

  it("shows a partial run's failed rules as text and offers only the remaining ones", async () => {
    const start = vi.spyOn(api, "runReparseRules").mockResolvedValue(STARTED);
    show({
      ...LAST,
      rules_state: "partial",
      rules_finished_at: "2026-10-10T12:03:00+00:00",
      rules_count: 3,
      rules_matched: 5,
      rules_items: 1,
      rules_error: "1 of 4 rules could not run. Run the remaining rules to try them again.",
      rules_failed: [
        { rule_id: "r2", title: "<i>SSH spray</i>", error: "QueryTimeoutError: took too long" },
      ],
    });
    expect(
      screen.getByText(/Rules over the reparsed range: 5 matches from 3 rules, 1 alert/),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 of 4 rules could not run/)).toBeInTheDocument();
    expect(
      screen.getByText("<i>SSH spray</i>: QueryTimeoutError: took too long"),
    ).toBeInTheDocument();
    expect(document.querySelector("i")).toBeNull();
    expect(screen.queryByRole("button", { name: LABEL })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run the remaining rules" }));
    expect(screen.getByText(/Run the rules that did not complete/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run the remaining rules" }));
    expect(start).toHaveBeenCalledWith("edge_fw", LAST.job_id);
  });

  it("says when a restart interrupted it", () => {
    show({ ...LAST, rules_state: "interrupted", rules_error: "The server stopped." });
    expect(
      screen.getByText("Rules over the reparsed range interrupted: The server stopped."),
    ).toBeInTheDocument();
  });

  it("offers it for a stopped reparse that rewrote the last waiting events", async () => {
    const start = vi.spyOn(api, "runReparseRules").mockResolvedValue({
      ...STARTED,
      state: "interrupted",
    });
    show({ ...LAST, state: "interrupted", rules_ready: true });
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    expect(start).toHaveBeenCalledWith("edge_fw", LAST.job_id);
    expect(await screen.findByText("Running rules over the reparsed range…")).toBeInTheDocument();
  });

  it("shows nothing for non-admins, no job, a job not ready, or one with no range", () => {
    show(LAST, false);
    show(null);
    show({ ...LAST, state: "running", rules_ready: false });
    show({ ...LAST, state: "failed", rules_ready: false });
    show({ ...LAST, time_min: null, time_max: null });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(/reparsed range/)).not.toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "runReparseRules").mockRejectedValue(
      new ApiError(409, "The rules already ran over this reparsed range"),
    );
    show(LAST);
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The rules already ran over this reparsed range",
    );
  });
});

describe("Rule re-run over a stopped reparse with events still waiting", () => {
  it("is offered from the list and shows the start's refusal with the count", async () => {
    const { ApiError } = await import("@/lib/api");
    const msg =
      "Reparse the remaining 2 events first. That reparse includes the events this one rewrote, and its rules can run once it is done";
    vi.spyOn(api, "runReparseRules").mockRejectedValue(new ApiError(409, msg));
    show({ ...LAST, state: "failed", rules_ready: true });
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    await userEvent.click(screen.getByRole("button", { name: LABEL }));
    expect(await screen.findByRole("alert")).toHaveTextContent(msg);
  });
});

describe("Sources page and the rule re-run", () => {
  it("offers it from the source list, with no request for sources without a job", async () => {
    window.history.replaceState(null, "", "/search");
    const spy = mockApi("Codename");
    const base = spy.getMockImplementation();
    const listed = [
      { ...SOURCE, source_id: "lin_plain", template_id: "linux_sshd", reparse_last: null },
      { ...SOURCE, source_id: "lin_back", template_id: "linux_sshd", reparse_last: LAST },
    ];
    spy.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/sources") && (init?.method ?? "GET") === "GET") {
        return new Response(JSON.stringify(listed), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return base!(input, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await userEvent.click(within(nav).getByText("Settings"));
    await screen.findByRole("heading", { level: 1, name: "Sources" });
    const button = await screen.findByRole("button", { name: LABEL });
    expect(button.closest("tr")).toHaveTextContent("lin_back");
    expect(screen.getAllByRole("button", { name: LABEL })).toHaveLength(1);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const asked = spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/reparse"));
    expect(asked).toEqual([]);
  });
});
