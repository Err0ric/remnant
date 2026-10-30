import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Places } from "@/lib/api";

/** Words, commas, or new lines: one entry each. */
function entries(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

interface FormProps {
  places: Places;
}

function PlacesForm({ places }: FormProps) {
  const client = useQueryClient();
  const [countries, setCountries] = useState(places.approved_countries.join(", "));
  const [nets, setNets] = useState(places.internal_networks.join("\n"));
  const save = useMutation({
    mutationFn: api.setPlaces,
    onSuccess: (data) => {
      client.setQueryData(["places"], data);
      setCountries(data.approved_countries.join(", "));
      setNets(data.internal_networks.join("\n"));
    },
  });
  const codes = entries(countries).map((c) => c.toUpperCase());
  const named = codes.filter((c) => /^[A-Z]{2}$/.test(c));
  return (
    <form
      className="flex flex-col gap-4 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ approved_countries: codes, internal_networks: entries(nets) });
      }}
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor="approved-countries" className="font-semibold text-text">
          Approved countries
        </label>
        <p className="max-w-prose text-text-secondary">
          Two-letter codes, separated by commas (US, CA). Sign-ins and VPN logins from anywhere else
          count as outside approved countries on the Dashboard. Empty: the Dashboard asks for them
          instead of counting.
        </p>
        <input
          id="approved-countries"
          value={countries}
          onChange={(e) => setCountries(e.target.value)}
          spellCheck={false}
          className="h-8 max-w-xl rounded border border-border bg-bg px-2 font-mono text-text"
        />
        {named.length ? (
          <p className="text-text-secondary">
            {named.map((c) => `${countryName(c)} (${c})`).join(", ")}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="internal-networks" className="font-semibold text-text">
          Internal networks
        </label>
        <p className="max-w-prose text-text-secondary">
          One address or range per line, private or public. Anything not listed counts as external
          on the Dashboard (attacks, sign-in failures).
        </p>
        {!places.has_public ? (
          <p
            role="note"
            className="max-w-prose rounded border border-warn bg-surface px-3 py-2 text-text"
          >
            Add your company&apos;s public egress addresses. Office sign-ins and VPN logins come
            from them, and they count as external until they are listed.
          </p>
        ) : null}
        <textarea
          id="internal-networks"
          value={nets}
          onChange={(e) => setNets(e.target.value)}
          rows={8}
          spellCheck={false}
          className="max-w-xl rounded border border-border bg-bg px-2 py-1.5 font-mono text-text"
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setNets(places.defaults.join("\n"))}
            className="text-accent-text hover:underline"
          >
            Use the private ranges
          </button>
          {!places.internal_set ? (
            <span className="text-text-muted">The private ranges are in use until you save.</span>
          ) : null}
        </div>
      </div>

      {save.error ? (
        <p role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={save.isPending}
          className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-60"
        >
          Save
        </button>
        {save.isSuccess ? <span className="text-text-secondary">Saved</span> : null}
      </div>
    </form>
  );
}

/** Approved countries and internal networks (ADR-0038 edit 10, calls 6 and 8). */
export function PlacesSettings() {
  const q = useQuery({ queryKey: ["places"], queryFn: api.places });
  return (
    <section
      aria-label="Countries and networks"
      className="rounded-card border border-border bg-surface"
    >
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold">Countries and networks</h2>
        <p className="mt-0.5 max-w-prose text-text-secondary">
          What the Dashboard counts as outside approved countries and as external. Kept in this
          install&apos;s settings only.
        </p>
      </div>
      {q.data ? (
        <PlacesForm places={q.data} />
      ) : q.error ? (
        <p role="alert" className="p-4 text-danger">
          {q.error instanceof ApiError ? q.error.message : "Could not load"}
        </p>
      ) : (
        <p className="p-4 text-text-secondary">Loading…</p>
      )}
    </section>
  );
}
