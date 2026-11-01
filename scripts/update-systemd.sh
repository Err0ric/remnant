#!/bin/sh
# Update a systemd install (docs/install/team-vm.md, option B) to the latest code.
#
#   sudo sh /opt/remnant/scripts/update-systemd.sh            # update and restart
#   sudo sh /opt/remnant/scripts/update-systemd.sh --aide     # check AIDE, update, re-baseline
#   sudo sh /opt/remnant/scripts/update-systemd.sh --aide-accept  # accept reviewed AIDE changes
#   sudo sh /opt/remnant/scripts/update-systemd.sh --no-pull  # code already in place
#   sh /opt/remnant/scripts/update-systemd.sh --print-aide-rules  # show the AIDE rules
#
# With AIDE installed, every run writes this install's AIDE rules to
# /etc/aide/aide.conf.d/90_aide_remnant, replacing that file, and says so when it changes.
# --aide first checks the files against the current baseline, before anything changes;
# changes outside /opt/remnant (other than the rules file and the installed-commit record)
# stop the update until reviewed and accepted.
# It re-baselines only after a successful update (never when nothing was updated).
#
# Fetches origin's main first (a failed fetch stops here, before anything changes, and an
# install whose last successful update was origin/main says so and exits; a checkout moved
# by hand is built even when there is nothing new to fetch), then stops the service, fast-forwards
# to origin/main, checks HEAD matches it, rebuilds the web UI, syncs Python packages, makes the install
# readable by the service user, starts the service, and checks it came up. Migrations run
# on start. Files are written with umask 022 whatever the shell had (F50: an update run
# with umask 077 left root-only files and the service failed with "Permission denied").
#
# Settings (environment): INSTALL_DIR (default /opt/remnant), SERVICE (default remnant),
# REMOTE (default origin), BRANCH (default main), STATE_FILE (default
# <data folder>/installed_commit: the commit last installed), ENV_FILE (default
# /etc/remnant/remnant.env, read for APP__PATHS__DATA_DIR), AIDE_CONF_D (default
# /etc/aide/aide.conf.d).
set -eu

INSTALL_DIR=${INSTALL_DIR:-/opt/remnant}
SERVICE=${SERVICE:-remnant}
REMOTE=${REMOTE:-origin}
BRANCH=${BRANCH:-main}
ENV_FILE=${ENV_FILE:-/etc/remnant/remnant.env}
STATE_FILE=${STATE_FILE:-}
# uid:gid the installed-commit record must have. Read only from this (root) process's
# environment, never from the service's env file, app config, or data folder, which the
# service or its settings can carry; sudo drops it from a caller's shell. Tests set it.
STATE_OWNER=${STATE_OWNER:-0:0}
case $STATE_OWNER in
  *[!0-9:]* | :* | *: | *:*:* | [!0-9]* ) echo "STATE_OWNER must be uid:gid" >&2; exit 2 ;;
esac
AIDE_CONF_D=${AIDE_CONF_D:-/etc/aide/aide.conf.d}
AIDE_CONF=${AIDE_CONF:-/etc/aide/aide.conf}
AIDE=0
ACCEPT=0
PULL=1
PRINT_RULES=0
for arg in "$@"; do
  case $arg in
    --aide) AIDE=1 ;;
    --aide-accept) AIDE=1; ACCEPT=1 ;;
    --no-pull) PULL=0 ;;
    --print-aide-rules) PRINT_RULES=1 ;;
    -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# The data folder from the service's settings (the last APP__PATHS__DATA_DIR line).
DATA_DIR=/var/lib/remnant
if [ -r "$ENV_FILE" ]; then
  found=$(sed -n 's/^[[:space:]]*APP__PATHS__DATA_DIR=[[:space:]]*//p' "$ENV_FILE" | tail -n 1 | tr -d "\"'")
  if [ -n "$found" ]; then DATA_DIR=${found%/}; fi
fi
STATE_FILE=${STATE_FILE:-$DATA_DIR/installed_commit}

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
# Files against the current AIDE baseline, before this run changes anything (owner,
# 2026-11-01: re-baselining without looking first accepts any tampering since the last
# baseline). Sets AIDE_STATE: clean, ours (changes only in the install, the rules file this
# script writes, or the installed-commit record), outside, or error. Nothing else under
# /etc/aide is exempt: a new rules file could hide later tampering (owner, 2026-11-01).
aide_check() {
  step "Checking files against the AIDE baseline"
  report=$(mktemp)
  rc=0
  aide --config "$AIDE_CONF" --check > "$report" 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    AIDE_STATE=clean
    echo "AIDE: no changes since the last baseline."
    rm -f "$report"
    return 0
  fi
  if [ "$rc" -ge 8 ]; then  # 1 to 7: added, removed, changed; higher: AIDE could not check
    AIDE_STATE=error
    echo "AIDE could not check (exit $rc):" >&2
    tail -n 5 "$report" >&2
    rm -f "$report"
    return 0
  fi
  count() { sed -n "s/^[[:space:]]*$1 entries:[[:space:]]*\([0-9][0-9]*\)[[:space:]]*\$/\1/p" "$report" | head -n 1; }
  echo "AIDE: $(count Added) added, $(count Removed) removed, $(count Changed) changed since the last baseline."
  paths=$(sed -n 's/^[^:]*: \(\/.*\)$/\1/p' "$report" | sort -u)
  inst=$(re_escape "$INSTALL_DIR")
  outside=$(printf '%s\n' "$paths" | grep -vE "^$inst(/|\$)" \
    | grep -vxF -e "$STATE_FILE" -e "$AIDE_CONF_D/90_aide_remnant" | grep . || true)
  rm -f "$report"
  if [ -n "$outside" ]; then
    AIDE_STATE=outside
    echo "Changed outside $INSTALL_DIR:"
    printf '%s\n' "$outside" | head -n 25 | sed 's/^/  /'
    n=$(printf '%s\n' "$outside" | wc -l)
    if [ "$n" -gt 25 ]; then echo "  ... and $((n - 25)) more (aide --check for all)"; fi
  else
    AIDE_STATE=ours
  fi
}

aide_baseline() {
  step "Re-baselining AIDE"
  if command -v aideinit >/dev/null 2>&1; then
    aideinit -y -f
  elif command -v aide >/dev/null 2>&1; then
    echo "AIDE is installed without aideinit: run your usual baseline update (aide --update, then replace the database)."
  else
    echo "AIDE is not installed; nothing to do."
  fi
}

AIDE_STATE=none
BASELINE_OK=0
if [ "$AIDE" -eq 1 ] && command -v aide >/dev/null 2>&1; then
  aide_check
  case $AIDE_STATE in
    clean | ours) BASELINE_OK=1 ;;
    outside)
      if [ "$ACCEPT" -eq 0 ]; then
        echo "AIDE found changes not made by this update. Review them, then re-run with --aide-accept. Nothing was changed." >&2
        exit 1
      fi
      echo "Accepted with --aide-accept: the baseline will include these changes."
      BASELINE_OK=1 ;;
    error)
      if [ "$ACCEPT" -eq 0 ]; then
        echo "Fix AIDE first, or re-run with --aide-accept to re-baseline without a check. Nothing was changed." >&2
        exit 1
      fi
      BASELINE_OK=1 ;;
  esac
elif [ "$AIDE" -eq 1 ]; then
  BASELINE_OK=1  # aideinit without aide, or neither: aide_baseline says what it can do
fi

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
# The commit the service last ran after a successful update: "up to date" means this,
# not the checkout (owner, 2026-11-01: a checkout moved by hand was reported up to date
# while the service still ran the old build).
# Trusted only when root wrote it (root:root, 0644, not a link): the data folder belongs
# to the service user, so a file the service could have written is ignored, and the
# update then builds instead of being talked into "up to date" (owner, 2026-11-01).
installed=""
if [ -e "$STATE_FILE" ] || [ -L "$STATE_FILE" ]; then
  if [ ! -L "$STATE_FILE" ] && [ -f "$STATE_FILE" ] \
    && [ "$(stat -c '%u:%g %a' "$STATE_FILE")" = "$STATE_OWNER 644" ]; then
    installed=$(head -n 1 "$STATE_FILE" | tr -dc '0-9a-f')
  else
    echo "Ignoring $STATE_FILE: not a root:root 0644 file. The update will build." >&2
  fi
fi
shown_installed=${installed:+$(printf '%.7s' "$installed")}
shown_installed=${shown_installed:-unknown}

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
  target_full=$(git_ rev-parse "refs/remotes/$REMOTE/$BRANCH")
  if [ "$(git_ rev-parse HEAD)" = "$target_full" ]; then
    if [ "$installed" = "$target_full" ]; then
      printf '\n%s is already up to date at %s (%s/%s, installed). Nothing to do.\n' \
        "$SERVICE" "$before" "$REMOTE" "$BRANCH"
      # Nothing was updated, so nothing explains changes: no re-baseline unless the
      # changes were reviewed and accepted (--aide-accept).
      if [ "$ACCEPT" -eq 1 ]; then
        aide_baseline
      elif [ "$AIDE" -eq 1 ]; then
        echo "Not re-baselining AIDE: nothing was updated."
      fi
      exit 0
    fi
    # The checkout is current but the service is not running it (moved by hand, or a
    # build that never finished): build and restart anyway.
    echo "The checkout is at $before ($REMOTE/$BRANCH) but the installed build is $shown_installed: building it."
  elif ! git_ merge-base --is-ancestor HEAD "refs/remotes/$REMOTE/$BRANCH"; then
    echo "$before is not an ancestor of $REMOTE/$BRANCH ($target): local commits or another branch. Nothing was changed." >&2
    exit 1
  else
    echo "$before -> $target (installed: $shown_installed)"
  fi
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

# Up on the new build: record it, so the next run compares origin/main against what the
# service runs, not against the checkout.
# Root-owned 0644, so the service user cannot edit it in place (see the check above).
mkdir -p "$(dirname "$STATE_FILE")"
state_tmp=$(mktemp "$STATE_FILE.XXXXXX")
git_ rev-parse HEAD > "$state_tmp"
chown "$STATE_OWNER" "$state_tmp"
chmod 0644 "$state_tmp"
mv -f "$state_tmp" "$STATE_FILE"

if [ "$AIDE" -eq 1 ] && [ "$BASELINE_OK" -eq 1 ]; then aide_baseline; fi

printf '\nUpdated %s to %s. Re-baseline any file integrity monitor that watches %s.\n' \
  "$SERVICE" "$after" "$INSTALL_DIR"
