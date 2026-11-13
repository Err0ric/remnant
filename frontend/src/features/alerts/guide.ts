import type { AlertItem } from "@/lib/api";

/** What kind of thing fired, for filters and the summary (ADR-0043): the AI Watch rule, or
 * the alert kind for everything else. */
export type Category = "detection" | "search" | "ai" | "gap";

export const CATEGORY_LABEL: Record<Category, string> = {
  detection: "Detections",
  search: "Saved searches",
  ai: "AI Watch",
  gap: "Source gaps",
};

export function categoryOf(i: AlertItem): Category {
  if (i.kind === "rule") return "detection";
  if (i.kind === "schedule") return "search";
  if (i.kind === "gap") return "gap";
  return "ai";
}

/** The rule behind an alert, from its group or how it was named. */
export type Rule =
  | "agent_change"
  | "agent_busy"
  | "agent_review"
  | "blocked_calls"
  | "personal_account"
  | "sensitive"
  | "service_review"
  | "mcp_review"
  | "gap"
  | "queue"
  | "refusals"
  | "rule"
  | "schedule";

export function ruleOf(i: AlertItem): Rule {
  if (i.rule === "agent_change" || i.rule === "agent_busy" || i.rule === "blocked_calls")
    return i.rule;
  if (i.kind === "gap") return i.subject.includes("/") ? "queue" : "gap";
  if (i.kind === "rule") return i.subject.startsWith("refusals:") ? "refusals" : "rule";
  if (i.kind === "schedule") return "schedule";
  if (i.subject.startsWith("account:")) return "personal_account";
  if (i.subject.startsWith("sensitive:")) return "sensitive";
  if (i.subject.startsWith("service:")) return "service_review";
  if (i.subject.startsWith("mcp:")) return "mcp_review";
  return "agent_review";
}

/** Why the rule exists, in one sentence, and what to do next (ADR-0043 layout). */
export const GUIDE: Record<Rule, { why: string; steps: string[] }> = {
  agent_change: {
    why: "An agent reached something new: an MCP server or tool it had not used before, or a new model.",
    steps: [
      "Open the person's AI use and check the new server or tool in their sessions.",
      "If it is expected, close as Approved: the agent is marked reviewed.",
      "If it should not be used, mark the MCP server Not approved on AI usage.",
    ],
  },
  agent_busy: {
    why: "The agent did far more in an hour than it usually does.",
    steps: [
      "Open the person's AI use and look at the busy session's tool calls.",
      "A long refactor or a batch job is Expected; repeated calls to one host or command are worth a closer look.",
    ],
  },
  agent_review: {
    why: "A new agent appeared and nobody has reviewed it yet.",
    steps: [
      "Check whose agent it is and which machines it runs on.",
      "Close as Approved to mark it reviewed, or Resolved once it is dealt with.",
    ],
  },
  blocked_calls: {
    why: "Many tool calls were blocked or failed in one hour: a policy, a broken tool, or someone pushing past a block.",
    steps: [
      "Open the person's AI use and see which tool and commands failed.",
      "If a hook or permission rule blocked them, confirm with the person what they were trying to do.",
      "Close as Resolved with what you found, or False positive if a tool was simply broken.",
    ],
  },
  personal_account: {
    why: "Claude Code ran on a company device signed in with an account outside the organization's email domains.",
    steps: [
      "Confirm the account with the person; company work belongs on the company account.",
      "If it is allowed (a test device, a contractor), close as Expected or Approved with a note.",
    ],
  },
  sensitive: {
    why: "Data that looks sensitive was sent to an AI service.",
    steps: [
      "Check what was sent and to which service, and whether that service is allowed that data.",
      "Talk to the person, then close as Resolved with what was done.",
    ],
  },
  service_review: {
    why: "An AI service is in use that nobody has reviewed yet.",
    steps: [
      "Decide whether it is allowed. An administrator chooses Approve or Not approved under Evidence, changes, and history, or on AI usage.",
      "Close as Approved to approve it in one step (administrators).",
    ],
  },
  mcp_review: {
    why: "An MCP server is in use that nobody has reviewed yet.",
    steps: [
      "Check what the server can reach before deciding.",
      "Approve it, or mark it Not approved so its use stands out.",
    ],
  },
  gap: {
    why: "A watched source stopped sending, so its events are missing from searches and rules.",
    steps: [
      "Open it on Health to see when it stopped and what the collector last said.",
      "Fix the collector or the network path; the alert notes when events arrive again.",
    ],
  },
  queue: {
    why: "A machine's hooks plugin is holding records it could not deliver.",
    steps: [
      "Check the machine is online and can reach the receiver.",
      "Once it delivers again, close as Resolved.",
    ],
  },
  refusals: {
    why: "One address had many credentials refused in a few minutes: guessing tokens or passwords.",
    steps: [
      "Look up the address and what it was trying to reach.",
      "Block it at the firewall if it is not yours, then close as Resolved.",
    ],
  },
  rule: {
    why: "A detection rule matched events in its range.",
    steps: [
      "Read the rows that fired and open the events around one of them.",
      "Close as Resolved if it was real, or False positive with a note so the rule can be tuned.",
    ],
  },
  schedule: {
    why: "A scheduled search crossed its threshold.",
    steps: [
      "Read the rows that fired.",
      "Close as Expected if the change is known, or Resolved once dealt with.",
    ],
  },
};

type Status = NonNullable<AlertItem["review_status"]>;

/** "Why it matters" and the next steps for an AI service or MCP server alert follow the
 * catalog status now, not the one it had when the alert was raised (owner item 5). */
const BY_STATUS: Record<"service_review" | "mcp_review", Partial<Record<Status, Guide>>> = {
  service_review: {
    not_approved: {
      why: "This AI service is marked Not approved, and it is still being used.",
      steps: [
        "Find out who used it: open the person, or the device when no person is named.",
        "Ask them to stop and use an approved service instead.",
        "Close as Resolved with what was done, or Approve the service if it should be allowed (administrators).",
      ],
    },
    unknown: {
      why: "An AI service is in use that is not in the AI service catalog, so it has no review status.",
      steps: [
        "Check what the service is and who used it.",
        "Close as Resolved with a note once it is dealt with.",
      ],
    },
    approved: {
      why: "This AI service was approved after the alert was raised.",
      steps: ["Close as Approved; nothing else is needed."],
    },
  },
  mcp_review: {
    not_approved: {
      why: "This MCP server is marked Not approved, and an agent is still using it.",
      steps: [
        "Open the person's AI use and see which sessions called it.",
        "Ask them to remove it, then close as Resolved with what was done.",
      ],
    },
    approved: {
      why: "This MCP server was approved after the alert was raised.",
      steps: ["Close as Approved; nothing else is needed."],
    },
  },
};

interface Guide {
  why: string;
  steps: string[];
}

/** The guide for one alert: its rule's, or for a service or MCP server its status's. */
export function guideFor(i: AlertItem): Guide {
  const rule = ruleOf(i);
  if ((rule === "service_review" || rule === "mcp_review") && i.review_status)
    return BY_STATUS[rule][i.review_status] ?? GUIDE[rule];
  return GUIDE[rule];
}

const SEV_ORDER: Record<string, number> = { high: 0, medium: 1 };

export function bySeverityThenNewest(a: AlertItem, b: AlertItem): number {
  const s = (SEV_ORDER[a.severity ?? ""] ?? 2) - (SEV_ORDER[b.severity ?? ""] ?? 2);
  if (s) return s;
  return (b.last_seen ?? b.created_at).localeCompare(a.last_seen ?? a.created_at);
}

const lit = (v: string) => `'${v.replace(/'/g, "''")}'`;

/** The events behind an alert, for Show events: the person's or machine's records over the
 * alert's span, or the source's for a gap. The SQL goes to Search, where it runs through
 * the guard on the viewer's own sources. None when the alert names nothing to filter on. */
export function evidenceSql(i: AlertItem): string | null {
  const where: string[] = [];
  const person = i.people?.[0];
  const device = i.devices?.[0];
  if (person) where.push(`actor_user_name = ${lit(person)}`);
  else if (device) where.push(`device_hostname = ${lit(device)}`);
  else if (i.kind === "gap" && !i.subject.includes("/"))
    where.push(`source_id = ${lit(i.subject)}`);
  else return null;
  if (categoryOf(i) === "ai") where.push("template_id IN ('claude_hooks', 'claude_code_otel')");
  return (
    "SELECT time, source_id, device_hostname, actor_user_name, message, event_id\n" +
    `FROM events\nWHERE ${where.join("\n  AND ")}\n` +
    "  AND coalesce(time, time_observed) >= TIMESTAMPTZ '{from}'" +
    " AND coalesce(time, time_observed) < TIMESTAMPTZ '{to}'\n" +
    "ORDER BY coalesce(time, time_observed) DESC"
  );
}
