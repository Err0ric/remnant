import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AuthCard } from "./AuthCard";
import { Field } from "./Field";
import { FormError } from "./FormError";
import { ApiError, api, type SignedIn } from "@/lib/api";

const MIN_PASSWORD = 12;

interface SetupPageProps {
  onDone: (signedIn: SignedIn) => void;
}

function tokenFromHash(): string {
  return window.location.hash.replace(/^#/, "");
}

export function SetupPage({ onDone }: SetupPageProps) {
  const [token] = useState(tokenFromHash);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const setup = useMutation({
    mutationFn: api.setup,
    onSuccess: (signedIn) => {
      // Drop the spent token from the address bar and history.
      window.history.replaceState(null, "", "/");
      onDone(signedIn);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setLocalError(`Use at least ${MIN_PASSWORD} characters.`);
      return;
    }
    if (password !== confirm) {
      setLocalError("The passwords do not match.");
      return;
    }
    setLocalError(null);
    setup.mutate({ token, username, password });
  };

  const serverError =
    setup.error instanceof ApiError
      ? setup.error.code === "setup_invalid"
        ? "This setup link is invalid, expired, or already used. Restart the server to print a new one."
        : setup.error.message
      : null;

  return (
    <AuthCard title="Create the administrator account">
      <p className="mb-5 text-sm text-text-secondary">
        You are creating the administrator account for this installation. This account manages
        users, sources, and access for everyone else.
      </p>
      {token ? (
        <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
          <Field
            label="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <Field
            label="Password"
            type="password"
            autoComplete="new-password"
            help={`At least ${MIN_PASSWORD} characters. A passphrase works well.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Field
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          <FormError message={localError ?? serverError} />
          <button
            type="submit"
            disabled={setup.isPending}
            className="h-9 rounded bg-accent text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            {setup.isPending ? "Creating account" : "Create administrator account"}
          </button>
        </form>
      ) : (
        <p className="rounded border border-border bg-inset px-3 py-2.5 text-sm text-text-secondary">
          Open the one-time setup link printed in the server log. It looks like{" "}
          <span className="font-mono text-sm">https://your-server:8080/setup#...</span> and works
          once, for 30 minutes. If a sign-in page came first, the link lost its code on the way
          back: open the link again now that you&apos;re signed in. Nothing has been used up.
        </p>
      )}
    </AuthCard>
  );
}
