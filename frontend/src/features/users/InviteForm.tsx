import { rememberFirstAdminLink } from "@/features/auth/firstAdminLink";
import { accountLink } from "@/lib/links";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type Role } from "@/lib/api";
import { ROLE_HELP, ROLE_LABEL } from "./roles";

const USERNAME = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$/;

interface InviteFormProps {
  onInvited: (username: string, token: string) => void;
  onCancel: () => void;
  /** No accounts exist yet: only an administrator can be first (ADR-0004). */
  firstAccount?: boolean;
}

export function InviteForm({ onInvited, onCancel, firstAccount = false }: InviteFormProps) {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<Role>(firstAccount ? "admin" : "analyst");
  const [localError, setLocalError] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: api.inviteUser,
    onSuccess: async (res) => {
      if (firstAccount) {
        // Open mode ends with this account; keep the link for the sign-in page.
        rememberFirstAdminLink({
          username: res.user.username,
          link: accountLink(res.invite_token),
        });
      }
      await client.invalidateQueries({ queryKey: ["users"] });
      onInvited(res.user.username, res.invite_token);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!USERNAME.test(username)) {
      setLocalError("Username: letters, digits, and . _ @ - (up to 64 characters).");
      return;
    }
    setLocalError(null);
    invite.mutate({ username, role });
  };

  return (
    <form
      aria-label="Invite user"
      onSubmit={submit}
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">Invite user</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Username"
          help="What they type to sign in. Use one account per person; there are no shared logins."
          value={username}
          onChange={(e) => setUsername(e.target.value.trim())}
          autoComplete="off"
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="invite-role" className="text-sm font-semibold">
            Role
          </label>
          <select
            id="invite-role"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
          >
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
          <p className="text-sm text-text-muted">{ROLE_HELP[role]}</p>
        </div>
      </div>
      <div className="mt-3">
        <FormError
          message={localError ?? (invite.error instanceof ApiError ? invite.error.message : null)}
        />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={invite.isPending}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {invite.isPending ? "Creating link" : "Create invite link"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-8 rounded border border-border-strong px-4 text-sm hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
