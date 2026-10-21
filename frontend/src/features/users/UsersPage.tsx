import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type User } from "@/lib/api";
import { accountLink } from "@/lib/links";
import { GroupsSection } from "./GroupsSection";
import { InviteForm } from "./InviteForm";
import { OneTimeLink } from "./OneTimeLink";
import { UserRow } from "./UserRow";

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
        crumbs={["Home", "Settings", "Users and access"]}
        title="Users and access"
        meta={`${list.length} ${list.length === 1 ? "user" : "users"}`}
        commands={
          <Command
            label="Invite user"
            primary
            onClick={() => {
              setShown(null);
              setInviting(true);
            }}
            disabled={inviting}
          />
        }
      />
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
            <h2 className="text-base font-semibold">Users</h2>
          </div>
          <div className="overflow-x-auto">
            <table aria-label="Users" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-sm text-text-secondary">
                  <th className="px-3 py-2 font-semibold">User</th>
                  <th className="px-3 py-2 font-semibold">Role</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Source access</th>
                  <th className="px-3 py-2 font-semibold">Last sign-in</th>
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
            <p className="px-3 py-8 text-center text-sm text-text-secondary">
              No accounts yet. This install runs without sign-in until the first administrator is
              invited.
            </p>
          ) : null}
        </section>
        <GroupsSection />
      </div>
    </div>
  );
}
