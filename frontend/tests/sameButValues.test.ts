import { describe, expect, it } from "vitest";
import { sameButValues } from "@/lib/search";

// Like who_had_ip: one parameter used twice, and the range placeholders.
const PACK =
  "SELECT time FROM events WHERE a = {{ip}} AND time BETWEEN {{start}} AND {{end}}\n" +
  "UNION ALL SELECT time FROM events WHERE b = {{ip}} AND n > {{limit}}";
const sql = (a: string, b: string, n = "5") =>
  PACK.replace("{{ip}}", a).replace("{{ip}}", b).replace("{{limit}}", n);

describe("A library query edited only in its values (D274)", () => {
  it("is the same query when every use of a parameter has the same value", () => {
    expect(sameButValues(sql("'10.20.1.5'", "'10.20.1.5'"), PACK)).toBe(true);
    expect(sameButValues(sql("'10.20.9.9'", "'10.20.9.9'", "12"), PACK)).toBe(true);
    expect(sameButValues(sql("'it''s'", "'it''s'", "-1.5"), PACK)).toBe(true);
    expect(sameButValues(PACK, PACK)).toBe(true); // placeholders left as they are
  });

  it("is another query when one use of a parameter changes alone", () => {
    expect(sameButValues(sql("'10.20.9.9'", "'10.20.1.5'"), PACK)).toBe(false);
    expect(sameButValues(sql("{{ip}}", "'10.20.1.5'"), PACK)).toBe(false);
  });

  it("is another query after any other edit, or with the range written in", () => {
    expect(sameButValues(`${sql("'x'", "'x'")} LIMIT 5`, PACK)).toBe(false);
    expect(sameButValues(sql("'x'", "'x'").replace("UNION ALL", "UNION"), PACK)).toBe(false);
    expect(sameButValues(sql("'x'", "'x'").replace("{{start}}", "'2026-11-01'"), PACK)).toBe(false);
    expect(sameButValues(sql("'x' OR true", "'x' OR true"), PACK)).toBe(false);
  });
});
