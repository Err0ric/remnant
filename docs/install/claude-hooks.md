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

**Sources > Add source**, **Reads from: OpenTelemetry (OTLP)**, Source ID for example `claude_hooks`, Parser **Automatic**. Use a source just for the plugins: each download issues a new token for the source, and earlier copies stop sending.

## 2. Download a plugin per platform

On the source's row, select **Claude plugin**, then:

- **Platform**: **Windows**, or **macOS and Linux**. Download each one you need; each download issues a new token, so download both before publishing either.
- **Where the address and token live**:
  - **In the plugin** (the pilot): one zip, nothing else to deploy.
  - **In a machine-wide file** (the fleet): a bundle with the plugin (its own config empty), `hooks.conf`, and a README. See step 4.
- **Include this server's self-signed certificate** (shown when this server serves its generated certificate): the scripts check the server against it. Untick it when people's machines already trust the server's certificate. There is no option to skip checking.
- **Server address**: what people's machines reach this server at, for example `https://siem.example.internal:8080`. It must be `https`.
- **Pilot users**: Claude account emails or OS user names. Only they send, wherever the plugin is installed. Empty: everyone who has it.

The page shows the version and the SHA-256 of the platform's script (`hooks/send.ps1` or `hooks/send.sh`); check it against the zip before you publish. Each script is short enough to read in one sitting. Downloads are audited (`source.claude_plugin`, with the platform and pilot list, never the token).

## 3. Publish to your organization

Organization plugins need a Team or Enterprise plan and an Owner (or Primary Owner) to publish (Anthropic support article "Manage plugins for your organization").

1. **Organization settings > Plugins & skills > Marketplaces > Add > Upload a plugin**. Upload each platform's zip.
2. Publish each plugin to the people on that platform, if the console lets you choose who gets it. If it does not, every member gets both plugins: the other platform's plugin cannot start on their machine (a hook notice at worst, nothing sent). The pilot checks how often that notice shows (step 6).
3. **Default access**: **Required** for the pilot (with the pilot list in the plugin), later **Installed by default** or **Required** for everyone.

One machine, or a quick test without the console: unzip the plugin and run `claude --plugin-dir <folder>`.

## 4. The machine-wide config (fleet)

The machine-wide file wins over the plugin's own config, which is then not read at all, so nothing in the user's folder can redirect records, add a CA, or change the token.

| Platform | Path | Permissions |
|---|---|---|
| Windows | `%ProgramData%\siem-claude-hooks\hooks.conf` | SYSTEM and Administrators: full control; Users: read |
| macOS | `/Library/Application Support/siem-claude-hooks/hooks.conf` | root, 0644 |
| Linux | `/etc/siem-claude-hooks/hooks.conf` | root, 0644 |

Users can read the file because the hook runs as them. The token in it can only add records to this one source; anyone who copies it can at most send records that look like that machine's. Rotate it with **New token** on the source's row.

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

## Turning it off

Set the plugin to **Not available** in the admin console, or make a new token for the source (**New token** on its row): every installed copy stops sending at once.
