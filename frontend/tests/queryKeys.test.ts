import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** D194 (owner, 2026-11-03): "e.map is not a function" on the Dashboard. Two queries
 * shared the key ["sources"] with different fetchers (a list of sources, and a Search
 * query result), so whichever ran first gave the other the wrong shape. One key, one
 * fetcher: checked over every `useQuery` with a literal key. */
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(p) ? [p] : [];
  });
}

const PAIR = /queryKey:\s*(\[[^\]]*\])\s*,\s*queryFn:\s*([^\n]+?)(?:,\s*$|\s*\}\)|,\s*\w+:|$)/gms;

describe("query keys", () => {
  it("never share a literal key between two fetchers", () => {
    const seen = new Map<string, { fn: string; at: string }>();
    const clashes: string[] = [];
    for (const path of files(join(__dirname, "..", "src"))) {
      const text = readFileSync(path, "utf8");
      for (const m of text.matchAll(PAIR)) {
        const key = m[1]!.replace(/\s+/g, "");
        const fn = m[2]!.replace(/\s+/g, " ").trim();
        // A key that carries values (a variable) is told apart by them; only the fetcher
        // name matters for a clash.
        const name = /api\.(\w+)/.exec(fn)?.[1] ?? fn;
        const prev = seen.get(key);
        if (prev && prev.fn !== name)
          clashes.push(`${key}: ${prev.fn} (${prev.at}) and ${name} (${path})`);
        else seen.set(key, { fn: name, at: path });
      }
    }
    expect(clashes).toEqual([]);
  });
});
