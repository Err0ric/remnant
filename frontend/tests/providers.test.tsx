import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "admin" },
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

function sent(spy: ReturnType<typeof mockApi>, method: string, test: (u: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

afterEach(() => vi.restoreAllMocks());

describe("AI providers", () => {
  it("tests a provider, picks a model from its list, and enables it", async () => {
    const spy = await renderAt("/providers");
    const table = await screen.findByRole("table", { name: "AI providers" });
    expect(await within(table).findByText("Local")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Enable Local Ollama" })).toBeDisabled();
    await userEvent.click(within(table).getByRole("button", { name: "Test Local Ollama" }));
    expect(await within(table).findByText("Reachable")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Edit Local Ollama" }));
    const form = screen.getByRole("form", { name: "Edit Local Ollama" });
    expect(form.querySelectorAll("datalist option")).toHaveLength(2);
    await userEvent.type(within(form).getByLabelText("Model"), "llama3.1:8b");
    await userEvent.click(within(form).getByRole("button", { name: "Save changes" }));
    const enable = await screen.findByRole("button", { name: "Enable Local Ollama" });
    await vi.waitFor(() => expect(enable).toBeEnabled());
    await userEvent.click(enable);
    const patches = sent(spy, "PATCH", (u) => u.includes("/api/providers/p1"));
    expect(patches[0]).toEqual({ name: "Local Ollama", model: "llama3.1:8b" }); // URL unchanged, not resent
    expect(patches[1]).toEqual({ enabled: true });
  });

  it("says when no model is chosen and lets Test's list pick one directly", async () => {
    const spy = await renderAt("/providers");
    const table = await screen.findByRole("table", { name: "AI providers" });
    expect(await within(table).findByText(/No model chosen/)).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Test Local Ollama" }));
    const picker = await within(table).findByRole("combobox", { name: "Model for Local Ollama" });
    await userEvent.selectOptions(picker, "llama3.1:8b");
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.includes("/api/providers/p1"))).toEqual([
        { model: "llama3.1:8b" },
      ]),
    );
    const enable = await screen.findByRole("button", { name: "Enable Local Ollama" });
    await vi.waitFor(() => expect(enable).toBeEnabled());
  });

  it("asks for an explicit acknowledgment before adding a cloud provider", async () => {
    const spy = await renderAt("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Add provider" }));
    const form = screen.getByRole("form", { name: "Add provider" });
    await userEvent.type(within(form).getByLabelText("Name"), "OpenAI");
    await userEvent.type(within(form).getByLabelText("Base URL"), "https://api.example.com/v1");
    await userEvent.type(within(form).getByLabelText("API key"), "sk-secret");
    await userEvent.click(within(form).getByRole("button", { name: "Add provider" }));
    const warning = await within(form).findByRole("alert");
    expect(warning).toHaveTextContent("local-only sources are always blocked");
    const submit = within(form).getByRole("button", { name: "Add provider" });
    expect(submit).toBeDisabled();
    await userEvent.click(within(warning).getByRole("checkbox"));
    await userEvent.click(submit);
    const table = await screen.findByRole("table", { name: "AI providers" });
    expect(await within(table).findByText("OpenAI")).toBeInTheDocument();
    expect(within(table).getByText("Cloud")).toBeInTheDocument();
    const posts = sent(spy, "POST", (u) => u.endsWith("/api/providers"));
    expect(posts.map((p) => p.acknowledge_cloud)).toEqual([undefined, true]);
    expect(document.body.textContent).not.toContain("sk-secret");
  });

  it("adds an Anthropic provider with its default URL, sent as kind anthropic", async () => {
    const spy = await renderAt("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Add provider" }));
    const form = screen.getByRole("form", { name: "Add provider" });
    await userEvent.selectOptions(within(form).getByLabelText("API"), "anthropic");
    expect(within(form).getByLabelText("Base URL")).toHaveValue("https://api.anthropic.com/v1");
    expect(within(form).getByText(/Always treated as a cloud provider/)).toBeInTheDocument();
    await userEvent.type(within(form).getByLabelText("Name"), "Claude");
    await userEvent.click(within(form).getByRole("button", { name: "Add provider" }));
    await within(form).findByRole("alert"); // the cloud acknowledgment
    const posts = sent(spy, "POST", (u) => u.endsWith("/api/providers"));
    expect(posts.at(-1)?.kind).toBe("anthropic");
  });

  it("lets an admin opt a cloud provider into redaction, off by default", async () => {
    const spy = await renderAt("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Add provider" }));
    const add = screen.getByRole("form", { name: "Add provider" });
    await userEvent.type(within(add).getByLabelText("Name"), "Hosted model");
    await userEvent.type(within(add).getByLabelText("Base URL"), "https://api.example.com/v1");
    await userEvent.click(within(add).getByRole("button", { name: "Add provider" }));
    await userEvent.click(within(await within(add).findByRole("alert")).getByRole("checkbox"));
    await userEvent.click(within(add).getByRole("button", { name: "Add provider" }));
    const table = await screen.findByRole("table", { name: "AI providers" });
    await userEvent.click(await within(table).findByRole("button", { name: "Edit Hosted model" }));
    const form = screen.getByRole("form", { name: "Edit Hosted model" });
    const box = within(form).getByRole("checkbox", { name: /as tokens/ });
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    await userEvent.click(within(form).getByRole("button", { name: /Save/ }));
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.includes("/api/providers/")).at(-1)?.redact).toBe(true),
    );
  });

  it("turns thinking off for a reasoning model", async () => {
    const spy = await renderAt("/providers");
    const table = await screen.findByRole("table", { name: "AI providers" });
    await userEvent.click(await within(table).findByRole("button", { name: "Edit Local Ollama" }));
    const form = screen.getByRole("form", { name: "Edit Local Ollama" });
    await userEvent.selectOptions(within(form).getByLabelText(/Thinking/), "none");
    await userEvent.click(within(form).getByRole("button", { name: "Save changes" }));
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.includes("/api/providers/")).at(-1)?.reasoning).toBe(
        "none",
      ),
    );
  });

  it("offers no redaction switch for local providers", async () => {
    await renderAt("/providers");
    const table = await screen.findByRole("table", { name: "AI providers" });
    await userEvent.click(await within(table).findByRole("button", { name: "Edit Local Ollama" }));
    const form = screen.getByRole("form", { name: "Edit Local Ollama" });
    expect(within(form).queryByRole("checkbox", { name: /as tokens/ })).toBeNull();
  });

  it("deletes only after confirmation", async () => {
    const spy = await renderAt("/providers");
    await userEvent.click(await screen.findByRole("button", { name: "Delete Local Ollama" }));
    expect(spy.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByText(/No providers/)).toBeInTheDocument();
  });

  it("is not shown to analysts", async () => {
    await renderAt("/providers", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("heading", { name: "Investigate", level: 1 });
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("AI providers")).not.toBeInTheDocument();
  });
});

describe("Locality badge", () => {
  it("explains a cloud badge caused by a host that does not resolve", async () => {
    const { LocalityBadge } = await import("@/features/providers/LocalityBadge");
    const { rerender } = render(<LocalityBadge locality="cloud" hostFound={false} />);
    expect(screen.getByText("Cloud")).toBeInTheDocument();
    expect(screen.getByText(/Host not found, so treated as cloud/)).toBeInTheDocument();
    rerender(<LocalityBadge locality="cloud" hostFound />);
    expect(screen.queryByText(/Host not found/)).not.toBeInTheDocument();
    rerender(<LocalityBadge locality="local" />);
    expect(screen.getByText("Local")).toBeInTheDocument();
  });
});
