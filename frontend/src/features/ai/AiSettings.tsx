import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, type AiWatch } from "@/lib/api";
import { StatusBadge, StatusPicker } from "./StatusBadge";

const SECTION = "overflow-hidden rounded-card border border-border bg-surface";
const HEAD = "border-b border-border bg-surface-head px-3 py-2";

function message(err: unknown): string {
  return err instanceof ApiError ? err.message : "That did not work";
}

/** Admin settings for AI usage (ADR-0015 rows 1, 7, 9): watch, MCP rules, catalog. */
export function AiSettings() {
  return (
    <div className="flex flex-col gap-3">
      <WatchSettings />
      <McpRules />
      <CatalogList />
    </div>
  );
}

function WatchSettings() {
  const client = useQueryClient();
  const watch = useQuery({ queryKey: ["ai-watch"], queryFn: api.aiWatch });
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const [draft, setDraft] = useState<AiWatch | null>(null);
  const value = draft ?? watch.data ?? null;
  const save = useMutation({
    mutationFn: (v: AiWatch) => api.setAiWatch(v),
    onSuccess: () => {
      setDraft(null);
      void client.invalidateQueries({ queryKey: ["ai-watch"] });
    },
  });
  if (!value) return null;
  const set = (patch: Partial<AiWatch>) => setDraft({ ...value, ...patch });
  return (
    <section aria-label="AI watch" className={SECTION}>
      <div className={HEAD}>
        <h2 className="text-base font-semibold">AI watch</h2>
        <p className="text-sm text-text-muted">
          Alerts the first time an AI service or MCP server that is not approved is seen for a
          person or machine, and when sensitive data is sent to Claude Code. Summaries only.
        </p>
      </div>
      <div className="flex flex-col gap-2 px-3 py-3 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={value.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
          />
          <span className="font-semibold">Watch for new AI use</span>
        </label>
        <label className="flex items-center gap-2 pl-6">
          <input
            type="checkbox"
            checked={value.include_unreviewed}
            onChange={(e) => set({ include_unreviewed: e.target.checked })}
          />
          <span>Also alert on Unreviewed services and servers (not only Not approved)</span>
        </label>
        <label className="flex items-center gap-2 pl-6">
          <input
            type="checkbox"
            checked={value.sensitive}
            onChange={(e) => set({ sensitive: e.target.checked })}
          />
          <span>
            Alert on sensitive-data signals (keys, card numbers, SSNs), unless the service is set to
            allow Confidential data
          </span>
        </label>
        <label className="flex items-center gap-2 pl-6">
          <input
            type="checkbox"
            checked={value.agents ?? false}
            onChange={(e) => set({ agents: e.target.checked })}
          />
          <span>
            Alert when an AI agent changes: a new tool, MCP server, or model, or a busy hour
          </span>
        </label>
        <div className="flex flex-col gap-1 pl-6">
          <span className="text-text-secondary">Send to</span>
          {(targets.data ?? []).length === 0 ? (
            <span className="text-text-muted">
              No alert targets yet; add one under Alert targets. Sightings are still recorded in the
              audit log.
            </span>
          ) : null}
          {(targets.data ?? []).map((t) => (
            <label key={t.target_id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={value.target_ids.includes(t.target_id)}
                onChange={() =>
                  set({
                    target_ids: value.target_ids.includes(t.target_id)
                      ? value.target_ids.filter((x) => x !== t.target_id)
                      : [...value.target_ids, t.target_id],
                  })
                }
              />
              <span>{t.name}</span>
            </label>
          ))}
        </div>
        {save.isError ? (
          <p role="alert" className="text-danger">
            {message(save.error)}
          </p>
        ) : null}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!draft || save.isPending}
            onClick={() => draft && save.mutate(draft)}
            className="h-8 rounded bg-accent px-4 font-semibold text-white hover:brightness-110 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {draft ? (
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="h-8 rounded border border-border-strong px-3"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function McpRules() {
  const client = useQueryClient();
  const rules = useQuery({ queryKey: ["ai-mcp-rules"], queryFn: api.aiMcpRules });
  const [pattern, setPattern] = useState("");
  const [status, setStatus] = useState<"approved" | "not_approved">("approved");
  const change = useMutation({
    mutationFn: (v: { pattern: string; status: "approved" | "not_approved" | null }) =>
      api.setAiMcpRule(v.pattern, v.status),
    onSuccess: () => {
      setPattern("");
      void client.invalidateQueries({ queryKey: ["ai-mcp-rules"] });
      void client.invalidateQueries({ queryKey: ["ai-usage"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (pattern.trim()) change.mutate({ pattern: pattern.trim(), status });
  };
  return (
    <section aria-label="MCP server rules" className={SECTION}>
      <div className={HEAD}>
        <h2 className="text-base font-semibold">MCP server rules</h2>
        <p className="text-sm text-text-muted">
          A server name, or a prefix ending in * (for example github or internal-*). Exact names win
          over prefixes. Servers with no rule are Unreviewed.
        </p>
      </div>
      <form
        onSubmit={submit}
        aria-label="Add MCP rule"
        className="flex flex-wrap items-center gap-2 px-3 py-3 text-sm"
      >
        <label htmlFor="mcp-pattern" className="sr-only">
          Server name or prefix
        </label>
        <input
          id="mcp-pattern"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          placeholder="github or internal-*"
          maxLength={121}
          className="h-8 min-w-0 flex-[1_1_200px] rounded border border-border-strong bg-inset px-2 font-mono"
        />
        <select
          aria-label="Rule"
          value={status}
          onChange={(e) => setStatus(e.target.value as "approved" | "not_approved")}
          className="h-8 rounded border border-border-strong bg-surface px-2"
        >
          <option value="approved">Approved</option>
          <option value="not_approved">Not approved</option>
        </select>
        <button
          type="submit"
          disabled={change.isPending}
          className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Add rule
        </button>
        {change.isError ? (
          <span role="alert" className="text-danger">
            {message(change.error)}
          </span>
        ) : null}
      </form>
      {(rules.data ?? []).length ? (
        <ul className="border-t border-border text-sm">
          {(rules.data ?? []).map((r) => (
            <li
              key={r.pattern}
              className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-1.5 last:border-0"
            >
              <span className="font-mono">{r.pattern}</span>
              <StatusBadge status={r.status} />
              <button
                type="button"
                onClick={() => change.mutate({ pattern: r.pattern, status: null })}
                aria-label={`Remove rule ${r.pattern}`}
                className="ml-auto text-text-secondary hover:text-text"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function CatalogList() {
  const client = useQueryClient();
  const catalog = useQuery({ queryKey: ["ai-catalog"], queryFn: api.aiCatalog });
  const [form, setForm] = useState({ id: "", name: "", vendor: "", kind: "chat", domains: "" });
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["ai-catalog"] });
    void client.invalidateQueries({ queryKey: ["ai-usage"] });
  };
  const status = useMutation({
    mutationFn: (v: { id: string; status: "approved" | "not_approved" | "unreviewed" }) =>
      api.setAiServiceStatus(v.id, v.status),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: () =>
      api.addAiService({
        ...form,
        domains: form.domains.split(/[\s,]+/).filter(Boolean),
      }),
    onSuccess: () => {
      setForm({ id: "", name: "", vendor: "", kind: "chat", domains: "" });
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: api.deleteAiService, onSuccess: refresh });
  return (
    <section aria-label="AI service catalog" className={SECTION}>
      <div className={HEAD}>
        <h2 className="text-base font-semibold">AI service catalog</h2>
        <p className="text-sm text-text-muted">
          Every service the network view recognizes, by domain. Mark them here before they show up,
          or add your own (an internal model gateway, a vendor not listed).
        </p>
      </div>
      <form
        aria-label="Add AI service"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
        className="grid gap-2 px-3 py-3 text-sm md:grid-cols-[repeat(5,minmax(0,1fr))_auto]"
      >
        {(
          [
            ["id", "Id (internal_llm)"],
            ["name", "Name"],
            ["vendor", "Vendor"],
          ] as const
        ).map(([key, ph]) => (
          <input
            key={key}
            aria-label={ph}
            placeholder={ph}
            value={form[key]}
            onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
            className="h-8 min-w-0 rounded border border-border-strong bg-inset px-2"
          />
        ))}
        <select
          aria-label="Kind"
          value={form.kind}
          onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
          className="h-8 rounded border border-border-strong bg-surface px-2"
        >
          {[
            "chat",
            "api",
            "coding",
            "agent_platform",
            "mcp_registry",
            "image",
            "meetings",
            "writing",
          ].map((k) => (
            <option key={k} value={k}>
              {k.replace("_", " ")}
            </option>
          ))}
        </select>
        <input
          aria-label="Domains"
          placeholder="Domains (llm.corp.example)"
          value={form.domains}
          onChange={(e) => setForm((f) => ({ ...f, domains: e.target.value }))}
          className="h-8 min-w-0 rounded border border-border-strong bg-inset px-2 font-mono"
        />
        <button
          type="submit"
          disabled={add.isPending}
          className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Add service
        </button>
        {add.isError ? (
          <span role="alert" className="text-danger md:col-span-6">
            {message(add.error)}
          </span>
        ) : null}
      </form>
      <div className="overflow-x-auto border-t border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-text-secondary">
              <th className="px-3 py-2 text-left font-semibold">Service</th>
              <th className="px-3 py-2 text-left font-semibold">Domains</th>
              <th className="px-3 py-2 text-left font-semibold">Review</th>
              <th className="px-3 py-2" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {(catalog.data ?? []).map((s) => (
              <tr key={s.id} className="border-b border-border last:border-0">
                <td className="px-3 py-1.5">
                  <span className="font-semibold">{s.name}</span>
                  <span className="text-text-muted"> · {s.vendor || "custom"}</span>
                </td>
                <td className="px-3 py-1.5 font-mono text-text-secondary">
                  {s.domains.join(", ")}
                </td>
                <td className="px-3 py-1.5">
                  <StatusPicker
                    label={s.name}
                    value={s.status}
                    onChange={(v) => status.mutate({ id: s.id, status: v })}
                  />
                </td>
                <td className="px-3 py-1.5 text-right">
                  {s.custom ? (
                    <button
                      type="button"
                      onClick={() => remove.mutate(s.id)}
                      aria-label={`Remove ${s.name}`}
                      className="text-text-secondary hover:text-text"
                    >
                      Remove
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
