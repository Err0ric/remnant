import { describe, expect, it } from "vitest";
import { describeAction } from "@/features/audit/actions";

describe("describeAction", () => {
  it("names known actions in plain words", () => {
    expect(describeAction("integrity.report")).toBe("Downloaded the integrity report");
    expect(describeAction("auth.login")).toBe("Signed in");
  });

  it("spells out an unknown code instead of hiding it", () => {
    expect(describeAction("widget.color_change")).toBe("Widget color change");
  });
});
