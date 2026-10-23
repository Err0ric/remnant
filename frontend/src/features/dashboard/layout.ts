import type { Dashboard, DashboardLayout } from "@/lib/api";

/** The dashboard as sections in order (no section first), each with its panels in order.
 * Sections with no panels are kept, so a new section can be filled by dragging. */
export function layoutOf(d: Dashboard): DashboardLayout {
  const order = [...d.panels].sort((a, b) => a.position - b.position);
  const names = ["", ...d.sections];
  for (const p of order) if (!names.includes(p.section)) names.push(p.section);
  return names.map((name) => ({
    name,
    schedule_ids: order.filter((p) => p.section === name).map((p) => p.schedule_id),
  }));
}

function without(layout: DashboardLayout, id: string): DashboardLayout {
  return layout.map((s) => ({ ...s, schedule_ids: s.schedule_ids.filter((x) => x !== id) }));
}

/** Put a panel into a section at an index (the end when omitted). */
export function placed(
  layout: DashboardLayout,
  id: string,
  section: string,
  index?: number,
): DashboardLayout {
  const out = without(layout, id);
  let target = out.find((s) => s.name === section);
  if (!target) {
    target = { name: section, schedule_ids: [] };
    out.push(target);
  }
  const at = index === undefined ? target.schedule_ids.length : Math.max(0, index);
  target.schedule_ids.splice(Math.min(at, target.schedule_ids.length), 0, id);
  return out;
}

/** Move a panel one place earlier or later within its section. */
export function stepped(layout: DashboardLayout, id: string, step: -1 | 1): DashboardLayout {
  return layout.map((s) => {
    const i = s.schedule_ids.indexOf(id);
    const j = i + step;
    if (i < 0 || j < 0 || j >= s.schedule_ids.length) return s;
    const ids = [...s.schedule_ids];
    [ids[i], ids[j]] = [ids[j] as string, ids[i] as string];
    return { ...s, schedule_ids: ids };
  });
}

/** Move a named section up or down (no section always stays first). */
export function sectionStepped(
  layout: DashboardLayout,
  name: string,
  step: -1 | 1,
): DashboardLayout {
  const out = [...layout];
  const i = out.findIndex((s) => s.name === name);
  const j = i + step;
  if (i <= 0 || j <= 0 || j >= out.length) return layout;
  [out[i], out[j]] = [out[j] as DashboardLayout[number], out[i] as DashboardLayout[number]];
  return out;
}

/** Delete a section: its panels go to no section, at the end. */
export function sectionRemoved(layout: DashboardLayout, name: string): DashboardLayout {
  const gone = layout.find((s) => s.name === name);
  if (!gone || !name) return layout;
  return layout
    .filter((s) => s.name !== name)
    .map((s) =>
      s.name === "" ? { ...s, schedule_ids: [...s.schedule_ids, ...gone.schedule_ids] } : s,
    );
}

export function sectionAdded(layout: DashboardLayout, name: string): DashboardLayout {
  return layout.some((s) => s.name === name) ? layout : [...layout, { name, schedule_ids: [] }];
}
