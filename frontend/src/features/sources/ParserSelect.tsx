import type { SourceFormat, TemplateInfo } from "@/lib/api";
import { AUTO_PARSER, FORMAT_LABELS } from "@/lib/parsers";
import { Select } from "@/components/forms/Select";

const TEMPLATES = "One template (fields mapped to OCSF)";
const GENERIC = "Generic (time, host, and message)";

interface ParserSelectProps {
  id: string;
  templateId: string | null | undefined;
  format: SourceFormat;
  templates: TemplateInfo[];
  /** Adding a source can pick any generic format; an existing source keeps its own. */
  formats: SourceFormat[];
  onChange: (templateId: string | null, format: SourceFormat) => void;
  label?: string;
}

/** Automatic, one template, or the generic parser for a format (ADR-0012). */
export function ParserSelect({
  id,
  templateId,
  format,
  templates,
  formats,
  onChange,
  label,
}: ParserSelectProps) {
  const value =
    templateId === AUTO_PARSER
      ? "auto:"
      : templateId
        ? `template:${templateId}`
        : `generic:${format}`;
  return (
    <Select
      id={id}
      aria-label={label}
      value={value}
      onChange={(v) => {
        const [kind, rest] = v.split(":") as [string, string];
        if (kind === "auto") {
          onChange(AUTO_PARSER, format === "csv" ? "syslog" : format);
        } else if (kind === "template") {
          const t = templates.find((x) => x.id === rest);
          onChange(rest, t?.envelope === "syslog" ? "syslog" : format === "csv" ? "json" : format);
        } else {
          onChange(null, rest as SourceFormat);
        }
      }}
      options={[
        ...(format !== "csv" || formats.length > 1
          ? [{ value: "auto:", label: "Automatic: pick a template per line" }]
          : []),
        ...templates.map((t) => ({ value: `template:${t.id}`, label: t.name, group: TEMPLATES })),
        ...formats.map((f) => ({ value: `generic:${f}`, label: FORMAT_LABELS[f], group: GENERIC })),
      ]}
      className="h-9 text-sm"
    />
  );
}
