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
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
MARKET="@MARKETPLACE@"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/$MARKET"

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
