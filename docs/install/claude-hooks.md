# Claude Code and Cowork sessions: the hooks plugin

The hooks plugin sends one record per session event from Claude Code and Cowork to this server: session start, each prompt, each tool call and its result, and stop. On the AI usage page, **Agents** lists the people and their tools, and **Sessions** shows each session in order (ADR-0026).

It only observes. It never blocks, changes, or slows anything: each hook runs in the background, waits at most 2 seconds for the server, ignores every error, and always exits 0.

## What it covers

| Client | Covered | Notes |
|---|---|---|
| Claude Code in a terminal, an IDE extension, or the desktop app's **Code** tab | Yes | Plugin hooks run here |
| Cowork tasks in the desktop app | Yes, when the task runs on the person's computer and that computer can reach this server | Cowork loads plugin hooks. A Cowork session running elsewhere cannot reach a server on your network |
| Chat on claude.ai, the desktop app's **Chat** tab, and the mobile apps | No | Chat ignores plugin hooks. Network logs and the AI service catalog still show the traffic |

Source: Anthropic's "Plugin feature support across platforms" page (claude.com/docs/plugins/platform-support), checked 2026-10-22: hooks load in Cowork and Claude Code, and are ignored in chat.

## What it sends

| Always (metadata) | Only when the source keeps content |
|---|---|
| Event, time, session id, `role` (session, user, tool_call, tool_result) | Prompt text |
| Person: the Claude account email on the machine, else the OS user | Tool input |
| Machine name, working folder | The whole hook input, including tool output |
| Tool name; MCP server and tool | |
| The file path, web host, or program name a tool touched | |
| Sizes, and SHA-256 hashes of the prompt and tool input | |

Content follows the source's **Keep prompt and tool content** setting at the time you download the plugin. Change the setting, then download and publish again. Whatever arrives is log content: stored as data and never given to a model as instructions.

## 1. Make a source for it

**Sources > Add source**, **Reads from: OpenTelemetry (OTLP)**, Source ID for example `claude_hooks`, Parser **Automatic**. Use a source just for the plugin: each download issues a new token for the source.

## 2. Download the plugin

On the source's row, select **Claude plugin**:

- **Server address**: the address people's computers reach this server at, for example `https://siem.example.internal:8080`. It must be `https` (the token travels with every record). It is written into the plugin; nothing on a computer or in a session can change it.
- **Pilot users**: Claude account emails or OS user names, separated by spaces or commas. Only they send, wherever the plugin is installed. Leave it empty to send for everyone who has it.

**Download plugin** saves a zip. The page shows the plugin version and the SHA-256 of its script, `hooks/send.sh`; check it against the zip before you publish. The script is about 180 lines of `sh`, `awk`, `sed`, and `curl`, readable in one sitting.

Downloading is audited (`source.claude_plugin`, with the pilot list, never the token).

## 3. Publish it to your organization

Organization plugins need a Team or Enterprise plan, with Cowork and Skills turned on, and an Owner (or Primary Owner) to publish (Anthropic support article "Manage plugins for your organization").

1. In Claude, **Organization settings > Plugins & skills > Marketplaces > Add > Upload a plugin**. Name a marketplace (for example "Security") and upload the zip.
2. **Inventory**, the plugin's menu, **Default access**: **Installed by default** (people can turn it off) or **Required** (they cannot). Required also installs it in Claude Code for people signed in with their Claude account.
3. Members get it on their next session or plugin refresh.

For a pilot, publish it Required and keep the pilot list short; widen it later by downloading again with a longer list (or none) and uploading the new zip.

Without the admin console (one machine, or a quick test): unzip it and run `claude --plugin-dir <folder>`, or add it with `/plugin` from a local marketplace.

## 4. Requirements on the computers

- macOS and Linux: nothing to install (`sh`, `awk`, `sed`, `curl`, and `shasum` or `sha256sum` are there).
- Windows: Git for Windows (Git Bash), which Claude Code uses to run hooks. Without it, Claude Code runs hooks with PowerShell and this script does not run; the session is not affected, but nothing is sent.

## 5. Reverse proxy and forward-auth

The plugin posts to `/api/otlp/v1/logs` with the source's token. A forward-auth proxy (Authelia, oauth2-proxy) must let that path through without its login, because the plugin cannot sign in. The server still checks the token on every request. See the forward-auth section of [tls.md](tls.md) for the bypass rule to give your proxy admin.

## 6. Check it

Open a Claude Code session as a pilot user and run one tool. Within a minute, **AI usage > Agents > Sessions** lists the session; open it to see each step. On the Sources page the source's count goes up. Nothing appears for people outside the pilot list.

## Turning it off

Set the plugin to **Not available** in the admin console, or make a new token for the source (**New token** on its row): every installed copy stops sending at once.
