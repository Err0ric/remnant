import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Card } from "@/components/Card";
import { OutcomeBadge } from "@/features/audit/OutcomeBadge";
import { EntityLink } from "@/components/EntityLink";
import { Skeleton } from "@/components/Skeleton";
import { When } from "@/components/When";
import { ApiError, api, type AddressSection, type AddressSectionName } from "@/lib/api";
import { isIpAddress } from "@/lib/entity";

interface AddressSectionsProps {
  ip: string;
  /** The whole address has no events: the page has said so once, so empty cards are
   * their titles alone. */
  quiet?: boolean;
  start: string | undefined;
  end?: string;
  /** The range's id, for caching: `start` moves with the clock. */
  range: string;
  /** "the last 7 days" */
  rangeWords: string;
  onSearch: (sql: string) => void;
}

/** The page's titles for the four sections; the server says the same in Ask's answer. */
const TITLES: Record<AddressSectionName, string> = {
  dhcp: "DHCP and VPN history",
  dns: "Names looked up",
  access: "Sign-ins and access",
  ai: "AI services",
};

// What an empty section says beside its title, after "None in <the window>".
const EMPTY_MORE: Partial<Record<AddressSectionName, string>> = {
  dhcp: "; it may be a static address",
};

// The page's one outcome mapping (OutcomeBadge): a success, a failure, a denial, or other.
const OUTCOME: Record<string, [string, string]> = {
  allowed: ["success", "Allowed"],
  denied: ["denied", "Denied"],
  succeeded: ["success", "Succeeded"],
  failed: ["failure", "Failed"],
  "not counted": ["other", "Interrupted or expired"],
  "signed out": ["other", "Signed out"],
  other: ["other", "Other"],
};

type Row = Record<string, unknown>;

function text(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function n(v: unknown): string {
  return Number(v ?? 0).toLocaleString();
}

/** How a cell is drawn: plain, data font, an entity link, a time, a number, a count that
 * opens its events in Logs (DESIGN 6.3: every number opens its rows), a badge, or a line. */
type Cell =
  | "text"
  | "mono"
  | "host"
  | "user"
  | "service"
  | "time"
  | "until"
  | "num"
  | "count"
  | "badge"
  | "line";
const COLUMNS: Record<AddressSectionName, [string, Cell, string][]> = {
  dhcp: [
    ["Kind", "text", "kind"],
    ["Device", "host", "device"],
    ["MAC", "mono", "mac"],
    ["Interface", "mono", "interface"],
    ["Person", "user", "person"],
    ["From", "time", "first_seen"],
    ["To", "until", "last_seen"],
  ],
  dns: [
    ["Name", "mono", "name"],
    ["Queries", "count", "queries"],
    ["First seen", "time", "first_seen"],
    ["Last seen", "time", "last_seen"],
  ],
  access: [
    ["Kind", "text", "kind"],
    ["Outcome", "badge", "outcome"],
    ["Events", "count", "events"],
    ["Last seen", "time", "last_seen"],
    ["Newest line", "line", "newest"],
  ],
  ai: [
    ["Service", "service", "service"],
    ["Events", "count", "events"],
    ["People", "num", "people"],
    ["Machines", "num", "machines"],
    ["Last seen", "time", "last_seen"],
  ],
};

function cell(
  how: Cell,
  r: Row,
  key: string,
  link: string | null,
  onSearch: (sql: string) => void,
): ReactNode {
  const v = r[key];
  if (how === "host" || how === "user")
    return v === null || v === undefined || v === "" ? (
      <span className="text-text-muted">·</span>
    ) : (
      <EntityLink kind={how} value={v} />
    );
  // A lease or tunnel seen on one line only has no length: one time, said so.
  if (how === "until")
    return text(v) === text(r.first_seen) ? (
      <span className="text-text-muted">seen once</span>
    ) : (
      <When iso={text(v)} />
    );
  if (how === "service") return <EntityLink kind="service" value={r.service_id} label={text(v)} />;
  if (how === "time") return <When iso={text(v)} />;
  if (how === "num" || (how === "count" && !link)) return n(v);
  if (how === "count" && link)
    return (
      <button
        type="button"
        onClick={() => onSearch(link)}
        title={`Open ${n(v)} ${Number(v) === 1 ? "event" : "events"} in Logs`}
        className="font-mono tabular-nums text-accent-text hover:underline"
      >
        {n(v)}
      </button>
    );
  if (how === "badge") {
    const [tone, label] = OUTCOME[text(v)] ?? ["other", text(v)];
    return <OutcomeBadge outcome={tone} label={label} />;
  }
  if (how === "line")
    return (
      <span title={text(v)} className="block truncate font-mono text-xs text-text-muted">
        {text(v)}
      </span>
    );
  return (
    <span className={how === "mono" ? "font-mono [overflow-wrap:anywhere]" : ""}>{text(v)}</span>
  );
}

function Rows({ s, onSearch }: { s: AddressSection; onSearch: (sql: string) => void }) {
  // A Kind column that says the same on every row says nothing.
  const kinds = new Set(s.rows.map((r) => r[s.columns.indexOf("kind")]));
  const cols = COLUMNS[s.section].filter(
    ([, , key]) => !(s.section === "dhcp" && key === "kind" && kinds.size === 1),
  );
  // With a line column, every other column takes only its content's width.
  const fit = cols.some(([, how]) => how === "line") ? "w-px whitespace-nowrap" : "";
  const right = (how: Cell) => (how === "num" || how === "count" ? "text-right tabular-nums" : "");
  return (
    <div className="overflow-x-auto">
      <table aria-label={TITLES[s.section]} className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            {cols.map(([label, how]) => (
              <th key={label} className={`px-3 py-1.5 ${right(how)}`}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {s.rows.map((raw, i) => {
            const r: Row = Object.fromEntries(s.columns.map((c, j) => [c, raw[j]]));
            return (
              <tr key={i} className="border-b border-border last:border-0">
                {cols.map(([label, how, key]) => (
                  <td
                    key={label}
                    className={`px-3 py-1.5 align-top ${right(how)} ${how === "line" ? "max-w-0" : fit}`}
                  >
                    {cell(how, r, key, s.links[i] ?? null, onSearch)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Section({
  name,
  ip,
  quiet,
  start,
  end,
  range,
  rangeWords,
  onSearch,
}: AddressSectionsProps & { name: AddressSectionName }) {
  // One request per section, so a slow one holds up no other (P4).
  const q = useQuery({
    queryKey: ["address-section", ip, name, range],
    queryFn: () => api.addressSection(ip, name, start, end),
    staleTime: 60_000,
  });
  const s = q.data;
  const more = Boolean(s && s.count > s.rows.length && s.section !== "access");
  // The newest first: leases and tunnels; the rest are the most first.
  const cut = s?.section === "dhcp" ? "newest" : "top";
  const empty = s?.state === "ok" && s.rows.length === 0;
  // What it read: every source on hover; in words, only those that returned rows.
  const checked = s
    ? `Checked ${s.read.length} ${s.read.length === 1 ? "source" : "sources"}${s.read.length ? `: ${s.read.join(", ")}` : ""}`
    : "";
  const note = !s
    ? undefined
    : s.state === "no_source"
      ? undefined
      : empty
        ? quiet
          ? undefined
          : `None in ${rangeWords}${EMPTY_MORE[name] ?? ""}`
        : more
          ? `${cut} ${s.rows.length} of ${s.count_words}`
          : s.count_words;
  return (
    <Card
      title={TITLES[name]}
      about={
        s
          ? `${s.library === "AI usage" ? `AI usage's own count: ${s.query}` : `the library query ${s.query} (${s.library})`}${s.restricted ? ", on the sources you may read" : ""}.`
          : undefined
      }
      note={note ? <span title={checked}>{note}</span> : undefined}
    >
      {q.isPending ? (
        <Skeleton label={TITLES[name]} rows={3} className="rounded-none border-0" />
      ) : q.error ? (
        <p role="alert" className="px-3 py-2 text-sm text-danger">
          {q.error instanceof ApiError ? q.error.message : "Could not load this section"}
        </p>
      ) : s && s.state === "no_source" ? (
        <p className="px-3 py-2 text-sm text-text-secondary">
          None of the sources you may read is set to {s.needs.join(" or ")}, so nothing was read.
        </p>
      ) : s && !empty ? (
        <>
          <Rows s={s} onSearch={onSearch} />
          <p
            title={checked}
            className="mt-auto border-t border-border px-3 py-1.5 text-xs text-text-muted"
          >
            From {foundWords(s)}
          </p>
        </>
      ) : null}
    </Card>
  );
}

/** "DNS (dns_bind) and firewall (paloalto_traffic)": the sources that returned rows. */
function foundWords(s: AddressSection): ReactNode {
  const byKind = new Map<string, string[]>();
  for (const f of s.found) byKind.set(f.kind, [...(byKind.get(f.kind) ?? []), f.source_id]);
  const parts = [...byKind].map(([kind, ids], i) => (
    <span key={kind}>
      {i === 0 ? "" : i === byKind.size - 1 ? " and " : ", "}
      {kind} (<span className="font-mono">{ids.join(", ")}</span>)
    </span>
  ));
  return parts.length ? parts : "the sources checked";
}

/** The address page's four sections (P4), each a library query the server runs on the
 * caller's view, asked for on its own: who had the address, the names it looked up, its
 * sign-ins and access, and the AI services seen from it. No model is called. */
export function AddressSections(props: AddressSectionsProps) {
  if (!isIpAddress(props.ip)) return null;
  return (
    <div className="flex flex-col gap-3">
      {(Object.keys(TITLES) as AddressSectionName[]).map((name) => (
        <Section key={name} name={name} {...props} />
      ))}
    </div>
  );
}
