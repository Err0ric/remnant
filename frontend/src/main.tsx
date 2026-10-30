import "@fontsource/source-sans-3/400.css";
import "@fontsource/source-sans-3/600.css";
import "@fontsource/source-sans-3/700.css";
import "@fontsource/source-code-pro/400.css";
import "@fontsource/source-code-pro/500.css";
import "./styles/globals.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { loadBranding } from "./lib/branding";
import { applyTheme, initialTheme } from "./lib/theme";
import { applyDensity, defaultDensity } from "./lib/density";

const theme = initialTheme();
applyTheme(theme);
// The signed-in user's own choice replaces this once the user menu loads.
applyDensity("", defaultDensity());

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

void loadBranding().then(() => {
  createRoot(root).render(
    <StrictMode>
      <App initialTheme={theme} />
    </StrictMode>,
  );
});
