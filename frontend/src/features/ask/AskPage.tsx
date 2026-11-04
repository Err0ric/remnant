import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { navigate } from "@/lib/route";
import { rangeStart, type TimeRangeId } from "@/lib/search";
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
  const [range, setRange] = useState<TimeRangeId>("24h");
  const [sources, setSources] = useState<string[]>([]);
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Investigate", "Ask AI"]} title="Ask AI" />
      <div className="flex flex-col gap-2.5 px-5 py-3">
        <FilterBar range={range} onRange={setRange} sources={sources} onSources={setSources} />
        <AskThread
          start={rangeStart(range)}
          sources={sources}
          isAdmin={isAdmin}
          onEdit={(sql, asked) => {
            seedSearch({
              sql,
              range,
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
