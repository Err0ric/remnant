import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AddressCoverage, InventoryMatch } from "@/lib/api";
import { CoverageLines, addressIn } from "@/features/investigate/EmptyAddress";
import { InventoryMatches, guestLabel } from "@/features/investigate/InventoryLine";

const VM: InventoryMatch = {
  source_id: "pve",
  vmid: 104,
  type: "qemu",
  name: "build-runner",
  node: "pve2",
  first_seen: "2026-11-05T10:00:00+00:00",
  last_seen: "2026-11-06T12:00:00+00:00",
  current: true,
  search_sql: "SELECT 1",
  matched_by: "ip",
  possible: false,
};

function coverage(over: Partial<AddressCoverage> = {}): AddressCoverage {
  return {
    value: "10.20.30.40",
    start: "2026-11-05T12:00:00+00:00",
    end: "2026-11-06T12:00:00+00:00",
    events: 0,
    categories: [
      {
        category: "dns",
        sources: [
          { source_id: "dns_a", state: "receiving", since: null, records_address: true },
          {
            source_id: "dns_b",
            state: "not_receiving",
            since: "2026-11-05T14:02:00+00:00",
            records_address: true,
          },
        ],
      },
      {
        category: "system",
        sources: [{ source_id: "sys", state: "off", since: null, records_address: true }],
      },
    ],
    missing: ["network", "identity"],
    inventory_source: true,
    inventory: [],
    restricted: false,
    can_add_source: true,
    ...over,
  };
}

describe("Proxmox inventory lines (ADR-0045 A5)", () => {
  it("names the guest, its node, and when it held the address", () => {
    expect(guestLabel(VM)).toBe("Proxmox VM 104 build-runner on pve2");
    expect(guestLabel({ ...VM, type: "lxc", vmid: 201, name: "dns-cache" })).toBe(
      "Proxmox container 201 dns-cache on pve2",
    );
    render(<InventoryMatches matches={[VM, { ...VM, vmid: 105, current: false }]} />);
    const list = screen.getByRole("list", { name: "Proxmox inventory" });
    expect(within(list).getAllByRole("button", { name: "Show events" })).toHaveLength(2);
    expect(within(list).getByText(/no longer holds it/)).toBeInTheDocument();
    expect(list.querySelectorAll("time")).toHaveLength(4); // local time, UTC on hover
  });
});

describe("Empty results say why (ADR-0045 Part B)", () => {
  it("states one line per category, the gaps, the inventory, and Add a source", () => {
    render(<CoverageLines data={coverage()} rangeWords="the last 24 hours" />);
    const box = screen.getByRole("region", { name: "Why there are no events" });
    expect(box).toHaveTextContent("No events for 10.20.30.40 in the last 24 hours.");
    expect(box).toHaveTextContent("DNS (2 sources): no lookups by this address");
    expect(box).toHaveTextContent("dns_b not receiving since");
    expect(box).toHaveTextContent(
      "Syslog (1 source): nothing received from this host (sys turned off)",
    );
    expect(box).toHaveTextContent("No firewall source");
    expect(box).toHaveTextContent("No identity source");
    expect(box).toHaveTextContent("Not in the Proxmox inventory");
    expect(within(box).getByRole("button", { name: "Add a source" })).toBeInTheDocument();
    expect(box).not.toHaveTextContent("were not searched");
  });

  it("shows the match instead, the no-access line, and no Add a source for analysts", () => {
    render(
      <CoverageLines
        data={coverage({ inventory: [VM], restricted: true, can_add_source: false })}
        rangeWords="the last 24 hours"
      />,
    );
    const box = screen.getByRole("region", { name: "Why there are no events" });
    expect(box).toHaveTextContent("Proxmox VM 104 build-runner on pve2");
    expect(box).not.toHaveTextContent("Not in the Proxmox inventory");
    expect(box).toHaveTextContent("Sources you don't have access to were not searched.");
    expect(within(box).queryByRole("button", { name: "Add a source" })).toBeNull();
  });

  it("says nothing when there are events", () => {
    const { container } = render(
      <CoverageLines data={coverage({ events: 3 })} rangeWords="the last 24 hours" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("finds the address an Ask question names", () => {
    expect(addressIn("what did 10.20.30.40 do yesterday?")).toBe("10.20.30.40");
    expect(addressIn("traffic from 2001:db8::5 to the dns servers")).toBe("2001:db8::5");
    expect(addressIn("failed sign-ins at 12:30 today")).toBeNull();
    expect(addressIn("version 1.2.3.4.5")).toBeNull();
  });
});

describe("host-name matches (D215)", () => {
  it("labels a match one guest's name made", () => {
    render(<InventoryMatches matches={[{ ...VM, matched_by: "name" }]} />);
    expect(screen.getByText("matched by name")).toBeInTheDocument();
    expect(screen.queryByText(/Possible matches/)).toBeNull();
  });

  it("lists guests that share a name as possible matches, picking none", () => {
    const other = { ...VM, vmid: 105, node: "pve1", matched_by: "name" as const, possible: true };
    render(<InventoryMatches matches={[{ ...VM, matched_by: "name", possible: true }, other]} />);
    expect(
      screen.getByText("Possible matches: 2 guests are named build-runner"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByText("matched by name")).toBeNull();
  });

  it("shows no name note for an IP match", () => {
    render(<InventoryMatches matches={[VM]} compact />);
    expect(screen.getByText(guestLabel(VM))).toBeInTheDocument();
  });
});
