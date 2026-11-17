import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/** Opens a themed select (components/forms/Select.tsx) and returns its list. */
export async function openList(control: HTMLElement): Promise<HTMLElement> {
  if (control.getAttribute("aria-expanded") !== "true") await userEvent.click(control);
  const id = control.getAttribute("aria-controls");
  const list = id ? document.getElementById(id) : null;
  if (!list) throw new Error(`the control ${control.getAttribute("aria-label") ?? ""} has no list`);
  return list;
}

/** Chooses `option` in a themed select, by its value or its label, as a person would: open
 * the control, click the option. The list closes after. */
export async function choose(control: HTMLElement, option: string | RegExp): Promise<void> {
  const list = await openList(control);
  const rows = within(list).getAllByRole("option");
  const hit =
    typeof option === "string"
      ? (rows.find((o) => o.getAttribute("data-value") === option) ??
        rows.find((o) => o.textContent === option))
      : rows.find((o) => option.test(o.textContent ?? ""));
  if (!hit) {
    const all = rows.map((o) => `${o.getAttribute("data-value")} (${o.textContent})`);
    throw new Error(`no option ${String(option)}; the list has ${all.join(", ")}`);
  }
  await userEvent.click(hit);
}

/** The labels a themed select offers, in order, read without opening it. */
export function optionLabels(control: HTMLElement): string[] {
  return Array.from(control.querySelectorAll("[data-select-sizer]")).map(
    (s) => s.getAttribute("data-select-sizer") ?? "",
  );
}
