// Dates on screen are in the viewer's time zone; tests read them as a viewer in UTC.
process.env.TZ = "UTC";

import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Pages are lazy-loaded (App.tsx); the first import of a page module in a test can take
// longer than the 1 s default while Vite transforms it.
configure({ asyncUtilTimeout: 5000 });

// A tall desktop window: the rail's short-window rules (D268, read from the window height)
// then show Recent and Pinned in full under any page's tabs.
window.innerHeight = 1000;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  try {
    window.localStorage.clear();
  } catch {
    // no storage in this environment
  }
});
