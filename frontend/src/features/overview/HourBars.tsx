interface HourBarsProps {
  counts: number[];
  max: number;
  label: string;
}

/** Events per hour, oldest on the left; one accent color, scaled to the shared `max`. */
export function HourBars({ counts, max, label }: HourBarsProps) {
  // Drawn in its own units and stretched to the cell's width.
  const width = Math.max(1, counts.length) * 10;
  const height = 28;
  const slot = width / Math.max(1, counts.length);
  const top = Math.max(1, max);
  return (
    <svg
      role="img"
      aria-label={label}
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="block min-w-[192px]"
    >
      <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} className="stroke-border" />
      {counts.map((n, i) =>
        n > 0 ? (
          <rect
            key={i}
            x={i * slot}
            y={height - Math.max(1, (n / top) * height)}
            width={slot - 2}
            height={Math.max(1, (n / top) * height)}
            className="fill-accent"
          />
        ) : null,
      )}
    </svg>
  );
}
