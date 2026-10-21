import type { SourceFormat, TemplateInfo } from "@/lib/api";
import { AUTO_PARSER, FORMAT_LABELS } from "@/lib/parsers";

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
    <select
      id={id}
      aria-label={label}
      value={value}
      onChange={(e) => {
        const [kind, rest] = e.target.value.split(":") as [string, string];
        if (kind === "auto") {
          onChange(AUTO_PARSER, format === "csv" ? "syslog" : format);
        } else if (kind === "template") {
          const t = templates.find((x) => x.id === rest);
          onChange(rest, t?.envelope === "syslog" ? "syslog" : format === "csv" ? "json" : format);
        } else {
          onChange(null, rest as SourceFormat);
        }
      }}
      className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
    >
      {format !== "csv" || formats.length > 1 ? (
        <option value="auto:">Automatic: pick a template per line</option>
      ) : null}
      <optgroup label="One template (fields mapped to OCSF)">
        {templates.map((t) => (
          <option key={t.id} value={`template:${t.id}`}>
            {t.name}
          </option>
        ))}
      </optgroup>
      <optgroup label="Generic (time, host, and message)">
        {formats.map((f) => (
          <option key={f} value={`generic:${f}`}>
            {FORMAT_LABELS[f]}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
