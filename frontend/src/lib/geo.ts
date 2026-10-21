import type { GeoInfo } from "@/lib/api";

/** "NL · AS64500": the muted label after an address in results (ADR-0023 row 6). */
export function geoShort(info: GeoInfo): string {
  return [info.country, info.asn != null ? `AS${info.asn}` : null].filter(Boolean).join(" · ");
}

/** "Netherlands · AS64500 Example Net": the line under an address in an event. */
export function geoLong(info: GeoInfo): string {
  const asn = info.asn != null ? [`AS${info.asn}`, info.org].filter(Boolean).join(" ") : info.org;
  return [info.country_name ?? info.country, asn].filter(Boolean).join(" · ");
}
