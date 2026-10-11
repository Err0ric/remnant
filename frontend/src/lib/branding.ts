import { api } from "./api";

// The product name is a working codename owned by the backend
// (app.core.branding.PRODUCT_NAME) and served by GET /api/meta.
// Read it from here only. Never hardcode the name in JSX, <title>, or copy.
const FALLBACK_NAME = "Console";

export let PRODUCT_NAME = FALLBACK_NAME;

export async function loadBranding(): Promise<string> {
  try {
    const meta = await api.meta();
    if (meta.product_name) PRODUCT_NAME = meta.product_name;
  } catch {
    PRODUCT_NAME = FALLBACK_NAME;
  }
  document.title = PRODUCT_NAME;
  return PRODUCT_NAME;
}
