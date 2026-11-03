import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent } from "react";
import { ApiError, api, type OtlpToken, type PluginPlatform } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/branding";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
import { LoadFailed } from "@/components/LoadFailed";
import { since, stamp } from "@/features/overview/time";
import { SectionTitle } from "@/components/SectionTitle";

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const NEW = "__new__";

/** Settings > Claude plugins (owner 2026-10-29, D127): one place to get the hooks plugin
 * for each platform, filled in for this install, with a named token per deployment that
 * can be revoked alone. A token is never shown here: only its name and first characters. */
export function PluginsPage() {
  const client = useQueryClient();
  const q = useQuery({ queryKey: ["plugins"], queryFn: api.plugins });
  const [source, setSource] = useState<string | null>(null);
  const [pick, setPick] = useState<string>(NEW);
  const [name, setName] = useState("");
  const [server, setServer] = useState("");
  const [pilot, setPilot] = useState("");
  const [cert, setCert] = useState<boolean | null>(null); // null: the server's default
  const [error, setError] = useState<string | null>(null);
  const d = q.data;
  const sourceId = source ?? d?.sources[0]?.source_id ?? null;
  const live = (d?.tokens ?? []).filter(
    (t) => t.source_id === sourceId && !t.revoked_at && t.downloadable,
  );
  // A token revoked (or gone) since it was picked falls back to "New token", so a download
  // never asks for a token that no longer exists (owner, 2026-11-02).
  const chosen = live.some((t) => t.token_id === pick) ? pick : NEW;
  const pilots = pilot.split(/[\s,;]+/).filter(Boolean);
  const certInfo = d?.certificate;
  const typedHost = hostOf(server);
  const certDefault =
    !!certInfo?.include_by_default && (!typedHost || certInfo.names.includes(typedHost));
  const includeCert = !!certInfo?.self_signed && (cert ?? certDefault);
  const certReason =
    typedHost && certInfo?.self_signed && !certInfo.names.includes(typedHost)
      ? `Off: ${typedHost} is not a name on this server's certificate, so another certificate answers there.`
      : (certInfo?.reason ?? "");
  const download = useMutation({
    mutationFn: (v: { platform: PluginPlatform; managed: boolean }) => {
      if (!sourceId) throw new Error("No source");
      return api.claudePlugin(sourceId, {
        ...(server.trim() ? { server_url: server.trim() } : {}),
        pilot_users: pilots,
        platform: v.platform,
        managed: v.managed,
        trust_server_certificate: includeCert,
        ...(chosen === NEW ? { token_name: name.trim() || undefined } : { token_id: chosen }),
      });
    },
    onSuccess: ({ blob }, v) => {
      setError(null);
      save(
        blob,
        `${PRODUCT_NAME.toLowerCase()}-claude-hooks-${v.platform}-${v.managed ? "managed" : "plugin"}-${sourceId}.zip`,
      );
      setName("");
      void client.invalidateQueries({ queryKey: ["plugins"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "The download failed"),
  });
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "Claude plugins"]} title="Claude plugins" />
      <div className="flex max-w-6xl flex-col gap-4 p-5">
        {q.isLoading ? (
          <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />
        ) : q.isError ? (
          <LoadFailed
            what="Claude plugins"
            error={q.error}
            onRetry={() => void q.refetch()}
            retrying={q.isFetching}
          />
        ) : !d ? null : d.sources.length === 0 ? (
          <section className="rounded-card border border-border bg-surface p-4 text-sm">
            <p className="font-semibold">Add an OpenTelemetry source first</p>
            <p className="mt-1 text-text-secondary">
              The plugin sends to an OTLP source, which holds its tokens.{" "}
              <button
                type="button"
                onClick={() => navigate("sources")}
                className="text-accent-text hover:underline"
              >
                Add a source
              </button>
            </p>
          </section>
        ) : (
          <>
            <section
              aria-label="Package settings"
              className="grid gap-3 rounded-card border border-border bg-surface p-4 text-sm md:grid-cols-2"
            >
              {d.sources.length > 1 ? (
                <label className="flex flex-col gap-1">
                  <span className="font-semibold">Source</span>
                  <select
                    value={sourceId ?? ""}
                    onChange={(e) => {
                      setSource(e.target.value);
                      setPick(NEW);
                    }}
                    className="h-8 rounded border border-border bg-inset px-2"
                  >
                    {d.sources.map((s) => (
                      <option key={s.source_id} value={s.source_id}>
                        {s.source_id}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="flex flex-col gap-1">
                <span className="font-semibold">Deployment token</span>
                <select
                  value={chosen}
                  onChange={(e) => setPick(e.target.value)}
                  className="h-8 rounded border border-border bg-inset px-2"
                >
                  <option value={NEW}>New token</option>
                  {live.map((t) => (
                    <option key={t.token_id} value={t.token_id}>
                      {t.name} ({t.prefix}…)
                    </option>
                  ))}
                </select>
                <span className="text-text-muted">
                  Each deployment gets its own token, so one can be revoked without breaking the
                  others.
                </span>
              </label>
              {chosen === NEW ? (
                <label className="flex flex-col gap-1">
                  <span className="font-semibold">Token name</span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="pilot, all windows"
                    maxLength={80}
                    className="h-8 rounded border border-border bg-inset px-2"
                  />
                </label>
              ) : null}
              <label className="flex flex-col gap-1">
                <span className="font-semibold">Server address</span>
                <input
                  value={server}
                  onChange={(e) => setServer(e.target.value)}
                  placeholder={d.public_url ?? "https://siem.example:8080"}
                  className="h-8 rounded border border-border bg-inset px-2 font-mono"
                />
                <span className="text-text-muted">
                  Where people's computers reach this server. Records go to /api/otlp/v1/logs.
                </span>
              </label>
              <label className="flex flex-col gap-1">
                <span className="font-semibold">Pilot users</span>
                <input
                  value={pilot}
                  onChange={(e) => setPilot(e.target.value)}
                  placeholder="Empty: everyone who has the plugin"
                  className="h-8 rounded border border-border bg-inset px-2 font-mono"
                />
                {pilots.length ? (
                  <span className="text-text-muted">
                    Only{" "}
                    {pilots.length === 1
                      ? "this person sends"
                      : `these ${pilots.length} people send`}
                    .
                  </span>
                ) : (
                  <span role="note" className="text-warn">
                    Everyone who installs this plugin will send records.
                  </span>
                )}
              </label>
              {certInfo?.self_signed ? (
                <label className="flex items-start gap-2 md:col-span-2">
                  <input
                    type="checkbox"
                    checked={includeCert}
                    onChange={(e) => setCert(e.target.checked)}
                    className="mt-1"
                  />
                  <span className="flex flex-col">
                    <span className="font-semibold">
                      Include this server's self-signed certificate
                    </span>
                    <span className="text-text-muted">{certReason}</span>
                  </span>
                </label>
              ) : null}
            </section>
            {error ? (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            ) : null}
            <div className="grid gap-4 md:grid-cols-2">
              {d.variants.map((v) => (
                <section
                  key={v.platform}
                  aria-label={v.label}
                  className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4 text-sm"
                >
                  <SectionTitle>{v.label}</SectionTitle>
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-0.5">
                    <dt className="text-text-secondary">Version</dt>
                    <dd className="font-mono">{d.version}</dd>
                    <dt className="text-text-secondary">Script SHA-256</dt>
                    <dd className="break-all font-mono text-xs">{v.script_sha256}</dd>
                    <dt className="text-text-secondary">Devices, last 24 hours</dt>
                    <dd className="tabular-nums">{v.devices_24h}</dd>
                    <dt className="text-text-secondary">Last event</dt>
                    <dd title={v.last_event ? `${stamp(v.last_event)} UTC` : undefined}>
                      {v.last_event ? since(v.last_event, new Date().toISOString()) : "None yet"}
                    </dd>
                    <dt className="text-text-secondary">Records lost, last 24 hours</dt>
                    <dd className={cn("tabular-nums", v.dropped_24h ? "text-warn" : "")}>
                      {v.dropped_24h}
                    </dd>
                  </dl>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={download.isPending}
                      onClick={() => download.mutate({ platform: v.platform, managed: false })}
                      className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-60"
                    >
                      Download plugin
                    </button>
                    <button
                      type="button"
                      disabled={download.isPending}
                      onClick={() => download.mutate({ platform: v.platform, managed: true })}
                      className="h-8 rounded border border-border px-3 hover:bg-surface-head disabled:opacity-60"
                    >
                      Download managed bundle
                    </button>
                  </div>
                  <p className="text-text-muted">
                    The plugin: on one machine, unzip it and run{" "}
                    <code className="font-mono">
                      {v.platform === "windows" ? "install-local.ps1" : "install-local.sh"}
                    </code>{" "}
                    from a terminal (the desktop app&apos;s Code tab cannot run /plugin); for the
                    organization, upload it under Organization settings, Plugins and skills. The
                    managed bundle: the plugin with an empty config plus hooks.conf for your
                    endpoint management tool, with the path it goes to.
                  </p>
                </section>
              ))}
            </div>
            <Tokens tokens={d.tokens} />
            <section
              aria-label="Check a deployment"
              className="rounded-card border border-border bg-surface p-4 text-sm"
            >
              <SectionTitle className="mb-1">Check a deployment</SectionTitle>
              <ol className="list-decimal pl-5 text-text-secondary">
                <li>Run a short Claude Code session on a pilot computer.</li>
                <li>
                  Agents, Sessions shows one record of each step: start, prompt, tool calls, stop.
                </li>
                <li>Stop this server for a minute: Claude Code should not slow down.</li>
                <li>Start it again: the records sent meanwhile arrive, marked late.</li>
              </ol>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

/** The host name of a typed server address, lower case; "" when it does not parse. */
function hostOf(raw: string): string {
  try {
    return raw.trim() ? new URL(raw.trim()).hostname.toLowerCase().replace(/^\[|\]$/g, "") : "";
  } catch {
    return "";
  }
}

function Tokens({ tokens }: { tokens: OtlpToken[] }) {
  const client = useQueryClient();
  const [confirm, setConfirm] = useState<string | null>(null);
  const revoke = useMutation({
    mutationFn: (t: OtlpToken) => api.revokeOtlpToken(t.source_id, t.token_id),
    onSuccess: () => {
      setConfirm(null);
      void client.invalidateQueries({ queryKey: ["plugins"] });
    },
  });
  // "Send a test record" (owner 2026-11-02): one synthetic SessionStart through the real
  // receiver with this deployment's token; the HTTP result shows under the row.
  const [tested, setTested] = useState<Record<string, { ok: boolean; text: string }>>({});
  const test = useMutation({
    mutationFn: (t: OtlpToken) => api.testOtlpToken(t.source_id, t.token_id),
    onSuccess: (r, t) => {
      setTested((m) => ({
        ...m,
        [`${t.source_id}:${t.token_id}`]: { ok: r.ok, text: `HTTP ${r.status}. ${r.detail}` },
      }));
      void client.invalidateQueries({ queryKey: ["plugins"] });
    },
    onError: (e, t) =>
      setTested((m) => ({
        ...m,
        [`${t.source_id}:${t.token_id}`]: {
          ok: false,
          text: e instanceof ApiError ? e.message : "Could not send the test record",
        },
      })),
  });
  const now = new Date().toISOString();
  const submit = (e: FormEvent, t: OtlpToken) => {
    e.preventDefault();
    revoke.mutate(t);
  };
  return (
    <section
      aria-label="Deployment tokens"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <h2 className="border-b border-border bg-surface-head px-3 py-2 text-base font-semibold">
        Deployment tokens
      </h2>
      {tokens.length === 0 ? (
        <p className="px-3 py-3 text-sm text-text-secondary">
          No tokens yet. A download creates one with the name you give it.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Name</th>
                <th className="px-3 py-2 font-semibold">Token</th>
                <th className="px-3 py-2 font-semibold">Source</th>
                <th className="px-3 py-2 font-semibold">Created</th>
                <th className="px-3 py-2 font-semibold">Last used</th>
                <th className="px-3 py-2 text-right font-semibold">Devices</th>
                <th className="px-3 py-2 font-semibold">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <Fragment key={`${t.source_id}:${t.token_id}`}>
                  <tr
                    className={cn(
                      "border-b border-border last:border-0",
                      t.revoked_at && "text-text-muted",
                    )}
                  >
                    <td className="px-3 py-2 font-semibold">{t.name}</td>
                    <td className="px-3 py-2 font-mono">{t.prefix}…</td>
                    <td className="px-3 py-2 font-mono">{t.source_id}</td>
                    <td
                      className="px-3 py-2"
                      title={t.created_at ? `${stamp(t.created_at)} UTC` : undefined}
                    >
                      {t.created_at ? since(t.created_at, now) : "Before named tokens"}
                    </td>
                    <td className="px-3 py-2">
                      {t.last_used_at ? since(t.last_used_at, now) : "Never"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums" title={t.hosts.join(", ")}>
                      {t.devices}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {t.revoked_at ? (
                        <span>Revoked {since(t.revoked_at, now)}</span>
                      ) : confirm === `${t.source_id}:${t.token_id}` ? (
                        <form onSubmit={(e) => submit(e, t)} className="flex justify-end gap-2">
                          <span className="text-text-secondary">
                            {t.devices} {t.devices === 1 ? "device stops" : "devices stop"} sending.
                          </span>
                          <button
                            type="submit"
                            className="font-semibold text-danger hover:underline"
                          >
                            Revoke
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirm(null)}
                            className="text-text-secondary hover:underline"
                          >
                            Cancel
                          </button>
                        </form>
                      ) : (
                        <span className="flex justify-end gap-3">
                          {t.downloadable ? (
                            <button
                              type="button"
                              aria-label={`Send a test record with ${t.name}`}
                              disabled={test.isPending}
                              onClick={() => test.mutate(t)}
                              className="text-accent-text hover:underline disabled:opacity-60"
                            >
                              Send a test record
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => setConfirm(`${t.source_id}:${t.token_id}`)}
                            className="text-accent-text hover:underline"
                          >
                            Revoke
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                  {tested[`${t.source_id}:${t.token_id}`] ? (
                    <tr className="border-b border-border last:border-0">
                      <td colSpan={7} className="px-3 pb-2">
                        <p
                          role="status"
                          className={cn(
                            "text-sm",
                            tested[`${t.source_id}:${t.token_id}`]!.ok
                              ? "text-text-secondary"
                              : "text-danger",
                          )}
                        >
                          Test record for {t.name}: {tested[`${t.source_id}:${t.token_id}`]!.text}
                        </p>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
