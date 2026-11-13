import { useMemo } from "react";
import { fragmentValues, setFragment, useSection } from "@/lib/route";

export interface Filters<K extends string> {
  values: Record<K, string>;
  /** Sets one filter. `replace` keeps Back where it was (typing in a text box). */
  set: (key: K, value: string, replace?: boolean) => void;
  reset: () => void;
  /** Every filter is at the page's default. */
  isDefault: boolean;
}

/** A page's filters, kept in the URL fragment (DESIGN.md 6.0: filter state lives in the
 * fragment). A filter at its default is left out of the address, so the default page has a
 * clean one. Other fragment state (`item=<id>`) is kept when a filter changes, and dropped
 * on Reset only if it is one of the page's own filters. A filter with a list in `allowed`
 * takes only those values: anything else in the address reads as the default, so a mistyped
 * address filters nothing and shows no Reset. */
export function useFilters<K extends string>(
  defaults: Record<K, string>,
  allowed: Partial<Record<K, readonly string[]>> = {},
): Filters<K> {
  const section = useSection();
  return useMemo(() => {
    const keys = Object.keys(defaults) as K[];
    const frag = fragmentValues(section);
    const read = (k: K) => {
      const v = frag.get(k);
      const ok = allowed[k];
      return v === null || (ok && !ok.includes(v)) ? defaults[k] : v;
    };
    const values = Object.fromEntries(keys.map((k) => [k, read(k)])) as Record<K, string>;
    // On the address the person is on: a tab of a page keeps its path.
    const go = (next: URLSearchParams, replace: boolean) => setFragment(next.toString(), replace);
    return {
      values,
      isDefault: keys.every((k) => values[k] === defaults[k]),
      set: (key, value, replace = false) => {
        const next = fragmentValues(section);
        if (value === defaults[key]) next.delete(key);
        else next.set(key, value);
        go(next, replace);
      },
      reset: () => {
        const next = fragmentValues(section);
        for (const k of keys) next.delete(k);
        go(next, false);
      },
    };
    // `defaults` and `allowed` are constants per page; the fragment is what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);
}
