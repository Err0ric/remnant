import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type ParamDef, type ParamType } from "@/lib/api";
import { slugify, sqlPlaceholders } from "@/lib/search";

interface SaveSearchFormProps {
  sql: string;
  /** Set when the SQL came from Ask: recorded as the search's origin, informational only. */
  askQuestion?: string;
  /** Set when the SQL came from Simple search: recorded as the origin (ADR-0009 row 7). */
  simpleText?: string;
  onDone: (id: string) => void;
  onCancel: () => void;
}

const TYPES: ParamType[] = ["string", "int", "float", "bool", "timestamp"];

/** Save the current SQL. {{name}} placeholders become typed parameters. */
export function SaveSearchForm({
  sql,
  askQuestion,
  simpleText,
  onDone,
  onCancel,
}: SaveSearchFormProps) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [visibility, setVisibility] = useState<"private" | "shared">("private");
  const names = sqlPlaceholders(sql);
  const [params, setParams] = useState<Record<string, { type: ParamType; def: string }>>(() =>
    Object.fromEntries(names.map((n) => [n, { type: "string" as ParamType, def: "" }])),
  );
  const save = useMutation({
    mutationFn: api.createSearch,
    onSuccess: async (s) => {
      await client.invalidateQueries({ queryKey: ["searches"] });
      onDone(s.id);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const defs: ParamDef[] = names.map((n) => {
      const p = params[n] ?? { type: "string", def: "" };
      const d: ParamDef = { name: n, type: p.type };
      if (p.def !== "") {
        d.default =
          p.type === "int" || p.type === "float"
            ? Number(p.def)
            : p.type === "bool"
              ? p.def === "true"
              : p.def;
      }
      return d;
    });
    save.mutate({
      id: slugify(name),
      name: name.trim(),
      description,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      visibility,
      sql,
      params: defs,
      ...(askQuestion ? { mode: "ask" as const, origin: { ask_prompt: askQuestion } } : {}),
      ...(simpleText ? { origin: { simple_text: simpleText } } : {}),
    });
  };

  return (
    <form
      aria-label="Save search"
      onSubmit={submit}
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">Save search</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field
          label="Name"
          help={name ? `Id: ${slugify(name)}` : "For example: Failed SSH logins by source"}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label="Tags"
          help="Comma separated"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
        />
        <Field
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="save-visibility" className="text-sm font-semibold">
            Visibility
          </label>
          <select
            id="save-visibility"
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as "private" | "shared")}
            className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
          >
            <option value="private">Private: only you</option>
            <option value="shared">Shared: everyone signed in</option>
          </select>
          <p className="text-sm text-text-muted">
            Shared searches run with each person&apos;s own source access, never yours.
          </p>
        </div>
      </div>

      <fieldset className="mt-4">
        <legend className="text-sm font-semibold">Parameters</legend>
        {names.length === 0 ? (
          <p className="text-sm text-text-muted">
            None. Write <span className="font-mono">{"{{name}}"}</span> in the SQL to add one;{" "}
            <span className="font-mono">{"{{start}}"}</span> and{" "}
            <span className="font-mono">{"{{end}}"}</span> come from the time range.
          </p>
        ) : (
          <div className="mt-1 flex flex-col gap-2">
            {names.map((n) => (
              <div key={n} className="grid items-center gap-2 md:grid-cols-[160px_140px_1fr]">
                <span className="font-mono text-sm">{n}</span>
                <select
                  aria-label={`Type of ${n}`}
                  value={params[n]?.type ?? "string"}
                  onChange={(e) =>
                    setParams({
                      ...params,
                      [n]: { type: e.target.value as ParamType, def: params[n]?.def ?? "" },
                    })
                  }
                  className="h-8 rounded border border-border-strong bg-inset px-2 text-sm text-text"
                >
                  {TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <input
                  aria-label={`Default for ${n}`}
                  placeholder="Default (optional)"
                  value={params[n]?.def ?? ""}
                  onChange={(e) =>
                    setParams({
                      ...params,
                      [n]: { type: params[n]?.type ?? "string", def: e.target.value },
                    })
                  }
                  className="h-8 rounded border border-border-strong bg-inset px-2 font-mono text-sm text-text"
                />
              </div>
            ))}
          </div>
        )}
      </fieldset>

      <div className="mt-3">
        <FormError message={save.error instanceof ApiError ? save.error.message : null} />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={!name.trim() || save.isPending}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-8 rounded border border-border-strong px-4 text-sm hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
