import { ApiError, type AskJob } from "@/lib/api";
import type { Phase, Turn } from "./AskTurnBlock";

/** What a turn shows of its job (D269) so far: the SQL step's answer, the rows as soon as
 * the query ran, the summary once written, each step with its time. `now` marks when a
 * step was first seen running, for its live elapsed time. */
export function fromJob(job: AskJob, turn: Turn, now: number): Partial<Turn> {
  const seen = { ...turn.seen };
  for (const s of job.steps) seen[s.name] ??= now;
  const ms = (name: string) => job.steps.find((s) => s.name === name)?.ms ?? undefined;
  const answer = job.ask ?? turn.answer;
  const result = job.result ?? undefined;
  const last = job.steps.at(-1)?.name;
  let phase: Phase;
  if (job.state === "failed") phase = "failed";
  else if (job.state === "running")
    phase = last === "summary" ? "writing" : last === "run" ? "running" : "finding";
  else if (answer?.route?.kind === "knowhow") phase = "guidance";
  // A bare address, host, or user name (D276): its page, nothing to run.
  else if (answer?.lookup?.length) phase = "lookup";
  else phase = result ? "done" : "ready";
  return {
    phase,
    answer,
    result,
    // A Run click's job starts at the query: the line keeps the step that wrote it.
    steps: job.steps.some((s) => s.name === "sql")
      ? job.steps
      : [...(turn.steps ?? []).filter((s) => s.name === "sql"), ...job.steps],
    seen,
    summary: job.summary ?? undefined,
    summaryNote: result?.summary_note ?? undefined,
    willSummarize: Boolean(result?.summarize),
    askMs: ms("sql") ?? turn.askMs,
    runMs: ms("run"),
    summaryMs: ms("summary"),
    // A failed job is a 200 that says why, in the words the server's error would use.
    error: job.error ? new ApiError(200, job.error.message, job.error.code) : undefined,
  };
}

/** A turn that failed, or whose job is gone: every step still running ends there, "stopped
 * at" the time it had run, so nothing keeps counting or asking about the model's queue. */
export function stopped(turn: Turn, error: unknown, now: number): Partial<Turn> {
  return {
    phase: "failed",
    error,
    steps: (turn.steps ?? []).map((s) =>
      s.state === "running"
        ? { ...s, state: "failed" as const, ms: now - (turn.seen?.[s.name] ?? now) }
        : s,
    ),
  };
}

/** How often a running job is read: every 0.5 s for its first reads, then every second. */
export function pollEvery(reads: number): number {
  return reads < 6 ? 500 : 1000;
}

/** A turn whose job the page stops following while it runs: its running steps end there,
 * and it shows what it has (its rows, or that it stopped). */
export function halted(turn: Turn, now: number): Partial<Turn> {
  if (!turn.steps?.some((s) => s.state === "running")) return {};
  const done = stopped(turn, new ApiError(0, "Stopped: another question started."), now);
  return turn.result ? { ...done, phase: "done", error: undefined } : done;
}
