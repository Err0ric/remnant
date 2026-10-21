import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type ManagedUser, type Role } from "@/lib/api";
import { ROLE_LABEL } from "./roles";

interface UserRowProps {
  user: ManagedUser;
  groupNames: string[];
  isSelf: boolean;
  onResetLink: (username: string, token: string) => void;
}

function status(u: ManagedUser): { label: string; dot: string } {
  if (u.disabled) return { label: "Disabled", dot: "bg-border-strong" };
  if (u.pending) return { label: "Invite pending", dot: "bg-warn" };
  return { label: "Active", dot: "bg-ok" };
}

function when(value: string | null): string {
  return value ? `${value.slice(0, 16).replace("T", " ")} UTC` : "Never";
}

export function UserRow({ user, groupNames, isSelf, onResetLink }: UserRowProps) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ["users"] });
  const update = useMutation({
    mutationFn: (body: { role?: Role; disabled?: boolean }) => api.updateUser(user.user_id, body),
    onSuccess: async () => {
      setConfirming(false);
      await refresh();
    },
  });
  const signOut = useMutation({ mutationFn: () => api.signOutUser(user.user_id) });
  const reset = useMutation({
    mutationFn: () => api.resetUser(user.user_id),
    onSuccess: (res) => onResetLink(user.username, res.reset_token),
  });
  const s = status(user);
  const error =
    (update.error instanceof ApiError && update.error.message) ||
    (reset.error instanceof ApiError && reset.error.message) ||
    null;

  return (
    <>
      <tr className="border-b border-border align-top last:border-0">
        <td className="px-3 py-2.5">
          <span className="font-mono">{user.username}</span>
          {isSelf ? <span className="ml-2 text-sm text-text-muted">(you)</span> : null}
          {user.sso ? (
            <span
              className="ml-2 rounded-badge border border-border-strong px-1.5 text-xs text-text-secondary"
              title="Signs in with single sign-on"
            >
              SSO
            </span>
          ) : null}
        </td>
        <td className="px-3 py-2.5">
          <select
            aria-label={`Role for ${user.username}`}
            value={user.role}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ role: e.target.value as Role })}
            className="h-7 rounded border border-border-strong bg-inset px-1.5 text-sm text-text"
          >
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </td>
        <td className="whitespace-nowrap px-3 py-2.5">
          <span className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden="true" />
            {s.label}
          </span>
        </td>
        <td className="px-3 py-2.5 text-sm text-text-secondary">
          {user.role === "admin"
            ? "All sources"
            : groupNames.length
              ? groupNames.join(", ")
              : "None"}
        </td>
        <td className="whitespace-nowrap px-3 py-2.5 font-mono text-sm">
          {when(user.last_login_at)}
        </td>
        <td className="whitespace-nowrap px-3 py-2.5 text-right">
          {confirming ? (
            <span className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => update.mutate({ disabled: true })}
                className="rounded border border-danger px-2 py-0.5 text-danger hover:bg-sev-critical-bg"
              >
                Disable
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="px-2 py-0.5 text-text-secondary"
              >
                Keep
              </button>
            </span>
          ) : (
            <span className="flex items-center justify-end gap-1">
              <button
                type="button"
                onClick={() => reset.mutate()}
                disabled={user.disabled || reset.isPending}
                aria-label={`Reset link for ${user.username}`}
                className="px-2 py-0.5 text-text-secondary hover:text-text disabled:opacity-40"
              >
                {user.pending ? "New invite link" : "Reset link"}
              </button>
              {!user.pending && !user.disabled ? (
                <button
                  type="button"
                  onClick={() => signOut.mutate()}
                  disabled={signOut.isPending}
                  aria-label={`Sign out ${user.username} everywhere`}
                  title="End every browser session and CLI token of this user"
                  className="px-2 py-0.5 text-text-secondary hover:text-text disabled:opacity-40"
                >
                  {signOut.isSuccess ? "Signed out" : "Sign out everywhere"}
                </button>
              ) : null}
              {user.disabled ? (
                <button
                  type="button"
                  onClick={() => update.mutate({ disabled: false })}
                  aria-label={`Enable ${user.username}`}
                  className="px-2 py-0.5 text-text-secondary hover:text-text"
                >
                  Enable
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(true)}
                  aria-label={`Disable ${user.username}`}
                  className="px-2 py-0.5 text-text-secondary hover:text-text"
                >
                  Disable
                </button>
              )}
            </span>
          )}
        </td>
      </tr>
      {confirming || error ? (
        <tr className="border-b border-border">
          <td colSpan={6} className="px-3 pb-2.5 text-sm">
            {error ? (
              <span role="alert" className="text-danger">
                {error}
              </span>
            ) : (
              <span className="text-text-secondary">
                Disabling signs {user.username} out everywhere and revokes their CLI tokens. Their
                audit history is kept. You can enable the account again later.
              </span>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}
