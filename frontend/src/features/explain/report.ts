import type { ExplainResponse } from "@/lib/api";

/**
 * A Markdown report draft from an explanation: every claim with its event id references,
 * unverified claims marked, and the events that were sent. Built in the browser from the
 * answer already shown; nothing is sent anywhere.
 */
export function reportMarkdown(r: ExplainResponse, title: string, at: Date = new Date()): string {
  const lines = [
    `# ${title}`,
    "",
    `Drafted ${at.toISOString().slice(0, 16).replace("T", " ")} UTC by ${r.provider.name} (${r.provider.model}, ${r.provider.locality}). AI-written: check each claim against the events it cites.`,
    "",
    `Citation check: ${r.citation_check === "pass" ? "every claim cites only events that were sent" : "some claims are unverified"}.`,
    "",
    "## Findings",
    "",
  ];
  r.claims.forEach((c, i) => {
    const refs = c.event_ids.length ? c.event_ids.map((id) => `\`${id}\``).join(", ") : "none";
    lines.push(`${i + 1}. ${c.verified ? "" : "**Unverified.** "}${c.text.replace(/\s+/g, " ")}`);
    lines.push(`   Events: ${refs}`);
  });
  lines.push("", "## Events sent", "");
  for (const id of r.events_sent) lines.push(`- \`${id}\``);
  lines.push("", `Sources: ${r.sources.join(", ")}. Model call: \`${r.call_id}\`.`, "");
  return lines.join("\n");
}
