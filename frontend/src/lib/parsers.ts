import type { SourceFormat, TemplateInfo } from "@/lib/api";

/** Reserved parser id: pick a template per line (ADR-0012). Mirrors app.core.ids.AUTO_PARSER. */
export const AUTO_PARSER = "auto";

export const FORMAT_LABELS: Record<SourceFormat, string> = {
  syslog: "Syslog (RFC 3164 / 5424, or plain lines)",
  json: "JSON lines (one object per line)",
  csv: "CSV with a header row",
};

/** Short name of a source's parser for tables and summaries. */
export function parserLabel(
  templateId: string | null | undefined,
  format: SourceFormat,
  templates: TemplateInfo[] = [],
): string {
  if (!templateId) return `Generic ${format}`;
  if (templateId === AUTO_PARSER) return "Automatic";
  return templates.find((t) => t.id === templateId)?.name ?? templateId;
}

/** One line of help under the parser choice. */
export function parserHelp(
  templateId: string | null | undefined,
  templates: TemplateInfo[] = [],
): string {
  if (templateId === AUTO_PARSER)
    return "Each line is matched to the template that fits it (sshd, sudo, firewall, and so on). Lines no template fits keep time, host, and message. Best for mixed streams such as a syslog file or a Loki query.";
  if (templateId) return templates.find((t) => t.id === templateId)?.description ?? "";
  return "Generic parsing keeps time, host, and message, and every other field in unmapped.";
}

/** Short name of the parser in effect, for summaries. */
export function parserName(
  templateId: string | null | undefined,
  format: string,
  templates: TemplateInfo[] = [],
): string {
  if (templateId === AUTO_PARSER) return "Automatic";
  if (templateId) return templates.find((t) => t.id === templateId)?.name ?? templateId;
  return `Generic ${format}`;
}
