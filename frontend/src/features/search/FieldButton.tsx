interface FieldButtonProps {
  label: string;
  title: string;
  onClick: () => void;
}

/** A small action on one field of an expanded event. */
export function FieldButton({ label, title, onClick }: FieldButtonProps) {
  return (
    <button
      type="button"
      aria-label={title}
      title={title}
      onClick={onClick}
      className="h-5 min-w-5 rounded border border-border-strong px-1 text-xs leading-none text-text-secondary hover:bg-surface-head hover:text-text focus:opacity-100"
    >
      {label}
    </button>
  );
}
