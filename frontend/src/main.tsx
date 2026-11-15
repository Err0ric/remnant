import "@fontsource/geist/latin-400.css";
import "@fontsource/geist/latin-500.css";
import "@fontsource/geist/latin-600.css";
import "@fontsource/geist/latin-700.css";
import "@fontsource/geist-mono/latin-400.css";
import "@fontsource/geist-mono/latin-500.css";
import "./styles/globals.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { PageBoundary } from "./components/ErrorBoundary";
import { errorId, reportClientError } from "./lib/clientErrors";
import { isChunkError, reloadOnce } from "./lib/chunkReload";
import { loadBranding } from "./lib/branding";
import { applyTheme, initialTheme } from "./lib/theme";
import { applyDensity, DEFAULT_DENSITY } from "./lib/density";
import { installCopyWhole } from "./lib/copyWhole";

const theme = initialTheme();
applyTheme(theme);
// The signed-in user's own choice replaces this once the user menu loads.
applyDensity("", DEFAULT_DENSITY);
// A cut name or email copies on one line, whatever the selection (D257).
installCopyWhole();

// Errors outside React's rendering (event handlers, timers, a failed chunk preload) still
// reach the server, and a missing chunk after an update reloads once.
window.addEventListener("error", (e) =>
  reportClientError("unhandled", e.error ?? e.message, errorId()),
);
window.addEventListener("unhandledrejection", (e) => {
  if (isChunkError(e.reason)) reloadOnce();
  reportClientError(isChunkError(e.reason) ? "chunk" : "unhandled", e.reason, errorId());
});
window.addEventListener("vite:preloadError", (e) => {
  if (reloadOnce()) e.preventDefault();
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

void loadBranding().then(() => {
  createRoot(root).render(
    <StrictMode>
      <PageBoundary>
        <App initialTheme={theme} />
      </PageBoundary>
    </StrictMode>,
  );
});
