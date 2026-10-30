/** While older days are re-checked for who had each address, their AI use shows without
 * people (owner, 2026-10-29). Says so, so a 0 is not read as nobody. */
export function PeoplePending({ pending, of }: { pending?: number; of?: number }) {
  if (!pending) return null;
  return (
    <p role="status" className="text-sm text-text-secondary">
      Rebuilding people for {pending.toLocaleString()} of {(of ?? pending).toLocaleString()}{" "}
      {(of ?? pending) === 1 ? "day" : "days"}: AI use on those days shows without people until it
      finishes.
    </p>
  );
}
