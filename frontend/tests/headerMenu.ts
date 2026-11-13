import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/** Opens the page header's "More actions" menu and returns the item with this name. */
export async function fromMore(name: string | RegExp): Promise<HTMLElement> {
  await userEvent.click(await screen.findByRole("button", { name: "More actions" }));
  return screen.getByRole("menuitem", { name });
}
