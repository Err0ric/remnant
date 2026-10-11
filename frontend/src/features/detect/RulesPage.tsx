import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type RuleRun, type SigmaRule } from "@/lib/api";
import { navigate } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { TIME_RANGES } from "@/lib/search";
import { RecentRuns } from "./RecentRuns";
import { RuleImportPanel } from "./RuleImportPanel";
import { RuleYaml } from "./RuleYaml";
import { RulesTable } from "./RulesTable";
import { RunPanel } from "./RunPanel";
import { filterRules } from "./rules";

const SHOWN = 200;
const RUN_RANGES = TIME_RANGES.filter((r) => ["1h", "24h", "7d", "30d"].includes(r.id));

interface RulesPageProps {
  isAdmin: boolean;
  /** Admins and analysts run rules; auditors read runs (ADR-0006 row 5). */
  canRun: boolean;
}

/** Imported Sigma rules: import, enable, run, and matches (ADR-0006). */
export function RulesPage({ isAdmin, canRun }: RulesPageProps) {
  const client = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [text, setText] = useState("");
  const [enabledOnly, setEnabledOnly] = useState(false);
  const [withDataOnly, setWithDataOnly] = useState(false);
  const [rangeId, setRangeId] = useState<string>("24h");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [viewing, setViewing] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<RuleRun | null>(null);
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const runs = useQuery({ queryKey: ["rule-runs"], queryFn: api.ruleRuns });
  const all = useMemo(() => rules.data ?? [], [rules.data]);
  const filtered = useMemo(
    () => filterRules(all, { text, enabledOnly, withDataOnly }),
    [all, text, enabledOnly, withDataOnly],
  );
  const shown = filtered.slice(0, SHOWN);
  const enabledCount = all.filter((r) => r.enabled).length;

  const setEnabled = useMutation({
    mutationFn: (enabled: boolean) => api.setRulesEnabled([...selected], enabled),
    onSuccess: async () => {
      setSelected(new Set());
      await client.invalidateQueries({ queryKey: ["rules"] });
    },
  });
  const run = useMutation({
    mutationFn: (rule: SigmaRule) => {
      const ms = RUN_RANGES.find((r) => r.id === rangeId)?.ms ?? 86_400_000;
      const end = new Date();
      return api.runRule(
        rule.rule_id,
        new Date(end.getTime() - ms).toISOString(),
        end.toISOString(),
      );
    },
    onSuccess: async (result) => {
      setViewing(null);
      setOpenRun(result);
      await client.invalidateQueries({ queryKey: ["rule-runs"] });
    },
  });
  const failure = [rules.error, setEnabled.error, run.error].find(Boolean);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Detect", "Detection rules"]}
        title="Detection rules"
        meta={`${all.length} ${all.length === 1 ? "rule" : "rules"} · ${enabledCount} enabled`}
        commands={
          isAdmin ? (
            <>
              <Command
                label="Import rules"
                primary
                onClick={() => setImporting(true)}
                disabled={importing}
              />
              <Command
                label={`Enable selected (${selected.size})`}
                onClick={() => setEnabled.mutate(true)}
                disabled={!selected.size || setEnabled.isPending}
              />
              <Command
                label="Disable selected"
                onClick={() => setEnabled.mutate(false)}
                disabled={!selected.size || setEnabled.isPending}
              />
            </>
          ) : null
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {importing ? <RuleImportPanel onClose={() => setImporting(false)} /> : null}
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure instanceof ApiError ? failure.message : "That did not work"}
          </p>
        ) : null}
        {openRun ? (
          <RunPanel run={openRun} onClose={() => setOpenRun(null)} canExplain={canRun} />
        ) : null}
        {viewing ? <RuleYaml ruleId={viewing} onClose={() => setViewing(null)} /> : null}
        <RecentRuns runs={runs.data ?? []} onOpen={(r) => setOpenRun(r)} />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <input
            aria-label="Filter rules"
            placeholder="Filter by title, author, tag, or log source"
            className="h-8 min-w-0 flex-[1_1_280px] rounded border border-border bg-inset px-2"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={enabledOnly}
              onChange={(e) => setEnabledOnly(e.target.checked)}
            />
            Enabled only
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={withDataOnly}
              onChange={(e) => setWithDataOnly(e.target.checked)}
            />
            With data only
          </label>
          {canRun ? (
            <label className="flex items-center gap-1.5">
              Run over
              <select
                aria-label="Run over"
                className="h-8 rounded border border-border bg-surface px-1"
                value={rangeId}
                onChange={(e) => setRangeId(e.target.value)}
              >
                {RUN_RANGES.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <RulesTable
            rules={shown}
            isAdmin={isAdmin}
            canRun={canRun}
            selected={selected}
            runningId={run.isPending ? (run.variables?.rule_id ?? null) : null}
            onToggle={toggle}
            onToggleAll={(checked) =>
              setSelected((prev) => {
                const next = new Set(prev);
                for (const r of shown) {
                  if (checked) next.add(r.rule_id);
                  else next.delete(r.rule_id);
                }
                return next;
              })
            }
            onRun={(r) => run.mutate(r)}
            onSchedule={(r) => {
              seedSchedule({ kind: "rule", targetId: r.rule_id });
              navigate("schedules");
            }}
            onView={(r) => {
              setOpenRun(null);
              setViewing(r.rule_id);
            }}
          />
          {filtered.length > SHOWN ? (
            <p className="border-t border-border px-3 py-2 text-sm text-text-secondary">
              Showing the first {SHOWN} of {filtered.length}. Narrow the filter to see more.
            </p>
          ) : null}
          {all.length === 0 && rules.isSuccess ? (
            <p className="px-3 py-8 text-center text-sm text-text-secondary">
              No rules yet.{" "}
              {isAdmin
                ? "Import a folder of Sigma rules, such as a copy of SigmaHQ in /rules."
                : "An administrator can import them."}
            </p>
          ) : null}
        </section>
        <p className="text-xs text-text-muted">
          Each rule shows its author as its licence requires (SigmaHQ rules: Detection Rule License
          1.1). A rule runs only on sources whose template declares its log source.
        </p>
      </div>
    </div>
  );
}
