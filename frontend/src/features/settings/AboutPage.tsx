import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/PageHeader";
import { api } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/branding";

interface DataSource {
  name: string;
  use: string;
  license: string;
  attribution: string;
  link: string;
}

// Data this server can load from outside, and what each licence asks for (F52).
const SOURCES: DataSource[] = [
  {
    name: "DB-IP IP to City Lite and IP to ASN Lite",
    use: "Country, city, and network owner for addresses (Settings > Enrichment)",
    license: "Creative Commons Attribution 4.0 (CC BY 4.0)",
    attribution: "IP Geolocation by DB-IP",
    link: "https://db-ip.com",
  },
  {
    name: "abuse.ch Feodo Tracker and ThreatFox",
    use: "Known bad addresses and domains (Settings > Enrichment)",
    license: "CC0 1.0 (no rights reserved)",
    attribution: "abuse.ch",
    link: "https://abuse.ch",
  },
  {
    name: "SigmaHQ rules",
    use: "Detection rules, when an administrator imports them (Detection rules)",
    license: "Detection Rule License (DRL) 1.1",
    attribution: "The rule authors named in each rule",
    link: "https://github.com/SigmaHQ/sigma",
  },
];

/** Version, licence, and the outside data this server can use, with the attribution each
 * licence asks for. */
export function AboutPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "About and licenses"]} title="About and licenses" />
      <div className="flex max-w-4xl flex-col gap-4 px-5 py-3 text-sm">
        <section aria-label="This server" className="flex flex-col gap-1">
          <h2 className="text-base font-semibold">{PRODUCT_NAME}</h2>
          <dl className="grid grid-cols-[10rem_minmax(0,1fr)] gap-x-3 gap-y-1">
            <dt className="text-text-secondary">Version</dt>
            <dd className="font-mono">{meta.data?.version ?? ""}</dd>
            <dt className="text-text-secondary">Event schema</dt>
            <dd className="font-mono">
              {meta.data
                ? `OCSF ${meta.data.ocsf_version}, schema ${meta.data.schema_version}`
                : ""}
            </dd>
            <dt className="text-text-secondary">Licence</dt>
            <dd>Apache License 2.0</dd>
          </dl>
        </section>
        <section aria-label="Data sources and licenses" className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Data sources and licenses</h2>
          <div className="overflow-x-auto rounded-card border border-border">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                  <th className="px-3 py-2 font-semibold">Data</th>
                  <th className="px-3 py-2 font-semibold">Used for</th>
                  <th className="px-3 py-2 font-semibold">Licence</th>
                  <th className="px-3 py-2 font-semibold">Attribution</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map((d) => (
                  <tr key={d.name} className="border-b border-border align-top last:border-0">
                    <td className="px-3 py-2">{d.name}</td>
                    <td className="px-3 py-2 text-text-secondary">{d.use}</td>
                    <td className="px-3 py-2">{d.license}</td>
                    <td className="px-3 py-2">
                      <a
                        href={d.link}
                        target="_blank"
                        rel="noreferrer"
                        className="text-text-secondary underline-offset-2 hover:underline"
                      >
                        {d.attribution}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-text-muted">
            Nothing here is downloaded unless an administrator turns it on. Open-source components
            and their licences are listed in the SBOM shipped with each release.
          </p>
        </section>
      </div>
    </div>
  );
}
