#!/bin/sh
# Update a systemd install (docs/install/team-vm.md, option B) to the latest code.
#
#   sudo sh /opt/remnant/scripts/update-systemd.sh            # update and restart
#   sudo sh /opt/remnant/scripts/update-systemd.sh --aide     # also re-baseline AIDE
#   sudo sh /opt/remnant/scripts/update-systemd.sh --no-pull  # code already in place
#   sh /opt/remnant/scripts/update-systemd.sh --print-aide-rules  # show the AIDE rules
#
# With AIDE installed, every run writes this install's AIDE rules to
# /etc/aide/aide.conf.d/90_aide_remnant, replacing that file, and says so when it changes.
#
# Fetches origin's main first (a failed fetch stops here, before anything changes, and an
# install already at origin/main says so and exits), then stops the service, fast-forwards
# to origin/main, checks HEAD matches it, rebuilds the web UI, syncs Python packages, makes the install
# readable by the service user, starts the service, and checks it came up. Migrations run
# on start. Files are written with umask 022 whatever the shell had (F50: an update run
# with umask 077 left root-only files and the service failed with "Permission denied").
#
# Settings (environment): INSTALL_DIR (default /opt/remnant), SERVICE (default remnant),
# REMOTE (default origin), BRANCH (default main), ENV_FILE (default
# /etc/remnant/remnant.env, read for APP__PATHS__DATA_DIR), AIDE_CONF_D (default
# /etc/aide/aide.conf.d).
set -eu

INSTALL_DIR=${INSTALL_DIR:-/opt/remnant}
SERVICE=${SERVICE:-remnant}
REMOTE=${REMOTE:-origin}
BRANCH=${BRANCH:-main}
ENV_FILE=${ENV_FILE:-/etc/remnant/remnant.env}
AIDE_CONF_D=${AIDE_CONF_D:-/etc/aide/aide.conf.d}
AIDE=0
PULL=1
PRINT_RULES=0
for arg in "$@"; do
  case $arg in
    --aide) AIDE=1 ;;
    --no-pull) PULL=0 ;;
    --print-aide-rules) PRINT_RULES=1 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# The data folder from the service's settings (the last APP__PATHS__DATA_DIR line).
DATA_DIR=/var/lib/remnant
if [ -r "$ENV_FILE" ]; then
  found=$(sed -n 's/^[[:space:]]*APP__PATHS__DATA_DIR=[[:space:]]*//p' "$ENV_FILE" | tail -n 1 | tr -d "\"'")
  if [ -n "$found" ]; then DATA_DIR=${found%/}; fi
fi

# AIDE rules (docs/install/team-vm.md, File integrity): skip data that changes on its own
# and node_modules. Everything else stays under the distribution's rules, including tls/,
# .venv, .python, backend/app, frontend/dist, and .git (this script runs git as root, so a
# changed hook would run on the next update).
re_escape() { printf '%s' "$1" | sed 's/[][\.^$*+?(){}|]/\\&/g'; }
aide_rules() {
  d=$(re_escape "$DATA_DIR")
  i=$(re_escape "$INSTALL_DIR")
  echo "# Written by $INSTALL_DIR/scripts/update-systemd.sh; replaced on every update."
  echo "# Data that changes constantly and has its own checks (docs/install/integrity.md)."
  for sub in lake rollup tmp enrichment; do
    printf '!%s/%s(/|$)\n' "$d" "$sub"
  done
  printf '!%s/meta\\.sqlite\n' "$d"
  echo "# JavaScript packages, rebuilt from the lockfile by every update."
  printf '!%s/frontend/node_modules(/|$)\n' "$i"
}
if [ "$PRINT_RULES" -eq 1 ]; then
  aide_rules
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo sh $0)." >&2
  exit 1
fi
[ -d "$INSTALL_DIR/.git" ] || { echo "$INSTALL_DIR is not a git checkout." >&2; exit 1; }
# git refuses a checkout owned by another user ("dubious ownership") unless it is listed
# in safe.directory; say so plainly instead of failing on the first git command.
if ! err=$(git -C "$INSTALL_DIR" rev-parse --git-dir 2>&1 >/dev/null); then
  echo "git cannot read $INSTALL_DIR: $err" >&2
  case $err in
    *"dubious ownership"*)
      echo "It is owned by $(stat -c %U "$INSTALL_DIR"). Either: chown -R root:root $INSTALL_DIR, or: git config --global --add safe.directory $INSTALL_DIR" >&2 ;;
  esac
  echo "Nothing was changed." >&2
  exit 1
fi

umask 022
step() { printf '\n== %s\n' "$1"; }
git_() { git -C "$INSTALL_DIR" "$@"; }

# Only with AIDE installed; one file at this exact path, overwritten, never a second one.
if [ -d "$AIDE_CONF_D" ] && { command -v aide >/dev/null 2>&1 || command -v aideinit >/dev/null 2>&1; }; then
  rules="$AIDE_CONF_D/90_aide_remnant"
  new=$(aide_rules)
  if [ ! -f "$rules" ] || [ "$(cat "$rules")" != "$new" ]; then
    verb=written; [ -f "$rules" ] && verb=replaced
    printf '%s\n' "$new" > "$rules"
    chmod 0644 "$rules"
    echo "AIDE rules $verb: $rules (data folder $DATA_DIR)"
  fi
fi

stopped=0
restart_on_error() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$stopped" -eq 1 ]; then
    echo "Update failed (exit $status). Starting the service on whatever is installed." >&2
    chmod -R a+rX "$INSTALL_DIR" || true
    systemctl start "$SERVICE" || true
  fi
}
trap restart_on_error EXIT

before=$(git_ rev-parse --short HEAD)

if [ "$PULL" -eq 1 ]; then
  # The fetch runs here, with the service still up: it never depends on the branch's
  # upstream, and a failure ends the update before anything changes (owner, 2026-11-01:
  # an update once reported success at the old commit).
  step "Fetching $BRANCH from $REMOTE ($(git_ remote get-url "$REMOTE" 2>/dev/null || echo 'no such remote'))"
  if ! git_ fetch "$REMOTE" "+refs/heads/$BRANCH:refs/remotes/$REMOTE/$BRANCH"; then
    echo "git fetch from $REMOTE failed. Nothing was changed; $SERVICE is still at $before." >&2
    exit 1
  fi
  target=$(git_ rev-parse --short "refs/remotes/$REMOTE/$BRANCH")
  if [ "$(git_ rev-parse HEAD)" = "$(git_ rev-parse "refs/remotes/$REMOTE/$BRANCH")" ]; then
    printf '\n%s is already up to date at %s (%s/%s). Nothing to do.\n' \
      "$SERVICE" "$before" "$REMOTE" "$BRANCH"
    exit 0
  fi
  if ! git_ merge-base --is-ancestor HEAD "refs/remotes/$REMOTE/$BRANCH"; then
    echo "$before is not an ancestor of $REMOTE/$BRANCH ($target): local commits or another branch. Nothing was changed." >&2
    exit 1
  fi
  echo "$before -> $target"
fi

step "Stopping $SERVICE"
systemctl stop "$SERVICE"
stopped=1

if [ "$PULL" -eq 1 ]; then
  step "Moving to $REMOTE/$BRANCH"
  git_ merge --ff-only "refs/remotes/$REMOTE/$BRANCH"
  if [ "$(git_ rev-parse HEAD)" != "$(git_ rev-parse "refs/remotes/$REMOTE/$BRANCH")" ]; then
    echo "HEAD is $(git_ rev-parse --short HEAD), not $REMOTE/$BRANCH ($target)." >&2
    exit 1
  fi
fi
after=$(git_ rev-parse --short HEAD)

step "Building the web UI"
cd "$INSTALL_DIR/frontend"
COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm install --frozen-lockfile
pnpm build

step "Syncing Python packages"
cd "$INSTALL_DIR/backend"
UV_PYTHON_INSTALL_DIR="$INSTALL_DIR/.python" uv sync --frozen --no-dev

step "Making the install readable by the service user"
chmod -R a+rX "$INSTALL_DIR"

step "Starting $SERVICE (migrations run on start)"
started=$(date '+%Y-%m-%d %H:%M:%S')
systemctl start "$SERVICE"
stopped=0

# Up when the "listening on" line is in the journal, within 60 seconds.
i=0
while [ $i -lt 60 ]; do
  if ! systemctl is-active --quiet "$SERVICE" && [ $i -gt 5 ]; then break; fi
  if journalctl -u "$SERVICE" --since "$started" --no-pager -q | grep -q "listening on"; then
    break
  fi
  sleep 1
  i=$((i + 1))
done

step "Startup lines"
journalctl -u "$SERVICE" --since "$started" --no-pager -q -o cat | head -n 20

if ! systemctl is-active --quiet "$SERVICE" \
  || ! journalctl -u "$SERVICE" --since "$started" --no-pager -q | grep -q "listening on"; then
  printf "\n%s is not up. See: journalctl -u %s -n 50\n" "$SERVICE" "$SERVICE" >&2
  exit 1
fi

if [ "$AIDE" -eq 1 ]; then
  step "Re-baselining AIDE"
  if command -v aideinit >/dev/null 2>&1; then
    aideinit -y -f
  elif command -v aide >/dev/null 2>&1; then
    echo "AIDE is installed without aideinit: run your usual baseline update (aide --update, then replace the database)."
  else
    echo "AIDE is not installed; nothing to do."
  fi
fi

printf '\nUpdated %s to %s. Re-baseline any file integrity monitor that watches %s.\n' \
  "$SERVICE" "$after" "$INSTALL_DIR"
