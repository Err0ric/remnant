import { useEffect } from "react";
import { redirect } from "@/lib/route";

/** The root address: always the Dashboard for a signed-in viewer, never Health (owner,
 * 2026-11-12; replaces ADR-0031's "Health without a panel"). Health problems show as a
 * banner on the Dashboard instead. */
export function HomeRedirect() {
  useEffect(() => redirect("dashboard"), []);
  return <div aria-busy="true" className="flex-1" />;
}

/** `/overview` and unknown addresses (ADR-0034 row 11): the former Overview is Health. */
export function ToHealth() {
  useEffect(() => redirect("health", "sources"), []);
  return <div aria-busy="true" className="flex-1" />;
}

/** Ask AI opened by someone who may not ask a model (an auditor): Logs instead (D206). */
export function ToLogs() {
  useEffect(() => redirect("logs"), []);
  return <div aria-busy="true" className="flex-1" />;
}
