import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/** Opens the page header's "More actions" menu, unless it is open already, and returns the
 * item with this name. Safe to retry inside a wait: a second call never closes the menu. */
export async function fromMore(name: string | RegExp): Promise<HTMLElement> {
  const more = await screen.findByRole("button", { name: "More actions" });
  if (more.getAttribute("aria-expanded") !== "true") await userEvent.click(more);
  return screen.getByRole("menuitem", { name });
}
