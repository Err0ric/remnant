import { useEffect, useMemo, useRef, type ReactNode } from "react";

const KEY = "dashboard.heights";
/** Boxes apply from 1024 px, where sections lay out side by side; below that they stack. */
const FROM = 1024;

function stored(): Record<string, number> {
  try {
    const v: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
    return v && typeof v === "object" ? (v as Record<string, number>) : {};
  } catch {
    return {};
  }
}

/** The height a card's content takes, whatever its box: header and body children. */
function natural(card: Element): number {
  const [head, body] = [card.children[0], card.children[1]];
  let h = (head as HTMLElement | undefined)?.offsetHeight ?? 0;
  for (const c of Array.from(body?.children ?? [])) h += (c as HTMLElement).offsetHeight;
  return h + 2; // the card's top and bottom border
}

interface SlotProps {
  /** Which part and window: "identity:7d". */
  name: string;
  /** The box on a first visit: the part loaded with its lists full. */
  fallback: number;
  /** Its answer is shown (not the skeleton), so its height is worth keeping. */
  loaded: boolean;
  children: ReactNode;
}

/** A Dashboard part's box (fix list 2026-11-16 item 27): as tall as the part was loaded on
 * this browser's last visit at this window and width (on a first visit, `fallback`), from
 * the first paint. The skeleton takes exactly that height and the loaded part at least it,
 * so nothing below moves when an answer arrives, and a returning viewer sees no padding.
 * The loaded height is kept for the next visit (this browser only; a convenience). */
export function Slot({ name, fallback, loaded, children }: SlotProps) {
  const ref = useRef<HTMLDivElement>(null);
  const wide = typeof window !== "undefined" && window.innerWidth >= FROM;
  const key = `${name}:${Math.round((typeof window !== "undefined" ? window.innerWidth : 0) / 40)}`;
  const height = useMemo(() => stored()[key] ?? fallback, [key, fallback]);
  useEffect(() => {
    const card = ref.current?.firstElementChild;
    if (!loaded || !wide || !card || typeof ResizeObserver === "undefined") return;
    const keep = () => {
      const all = stored();
      all[key] = natural(card);
      try {
        window.localStorage.setItem(KEY, JSON.stringify(all));
      } catch {
        // Storage blocked: the next visit starts from the fallback.
      }
    };
    const watch = new ResizeObserver(keep);
    watch.observe(card);
    for (const c of Array.from(card.children[1]?.children ?? [])) watch.observe(c);
    return () => watch.disconnect();
  }, [loaded, wide, key]);
  return (
    <div
      ref={ref}
      data-slot={name}
      className="flex min-w-0 flex-col [&>*]:flex-1"
      style={wide ? (loaded ? { minHeight: height } : { height }) : undefined}
    >
      {children}
    </div>
  );
}
