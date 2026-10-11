import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth = { mode: "login", signedIn: true }) {
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

afterEach(() => vi.restoreAllMocks());

describe("Users and access", () => {
  it("lists users with role, status, and source access", async () => {
    await renderAt("/users");
    const usersTable = await screen.findByRole("table", { name: "Users" });
    const row = (await within(usersTable).findByText("kelly")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("combobox", { name: "Role for kelly" })).toHaveValue("analyst");
    expect(within(row).getByText("Active")).toBeInTheDocument();
    expect(within(row).getByText("Security")).toBeInTheDocument();
    const me = within(usersTable).getByText("jordan").closest("tr") as HTMLElement;
    expect(within(me).getByText("(you)")).toBeInTheDocument();
    expect(within(me).getByText("All sources")).toBeInTheDocument();
  });

  it("invites a user and shows the one-time link once", async () => {
    await renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    const form = screen.getByRole("form", { name: "Invite user" });
    await userEvent.type(within(form).getByLabelText("Username"), "dana");
    await userEvent.selectOptions(within(form).getByLabelText("Role"), "auditor");
    await userEvent.click(within(form).getByRole("button", { name: "Create invite link" }));
    const panel = await screen.findByRole("region", { name: "Invite link" });
    expect(within(panel).getByLabelText("One-time link")).toHaveValue(
      `${window.location.origin}/account#invite-token-123`,
    );
    expect(within(panel).getByText(/not shown again/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("region", { name: "Invite link" })).not.toBeInTheDocument();
    expect(await screen.findByText("Invite pending")).toBeInTheDocument();
  });

  it("asks before disabling and shows the last-admin refusal inline", async () => {
    await renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: "Disable jordan" }));
    expect(screen.getByText(/signs jordan out everywhere/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disable" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("last active administrator");
  });

  it("creates a reset link", async () => {
    await renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: "Reset link for kelly" }));
    const panel = await screen.findByRole("region", { name: "Reset link" });
    expect(within(panel).getByLabelText("One-time link")).toHaveValue(
      `${window.location.origin}/account#reset-token-456`,
    );
  });

  it("is not offered to analysts, even by URL", async () => {
    await renderAt("/users", { mode: "login", signedIn: true, role: "analyst" });
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Users and access")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Users and access" })).not.toBeInTheDocument();
  });
});

describe("Account password page", () => {
  it("sets a password from an invite link while signed out and clears the token", async () => {
    await renderAt("/account#invite-token-123", { mode: "login" });
    await userEvent.type(await screen.findByLabelText("New password"), "a long passphrase");
    await userEvent.type(screen.getByLabelText("Confirm password"), "a long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByText("Password set")).toBeInTheDocument();
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("explains a spent link", async () => {
    await renderAt("/account#used-token", { mode: "login" });
    await userEvent.type(await screen.findByLabelText("New password"), "a long passphrase");
    await userEvent.type(screen.getByLabelText("Confirm password"), "a long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already used");
  });
});

describe("Source groups", () => {
  function puts(spy: ReturnType<typeof mockApi>, suffix: string) {
    return spy.mock.calls
      .filter(([u, init]) => String(u).endsWith(suffix) && init?.method === "PUT")
      .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, string[]>);
  }

  it("lists groups with their sources and members", async () => {
    await renderAt("/users");
    const groupsTable = await screen.findByRole("table", { name: "Source groups" });
    const row = (await within(groupsTable).findByText("Security")).closest("tr") as HTMLElement;
    expect(within(row).getByText("linux_sshd")).toBeInTheDocument();
    expect(within(row).getByText("kelly")).toBeInTheDocument();
  });

  it("creates a group, then saves its sources and members", async () => {
    const spy = await renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: "New group" }));
    const form = screen.getByRole("form", { name: "New group" });
    await userEvent.type(within(form).getByLabelText("Name"), "Network");
    await userEvent.click(within(form).getByRole("button", { name: "Create group" }));
    const editor = await screen.findByRole("region", { name: "Edit group Network" });
    expect(within(editor).queryByText("jordan")).not.toBeInTheDocument(); // admins see all already
    await userEvent.click(within(editor).getByRole("checkbox", { name: /linux_sshd/ }));
    await userEvent.click(within(editor).getByRole("button", { name: "Save sources" }));
    await waitFor(() => expect(puts(spy, "/sources")).toEqual([{ source_ids: ["linux_sshd"] }]));
    // Saving refreshes the group, which remounts the editor: look it up again.
    const fresh = await screen.findByRole("region", { name: "Edit group Network" });
    await userEvent.click(within(fresh).getByRole("checkbox", { name: /kelly/ }));
    await userEvent.click(within(fresh).getByRole("button", { name: "Save members" }));
    await waitFor(() => expect(puts(spy, "/members")).toEqual([{ user_ids: ["u2"] }]));
  });

  it("asks before deleting a group", async () => {
    await renderAt("/users");
    await userEvent.click(await screen.findByRole("button", { name: "Edit Security" }));
    const editor = screen.getByRole("region", { name: "Edit group Security" });
    await userEvent.click(within(editor).getByRole("button", { name: "Delete group" }));
    expect(within(editor).getByText(/lose access/)).toBeInTheDocument();
    await userEvent.click(within(editor).getByRole("button", { name: "Delete group" }));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Edit group Security" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/No groups yet/)).toBeInTheDocument();
  });
});

describe("First administrator on an install with no accounts", () => {
  it("defaults to Administrator and keeps the one-time link after sign-in takes over", async () => {
    await renderAt("/users", { mode: "open", noAccounts: true });
    await userEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    const form = screen.getByRole("form", { name: "Invite user" });
    expect(within(form).getByLabelText("Role")).toHaveValue("admin");
    await userEvent.type(within(form).getByLabelText("Username"), "jordan");
    await userEvent.click(within(form).getByRole("button", { name: "Create invite link" }));
    // Creating the first account ends open mode, so the app moves to sign-in. The link
    // must still be on screen: it is the only way to set the new administrator's password.
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Administrator invite link" });
    expect(within(panel).getByText(/jordan/)).toBeInTheDocument();
    const link = within(panel).getByRole("textbox", { name: "One-time link" }) as HTMLInputElement;
    expect(link.value).toContain("invite-token-123");
  });
});

describe("Suggested groups", () => {
  it("applies only the ticked sources of one suggestion and adds no people", async () => {
    const spy = await renderAt("/users");
    const panel = await screen.findByRole("region", { name: "Suggested groups" });
    await userEvent.click(within(panel).getByRole("checkbox", { name: "linux_sudo" }));
    await userEvent.click(within(panel).getByRole("button", { name: "Create Identity" }));
    await waitFor(() =>
      expect(
        spy.mock.calls.filter(([u]) => String(u).endsWith("/api/groups/suggestions/accept")),
      ).toHaveLength(1),
    );
    const [, init] =
      spy.mock.calls.find(([u]) => String(u).endsWith("/api/groups/suggestions/accept")) ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({
      kind: "category",
      key: "identity",
      source_ids: ["linux_sshd"],
    });
  });
});
