import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DeviceRows } from "@/features/alerts/DeviceRows";

describe("An alert's devices (owner review, item 8)", () => {
  it("links the host name to its host page and the address to its IP page", () => {
    render(
      <dl>
        <DeviceRows devices={["10.20.1.5", "ws-0101"]} />
      </dl>,
    );
    expect(screen.getByText("Devices")).toBeInTheDocument();
    expect(screen.getByText("Addresses")).toBeInTheDocument();
    const host = screen.getByRole("link", { name: "ws-0101" });
    const ip = screen.getByRole("link", { name: "10.20.1.5" });
    expect(host.getAttribute("href")).toContain("host=ws-0101");
    expect(ip.getAttribute("href")).toContain("ip=10.20.1.5");
    expect(host).toHaveAttribute("title", "Investigate this machine");
  });

  it("shows only an Addresses row for a device known only by its address", () => {
    render(
      <dl>
        <DeviceRows devices={["10.20.1.5"]} />
      </dl>,
    );
    expect(screen.queryByText("Devices")).toBeNull();
    expect(screen.getByRole("link", { name: "10.20.1.5" })).toBeInTheDocument();
  });
});
