import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { When } from "@/components/When";
import { api, type AddressCoverage } from "@/lib/api";
import { navigate } from "@/lib/route";
import { InventoryMatches } from "./InventoryLine";

/** What each category's line says was checked (ADR-0045 B2). Code, never a model. */
interface Words {
  label: string;
  found: string;
  none: string;
}

const OTHER: Words = { label: "Other sources", found: "no events naming this address", none: "" };

const CATEGORY: Record<string, Words> = {
  dns: { label: "DNS", found: "no lookups by this address", none: "No DNS source" },
  network: {
    label: "Firewall",
    found: "no traffic logged to or from this address",
    none: "No firewall source",
  },
  system: { label: "Syslog", found: "nothing received from this host", none: "No syslog source" },
  identity: {
    label: "Identity",
    found: "no sign-ins from this address",
    none: "No identity source",
  },
  application: { label: "Applications", found: "no events naming this address", none: "" },
  findings: { label: "Findings", found: "no findings naming this address", none: "" },
  other: OTHER,
};

function sourceNotes(c: AddressCoverage["categories"][number]): ReactNode[] {
  const out: ReactNode[] = [];
  const blind = c.sources.filter((s) => !s.records_address).length;
  if (blind) out.push(`${blind} ${blind === 1 ? "does" : "do"} not record addresses`);
  for (const s of c.sources) {
    if (s.state === "not_receiving")
      out.push(
        <span key={s.source_id}>
          <span className="font-mono">{s.source_id}</span> not receiving since{" "}
          <When iso={s.since} />
        </span>,
      );
    else if (s.state === "never")
      out.push(
        <span key={s.source_id}>
          <span className="font-mono">{s.source_id}</span> has received nothing yet
        </span>,
      );
    else if (s.state === "off")
      out.push(
        <span key={s.source_id}>
          <span className="font-mono">{s.source_id}</span> turned off
        </span>,
      );
  }
  return out;
}

interface CoverageLinesProps {
  data: AddressCoverage;
  /** "the last 24 hours" */
  rangeWords: string;
}

/** "No events for 10.20.30.40 in the last 24 hours.", then one line per category. */
export function CoverageLines({ data, rangeWords }: CoverageLinesProps) {
  if (data.events > 0) return null;
  return (
    <section
      aria-label="Why there are no events"
      className="flex flex-col gap-1.5 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <p className="text-text">
        No events for <span className="font-mono">{data.value}</span> in {rangeWords}.
      </p>
      <ul className="flex flex-col gap-1 text-text-secondary">
        {data.categories.map((c) => {
          const words = CATEGORY[c.category] ?? OTHER;
          const notes = sourceNotes(c);
          const n = c.sources.length;
          return (
            <li key={c.category}>
              <span className="font-semibold text-text">{words.label}</span> ({n}{" "}
              {n === 1 ? "source" : "sources"}): {words.found}
              {notes.length ? (
                <span className="text-text-muted">
                  {" "}
                  (
                  {notes.map((x, i) => (
                    <span key={i}>
                      {i ? "; " : ""}
                      {x}
                    </span>
                  ))}
                  )
                </span>
              ) : null}
            </li>
          );
        })}
        {data.missing.map((m) => (
          <li key={m} className="font-semibold text-text">
            {CATEGORY[m]?.none}
          </li>
        ))}
        {data.inventory.length ? (
          <li>
            <InventoryMatches matches={data.inventory} />
          </li>
        ) : data.inventory_source ? (
          <li>Not in the Proxmox inventory</li>
        ) : null}
        {data.restricted ? <li>Sources you don&apos;t have access to were not searched.</li> : null}
      </ul>
      {data.can_add_source ? (
        <button
          type="button"
          onClick={() => navigate("sources")}
          className="self-start text-accent hover:underline"
        >
          Add a source
        </button>
      ) : null}
    </section>
  );
}

interface EmptyAddressProps {
  value: string;
  start: string | undefined;
  end?: string;
  rangeWords: string;
}

/** Asks the server what was searched for an address with no events, and shows it. */
export function EmptyAddress({ value, start, end, rangeWords }: EmptyAddressProps) {
  const q = useQuery({
    queryKey: ["address-coverage", value, start, end],
    queryFn: () => api.addressCoverage(value, start, end),
    staleTime: 60_000,
  });
  return q.data ? <CoverageLines data={q.data} rangeWords={rangeWords} /> : null;
}

const IPV4 = /(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])/;
const IPV6 = /(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){1,7}:?(?:[0-9A-Fa-f]{1,4})?(?![0-9A-Fa-f:])/;

/** The first IP address a question names, for Ask's empty answers (B5); null for none. */
export function addressIn(text: string): string | null {
  const v4 = IPV4.exec(text);
  if (v4) return v4[0];
  const v6 = IPV6.exec(text)?.[0];
  return v6 && (v6.includes("::") || v6.split(":").length === 8) ? v6 : null;
}
