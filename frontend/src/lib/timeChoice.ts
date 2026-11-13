import { useMemo, useState } from "react";
import type { TimePreset } from "@/components/FilterBar";
import { fragmentValues, setFragment, useSection } from "@/lib/route";
import { localInput, localTime, TIME_IDS, windowOf, type TimeChoice } from "@/lib/timeWindow";

type Fixed = Exclude<TimePreset, "custom">;

const SPAN_MS: Record<Fixed, number> = {
  "1h": 3_600_000,
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

export const TIME_WORDS: Record<Fixed, string> = {
  "1h": "hour",
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
};

export interface PageTime {
  /** The choice, with Custom's sides as local date-times. */
  choice: TimeChoice;
  /** For a query key: changes when the choice does, not as the clock moves. */
  key: readonly string[];
  /** The window as the API takes it, worked out now: a preset ends now (no end). */
  bounds: () => { start?: string; end?: string };
  /** The `time` prop of the page's `FilterBar`. */
  bar: {
    value: TimePreset;
    onChange: (id: TimePreset) => void;
    custom: { from: string; to: string; onChange: (from: string, to: string) => void };
  };
  isDefault: boolean;
  /** "the last 7 days", or "this range" for Custom. */
  words: string;
  /** "previous 7 days", or "period of the same length before" for Custom. */
  before: string;
}

function pageTime(
  choice: TimeChoice,
  fallback: Fixed,
  write: (next: TimeChoice, replace: boolean) => void,
): PageTime {
  const fixed = choice.preset === "custom" ? null : choice.preset;
  return {
    choice,
    key: [choice.preset, choice.from, choice.to],
    bounds: () => {
      const w = windowOf(choice);
      return { start: w.from?.toISOString(), end: w.to?.toISOString() };
    },
    bar: {
      value: choice.preset,
      // Custom opens on the window that was showing (its start filled in, its end open),
      // so choosing it reads nothing new, and never everything kept before a date is set.
      onChange: (id) =>
        write(
          id === "custom"
            ? {
                preset: id,
                from: localInput(
                  new Date(Date.now() - SPAN_MS[fixed ?? fallback]).toISOString().slice(0, 16) +
                    "Z",
                ),
                to: "",
              }
            : { preset: id, from: "", to: "" },
          false,
        ),
      // Typing a date replaces the address: Back leaves Custom in one step.
      custom: {
        from: choice.from,
        to: choice.to,
        onChange: (from, to) => write({ preset: "custom", from, to }, true),
      },
    },
    isDefault: choice.preset === fallback,
    words: fixed ? `the last ${TIME_WORDS[fixed]}` : "this range",
    before: fixed ? `previous ${TIME_WORDS[fixed]}` : "period of the same length before",
  };
}

/** A page's one time control (ADR-0052 section 3.7), kept in the URL fragment beside the
 * page's other state: `time=30d`, or `time=custom&from=...&to=...` with UTC times, so a
 * link is the same moments in any time zone. The page's default is left out of the
 * address. Custom's sides are edited as local date-times; an empty side is open. */
export function usePageTime(fallback: Fixed): PageTime {
  const section = useSection();
  return useMemo(() => {
    const frag = fragmentValues(section);
    const asked = frag.get("time") ?? "";
    const preset = (TIME_IDS as readonly string[]).includes(asked)
      ? (asked as TimePreset)
      : fallback;
    const side = (key: "from" | "to") => {
      const v = frag.get(key) ?? "";
      // A UTC time (what this writes), or a local date-time typed into an address.
      return localTime(v) ? v : localInput(v);
    };
    const choice: TimeChoice =
      preset === "custom"
        ? { preset, from: side("from"), to: side("to") }
        : { preset, from: "", to: "" };
    return pageTime(choice, fallback, (next, replace) => {
      const to = fragmentValues(section);
      for (const k of ["time", "from", "to"]) to.delete(k);
      if (next.preset !== fallback) to.set("time", next.preset);
      if (next.preset === "custom") {
        const utc = (local: string) => localTime(local)?.toISOString() ?? "";
        if (utc(next.from)) to.set("from", utc(next.from));
        if (utc(next.to)) to.set("to", utc(next.to));
      }
      setFragment(to.toString(), replace);
    });
  }, [section, fallback]);
}

/** The same control kept in the page, not the address: for a page whose fragment names
 * what is open (People & devices: `#user=alice`) and is rewritten by every pivot, so the
 * time must not be lost with it. */
export function usePageTimeState(fallback: Fixed): PageTime {
  const [choice, setChoice] = useState<TimeChoice>({ preset: fallback, from: "", to: "" });
  return useMemo(() => pageTime(choice, fallback, (next) => setChoice(next)), [choice, fallback]);
}
