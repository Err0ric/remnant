/** "How this is counted" for every number on the Dashboard, Microsoft 365, Agents, AI
 * Watch, and Health (owner, 2026-11-02): which events, which sources, what window, what is
 * left out, and the rule used, in plain words. Every KPI component requires one, so a new
 * number cannot ship without it (tests/kpiAbout.test.tsx). */

const WINDOW =
  "In the window picked at the top of the page, against the window of the same length before it.";

export const COUNTED = {
  // Dashboard > Identity and Microsoft 365 > Overview (Microsoft 365 sources only).
  signIns: `Every Microsoft Entra sign-in from the Graph sign-in logs, interactive and background, succeeded or not. ${WINDOW}`,
  outside: `Successful Microsoft Entra sign-ins whose address GeoIP places in a country not on the approved list (Settings > Enrichment). Addresses GeoIP cannot place are not counted. ${WINDOW}`,
  mailRules: `New or changed Exchange inbox rules (New-InboxRule, Set-InboxRule, UpdateInboxRules) and mailbox forwarding changes, from the Management Activity API, one per record. Risky means the rule hides, deletes, or forwards mail outside your domains; organizing rules are counted apart. ${WINDOW}`,
  consents: `Microsoft 365 app consents granted, from directory audits and the Management Activity API, the same consent counted once. Blocked consent attempts are counted apart, not added in. ${WINDOW}`,
  roleGrants: `Entra "Add member to role" and "Add eligible member to role" changes from directory audits, one per change (several records of one change counted once). ${WINDOW}`,
  caEdits: `Conditional Access policy adds, updates, and deletes from directory audits, one per change. ${WINDOW}`,
  adminChanges: `Entra role grants plus Conditional Access policy edits from directory audits, one per change. ${WINDOW}`,
  blocked: `Failed Microsoft Entra sign-ins with error code 53003 (blocked by Conditional Access). These are also counted in Failed sign-ins. ${WINDOW}`,
  risky: `Microsoft Entra sign-ins Microsoft rated medium or high risk (any outcome). Microsoft only reports risk levels with Entra ID P2; without it this stays 0. ${WINDOW}`,

  // Dashboard > Attacks and access (every login source except Microsoft 365).
  externalFailures: `Failed logins (OCSF authentication events with a failure status) from every source except Microsoft 365: SSH and PAM, Windows logons, VPN (GlobalProtect, OpenVPN), firewalls, and any other template that maps logins. External means the source address is not in your internal networks (private ranges and the networks listed in Settings > Enrichment). Events with no source address are left out. ${WINDOW}`,
  attackingAddresses: `Distinct external source addresses with at least one failed login in the window, from the same events as External sign-in failures. One address counts once however many failures it had. ${WINDOW}`,
  countries: `Distinct countries those attacking addresses are placed in by the local GeoIP file. Addresses it cannot place are left out, so this can be lower than the addresses. Needs a GeoIP file (Settings > Enrichment). ${WINDOW}`,
  vpnOutside: `Successful VPN logins (GlobalProtect, OpenVPN) whose address GeoIP places outside the approved countries. Addresses GeoIP cannot place are not counted. ${WINDOW}`,

  // Dashboard > Detections (Sigma rules).
  ruleMatches: `Detection rule matches on sources you may read, one per rule and event: an event two rules matched counts twice. ${WINDOW}`,
  rulesMatched: `Detection rules with at least one match in the window, shown against how many rules are enabled. ${WINDOW}`,
  hostsInvolved: `Distinct host names on the matched events. Events with no host are left out. ${WINDOW}`,
  usersInvolved: `Distinct user names on the matched events. Events with no user are left out. ${WINDOW}`,

  // Agents > Overview (the Claude hooks plugin's records).
  sessions: `Claude Code and Cowork sessions (distinct session ids) with at least one hooks plugin record in the window. ${WINDOW}`,
  agentPeople: `Distinct people on hooks plugin records: the Claude account email, else the computer's user name. ${WINDOW}`,
  toolCalls: `Tool calls the hooks plugin recorded (one per "before tool use" record), built-in tools and MCP tools alike. A copy sent twice from the offline queue counts once. ${WINDOW}`,
  failedCalls: `Tool calls the hooks plugin recorded as failed. ${WINDOW}`,
  mcpNotApproved: `Distinct MCP servers called through the hooks plugin marked not approved on AI usage (unreviewed ones are not counted here). ${WINDOW}`,
  lateDevices: `Machines whose hooks plugin records arrived an hour or more after they happened (sent later from the plugin's offline queue). ${WINDOW}`,

  // Health.
  events24h:
    "Events stored from every source you may read in the last 24 hours, by when each event happened, against the 24 hours before.",
  sourcesHealthy:
    "Turned-on sources reading without errors or warnings, not quiet past their limit, and with no gap in event volume in the last 24 hours. Paused sources are counted in the total but never healthy.",
  openAlerts:
    "Alerts not yet resolved or dismissed, from rules and schedules on sources you may read.",
  delivery:
    "Alert messages to email, chat, and webhook targets that failed in the last 24 hours, after retries. A target that is failing right now is named.",
} as const;

/** Microsoft 365 > Overview counts row, by key. All from the Management Activity API, one
 * operation per record. */
export const M365_COUNT_COUNTED: Record<string, string> = {
  mail_rules: COUNTED.mailRules,
  dlp: `Microsoft Purview DLP rule matches (DlpRuleMatch). ${WINDOW}`,
  downloads: `SharePoint and OneDrive file downloads, including full sync downloads (FileDownloaded, FileSyncDownloadedFull). ${WINDOW}`,
  external_shares: `Anonymous links and sharing invitations created in SharePoint and OneDrive (AnonymousLinkCreated, SharingInvitationCreated). ${WINDOW}`,
  copilot: `Microsoft 365 Copilot interactions (CopilotInteraction), one per prompt and answer. ${WINDOW}`,
};

/** Microsoft 365 > Sign-in outcomes, by class (D158). */
export const OUTCOME_COUNTED: Record<string, string> = {
  Succeeded: "Microsoft Entra sign-ins with error code 0, interactive and background.",
  Failed:
    "Real failures: the error codes classed failed in this install's sign-in classes (wrong password, locked, MFA denied, blocked by Conditional Access, and others). These are the Failed sign-ins number.",
  Interrupted:
    "Sign-ins that stopped for a step the person then took (MFA prompt, stay signed in, consent). Not counted as failures.",
  Expired:
    "Expired or revoked sessions and tokens refreshed in the background. Not counted as failures.",
  Other: "Failed sign-ins whose error code is in no class. Counted apart, never dropped.",
};

/** AI Watch cards (ADR-0038 row 13), by card key. */
export const AI_WATCH_COUNTED: Record<string, string> = {
  services:
    "AI services from the catalog seen in DNS, firewall, proxy, and Claude telemetry that are not yet approved: Not approved (decided against) and Unreviewed (no decision yet), shown apart below the number. Unreviewed is not a violation. In the range picked, against the range before.",
  people:
    "Distinct people seen reaching a service that is not yet approved (Not approved or Unreviewed, shown apart below the number). A person is the user name on the event, or, for network logs that only have an address, the person that address maps to from sign-ins and DHCP in the same hour. Devices no person maps to are counted apart, never added in. In the range picked, against the range before.",
  agents:
    "AI agents and MCP servers first seen in this range: Claude Code per person, MCP setups per machine and client, and API keys, from telemetry, the hooks plugin, the MCP inventory, and the Anthropic usage connector.",
  consent:
    "Microsoft 365 app consents granted in this range, Graph and the Management API counted once. Blocked attempts are shown apart.",
  sensitive:
    "Sensitive data signals Claude Code telemetry reported (keys, tokens, card numbers), one per prompt or tool input that had one. The content itself is never stored.",
};
