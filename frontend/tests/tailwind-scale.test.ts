import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import config from "../tailwind.config";

// tailwind.config.ts replaces the spacing scale, so a class like `max-h-56` with no
// matching step generates no CSS and silently does nothing. This keeps them honest.
const PREFIX =
  "-?(?:m|mx|my|mt|mb|ml|mr|p|px|py|pt|pb|pl|pr|gap|gap-x|gap-y|space-x|space-y|w|h|min-w|min-h|max-w|max-h|top|bottom|left|right|inset|inset-x|inset-y|translate-x|translate-y|size|basis)";
const CLASS = new RegExp(`(?<![\\w-])(?:[a-z0-9]+:)*(${PREFIX})-([\\d.]+)(?![\\w.\\[/])`, "g");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("Tailwind spacing scale", () => {
  it("defines every numeric spacing step the source uses", () => {
    const steps = new Set(Object.keys(config.theme?.spacing ?? {}));
    const missing = new Set<string>();
    for (const file of files(join(__dirname, "..", "src"))) {
      for (const m of readFileSync(file, "utf8").matchAll(CLASS)) {
        if (!steps.has(m[2]!)) missing.add(`${m[1]}-${m[2]} in ${file.split("src/")[1]}`);
      }
    }
    expect([...missing]).toEqual([]);
  });
});
