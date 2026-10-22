# Every result offers the next click

Status: **Proposal** 2026-10-22, for owner review. Only part (c), Add to dashboard, is built (D89); everything else here is a plan.

## Why

The first install on real data showed where the app still makes people work by hand:

| Finding | What it cost |
|---|---|
| Real answers needed hand-written SQL | AI services by device, who had an address, parser mix, and firewall maintenance were all regex queries over `raw` |
| Pivoting between address, device, and person took separate queries | An address in a result led to a DHCP query, then a VPN query, then an auth query, each typed |
| Dashboards needed a schedule first | A useful result had to be saved, then scheduled, then found on the Dashboard |
| Loki onboarding was guesswork | Which labels exist, how much each sends, and which template fits were found by trial |
| Empty pages explained but did not act | Many empty states say what is missing; few have the button that fixes it |

The principle: **every result offers the next click**. A value in a table is a door (to its context, to a filter, to an investigation); a result is one click from a panel; an empty page is one click from the setup step that fills it.

Design rules that hold throughout (DESIGN.md): plain labels, text command buttons, monospace for data, detail in place (no modals for reading data), one accent, severity colors only for severity, dense layout, keyboard reachable.

## (a) Discover from Loki

Today: Sources > Discover scans a folder: candidates grouped by host and pattern, sniffed, matched to templates (Slice 3). A Loki source is added by typing a URL and a LogQL selector and hoping the volume and the parser fit.

Proposal: the same Discover flow for a Loki URL.

1. **Connect**: the Loki URL (offered from existing Loki sources, F27), tenant and auth as today.
2. **Label inventory**: `GET /loki/api/v1/labels` and `/label/{name}/values`, then one `query_range` count per candidate stream group over the last hour (`count_over_time`, a metric query, run server-side with the same network rules as the poller). Grouped by the labels that usually name a source (`job`, `app`, `service_name`, `host`, `container`).
3. **Suggestions**: per group, a 200-line sample through the template matcher (the folder Discover code), showing the best template and its confidence, and whether the labels stand in for a missing syslog header (D76).
4. **Volume warnings**: lines per hour and an estimate per day; groups above a threshold (default 1 million lines a day) are flagged "High volume" with the suggested line filter (`!= "DEBUG"`, or for `slapd` the stats filter from its template description).
5. **Create**: checked groups become Loki sources with the selector filled in, the template chosen, and the classification default `local_only`. Nothing is created without the checkbox and the Create click; each creation is audited `source.create` as today.

```
Settings > Sources > Discover from Loki
+------------------------------------------------------------------------------------+
| Loki  [ http://10.20.0.40:3100          v ]  Tenant [        ]  [ Scan labels ]     |
+------------------------------------------------------------------------------------+
| Streams in the last hour                         lines/h   per day  parser   conf.  |
| [x] {job="syslog", app="named"}                   41,200     ~990K  dns_bind  0.98  |
| [x] {job="syslog", app="authelia"}                   310       ~7K  authelia  0.96  |
| [ ] {job="syslog", app="slapd"}                  610,000     ~15M  openldap  0.99  |
|     High volume. Suggested filter:  |~ "ACCEPT|BIND|RESULT tag=97|closed"           |
| [ ] {job="docker", container="grafana"}            2,100      ~50K  generic   0.40  |
|     No template fits. Draft a parser from a sample                                  |
+------------------------------------------------------------------------------------+
| 2 selected, about 1M lines a day                    Cancel   Create 2 sources       |
+------------------------------------------------------------------------------------+
```

Needs: an ADR (a new outbound call pattern to Loki: label and metric queries) before building. Cost: one count query per group at scan time only.

## (b) Entity pivots: a context panel for any address, host, or user

Today: Event detail has Filter for, Filter out, Top values, and Investigate per field (good). The Investigation page has entity mode. What is missing is the answer to "who or what is this" in place, without leaving the result.

Proposal: any value in a column the schema knows is an entity (`src_endpoint_ip`, `dst_endpoint_ip`, `device_ip`, `*_hostname`, `actor_user_name`) is underlined on hover; clicking it opens a context panel **under the row** (detail in place), with sections that each come from one fixed, server-built query in the caller's scope:

| Section | Address | Host | User |
|---|---|---|---|
| Held by (at the event's time) | DHCP device and MAC, VPN person and laptop, logon and User-ID person (ADR-0029 spans) | Addresses it held today | Devices and addresses seen with them |
| Recent sign-ins | Successes and failures to and from it | Logons on it | Their sign-ins: where from, results |
| AI services | Catalog services it reached | Same | Same, with the AI usage page link |
| Detections | Rule matches and flagged schedules naming it | Same | Same |
| Next | Search all its events, Investigate, Add to dashboard (its activity by hour) | Same | Same |

```
| 13:05:12  dns  10.20.1.5  chatgpt.com  A  ...                                     |
|   +--------------------------------------------------------------------------+    |
|   | 10.20.1.5                     at 13:05 UTC on 2026-10-09                 |    |
|   | Held by     LAPTOP-B  00:00:5e:00:53:0b  (DHCP, since 12:00)             |    |
|   |             no VPN or logon user for this address at that time         |    |
|   | Sign-ins    4 success, 0 failure today          Show                     |    |
|   | AI          ChatGPT 12, Claude 3 today          AI usage                 |    |
|   | Detections  none in 24 h                                                 |    |
|   | Search its events   Investigate   Add to dashboard                       |    |
|   +--------------------------------------------------------------------------+    |
```

Rules: names of people follow ADR-0029 governance (masked without the permission); every open writes one audit row (`entity.context`); the panel never calls a model. Depends on ADR-0029 for "Held by"; the other sections can ship first.

## (c) Add to dashboard (built, D89)

Today: a result reaches the Dashboard only through Save, then Schedules > New schedule, then waiting for the first run.

Built: **Add to dashboard** next to Save in the Search command bar, and on any saved search. One step creates the schedule with defaults and runs it once so the panel is filled at once:

| Default | Value | Why |
|---|---|---|
| Schedule | Hourly | Fresh enough for a dashboard, light on the server |
| Range | Last 24 hours (`lookback_minutes = 1440`) | What a dashboard panel usually means |
| View | Bars when the result is a label and a count, otherwise a table | Summary results read better as bars (D82) |
| Width | A third | Same as today's default |
| Sharing | Private | Sharing stays a deliberate choice |

From Search, an unsaved query is saved first with a name the user confirms (the same Save form, one field), because schedules run saved searches (SPEC 5.5: the schedule pins the search's hash). The form shows the defaults on one line with a Change link to the full schedule form.

```
Search  >  command bar:   Run query   Save   Add to dashboard   Schedule   Export
+---------------------------------------------------------------------+
| Add to dashboard                                                    |
| Name   [ AI services from DNS                    ]                  |
| Hourly, last 24 hours, bars, a third wide, private.  Change         |
|                                       Cancel   Add to dashboard     |
+---------------------------------------------------------------------+
```

## (d) Empty states with an action on every page

Today most empty states explain; some link. Proposal: every empty state names what fills it and has one button that goes there, in accent text, and admins and analysts see the action they can take (an analyst sees who to ask).

| Page | Empty when | Button |
|---|---|---|
| Overview | No sources | Add a log source (Sources > Add), or Discover from Loki |
| Dashboard | No panels | Add an example panel (imports `parser_mix` and adds it), Go to Search |
| Search | No rows | Widen to 7 days; Remove source filter; Show parser mix for these sources |
| Saved searches | None | Import an example (the six in `examples/saved-searches`) |
| Schedules | None | Add to dashboard from a saved search |
| Detection rules | None | Import the SigmaHQ core rules (Sigma import) |
| AI usage, Services | No DNS, firewall, or proxy source | Add a DNS source; Discover from Loki |
| AI usage, Claude usage | No telemetry | Set up Claude Code telemetry (the OTLP source wizard) |
| Investigations | Nothing selected | Most active users, addresses, hosts (already there); Pick from Search |
| Identities | No identity map | Import from Microsoft 365 sign-ins |
| Health, Agents | No agents | Download an agent config |
| Alert targets | None | Add Slack, Teams, email, or webhook (admins); "Ask an administrator" (others) |
| Audit log | Filter matches nothing | Clear filters |

## (e) Where people type SQL today, and what should replace it

| Where | What people type | Built-in view that replaces it | Depends on |
|---|---|---|---|
| Search, SQL tab: AI by device | DNS regex plus a DHCP join | AI usage "Who" column names devices (ADR-0029); example `ai_services_by_device` until then | ADR-0029 |
| Search: who had an address | DHCP and VPN regex | Context panel "Held by" (b) | ADR-0029 |
| Search: parser mix | `GROUP BY source_id, template_id, parse_status` | Sources page column "Parsed by" with the mix as a bar; example `parser_mix` | none |
| Search: firewall maintenance | Regex on PAN system descriptions | Health tab "Device events" for firewall system logs (HA, commits, restarts); example `firewall_maintenance` | none |
| Search: SSH sign-ins | `linux_sshd` filters | Investigations preset "Sign-ins" (user, source, result) | none |
| Search: top talkers, top denied | `GROUP BY src_endpoint_ip` | Facet sidebar already lists top values; add "Top N by" on any column header | none |
| Saved search to Dashboard | Save, then schedule | Add to dashboard (c) | built |
| Sources, Loki query | LogQL selector by hand | Discover from Loki (a) | ADR needed |
| Schedules, threshold | Numbers per schedule | Suggest from the last 7 days (median times 3) | none |
| Templates, new parser | YAML | Draft from sample exists; add "Draft from these lines" on generic rows in Search | none |
| Health, quiet sources | Typing a source's normal volume | Learned from history (already, ADR-0014) | done |

## Order

1. (c) Add to dashboard (built tonight, small).
2. (d) Empty-state actions (no ADR; one PR per few pages).
3. (e) the no-dependency rows: parser mix on Sources, Top N by on column headers, Sign-ins preset, threshold suggestion.
4. (b) Context panel without "Held by"; then with it after ADR-0029.
5. (a) Discover from Loki after its ADR.
