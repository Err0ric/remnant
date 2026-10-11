import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function openApp(auth: MockAuth = { mode: "open" }) {
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
  return { spy, nav: await screen.findByRole("navigation", { name: "Primary" }) };
}

function calls(spy: ReturnType<typeof mockApi>, path: string, method: string) {
  return spy.mock.calls.filter(
    ([u, init]) => String(u).endsWith(path) && (init?.method ?? "GET") === method,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Templates page", () => {
  it("creates a draft from pasted lines, previews it, and approves it", async () => {
    const { spy, nav } = await openApp();
    await userEvent.click(within(nav).getByText("Templates"));
    await screen.findByRole("heading", { level: 1, name: "Templates" });
    expect(window.location.pathname).toBe("/templates");

    await userEvent.click(screen.getByRole("button", { name: "New draft" }));
    const form = screen.getByRole("form", { name: "New template draft" });
    await userEvent.type(within(form).getByLabelText("Template ID"), "widget_app");
    await userEvent.type(within(form).getByLabelText("Pasted sample"), "widget started");
    await userEvent.click(within(form).getByRole("button", { name: "Create draft" }));

    const editor = await screen.findByRole("region", { name: "Draft widget_app" });
    expect(within(editor).getByLabelText("Template YAML")).toHaveTextContent("id: widget_app");
    const approve = within(editor).getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled(); // nothing previewed yet

    await userEvent.click(within(editor).getByRole("button", { name: "Preview" }));
    expect(await within(editor).findByText("Ready to approve")).toBeInTheDocument();
    // Sample text is rendered as text, never as markup.
    expect(within(editor).getByText("<b>widget</b> started")).toBeInTheDocument();
    expect(within(editor).getByText("widget started")).toBeInTheDocument();
    expect(approve).toBeEnabled();

    await userEvent.click(approve);
    expect(await screen.findByRole("region", { name: "Approved" })).toHaveTextContent(
      "Approved widget_app 0.1.0",
    );
    const sent = calls(spy, "/api/templates/drafts/widget_app/approve", "POST");
    expect(sent).toHaveLength(1);
    // The approval names the preview that was reviewed.
    expect(JSON.parse(String(sent[0]?.[1]?.body))).toEqual({ sha256: "cd".repeat(32) });
  });

  it("shows validation problems and keeps Approve off", async () => {
    const { nav } = await openApp();
    await userEvent.click(within(nav).getByText("Templates"));
    await userEvent.click(await screen.findByRole("button", { name: "New draft" }));
    const form = screen.getByRole("form", { name: "New template draft" });
    await userEvent.type(within(form).getByLabelText("Template ID"), "broken_app");
    await userEvent.type(within(form).getByLabelText("Pasted sample"), "anything");
    await userEvent.click(within(form).getByRole("button", { name: "Create draft" }));
    const editor = await screen.findByRole("region", { name: "Draft broken_app" });
    await userEvent.click(within(editor).getByRole("button", { name: "Preview" }));
    const alert = await within(editor).findByRole("alert");
    expect(alert).toHaveTextContent("Not a valid template");
    expect(alert).toHaveTextContent("mapping: field required");
    expect(within(editor).getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("drafts with a model and marks the draft as model-written", async () => {
    const { spy, nav } = await openApp();
    await userEvent.click(within(nav).getByText("Templates"));
    await userEvent.click(await screen.findByRole("button", { name: "New draft" }));
    const form = screen.getByRole("form", { name: "New template draft" });
    await userEvent.type(within(form).getByLabelText("Template ID"), "kv_app");
    await userEvent.type(within(form).getByLabelText("Pasted sample"), "a=1 b=2 c=3");
    await userEvent.click(within(form).getByRole("button", { name: "Create draft" }));
    const editor = await screen.findByRole("region", { name: "Draft kv_app" });
    await userEvent.click(await within(editor).findByRole("button", { name: "Draft parser" }));
    expect(await within(editor).findByText(/Drafted by a model/)).toBeInTheDocument();
    expect(within(editor).getByLabelText("Template YAML")).toHaveTextContent("format: kv");
    expect(calls(spy, "/api/templates/drafts/kv_app/ai-draft", "POST")).toHaveLength(1);
    // Still needs a clean preview before it can be approved.
    expect(within(editor).getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("explains a refused starter id", async () => {
    const { nav } = await openApp();
    await userEvent.click(within(nav).getByText("Templates"));
    await userEvent.click(await screen.findByRole("button", { name: "New draft" }));
    const form = screen.getByRole("form", { name: "New template draft" });
    await userEvent.type(within(form).getByLabelText("Template ID"), "linux_sshd");
    await userEvent.click(within(form).getByRole("button", { name: "Create draft" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("starter template");
  });

  it("is not offered to analysts", async () => {
    const { nav } = await openApp({ mode: "login", signedIn: true, role: "analyst" });
    expect(within(nav).queryByText("Templates")).not.toBeInTheDocument();
  });
});
