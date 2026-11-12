import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ViewerProvider } from "@/app/ViewerProvider";
import type { User } from "@/lib/api";
import { useViewer } from "@/lib/viewer";

function Probe() {
  const { canViewPeople } = useViewer();
  return <span>{canViewPeople ? "names" : "masked"}</span>;
}

function viewer(user: User | null) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ViewerProvider user={user}>
        <Probe />
      </ViewerProvider>
    </QueryClientProvider>,
  );
  const text = screen.getByText(/names|masked/).textContent;
  cleanup();
  return text;
}

const base = { user_id: "u1", username: "ana" };

describe("View people in AI usage (D242)", () => {
  it("is on for an admin whatever the stored flag says", () => {
    expect(viewer({ ...base, role: "admin", view_ai_people: false } as User)).toBe("names");
  });
  it("is off for an analyst or auditor until granted", () => {
    expect(viewer({ ...base, role: "analyst", view_ai_people: false } as User)).toBe("masked");
    expect(viewer({ ...base, role: "auditor" } as User)).toBe("masked");
  });
  it("is on once an admin grants it", () => {
    expect(viewer({ ...base, role: "analyst", view_ai_people: true } as User)).toBe("names");
  });
});
