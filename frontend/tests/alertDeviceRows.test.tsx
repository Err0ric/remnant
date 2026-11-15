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
    expect(host).toHaveAttribute("title", "ws-0101\nInvestigate this machine");
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

  it("keeps each comma with the value before it, so a line never starts with one", () => {
    const { container } = render(
      <dl>
        <DeviceRows devices={["ws-0101", "ws-0102", "ws-0103"]} />
      </dl>,
    );
    const kept = [...container.querySelectorAll("dd .whitespace-nowrap")];
    expect(kept.map((k) => k.textContent)).toEqual(["ws-0101,", "ws-0102,", "ws-0103"]);
    expect(kept[1]?.firstElementChild?.tagName).toBe("A");
  });

  it("says when the list was cut, and how many there were", () => {
    const shown = Array.from({ length: 20 }, (_, i) => `ws-${String(i).padStart(4, "0")}`);
    render(
      <dl>
        <DeviceRows devices={shown} total={85} />
      </dl>,
    );
    expect(screen.getByText("20 of 85 devices and addresses")).toBeInTheDocument();
  });

  it("says nothing more when every device is listed", () => {
    render(
      <dl>
        <DeviceRows devices={["ws-0101", "10.20.1.5"]} total={2} />
      </dl>,
    );
    expect(screen.queryByText(/ of \d+ devices/)).toBeNull();
  });
});
