import { PageHeader } from "@/components/shell/PageHeader";
import type { User } from "@/lib/api";
import { TokensSection } from "./TokensSection";

interface AccountPageProps {
  me: User;
}

export function AccountPage({ me }: AccountPageProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader crumbs={["Home", "Your account"]} title="Your account" />
      <div className="flex flex-col gap-3 px-5 py-3">
        <p className="text-sm text-text-secondary">
          Signed in as <span className="font-mono text-text">{me.username}</span> ({me.role}). To
          change your password, ask an administrator for a reset link.
        </p>
        <TokensSection />
      </div>
    </div>
  );
}
