import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, type EmptyKind } from "@/components/EmptyState";
import { InlineError } from "@/components/InlineError";
import { Skeleton } from "@/components/Skeleton";

// Every source file of the app, as text.
const sources = import.meta.glob("../src/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("Spinners (DESIGN.md 6.0)", () => {
  it("are only inside buttons: the one spinning icon is the Refresh button's", () => {
    const spinning = Object.entries(sources)
      .filter(([, text]) => /animate-spin/.test(String(text)))
      .map(([path]) => path.split("/").pop());
    expect(spinning).toEqual(["Freshness.tsx"]);
  });
});

/** How often `pattern` is in each source file that has it, by file name. */
function uses(pattern: RegExp): Record<string, number> {
  return Object.fromEntries(
    Object.entries(sources)
      .map(([path, text]) => [path.split("/").pop(), String(text).match(pattern)?.length ?? 0])
      .filter(([, n]) => n !== 0),
  );
}

describe("Loading placeholders and empty lists (DESIGN.md 6.0, redesign build row 15)", () => {
  it("are the Skeleton component, apart from three that already draw their final layout", () => {
    // The entity summary draws its own title and its tiles; People & devices has a thin
    // progress line under a table that is already on screen.
    expect(uses(/animate-pulse/g)).toEqual({
      "EntitySummary.tsx": 2,
      "InvestigatePage.tsx": 1,
      "Skeleton.tsx": 8,
    });
  });

  it("never say only Loading, except on the button that loads older audit entries", () => {
    expect(uses(/Loading…/g)).toEqual({ "AuditLogPage.tsx": 1 });
  });

  it("are not centered: an empty list reads from the top left", () => {
    // A dashed drop area in Edit layout, the Load older entries row, and the palette.
    expect(uses(/text-center/g)).toEqual({
      "AuditLogPage.tsx": 1,
      "CommandPalette.tsx": 1,
      "DashboardPage.tsx": 1,
    });
  });
});

describe("Help text (ADR-0052 section 3.7, redesign build rows 15 and 16)", () => {
  /** Text of two or more sentences in a paragraph, span, or div of the swept areas' page
   * files, as "<file>: <its first words>". */
  function longText(): string[] {
    const areas =
      /\/features\/(alerts|dashboard|search|ask|investigate|saved|detect|schedules|m365|ai|health)\//;
    const found: string[] = [];
    for (const [path, text] of Object.entries(sources).sort(([a], [b]) => a.localeCompare(b))) {
      if (!areas.test(path)) continue;
      for (const m of String(text).matchAll(/<(?:p|span|div)\b[^>]*>\s*([^<{]+)/g)) {
        const run = (m[1] ?? "").split(/\s+/).join(" ").trim();
        if ((`${run} A`.match(/[.!?](?=\s+[A-Z])/g) ?? []).length >= 2)
          found.push(`${path.replace(/^.*\/features\//, "")}: ${run.slice(0, 40)}`);
      }
    }
    return found;
  }

  it("has no text that explains a page: what is left is a state, a notice, or field help", () => {
    // Each line was looked at in the sweep (docs/proposals/help-text-sweep-2026-11.md): an
    // empty state, a state notice, a confirmation, a line about access or where data goes
    // (the owner keeps those visible), or help under a form field. New text of two sentences
    // on these pages fails here, by its words: make it a popover on its label, a button, or
    // one line. (Text after a `{...}` expression is not seen by this check.)
    expect(longText().sort()).toEqual(
      [
        "ai/AiSettings.tsx: A server name, or a prefix ending in * (", // Settings: field help
        "ai/AiSettings.tsx: Alerts the first time an AI service or M", // Settings: what it does
        "ai/AiSettings.tsx: Every service the network view recognize", // Settings: what it lists
        "ai/AiSettings.tsx: No alert targets yet; add one under Aler", // state
        "ai/AiUsagePage.tsx: Vendor ad and measurement tags that othe", // why not counted
        "alerts/AlertsPage.tsx: Not reviewed yet. Closing an alert does ", // who reviews
        "ask/AskThread.tsx: No AI provider is set up. Logs works wit", // not set up
        "dashboard/DashboardPage.tsx: Delete this dashboard? Its schedules kee", // confirmation
        "investigate/InvestigatePage.tsx: Names are hidden. An admin can turn on V", // masking notice
        "investigate/InvestigatePage.tsx: No users, IP addresses, or hosts in this", // empty state
        "schedules/ScheduleForm.tsx: Runs as you, with your access checked ev", // access
        "search/FacetSidebar.tsx: No countable fields in this result. Face", // empty state
        "search/HandoffPanel.tsx: Webhooks get each event with its raw lin", // where data goes
        "search/SearchPage.tsx: Your edits are not saved or run. Start a", // confirmation
      ].sort(),
    );
  });

  it("keeps each note that left the page on an (i) beside the label it is about", () => {
    const text = (file: string) =>
      String(Object.entries(sources).find(([path]) => path.endsWith(`/${file}`))?.[1] ?? "");
    // The note, in the file that draws its label, inside an About.
    for (const [file, note] of [
      [
        "SavedSearchesPage.tsx",
        "Other people's schedules of it pause until they review and resume.",
      ],
      ["SavedSearchesPage.tsx", "Editing it clears the mark."],
      ["RiskTable.tsx", "10 per critical, 5 per high, 2 per medium, 1 per low rule match"],
      ["RulesTable.tsx", "A rule runs only on sources whose template declares its log source."],
      ["AdminChanges.tsx", "Routine updates are changes to a user's or group's details."],
      ["MailRules.tsx", "forward it outside the person's domain"],
      ["AccountsCard.tsx", "A company email is confirmed by an Entra sign-in to Claude"],
      ["SpeedTable.tsx", "Time reading data."],
      ["SpeedTable.tsx", "Time queued for a query slot."],
    ] as const)
      expect(text(file), `${file}: ${note}`).toContain(note);
    for (const file of [
      "SavedSearchesPage.tsx",
      "RiskTable.tsx",
      "RulesTable.tsx",
      "AdminChanges.tsx",
      "MailRules.tsx",
      "AccountsCard.tsx",
      "SpeedTable.tsx",
    ])
      expect(text(file), file).toMatch(/<About\b/);
  });

  it("lets the (i) be read by keyboard and touch, and adds no text to its row", async () => {
    const { About } = await import("@/components/About");
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th aria-label="Score">
              Score <About text="10 per critical." />
            </th>
          </tr>
        </thead>
      </table>,
    );
    const mark = screen.getByRole("img", { name: "How this is counted: 10 per critical." });
    // A tab stop: focus shows the note (drawn from the attribute by the stylesheet).
    expect(mark).toHaveAttribute("tabindex", "0");
    expect(mark).toHaveAttribute("data-note", "How this is counted: 10 per critical.");
    expect(mark.className).toMatch(/focus:after:block/);
    expect(mark.className).toMatch(/hover:after:block/);
    await userEvent.tab();
    expect(mark).toHaveFocus();
    // The header keeps its plain name, and the row gains only the letter.
    expect(screen.getByRole("columnheader", { name: "Score" })).toBeInTheDocument();
    expect(container.textContent?.replace(/\s+/g, " ").trim()).toBe("Score i");
  });

  it("keeps the lines about access and where data goes on the page", () => {
    const all = Object.values(sources).map(String).join("\n");
    for (const line of [
      "Saved searches run with your own source access",
      "Only sources you may read are counted.",
      "Alerts carry a summary and a link back, never log content.",
      "Shared searches run with each person&apos;s own source access, never yours.",
      "Runs as you, with your access checked every run.",
      "Events from local-only sources go only to targets on your own network",
      "Nothing connects to the device.",
    ])
      expect(all, line).toContain(line);
  });
});

describe("State components (DESIGN.md 6.0, redesign build row 14)", () => {
  it("holds the place of rows while loading, with no spinner", () => {
    const { container } = render(<Skeleton label="alerts" rows={4} />);
    const box = screen.getByRole("status", { name: "Loading alerts" });
    expect(box).toHaveAttribute("aria-busy", "true");
    expect(box.children).toHaveLength(4);
    for (const row of Array.from(box.children)) expect(row.className).toContain("h-[var(--row-h)]");
    expect(container.querySelector(".animate-spin")).toBeNull();
  });

  it("can hold the place of one block", () => {
    render(<Skeleton label="AI Watch" block="h-48" />);
    const box = screen.getByRole("status", { name: "Loading AI Watch" });
    expect(box.children).toHaveLength(1);
    expect(box.firstElementChild?.className).toContain("h-48");
  });

  it("says an error in place, with Retry", async () => {
    const retry = vi.fn();
    render(<InlineError what="Alerts" error={new Error("x")} onRetry={retry} retrying={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/^Alerts did not load: /);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it.each<[EmptyKind, boolean]>([
    ["not-set-up", true],
    ["filtered", true],
    ["good-zero", false],
    ["default-empty", false],
    ["restricted", false],
  ])(
    "empty state %s: left-aligned, two lines at most, an action only where one helps",
    (kind, acts) => {
      const { container } = render(
        <EmptyState
          kind={kind}
          title="First line."
          detail="Second line."
          action={{ label: "Do it", onClick: () => undefined }}
        />,
      );
      const box = container.querySelector(`[data-empty="${kind}"]`) as HTMLElement;
      expect(box.querySelectorAll("p")).toHaveLength(2);
      expect(box.className).toContain("items-start");
      expect(box.className).not.toContain("text-center");
      expect(box.querySelector("img, svg")).toBeNull();
      expect(screen.queryAllByRole("button", { name: "Do it" })).toHaveLength(acts ? 1 : 0);
      // A good zero is said in normal text.
      const first = box.querySelector("p") as HTMLElement;
      expect(first.className).toBe(
        kind === "good-zero"
          ? "text-text"
          : kind === "default-empty"
            ? "text-text-secondary"
            : "text-md text-text",
      );
    },
  );
});
