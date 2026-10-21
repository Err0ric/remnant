import { api } from "./api";

// The product name is a working codename owned by the backend
// (app.core.branding.PRODUCT_NAME) and served by GET /api/meta.
// Read it from here only. Never hardcode the name in JSX, <title>, or copy.
const FALLBACK_NAME = "Console";

export let PRODUCT_NAME = FALLBACK_NAME;
/** Optional label an administrator sets (server.environment_label), shown in the top bar. */
export let ENVIRONMENT_LABEL: string | null = null;

export async function loadBranding(): Promise<string> {
  try {
    const meta = await api.meta();
    if (meta.product_name) PRODUCT_NAME = meta.product_name;
    ENVIRONMENT_LABEL = meta.environment_label ?? null;
  } catch {
    PRODUCT_NAME = FALLBACK_NAME;
  }
  document.title = PRODUCT_NAME;
  return PRODUCT_NAME;
}
