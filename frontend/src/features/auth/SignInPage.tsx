import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AuthCard } from "./AuthCard";
import { Field } from "./Field";
import { FirstAdminLinkPanel } from "./FirstAdminLinkPanel";
import { firstAdminLink, forgetFirstAdminLink } from "./firstAdminLink";
import { FormError } from "./FormError";
import { SsoButton } from "./SsoButton";
import { ApiError, api, type SignedIn, type SsoState } from "@/lib/api";
import { ssoMessage, takeSsoCode } from "@/lib/sso";

interface SignInPageProps {
  onDone: (signedIn: SignedIn) => void;
  /** Shown above the form, for example when the last sign-out failed. */
  notice?: string | null;
  /** Single sign-on, when the server has it turned on. */
  sso?: SsoState | null;
}

export function SignInPage({ onDone, notice = null, sso = null }: SignInPageProps) {
  const [ssoCode] = useState(takeSsoCode);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState(firstAdminLink);
  const login = useMutation({
    mutationFn: api.login,
    onSuccess: (signed) => {
      forgetFirstAdminLink(); // used or not, it is never shown again after a sign-in
      onDone(signed);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ username, password });
  };

  const error =
    login.error instanceof ApiError
      ? login.error.code === "rate_limited"
        ? "Too many failed attempts. Wait a few minutes and try again."
        : login.error.message
      : null;
  const ssoError = ssoCode ? ssoMessage(ssoCode, sso?.label ?? "single sign-on") : null;

  return (
    <AuthCard title="Sign in">
      {invite ? (
        <FirstAdminLinkPanel
          value={invite}
          onDone={() => {
            forgetFirstAdminLink();
            setInvite(null);
          }}
        />
      ) : null}
      {notice ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {notice}
        </p>
      ) : null}
      {ssoError ? (
        <div className="mt-4">
          <FormError message={ssoError} />
        </div>
      ) : null}
      {sso ? (
        <div className="mt-4 flex flex-col gap-3">
          <SsoButton label={sso.label} />
          <div className="flex items-center gap-3 text-sm text-text-muted" aria-hidden="true">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>
          {sso.passwords_admins_only ? (
            <p className="text-sm text-text-muted">Password sign-in is for administrators.</p>
          ) : null}
        </div>
      ) : null}
      <form className="mt-4 flex flex-col gap-4" onSubmit={submit}>
        <Field
          label="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          autoFocus={!sso}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <FormError message={error} />
        <button
          type="submit"
          disabled={login.isPending}
          className={
            sso
              ? "h-9 rounded border border-border-strong bg-surface text-sm font-semibold text-text hover:bg-surface-head disabled:opacity-60"
              : "h-9 rounded bg-accent text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          }
        >
          {login.isPending ? "Signing in" : sso ? "Sign in with password" : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-sm text-text-muted">
        Forgot your password? Ask an administrator to reset it.
      </p>
    </AuthCard>
  );
}
