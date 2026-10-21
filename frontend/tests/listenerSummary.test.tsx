import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ListenerSummary } from "@/features/sources/ListenerSummary";
import type { ListenerStatus } from "@/lib/api";

function status(addresses: string[]): ListenerStatus {
  return {
    protocol: "udp",
    port: 5514,
    listening: true,
    received: 10,
    dropped_not_allowed: 0,
    dropped_full: 0,
    connections: 0,
    last_message_at: null,
    senders: addresses.map((address) => ({ address, count: 5, last_seen: null, allowed: true })),
  };
}

describe("ListenerSummary", () => {
  it("warns when every sender looks like a Docker gateway", () => {
    render(<ListenerSummary settings={null} listener={status(["172.17.0.1", "172.18.0.1"])} />);
    expect(screen.getByRole("note")).toHaveTextContent("Docker gateway");
  });

  it("says nothing when real device addresses come through", () => {
    render(<ListenerSummary settings={null} listener={status(["172.17.0.1", "192.168.1.20"])} />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
