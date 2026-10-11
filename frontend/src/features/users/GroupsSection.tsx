import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api } from "@/lib/api";
import { GroupEditor } from "./GroupEditor";
import { GroupSuggestions } from "./GroupSuggestions";

/** Source groups: the per-user access boundary (SPEC 3.6). Nothing is granted automatically. */
export function GroupsSection() {
  const client = useQueryClient();
  const groups = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources });
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const create = useMutation({
    mutationFn: api.createGroup,
    onSuccess: async (g) => {
      await client.invalidateQueries({ queryKey: ["groups"] });
      setCreating(false);
      setName("");
      setDescription("");
      setEditing(g.group_id);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate({ name: name.trim(), description });
  };

  const list = groups.data ?? [];
  const current = list.find((g) => g.group_id === editing);
  const userName = new Map((users.data ?? []).map((u) => [u.user_id, u.username]));

  return (
    <section className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Source groups</h2>
        <span className="text-sm text-text-muted">
          Analysts and auditors only see sources in their groups.
        </span>
        <button
          type="button"
          onClick={() => setCreating(true)}
          disabled={creating}
          className="ml-auto text-sm font-semibold text-accent-text disabled:opacity-40"
        >
          New group
        </button>
      </div>

      <div className="flex flex-col gap-3 p-3">
        {creating ? (
          <form aria-label="New group" onSubmit={submit} className="flex flex-col gap-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} />
              <Field
                label="Description"
                help="Optional, for example: firewalls and VPN"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <FormError message={create.error instanceof ApiError ? create.error.message : null} />
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={!name.trim() || create.isPending}
                className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
              >
                Create group
              </button>
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="h-8 rounded border border-border-strong px-4 text-sm hover:bg-surface-head"
              >
                Cancel
              </button>
            </div>
          </form>
        ) : null}

        <GroupSuggestions />

        {current ? (
          <GroupEditor
            key={current.group_id + current.source_ids.join() + current.user_ids.join()}
            group={current}
            sources={sources.data ?? []}
            users={users.data ?? []}
            onClose={() => setEditing(null)}
          />
        ) : null}

        {list.length === 0 && !groups.isPending ? (
          <p className="py-4 text-center text-sm text-text-secondary">
            No groups yet. Until you create one, analysts and auditors see no events.
          </p>
        ) : (
          <table aria-label="Source groups" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="py-2 pr-3 font-semibold">Group</th>
                <th className="py-2 pr-3 font-semibold">Sources</th>
                <th className="py-2 pr-3 font-semibold">Members</th>
                <th className="py-2" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((g) => (
                <tr key={g.group_id} className="border-b border-border align-top last:border-0">
                  <td className="py-2.5 pr-3 font-semibold">{g.name}</td>
                  <td className="py-2.5 pr-3 font-mono">{g.source_ids.join(", ") || "None"}</td>
                  <td className="py-2.5 pr-3 font-mono">
                    {g.user_ids.map((id) => userName.get(id) ?? id).join(", ") || "None"}
                  </td>
                  <td className="py-2.5 text-right">
                    <button
                      type="button"
                      aria-label={`Edit ${g.name}`}
                      onClick={() => setEditing(g.group_id)}
                      className="text-text-secondary hover:text-text"
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
