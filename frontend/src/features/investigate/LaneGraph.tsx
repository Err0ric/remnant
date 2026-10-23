import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import type { EntityGraph, GraphCard } from "@/lib/api";

// Layout (ADR-0016 row 5, the data-access lane layout the owner preferred): each lane is a column
// of group boxes ("MCP servers", "Built-in tools"), cards inside, joined left to right
// by right-angled links that share a trunk between lanes.
const MIN_LANE = 160;
const GUTTER = 56; // between lanes, where the links turn
const PAD = 20; // canvas edge
const TITLE_H = 26; // lane title above its boxes
const BOX_PAD = 10;
const GROUP_H = 22; // a group's heading inside its box
const BOX_GAP = 12;
const CARD_H = 52;
const CARD_BADGE_H = 72;
const CARD_GAP = 8;
const RADIUS = 6;
// Groups that are the point of a lane come before the leftovers in it.
const GROUP_LAST = new Set([
  "Addresses",
  "Devices not matched to a person",
  "Built-in tools",
  "Other hosts",
  "IP addresses",
  "Other",
]);

/** Width of the element, following resizes (falls back to a desktop width in tests). */
function useWidth(): [RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1040);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      if (el.clientWidth > 0) setWidth(el.clientWidth);
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Cards reachable from `id` going left and going right: the path a click highlights. */
export function connected(graph: EntityGraph, id: string): Set<string> {
  const out = new Set([id]);
  for (const dir of ["forward", "back"] as const) {
    const queue = [id];
    while (queue.length) {
      const cur = queue.shift() as string;
      for (const e of graph.edges) {
        const [from, to] = dir === "forward" ? [e.source, e.target] : [e.target, e.source];
        if (from === cur && !out.has(to)) {
          out.add(to);
          queue.push(to);
        }
      }
    }
  }
  return out;
}

/** A right-angled link with rounded corners: out of the card, along the trunk, in. */
function elbow(x1: number, y1: number, xm: number, x2: number, y2: number): string {
  const dy = y2 - y1;
  if (Math.abs(dy) < 1) return `M${x1},${y1} H${x2}`;
  const r = Math.min(RADIUS, Math.abs(dy) / 2, xm - x1, x2 - xm);
  const s = dy > 0 ? 1 : -1;
  return [
    `M${x1},${y1}`,
    `H${xm - r}`,
    `Q${xm},${y1} ${xm},${y1 + s * r}`,
    `V${y2 - s * r}`,
    `Q${xm},${y2} ${xm + r},${y2}`,
    `H${x2}`,
  ].join(" ");
}

type Glyph =
  | "person"
  | "address"
  | "host"
  | "source"
  | "activity"
  | "app"
  | "plug"
  | "tool"
  | "cloud"
  | "globe";

/** Which small symbol a card carries, from its lane and group. */
function glyphFor(graph: EntityGraph, card: GraphCard): Glyph {
  const g = card.group;
  if (graph.mode === "ai") {
    // Devices with no person named are their own group, never shown as people.
    if (card.lane === 0)
      return g === "Addresses"
        ? "address"
        : g === "Devices not matched to a person"
          ? "host"
          : "person";
    if (card.lane === 1) return "app";
    if (card.lane === 2) return g === "MCP servers" ? "plug" : "tool";
    return g === "AI services" ? "cloud" : "globe";
  }
  if (card.lane === 0)
    return card.sublabel === "User" ? "person" : card.sublabel === "Host" ? "host" : "address";
  if (card.lane === 1) return "source";
  if (card.lane === 2) return "activity";
  return g === "IP addresses" ? "address" : "host";
}

/** 16 by 16 line symbols, drawn in the card's text color. */
function GlyphPath({ glyph }: { glyph: Glyph }) {
  const d: Record<Glyph, string> = {
    person: "M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-5.5 6.5c.6-2.6 2.8-4.3 5.5-4.3s4.9 1.7 5.5 4.3",
    address: "M2 4h12v8H2zM5 7h1M8 7h3M5 9.5h6",
    host: "M2 3h12v7H2zM6 13h4M8 10v3",
    source:
      "M3 4c0-1.1 2.2-2 5-2s5 .9 5 2-2.2 2-5 2-5-.9-5-2Zm0 0v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2",
    activity: "M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z",
    app: "M2 3h12v10H2zM2 6h12M4 4.5h1",
    plug: "M6 2v3M10 2v3M4 5h8v2.5a4 4 0 0 1-8 0zM8 11.5V14",
    tool: "M10.5 2.5a3 3 0 0 0-3.7 3.7L2.5 10.5l3 3 4.3-4.3a3 3 0 0 0 3.7-3.7l-2 2-2-.5-.5-2z",
    cloud: "M4.5 12.5h7a3 3 0 0 0 .3-6 4 4 0 0 0-7.6-1A3.3 3.3 0 0 0 4.5 12.5Z",
    globe:
      "M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12ZM2 8h12M8 2c1.8 1.7 2.6 3.7 2.6 6S9.8 12.3 8 14M8 2C6.2 3.7 5.4 5.7 5.4 8s.8 4.3 2.6 6",
  };
  return (
    <path
      d={d[glyph]}
      fill="none"
      strokeWidth={1.3}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="stroke-current"
    />
  );
}

interface Placed {
  card: GraphCard;
  x: number;
  y: number;
  h: number;
}

interface Box {
  lane: number;
  group: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

function badgeClass(b: string): string {
  if (b === "Not approved" || b === "High severity" || b.includes("rule match"))
    return "fill-sev-critical-bg";
  if (b === "Sensitive data") return "fill-sev-medium-bg";
  return "fill-sev-info-bg";
}

function badgeText(b: string): string {
  if (b === "Not approved" || b === "High severity" || b.includes("rule match"))
    return "fill-sev-critical-text";
  if (b === "Sensitive data") return "fill-sev-medium-text";
  return "fill-sev-info-text";
}

interface LaneGraphProps {
  graph: EntityGraph;
  selected: string | null;
  onSelect: (card: GraphCard | null) => void;
}

/** Lanes of grouped cards on a dotted canvas. A selected card keeps its path lit and
 * fades the rest. Every value is an SVG text node. */
export function LaneGraph({ graph, selected, onSelect }: LaneGraphProps) {
  const [box, boxWidth] = useWidth();
  const n = Math.max(1, graph.lanes.length);
  const laneW = Math.max(MIN_LANE, Math.floor((boxWidth - 2 * PAD - (n - 1) * GUTTER) / n));
  const cardW = laneW - 2 * BOX_PAD;
  const chars = Math.floor((cardW - 52) / 7.8);

  const layout = useMemo(() => {
    const placed = new Map<string, Placed>();
    const boxes: Box[] = [];
    const bottoms: number[] = [];
    graph.lanes.forEach((_, lane) => {
      const x = PAD + lane * (laneW + GUTTER);
      // Groups in the order their first (largest) card appears.
      const groups = new Map<string, GraphCard[]>();
      for (const c of graph.cards.filter((c) => c.lane === lane)) {
        const list = groups.get(c.group) ?? [];
        list.push(c);
        groups.set(c.group, list);
      }
      const ordered = [...groups].sort(
        ([a], [b]) => Number(GROUP_LAST.has(a)) - Number(GROUP_LAST.has(b)),
      );
      let y = PAD + TITLE_H;
      for (const [group, cards] of ordered) {
        const top = y;
        y += BOX_PAD + (group ? GROUP_H : 0);
        for (const card of cards) {
          const h = card.badges.length ? CARD_BADGE_H : CARD_H;
          placed.set(card.id, { card, x: x + BOX_PAD, y, h });
          y += h + CARD_GAP;
        }
        y += BOX_PAD - CARD_GAP;
        boxes.push({ lane, group, x, y: top, w: laneW, h: y - top });
        y += BOX_GAP;
      }
      bottoms.push(y + ((graph.more[lane] ?? 0) > 0 ? 18 : 0));
    });
    return { placed, boxes, bottoms, height: Math.max(160, ...bottoms) + PAD };
  }, [graph, laneW]);

  const lit = useMemo(() => (selected ? connected(graph, selected) : null), [graph, selected]);
  const width = 2 * PAD + n * laneW + (n - 1) * GUTTER;

  const key = (card: GraphCard) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(selected === card.id ? null : card);
    }
  };

  return (
    <div ref={box} className="min-w-0 flex-1 overflow-x-auto">
      <svg
        width={width}
        height={layout.height}
        viewBox={`0 0 ${width} ${layout.height}`}
        role="group"
        aria-label={`Investigation lanes: ${graph.lanes.join(", ")}`}
        className="block"
        onClick={(e) => {
          if (e.target === e.currentTarget) onSelect(null);
        }}
      >
        <defs>
          <pattern id="lane-dots" width={16} height={16} patternUnits="userSpaceOnUse">
            <circle cx={1} cy={1} r={1} className="fill-border-strong" opacity={0.55} />
          </pattern>
        </defs>
        <rect width={width} height={layout.height} fill="url(#lane-dots)" pointerEvents="none" />

        {graph.lanes.map((lane, i) => (
          <text
            key={lane}
            x={PAD + i * (laneW + GUTTER) + 2}
            y={PAD + 12}
            className="fill-text-secondary text-xs font-semibold"
          >
            {lane}
          </text>
        ))}

        {layout.boxes.map((b) => (
          <g key={`${b.lane}:${b.group}`} pointerEvents="none">
            <rect
              x={b.x}
              y={b.y}
              width={b.w}
              height={b.h}
              rx={8}
              className="fill-surface stroke-border"
            />
            {b.group ? (
              <text
                x={b.x + BOX_PAD + 2}
                y={b.y + BOX_PAD + 12}
                className="fill-text-muted text-xs"
              >
                {b.group}
              </text>
            ) : null}
          </g>
        ))}

        {graph.edges.map((e) => {
          const a = layout.placed.get(e.source);
          const b = layout.placed.get(e.target);
          if (!a || !b) return null;
          const x1 = a.x + cardW;
          const x2 = b.x;
          // The trunk sits halfway across the gutter before the target's lane.
          const xm = b.x - BOX_PAD - GUTTER / 2;
          const on = lit ? lit.has(e.source) && lit.has(e.target) : false;
          return (
            <path
              key={`${e.source}>${e.target}`}
              d={elbow(x1, a.y + a.h / 2, xm, x2, b.y + b.h / 2)}
              fill="none"
              strokeWidth={on ? 2 : 1}
              className={
                on
                  ? "stroke-accent-text"
                  : lit
                    ? "stroke-border opacity-30"
                    : "stroke-border-strong"
              }
            />
          );
        })}

        {[...layout.placed.values()].map(({ card, x, y, h }) => {
          const on = selected === card.id;
          const dim = lit !== null && !lit.has(card.id);
          const flagged = card.matches > 0 || card.badges.includes("Not approved");
          const detail = [card.sublabel, plural(card.events, "event")].filter(Boolean).join(" · ");
          let bx = 46;
          return (
            <g
              key={card.id}
              transform={`translate(${x},${y})`}
              role="button"
              tabIndex={0}
              aria-pressed={on}
              aria-label={`${graph.lanes[card.lane]}: ${card.label}, ${detail}${card.badges.length ? `, ${card.badges.join(", ")}` : ""}`}
              onClick={() => onSelect(on ? null : card)}
              onKeyDown={key(card)}
              className={`group cursor-pointer outline-none transition-opacity ${dim ? "opacity-40" : ""}`}
            >
              <title>{card.label}</title>
              <rect
                width={cardW}
                height={h}
                rx={RADIUS}
                className={
                  on
                    ? "fill-accent-subtle stroke-accent-text"
                    : "fill-bg stroke-border-strong group-hover:stroke-accent-text group-focus-visible:stroke-focus-ring"
                }
                strokeWidth={on ? 2 : 1}
              />
              {flagged ? (
                <rect x={0} y={8} width={3} height={h - 16} rx={1.5} className="fill-danger" />
              ) : null}
              <circle cx={24} cy={26} r={13} className="fill-surface-head stroke-border" />
              <g
                transform="translate(16,18)"
                className={flagged ? "text-danger" : "text-text-secondary"}
              >
                <GlyphPath glyph={glyphFor(graph, card)} />
              </g>
              <text x={46} y={22} className="fill-text font-mono text-sm">
                {clip(card.label, chars)}
              </text>
              <text x={46} y={39} className="fill-text-muted text-xs">
                {clip(detail, chars + 6)}
              </text>
              {card.badges.slice(0, 2).map((b) => {
                const label = clip(b, 18);
                const w = label.length * 6.4 + 12;
                const at = bx;
                bx += w + 4;
                if (at + w > cardW - 6) return null;
                return (
                  <g key={b} transform={`translate(${at},48)`}>
                    <rect width={w} height={16} rx={3} className={badgeClass(b)} />
                    <text x={6} y={11.5} className={`text-[11px] font-semibold ${badgeText(b)}`}>
                      {label}
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}

        {graph.more.map((count, lane) =>
          count > 0 ? (
            <text
              key={`more-${lane}`}
              x={PAD + lane * (laneW + GUTTER) + 2}
              y={(layout.bottoms[lane] ?? 0) - 6}
              className="fill-text-muted text-xs"
            >
              {count} more not shown (smaller ones)
            </text>
          ) : null,
        )}
      </svg>
    </div>
  );
}
