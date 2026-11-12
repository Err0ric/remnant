import { When } from "@/components/When";

interface LateRowProps {
  late: boolean | undefined;
  start: string | null | undefined;
  end: string | null | undefined;
}

/** On an alert's page: it was found when the rules ran over events parsed again after
 * their source's template was missing (D241), and the time range of those events. */
export function LateRow({ late, start, end }: LateRowProps) {
  if (!late) return null;
  return (
    <>
      <dt className="text-text-muted">Late detection</dt>
      <dd className="text-text-secondary">
        Rules ran over reparsed events from <When iso={start} /> to <When iso={end} />
      </dd>
    </>
  );
}
