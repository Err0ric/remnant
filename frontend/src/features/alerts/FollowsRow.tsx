import { navigate, pathFor } from "@/lib/route";

interface FollowsRowProps {
  follows: string | null | undefined;
}

/** The closed alert this one follows (ADR-0049 0c): a vendor alert that rose after its
 * alert was closed opens a new one, and the closed one keeps its decision. */
export function FollowsRow({ follows }: FollowsRowProps) {
  if (!follows) return null;
  const section = `item=${encodeURIComponent(follows)}`;
  return (
    <>
      <dt className="text-text-muted">Follows</dt>
      <dd>
        <a
          href={`${pathFor("alerts")}#${section}`}
          onClick={(e) => {
            e.preventDefault();
            navigate("alerts", section);
          }}
          className="text-accent-text hover:underline"
        >
          Earlier alert, closed before this one rose
        </a>
      </dd>
    </>
  );
}
