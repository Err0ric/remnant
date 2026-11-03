# Claude Code sessions: the hooks plugins (pilot guide)

The hooks plugins send one record per session event from Claude Code to this server: session start, each prompt, each tool call and its result or failure, each turn end, and session end. On the AI usage page, **Agents** lists the people and their tools, and **Sessions** shows each session in order (ADR-0026 and its 2026-10-29 amendment).

They only observe. A plugin never blocks, changes, or slows anything: each hook runs in the background, waits at most 2 seconds for the server, ignores every error, prints only `{}` (never the server's answer), and always exits 0. A server that is down, slow, or hostile cannot change what Claude does.

## What it covers

| Client | Plugin | Notes |
|---|---|---|
| Claude Code on Windows (terminal, IDE extension, desktop app's Code tab) | **Windows** | Windows PowerShell 5.1, which every Windows 10 and 11 machine has. Nothing to install, no Git Bash |
| Claude Code on macOS and Linux | **macOS and Linux** | `sh`, `awk`, `sed`, `curl`, and `shasum` or `sha256sum`, all already there |
| Cowork tasks | Not yet | A separate plugin, after the pilot checks a Cowork session can reach this server |
| Chat on claude.ai, the desktop app's Chat tab, the mobile apps | No | Chat ignores plugin hooks. Network logs and the AI service catalog still show the traffic |

Each plugin stands aside on a session that belongs to another (the Windows one on macOS, Linux, and Cowork; the macOS and Linux one on Windows and Cowork), so a machine with two plugins never sends twice.

## What it sends

| Always (metadata) | Only when the source keeps content |
|---|---|
| Event, time, session id, `role` (session, user, tool_call, tool_result, turn) | Prompt text |
| The Claude account email, and where it came from (`managed`, `env`, or `claude_json`) | Tool input |
| The OS user and the machine name | Tool output |
| Tool name; MCP server and tool; the working folder | A failed tool's error text |
| The file path, web host, or program name a tool touched | |
| Sizes; SHA-256 of the prompt and tool input; how many earlier records could not be sent | |

The Claude account email is the first of: `CLAUDE_EMAIL` in the machine-wide config, the `CLAUDE_CODE_USER_EMAIL` variable, and `oauthAccount.emailAddress` in `.claude.json` (in `CLAUDE_CONFIG_DIR`, else the home folder). Nothing else is read from that file. A session signed in with an API key has no account email; it shows as "Not checked" (ADR-0030).

Content follows the source's **Keep prompt and tool content** setting at download time. Each piece is cut to its first and last 4 KB on the machine, and the server masks secrets it detects (keys, tokens, card numbers) before storing, after counting them. Whatever arrives is stored as data and never given to a model as instructions.

## 1. Make a source for it

**Sources > Add source**, **Reads from: OpenTelemetry (OTLP)**, Source ID for example `claude_hooks`, Parser **Automatic**. Use a source just for the plugins. Download the plugin from **Settings > Claude plugins**: each deployment ("pilot", "all Windows") gets its own named token, and a later download for the same deployment carries the same token. Revoking one token stops that deployment only.

## 2. Download a plugin per platform

On **Settings > Claude plugins** (the only place that issues plugin tokens; the source's row links there):

- **Deployment token**: **New token** with a name ("pilot", "all Windows"), or an existing deployment's token, so a later download carries the same one. Revoking a token stops every copy that carries it, and only those.
- **Server address**: what people's machines reach this server at, for example `https://siem.example.internal:8080`. It must be `https`.
- **Pilot users**: Claude account emails or OS user names. Only they send, wherever the plugin is installed. Empty: everyone who installs it, and the page says so before you download.
- **Include this server's self-signed certificate** (shown when this server serves its generated certificate): the scripts then check the server against it. It is off by default when people reach the server through a reverse proxy (trusted proxies are set) or when the address you give is not a name on the server's certificate, because the proxy's certificate is the one their machines see and pinning this one would break every send. The line under the checkbox says which applies. There is no option to skip checking.
- Then **Download plugin** (for one machine or the organization library) or **Download managed bundle** (for the fleet, step 3b) for **Windows** or **macOS and Linux**.

The page shows the version and the SHA-256 of each platform's script (`hooks/send.ps1` or `hooks/send.sh`); check it against the zip before you publish. Each script is short enough to read in one sitting. Downloads are audited (`source.claude_plugin`, with the platform and pilot list, never the token).

## 3. Publish

Three paths, in the order to try them. Whichever you use, run the pilot checks (step 7) first on one machine.

**The desktop app's Code tab cannot install plugins**: `/plugin` there answers "/plugin isn't available in this environment". Install from a terminal with the Claude Code CLI (`claude`), as below.

### 3a. One machine: the local installer

For testing on your own machine. The plugin download carries an installer for its platform:

| Platform | Run from the unzipped plugin folder |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File .\install-local.ps1` |
| macOS, Linux | `sh install-local.sh` |

It copies the folder into a local marketplace (`<product>-local`, under `%LOCALAPPDATA%` or `~/.local/share`), then runs `claude plugin marketplace add <that folder>` and `claude plugin install <plugin name>@<product>-local --scope user`, and prints `claude plugin list`. Running it again replaces the earlier copy. Remove it with `claude plugin marketplace remove <product>-local`. The plugin then runs in Claude Code sessions started from the terminal; run pilot check 1 in each client you rely on (the desktop app's Code sessions included) before counting on it there.

### 3b. Fleet: the managed bundle plus the plugin

For everyone on a platform. The managed bundle holds the plugin (its own config empty, so it sends nothing by itself), `hooks.conf`, and a README:

1. Deploy `hooks.conf` (and `server-ca.pem`, if included) with your endpoint management tool to the machine-wide path in step 4, for example `%ProgramData%\siem-claude-hooks\hooks.conf` on Windows.
2. Get the plugin onto those machines: run the plugin's install (as in 3a, with the managed bundle's `plugin-<platform>.zip`) from the same tool as each user, or require a marketplace that lists it in managed settings ("Manage plugins for your organization" in the Claude Code docs).

The machine-wide file wins over the plugin's own config, so the address, token, and certificate stay under your tool's control.

### 3c. Organization library upload

Organization plugins need a Team or Enterprise plan and an Owner (or Primary Owner) to publish (Anthropic support article "Manage plugins for your organization").

1. **Organization settings > Plugins & skills > Marketplaces > Add > Upload a plugin**. Upload each platform's zip.
2. **Default access**: **Available to install**, **Installed by default**, or **Required**. Installed by default and Required apply to every member: that screen has no per-user or per-group audience, so use **Pilot users** in the plugin to limit who sends.

**Tested on the Windows desktop app (2026-11-02):** a plugin set to **Available to install** and then turned on for one account landed under `%LOCALAPPDATA%\Claude-Data\...\plugin_<id>\`, but its hooks never ran in the desktop app's local Code sessions (no spool folder, no records). The same plugin sent records when its script was run by hand. Until that changes, prefer 3a or 3b for the desktop app, and confirm any path there with pilot check 1.

### Which install paths fire hooks

| Path | Hooks fire? | Evidence |
|---|---|---|
| Script run by hand (`send.sh` or `send.ps1` with a hook payload on stdin) | Yes | Owner's test install, Windows, 2026-11-02: records reached the server |
| Terminal CLI: `claude plugin install` from a marketplace (3a, `install-local`) | Untested on a real client | The installer is tested against a stand-in `claude` that records its calls; that the CLI then runs the hooks in a session is not yet confirmed |
| Desktop app, Code tab, plugin installed by the CLI for the same user | Untested | |
| Organization library, **Available to install**, turned on per account (3c) | No, on the Windows desktop app | Owner's test install, 2026-11-02: the plugin landed on disk but no hook ran (no status, spool, or records) |
| Organization library, **Installed by default** or **Required** (3c) | Untested | |
| Managed bundle: machine-wide `hooks.conf` plus the plugin (3b) | Untested on a real client | Config handling is tested in the suite |

Mark a row tested only after pilot check 1 passes on that path, and note the client and version.

## 4. The machine-wide config (fleet)

The machine-wide file wins over the plugin's own config, which is then not read at all, so nothing in the user's folder can redirect records, add a CA, or change the token.

| Platform | Path | Permissions |
|---|---|---|
| Windows | `%ProgramData%\siem-claude-hooks\hooks.conf` | SYSTEM and Administrators: full control; Users: read |
| macOS | `/Library/Application Support/siem-claude-hooks/hooks.conf` | root, 0644 |
| Linux | `/etc/siem-claude-hooks/hooks.conf` | root, 0644 |

Users can read the file because the hook runs as them. The token in it can only add records to this one source; anyone who copies it can at most send records that look like that machine's. Rotate it with a new deployment token on **Settings > Claude plugins**.

Windows, as an endpoint management script run as SYSTEM (keep the token in your tool's secret field, not in the script text):

```powershell
$dir = Join-Path $env:ProgramData 'siem-claude-hooks'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
icacls $dir /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' 'Users:(OI)(CI)RX' | Out-Null
$conf = "REMNANT_URL=https://siem.example.internal:8080`nREMNANT_TOKEN=$env:HOOKS_TOKEN`nSEND_CONTENT=0`nPILOT_USERS=`n"
[IO.File]::WriteAllText((Join-Path $dir 'hooks.conf'), $conf)
```

Add `CA_FILE=C:\ProgramData\siem-claude-hooks\server-ca.pem` and copy `server-ca.pem` there when the bundle includes the certificate. Optional keys, read from this file only: `CLAUDE_EMAIL` (the account email, when the machine has none), and `DEV_ENV_OVERRIDE=1` (lets `REMNANT_URL` and `REMNANT_TOKEN` come from the environment, for testing a server build; never on people's machines).

## 5. For your proxy admin

The plugins post to **one path**, with the source's token in an `Authorization: Bearer` header. They connect to the server directly (the Windows plugin does not use a system proxy), so people's machines need a route to it:

```
POST /api/otlp/v1/logs
```

A forward-auth proxy (Authelia, oauth2-proxy) must let exactly that path through without its login, because a hook cannot sign in. The server checks the token on every request. Authelia rule (the full table of token-checked paths is in [tls.md](tls.md)):

```yaml
access_control:
  rules:
    - domain: siem.example.internal
      resources: ['^/api/otlp/v1/logs$']
      policy: bypass
```

Records the plugin cannot send (refused, timed out, unreachable: at home without VPN, for example) wait on the machine in `${CLAUDE_PLUGIN_DATA}/spool`, metadata only, and go out after the next record that reaches the server, oldest first, in the background. The queue keeps at most 10,000 records and 7 days; past that the oldest are lost and counted. Every record carries a per-install sequence number, so **Health > Endpoint agents** shows per machine: queued at its last check-in, delivered late, lost, and missing (numbers that never arrived, with when). Session steps that arrived late say so ("delivered 3 h late"). Do not expose the receiver to the internet to reach people at home: the queue covers that.

## 6. PowerShell, execution policy, and EDR

The Windows plugin runs `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <plugin>\hooks\send.ps1` on every hook. `-NoProfile` keeps people's profile scripts out. `-ExecutionPolicy Bypass` on every tool call is the pattern defenders hunt for (ATT&CK T1059.001): expect your EDR to notice it, and if you allow it, allow it by the script's SHA-256, never by command line. A Group Policy execution policy overrides the command-line flag. A signed-script option (`-ExecutionPolicy AllSigned` with your code-signing certificate) is planned (ADR-0026 row 17).

## 7. Pilot checks

Before any client: on **Settings > Claude plugins**, **Send a test record** next to the deployment's token posts one synthetic session start through the real receiver with that token and shows the HTTP result. 200 means the token, the source, and the receiver work; the record names no person or machine and shows on **Sessions** only with "Hide sessions with no tool calls or prompts" unticked. It does not check the network path from a laptop, the proxy, or the certificate; check 1 does.

Run each on one Windows and one Mac (or Linux) pilot machine. Each is pass or fail.

| # | Check | Pass |
|---|---|---|
| 1 | Start a session, send a prompt, let Claude read a file, fetch a page, run a command that fails, end the session | **AI usage > Agents > Sessions** shows one session with each event in order: Started, Prompt, Calls, Returned, Failed, Turn end, Ended |
| 2 | Stop the server (or take a laptop off the network), then use Claude Code for a few tool calls | Claude is no slower than without the plugin; nothing appears on screen; after the server is back and one more tool call runs, the queued steps appear in the session marked "delivered late", and Health shows them as late, none missing |
| 3 | Point a test copy at a receiver that answers 403 with a body that asks to deny the tool | Claude's behavior does not change; the tool runs |
| 4 | Point a test copy at a receiver that waits 30 seconds | No delay in Claude |
| 5 | Use Claude Code as someone not on the pilot list | Nothing arrives |
| 6 | Leave the other platform's plugin installed (if the console cannot scope by group) | It sends nothing. A hook notice once per session is acceptable. **A notice on every tool call fails the approach**: then publish each plugin to a group in the console, or switch to a single launcher that picks the script per OS |
| 7 | The source's Sessions view, as a user who cannot read the source | No sessions |

The script under Windows PowerShell 5.1 is also checked by the `hooks-windows` workflow (`scripts/check_hooks_windows.py`): the `.claude.json` fallback parser and the certificate check.

## Troubleshooting

Since plugin version 2.2.0, every hook run leaves a small **status file** in the plugin's data folder (`$CLAUDE_PLUGIN_DATA/status`; when Claude gives no data folder, `~/.cache/siem-claude-hooks/status` on macOS and Linux or `%LOCALAPPDATA%\siem-claude-hooks\status` on Windows). It holds the last run time, the last event, whether the record was sent, queued, or skipped (and why: no config, not in `PILOT_USERS`, no server or token), the server's HTTP status (`000` when it was not reached), the queue depth, and where the config came from. Never the token, a prompt, or any tool content.

| What you see | What it means |
|---|---|
| No status file at all | The hook never ran for this user: the install path did not load the plugin's hooks (see the table above), or Claude was not restarted |
| `result=skipped: no config file` | The plugin's own `config` is empty and no machine-wide `hooks.conf` exists (the managed bundle's plugin sends only with `hooks.conf`) |
| `result=skipped: not in PILOT_USERS` | Working as set: this account is not in the pilot list |
| `result=queued: not sent`, `http_status=000` | The server was not reached: network, proxy, DNS, or the certificate (section 5) |
| `result=queued: not sent`, `http_status=401` | The token was refused: wrong, revoked, or its source is turned off. **Settings > Claude plugins** shows the last error per token |

**Doctor mode** checks a machine in one go and prints a pass or fail per check: the config, the certificate file, that the server answers, that the token works (it sends one test record, marked as a test, with no person or machine), that `claude plugin list` shows the plugin, and the hook's last status. It never prints the token.

```
sh install-local.sh --doctor                                          # macOS, Linux
powershell -ExecutionPolicy Bypass -File .\install-local.ps1 -Doctor  # Windows
```

## Turning it off

Set the plugin to **Not available** in the admin console, or revoke the deployment's token on **Settings > Claude plugins**: every copy with that token stops sending at once, and other deployments keep sending. **New token** on the source's row still replaces the source's earlier token (from before named tokens).
