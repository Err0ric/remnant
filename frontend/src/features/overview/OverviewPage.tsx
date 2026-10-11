import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api } from "@/lib/api";
import { AlertHealthPanel } from "./AlertHealthPanel";
import { DetectionsPanel } from "./DetectionsPanel";
import { IngestPanel } from "./IngestPanel";
import { PausedPanel } from "./PausedPanel";
import { VolumePanel } from "./VolumePanel";
import { stamp } from "./time";

/** The home page (ADR-0008): is data arriving, did anything fire, is anything stuck. */
export function OverviewPage() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const o = overview.data;
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "General", "Overview"]}
        title="Overview"
        meta={o ? `Updated ${stamp(o.generated_at)} UTC` : undefined}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {overview.error ? (
          <p role="alert" className="text-sm text-danger">
            {overview.error instanceof ApiError ? overview.error.message : "Could not load"}
          </p>
        ) : null}
        {overview.isPending ? <p className="text-sm text-text-secondary">Loading…</p> : null}
        {o ? (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-3">
            <VolumePanel overview={o} />
            <IngestPanel overview={o} />
            <DetectionsPanel overview={o} />
            <PausedPanel overview={o} />
            {o.alerts ? <AlertHealthPanel alerts={o.alerts} /> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
