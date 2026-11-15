import type { ReactNode } from "react";

interface CardActionProps {
  children: ReactNode;
  onClick: () => void;
  title?: string;
}

/** The one action at the top right of a card (DESIGN.md 7): "View all" when it opens the
 * full list of what the card shows, the page's name only when it leaves the card's subject.
 * A real button in the accent text color. */
export function CardAction({ children, onClick, title }: CardActionProps) {
  return (
    <button
      type="button"
      data-card-action=""
      onClick={onClick}
      title={title}
      className="whitespace-nowrap rounded-sm text-sm text-accent-text hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-focus-ring"
    >
      {children}
    </button>
  );
}
