/** One-time invite or reset link. The token travels in the fragment, never to a server log. */
export function accountLink(token: string): string {
  return `${window.location.origin}/account#${token}`;
}
