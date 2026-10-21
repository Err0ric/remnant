import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api } from "@/lib/api";

const INPUT =
  "h-8 min-w-0 rounded border border-border-strong bg-inset px-2 font-mono text-sm text-text";
const BTN = "h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head";
const PRIMARY =
  "h-8 rounded bg-accent px-3 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50";

function errorText(e: unknown): string | null {
  return e instanceof ApiError ? e.message : e ? "That did not work" : null;
}

/** Settings > Identities (ADR-0018): one person under several names. */
export function IdentitiesPage() {
  const client = useQueryClient();
  const data = useQuery({ queryKey: ["identities"], queryFn: api.identities });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["identities"] });
    await client.invalidateQueries({ queryKey: ["entity-risk"] });
    await client.invalidateQueries({ queryKey: ["entity-graph"] });
    await client.invalidateQueries({ queryKey: ["ai-usage"] });
  };
  const domains = useMutation({ mutationFn: api.setIdentityDomains, onSuccess: refresh });
  const alias = useMutation({
    mutationFn: (v: { alias: string; person: string | null }) =>
      api.setIdentityAlias(v.alias, v.person),
    onSuccess: refresh,
  });
  const [domain, setDomain] = useState("");
  const [name, setName] = useState("");
  const [person, setPerson] = useState("");
  const d = data.data;
  const current = d?.domains ?? [];

  const addDomain = (e: FormEvent) => {
    e.preventDefault();
    if (domain.trim())
      domains.mutate([...current, domain.trim()], { onSuccess: () => setDomain("") });
  };
  const addAlias = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim() && person.trim())
      alias.mutate(
        { alias: name.trim(), person: person.trim() },
        {
          onSuccess: () => {
            setName("");
            setPerson("");
          },
        },
      );
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "Identities"]} title="Identities" />
      <div className="flex max-w-4xl flex-col gap-4 px-5 py-3 text-sm">
        <p className="text-text-secondary">
          The same person often appears as <span className="font-mono">alice</span>,{" "}
          <span className="font-mono">CORP\alice</span>, and{" "}
          <span className="font-mono">alice@example.com</span>. Here you say which names are one
          person. It changes how Investigations and AI usage count people; stored events and Search
          keep every name exactly as logged.
        </p>
        <p className="text-text-muted">
          Case differences and <span className="font-mono">DOMAIN\</span> prefixes are always
          ignored. Everything else on this page is optional.
        </p>

        {data.error ? (
          <p role="alert" className="text-danger">
            {errorText(data.error)}
          </p>
        ) : null}

        <section
          aria-label="Organization domains"
          className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">Organization domains</h2>
          <p className="text-text-secondary">
            Addresses in these domains count as the same person as the bare name:{" "}
            <span className="font-mono">alice@example.com</span> is{" "}
            <span className="font-mono">alice</span>. People are shown with the first domain.
          </p>
          {current.length ? (
            <ul className="flex flex-wrap gap-2">
              {current.map((dom, i) => (
                <li
                  key={dom}
                  className="flex items-center gap-2 rounded-badge bg-surface-head px-2 py-1 font-mono"
                >
                  {dom}
                  {i === 0 ? (
                    <span className="font-sans text-xs text-text-muted">shown</span>
                  ) : null}
                  <button
                    type="button"
                    aria-label={`Remove ${dom}`}
                    onClick={() => domains.mutate(current.filter((x) => x !== dom))}
                    className="font-sans text-text-secondary hover:text-danger"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-text-muted">None yet: only exact names are merged.</p>
          )}
          <form onSubmit={addDomain} aria-label="Add a domain" className="flex flex-wrap gap-2">
            <input
              aria-label="Domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="example.com"
              className={`${INPUT} w-64`}
            />
            <button
              type="submit"
              disabled={!domain.trim() || domains.isPending}
              className={PRIMARY}
            >
              Add domain
            </button>
          </form>
          <FormError message={errorText(domains.error)} />
        </section>

        <section
          aria-label="Suggestions"
          className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">Suggestions</h2>
          <p className="text-text-secondary">
            Found in your logs. Nothing is applied until you accept it; check the evidence first.
          </p>
          {data.isLoading ? <p className="text-text-muted">Looking…</p> : null}
          {d && !d.domain_suggestions.length && !d.alias_suggestions.length ? (
            <p className="text-text-muted">No suggestions right now.</p>
          ) : null}
          {d?.domain_suggestions.map((s) => (
            <div
              key={s.domain}
              className="flex flex-wrap items-start justify-between gap-2 border-t border-border pt-3"
            >
              <div className="min-w-0">
                <div>
                  Add <span className="font-mono">{s.domain}</span> as an organization domain
                </div>
                <div className="text-text-muted">
                  {s.shared} of {s.addresses} addresses also appear as bare names:{" "}
                  <span className="font-mono">{s.examples.join(", ")}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => domains.mutate([...current, s.domain])}
                className={BTN}
              >
                Add domain
              </button>
            </div>
          ))}
          {d?.alias_suggestions.map((s) => (
            <div
              key={`${s.alias}>${s.person}`}
              className="flex flex-wrap items-start justify-between gap-2 border-t border-border pt-3"
            >
              <div className="min-w-0">
                <div>
                  <span className="font-mono">{s.alias}</span> is{" "}
                  <span className="font-mono">{s.person}</span>
                </div>
                <div className="text-text-muted">
                  The only two names seen on <span className="font-mono">{s.hosts.join(", ")}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => alias.mutate({ alias: s.alias, person: s.person })}
                className={BTN}
              >
                Accept
              </button>
            </div>
          ))}
        </section>

        <section
          aria-label="Aliases"
          className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4"
        >
          <h2 className="text-base font-semibold">Aliases</h2>
          <p className="text-text-secondary">
            For names the rules above cannot connect, such as{" "}
            <span className="font-mono">jsmith</span> and{" "}
            <span className="font-mono">john.smith@example.com</span>.
          </p>
          <form
            onSubmit={addAlias}
            aria-label="Add an alias"
            className="flex flex-wrap items-center gap-2"
          >
            <input
              aria-label="Name as logged"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="jsmith"
              className={`${INPUT} w-48`}
            />
            <span className="text-text-secondary">is</span>
            <input
              aria-label="Person"
              value={person}
              onChange={(e) => setPerson(e.target.value)}
              placeholder="john.smith@example.com"
              className={`${INPUT} w-64`}
            />
            <button
              type="submit"
              disabled={!name.trim() || !person.trim() || alias.isPending}
              className={PRIMARY}
            >
              Add alias
            </button>
          </form>
          <FormError message={errorText(alias.error)} />
          {d?.aliases.length ? (
            <table aria-label="Aliases" className="w-full">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="py-1.5 pr-3 font-semibold">Name as logged</th>
                  <th className="py-1.5 pr-3 font-semibold">Person</th>
                  <th className="py-1.5 pr-3 font-semibold">Added by</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.aliases.map((a) => (
                  <tr key={a.alias} className="border-b border-border last:border-b-0">
                    <td className="py-1.5 pr-3 font-mono">{a.alias}</td>
                    <td className="py-1.5 pr-3 font-mono">{a.person}</td>
                    <td className="py-1.5 pr-3 text-text-secondary">{a.created_by ?? "·"}</td>
                    <td className="py-1.5 text-right">
                      <button
                        type="button"
                        aria-label={`Remove alias ${a.alias}`}
                        onClick={() => alias.mutate({ alias: a.alias, person: null })}
                        className="text-text-secondary hover:text-danger"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-text-muted">No aliases.</p>
          )}
        </section>
      </div>
    </div>
  );
}
