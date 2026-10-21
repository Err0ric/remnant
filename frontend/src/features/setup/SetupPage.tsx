import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/PageHeader";
import { OptionalSection } from "@/components/forms/OptionalSection";
import { api } from "@/lib/api";
import { navigate, type PageId } from "@/lib/route";

interface Step {
  label: string;
  hint: string;
  done: boolean;
  page: PageId;
}

function StepRow({ step }: { step: Step }) {
  return (
    <li className="flex items-start gap-3 border-t border-border py-2.5 first:border-0">
      <span
        aria-hidden="true"
        className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-xs ${
          step.done ? "border-ok bg-ok text-white" : "border-border-strong"
        }`}
      >
        {step.done ? "✓" : ""}
      </span>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => navigate(step.page)}
          className="text-left text-accent-text hover:underline"
        >
          {step.label}
        </button>
        <span className="sr-only">{step.done ? " (done)" : " (to do)"}</span>
        <div className="text-text-muted">{step.hint}</div>
      </div>
      <span className={`shrink-0 text-xs ${step.done ? "text-ok" : "text-text-muted"}`}>
        {step.done ? "Done" : "To do"}
      </span>
    </li>
  );
}

/** Settings > Setup checklist: what a new install needs, and what is optional. Only
 * checks; it never changes anything. */
export function SetupPage() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules, staleTime: 60_000 });
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources, staleTime: 30_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const enrichment = useQuery({ queryKey: ["enrichment"], queryFn: api.enrichment });
  const watch = useQuery({ queryKey: ["ai-watch"], queryFn: api.aiWatch });
  const catalog = useQuery({ queryKey: ["ai-catalog"], queryFn: api.aiCatalog, staleTime: 60_000 });
  const identities = useQuery({
    queryKey: ["identities"],
    queryFn: api.identities,
    staleTime: 300_000,
  });

  const kinds = new Set((sources.data ?? []).map((s) => s.kind ?? "file"));
  const core: Step[] = [
    {
      label: "Add a log source",
      hint: "Point it at the folder your syslog server writes, or use Discover.",
      done: (overview.data?.sources.length ?? 0) > 0,
      page: "sources",
    },
    {
      label: "Collect AI telemetry",
      hint: "An OpenTelemetry source for Claude Code and the endpoint MCP inventory, so agents and MCP servers show up.",
      done: kinds.has("otlp"),
      page: "sources",
    },
    {
      label: "Review AI services",
      hint: "Mark the AI services you allow as Approved and the rest as Not approved.",
      done: (catalog.data ?? []).some((s) => s.status !== "unreviewed"),
      page: "ai",
    },
    {
      label: "Turn on the AI watch",
      hint: "One alert per first sighting of unapproved AI, sensitive data, or an agent change.",
      done: watch.data?.enabled ?? false,
      page: "ai",
    },
    {
      label: "Import and enable detection rules",
      hint: "Sigma rules (for example SigmaHQ) folded into risk and Investigations.",
      done: (rules.data ?? []).some((r) => r.enabled),
      page: "rules",
    },
    {
      label: "Add an alert target",
      hint: "Teams, Slack, email, or a webhook for flagged runs.",
      done: (targets.data ?? []).length > 0,
      page: "alerts",
    },
    {
      label: "Schedule your rules",
      hint: "So they run on their own and alert, instead of only on demand.",
      done: (schedules.data ?? []).some((s) => s.kind === "rule"),
      page: "schedules",
    },
  ];
  const optional: Step[] = [
    {
      label: "Connect Microsoft 365",
      hint: "Audit logs, Entra sign-ins, Copilot, DLP, and alerts.",
      done: kinds.has("m365"),
      page: "sources",
    },
    {
      label: "List your organization domains",
      hint: "So alice and alice@example.com count as one person.",
      done: (identities.data?.domains ?? []).length > 0,
      page: "identities",
    },
    {
      label: "Keep enrichment data current",
      hint: "Recommended. Country and network for public addresses, updated automatically.",
      done: enrichment.data?.auto_update ?? false,
      page: "enrichment",
    },
    {
      label: "Add an AI provider",
      hint: "For plain-English search and explanations. A local model keeps data local.",
      done: (providers.data ?? []).length > 0,
      page: "providers",
    },
  ];
  const left = core.filter((s) => !s.done).length;
  const loading = overview.isPending || rules.isPending;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "Setup checklist"]} title="Setup checklist" />
      <div className="flex max-w-3xl flex-col gap-4 px-5 py-3 text-sm">
        <p className="text-text-secondary">
          What a new install needs before it is useful. Each step links to where you do it.
        </p>
        <section
          aria-label="Required steps"
          className="rounded-card border border-border bg-surface p-4"
        >
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <h2 className="text-base font-semibold">Core steps</h2>
            <span className="text-text-secondary">
              {loading ? "Checking…" : left === 0 ? "All done" : `${left} of ${core.length} left`}
            </span>
          </div>
          <ol>
            {core.map((s) => (
              <StepRow key={s.label} step={s} />
            ))}
          </ol>
        </section>
        <OptionalSection
          title="More you can add"
          span=""
          defaultOpen
          summary={`${optional.filter((s) => s.done).length} of ${optional.length} done`}
        >
          <ol className="md:col-span-2">
            {optional.map((s) => (
              <StepRow key={s.label} step={s} />
            ))}
          </ol>
        </OptionalSection>
      </div>
    </div>
  );
}
