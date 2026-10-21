import { useMutation } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { goToSso } from "@/lib/sso";
import { FormError } from "./FormError";

interface SsoButtonProps {
  label: string;
  /** Invite or reset link this sign-in finishes (binds the account to the identity). */
  linkToken?: string;
  /** Primary when it is the main way in; secondary next to a password form. */
  primary?: boolean;
}

export function SsoButton({ label, linkToken, primary = true }: SsoButtonProps) {
  const start = useMutation({ mutationFn: () => goToSso(linkToken) });
  const error =
    start.error instanceof ApiError
      ? start.error.message
      : start.error
        ? "The sign-in service cannot be reached. Try again."
        : null;
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={start.isPending || start.isSuccess}
        className={
          primary
            ? "h-9 rounded bg-accent text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
            : "h-9 rounded border border-border-strong bg-surface text-sm font-semibold text-text hover:bg-surface-head disabled:opacity-60"
        }
      >
        {start.isPending || start.isSuccess ? `Opening ${label}` : `Continue with ${label}`}
      </button>
      <FormError message={error} />
    </div>
  );
}
