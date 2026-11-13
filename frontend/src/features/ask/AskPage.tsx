import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { navigate } from "@/lib/route";
import { rangeStart, type LogsRange } from "@/lib/search";
import { windowOf } from "@/lib/timeWindow";
import { seedSearch } from "@/lib/searchSeed";
import { FilterBar } from "@/features/search/FilterBar";
import { AskThread } from "./AskThread";

interface AskPageProps {
  isAdmin: boolean;
}

/** Ask AI (D206): its own page under Investigate, for admins and analysts. A question
 * becomes SQL over the chosen range and sources; Open in Logs hands an answer's SQL to the
 * Logs SQL mode with the same range and sources, where it can be changed and saved. */
export function AskPage({ isAdmin }: AskPageProps) {
  const [range, setRange] = useState<LogsRange>("24h");
  // Custom: a start and an end as local date-times; an empty side is open.
  const [custom, setCustom] = useState<{ from: string; to: string } | null>(null);
  const span = custom ? windowOf({ preset: "custom", ...custom }) : null;
  const [sources, setSources] = useState<string[]>([]);
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Ask AI" />
      <div className="flex flex-col gap-2.5 px-5 py-3">
        <FilterBar
          range={range}
          custom={custom}
          onRange={(r) => {
            setCustom(null);
            setRange(r);
          }}
          onCustom={(from, to) => setCustom({ from, to })}
          sources={sources}
          onSources={setSources}
        />
        <AskThread
          start={span ? span.from?.toISOString() : rangeStart(range)}
          end={span?.to?.toISOString()}
          sources={sources}
          isAdmin={isAdmin}
          onEdit={(sql, asked) => {
            seedSearch({
              sql,
              range,
              custom: custom ?? undefined,
              sources: sources.length ? sources : undefined,
              origin: asked ? `From Ask AI: ${asked}` : "From Ask AI",
              askQuestion: asked,
            });
            navigate("logs");
          }}
        />
      </div>
    </div>
  );
}
