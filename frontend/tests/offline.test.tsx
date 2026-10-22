import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OfflineBanner } from "@/components/shell/OfflineBanner";
import { api } from "@/lib/api";
import { resetConnectivity } from "@/lib/connectivity";

afterEach(() => {
  vi.restoreAllMocks();
  act(() => resetConnectivity());
});

function respond(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

describe("Can't reach the server (F40)", () => {
  it("shows when calls stop reaching the server, with the time of the last answer", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<OfflineBanner />);
    fetchMock.mockImplementationOnce(() => respond(200, []));
    await act(() => api.searches());
    expect(screen.queryByRole("alert")).toBeNull();
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("Failed to fetch")));
    await act(() => api.searches().catch(() => undefined));
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Can't reach the server\s*Showing data from \d\d:\d\d\. Retrying in the background\./,
    );
    fetchMock.mockImplementationOnce(() => respond(200, []));
    await act(() => api.searches());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("treats a proxy's 502 as unreachable, but not the server's own busy or errors", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<OfflineBanner />);
    fetchMock.mockImplementationOnce(() => respond(503, { detail: "busy", code: "busy" }));
    await act(() => api.searches().catch(() => undefined));
    expect(screen.queryByRole("alert")).toBeNull();
    fetchMock.mockImplementationOnce(() => respond(404, { detail: "No", code: "not_found" }));
    await act(() => api.searches().catch(() => undefined));
    expect(screen.queryByRole("alert")).toBeNull();
    fetchMock.mockImplementationOnce(() =>
      Promise.resolve(new Response("Bad Gateway", { status: 502 })),
    );
    await act(() => api.searches().catch(() => undefined));
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
