import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OfflineBanner } from "@/components/shell/OfflineBanner";
import { api, ApiError } from "@/lib/api";
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
      /Can't reach the server\s*Showing data from [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d\d [AP]M\. Retrying in the background\./,
    );
    fetchMock.mockImplementationOnce(() => respond(200, []));
    await act(() => api.searches());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says a proxy's 502 or 504 took too long and its 503 is busy, without the banner", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<OfflineBanner />);
    const said = async (res: Response) => {
      fetchMock.mockImplementationOnce(() => Promise.resolve(res));
      const err = await act(() =>
        api.searches().then(
          () => null,
          (e: unknown) => e,
        ),
      );
      expect(err).toBeInstanceOf(ApiError);
      return (err as ApiError).message;
    };
    expect(await said(new Response("Bad Gateway", { status: 502 }))).toBe(
      "The request took too long",
    );
    expect(await said(new Response("<html>504</html>", { status: 504 }))).toBe(
      "The request took too long",
    );
    expect(await said(new Response("Service Unavailable", { status: 503 }))).toBe(
      "The server is busy",
    );
    expect(screen.queryByRole("alert")).toBeNull();
    // The server's own answers keep their words: its busy model, its model time limit.
    const own = (status: number, detail: string, code: string) =>
      new Response(JSON.stringify({ detail, code }), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    expect(await said(own(503, "The model was busy", "provider_busy"))).toBe("The model was busy");
    expect(await said(own(504, "The model took too long", "model_timeout"))).toBe(
      "The model took too long",
    );
    expect(await said(own(404, "No", "not_found"))).toBe("No");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says Can't reach the server only when the request itself fails", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<OfflineBanner />);
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError("Failed to fetch")));
    const err = await act(() =>
      api.searches().then(
        () => null,
        (e: unknown) => e,
      ),
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("Can't reach the server");
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the server");
  });

  it("leaves a request cancelled in the page as cancelled, not unreachable", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(<OfflineBanner />);
    fetchMock.mockImplementationOnce(() =>
      Promise.reject(new DOMException("The operation was aborted.", "AbortError")),
    );
    const err = await act(() =>
      api.searches().then(
        () => null,
        (e: unknown) => e,
      ),
    );
    expect(err).toBeInstanceOf(DOMException);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
