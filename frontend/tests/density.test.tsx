import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UserMenu } from "@/components/shell/UserMenu";
import type { User } from "@/lib/api";
import { currentDensity, DEFAULT_DENSITY } from "@/lib/density";

function user(role: string, username = "alice"): User {
  return { username, role } as User;
}

function narrowScreen() {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false,
    media: q,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-density");
});

describe("Density (ADR-0052 section 3.10, D248)", () => {
  it.each(["admin", "analyst", "auditor"])(
    "gives a new %s Comfortable at any screen width",
    (role) => {
      narrowScreen();
      expect(DEFAULT_DENSITY).toBe("comfortable");
      expect(currentDensity("alice")).toBe("comfortable");
      render(<UserMenu user={user(role)} onSignOut={() => undefined} />);
      expect(document.documentElement.dataset.density).toBe("comfortable");
    },
  );

  it("keeps a Compact choice after a reload, for that user only", async () => {
    const first = render(<UserMenu user={user("analyst")} onSignOut={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /alice/ }));
    await userEvent.click(screen.getByRole("button", { name: /Compact/ }));
    expect(document.documentElement.dataset.density).toBe("compact");

    // A reload: the page starts Comfortable, then the user menu applies the stored choice.
    first.unmount();
    document.documentElement.dataset.density = DEFAULT_DENSITY;
    render(<UserMenu user={user("analyst")} onSignOut={() => undefined} />);
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(currentDensity("bob")).toBe("comfortable");
  });
});

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return sources(path);
    return /\.(ts|tsx|css|html)$/.test(e.name) ? [path] : [];
  });
}

describe("Tokens and fonts (redesign build row 1)", () => {
  const files = [...sources("src"), "index.html", "tailwind.config.ts"];

  it("has no hex color in a component: colors come from tokens.css", () => {
    const hex = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/;
    const found = files
      .filter((f) => f.startsWith("src") && !f.endsWith("tokens.css"))
      .filter((f) => hex.test(readFileSync(f, "utf8").replace(/&#\d+;|#root\b/g, "")));
    expect(found).toEqual([]);
  });

  it("asks for no Source font", () => {
    const found = files.filter((f) =>
      /source[- ]sans|source[- ]code[- ]pro/i.test(readFileSync(f, "utf8")),
    );
    expect(found).toEqual([]);
    expect(readFileSync("package.json", "utf8")).not.toMatch(/fontsource\/source/);
  });
});

describe("Focus ring and muted text (owner, 2026-11-12)", () => {
  it("uses the top bar's own focus ring inside it, and the page's ring in its menu", async () => {
    const { TopBar } = await import("@/components/shell/TopBar");
    vi.stubGlobal("fetch", () => Promise.reject(new Error("no server in this test")));
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <TopBar
          theme="light"
          onToggleTheme={() => undefined}
          user={user("admin")}
          onSignOut={() => undefined}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("banner")).toHaveClass("[--focus-ring:var(--focus-ring-top)]");
    await userEvent.click(screen.getByRole("button", { name: /alice/ }));
    const panel = screen.getByRole("group", { name: "Density" }).parentElement;
    expect(panel).toHaveClass("[--focus-ring:var(--accent-text)]", "bg-surface");
  });

  it("turns muted text into secondary text on the pressed fill", () => {
    const css = readFileSync("src/styles/globals.css", "utf8").replace(/\s+/g, " ");
    expect(css).toContain(".bg-accent-subtle { --text-muted: var(--text-secondary); }");
  });
});
