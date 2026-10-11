interface ParserMixProps {
  /** template_id -> stored events, for one Automatic source. */
  counts: Map<string, number>;
}

/** Which parsers an Automatic source's lines went to, so an admin can see routing work. */
export function ParserMix({ counts }: ParserMixProps) {
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  const shown = entries.slice(0, 5);
  const rest = entries.slice(5).reduce((n, [, c]) => n + c, 0);
  return (
    <p className="mt-0.5 text-sm text-text-muted">
      Parsed by{" "}
      {shown.map(([id, n], i) => (
        <span key={id}>
          {i > 0 ? " · " : ""}
          <span className="font-mono">{id}</span> {n.toLocaleString()}
        </span>
      ))}
      {rest > 0 ? ` · ${rest.toLocaleString()} more` : ""}
    </p>
  );
}
