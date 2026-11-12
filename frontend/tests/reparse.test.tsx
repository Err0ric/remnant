import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ReparseJob, type ReparseStatus } from "@/lib/api";
import { ReparseControl } from "@/features/sources/ReparseControl";
import { SOURCE, mockApi } from "./mockApi";

const JOB: ReparseJob = {
  job_id: "11111111-1111-4111-8111-111111111111",
  template_id: "linux_sshd",
  state: "done",
  started_at: "2026-10-10T12:00:00+00:00",
  finished_at: "2026-10-10T12:01:00+00:00",
  rows_found: 1200,
  rows_rewritten: 1200,
  files_rewritten: 3,
  time_min: "2026-10-09T20:01:06+00:00",
  time_max: "2026-10-10T08:00:00+00:00",
  error: null,
};

function status(over: Partial<ReparseStatus> = {}): ReparseStatus {
  return {
    source_id: "edge_fw",
    template_id: "linux_sshd",
    template_available: true,
    pending: 1200,
    job: null,
    ...over,
  };
}

function control(canManage: boolean, templateId: string | null, pending: boolean) {
  return (
    <ReparseControl
      sourceId="edge_fw"
      templateId={templateId}
      canManage={canManage}
      pending={pending}
    />
  );
}

function show(canManage = true, templateId: string | null = "linux_sshd", pending = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (ui: React.ReactElement) => (
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>
  );
  const view = render(wrap(control(canManage, templateId, pending)));
  return (next: boolean) => view.rerender(wrap(control(canManage, templateId, next)));
}

afterEach(() => vi.restoreAllMocks());

describe("Reparse events stored without the template (ADR-0050 row 7)", () => {
  it("offers the reparse with a confirm step, then shows the running job", async () => {
    const get = vi
      .spyOn(api, "reparseStatus")
      .mockResolvedValueOnce(status())
      .mockResolvedValue(
        status({ job: { ...JOB, state: "running", rows_rewritten: 400, finished_at: null } }),
      );
    const start = vi
      .spyOn(api, "startReparse")
      .mockResolvedValue({ ...JOB, state: "running", rows_rewritten: 0, finished_at: null });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Reparse 1,200 events" }));
    expect(start).not.toHaveBeenCalled(); // the first click only asks
    expect(screen.getByText(/Event IDs, raw lines, and times stay the same/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reparse 1,200 events" }));
    expect(start).toHaveBeenCalledWith("edge_fw");
    expect(await screen.findByText("Reparsing: 400 of 1,200 events")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reparse/ })).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("edge_fw");
  });

  it("Cancel closes the confirm step without starting", async () => {
    vi.spyOn(api, "reparseStatus").mockResolvedValue(status({ pending: 1 }));
    const start = vi.spyOn(api, "startReparse");
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Reparse 1 event" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(start).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reparse 1 event" })).toBeInTheDocument();
  });

  it("shows no button while the template is still missing", async () => {
    const get = vi
      .spyOn(api, "reparseStatus")
      .mockResolvedValue(status({ template_available: false }));
    show();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a finished job with its counts", async () => {
    vi.spyOn(api, "reparseStatus").mockResolvedValue(status({ pending: 0, job: JOB }));
    show();
    expect(await screen.findByText(/Reparsed 1,200 events in 3 files/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a failed job's error as text, and an interrupted one", async () => {
    vi.spyOn(api, "reparseStatus").mockResolvedValue(
      status({
        pending: 800,
        job: { ...JOB, state: "failed", rows_rewritten: 400, error: "<b>disk full</b>" },
      }),
    );
    show();
    expect(
      await screen.findByText("Reparse failed after 400 events: <b>disk full</b>"),
    ).toBeInTheDocument();
    // The rest can be started again.
    expect(screen.getByRole("button", { name: "Reparse 800 events" })).toBeInTheDocument();
  });

  it("says when a restart interrupted the job", async () => {
    vi.spyOn(api, "reparseStatus").mockResolvedValue(
      status({
        pending: 0,
        job: { ...JOB, state: "interrupted", rows_rewritten: 10, error: "The server stopped." },
      }),
    );
    show();
    expect(
      await screen.findByText("Reparse interrupted after 10 events: The server stopped."),
    ).toBeInTheDocument();
  });

  it("never asks for non-admins, sources without a template, or unflagged sources", async () => {
    const get = vi.spyOn(api, "reparseStatus").mockResolvedValue(status());
    show(false);
    show(true, null);
    show(true, "auto");
    show(true, "linux_sshd", false); // the source list says nothing waits
    await new Promise((r) => setTimeout(r, 10));
    expect(get).not.toHaveBeenCalled();
  });

  it("follows a running job to its end after the source list drops the flag", async () => {
    const running = status({
      job: { ...JOB, state: "running", rows_rewritten: 400, finished_at: null },
    });
    const get = vi
      .spyOn(api, "reparseStatus")
      .mockResolvedValueOnce(running)
      .mockResolvedValue(status({ pending: 0, job: JOB }));
    const flag = show();
    expect(await screen.findByText("Reparsing: 400 of 1,200 events")).toBeInTheDocument();
    flag(false); // the list refreshed first: the job is done on the server
    expect(
      await screen.findByText(/Reparsed 1,200 events in 3 files/, undefined, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("shows the server's refusal", async () => {
    const { ApiError } = await import("@/lib/api");
    vi.spyOn(api, "reparseStatus").mockResolvedValue(status());
    vi.spyOn(api, "startReparse").mockRejectedValue(
      new ApiError(409, "A reparse is already running for this source"),
    );
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Reparse 1,200 events" }));
    await userEvent.click(screen.getByRole("button", { name: "Reparse 1,200 events" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A reparse is already running for this source",
    );
  });
});

describe("Sources page and the reparse count (review on #500)", () => {
  it("asks for the exact count only for sources the list flags", async () => {
    window.history.replaceState(null, "", "/search");
    const spy = mockApi("Codename");
    const base = spy.getMockImplementation();
    const listed = [
      { ...SOURCE, source_id: "lin_plain", template_id: "linux_sshd", reparse_pending: false },
      { ...SOURCE, source_id: "lin_back", template_id: "linux_sshd", reparse_pending: true },
    ];
    const reply = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    spy.mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/sources") && method === "GET") return reply(listed);
      if (url.endsWith("/reparse") && method === "GET") {
        return reply(status({ source_id: "lin_back", pending: 7 }));
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
    expect(await screen.findByRole("button", { name: "Reparse 7 events" })).toBeInTheDocument();
    const asked = spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/reparse"));
    expect(asked.length).toBeGreaterThan(0);
    expect(asked.every((u) => u.endsWith("/api/sources/lin_back/reparse"))).toBe(true);
  });
});
