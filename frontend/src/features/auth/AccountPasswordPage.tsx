import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AuthCard } from "./AuthCard";
import { Field } from "./Field";
import { FormError } from "./FormError";
import { ApiError, api } from "@/lib/api";

const MIN_PASSWORD = 12;

/** Landing page for invite and reset links: the user chooses their own password. */
export function AccountPasswordPage() {
  const [token] = useState(() => window.location.hash.replace(/^#/, ""));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
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

  return (
    <AuthCard title="Set your password">
      {token ? (
        <form className="mt-3 flex flex-col gap-4" onSubmit={submit} noValidate>
          <p className="text-sm text-text-secondary">
            Choose the password you will use to sign in. This link works once.
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
      ) : (
        <p className="mt-3 text-sm text-text-secondary">
          This page needs the link an administrator sent you. Ask them for a new one if it has
          expired.
        </p>
      )}
    </AuthCard>
  );
}
