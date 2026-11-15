import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FirstAdminLinkPanel } from "@/features/auth/FirstAdminLinkPanel";
import { SigningKey } from "@/features/alerts/SigningKey";
import { EventDetail } from "@/features/search/EventDetail";
import { CopyRaw } from "@/features/search/CopyRaw";
import { CopyValue } from "@/features/settings/CopyValue";
import { CopyBlock } from "@/features/sources/OtlpSetup";
import { linkMessage, OneTimeLink } from "@/features/users/OneTimeLink";

/** A stored value with everything a careless copy loses: leading and trailing spaces, a
 * tab, and line breaks (owner, 2026-11-14: an exact copy path, byte for byte). */
const ODD = "  first\tline\nsecond line\r\nthird  ";

let writeText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

afterEach(() => vi.restoreAllMocks());

const copied = () => writeText.mock.calls.at(-1)?.[0] as string;

function detail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventDetail
        columns={["time", "device_hostname", "message", "raw"]}
        row={["2026-11-10T12:00:00+00:00", "ws-00\t42\nbuild", "a message", ODD]}
      />
    </QueryClientProvider>,
  );
}

const ID = "01a1d8cd-1966-73ae-9915-b447d4f1dc08";

/** An expanded row whose query named a cut value `raw` (`left(raw, 40) AS raw`); the full
 * event, looked up by id, holds the stored line. */
function lookedUp(answer: () => Promise<Response>) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    String(input).includes("/api/query")
      ? answer()
      : Promise.resolve(new Response("{}", { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventDetail columns={["event_id", "raw"]} row={[ID, "  first\tline"]} />
    </QueryClientProvider>,
  );
}

const fullEvent = () =>
  Promise.resolve(
    new Response(
      JSON.stringify({
        columns: ["event_id", "time", "raw"],
        rows: [[ID, "2026-11-10T12:00:00+00:00", ODD]],
        row_count: 1,
        truncated: false,
        elapsed_ms: 1,
        executed_sql: "",
        sources: [],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );

describe("The raw event of a row with an event id", () => {
  it("is the stored line from the full event, never the query's own raw column", async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((r) => (release = r));
    lookedUp(() => held.then(fullEvent));
    // While the full event loads: neither the cut value nor a Copy for it.
    expect(screen.queryByRole("button", { name: "Copy raw event" })).toBeNull();
    expect(screen.queryByText("first", { exact: false, selector: "pre" })).toBeNull();
    release();
    const copy = await screen.findByRole("button", { name: "Copy raw event" });
    const box = copy.parentElement!.parentElement!;
    expect(within(box).getByText("Raw event", { exact: false })).toBeVisible();
    expect(box.querySelector("pre")?.textContent).toBe(ODD);
    await userEvent.click(copy);
    expect(copied()).toBe(ODD);
  });

  it("says so plainly when the stored line cannot be loaded, and offers no Copy", async () => {
    lookedUp(() => Promise.resolve(new Response("{}", { status: 500 })));
    expect(await screen.findByText(/stored raw event could not be loaded/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Copy raw event" })).toBeNull();
    expect(document.querySelector("pre")).toBeNull();
  });

  it("reads Copy again when the line it shows changes", async () => {
    const { rerender } = render(<CopyRaw raw="one" />);
    await userEvent.click(screen.getByRole("button", { name: "Copy raw event" }));
    expect(screen.getByRole("button", { name: "Copy raw event" })).toHaveTextContent("Copied");
    rerender(<CopyRaw raw={ODD} />);
    expect(screen.getByRole("button", { name: "Copy raw event" })).toHaveTextContent("Copy");
    expect(screen.getByRole("button", { name: "Copy raw event" })).not.toHaveTextContent("Copied");
  });
});

describe("Exact copy paths (owner, 2026-11-14)", () => {
  it("shows a result's raw column as such when there is no event id, and copies it exactly", async () => {
    detail();
    const pre = screen.getByText("raw column of this result").parentElement!.querySelector("pre")!;
    expect(pre.textContent).toBe(ODD);
    expect(pre).toHaveClass("whitespace-pre-wrap");
    await userEvent.click(screen.getByRole("button", { name: "Copy raw event" }));
    expect(copied()).toBe(ODD);
  });

  it("copies every field exactly as JSON, a cut host with a tab and a break included", async () => {
    detail();
    await userEvent.click(screen.getByRole("button", { name: "Copy as JSON" }));
    const json = JSON.parse(copied()) as Record<string, string>;
    expect(json.raw).toBe(ODD);
    expect(json.device_hostname).toBe("ws-00\t42\nbuild");
  });

  it.each([
    ["a copy block", () => render(<CopyBlock label="Token" text={ODD} />), "Copy"],
    ["the single sign-on value", () => render(<CopyValue value={ODD} />), "Copy"],
    [
      "a signing key",
      () => render(<SigningKey name="hook" signingKey={ODD} onDone={() => {}} />),
      "Copy",
    ],
    [
      "the first administrator's link",
      () =>
        render(<FirstAdminLinkPanel value={{ username: "admin", link: ODD }} onDone={() => {}} />),
      "Copy",
    ],
    [
      "a one-time link",
      () => render(<OneTimeLink title="Invite" username="alice" link={ODD} onDone={() => {}} />),
      "Copy",
    ],
  ])("copies %s byte for byte", async (_name, draw, button) => {
    draw();
    await userEvent.click(screen.getByRole("button", { name: button }));
    expect(copied()).toBe(ODD);
  });

  it("copies a one-time link's message with the link in it exactly", async () => {
    render(<OneTimeLink title="Invite" username="alice" link={ODD} onDone={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(copied()).toBe(linkMessage("alice", ODD));
    expect(copied()).toContain(ODD);
  });
});
