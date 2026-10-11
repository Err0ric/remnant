import { columnLabel } from "@/lib/search";
interface ColumnChooserProps {
  columns: string[];
  hidden: string[];
  onChange: (hidden: string[]) => void;
}

/** Which result columns to show. Hiding a column only changes this view, not the query. */
export function ColumnChooser({ columns, hidden, onChange }: ColumnChooserProps) {
  const shown = columns.filter((c) => !hidden.includes(c));
  return (
    <fieldset
      aria-label="Columns"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-3.5 py-2 text-sm"
    >
      <legend className="sr-only">Columns</legend>
      {columns.map((c) => (
        <label key={c} title={c} className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={!hidden.includes(c)}
            // The last shown column stays: a table with no columns explains nothing.
            disabled={shown.length === 1 && !hidden.includes(c)}
            onChange={() =>
              onChange(hidden.includes(c) ? hidden.filter((h) => h !== c) : [...hidden, c])
            }
          />
          {columnLabel(c)}
        </label>
      ))}
      {hidden.length ? (
        <button
          type="button"
          onClick={() => onChange([])}
          className="ml-auto text-text-secondary hover:text-text"
        >
          Show all
        </button>
      ) : null}
    </fieldset>
  );
}
