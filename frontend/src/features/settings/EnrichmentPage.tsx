import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { PlacesSettings } from "./PlacesSettings";
import { since, stamp } from "@/features/overview/time";
import { ApiError, api, type EnrichmentFeed, type FeedLevel } from "@/lib/api";

const LEVEL: Record<FeedLevel, { label: string; badge: string }> = {
  healthy: { label: "Current", badge: "bg-local-bg text-local-text" },
  attention: { label: "Getting old", badge: "bg-sev-medium-bg text-sev-medium-text" },
  unhealthy: { label: "Out of date", badge: "bg-sev-critical-bg text-sev-critical-text" },
  missing: { label: "Not installed", badge: "bg-sev-info-bg text-text-secondary" },
};

function mb(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function KeyForm({ feed, onDone }: { feed: EnrichmentFeed; onDone: () => void }) {
  const client = useQueryClient();
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: (value: string) => api.setFeed(feed.feed_id, { key: value }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["enrichment"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (key.trim()) save.mutate(key.trim());
  };
  return (
    <form onSubmit={submit} className="mt-1.5 flex flex-wrap items-center gap-2">
      <input
        type="password"
        autoComplete="off"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        aria-label={`Auth-Key for ${feed.label}`}
        placeholder="abuse.ch Auth-Key"
        className="h-7 w-56 rounded border border-border-strong bg-inset px-2 font-mono text-xs"
      />
      <button
        type="submit"
        disabled={!key.trim() || save.isPending}
        className="h-7 rounded border border-border-strong px-2.5 text-sm hover:bg-surface-head disabled:opacity-40"
      >
        Save key
      </button>
      <button
        type="button"
        onClick={onDone}
        className="text-sm text-text-secondary hover:text-text"
      >
        Cancel
      </button>
      {save.error ? (
        <span role="alert" className="text-xs text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
    </form>
  );
}

interface FeedRowProps {
  feed: EnrichmentFeed;
  now: string;
}

function FeedRow({ feed, now }: FeedRowProps) {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [keying, setKeying] = useState(false);
  const done = () => void client.invalidateQueries({ queryKey: ["enrichment"] });
  const update = useMutation({ mutationFn: () => api.updateFeed(feed.feed_id), onSettled: done });
  const upload = useMutation({
    mutationFn: (file: File) => api.uploadFeed(feed.feed_id, file),
    onSettled: done,
  });
  const toggle = useMutation({
    mutationFn: (on: boolean) => api.setFeed(feed.feed_id, { enabled: on }),
    onSettled: done,
  });
  const error = update.error ?? upload.error ?? toggle.error;
  const intel = feed.kind === "intel";
  const waitingForKey = feed.needs_key && !feed.has_key;
  const level = !feed.enabled
    ? { label: "Off", badge: "bg-sev-info-bg text-text-secondary" }
    : waitingForKey
      ? { label: "Needs a key", badge: "bg-sev-info-bg text-text-secondary" }
      : LEVEL[feed.level];
  return (
    <tr className={`border-t border-border align-top ${feed.enabled ? "" : "text-text-muted"}`}>
      {intel ? (
        <td className="w-10 py-2.5 pl-3">
          <input
            type="checkbox"
            checked={feed.enabled}
            disabled={toggle.isPending}
            onChange={(e) => toggle.mutate(e.target.checked)}
            aria-label={`Use ${feed.label}`}
          />
        </td>
      ) : null}
      <td className="px-3 py-2.5">
        <div className={feed.enabled ? "text-text" : ""}>{feed.label}</div>
        <div className="text-xs text-text-muted">
          {feed.terms_url ? (
            <a
              href={feed.terms_url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-text hover:underline"
            >
              {feed.provider}
            </a>
          ) : (
            feed.provider
          )}
        </div>
        {keying ? <KeyForm feed={feed} onDone={() => setKeying(false)} /> : null}
      </td>
      <td className="px-3 py-2.5">
        <span className={`rounded-badge px-2 py-px text-xs ${level.badge}`}>{level.label}</span>
      </td>
      <td className="px-3 py-2.5 text-xs">
        {feed.installed_at ? (
          <>
            <span className="font-mono text-text">
              {intel
                ? `${feed.entries.toLocaleString()} ${feed.entries === 1 ? "entry" : "entries"}`
                : (feed.version ?? "")}
            </span>
            <div className="text-text-muted">
              {feed.source === "upload" ? "Uploaded" : "Downloaded"} {since(feed.installed_at, now)}
              {feed.size ? ` · ${mb(feed.size)}` : ""}
            </div>
          </>
        ) : (
          <span className="text-text-muted">None yet</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-text-secondary">
        {!feed.downloadable ? (
          <span className="text-text-muted">Upload only</span>
        ) : feed.checked_at ? (
          <span title={`${stamp(feed.checked_at)} UTC`}>{since(feed.checked_at, now)}</span>
        ) : (
          "Never"
        )}
        {feed.error || error ? (
          <div role="alert" className="mt-0.5 max-w-xs text-warn">
            {error instanceof ApiError ? error.message : feed.error}
          </div>
        ) : null}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right">
        {feed.needs_key ? (
          <button
            type="button"
            onClick={() => setKeying(!keying)}
            className="h-7 rounded px-2.5 text-sm text-text hover:bg-surface-head"
          >
            {feed.has_key ? "Change key" : "Add key"}
          </button>
        ) : null}
        {feed.downloadable ? (
          <button
            type="button"
            onClick={() => update.mutate()}
            disabled={update.isPending || !feed.enabled || waitingForKey}
            className="h-7 rounded px-2.5 text-sm text-accent-text hover:bg-surface-head disabled:opacity-40"
          >
            {update.isPending ? "Checking…" : "Update now"}
          </button>
        ) : null}
        {feed.feed_id !== "intel_threatfox" ? (
          <button
            type="button"
            onClick={() => input.current?.click()}
            disabled={upload.isPending}
            className="h-7 rounded px-2.5 text-sm text-text hover:bg-surface-head disabled:opacity-40"
          >
            {upload.isPending ? "Uploading…" : feed.downloadable ? "Upload file" : "Upload list"}
          </button>
        ) : null}
        <input
          ref={input}
          type="file"
          accept={intel ? ".txt,.csv" : ".mmdb,.gz"}
          aria-label={`Upload a file for ${feed.label}`}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
      </td>
    </tr>
  );
}

function FeedTable({
  label,
  feeds,
  now,
  intel,
}: {
  label: string;
  feeds: EnrichmentFeed[];
  now: string;
  intel: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full text-sm">
        <thead className="bg-surface-head text-left text-xs uppercase tracking-wide text-text-muted">
          <tr>
            {intel ? (
              <th className="w-10 py-2 pl-3 font-medium">
                <span className="sr-only">On</span>
              </th>
            ) : null}
            <th className="px-3 py-2 font-medium">{intel ? "List" : "Feed"}</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">{intel ? "Contents" : "Edition"}</th>
            <th className="px-3 py-2 font-medium">Last check</th>
            <th className="px-3 py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {feeds.map((f) => (
            <FeedRow key={f.feed_id} feed={f} now={now} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Settings > Enrichment (ADR-0023): GeoIP and threat intel, looked up on this server,
 * kept current on request. */
export function EnrichmentPage() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["enrichment"], queryFn: api.enrichment });
  const auto = useMutation({
    mutationFn: api.setEnrichmentAuto,
    onSuccess: (data) => client.setQueryData(["enrichment"], data),
  });
  const data = status.data;
  const now = new Date().toISOString();
  const error = status.error ?? auto.error;
  const geo = (data?.feeds ?? []).filter((f) => f.kind === "geoip");
  const intel = (data?.feeds ?? []).filter((f) => f.kind === "intel");

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Settings", "Enrichment"]}
        title="Enrichment"
        meta="Looked up on this server · no address is sent anywhere"
      />
      <div className="flex max-w-5xl flex-col gap-4 px-5 py-3 text-sm">
        {error ? (
          <p role="alert" className="text-danger">
            {error instanceof ApiError ? error.message : "Could not load enrichment settings"}
          </p>
        ) : null}

        <section
          aria-label="Automatic updates"
          className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4"
        >
          <label className="flex items-start gap-2.5">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={data?.auto_update ?? false}
              disabled={!data || auto.isPending}
              onChange={(e) => auto.mutate(e.target.checked)}
            />
            <span>
              <span className="font-semibold text-text">
                Keep these lists and files current automatically
              </span>
              <span className="mt-0.5 block max-w-prose text-text-secondary">
                GeoIP is checked once a day and downloaded only when a new monthly edition is out.
                Threat intel lists are checked every 4 hours and downloaded only when they changed.
                Connects only to download.db-ip.com, feodotracker.abuse.ch, and
                threatfox-api.abuse.ch, through the proxy if one is set, and sends nothing from your
                logs. Off until you turn it on.
              </span>
            </span>
          </label>
        </section>

        <section aria-label="GeoIP" className="rounded-card border border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-base font-semibold">GeoIP</h2>
            <p className="mt-0.5 text-text-secondary">
              Country and network after public addresses in search results.
            </p>
          </div>
          <FeedTable label="GeoIP files" feeds={geo} now={now} intel={false} />
        </section>

        <section aria-label="Threat intel" className="rounded-card border border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-base font-semibold">Threat intel</h2>
            <p className="mt-0.5 max-w-prose text-text-secondary">
              Values in search results that appear on a list get a small red marker; search{" "}
              <span className="font-mono text-text">intel:listed</span> for every event that touches
              one. ThreatFox needs a free Auth-Key from abuse.ch. Your list takes one address,
              domain, URL, or hash per line, optionally followed by a comma and a note.
            </p>
          </div>
          <FeedTable label="Threat intel lists" feeds={intel} now={now} intel />
        </section>

        <PlacesSettings />

        {status.isPending ? <p className="text-text-secondary">Loading…</p> : null}

        <p className="max-w-prose text-xs text-text-muted">
          No internet on this server? Download the monthly .mmdb.gz files from db-ip.com/db/lite.php
          on another machine and use Upload file. MaxMind GeoLite2 country and ASN files work too.{" "}
          {data ? (
            <a
              href={data.attribution_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent-text hover:underline"
            >
              {data.attribution}
            </a>
          ) : null}
        </p>
      </div>
    </div>
  );
}
