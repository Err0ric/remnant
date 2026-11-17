import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Select, type SelectOption } from "@/components/forms/Select";
import { choose } from "./choose";

const SEVERITY: SelectOption[] = [
  { value: "", label: "Any" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium", disabled: true },
  { value: "low", label: "Low" },
  { value: "info", label: "Info" },
];

interface HarnessProps {
  start?: string;
  options?: SelectOption[];
  onChange?: (v: string) => void;
  name?: string;
}

function Harness({ start = "", options = SEVERITY, onChange, name }: HarnessProps) {
  const [value, setValue] = useState(start);
  return (
    <form aria-label="Filters">
      <label>
        <span>Severity</span>
        <Select
          value={value}
          options={options}
          name={name}
          onChange={(v) => {
            setValue(v);
            onChange?.(v);
          }}
        />
      </label>
      <button type="button">Next</button>
    </form>
  );
}

const control = () => screen.getByRole("combobox", { name: "Severity" });
const active = () => {
  const id = control().getAttribute("aria-activedescendant");
  return id ? document.getElementById(id)?.textContent : null;
};

describe("Select (components/forms/Select.tsx)", () => {
  it("is a select-only combobox named by its label, showing the current value", () => {
    render(<Harness start="high" />);
    const c = control();
    expect(c).toHaveAttribute("aria-haspopup", "listbox");
    expect(c).toHaveAttribute("aria-expanded", "false");
    expect(c).toHaveValue("high");
    expect(c).toHaveTextContent("High");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("opens on a click with the current option marked, and closes on a choice", async () => {
    const onChange = vi.fn();
    render(<Harness start="high" onChange={onChange} />);
    await userEvent.click(control());
    const list = screen.getByRole("listbox", { name: "Severity" });
    expect(control()).toHaveAttribute("aria-expanded", "true");
    expect(control()).toHaveAttribute("aria-controls", list.id);
    expect(within(list).getByRole("option", { name: "High", selected: true })).toBeVisible();
    expect(within(list).getAllByRole("option", { selected: true })).toHaveLength(1);
    expect(active()).toBe("High");
    await userEvent.click(within(list).getByRole("option", { name: "Low" }));
    expect(onChange).toHaveBeenCalledWith("low");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(control()).toHaveFocus();
    expect(control()).toHaveValue("low");
  });

  it.each(["{ArrowDown}", "{ArrowUp}", "{Enter}", " "])("opens with %s", async (key) => {
    render(<Harness start="critical" />);
    control().focus();
    await userEvent.keyboard(key);
    expect(screen.getByRole("listbox")).toBeVisible();
    expect(active()).toBe("Critical");
  });

  it("moves with the arrows, Home, and End, skipping a disabled option", async () => {
    const onChange = vi.fn();
    render(<Harness start="high" onChange={onChange} />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toBe("Low"); // Medium is disabled
    await userEvent.keyboard("{ArrowUp}");
    expect(active()).toBe("High");
    await userEvent.keyboard("{End}");
    expect(active()).toBe("Info");
    await userEvent.keyboard("{ArrowDown}");
    expect(active()).toBe("Info"); // no wrap
    await userEvent.keyboard("{Home}");
    expect(active()).toBe("Any");
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("critical");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(control()).toHaveFocus();
  });

  it("selects with Space", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    await new Promise((r) => setTimeout(r, 650)); // past type-ahead, so Space selects
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith("critical");
  });

  it("draws a disabled option muted and never selects it; enabled ones, the placeholder too, are not", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(control());
    const off = screen.getByRole("option", { name: "Medium" });
    expect(off).toHaveAttribute("aria-disabled", "true");
    expect(off).toHaveClass("text-text-muted");
    for (const name of ["Any", "Critical", "Info"]) {
      const o = screen.getByRole("option", { name });
      expect(o).not.toHaveAttribute("aria-disabled");
      expect(o).toHaveClass("text-text");
    }
    await userEvent.click(off);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeVisible();
  });

  it("finds an option by the first letters typed, open or closed", async () => {
    render(<Harness />);
    control().focus();
    await userEvent.keyboard("l");
    expect(screen.getByRole("listbox")).toBeVisible();
    expect(active()).toBe("Low");
    await new Promise((r) => setTimeout(r, 650));
    await userEvent.keyboard("hi");
    expect(active()).toBe("High");
    await new Promise((r) => setTimeout(r, 650));
    await userEvent.keyboard("m"); // only Medium starts with m, and it is disabled
    expect(active()).toBe("High");
  });

  it("closes on Escape keeping the value, and the Escape goes no further", async () => {
    const onChange = vi.fn();
    const outer = vi.fn();
    window.addEventListener("keydown", outer);
    render(<Harness start="high" onChange={onChange} />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Escape}");
    window.removeEventListener("keydown", outer);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(control()).toHaveValue("high");
    expect(control()).toHaveFocus();
    expect(outer.mock.calls.filter(([e]) => (e as KeyboardEvent).key === "Escape")).toEqual([]);
  });

  it("closes on Tab and moves on to the next control", async () => {
    render(<Harness start="high" />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.tab();
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Next" })).toHaveFocus();
    expect(control()).toHaveValue("high");
  });

  it("closes on a click outside", async () => {
    render(<Harness />);
    await userEvent.click(control());
    await userEvent.click(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("lists grouped options under their heading", async () => {
    render(
      <Harness
        options={[
          { value: "auto", label: "Automatic" },
          { value: "t:a", label: "Alpha", group: "One template" },
          { value: "t:b", label: "Beta", group: "One template" },
          { value: "g:json", label: "JSON", group: "Generic" },
        ]}
        start="auto"
      />,
    );
    await userEvent.click(control());
    const group = screen.getByRole("group", { name: "One template" });
    expect(
      within(group)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Alpha", "Beta"]);
    expect(
      within(screen.getByRole("group", { name: "Generic" })).getByRole("option"),
    ).toHaveTextContent("JSON");
  });

  it("submits its value with a form through a hidden input", async () => {
    render(<Harness start="high" name="severity" />);
    const form = screen.getByRole("form", { name: "Filters" }) as HTMLFormElement;
    expect(new FormData(form).get("severity")).toBe("high");
    await choose(control(), "info");
    expect(new FormData(form).get("severity")).toBe("info");
  });

  it("never scrolls the page: the list is fixed from its first render, and nothing in it is scrolled into view", async () => {
    const into = vi.fn();
    Element.prototype.scrollIntoView = into;
    render(<Harness start="info" />);
    const before = window.scrollY;
    await userEvent.click(control());
    const list = screen.getByRole("listbox");
    expect(list.style.position).toBe("fixed");
    await userEvent.keyboard("{Home}{End}{ArrowUp}");
    expect(into).not.toHaveBeenCalled();
    expect(window.scrollY).toBe(before);
    delete (Element.prototype as Partial<Element>).scrollIntoView;
  });

  it("with a placeholder, shows it until a choice is made and lists only the real choices", async () => {
    const onChange = vi.fn();
    render(
      <Select
        aria-label="Add source filter"
        placeholder="Add source filter"
        look="facet"
        value=""
        options={[
          { value: "dns_bind", label: "dns_bind" },
          { value: "linux_sshd", label: "linux_sshd" },
        ]}
        onChange={onChange}
      />,
    );
    const c = screen.getByRole("combobox", { name: "Add source filter" });
    expect(c).toHaveTextContent("Add source filter");
    await userEvent.click(c);
    const rows = screen.getAllByRole("option");
    expect(rows.map((o) => o.textContent)).toEqual(["dns_bind", "linux_sshd"]);
    expect(screen.queryAllByRole("option", { selected: true })).toEqual([]);
    await userEvent.click(rows[1]!);
    expect(onChange).toHaveBeenCalledWith("linux_sshd");
  });

  it("has two looks: a field like the text inputs and a facet that reads Name Value", () => {
    render(
      <>
        <Select
          aria-label="Kind"
          value="a"
          options={[{ value: "a", label: "A" }]}
          onChange={vi.fn()}
        />
        <Select
          look="facet"
          aria-label="Severity"
          prefix="Severity"
          value="high"
          options={[{ value: "high", label: "High" }]}
          onChange={vi.fn()}
        />
      </>,
    );
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveClass(
      "bg-inset",
      "border-border-control",
    );
    const facet = screen.getByRole("combobox", { name: "Severity" });
    expect(facet).toHaveClass("border-border-strong");
    expect(facet).toHaveTextContent(/^Severity\s*High$/);
  });

  it("moves ten rows with PageDown and PageUp, stopping at the ends", async () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ value: `v${i}`, label: `Row ${i}` }));
    render(<Harness options={many} start="v0" />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}{PageDown}");
    expect(active()).toBe("Row 10");
    await userEvent.keyboard("{PageDown}{PageDown}");
    expect(active()).toBe("Row 24");
    await userEvent.keyboard("{PageUp}");
    expect(active()).toBe("Row 14");
    await userEvent.keyboard("{PageUp}{PageUp}");
    expect(active()).toBe("Row 0");
  });

  it("types a space inside a type-ahead and stays on the option the whole string matches", async () => {
    const onChange = vi.fn();
    const mute = [
      { value: "0", label: "No" },
      { value: "7", label: "For 7 days" },
      { value: "30", label: "For 30 days" },
    ];
    render(<Harness options={mute} start="7" onChange={onChange} />);
    control().focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("for ");
    expect(screen.getByRole("listbox")).toBeVisible(); // Space inside a type-ahead does not choose
    expect(active()).toBe("For 30 days");
    await userEvent.keyboard("3");
    expect(active()).toBe("For 30 days");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("is not toggled twice by the click a browser makes from Space or Enter (Firefox: on keyup)", () => {
    const onChange = vi.fn();
    render(<Harness start="high" onChange={onChange} />);
    const c = control();
    c.focus();
    // Closed: Space opens, and the click that follows its keyup leaves it open.
    fireEvent.keyDown(c, { key: " " });
    fireEvent.keyUp(c, { key: " " });
    fireEvent.click(c, { detail: 0 });
    expect(screen.getByRole("listbox")).toBeVisible();
    // Open: Enter chooses and closes, and a click from it does not reopen the list.
    fireEvent.keyDown(c, { key: "ArrowDown" });
    fireEvent.keyDown(c, { key: "Enter" });
    fireEvent.keyUp(c, { key: "Enter" });
    fireEvent.click(c, { detail: 0 });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).toHaveBeenCalledWith("low");
  });

  it("chooses with Space and stays closed after the click from its keyup", async () => {
    const onChange = vi.fn();
    render(<Harness start="high" onChange={onChange} />);
    const c = control();
    c.focus();
    fireEvent.keyDown(c, { key: "ArrowDown" });
    fireEvent.keyDown(c, { key: "ArrowDown" });
    await new Promise((r) => setTimeout(r, 650)); // past type-ahead, so Space selects
    fireEvent.keyDown(c, { key: " " });
    const up = fireEvent.keyUp(c, { key: " " });
    expect(up).toBe(false); // keyup's default (a click in Firefox) is cancelled
    fireEvent.click(c, { detail: 0 });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onChange).toHaveBeenCalledWith("low");
    // A later pointer click still opens it.
    await new Promise((r) => setTimeout(r, 0));
    await userEvent.click(c);
    expect(screen.getByRole("listbox")).toBeVisible();
  });

  it("with nothing to choose, is disabled and says why", async () => {
    render(
      <Select
        aria-label="Add source filter"
        placeholder="Add source filter"
        emptyReason="Every source is already added"
        value=""
        options={[]}
        onChange={vi.fn()}
      />,
    );
    const c = screen.getByRole("combobox", { name: "Add source filter" });
    expect(c).toBeDisabled();
    expect(c).toHaveAccessibleDescription("Every source is already added");
    await userEvent.click(c);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("does nothing while disabled", async () => {
    render(<Select aria-label="Role" value="a" disabled options={SEVERITY} onChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Role" }));
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  // Not testable in jsdom, which has no layout: the list is portalled to document.body with
  // fixed positioning from the button, so a card's overflow or a sticky pane cannot clip it;
  // checked in the before and after screenshots (scripts/screenshots/pages.py).
});

describe("No native select (owner, 2026-11-16)", () => {
  const sources = import.meta.glob("../src/**/*.tsx", {
    query: "?raw",
    import: "default",
    eager: true,
  });

  it("every dropdown is the themed Select: a native one is unreadable in the dark theme", () => {
    // A text box's suggestions (<datalist>) are typed over, not chosen from, so they stay.
    const native = Object.entries(sources)
      .filter(([, text]) => /<select\b|<optgroup\b/.test(String(text)))
      .map(([path]) => path.replace(/^.*\/src\//, ""));
    expect(native).toEqual([]);
  });
});
