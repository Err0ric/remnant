import { EmptyState } from "@/components/EmptyState";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { navigate } from "@/lib/route";
import { ApiError, api, type User } from "@/lib/api";
import { accountLink } from "@/lib/links";
import { AuditorSqlSection } from "./AuditorSqlSection";
import { GroupsSection } from "./GroupsSection";
import { InviteForm } from "./InviteForm";
import { OneTimeLink } from "./OneTimeLink";
import { UserRow } from "./UserRow";
import { SectionTitle } from "@/components/SectionTitle";

interface UsersPageProps {
  me: User | null;
}

interface Shown {
  title: string;
  username: string;
  token: string;
}

export function UsersPage({ me }: UsersPageProps) {
  const [inviting, setInviting] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const groups = useQuery({ queryKey: ["groups"], queryFn: api.groups });

  const groupsByUser = new Map<string, string[]>();
  for (const g of groups.data ?? []) {
    for (const id of g.user_ids) groupsByUser.set(id, [...(groupsByUser.get(id) ?? []), g.name]);
  }
  const list = users.data ?? [];

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Users and access"
        count={`${list.length} ${list.length === 1 ? "user" : "users"}`}
        primary={{
          label: "Invite user",
          onClick: () => {
            setShown(null);
            setInviting(true);
          },
          disabled: inviting,
        }}
      />
      <p className="px-5 pt-3 text-sm text-text-secondary">
        Sign-in with your identity provider is set up on{" "}
        <button
          type="button"
          onClick={() => navigate("sso")}
          className="text-accent-text hover:underline"
        >
          Single sign-on
        </button>
        .
      </p>
      <div className="flex flex-col gap-3 px-5 py-3">
        {shown ? (
          <OneTimeLink
            title={shown.title}
            username={shown.username}
            link={accountLink(shown.token)}
            onDone={() => setShown(null)}
          />
        ) : null}
        {inviting ? (
          <InviteForm
            firstAccount={me === null && users.data?.length === 0}
            onCancel={() => setInviting(false)}
            onInvited={(username, token) => {
              setInviting(false);
              setShown({ title: "Invite link", username, token });
            }}
          />
        ) : null}
        {users.isError ? (
          <p role="alert" className="text-sm text-danger">
            {users.error instanceof ApiError ? users.error.message : "Could not load users."}
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="border-b border-border bg-surface-head px-3 py-2">
            <SectionTitle>Users</SectionTitle>
          </div>
          <div className="overflow-x-auto">
            <table aria-label="Users" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-sm text-text-secondary">
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Source access</th>
                  <th className="px-3 py-2">Last sign-in</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((u) => (
                  <UserRow
                    key={u.user_id}
                    user={u}
                    groupNames={groupsByUser.get(u.user_id) ?? []}
                    isSelf={me?.user_id === u.user_id}
                    onResetLink={(username, token) =>
                      setShown({ title: "Reset link", username, token })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
          {list.length === 0 && !users.isPending ? (
            <EmptyState kind="not-set-up" title="No accounts yet." />
          ) : null}
        </section>
        <AuditorSqlSection />
        <GroupsSection />
      </div>
    </div>
  );
}
