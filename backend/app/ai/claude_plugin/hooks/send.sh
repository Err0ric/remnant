#!/bin/sh
# Observe-only hook for Claude Code and Cowork (ADR-0026). One OTLP log record per event,
# sent to the one server written in the plugin's config file when it was downloaded.
#
# What it never does: block, change, or delay anything. It runs in the background
# (async in hooks.json), waits at most 2 seconds for the server, ignores every error,
# and always exits 0. It never prints, so nothing reaches Claude's context.
#
# What it sends by default: the event, time, session id, person (Claude account email,
# else the OS user), machine, tool name, the MCP server and tool, the file path or web
# host or program name a tool touched, sizes, and SHA-256 hashes of the prompt and tool
# input. Prompt text and tool input and output are sent only when the config says
# SEND_CONTENT=1, which the download sets from the source's "keep content" choice.
#
# Needs: sh, awk, sed, curl, and sha256sum or shasum. On Windows: Git Bash, which
# Claude Code uses to run hooks.

cfg="$(dirname "$0")/../config"
[ -r "$cfg" ] || exit 0
url="" token="" send_content=0 pilot=""
# The config is read as data (key=value), never run.
while IFS='=' read -r key value; do
  case "$key" in
    REMNANT_URL) url=$value ;;
    REMNANT_TOKEN) token=$value ;;
    SEND_CONTENT) send_content=$value ;;
    PILOT_USERS) pilot=$value ;;
  esac
done < "$cfg"
[ -n "$url" ] && [ -n "$token" ] || exit 0

# The hook input, capped at 1 MB.
input=$(head -c 1048576)

# The person: the Claude account email if this machine has one, else the OS user.
user=$(sed -n 's/.*"emailAddress"[[:space:]]*:[[:space:]]*"\([^"@]*@[^"]*\)".*/\1/p' \
  "$HOME/.claude.json" 2>/dev/null | head -n 1)
os_user=$(id -un 2>/dev/null || echo "${USERNAME:-}")
[ -n "$user" ] || user=$os_user

# Pilot mode: when PILOT_USERS lists people (space separated), only they send.
if [ -n "$pilot" ]; then
  me=$(printf '%s' "$user" | tr 'A-Z' 'a-z')
  case " $(printf '%s' "$pilot" | tr 'A-Z' 'a-z') " in
    *" $me "*) ;;
    *) exit 0 ;;
  esac
fi

hash() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -c1-64
}

# Pull the pieces out of the hook JSON with awk (no jq needed). Strings stay in their
# JSON-escaped form, so they are written back out exactly as Claude Code sent them.
fields=$(printf '%s' "$input" | awk '
  { s = s (NR > 1 ? "\n" : "") $0 }
  # The JSON-escaped text of the first string value for "key" (not inside another string).
  function str(key,   p, i, c, out) {
    p = 0
    while ((i = index(substr(s, p + 1), "\"" key "\"")) > 0) {
      p += i
      if (p > 1 && substr(s, p - 1, 1) == "\\") continue
      rest = substr(s, p + length(key) + 2)
      if (!match(rest, /^[ \t\r\n]*:[ \t\r\n]*"/)) continue
      rest = substr(rest, RLENGTH + 1); out = ""
      for (i = 1; i <= length(rest); i++) {
        c = substr(rest, i, 1)
        if (c == "\\") { out = out c substr(rest, i + 1, 1); i++; continue }
        if (c == "\"") return out
        out = out c
      }
      return ""
    }
    return ""
  }
  # The raw text of the first object or array value for "key".
  function obj(key,   p, rest, i, c, depth, instr) {
    p = index(s, "\"" key "\"")
    if (p == 0) return ""
    rest = substr(s, p + length(key) + 2)
    if (!match(rest, /^[ \t\r\n]*:[ \t\r\n]*/)) return ""
    rest = substr(rest, RLENGTH + 1)
    c = substr(rest, 1, 1)
    if (c != "{" && c != "[") return ""
    depth = 0; instr = 0
    for (i = 1; i <= length(rest); i++) {
      c = substr(rest, i, 1)
      if (instr) { if (c == "\\") i++; else if (c == "\"") instr = 0; continue }
      if (c == "\"") instr = 1
      else if (c == "{" || c == "[") depth++
      else if (c == "}" || c == "]") { depth--; if (depth == 0) return substr(rest, 1, i) }
    }
    return ""
  }
  function clip(v) {  # at most 512 characters, never ending inside an escape
    if (length(v) <= 512) return v
    v = substr(v, 1, 512)
    sub(/\\u[0-9A-Fa-f]?[0-9A-Fa-f]?[0-9A-Fa-f]?$/, "", v)
    if (match(v, /\\+$/) && RLENGTH % 2 == 1) v = substr(v, 1, length(v) - 1)
    return v
  }
  END {
    tool = str("tool_name")
    path = str("file_path"); if (path == "") path = str("notebook_path"); if (path == "") path = str("path")
    host = str("url"); gsub(/\\\//, "/", host); sub(/^[A-Za-z][A-Za-z0-9+.-]*:\/\//, "", host)
    sub(/[\/:?#].*$/, "", host); if (host !~ /^[A-Za-z0-9.-]+$/) host = ""
    prog = str("command"); gsub(/\\["\\]|["'\'']/, "", prog); sub(/^[ \t]+/, "", prog)
    sub(/[ \t;|&<>(].*$/, "", prog); sub(/^.*\//, "", prog); if (prog !~ /^[A-Za-z0-9._+-]+$/) prog = ""
    mcp_server = ""; mcp_tool = ""
    if (tool ~ /^mcp__/) { n = split(tool, part, "__"); mcp_server = part[2]; mcp_tool = part[3] }
    tin = obj("tool_input"); tout = obj("tool_response"); if (tout == "") tout = str("tool_response")
    print "event=" str("hook_event_name")
    print "session=" clip(str("session_id"))
    print "source=" clip(str("source"))
    print "cwd=" clip(str("cwd"))
    print "tool=" clip(tool)
    print "mcp_server=" clip(mcp_server)
    print "mcp_tool=" clip(mcp_tool)
    print "path=" clip(path)
    print "host=" host
    print "program=" prog
    print "prompt=" str("prompt")
    print "tool_input=" tin
    print "tool_input_chars=" length(tin)
    print "tool_response_chars=" length(tout)
  }')

get() { printf '%s\n' "$fields" | sed -n "s/^$1=//p" | head -n 1; }
event=$(get event)
case "$event" in
  SessionStart) name=session_start role=session ;;
  UserPromptSubmit) name=user_prompt_submit role=user ;;
  PreToolUse) name=pre_tool_use role=tool_call ;;
  PostToolUse) name=post_tool_use role=tool_result ;;
  Stop) name=stop role=session ;;
  *) exit 0 ;;
esac
prompt=""
[ "$event" = UserPromptSubmit ] && prompt=$(get prompt)
tool_input=$(get tool_input)

# One OTLP attribute: a JSON string value, already escaped.
attr() { [ -n "$2" ] && printf ',{"key":"%s","value":{"stringValue":"%s"}}' "$1" "$2"; }
num() { [ -n "$2" ] && [ "$2" != 0 ] && printf ',{"key":"%s","value":{"intValue":"%s"}}' "$1" "$2"; }
# Text for a JSON string: backslashes, quotes, and control characters escaped.
esc() { printf '%s' "$1" | awk '{ gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t"); gsub(/\r/, "\\r"); printf "%s%s", (NR > 1 ? "\\n" : ""), $0 }'; }

attrs=$(
  printf '{"key":"event_name","value":{"stringValue":"claude_hooks.%s"}}' "$name"
  attr role "$role"
  attr session_id "$(get session)"
  attr session_source "$(get source)"
  attr user "$(esc "$user")"
  attr os_user "$(esc "$os_user")"
  attr cwd "$(get cwd)"
  attr tool_name "$(get tool)"
  attr mcp_server_name "$(get mcp_server)"
  attr mcp_tool_name "$(get mcp_tool)"
  attr path "$(get path)"
  attr web_host "$(get host)"
  attr program "$(get program)"
  if [ -n "$prompt" ]; then
    attr prompt_sha256 "$(printf '%s' "$prompt" | hash)"
    num prompt_chars "${#prompt}"
  fi
  if [ -n "$tool_input" ]; then
    attr tool_input_sha256 "$(printf '%s' "$tool_input" | hash)"
  fi
  num tool_input_chars "$(get tool_input_chars)"
  num tool_response_chars "$(get tool_response_chars)"
  if [ "$send_content" = 1 ]; then
    attr prompt "$prompt"
    attr tool_input "$(esc "$tool_input")"
    attr hook_payload "$(esc "$input")"
  fi
)

body=$(printf '{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"claude-hooks"}},{"key":"host.name","value":{"stringValue":"%s"}}]},"scopeLogs":[{"scope":{"name":"claude-hooks","version":"1.0.0"},"logRecords":[{"timeUnixNano":"%s000000000","body":{"stringValue":"claude_hooks.%s"},"attributes":[%s]}]}]}]}' \
  "$(esc "$(uname -n)")" "$(date +%s)" "$name" "$attrs")

printf '%s' "$body" | curl --silent --output /dev/null --max-time 2 --connect-timeout 1 \
  -X POST "$url/api/otlp/v1/logs" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $token" --data-binary @- >/dev/null 2>&1 || true
exit 0
