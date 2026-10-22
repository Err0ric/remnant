import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AuthCard } from "./AuthCard";
import { Field } from "./Field";
import { FormError } from "./FormError";
import { SsoButton } from "./SsoButton";
import { ApiError, api } from "@/lib/api";

const MIN_PASSWORD = 12;

/** Landing page for invite and reset links: the user chooses their own password. */
export function AccountPasswordPage() {
  const [token] = useState(() => window.location.hash.replace(/^#/, ""));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  // Own key: this page sits outside the sign-in gate and must not touch its cached state.
  const state = useQuery({ queryKey: ["auth-state", "link-page"], queryFn: api.authState });
  const sso = state.data?.sso ?? null;
  const [showPassword, setShowPassword] = useState(false);
  const save = useMutation({
    mutationFn: api.setPasswordFromLink,
    // Remove the spent token from the address bar and history either way.
    onSettled: () => window.history.replaceState(null, "", "/account"),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD)
      return setLocalError(`Use at least ${MIN_PASSWORD} characters.`);
    if (password !== confirm) return setLocalError("The passwords do not match.");
    setLocalError(null);
    save.mutate({ token, password });
  };

  if (save.isSuccess) {
    return (
      <AuthCard title="Password set">
        <p className="mb-4 text-sm text-text-secondary">
          You can now sign in with your new password.
        </p>
        <a href="/" className="text-sm font-semibold text-accent-text">
          Go to sign in
        </a>
      </AuthCard>
    );
  }

  const serverError =
    save.error instanceof ApiError
      ? save.error.code === "rate_limited"
        ? "Too many attempts. Wait a few minutes and try again."
        : save.error.message
      : null;

  const passwordForm = !sso || showPassword;

  return (
    <AuthCard
      title={
        !token
          ? "Open your link again"
          : sso
            ? "Finish setting up your account"
            : "Set your password"
      }
    >
      {token && sso ? (
        <div className="mt-3 flex flex-col gap-3">
          <p className="text-sm text-text-secondary">
            Sign in with {sso.label} to finish. Your {sso.label} account becomes how you sign in
            here. This link works once.
          </p>
          <SsoButton label={sso.label} linkToken={token} />
          {sso.passwords_admins_only && !showPassword ? (
            <button
              type="button"
              onClick={() => setShowPassword(true)}
              className="self-start text-sm text-accent-text hover:underline"
            >
              Administrator? Set a password instead
            </button>
          ) : null}
        </div>
      ) : null}
      {token && passwordForm ? (
        <form className="mt-3 flex flex-col gap-4" onSubmit={submit} noValidate>
          <p className="text-sm text-text-secondary">
            {sso
              ? "Administrators keep a password for when single sign-on is unavailable."
              : "Choose the password you will use to sign in. This link works once."}
          </p>
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            help={`At least ${MIN_PASSWORD} characters. A passphrase works well.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Field
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <FormError message={localError ?? serverError} />
          <button
            type="submit"
            disabled={save.isPending}
            className="h-9 rounded bg-accent text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            {save.isPending ? "Saving" : "Set password"}
          </button>
        </form>
      ) : null}
      {!token ? (
        <div role="status" className="mt-3 flex flex-col gap-2 text-sm text-text-secondary">
          {/* A forward-auth proxy (Authelia, oauth2-proxy) drops the part after `#` when it
              sends the browser back from its login, so the code never reaches this page. The
              code stays in the fragment so it is not written to proxy logs. Nothing is spent:
              a link is only used up when a password is set or a single sign-on link finishes. */}
          <p className="text-text">
            This link lost its code during sign-in. Open the invite link again now that you&apos;re
            signed in.
          </p>
          <p>
            Opened this page without a link? Ask an administrator for one. Links work once and
            expire after 24 hours.
          </p>
        </div>
      ) : null}
    </AuthCard>
  );
}
