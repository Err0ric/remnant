import { Check, ChevronDown } from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  /** Only a truly unavailable choice: drawn muted, skipped by the arrow keys. */
  disabled?: boolean;
  /** Shown on hover. */
  title?: string;
  /** Options with the same group in a row are listed under that heading (was an optgroup). */
  group?: string;
}

/** The two looks (DESIGN.md 7): `field`, a form control drawn like the text inputs beside
 * it; `facet`, the filter bar's "Name Value" control. */
export type SelectLook = "field" | "facet";

const LOOK: Record<SelectLook, string> = {
  field: "h-8 rounded border border-border-control bg-inset px-2 text-text",
  facet: "h-7 rounded border border-border-strong bg-transparent pl-2.5 pr-2 text-text-secondary",
};

/** The focus ring while focused or open, on every trigger alike. Kept out of `cn`, whose
 * merge would drop `outline` as a duplicate of `outline-2`. */
const RING =
  "focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-focus-ring " +
  "aria-expanded:outline aria-expanded:outline-2 aria-expanded:outline-offset-1 aria-expanded:outline-focus-ring";

interface SelectProps {
  value: string;
  options: readonly SelectOption[];
  onChange: (value: string) => void;
  /** For a `<label htmlFor>`; a wrapping `<label>` names the control by itself. */
  id?: string;
  "aria-label"?: string;
  /** Submitted with a form under this name, through a hidden input. */
  name?: string;
  disabled?: boolean;
  look?: SelectLook;
  /** A facet's name, read before its value inside the button ("Severity High"). */
  prefix?: string;
  /** Drawn inside the button after the value (Ask's Model chip: its Local or Cloud badge). */
  suffix?: ReactNode;
  /** Shown while no option is chosen; the list then holds only the real choices. For an
   * instruction or an action ("Choose...", "Add source filter"), never a value. */
  placeholder?: string;
  /** Why there is nothing to choose, read on hover and by assistive technology while the
   * list is empty ("Every source is already added", "Loading"); the control is then
   * disabled. */
  emptyReason?: string;
  /** Layout only (height, width, flex, mono font); the look comes from `look`. */
  className?: string;
  /** Extra classes for each row of the list (font-mono for data values). */
  optionClassName?: string;
}

const GAP = 4;
const EDGE = 8;
const MAX_LIST = 320;
const TYPE_AHEAD_MS = 600;

/** The themed single select (DESIGN.md 7): a button that reads like the app's inputs and
 * opens a list drawn in theme tokens, in a portal so no card, table, or sticky pane clips
 * it. WAI-ARIA select-only combobox: focus stays on the button, the list follows it with
 * aria-activedescendant. */
export function Select({
  value,
  options,
  onChange,
  id,
  "aria-label": ariaLabel,
  name,
  disabled,
  look = "field",
  prefix,
  suffix,
  placeholder,
  emptyReason = "Nothing to choose",
  className,
  optionClassName,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [place, setPlace] = useState<CSSProperties>(HIDDEN);
  const [listName, setListName] = useState<string | undefined>(undefined);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const typed = useRef({ text: "", at: 0 });
  // Set while a keyboard Enter or Space is being handled, so the click a browser makes from
  // that key (Firefox makes it on Space's keyup) does not toggle the list a second time.
  const keyClick = useRef(false);
  const listId = useId();
  const optionId = (i: number) => `${listId}-o${i}`;
  const selected = options.findIndex((o) => o.value === value);
  const enabled = (i: number) => i >= 0 && i < options.length && !options[i]?.disabled;

  /** The nearest enabled option from `from` in direction `step`, or `fallback`. */
  const nearest = (from: number, step: 1 | -1, fallback: number) => {
    for (let i = from; i >= 0 && i < options.length; i += step) if (enabled(i)) return i;
    return fallback;
  };
  const empty = !options.some((o) => !o.disabled);
  const off = Boolean(disabled) || empty;
  const first = () => nearest(0, 1, -1);
  const last = () => nearest(options.length - 1, -1, -1);

  const show = (at: number) => {
    if (off) return;
    setListName(ariaLabel ?? labelOf(trigger.current));
    // Placed before the first paint from an estimate, so the list is never in the page's
    // flow (where it would scroll the page); measured again once it has drawn.
    const box = trigger.current?.getBoundingClientRect();
    setPlace(box ? placeFor(box, Math.min(MAX_LIST, options.length * 32 + 10), box.width) : HIDDEN);
    setActive(at);
    setOpen(true);
  };
  const close = useCallback(() => {
    setOpen(false);
    setActive(-1);
  }, []);
  const choose = (i: number) => {
    const o = options[i];
    if (!o || o.disabled) return;
    close();
    trigger.current?.focus();
    if (o.value !== value) onChange(o.value);
  };

  /** Type-ahead: the first enabled option, from `from`, whose label starts with all the
   * letters typed so far (spaces included). A first letter, or the same letter again, moves
   * on to the next match; a longer string stays on the current one while it still matches. */
  const seek = (key: string, from: number) => {
    const now = Date.now();
    const t = typed.current;
    t.text = now - t.at > TYPE_AHEAD_MS ? key : t.text + key;
    t.at = now;
    const text = t.text.toLowerCase();
    const repeat = text.length > 1 && text.split("").every((c) => c === text[0]);
    const want = repeat ? text.slice(0, 1) : text;
    const start = want.length === 1 ? from + 1 : Math.max(from, 0);
    for (let n = 0; n < options.length; n++) {
      const i = (start + n) % options.length;
      const o = options[i];
      if (enabled(i) && o && o.label.toLowerCase().startsWith(want)) return i;
    }
    return -1;
  };

  const measure = useCallback(() => {
    const box = trigger.current?.getBoundingClientRect();
    const el = list.current;
    if (!box || !el) return;
    setPlace(placeFor(box, Math.min(MAX_LIST, el.scrollHeight), el.offsetWidth));
  }, []);

  useLayoutEffect(() => {
    if (open) measure();
  }, [open, measure, options.length]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      const own = trigger.current;
      if (own?.contains(t) || list.current?.contains(t)) return;
      // A click on the control's own label toggles it through the button.
      if (Array.from(own?.labels ?? []).some((l) => l.contains(t))) return;
      close();
    };
    document.addEventListener("pointerdown", away);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, close, measure]);

  // Keep the active row in view while the arrows move it: the list's own scroll only, never
  // scrollIntoView, which would also scroll the page.
  useLayoutEffect(() => {
    const el = list.current;
    const row = open && active >= 0 ? document.getElementById(`${listId}-o${active}`) : null;
    if (!el || !row) return;
    if (row.offsetTop < el.scrollTop) el.scrollTop = row.offsetTop;
    else if (row.offsetTop + row.offsetHeight > el.scrollTop + el.clientHeight)
      el.scrollTop = row.offsetTop + row.offsetHeight - el.clientHeight;
  }, [open, active, listId]);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const k = e.key;
    let handled = true;
    if (!open) {
      if (k === "ArrowDown" || k === "ArrowUp" || k === "Enter" || k === " ") {
        if (k === "Enter" || k === " ") keyClick.current = true;
        show(enabled(selected) ? selected : first());
      } else if (k === "Home") show(first());
      else if (k === "End") show(last());
      else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const hit = seek(k, selected);
        show(hit >= 0 ? hit : enabled(selected) ? selected : first());
      } else handled = false;
    } else if (k === "ArrowDown") setActive(nearest(active + 1, 1, active));
    else if (k === "ArrowUp") setActive(nearest(active - 1, -1, active));
    else if (k === "Home") setActive(first());
    else if (k === "End") setActive(last());
    else if (k === "PageDown")
      setActive(nearest(Math.min(active + 10, options.length - 1), -1, active));
    else if (k === "PageUp") setActive(nearest(Math.max(active - 10, 0), 1, active));
    else if (k === "Enter" || k === " ") {
      keyClick.current = true;
      if (k === " " && Date.now() - typed.current.at < TYPE_AHEAD_MS) {
        const hit = seek(" ", active);
        if (hit >= 0) setActive(hit);
      } else choose(active);
    } else if (k === "Escape") close();
    else if (k === "Tab") {
      close();
      handled = false;
    } else if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const hit = seek(k, active);
      if (hit >= 0) setActive(hit);
    } else handled = false;
    if (handled) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  // As a native select did: with no matching value it shows the first enabled option,
  // unless there is a placeholder to show.
  const current = options[selected] ?? (placeholder === undefined ? options[first()] : undefined);
  const shown = current?.label ?? placeholder ?? "";
  return (
    <>
      <button
        ref={trigger}
        type="button"
        id={id}
        role="combobox"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        value={value}
        disabled={off}
        title={empty ? emptyReason : (current?.title ?? shown)}
        onClick={() => {
          // The keyboard already acted on this key: a click it made is not a second toggle.
          if (keyClick.current) {
            keyClick.current = false;
            return;
          }
          if (open) close();
          else show(enabled(selected) ? selected : first());
        }}
        onKeyDown={onKeyDown}
        onKeyUp={(e) => {
          if (e.key !== " " && e.key !== "Enter") return;
          e.preventDefault();
          // A click made from this key comes right after keyup, in the same task.
          setTimeout(() => {
            keyClick.current = false;
          }, 0);
        }}
        onBlur={(e) => {
          if (!list.current?.contains(e.relatedTarget as Node | null)) close();
        }}
        className={`${RING} ${cn(
          "inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap text-left",
          "disabled:cursor-default disabled:opacity-60",
          LOOK[look],
          className,
        )}`}
      >
        {prefix ? <span className="shrink-0">{prefix}</span> : null}
        {/* Every label is measured in one cell, so the button is as wide as its longest
            option, as a native select was, and does not change width with the value. */}
        <span className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)]">
          {/* First, so the button's baseline is its text's, as a native select's is. */}
          <span
            className={cn(
              "col-start-1 row-start-1 truncate",
              current ? (look === "facet" ? "font-semibold text-text" : "") : "text-text-secondary",
            )}
          >
            {shown}
          </span>
          {placeholder !== undefined ? (
            <span
              data-select-sizer={placeholder}
              className="col-start-1 row-start-1 overflow-hidden"
            />
          ) : null}
          {options.map((o) => (
            <span
              key={o.value}
              data-select-sizer={o.label}
              className="col-start-1 row-start-1 overflow-hidden"
            />
          ))}
        </span>
        {suffix}
        <ChevronDown
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className="shrink-0 text-text-secondary"
        />
      </button>
      {name ? <input type="hidden" name={name} value={value} /> : null}
      {open
        ? createPortal(
            <div
              ref={list}
              id={listId}
              role="listbox"
              aria-label={listName}
              tabIndex={-1}
              style={place}
              onMouseDown={(e) => e.preventDefault()}
              className="flex flex-col overflow-y-auto overscroll-contain rounded-card border border-border bg-surface py-1 text-base text-text shadow-lg"
            >
              {groups(options).map(({ group, items }) =>
                group ? (
                  <div key={group} role="group" aria-labelledby={`${listId}-g${items[0]}`}>
                    <div
                      id={`${listId}-g${items[0]}`}
                      role="presentation"
                      className="px-2.5 pb-0.5 pt-2 text-xs text-text-secondary"
                    >
                      {group}
                    </div>
                    {items.map(row)}
                  </div>
                ) : (
                  <Fragment key={`_${items[0]}`}>{items.map(row)}</Fragment>
                ),
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );

  function row(i: number) {
    const o = options[i];
    if (!o) return null;
    const isSelected = i === selected;
    return (
      <div
        key={o.value}
        id={optionId(i)}
        role="option"
        aria-selected={isSelected}
        aria-disabled={o.disabled || undefined}
        data-value={o.value}
        data-active={i === active || undefined}
        title={o.title}
        onMouseEnter={() => (o.disabled ? undefined : setActive(i))}
        onClick={() => choose(i)}
        className={cn(
          "flex min-h-8 cursor-default items-center gap-2 whitespace-nowrap py-1.5 pl-2 pr-3",
          o.disabled ? "text-text-muted" : "text-text",
          i === active && "bg-accent-subtle",
          isSelected && "font-semibold",
          optionClassName,
        )}
      >
        <Check
          size={14}
          strokeWidth={2}
          aria-hidden
          className={cn("shrink-0", isSelected ? "text-accent-text" : "invisible")}
        />
        {o.label}
      </div>
    );
  }
}

/** Before the list is placed: fixed and hidden, so it never lands in the page's flow. */
const HIDDEN: CSSProperties = {
  position: "fixed",
  zIndex: 60,
  top: 0,
  left: 0,
  visibility: "hidden",
};

/** Below the trigger, above when there is more room there; its left edge on the trigger's,
 * or its right edge on the trigger's when it would leave the viewport; at least as wide. */
function placeFor(box: DOMRect, height: number, width: number): CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const below = vh - box.bottom - GAP - EDGE;
  const above = box.top - GAP - EDGE;
  const up = below < height && above > below;
  const maxWidth = vw - 2 * EDGE;
  const w = Math.min(Math.max(box.width, width), maxWidth);
  const left = box.left + w > vw - EDGE ? Math.max(EDGE, box.right - w) : box.left;
  return {
    position: "fixed",
    zIndex: 60,
    left,
    minWidth: Math.min(box.width, maxWidth),
    maxWidth,
    maxHeight: Math.max(96, Math.min(MAX_LIST, up ? above : below)),
    ...(up ? { bottom: vh - box.top + GAP } : { top: box.bottom + GAP }),
  };
}

/** Options in order, consecutive ones with the same group together. */
function groups(options: readonly SelectOption[]): { group?: string; items: number[] }[] {
  const out: { group?: string; items: number[] }[] = [];
  options.forEach((o, i) => {
    const prev = out[out.length - 1];
    if (prev && prev.group === o.group) prev.items.push(i);
    else out.push({ group: o.group, items: [i] });
  });
  return out;
}

/** The text of the trigger's label, so the list is named like the control. */
function labelOf(el: HTMLButtonElement | null): string | undefined {
  const label = el?.labels?.[0];
  if (!label) return undefined;
  const parts: string[] = [];
  const walk = (n: Node) => {
    if (n === el) return;
    if (n.nodeType === Node.TEXT_NODE) parts.push(n.textContent ?? "");
    n.childNodes.forEach(walk);
  };
  walk(label);
  return parts.join(" ").replace(/\s+/g, " ").trim() || undefined;
}
