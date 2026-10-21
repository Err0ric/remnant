import { api } from "@/lib/api";

/** Plain messages for the fixed codes the sign-in callback returns (ADR-0013 row 12). */
export function ssoMessage(code: string, label: string): string {
  switch (code) {
    case "expired":
      return "That sign-in took too long or was already used. Try again.";
    case "denied":
      return `Sign-in with ${label} was cancelled or refused.`;
    case "unavailable":
      return `${label} sign-in cannot be reached right now. Try again shortly.`;
    case "not_invited":
      return `Your ${label} account does not have access here yet. Ask an administrator for an invite, then open the invite link.`;
    case "disabled":
      return "This account is disabled. Ask an administrator.";
    case "not_in_group":
      return `Your ${label} account is not in the group allowed to use this app. Ask an administrator.`;
    case "too_many_groups":
      return `Your ${label} account is in too many groups to check. An administrator can limit the groups sent at sign-in (see the setup guide).`;
    case "already_linked":
      return `That ${label} account already signs in to another account here.`;
    case "off":
      return "Single sign-on is not turned on for this server.";
    default:
      return "Sign-in did not complete. Try again, and ask an administrator if it keeps happening.";
  }
}

/** Read and clear the `?sso=` code the callback leaves on the sign-in page. */
export function takeSsoCode(): string | null {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("sso");
  if (code !== null) window.history.replaceState(null, "", "/");
  return code;
}

/** Full-page navigation away; an object so tests can watch it without a real redirect. */
export const leave = { to: (url: string) => window.location.assign(url) };

/** Leave for the identity provider. The browser comes back to the callback, then to `/`. */
export async function goToSso(linkToken?: string): Promise<void> {
  const { url } = await api.startSso(linkToken);
  leave.to(url);
}
