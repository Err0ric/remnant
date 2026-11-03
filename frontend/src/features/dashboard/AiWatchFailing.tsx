import { useQuery } from "@tanstack/react-query";
import { stamp } from "@/features/overview/time";
import { api, type FailingJob } from "@/lib/api";
import { navigate } from "@/lib/route";

const WHAT: Record<string, string> = {
  "ai_watch.events": "the check for new AI use",
  "ai_watch.agents": "the agent change check",
  "ai_watch.review": "the hourly review",
  "page.ai_watch": "the refresh of these numbers",
};

function what(job: string): string {
  return WHAT[job] ?? job;
}

/** AI Watch checks that are failing (owner, 2026-11-03): they failed for hours with nothing
 * on screen. Says since when and how often, that alerts and items may be behind, and for
 * administrators why, with a link to Health. Nothing renders while all is well. */
export function AiWatchFailing({ isAdmin }: { isAdmin: boolean }) {
  const q = useQuery({
    queryKey: ["ai-watch-status"],
    queryFn: api.aiWatchStatus,
    refetchInterval: 60_000,
  });
  const failing: FailingJob[] = q.data?.failing ?? [];
  if (failing.length === 0) return null;
  const first = failing.reduce((a, b) => (a.since <= b.since ? a : b));
  return (
    <div role="alert" className="border-b border-warn px-3 py-2 text-sm">
      <p>
        <span className="font-semibold">AI Watch checks are failing</span> since{" "}
        {stamp(first.since)} UTC: {failing.map((f) => `${what(f.job)} (${f.count}x)`).join(", ")}.
        New AI use, alerts, and review items may be behind.
      </p>
      {isAdmin ? (
        <p className="mt-0.5 text-text-secondary">
          {failing
            .filter((f) => f.detail)
            .map((f) => (
              <span key={f.job} className="block font-mono [overflow-wrap:anywhere]">
                {f.job}: {f.detail}
              </span>
            ))}
          <button
            type="button"
            onClick={() => navigate("health")}
            className="text-accent-text hover:underline"
          >
            Check now on Health
          </button>
        </p>
      ) : (
        <p className="mt-0.5 text-text-secondary">An administrator can see why on Health.</p>
      )}
    </div>
  );
}
