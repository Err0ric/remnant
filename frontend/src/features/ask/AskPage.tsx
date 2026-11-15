import { useState } from "react";
import { CustomRange, FacetSelect, TIME_PRESETS } from "@/components/FilterBar";
import { PageHeader } from "@/components/shell/PageHeader";
import { navigate } from "@/lib/route";
import { rangeStart, type LogsRange } from "@/lib/search";
import { windowOf } from "@/lib/timeWindow";
import { seedSearch } from "@/lib/searchSeed";
import { AskThread } from "./AskThread";
import { SourcesChip } from "./SourcesChip";

interface AskPageProps {
  isAdmin: boolean;
}

/** Ask AI (D206), search first (D256): its own page under Investigate, for admins and
 * analysts. The prompt comes first, then Time, Sources, and Model as chips; a question
 * becomes SQL over that range and those sources. Open in Logs hands an answer's SQL to the
 * Logs SQL mode with the same range and sources, where it can be changed and saved. */
export function AskPage({ isAdmin }: AskPageProps) {
  const [range, setRange] = useState<LogsRange>("24h");
  // Custom: a start and an end as local date-times; an empty side is open.
  const [custom, setCustom] = useState<{ from: string; to: string } | null>(null);
  const span = custom ? windowOf({ preset: "custom", ...custom }) : null;
  const [sources, setSources] = useState<string[]>([]);
  // New question in the header: the thread starts over (a count, so each click is new).
  const [hasTurns, setHasTurns] = useState(false);
  const [startOver, setStartOver] = useState(0);
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Ask AI"
        secondary={
          hasTurns ? [{ label: "New question", onClick: () => setStartOver((n) => n + 1) }] : []
        }
      />
      <div className="flex flex-col px-5 py-3">
        <AskThread
          start={span ? span.from?.toISOString() : rangeStart(range)}
          end={span?.to?.toISOString()}
          sources={sources}
          isAdmin={isAdmin}
          startOver={startOver}
          onTurns={setHasTurns}
          filters={
            <>
              <FacetSelect
                name="Time"
                value={custom ? "custom" : range}
                options={[...TIME_PRESETS]}
                onChange={(id) => {
                  // Custom opens with both sides open: everything kept, until a date is set.
                  if (id === "custom") return setCustom({ from: "", to: "" });
                  setCustom(null);
                  setRange(id as LogsRange);
                }}
              />
              {custom ? (
                <CustomRange
                  from={custom.from}
                  to={custom.to}
                  onChange={(from, to) => setCustom({ from, to })}
                />
              ) : null}
              <SourcesChip sources={sources} onSources={setSources} />
            </>
          }
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
