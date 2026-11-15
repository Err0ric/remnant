import { render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChangePill } from "@/components/ChangePill";
import { EventIdChip } from "@/components/EventIdChip";
import { OutcomeBadge } from "@/features/audit/OutcomeBadge";
import { badgeKind, clipMiddle } from "@/features/investigate/LaneGraph";
import { SeverityBadge } from "@/components/SeverityBadge";
import { SeverityMark, severityTone } from "@/components/SeverityMark";
import { STATUS_LABEL, StatusBadge, StatusPicker } from "@/features/ai/StatusBadge";
import { LevelBadge } from "@/features/detect/LevelBadge";
import type { AiStatus } from "@/lib/api";

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const path = join(dir, e.name);
    if (e.isDirectory()) return sources(path);
    return /\.tsx?$/.test(e.name) ? [path] : [];
  });
}

describe("Severity marks (DESIGN.md sections 2 and 7, D248)", () => {
  it("shows Critical and High as solid badges with their label", () => {
    render(
      <>
        <SeverityBadge value={5} />
        <SeverityBadge value={4} />
      </>,
    );
    expect(screen.getByText("Critical")).toHaveClass("bg-sev-c-solid", "text-sev-c-on");
    expect(screen.getByText("High")).toHaveClass("bg-sev-h-solid", "text-sev-h-on");
  });

  it("shows Medium, Low, and Info as a dot and the label in the text color", () => {
    render(
      <>
        <SeverityBadge value={3} />
        <SeverityBadge value={2} />
        <SeverityBadge value={1} />
      </>,
    );
    for (const [label, dot] of [
      ["Medium", "bg-sev-m-dot"],
      ["Low", "bg-text-muted"],
      ["Info", "bg-text-muted"],
    ] as const) {
      const mark = screen.getByText(label);
      expect(mark).toHaveClass("text-text");
      expect(mark.className).not.toMatch(/bg-/);
      expect(mark.querySelector("[aria-hidden]")).toHaveClass(dot, "h-[7px]", "w-[7px]");
    }
  });

  it("keeps a Sigma level's own word and treats an unknown level as neutral", () => {
    render(
      <>
        <LevelBadge level="informational" />
        <LevelBadge level="high" />
      </>,
    );
    expect(screen.getByText("informational").dataset.severity).toBe("info");
    expect(screen.getByText("high").dataset.severity).toBe("high");
    expect(severityTone("Critical")).toBe("critical");
    expect(severityTone("something else")).toBe("info");
  });

  it("never renders a mark without its label", () => {
    const { container } = render(<SeverityMark tone="medium" label="Medium" />);
    expect(container.textContent).toBe("Medium");
  });

  it("keeps severity colors for severities: no tinted severity token is left", () => {
    const tinted = /sev-(critical|high|medium|low|info)-(bg|text)/;
    const found = [...sources("src"), "src/styles/tokens.css", "tailwind.config.ts"].filter((f) =>
      tinted.test(readFileSync(f, "utf8")),
    );
    expect(found).toEqual([]);
  });

  it("has no blue Low badge left in any component", () => {
    const found = sources("src").filter((f) => /sev-low-(bg|text)/.test(readFileSync(f, "utf8")));
    expect(found).toEqual([]);
  });
});

describe("AI status (DESIGN.md 7)", () => {
  it.each(Object.keys(STATUS_LABEL) as AiStatus[])("shows %s as a dot and its label", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(STATUS_LABEL[status]);
    expect(badge.querySelector("[aria-hidden]")).not.toBeNull();
    expect(badge.outerHTML).not.toMatch(/sev-|danger/);
  });

  it("outlines Unreviewed in the accent and Not approved in the warn color", () => {
    render(
      <>
        <StatusBadge status="approved" />
        <StatusBadge status="unreviewed" />
        <StatusBadge status="not_approved" />
      </>,
    );
    const dot = (label: string) => screen.getByText(label).querySelector("[aria-hidden]");
    expect(dot("Approved")).toHaveClass("bg-local-tx");
    expect(dot("Unreviewed")).toHaveClass("border-accent-text");
    expect(dot("Not approved")).toHaveClass("border-warn");
  });

  it("uses no severity token anywhere in the status badge or picker", () => {
    render(<StatusPicker label="Gemini" value="not_approved" onChange={() => undefined} />);
    const picker = screen.getByRole("combobox", { name: "Review status of Gemini" });
    expect(picker.className).not.toMatch(/sev-|danger/);
    expect(picker).toHaveClass("border-border-control");
    expect(readFileSync("src/features/ai/StatusBadge.tsx", "utf8")).not.toMatch(/sev-/);
  });

  it("colors Not approved without a severity token on the chart and the page header too", () => {
    const found = sources("src").filter((f) => {
      const text = readFileSync(f, "utf8");
      return /not_approved[^\n]*sev-/.test(text) || /sev-[^>]*>\s*\{notApproved\}/.test(text);
    });
    expect(found).toEqual([]);
    const chart = readFileSync("src/features/dashboard/AiWatch.tsx", "utf8");
    expect(chart).toMatch(/unreviewed: "accent-text",\s+not_approved: "warn"/);
  });
});

describe("Titles", () => {
  it("has no upper-case text style in any component", () => {
    const found = sources("src").filter((f) => /\buppercase\b/.test(readFileSync(f, "utf8")));
    expect(found).toEqual([]);
  });
});

describe("Table headers and control edges (DESIGN.md 4 and 7)", () => {
  const files = sources("src").map((f) => [f, readFileSync(f, "utf8")] as const);

  it("gives no header cell or header row its own weight or fill", () => {
    const found = files.filter(
      ([, text]) =>
        /<th\b[^>]*\bfont-(semibold|medium|bold|normal)\b[^>]*>(?![\s\S]{0,400}<\/tbody)/.test(
          text.replace(/<tbody[\s\S]*?<\/tbody>/g, ""),
        ) ||
        /const TH\w* =\s*"[^"]*\bfont-(semibold|medium|bold|normal)\b/.test(text) ||
        /<thead[^>]*>\s*<tr\b[^>]*\bbg-surface-head\b/.test(text),
    );
    expect(found.map(([f]) => f)).toEqual([]);
    const css = readFileSync("src/styles/globals.css", "utf8").replace(/\s+/g, " ");
    expect(css).toContain(
      "thead th { font-size: 12px; line-height: 16px; font-weight: 500; color: var(--text-secondary); }",
    );
  });

  it("draws every checkbox state and keeps the system's box in forced colors", () => {
    const css = readFileSync("src/styles/globals.css", "utf8").replace(/\s+/g, " ");
    for (const rule of [
      'input[type="checkbox"]:checked::before {',
      'input[type="checkbox"]:indeterminate::before {',
      'input[type="checkbox"]:disabled { opacity: 0.5; }',
      '@media (forced-colors: active) { input[type="checkbox"] { appearance: auto; } }',
    ]) {
      expect(css).toContain(rule);
    }
    // In the base layer, so a spacing class on a checkbox still wins over the reset margin.
    expect(css.indexOf("@layer base { /* Table headers")).toBeGreaterThan(-1);
  });

  it("edges text inputs, selects, and checkboxes in --border-control", () => {
    const found = files.filter(
      ([, text]) =>
        /<(input|select|textarea)\b[^<]*border-border-strong/.test(text) ||
        /border-border-strong bg-inset/.test(text),
    );
    expect(found.map(([f]) => f)).toEqual([]);
    const css = readFileSync("src/styles/globals.css", "utf8");
    expect(css).toMatch(
      /input\[type="checkbox"\] \{[^}]*border: 1px solid var\(--border-control\)/,
    );
  });
});

describe("Change pill and cited ID chip (DESIGN.md 7)", () => {
  it("shows the change as a neutral pill: an arrow and the amount, or same", () => {
    render(
      <>
        <ChangePill change={53} spoken="+53 vs previous 7 days" />
        <ChangePill change={-2} spoken="-2 vs previous 7 days" />
        <ChangePill change={0} spoken="same as previous 7 days" />
      </>,
    );
    for (const text of ["↑ 53", "↓ 2", "same"]) {
      const pill = screen.getByText(text).parentElement as HTMLElement;
      expect(pill.dataset.change).toBe("");
      expect(pill.className).not.toMatch(/ok|danger|warn|sev-|accent/);
    }
    expect(screen.getByText("same as previous 7 days")).toHaveClass("sr-only");
  });

  it("is a button only when it opens something", async () => {
    const open = vi.fn();
    render(<ChangePill change={1} spoken="+1; open it in Logs" onOpen={open} />);
    await userEvent.click(screen.getByRole("button", { name: "+1; open it in Logs" }));
    expect(open).toHaveBeenCalledOnce();
  });

  it("shows a cited id on the Info pair, the selected one on the pressed fill", async () => {
    const select = vi.fn();
    render(
      <>
        <EventIdChip id="id-plain" label="aaaa1111" />
        <EventIdChip id="id-chosen" label="bbbb2222" selected onSelect={select} />
        <EventIdChip id="id-bad" label="cccc3333" verified={false} />
      </>,
    );
    expect(screen.getByText("aaaa1111")).toHaveClass("bg-info-bg", "text-info-tx", "font-mono");
    const chosen = screen.getByRole("button", { name: "bbbb2222" });
    expect(chosen).toHaveClass("bg-accent-subtle", "border-accent-text");
    expect(chosen).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chosen);
    expect(select).toHaveBeenCalledWith("id-chosen");
    const bad = screen.getByText("cccc3333");
    expect(bad).toHaveClass("border-danger", "text-danger");
    expect(bad.className).not.toMatch(/sev-|bg-/);
  });
});

describe("State tags (DESIGN.md 2 and 7)", () => {
  it("keeps the solid pair for a real severity on investigation cards", () => {
    expect(badgeKind("High severity")).toBe("severity");
    expect(badgeKind("3 rule matches")).toBe("neutral");
    expect(badgeKind("Not approved")).toBe("state");
    expect(badgeKind("Sensitive data")).toBe("state");
    expect(badgeKind("New")).toBe("neutral");
  });

  it("tags a new agent with a neutral outline, not the accent", () => {
    const card = readFileSync("src/features/ai/AgentsCard.tsx", "utf8");
    const tag = /new: \{ label: "New agent", tint: "([^"]*)" \}/.exec(card)?.[1] ?? "";
    expect(tag).toBe("border border-border-strong text-text-secondary");
    expect(card).not.toMatch(/tint: "[^"]*accent/);
  });

  it("outlines a failure and a gate block in danger, a denial in warn, and fills neither", () => {
    render(
      <>
        <OutcomeBadge outcome="failure" />
        <OutcomeBadge outcome="blocked" />
        <OutcomeBadge outcome="denied" />
        <OutcomeBadge outcome="success" />
      </>,
    );
    for (const outcome of ["failure", "blocked"]) {
      expect(screen.getByText(outcome)).toHaveClass("border-danger", "text-danger");
    }
    expect(screen.getByText("denied")).toHaveClass("border-warn", "text-warn");
    for (const outcome of ["failure", "blocked", "denied"]) {
      expect(screen.getByText(outcome).className).not.toMatch(/\bbg-/);
    }
    expect(screen.getByText("success")).toHaveClass("bg-info-bg");
  });
});

describe("Lane box labels (D257)", () => {
  it("cut a long name in the middle, keeping its last 8 characters", () => {
    expect(clipMiddle("Office 365 SharePoint Online", 20)).toBe("Office 365 …t Online");
    expect(clipMiddle("Office 365 SharePoint Online", 20)).toHaveLength(20);
    expect(clipMiddle("claude", 20)).toBe("claude");
    expect(clipMiddle("m365_management_activity", 6)).toMatch(/^m…/);
  });
});
