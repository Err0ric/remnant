#!/bin/sh
# Observe-only hook for Claude Code on macOS and Linux (ADR-0026, amendment 2026-10-29).
# One OTLP log record per event, sent to the one server named in the managed config.
#
# What it never does: block, change, or delay anything. It runs in the background
# (async in hooks.json), waits at most 2 seconds for the server, ignores every error,
# prints only {} (never the server's answer), and always exits 0.
#
# Sends by default: the event, time, session id, Claude account email (and where it came
# from), OS user, machine, tool name, the MCP server and tool, the file path or web host
# or program name a tool touched, sizes, and SHA-256 hashes of the prompt and tool input.
# Prompt text, tool input, tool output, and tool errors are sent only when the config
# says SEND_CONTENT=1, each cut to its first and last 4 KB.
#
# Offline: a record that cannot be sent waits in ${CLAUDE_PLUGIN_DATA}/spool (metadata
# only) and goes out after the next record that reaches the server. Each record carries
# this install's id and a sequence number, so the server sees what never arrived.
#
# Needs: sh, awk, sed, curl, and sha256sum or shasum.

trap 'printf "{}\n"' EXIT
exec 2>/dev/null  # nothing ever reaches the person's screen
umask 077
set -f

# Sessions that belong to another plugin: Cowork has its own, Windows has its own.
case "${CLAUDE_CODE_IS_COWORK:-}" in true | TRUE | True | 1) exit 0 ;; esac
[ "${OS:-}" = Windows_NT ] && exit 0
case "$(uname -s 2>/dev/null)" in MINGW* | MSYS* | CYGWIN* | Windows*) exit 0 ;; esac

# --- Config: the machine-wide file wins; the plugin's own copy is the fallback. -------
# Both are key=value data, read and never run. When the machine file exists, the
# plugin's copy (in the user's own folder) is not read at all.
url="" token="" send_content=0 pilot="" ca="" managed_email="" dev=0 from=""
read_conf() {
  while IFS='=' read -r key value || [ -n "$key" ]; do
    value=$(printf '%s' "$value" | tr -d '\r')
    case "$key" in
      REMNANT_URL) url=$value ;;
      REMNANT_TOKEN) token=$value ;;
      SEND_CONTENT) send_content=$value ;;
      PILOT_USERS) pilot=$value ;;
      CA_FILE) ca=$value ;;
      CLAUDE_EMAIL) [ "$from" = machine ] && managed_email=$value ;;
      DEV_ENV_OVERRIDE) [ "$from" = machine ] && dev=$value ;;
    esac
  done < "$1"
}
case "$(uname -s 2>/dev/null)" in
  Darwin) machine_conf="/Library/Application Support/siem-claude-hooks/hooks.conf" ;;
  *) machine_conf="/etc/siem-claude-hooks/hooks.conf" ;;
esac
if [ -r "$machine_conf" ]; then
  from=machine
  read_conf "$machine_conf"
  # Only the machine file can let the environment name the server (testing a build).
  if [ "$dev" = 1 ]; then
    [ -n "${REMNANT_URL:-}" ] && url=$REMNANT_URL
    [ -n "${REMNANT_TOKEN:-}" ] && token=$REMNANT_TOKEN
  fi
else
  bundled="$(dirname "$0")/../config"
  [ -r "$bundled" ] || exit 0
  from=plugin
  read_conf "$bundled"
  # A certificate named without a folder is the one bundled in the plugin.
  case "$ca" in "" | /*) ;; *) ca="$(dirname "$0")/../$ca" ;; esac
fi
[ -n "$url" ] && [ -n "$token" ] || exit 0

# Where this plugin keeps its cache and the count of records it could not send.
data=${CLAUDE_PLUGIN_DATA:-${HOME:-/tmp}/.cache/siem-claude-hooks}
mkdir -p "$data" 2>/dev/null

# The hook input, capped at 1 MB.
input=$(head -c 1048576)

# --- Shared JSON helpers (awk): strings stay in their JSON-escaped form. -------------
lib='
  function str(src, key,   p, i, c, out, rest) {
    p = 0
    while ((i = index(substr(src, p + 1), "\"" key "\"")) > 0) {
      p += i
      if (p > 1 && substr(src, p - 1, 1) == "\\") continue
      rest = substr(src, p + length(key) + 2)
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
  function obj(src, key,   p, rest, i, c, depth, instr) {
    p = index(src, "\"" key "\"")
    if (p == 0) return ""
    rest = substr(src, p + length(key) + 2)
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
  # At most n characters, never ending inside an escape.
  function head(v, n) {
    if (length(v) <= n) return v
    v = substr(v, 1, n)
    sub(/\\u[0-9A-Fa-f]?[0-9A-Fa-f]?[0-9A-Fa-f]?$/, "", v)
    if (match(v, /\\+$/) && RLENGTH % 2 == 1) v = substr(v, 1, length(v) - 1)
    return v
  }
  # The last n characters, never starting inside an escape.
  function tail(v, n,   s, k, j, run, len) {
    s = length(v) - n + 1
    for (k = s - 1; k >= s - 6 && k >= 1; k--) {
      if (substr(v, k, 1) != "\\") continue
      run = 0
      for (j = k - 1; j >= 1 && substr(v, j, 1) == "\\"; j--) run++
      if (run % 2 == 1) continue
      len = (substr(v, k + 1, 1) == "u") ? 6 : 2
      if (k + len > s) s = k + len
      break
    }
    return substr(v, s)
  }
  # Content is cut to its first and last 4 KB.
  function cap(v) {
    if (length(v) <= 8192) return v
    return head(v, 4096) "\\n[...]\\n" tail(v, 4096)
  }
'

# --- The Claude account: managed config, then CLAUDE_CODE_USER_EMAIL, then the signed-in
# account in .claude.json (oauthAccount.emailAddress only; nothing else is read). ------
email="" account_from=""
if [ -n "$managed_email" ]; then
  email=$managed_email account_from=managed
elif [ -n "${CLAUDE_CODE_USER_EMAIL:-}" ]; then
  email=$CLAUDE_CODE_USER_EMAIL account_from=env
else
  json="${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json"
  cache="$data/account"
  if [ -r "$json" ]; then
    # The file can be large: read it again only when it changed since the cache.
    if [ -s "$cache" ] && ! [ "$json" -nt "$cache" ]; then
      email=$(head -n 1 "$cache")
    else
      email=$(head -c 16777216 "$json" | awk "$lib"'
        { s = s (NR > 1 ? "\n" : "") $0 }
        END { print str(obj(s, "oauthAccount"), "emailAddress") }')
      printf '%s\n' "$email" > "$cache" 2>/dev/null
    fi
    case "$email" in *@*) account_from=claude_json ;; *) email="" ;; esac
  fi
fi
case "$email" in *[!A-Za-z0-9.@_+-]*) email="" account_from="" ;; esac
os_user=$(id -un 2>/dev/null || printf '%s' "${USER:-}")

# Pilot mode: when PILOT_USERS lists people (space separated), only they send.
if [ -n "$pilot" ]; then
  me=$(printf '%s' "$email" | tr 'A-Z' 'a-z')
  me2=$(printf '%s' "$os_user" | tr 'A-Z' 'a-z')
  ok=0
  for p in $(printf '%s' "$pilot" | tr 'A-Z,' 'a-z '); do
    { [ -n "$me" ] && [ "$p" = "$me" ]; } || { [ -n "$me2" ] && [ "$p" = "$me2" ]; } && ok=1
  done
  [ "$ok" = 1 ] || exit 0
fi

hash() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi | cut -c1-64
}

fields=$(printf '%s' "$input" | awk "$lib"'
  { s = s (NR > 1 ? "\n" : "") $0 }
  END {
    tool = str(s, "tool_name")
    path = str(s, "file_path"); if (path == "") path = str(s, "notebook_path")
    if (path == "") path = str(s, "path")
    host = str(s, "url"); gsub(/\\\//, "/", host); sub(/^[A-Za-z][A-Za-z0-9+.-]*:\/\//, "", host)
    sub(/[\/:?#].*$/, "", host); if (host !~ /^[A-Za-z0-9.-]+$/) host = ""
    prog = str(s, "command"); gsub(/\\["\\]|["'\'']/, "", prog); sub(/^[ \t]+/, "", prog)
    sub(/[ \t;|&<>(].*$/, "", prog); sub(/^.*\//, "", prog); if (prog !~ /^[A-Za-z0-9._+-]+$/) prog = ""
    mcp_server = ""; mcp_tool = ""
    if (tool ~ /^mcp__/) { n = split(tool, part, "__"); mcp_server = part[2]; mcp_tool = part[3] }
    tin = obj(s, "tool_input"); tout = obj(s, "tool_response"); if (tout == "") tout = str(s, "tool_response")
    err = str(s, "error")
    print "event=" str(s, "hook_event_name")
    print "session=" head(str(s, "session_id"), 512)
    print "source=" head(str(s, "source"), 64)
    print "reason=" head(str(s, "reason"), 64)
    print "cwd=" head(str(s, "cwd"), 512)
    print "tool=" head(tool, 512)
    print "mcp_server=" head(mcp_server, 512)
    print "mcp_tool=" head(mcp_tool, 512)
    print "path=" head(path, 512)
    print "host=" host
    print "program=" prog
    print "tool_input_chars=" length(tin)
    print "tool_response_chars=" length(tout)
    print "error_chars=" length(err)
  }')
get() { printf '%s\n' "$fields" | sed -n "s/^$1=//p" | head -n 1; }
# Content pieces, each on its own so a newline inside cannot shift another field.
content() { printf '%s' "$input" | awk "$lib"'
  { s = s (NR > 1 ? "\n" : "") $0 }
  END {
    if (k == "tool_input" || k == "tool_response") v = obj(s, k)
    else if (k == "tool_response_text") { v = obj(s, "tool_response") == "" ? str(s, "tool_response") : "" }
    else v = str(s, k)
    if (raw != 1) v = cap(v)
    printf "%s", v
  }' k="$1" raw="${2:-0}"; }

event=$(get event)
case "$event" in
  SessionStart) name=session_start role=session ;;
  UserPromptSubmit) name=user_prompt_submit role=user ;;
  PreToolUse) name=pre_tool_use role=tool_call ;;
  PostToolUse) name=post_tool_use role=tool_result ;;
  PostToolUseFailure) name=post_tool_use_failure role=tool_result ;;
  Stop) name=stop role=turn ;;
  SessionEnd) name=session_end role=session ;;
  *) exit 0 ;;
esac

# One OTLP attribute: a JSON string value, already escaped.
attr() { [ -n "$2" ] && printf ',{"key":"%s","value":{"stringValue":"%s"}}' "$1" "$2"; }
num() { [ -n "$2" ] && [ "$2" != 0 ] && printf ',{"key":"%s","value":{"intValue":"%s"}}' "$1" "$2"; }
# Text for a JSON string: backslashes, quotes, and control characters escaped.
esc() { printf '%s' "$1" | awk '{ gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); gsub(/\t/, "\\t"); gsub(/\r/, "\\r"); printf "%s%s", (NR > 1 ? "\\n" : ""), $0 }'; }

# --- Sequence, spool, and lost records (offline queue) ---------------------------------
# Each record gets the next number of this install, so the server can see gaps; a new
# install (a new random id) starts again at 1. A lock folder keeps parallel hooks apart.
spool="$data/spool"
mkdir -p "$spool" 2>/dev/null
[ -s "$data/install" ] || od -An -N8 -tx1 /dev/urandom | tr -d ' \n' > "$data/install"
install=$(head -c 32 "$data/install" | tr -cd '0-9a-f')
lock() {
  i=0
  while ! mkdir "$1" 2>/dev/null; do
    # A lock older than a minute was left by a hook that was killed.
    [ -n "$(find "$1" -maxdepth 0 -mmin +1 2>/dev/null)" ] && rmdir "$1" && continue
    i=$((i + 1)); [ "$i" -gt 100 ] && return 1
    sleep 0.02 || sleep 1
  done
}
seq=""
if lock "$data/seq.lock"; then
  last=$(head -n 1 "$data/seq" 2>/dev/null)
  case "$last" in '' | *[!0-9]*) last=0 ;; esac
  seq=$((last + 1))
  printf '%s\n' "$seq" > "$data/seq.tmp" && mv "$data/seq.tmp" "$data/seq"
  rmdir "$data/seq.lock"
fi
queued=$(ls "$spool" 2>/dev/null | wc -l | tr -d ' ')

# Records lost on this machine (the queue was full or a record was older than 7 days):
# counted, and reported with the next record that reaches the server.
pending="" dropped=0
if [ -s "$data/dropped" ] && mv "$data/dropped" "$data/dropped.$$" 2>/dev/null; then
  pending="$data/dropped.$$"
  dropped=$(wc -c < "$pending" | tr -d ' ')
fi

prompt=""
[ "$event" = UserPromptSubmit ] && prompt=$(content prompt 1)
tool_input=$(content tool_input 1)
meta=$(
  printf '{"key":"event_name","value":{"stringValue":"claude_hooks.%s"}}' "$name"
  attr role "$role"
  attr plugin_variant posix
  attr install_id "$install"
  num seq "$seq"
  attr session_id "$(get session)"
  attr session_source "$(get source)"
  attr end_reason "$(get reason)"
  attr claude_account_email "$email"
  attr account_from "$account_from"
  attr os_user "$(esc "$os_user")"
  attr cwd "$(get cwd)"
  attr tool_name "$(get tool)"
  attr mcp_server_name "$(get mcp_server)"
  attr mcp_tool_name "$(get mcp_tool)"
  attr path "$(get path)"
  attr web_host "$(get host)"
  attr program "$(get program)"
  [ "$name" = post_tool_use_failure ] && attr outcome failure
  if [ -n "$prompt" ]; then
    attr prompt_sha256 "$(printf '%s' "$prompt" | hash)"
    num prompt_chars "${#prompt}"
  fi
  [ -n "$tool_input" ] && attr tool_input_sha256 "$(printf '%s' "$tool_input" | hash)"
  num tool_input_chars "$(get tool_input_chars)"
  num tool_response_chars "$(get tool_response_chars)"
  num error_chars "$(get error_chars)"
)
extra=$(
  num dropped_since_last "$dropped"
  num queued_at_send "$queued"
  if [ "$send_content" = 1 ]; then
    [ "$event" = UserPromptSubmit ] && attr prompt "$(content prompt)"
    attr tool_input "$(esc "$(content tool_input)")"
    out=$(content tool_response)
    if [ -n "$out" ]; then attr tool_response "$(esc "$out")"; else attr tool_response "$(content tool_response_text)"; fi
    attr tool_error "$(content error)"
  fi
)

now=$(date +%s)
host=$(esc "$(uname -n)")
record() { printf '{"timeUnixNano":"%s000000000","body":{"stringValue":"claude_hooks.%s"},"attributes":[%s]}' "$now" "$name" "$1"; }
wrap() { printf '{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"claude-hooks"}},{"key":"host.name","value":{"stringValue":"%s"}}]},"scopeLogs":[{"scope":{"name":"claude-hooks","version":"2.1.0"},"logRecords":[%s]}]}]}' "$host" "$1"; }
# One POST of a body on stdin: 2 seconds at most, only the CA named in the config when one
# is named (never a switch to skip checking), and the answer is never read.
post() {
  if [ -n "$ca" ] && [ -r "$ca" ]; then
    curl --silent --fail --output /dev/null --max-time 2 --connect-timeout 1 --cacert "$ca" \
      -X POST "$url/api/otlp/v1/logs" -H "Content-Type: application/json" \
      -H "Authorization: Bearer $token" --data-binary @- >/dev/null 2>&1
  else
    curl --silent --fail --output /dev/null --max-time 2 --connect-timeout 1 \
      -X POST "$url/api/otlp/v1/logs" -H "Content-Type: application/json" \
      -H "Authorization: Bearer $token" --data-binary @- >/dev/null 2>&1
  fi
}

# Queued records go out after the live one, oldest first, 50 to a request, for at most 15
# seconds. This hook runs in the background, so Claude never waits for it. One hook flushes
# at a time; a record older than 7 days is dropped and counted as lost.
flush() {
  lock "$data/flush.lock" || return 0
  began=$(date +%s)
  cutoff=$((began - 604800))
  while [ $(($(date +%s) - began)) -lt 15 ]; do
    files=$(ls "$spool" 2>/dev/null | head -n 50)
    [ -n "$files" ] || break
    batch="" names=""
    for f in $files; do
      t=${f%%-*}
      case "$t" in '' | *[!0-9]*) rm -f "$spool/$f"; continue ;; esac
      if [ "$t" -lt "$cutoff" ]; then rm -f "$spool/$f"; printf x >> "$data/dropped"; continue; fi
      batch="${batch:+$batch,}$(cat "$spool/$f")"
      names="$names $f"
    done
    [ -n "$batch" ] || continue
    wrap "$batch" | post || break
    for f in $names; do rm -f "$spool/$f"; done
  done
  rmdir "$data/flush.lock"
}

if wrap "$(record "$meta$extra")" | post; then
  [ -n "$pending" ] && rm -f "$pending"
  [ "$queued" -gt 0 ] && flush
else
  # Not sent: the lost count waits for the next record, and this record is queued
  # (metadata only: content is never written to disk). At most 10,000 records (about
  # 20 MB) are kept; past that the oldest are dropped and counted as lost.
  [ -n "$pending" ] && { cat "$pending" >> "$data/dropped"; rm -f "$pending"; }
  n=$(printf '%012d' "${seq:-0}")
  record "$meta" > "$spool/.$now-$n-$$" && mv "$spool/.$now-$n-$$" "$spool/$now-$n-$$.rec"
  over=$(($(ls "$spool" | wc -l) - 10000))
  if [ "$over" -gt 0 ]; then
    for f in $(ls "$spool" | head -n "$over"); do rm -f "$spool/$f"; printf x >> "$data/dropped"; done
  fi
fi
exit 0
