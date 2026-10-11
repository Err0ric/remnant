import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type ManagedUser, type Source, type SourceGroup } from "@/lib/api";

interface GroupEditorProps {
  group: SourceGroup;
  sources: Source[];
  users: ManagedUser[];
  onClose: () => void;
}

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

/** Edit which sources a group covers and who is in it. Saves replace the whole set. */
export function GroupEditor({ group, sources, users, onClose }: GroupEditorProps) {
  const client = useQueryClient();
  const [sourceIds, setSourceIds] = useState(group.source_ids);
  const [userIds, setUserIds] = useState(group.user_ids);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ["groups"] });

  const saveSources = useMutation({
    mutationFn: () => api.setGroupSources(group.group_id, sourceIds),
    onSuccess: refresh,
  });
  const saveMembers = useMutation({
    mutationFn: () => api.setGroupMembers(group.group_id, userIds),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteGroup(group.group_id),
    onSuccess: async () => {
      await refresh();
      onClose();
    },
  });

  const sourcesDirty = [...sourceIds].sort().join() !== [...group.source_ids].sort().join();
  const membersDirty = [...userIds].sort().join() !== [...group.user_ids].sort().join();
  const error = [saveSources.error, saveMembers.error, remove.error].find((e) => e) as
    Error | undefined;
  // Admins already see every source (ADR-0004); listing them here would mislead.
  const members = users.filter((u) => u.role !== "admin");

  return (
    <section
      aria-label={`Edit group ${group.name}`}
      className="rounded-card border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-base font-semibold">{group.name}</h3>
        {group.description ? (
          <span className="text-sm text-text-secondary">{group.description}</span>
        ) : null}
        <button type="button" onClick={onClose} className="ml-auto text-sm text-text-secondary">
          Close
        </button>
      </div>

      <div className="mt-3 grid gap-5 md:grid-cols-2">
        <fieldset>
          <legend className="text-sm font-semibold">Sources in this group</legend>
          <p className="mb-2 text-sm text-text-muted">Members can search these sources.</p>
          <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
            {sources.length === 0 ? (
              <span className="text-sm text-text-muted">No sources configured yet.</span>
            ) : null}
            {sources.map((s) => (
              <label key={s.source_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={sourceIds.includes(s.source_id)}
                  onChange={() => setSourceIds(toggle(sourceIds, s.source_id))}
                />
                <span className="font-mono">{s.source_id}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            disabled={!sourcesDirty || saveSources.isPending}
            onClick={() => saveSources.mutate()}
            className="mt-2 h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-40"
          >
            Save sources
          </button>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-semibold">Members</legend>
          <p className="mb-2 text-sm text-text-muted">
            Analysts and auditors. Admins see every source already.
          </p>
          <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
            {members.length === 0 ? (
              <span className="text-sm text-text-muted">No analysts or auditors yet.</span>
            ) : null}
            {members.map((u) => (
              <label key={u.user_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={userIds.includes(u.user_id)}
                  onChange={() => setUserIds(toggle(userIds, u.user_id))}
                />
                <span className="font-mono">{u.username}</span>
                <span className="text-text-muted">{u.role}</span>
                {u.disabled ? <span className="text-text-muted">(disabled)</span> : null}
              </label>
            ))}
          </div>
          <button
            type="button"
            disabled={!membersDirty || saveMembers.isPending}
            onClick={() => saveMembers.mutate()}
            className="mt-2 h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-40"
          >
            Save members
          </button>
        </fieldset>
      </div>

      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error instanceof ApiError ? error.message : "Could not save."}
        </p>
      ) : null}
      {saveSources.isSuccess || saveMembers.isSuccess ? (
        <p className="mt-3 text-sm text-text-secondary">Saved. Access changes apply immediately.</p>
      ) : null}

      <div className="mt-4 border-t border-border pt-3">
        {confirmDelete ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-text-secondary">
              Members lose access to these sources unless another group grants them.
            </span>
            <button
              type="button"
              onClick={() => remove.mutate()}
              className="rounded border border-danger px-2 py-0.5 text-danger hover:bg-sev-critical-bg"
            >
              Delete group
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(false)}
              className="px-2 py-0.5 text-text-secondary"
            >
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="text-sm text-text-secondary hover:text-text"
          >
            Delete group
          </button>
        )}
      </div>
    </section>
  );
}
