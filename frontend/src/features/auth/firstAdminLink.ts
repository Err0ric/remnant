/**
 * The first administrator's one-time link, kept in this tab's memory only.
 *
 * On an install with no accounts, creating the first account ends open mode on the server
 * (ADR-0004), so the next request is refused and the app moves to sign-in before the Users
 * page can show the link. Without it nobody could set a password. It is never written to
 * storage and is gone on reload; the same tab already had full access in open mode.
 */
export interface FirstAdminLink {
  username: string;
  link: string;
}

let pending: FirstAdminLink | null = null;

export function rememberFirstAdminLink(value: FirstAdminLink): void {
  pending = value;
}

export function firstAdminLink(): FirstAdminLink | null {
  return pending;
}

export function forgetFirstAdminLink(): void {
  pending = null;
}
