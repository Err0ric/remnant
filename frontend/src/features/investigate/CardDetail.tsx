import type { GraphCard } from "@/lib/api";

interface CardDetailProps {
  lane: string;
  card: GraphCard;
  canFollow: boolean;
  onOpenSearch: (sql: string) => void;
  onFollow: () => void;
  onClose: () => void;
}

/** The side panel for one card: what it stands for, with the way to its events. */
export function CardDetail({
  lane,
  card,
  canFollow,
  onOpenSearch,
  onFollow,
  onClose,
}: CardDetailProps) {
  return (
    <section
      aria-label="Selected card"
      className="flex w-full shrink-0 flex-col gap-3 border-t border-border bg-surface p-4 text-sm lg:w-64 lg:border-l lg:border-t-0"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs text-text-muted">
            {lane}
            {card.group ? ` · ${card.group}` : ""}
          </div>
          <div className="break-all font-mono text-base">{card.label}</div>
          {card.sublabel ? <div className="text-text-secondary">{card.sublabel}</div> : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="h-7 rounded border border-border-strong px-2 text-sm hover:bg-surface-head"
        >
          Close
        </button>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        <div>
          <dt className="text-xs text-text-muted">Events</dt>
          <dd className="font-mono text-lg tabular-nums">{card.events.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-muted">Rule matches</dt>
          <dd className="font-mono text-lg tabular-nums">{card.matches.toLocaleString()}</dd>
        </div>
      </dl>
      {card.badges.length ? (
        <ul className="flex flex-wrap gap-1">
          {card.badges.map((b) => (
            <li
              key={b}
              className="rounded-badge bg-sev-critical-bg px-2 py-px text-xs text-sev-critical-text"
            >
              {b}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-text-muted">The lit path shows everything this card connects to.</p>
      <div className="flex flex-wrap gap-2">
        {card.search_sql ? (
          <button
            type="button"
            onClick={() => onOpenSearch(card.search_sql as string)}
            className="h-8 rounded bg-accent px-3 text-sm font-semibold text-white hover:brightness-110"
          >
            Open in Search
          </button>
        ) : null}
        {canFollow ? (
          <button
            type="button"
            onClick={onFollow}
            className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
          >
            Investigate this
          </button>
        ) : null}
      </div>
    </section>
  );
}
