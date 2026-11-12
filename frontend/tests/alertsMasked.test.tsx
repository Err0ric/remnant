import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DevicePeople } from "@/features/alerts/DevicePeople";
import { mockApi, type MockAuth } from "./mockApi";

const NOTE = "Names are hidden. An admin can turn on View people in AI usage for you.";

/** What the server sends a viewer without the permission for the AI Watch alert (D242). */
function masked(item: Record<string, unknown>): void {
  if (item.kind !== "ai_watch") return;
  Object.assign(item, {
    detail: "3 people: a person, a person, a person",
    people: [],
    people_hidden: 3,
    masked: true,
    devices: ["ws-0042"],
    device_people: [{ device: "ws-0042", level: "possible", people: [], count: 2, how: "hooks" }],
  });
}

async function renderAlerts(role: MockAuth["role"]) {
  window.history.replaceState(null, "", "/alerts");
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role });
  const base = spy.getMockImplementation()!;
  spy.mockImplementation(async (input, init) => {
    const res = await base(input, init);
    if (!/\/api\/alerts(\?|\/w1$)/.test(String(input))) return res;
    const body = await res.json();
    for (const i of body.items ?? [body]) masked(i);
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
}

afterEach(() => vi.restoreAllMocks());

describe("AI Watch alerts without View people in AI usage (D242)", () => {
  it.each(["analyst", "auditor"] as const)(
    "show text only and say names are hidden, for an %s",
    async (role) => {
      const errors = vi.spyOn(console, "error");
      await renderAlerts(role);
      const pane = await screen.findByRole("region", { name: "This alert" });
      expect(within(pane).getByRole("heading", { name: "New AI service: DeepSeek" })).toBeVisible();
      expect(within(pane).getByText(/3 people: a person, a person, a person/)).toBeVisible();
      expect(within(pane).getAllByText(NOTE)).toHaveLength(2); // People, Person on device
      expect(pane).toHaveTextContent("ws-0042: Possible, 2 people seen on this host in the hooks");
      const links = within(pane)
        .queryAllByRole("link")
        .map((a) => a.getAttribute("href") ?? "");
      expect(links.some((h) => h.includes("user="))).toBe(false);
      expect(errors).not.toHaveBeenCalled();
    },
  );
});

describe("Person on device, masked", () => {
  it("gives the count and how, with no name and no link", () => {
    render(
      <dl>
        <DevicePeople
          masked
          found={[{ device: "ws-0101.corp.internal", level: "attributed", people: [], count: 1, how: "hooks" }]} // prettier-ignore
        />
      </dl>,
    );
    expect(screen.getByText(/a person/)).toBeInTheDocument();
    expect(screen.getByText(", seen on this host in the hooks plugin")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });
});
