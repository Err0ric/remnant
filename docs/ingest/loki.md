# Reading from Grafana Loki

If your logs already go to Loki, the app can copy them from there instead of reading files. It asks Loki for new lines every 30 seconds, keeps its own copy, and parses each line exactly as it would a line from a file. With the **Automatic** parser (the default) each line goes to the template that fits it, so one query can return sshd, sudo, firewall, and application lines together. Loki is not changed and keeps its own data.

## What you need from whoever runs Loki

| Item | Example | Notes |
|---|---|---|
| Loki URL | `http://loki.internal:3100` | The Loki root, reachable from the server running the app. `https` is required unless the address is private (10/8, 172.16/12, 192.168/16, loopback) |
| Sign-in | none, username and password, or a token | For Loki behind a gateway or Grafana Cloud |
| Tenant | `team-a` | Only for multi-tenant Loki; sent as `X-Scope-OrgID` |
| Labels | `{job="syslog", host=~"fw.*"}` | Which streams to read. `curl $LOKI/loki/api/v1/labels` lists the label names; `curl $LOKI/loki/api/v1/label/job/values` lists the values of one |
| Line format | raw syslog, JSON, Palo Alto CSV | Automatic handles a mix; pick one template only when every line is the same product |

## Adding the source

1. Sources > Add source, and set **Reads from** to **Grafana Loki**.
2. Fill in the URL, the query, and sign-in. The query is a label selector, optionally followed by line filters: `{job="syslog"} |= "sshd" != "CRON"`. Parsers such as `| json` are not accepted; the app's templates do the parsing.
3. Click **Test connection**. It reads up to 100 lines from the last hour and lists the streams that matched. "No lines matched" usually means the labels are wrong or the streams are quiet.
4. Leave the parser on Automatic (or pick one template when every line is from one product), and how many hours to read back on the first run (24 by default).
5. Add the source. New events appear within a minute. Like every source it starts **local only**.

## Good to know

- Each line is kept exactly as Loki returned it in `raw`. The stream labels are kept in `envelope.loki_labels`, so a search can use them: `json_extract_string(envelope, '$.loki_labels.host')`.
- If a line has no timestamp of its own (common when the shipper strips the syslog header), the event time is Loki's timestamp for that line.
- Reading stops 30 seconds short of now, so lines that reach Loki a little late are still picked up. The Sources page shows how far behind each Loki source is.
- If the app is stopped for a while, it carries on from where it stopped. It reads at most 20,000 lines per source every 30 seconds while catching up.
- Credentials are stored encrypted and are never shown again; to change them, remove the source and add it again.

## Trouble

| Message | Likely cause |
|---|---|
| Loki refused the credentials (HTTP 401 or 403) | Wrong token or password, or a missing tenant |
| No Loki API at this URL (HTTP 404) | The URL points at Grafana or a path under Loki; give the Loki root |
| Loki rejected the query (HTTP 400) | A label name or value is wrong, or the selector matches everything (Loki needs at least one matcher that is not empty) |
| Public addresses need https | The URL is public and uses `http` |
| Address ... is not allowed | The host resolves to a link-local or cloud metadata address |
