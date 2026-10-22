import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function openSources(auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", "/search");
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  const nav = await screen.findByRole("navigation", { name: "Primary" });
  await userEvent.click(within(nav).getByText("Settings")); // opens Sources first
  await screen.findByRole("heading", { level: 1, name: "Sources" });
  return spy;
}

function posts(spy: ReturnType<typeof mockApi>, path: string) {
  return spy.mock.calls.filter(
    ([u, init]) => String(u).endsWith(path) && (init?.method ?? "GET") === "POST",
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Sources page", () => {
  it("discovers a folder and prefills the add form from a suggestion", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Discover" }));
    const panel = screen.getByRole("region", { name: "Discover sources" });
    expect(within(panel).getByLabelText("Folder")).toHaveValue("/logs");
    await userEvent.click(within(panel).getByRole("button", { name: "Scan folder" }));
    const row = (await within(panel).findByText("*/sshd.log")).closest("tr") as HTMLElement;
    expect(within(row).getByText("192.0.2.10, 192.0.2.11")).toBeInTheDocument();
    expect(within(row).getByText("matches 100% · parses 99%")).toBeInTheDocument();
    expect(within(panel).getByText(/skipped: 2 compressed/)).toBeInTheDocument();
    expect(within(panel).getByText(/also matches 2 other files/)).toBeInTheDocument();
    // Log text is shown as text, never as markup.
    expect(within(panel).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img[src=x]")).toBeNull();
    // Scanning creates nothing.
    expect(posts(spy, "/api/sources")).toHaveLength(0);

    await userEvent.click(within(row).getByRole("button", { name: "Add source for */sshd.log" }));
    const form = screen.getByRole("form", { name: "Add source" });
    // linux_sshd is already a source in the mock, so the suggestion does not collide.
    expect(within(form).getByLabelText("Source ID")).toHaveValue("linux_sshd_2");
    expect(within(form).getByLabelText("File pattern")).toHaveValue("*/sshd.log");
    await within(form).findByRole("option", { name: "Linux sshd authentication" });
    expect(within(form).getByLabelText("Parser")).toHaveValue("template:linux_sshd");
  });

  it("shows discovery errors from the server", async () => {
    await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Discover" }));
    const panel = screen.getByRole("region", { name: "Discover sources" });
    const folder = within(panel).getByLabelText("Folder");
    await userEvent.clear(folder);
    await userEvent.type(folder, "/etc");
    await userEvent.click(within(panel).getByRole("button", { name: "Scan folder" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("outside the allowed roots");
  });

  it("navigates from the side nav and shows status, counts, and data handling", async () => {
    await openSources();
    expect(window.location.pathname).toBe("/sources");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Settings")).toHaveAttribute("aria-current", "page");
    const sub = screen.getByRole("navigation", { name: "Settings" });
    expect(within(sub).getByText("Sources and connectors")).toHaveAttribute("aria-current", "page");
    const row = (await screen.findByText("linux_sshd")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Reading")).toBeInTheDocument();
    expect(within(row).getByText("Local only")).toBeInTheDocument();
    expect(await within(row).findByText("1,234")).toBeInTheDocument();
    expect(within(row).getByText("2 files · **/*.log")).toBeInTheDocument();
  });

  it("lets an admin change a source's classification, explaining what it means", async () => {
    const spy = await openSources();
    const row = (await screen.findByText("linux_sshd")).closest("tr") as HTMLElement;
    await userEvent.click(
      within(row).getByRole("button", { name: "Change classification of linux_sshd" }),
    );
    expect(within(row).getByText(/Events already stored stay local only/)).toBeInTheDocument();
    const save = within(row).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet
    await userEvent.click(within(row).getAllByRole("radio")[1]!);
    await userEvent.click(save);
    expect(await within(row).findByText("Cloud allowed")).toBeInTheDocument();
    const sent = spy.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/sources/linux_sshd") && init?.method === "PATCH",
    );
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ classification: "cloud_allowed" });
  });

  it("adds a Loki source after testing the connection, with the token sent once", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "loki");
    expect(within(form).queryByLabelText("File or folder")).toBeNull();
    await userEvent.type(within(form).getByLabelText("Source ID"), "loki_fw");
    await userEvent.type(within(form).getByLabelText("Loki URL"), "http://loki.internal:3100");
    await userEvent.type(within(form).getByLabelText("Query"), '{{job="syslog"}');
    await userEvent.selectOptions(within(form).getByLabelText("Sign-in"), "bearer");
    await userEvent.type(within(form).getByLabelText("Token"), "tok-123");
    await userEvent.click(within(form).getByRole("button", { name: "Test connection" }));
    expect(await within(form).findByText(/Connected: 42 lines/)).toBeInTheDocument();
    expect(within(form).getByText('{job="syslog", host="fw01"}')).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    await screen.findByText("loki_fw");
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as Record<
      string,
      unknown
    >;
    expect(body.kind).toBe("loki");
    expect(body.path).toBe("");
    expect(body.loki_secret).toBe("tok-123");
    expect(body.loki).toMatchObject({
      url: "http://loki.internal:3100",
      auth: "bearer",
      backfill_hours: 24,
    });
  });

  it("defaults a new source to the Automatic parser", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    expect(within(form).getByLabelText("Parser")).toHaveValue("auto:");
    expect(within(form).getByText(/matched to the template that fits it/)).toBeInTheDocument();
    await userEvent.type(within(form).getByLabelText("Source ID"), "host_syslog");
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    await screen.findByText("host_syslog");
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as {
      template_id: string;
      format: string;
    };
    expect(body).toMatchObject({ template_id: "auto", format: "syslog" });
  });

  it("lets an admin change a source's parser, for new lines only", async () => {
    const spy = await openSources();
    const row = (await screen.findByText("linux_sshd")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Change parser of linux_sshd" }));
    expect(within(row).getByText(/Only lines read from now on/)).toBeInTheDocument();
    await userEvent.selectOptions(within(row).getByLabelText("Parser for linux_sshd"), "auto:");
    await userEvent.click(within(row).getByRole("button", { name: "Save" }));
    expect(await within(row).findByText("Automatic")).toBeInTheDocument();
    const sent = spy.mock.calls.find(
      ([u, init]) =>
        String(u).endsWith("/api/sources/linux_sshd") &&
        init?.method === "PATCH" &&
        String(init.body).includes("template_id"),
    );
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ template_id: "auto" });
  });

  it("adds a source parsed by a template", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "bastion_auth");
    const parser = within(form).getByLabelText("Parser");
    await within(form).findByRole("option", { name: "Linux sshd authentication" });
    await userEvent.selectOptions(parser, "template:linux_sshd");
    expect(within(form).getByText(/OpenSSH server authentication/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    await screen.findByText("bastion_auth");
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as {
      template_id: string;
      format: string;
    };
    expect(body).toMatchObject({ template_id: "linux_sshd", format: "syslog" });
  });

  it("adds a source and shows server-side path errors", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    expect(within(form).getByText("Must be inside: /logs")).toBeInTheDocument();
    await userEvent.type(within(form).getByLabelText("Source ID"), "fw_traffic");
    const path = within(form).getByLabelText("File or folder");
    await userEvent.clear(path);
    await userEvent.type(path, "/etc");
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("outside the allowed roots");

    await userEvent.clear(path);
    await userEvent.type(path, "/logs/fw");
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    expect(await screen.findByText("fw_traffic")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Add source" })).not.toBeInTheDocument();
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as {
      path: string;
      glob: string;
    };
    expect(body).toMatchObject({ path: "/logs/fw", glob: "**/*.log" });
  });

  it("checks the source ID before sending", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "Bad-Name");
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("lowercase letters");
    expect(posts(spy, "/api/sources")).toHaveLength(0);
  });

  it("asks for confirmation before removing", async () => {
    await openSources();
    await userEvent.click(await screen.findByRole("button", { name: "Remove linux_sshd" }));
    expect(screen.getByText(/Data already collected stays searchable/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText("linux_sshd")).not.toBeInTheDocument());
  });

  it("hides management actions from analysts", async () => {
    await openSources({ mode: "login", signedIn: true, role: "analyst" });
    await screen.findByText("linux_sshd");
    expect(screen.queryByRole("button", { name: "Add source" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Change parser/ })).not.toBeInTheDocument();
  });
});

describe("Write a parser from Discover", () => {
  it("opens a new draft filled in from a candidate no template fits", async () => {
    await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Discover" }));
    const panel = screen.getByRole("region", { name: "Discover sources" });
    await userEvent.click(within(panel).getByRole("button", { name: "Scan folder" }));
    await within(panel).findByText("notes.txt");
    // A candidate a template fits offers no parser writing.
    expect(
      within(panel).queryByRole("button", { name: "Write a parser for */sshd.log" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(panel).getByRole("button", { name: "Write a parser for notes.txt" }),
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Templates" })).toBeInTheDocument();
    const form = await screen.findByRole("form", { name: "New template draft" });
    expect(within(form).getByLabelText("Template ID")).toHaveValue("notes");
    expect(within(form).getByLabelText("File on this server")).toBeChecked();
    expect(within(form).getByLabelText("File or folder")).toHaveValue("/logs");
    expect(within(form).getByLabelText("File pattern")).toHaveValue("notes.txt");
  });
});

describe("Source status", () => {
  const base = {
    state: "reading" as const,
    files: 1,
    last_pass_at: null,
    last_event_at: null,
    events_since_start: 0,
    error: null,
    records_skipped: 0,
    files_waiting: 0,
  };

  it("says how many records could not be read, and nothing when none were lost", async () => {
    const { SourceState } = await import("@/features/sources/SourceState");
    const { rerender } = render(<SourceState status={base} />);
    expect(screen.queryByText(/could not be read/)).not.toBeInTheDocument();
    rerender(<SourceState status={{ ...base, records_skipped: 1 }} />);
    expect(
      screen.getByText("1 record could not be read (latest read); see the server log"),
    ).toBeInTheDocument();
    rerender(<SourceState status={{ ...base, records_skipped: 3 }} />);
    expect(screen.getByText(/^3 records could not be read/)).toBeInTheDocument();
    rerender(<SourceState status={{ ...base, files_waiting: 1 }} />);
    expect(screen.getByText(/1 .evtx file looks partly copied/)).toBeInTheDocument();
  });

  it("warns when event times look a whole number of hours off", async () => {
    const { SourceState } = await import("@/features/sources/SourceState");
    render(
      <SourceState
        status={{
          ...base,
          time_offset_h: 7,
          time_offset_text: "Event times look 7 hours early; check this source's time zone",
        }}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "Event times look 7 hours early; check this source's time zone.",
    );
  });

  it("lets an admin change a source's time zone", async () => {
    const spy = await openSources();
    await userEvent.click(
      await screen.findByRole("button", { name: "Change time zone of linux_sshd" }),
    );
    const form = screen.getByRole("form", { name: "Time zone of linux_sshd" });
    const input = within(form).getByLabelText("Time zone (IANA name)");
    await userEvent.clear(input);
    await userEvent.type(input, "America/Los_Angeles");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        spy.mock.calls
          .filter(
            ([u, i]) => String(u).endsWith("/api/sources/linux_sshd") && i?.method === "PATCH",
          )
          .map(([, i]) => JSON.parse(String(i?.body))),
      ).toEqual([{ timezone: "America/Los_Angeles" }]),
    );
  });
});

describe("Quiet-source alert (ADR-0014)", () => {
  function puts(spy: ReturnType<typeof mockApi>) {
    return spy.mock.calls.filter(
      ([u, init]) => String(u).endsWith("/watch") && init?.method === "PUT",
    );
  }

  it("lets an admin set a quiet period and targets, then turn it off", async () => {
    const spy = await openSources();
    const row = (await screen.findByText("linux_sshd")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Quiet alert for linux_sshd" }));
    const box = within(row).getByRole("group", { name: "Quiet alert for linux_sshd" });
    await userEvent.selectOptions(within(box).getByLabelText("Alert if no events for"), "14400");
    await userEvent.click(await within(box).findByRole("checkbox", { name: "SOC Slack" }));
    await userEvent.click(within(box).getByRole("button", { name: "Save" }));
    const init = puts(spy)[0]?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({ quiet_after_s: 14400, target_ids: ["t1"] });
    expect(await within(row).findByText("Alert after 4 hours quiet")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Quiet alert for linux_sshd" }));
    const again = within(row).getByRole("group", { name: "Quiet alert for linux_sshd" });
    expect(await within(again).findByRole("checkbox", { name: "SOC Slack" })).toBeChecked();
    await userEvent.selectOptions(within(again).getByLabelText("Alert if no events for"), "off");
    await userEvent.click(within(again).getByRole("button", { name: "Save" }));
    expect(JSON.parse(String(puts(spy)[1]?.[1]?.body))).toEqual({
      quiet_after_s: null,
      target_ids: [],
    });
    expect(
      await within(row).findByRole("button", { name: "Quiet alert for linux_sshd" }),
    ).toHaveTextContent("Alert if quiet");
  });

  it("shows the quiet state to everyone and the setting only to admins", async () => {
    const { QuietAlert } = await import("@/features/sources/QuietAlert");
    const quiet = {
      quiet_after_s: 3600,
      state: "quiet" as const,
      quiet_since: "2026-10-10T11:00:00+00:00",
      last_seen: "2026-10-10T10:00:00+00:00",
    };
    const { rerender } = render(<QuietAlert sourceId="s" quiet={quiet} canManage={false} />);
    expect(screen.getByText(/^Quiet: nothing received/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<QuietAlert sourceId="s" quiet={{ ...quiet, state: "ok" }} canManage={false} />);
    expect(screen.queryByText(/^Quiet/)).toBeNull();
  });
});

describe("OTLP sources (ADR-0015)", () => {
  it("adds an OTLP source and shows the token and Claude Code settings once", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "claude_code");
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "otlp");
    expect(within(form).queryByLabelText("File or folder")).toBeNull();
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    const panel = await screen.findByRole("region", { name: "Ingest token" });
    expect(within(panel).getByLabelText("Token")).toHaveTextContent("rmt_test_token_value");
    const settings = within(panel).getByLabelText("Claude Code managed settings (env block)");
    expect(settings).toHaveTextContent('"OTEL_EXPORTER_OTLP_PROTOCOL": "http/json"');
    expect(settings).toHaveTextContent("Authorization=Bearer rmt_test_token_value");
    const body = JSON.parse(String(posts(spy, "/api/sources")[0]?.[1]?.body)) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({ kind: "otlp", format: "json", template_id: "auto", path: "" });
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("region", { name: "Ingest token" })).toBeNull();
    const row = (await screen.findByText("claude_code")).closest("tr") as HTMLElement;
    expect(within(row).getByText(/OTLP receiver/)).toBeInTheDocument();
    expect(
      within(row).getByRole("checkbox", { name: /Keep prompt and tool content/ }),
    ).not.toBeChecked();
  });

  it("adds a syslog listener with protocol, port, and allowed senders", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "firewall");
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "syslog");
    expect(within(form).queryByLabelText("File or folder")).toBeNull();
    expect(within(form).getByLabelText("Port")).toHaveValue(5514);
    await userEvent.selectOptions(within(form).getByLabelText("Protocol"), "tls");
    expect(within(form).getByLabelText("Port")).toHaveValue(6514); // follows the protocol
    await userEvent.click(within(form).getByText("Parsing and retention"));
    await userEvent.type(
      within(form).getByLabelText("Allowed senders"),
      "192.168.1.0/24{enter}10.0.0.5",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    await waitFor(() => expect(posts(spy, "/api/sources")).toHaveLength(1));
    const body = JSON.parse(String(posts(spy, "/api/sources")[0]?.[1]?.body)) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      kind: "syslog",
      format: "syslog",
      path: "",
      syslog: { protocol: "tls", port: 6514, allowed_senders: ["192.168.1.0/24", "10.0.0.5"] },
    });
    const row = (await screen.findByText("firewall")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Syslog TLS")).toBeInTheDocument();
    expect(within(row).getByText(/1,200 received, 4 refused/)).toBeInTheDocument();
    await userEvent.click(within(row).getByText("Senders (2)"));
    const senders = within(row).getByRole("list", { name: "Senders" });
    expect(within(senders).getByText("Refused")).toBeVisible();
  });

  it("adds a Microsoft 365 source with a certificate after a per-feed test", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "m365");
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "m365");
    expect(within(form).queryByLabelText("File or folder")).toBeNull();
    const tenant = "11111111-2222-4333-8444-555555555555";
    await userEvent.type(within(form).getByLabelText("Directory (tenant) ID"), tenant);
    await userEvent.type(
      within(form).getByLabelText("Application (client) ID"),
      "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    );
    await userEvent.type(within(form).getByLabelText("Certificate (PEM)"), "CERT");
    await userEvent.type(within(form).getByLabelText("Private key (PEM, unencrypted)"), "KEY");
    await userEvent.click(within(form).getByLabelText(/DLP rule matches/));
    await userEvent.click(within(form).getByRole("button", { name: "Test connection" }));
    const result = await within(form).findByRole("status");
    expect(
      within(result).getByText("A1B2C3D4E5F60718293A4B5C6D7E8F9012345678"),
    ).toBeInTheDocument();
    expect(within(result).getByText(/need Entra ID P1 or P2/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    const row = (await screen.findByText(tenant)).closest("tr") as HTMLElement;
    expect(within(row).getByText("Microsoft 365")).toBeInTheDocument();
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      kind: "m365",
      format: "json",
      template_id: "auto",
      path: "",
      credentials: { certificate_pem: "CERT", private_key_pem: "KEY" },
    });
    expect((body.m365 as { content_types: string[] }).content_types).toContain("DLP.All");
    expect(JSON.stringify(within(row).getByText(tenant).closest("td")?.textContent)).not.toContain(
      "KEY",
    );
  });

  it("adds an Anthropic source with the reports template and replaces its key later", async () => {
    const spy = await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    await userEvent.type(within(form).getByLabelText("Source ID"), "claude_admin");
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "anthropic");
    await userEvent.type(within(form).getByLabelText("API key"), "sk-ant-admin01-x");
    await userEvent.click(within(form).getByRole("button", { name: "Add source" }));
    const row = (await screen.findByText("claude_admin")).closest("tr") as HTMLElement;
    const body = JSON.parse(String(posts(spy, "/api/sources").at(-1)?.[1]?.body)) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      kind: "anthropic",
      template_id: "anthropic_reports",
      anthropic: { key_type: "admin", feeds: ["usage", "cost", "claude_code"] },
      credentials: { api_key: "sk-ant-admin01-x" },
    });
    await userEvent.click(within(row).getByRole("button", { name: "Replace credentials" }));
    const replace = within(row).getByRole("form", { name: /Replace credentials/ });
    await userEvent.type(within(replace).getByLabelText("API key"), "sk-ant-admin01-new");
    await userEvent.click(within(replace).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(within(row).queryByRole("form", { name: /Replace credentials/ })).toBeNull(),
    );
    const put = spy.mock.calls.find(
      ([u, init]) => String(u).endsWith("/credentials") && init?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ api_key: "sk-ant-admin01-new" });
  });

  it("keeps settings with defaults in a separate, labeled Optional block", async () => {
    await openSources();
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    const form = screen.getByRole("form", { name: "Add source" });
    const block = within(form).getByText("Optional").closest("details") as HTMLElement;
    expect(block).not.toHaveAttribute("open");
    expect(
      within(block).getByText(
        /Parser: Automatic · Pattern: \*\*\/\*\.log · Time zone: UTC · Keep 30 days/,
      ),
    ).toBeInTheDocument();
    expect(within(block).getByLabelText("Time zone")).toBeInTheDocument();
    expect(within(block).queryByLabelText("Source ID")).toBeNull();
    await userEvent.selectOptions(within(form).getByLabelText("Reads from"), "m365");
    const blocks = within(form)
      .getAllByText("Optional")
      .map((el) => el.closest("details") as HTMLElement);
    expect(blocks).toHaveLength(2);
    expect(
      within(blocks[0] as HTMLElement).getByText(/Cloud: Commercial · Feeds:/),
    ).toBeInTheDocument();
    expect(within(blocks[0] as HTMLElement).getByLabelText("Cloud")).toBeInTheDocument();
    expect(within(form).getByLabelText("Directory (tenant) ID").closest("details")).toBeNull();
  });
});

describe("Add a Loki source (F27)", () => {
  it("offers the Loki address existing sources use", async () => {
    const spy = await openSources();
    const real = spy.getMockImplementation();
    spy.mockImplementation((url, init) =>
      String(url).endsWith("/api/sources") && (init?.method ?? "GET") === "GET"
        ? Promise.resolve(
            new Response(
              JSON.stringify([
                {
                  source_id: "loki_dns",
                  kind: "loki",
                  format: "syslog",
                  path: "",
                  glob: "*",
                  timezone: "UTC",
                  retention_days: 30,
                  classification: "local_only",
                  enabled: true,
                  loki: {
                    url: "http://10.20.0.40:3100",
                    query: '{job="dns"}',
                    auth: "none",
                    backfill_hours: 24,
                  },
                  status: {
                    state: "reading",
                    files: 0,
                    last_pass_at: null,
                    last_event_at: null,
                    events_since_start: 0,
                    error: null,
                    records_skipped: 0,
                    files_waiting: 0,
                  },
                },
              ]),
              { headers: { "Content-Type": "application/json" } },
            ),
          )
        : (real as typeof fetch)(url, init),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Add source" }));
    await userEvent.selectOptions(await screen.findByLabelText("Reads from"), "loki");
    await userEvent.click(
      await screen.findByRole("button", { name: "Use http://10.20.0.40:3100" }),
    );
    expect(screen.getByLabelText("Loki URL")).toHaveValue("http://10.20.0.40:3100");
  });
});
