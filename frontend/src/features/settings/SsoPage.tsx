import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
import { LoadFailed } from "@/components/LoadFailed";
import { since } from "@/features/overview/time";

const STATUS = {
  off: { text: "Off", tone: "text-text-secondary" },
  on: { text: "On", tone: "text-ok" },
  misconfigured: { text: "Not working", tone: "text-warn" },
} as const;

function Copy({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => setDone(true))
          .catch(() => setDone(false));
      }}
      className="text-sm text-accent-text hover:underline"
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/** Settings > Single sign-on (F64): the OIDC setup is server-side (ADR-0013, the secret
 * in the environment); this page says whether it works, what it uses, the redirect URI to
 * give the identity provider, the variables to set, and who is bound to an identity. */
export function SsoPage() {
  const q = useQuery({ queryKey: ["sso-settings"], queryFn: api.ssoSettings });
  const test = useMutation({ mutationFn: api.ssoTest });
  const d = q.data;
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Settings", "Single sign-on"]} title="Single sign-on" />
      <div className="flex max-w-4xl flex-col gap-4 p-5 text-sm">
        {q.isLoading ? (
          <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />
        ) : q.isError ? (
          <LoadFailed
            what="single sign-on"
            error={q.error}
            onRetry={() => void q.refetch()}
            retrying={q.isFetching}
          />
        ) : d ? (
          <>
            <section
              aria-label="Status"
              className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4"
            >
              <p>
                <span className="font-semibold">Status: </span>
                <span className={cn("font-semibold", STATUS[d.status].tone)}>
                  {STATUS[d.status].text}
                </span>
              </p>
              {d.problem ? <p className="text-warn">{d.problem}</p> : null}
              <p className="text-text-secondary">
                Single sign-on is set on the server, not here: the client secret stays in the
                server's environment. People are invited first; the invite link binds their
                identity. With it on, {d.password_login === "everyone" ? "everyone" : "only admins"}{" "}
                can still sign in with a password.
              </p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  disabled={d.status === "off" || test.isPending}
                  onClick={() => test.mutate()}
                  className="h-8 rounded border border-border px-3 hover:bg-surface-head disabled:opacity-60"
                >
                  Test sign-in
                </button>
                {test.data ? (
                  <span role="status" className={test.data.ok ? "text-ok" : "text-warn"}>
                    {test.data.message}
                  </span>
                ) : null}
              </div>
            </section>
            <section
              aria-label="Setup in use"
              className="rounded-card border border-border bg-surface p-4"
            >
              <h2 className="mb-2 text-base font-semibold">Setup in use</h2>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
                <dt className="text-text-secondary">Issuer</dt>
                <dd className="break-all font-mono">{d.issuer ?? "Not set"}</dd>
                <dt className="text-text-secondary">Client ID</dt>
                <dd className="break-all font-mono">{d.client_id ?? "Not set"}</dd>
                <dt className="text-text-secondary">Client secret</dt>
                <dd className="text-text-secondary">Set in the environment; never shown</dd>
                <dt className="text-text-secondary">Required groups</dt>
                <dd className="font-mono">{d.required_groups.join(", ") || "None"}</dd>
                <dt className="text-text-secondary">Redirect URI</dt>
                <dd className="flex flex-wrap items-center gap-2">
                  {d.redirect_uri ? (
                    <>
                      <span className="break-all font-mono">{d.redirect_uri}</span>
                      <Copy value={d.redirect_uri} />
                    </>
                  ) : (
                    <span className="text-warn">Set APP__SERVER__PUBLIC_URL first</span>
                  )}
                </dd>
              </dl>
              <p className="mt-2 text-text-secondary">
                In Entra: App registrations, your app, Authentication, add a Web platform with this
                redirect URI.
              </p>
            </section>
            <section
              aria-label="Variables to set"
              className="overflow-hidden rounded-card border border-border bg-surface"
            >
              <h2 className="border-b border-border bg-surface-head px-3 py-2 text-base font-semibold">
                Variables to set
              </h2>
              <table className="w-full">
                <tbody>
                  {d.env.map((e) => (
                    <tr key={e.name} className="border-b border-border last:border-0">
                      <td className="px-3 py-1.5 font-mono">{e.name}</td>
                      <td className="px-3 py-1.5 text-text-secondary">{e.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section
              aria-label="Bound identities"
              className="overflow-hidden rounded-card border border-border bg-surface"
            >
              <h2 className="border-b border-border bg-surface-head px-3 py-2 text-base font-semibold">
                People bound to an identity
              </h2>
              {d.bound.length === 0 ? (
                <p className="px-3 py-3 text-text-secondary">
                  Nobody yet. Invite someone on{" "}
                  <button
                    type="button"
                    onClick={() => navigate("users")}
                    className="text-accent-text hover:underline"
                  >
                    Users and access
                  </button>
                  ; their invite link binds their identity on first sign-in.
                </p>
              ) : (
                <table className="w-full">
                  <tbody>
                    {d.bound.map((b) => (
                      <tr key={b.user_id} className="border-b border-border last:border-0">
                        <td className="px-3 py-1.5">{b.username}</td>
                        <td className="px-3 py-1.5 text-text-secondary">{b.role}</td>
                        <td className="px-3 py-1.5 text-text-secondary">
                          {b.disabled
                            ? "Disabled"
                            : b.last_login_at
                              ? `Signed in ${since(b.last_login_at, new Date().toISOString())}`
                              : "Not signed in yet"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
