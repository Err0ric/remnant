import { useQuery } from "@tanstack/react-query";
import { api, type SignInClasses } from "@/lib/api";

const FALLBACK =
  "Real failures only (wrong password, locked, MFA denied, expired password, disabled account, user not found, blocked by Conditional Access). Interrupted, expired, and other sign-ins are counted apart, never dropped.";

/** "How this is counted" for Failed sign-ins, from the classes in force (D158). */
export function signInAbout(c: SignInClasses | undefined): string {
  if (!c) return FALLBACK;
  const of = (cls: string) => c.codes.filter((x) => x.cls === cls);
  const failed = of("failed")
    .map((x) => `${x.label.toLowerCase()} (${x.code})`)
    .join(", ");
  const codes = (cls: string) =>
    of(cls)
      .map((x) => x.code)
      .join(", ");
  const parts = [
    `Counts real failures only, by Entra error code: ${failed}.`,
    `${c.blocked_code} is also shown on its own as Blocked by policy.`,
    `Not counted, shown apart and filterable on Microsoft 365 > Sign-ins: interrupted (the person was asked for MFA, to stay signed in, or to consent, and went on: ${codes(
      "interrupted",
    )}), expired (background session and token refreshes: ${codes(
      "expired",
    )}), and other (any code in no class).`,
  ];
  if (c.adjusted.length) {
    const moved = c.adjusted
      .map((x) => `${x.code} counted as ${x.cls}${x.shipped ? ` (shipped: ${x.shipped})` : ""}`)
      .join("; ");
    parts.push(`Classification: adjusted on this install: ${moved}.`);
  } else {
    parts.push("Classification: the shipped default.");
  }
  return parts.join(" ");
}

export function useSignInAbout(): string {
  const q = useQuery({
    queryKey: ["m365-signin-classes"],
    queryFn: api.m365SignInClasses,
    staleTime: 5 * 60_000,
  });
  return signInAbout(q.data);
}

/** The Failed sign-ins card's line for what it leaves out: "+ 12 interrupted or expired
 * (not counted)", with codes in no class named apart ("+ 12 interrupted or expired, 2
 * other (not counted)"). `extra` is all of them; `other` is the part in no class. */
export function notCountedText(extra: number, other = 0): string {
  const ie = Math.max(0, extra - other);
  const parts = [
    ...(ie ? [`${ie.toLocaleString()} interrupted or expired`] : []),
    ...(other ? [`${other.toLocaleString()} other`] : []),
  ];
  return `+ ${parts.join(", ")} (not counted)`;
}

/** The `extra` prop for a Failed sign-ins Kpi, or nothing when none were left out. */
export function notCountedExtra(extra: number | null | undefined, other = 0) {
  return extra
    ? {
        text: notCountedText(extra, other),
        label: "Sign-ins interrupted, expired, or other (not counted)",
        noun: "sign-ins not counted",
      }
    : undefined;
}
