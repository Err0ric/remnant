import { EmptyState } from "@/components/EmptyState";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type AlertTarget } from "@/lib/api";
import { SigningKey } from "./SigningKey";
import { TargetForm } from "./TargetForm";

const KIND: Record<AlertTarget["kind"], string> = {
  email: "Email",
  slack: "Slack",
  teams: "Teams",
  webhook: "Webhook",
};

function health(t: AlertTarget): { text: string; tone: string } {
  if (t.failing)
    return { text: `Failing (${t.consecutive_failures} in a row)`, tone: "text-danger" };
  if (t.consecutive_failures) return { text: "Last send failed", tone: "text-warn" };
  if (t.last_sent_at)
    return { text: `Sent ${t.last_sent_at.slice(0, 16).replace("T", " ")}`, tone: "" };
  return { text: "Not used yet", tone: "text-text-muted" };
}

/** Configuration > Alert targets (ADR-0007): admins add, test, and remove destinations. */
export function AlertTargetsPage() {
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [key, setKey] = useState<{ name: string; key: string } | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [confirm, setConfirm] = useState<string | null>(null);
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const list = targets.data ?? [];
  const refresh = () => client.invalidateQueries({ queryKey: ["alert-targets"] });
  const test = useMutation({
    mutationFn: (id: string) => api.testAlertTarget(id),
    onSuccess: async (r, id) => {
      setResults((prev) => ({ ...prev, [id]: r }));
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteAlertTarget(id),
    onSuccess: async () => {
      setConfirm(null);
      await refresh();
    },
  });
  const failure = [targets.error, test.error, remove.error].find(Boolean);
  const btn = "rounded px-2 py-0.5 hover:bg-surface-head disabled:opacity-40";

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Alert targets"
        count={`${list.length} ${list.length === 1 ? "target" : "targets"}`}
        primary={{ label: "Add target", onClick: () => setAdding(true), disabled: adding }}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        <p className="max-w-3xl text-sm text-text-secondary">
          Alerts carry a summary and a link back, never log content.
        </p>
        {key ? (
          <SigningKey name={key.name} signingKey={key.key} onDone={() => setKey(null)} />
        ) : null}
        {adding ? (
          <TargetForm
            onCancel={() => setAdding(false)}
            onCreated={(name, signingKey) => {
              setAdding(false);
              if (signingKey) setKey({ name, key: signingKey });
            }}
          />
        ) : null}
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure instanceof ApiError ? failure.message : "That did not work"}
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="overflow-x-auto">
            <table aria-label="Alert targets" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Goes to</th>
                  <th className="px-3 py-2">Health</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((t) => {
                  const h = health(t);
                  const r = results[t.target_id];
                  return (
                    <tr
                      key={t.target_id}
                      className="border-b border-border align-top last:border-0"
                    >
                      <td className="px-3 py-2 font-semibold">{t.name}</td>
                      <td className="px-3 py-2">{KIND[t.kind]}</td>
                      <td className="px-3 py-2">
                        <span className="font-mono">{t.display}</span>
                        {t.recipients.length ? (
                          <div className="text-text-muted">{t.recipients.join(", ")}</div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <span className={h.tone}>{h.text}</span>
                        {t.last_error ? (
                          <div className="text-text-secondary">{t.last_error}</div>
                        ) : null}
                        {r ? (
                          <div role="status" className={r.ok ? "text-ok" : "text-danger"}>
                            Test: {r.detail}
                          </div>
                        ) : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        <button
                          type="button"
                          className={btn}
                          disabled={test.isPending}
                          onClick={() => test.mutate(t.target_id)}
                          aria-label={`Send a test to ${t.name}`}
                        >
                          Send test
                        </button>
                        {confirm === t.target_id ? (
                          <>
                            <button
                              type="button"
                              className={`${btn} font-semibold text-danger`}
                              onClick={() => remove.mutate(t.target_id)}
                            >
                              Confirm delete
                            </button>
                            <button type="button" className={btn} onClick={() => setConfirm(null)}>
                              Keep
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className={btn}
                            onClick={() => setConfirm(t.target_id)}
                            aria-label={`Delete ${t.name}`}
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {list.length === 0 && targets.isSuccess ? (
            <EmptyState
              kind="not-set-up"
              title="No alert targets."
              detail="Add Slack, Teams, email, or a webhook."
            />
          ) : null}
        </section>
      </div>
    </div>
  );
}
