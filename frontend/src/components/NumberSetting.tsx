import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { SectionTitle } from "@/components/SectionTitle";

/** A setting's value in force, its bounds, and where it comes from. */
export interface NumberValue {
  value: number;
  min: number;
  max: number;
  /** Shown under the box, for example "90 seconds, from the install's configuration". */
  note?: string;
  /** Saved here and can be cleared, so the default applies again. */
  saved?: boolean;
}

interface NumberSettingProps {
  title: string;
  help: string;
  /** Plural unit after the box and in the read-only value: "minutes", "seconds". */
  unit: string;
  queryKey: string;
  load: () => Promise<NumberValue>;
  save: (n: number) => Promise<NumberValue>;
  /** A button that clears a saved value so the default applies, shown while one is saved. */
  reset?: { label: string; run: () => Promise<NumberValue> };
  canEdit: boolean;
}

/** One whole-number install setting with a range: a box and Save for an Admin, the value
 * for everyone else (the live search time limit, Ask's time limit). */
export function NumberSetting({
  title,
  help,
  unit,
  queryKey,
  load,
  save,
  reset,
  canEdit,
}: NumberSettingProps) {
  const client = useQueryClient();
  const current = useQuery({ queryKey: [queryKey], queryFn: load });
  const [draft, setDraft] = useState<string | null>(null);
  const saving = useMutation({
    mutationFn: (run: () => Promise<NumberValue>) => run(),
    onSuccess: (data) => {
      client.setQueryData([queryKey], data);
      setDraft(null);
    },
  });
  const data = current.data;
  const value = draft ?? String(data?.value ?? "");
  const n = Number(value);
  const valid = data !== undefined && Number.isInteger(n) && n >= data.min && n <= data.max;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) saving.mutate(() => save(n));
  };
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <SectionTitle>{title}</SectionTitle>
      <p className="max-w-3xl text-text-secondary">{help}</p>
      {canEdit ? (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <input
            aria-label={unit.charAt(0).toUpperCase() + unit.slice(1)}
            inputMode="numeric"
            value={value}
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 w-24 rounded border border-border-control bg-surface px-2 tabular-nums"
          />
          <span className="text-text-secondary">
            {unit}
            {data ? ` (${data.min} to ${data.max})` : ""}
          </span>
          <button
            type="submit"
            disabled={saving.isPending || draft === null || !valid}
            className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head disabled:opacity-50"
          >
            Save
          </button>
          {reset && data?.saved ? (
            <button
              type="button"
              disabled={saving.isPending}
              onClick={() => saving.mutate(reset.run)}
              className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head disabled:opacity-50"
            >
              {reset.label}
            </button>
          ) : null}
          {saving.isError ? (
            <span role="alert" className="text-danger">
              {saving.error instanceof ApiError ? saving.error.message : "Could not save."}
            </span>
          ) : null}
        </form>
      ) : (
        <p>{data ? `${data.value} ${unit}` : ""}</p>
      )}
      {data?.note ? <p className="text-text-secondary">{data.note}</p> : null}
    </section>
  );
}
