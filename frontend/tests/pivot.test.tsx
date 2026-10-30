import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntityLink, EntityList } from "@/components/EntityLink";
import { ResultsTable } from "@/features/search/ResultsTable";
import { entityHref, kindForColumn, parseEntity } from "@/lib/entity";
import type { QueryResult } from "@/lib/api";

afterEach(() => vi.restoreAllMocks());

describe("Pivot links (product pass step 2)", () => {
  it("maps columns to entities and round-trips the address", () => {
    expect(kindForColumn("src_endpoint_ip")).toBe("ip");
    expect(kindForColumn("Address")).toBe("ip");
    expect(kindForColumn("actor_user_name")).toBe("user");
    expect(kindForColumn("device_hostname")).toBe("host");
    expect(kindForColumn("source_id")).toBeNull();
    const href = entityHref({ kind: "user", value: "EXAMPLE\\alice" });
    expect(href).toBe("/investigate/people#user=EXAMPLE%5Calice");
    expect(parseEntity(href.split("#")[1] ?? "")).toEqual({
      kind: "user",
      value: "EXAMPLE\\alice",
    });
    expect(parseEntity("agents")).toBeNull(); // a tab, not an entity
    expect(parseEntity("ip=")).toBeNull();
  });

  it("is a real link that opens the entity, and placeholders stay text", async () => {
    window.history.replaceState(null, "", "/search");
    render(
      <p>
        <EntityLink kind="ip" value="203.0.113.9" />
        <EntityLink kind="host" value="-" />
      </p>,
    );
    const link = screen.getByRole("link", { name: "203.0.113.9" });
    expect(link).toHaveAttribute("href", "/investigate/people#ip=203.0.113.9");
    expect(screen.queryByRole("link", { name: "-" })).toBeNull();
    await userEvent.click(link);
    expect(window.location.pathname + window.location.hash).toBe(
      "/investigate/people#ip=203.0.113.9",
    );
  });

  it("tells addresses from machine names in a Who list", () => {
    render(<EntityList machines={["10.0.0.5", "ws-0042"]} />);
    expect(screen.getByRole("link", { name: "10.0.0.5" })).toHaveAttribute(
      "href",
      "/investigate/people#ip=10.0.0.5",
    );
    expect(screen.getByRole("link", { name: "ws-0042" })).toHaveAttribute(
      "href",
      "/investigate/people#host=ws-0042",
    );
  });

  it("links entity columns in search results without opening the row", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    const result: QueryResult = {
      columns: ["time", "src_endpoint_ip", "actor_user_name", "source_id"],
      rows: [["2026-10-10T11:00:00+00:00", "203.0.113.9", "alice", "fw"]],
      row_count: 1,
      truncated: false,
      elapsed_ms: 1,
      executed_sql: "SELECT 1",
      sources: ["fw"],
    };
    render(<ResultsTable result={result} view="parsed" />);
    const row = screen.getAllByRole("row")[1] as HTMLElement;
    await userEvent.click(screen.getByRole("link", { name: "alice" }));
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(window.location.hash).toBe("#user=alice");
    expect(screen.queryByRole("link", { name: "fw" })).toBeNull();
  });
});
