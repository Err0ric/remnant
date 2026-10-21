interface SparklineProps {
  values: (number | null)[];
  label: string;
}

const SLOTS = 30; // runs kept per schedule; fewer runs leave the left side empty

/** Simple bars of run counts, newest on the right; gaps for runs with no count. */
export function Sparkline({ values, label }: SparklineProps) {
  const width = 120;
  const height = 28;
  const max = Math.max(1, ...values.map((v) => v ?? 0));
  const slot = width / SLOTS;
  const bar = slot - 1;
  const offset = SLOTS - Math.min(values.length, SLOTS);
  values = values.slice(-SLOTS);
  return (
    <svg
      role="img"
      aria-label={label}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="shrink-0"
    >
      {values.map((v, i) =>
        v === null ? null : (
          <rect
            key={i}
            x={(offset + i) * slot}
            y={height - Math.max(1, (v / max) * height)}
            width={bar}
            height={Math.max(1, (v / max) * height)}
            className="fill-accent"
          />
        ),
      )}
    </svg>
  );
}
