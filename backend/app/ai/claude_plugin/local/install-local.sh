#!/bin/sh
# Install this hooks plugin for your own user on this one machine, to test it.
#
# Run it from the unzipped plugin folder:   sh install-local.sh
#
# It copies this folder into a local marketplace (@MARKETPLACE@) under your user data
# folder, registers that marketplace, installs the plugin for your user, and lists your
# plugins. Running it again replaces the earlier copy. Needs the Claude Code CLI (`claude`)
# on PATH: the desktop app's Code tab cannot run /plugin, so install from a terminal.
# To remove it: claude plugin marketplace remove @MARKETPLACE@
#
# Check a machine instead:   sh install-local.sh --doctor
# It reads the config (the machine file, else this folder's), checks the server answers,
# sends one test record with the token (marked as a test: no person, no machine), looks
# for the plugin in `claude plugin list`, and prints the hook's last status. It prints a
# pass or fail per check and never prints the token.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MARKET="@MARKETPLACE@"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/$MARKET"

doctor() {
  failed=0
  pass() { printf 'PASS  %s\n' "$1"; }
  fail() { printf 'FAIL  %s\n' "$1"; failed=1; }
  note() { printf 'INFO  %s\n' "$1"; }
  case "$(uname -s 2>/dev/null)" in
    Darwin) conf="/Library/Application Support/siem-claude-hooks/hooks.conf" ;;
    *) conf="/etc/siem-claude-hooks/hooks.conf" ;;
  esac
  [ -r "$conf" ] || conf="$HERE/config"
  url="" token="" ca=""
  if [ -r "$conf" ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
      value=$(printf '%s' "$value" | tr -d '\r')
      case "$key" in REMNANT_URL) url=$value ;; REMNANT_TOKEN) token=$value ;; CA_FILE) ca=$value ;; esac
    done < "$conf"
    pass "Config found: $conf"
  else
    fail "No config: neither the machine file nor $HERE/config"
  fi
  [ -n "$url" ] && pass "Server: $url" || fail "The config names no server (REMNANT_URL)"
  if [ -n "$token" ]; then
    pass "Token present: $(printf '%s' "$token" | cut -c1-8)... (the rest is not shown)"
  else
    fail "The config has no token (REMNANT_TOKEN)"
  fi
  cacert=""
  if [ -n "$ca" ]; then
    case "$ca" in /*) ;; *) ca="$HERE/$ca" ;; esac
    if [ -r "$ca" ]; then pass "Certificate file: $ca"; cacert="--cacert $ca"; else fail "Certificate file named in the config is missing: $ca"; fi
  fi
  if [ -n "$url" ]; then
    # shellcheck disable=SC2086  # cacert is empty or one option and its path
    code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 $cacert \
      "$url/api/health" 2>/dev/null) || true
    case "$code" in
      200) pass "The server answers at $url" ;;
      000|"") fail "Cannot reach $url (network, proxy, DNS, or the certificate is not trusted)" ;;
      *) fail "The server answered $code at $url/api/health" ;;
    esac
  fi
  if [ -n "$url" ] && [ -n "$token" ]; then
    now=$(date +%s)
    body='{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"claude-hooks"}}]},"scopeLogs":[{"scope":{"name":"claude-hooks"},"logRecords":[{"timeUnixNano":"'"$now"'000000000","body":{"stringValue":"claude_hooks.session_start"},"attributes":[{"key":"event_name","value":{"stringValue":"claude_hooks.session_start"}},{"key":"role","value":{"stringValue":"session"}},{"key":"session_id","value":{"stringValue":"doctor-'"$now"'"}},{"key":"plugin_variant","value":{"stringValue":"doctor"}},{"key":"test_record","value":{"stringValue":"true"}}]}]}]}]}'
    # shellcheck disable=SC2086
    code=$(printf '%s' "$body" | curl --silent --output /dev/null --write-out '%{http_code}' \
      --max-time 5 $cacert -X POST "$url/api/otlp/v1/logs" -H "Content-Type: application/json" \
      -H "Authorization: Bearer $token" --data-binary @- 2>/dev/null) || true
    case "$code" in
      2??) pass "The token works: a test record was accepted (HTTP $code)" ;;
      401) fail "The server refused the token (HTTP 401): wrong, revoked, or its source is off" ;;
      000|"") fail "The test record could not be sent" ;;
      *) fail "The server answered HTTP $code to the test record" ;;
    esac
  fi
  NAME=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$HERE/.claude-plugin/plugin.json" 2>/dev/null | head -n 1)
  if command -v claude >/dev/null 2>&1; then
    if claude plugin list 2>/dev/null | grep -q "$NAME"; then
      pass "Claude Code lists the plugin ($NAME)"
    else
      fail "Claude Code does not list $NAME: install it (sh install-local.sh) and restart Claude"
    fi
  else
    note "The Claude Code CLI is not on PATH: cannot check which plugins are installed"
  fi
  found=""
  for f in "${CLAUDE_PLUGIN_DATA:-/nonexistent}/status" "$HOME"/.claude/plugins/data/*/status \
           "$HOME/.cache/siem-claude-hooks/status"; do
    [ -r "$f" ] || continue
    found=1
    pass "The hook has run on this machine; its last status ($f):"
    sed 's/^/        /' "$f"
  done
  [ -n "$found" ] || fail "No status file: the hook has not run for this user since version 2.2.0 (start a Claude Code session, then check again)"
  if [ "$failed" = 0 ]; then echo "All checks passed."; else echo "Some checks failed."; fi
  return "$failed"
}

if [ "${1:-}" = "--doctor" ]; then
  doctor
  exit $?
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "The Claude Code CLI (claude) is not on PATH. Install it, then run this again." >&2
  exit 1
fi
NAME=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$HERE/.claude-plugin/plugin.json" 2>/dev/null | head -n 1)
if [ -z "$NAME" ]; then
  echo "No plugin name in .claude-plugin/plugin.json: run this from the unzipped plugin folder." >&2
  exit 1
fi

# A fresh copy each time: removing the marketplace also uninstalls the earlier copy.
claude plugin marketplace remove "$MARKET" >/dev/null 2>&1 || true
rm -rf "$DEST"
mkdir -p "$DEST/.claude-plugin" "$DEST/plugins/$NAME"
cp -R "$HERE/." "$DEST/plugins/$NAME/"
rm -f "$DEST/plugins/$NAME/install-local.sh" "$DEST/plugins/$NAME/install-local.ps1"
chmod 600 "$DEST/plugins/$NAME/config" 2>/dev/null || true
cat > "$DEST/.claude-plugin/marketplace.json" <<EOF
{
  "name": "$MARKET",
  "owner": { "name": "Local test install" },
  "plugins": [
    {
      "name": "$NAME",
      "source": "./plugins/$NAME",
      "description": "Observe-only Claude Code hooks, installed on this machine for testing"
    }
  ]
}
EOF

claude plugin marketplace add "$DEST"
claude plugin install "$NAME@$MARKET" --scope user
claude plugin list
