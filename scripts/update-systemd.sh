#!/bin/sh
# Update a systemd install (docs/install/team-vm.md, option B) to the latest code.
#
#   sudo sh /opt/remnant/scripts/update-systemd.sh            # update and restart
#   sudo sh /opt/remnant/scripts/update-systemd.sh --aide     # check AIDE, update, re-baseline
#   sudo sh /opt/remnant/scripts/update-systemd.sh --aide-accept  # accept reviewed AIDE changes
#   sudo sh /opt/remnant/scripts/update-systemd.sh --no-pull  # code already in place
#   sudo sh /opt/remnant/scripts/update-systemd.sh --rollback # back to the version before the last update
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
# Each successful update also records the commit it replaced (previous_commit, next to
# installed_commit, same rules). --rollback stops the service, checks that commit out
# (detached, verified), rebuilds as an update does, starts the service, and records it as
# installed. It goes back one update only: a second --rollback is refused until the next
# update (which also rolls forward). It refuses, changing nothing, without a recorded
# previous commit or with uncommitted changes to tracked files. The database keeps what the
# newer version added (migrations are additive; docs/install/team-vm.md, Roll back).
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
ROLLBACK=0
for arg in "$@"; do
  case $arg in
    --aide) AIDE=1 ;;
    --aide-accept) AIDE=1; ACCEPT=1 ;;
    --no-pull) PULL=0 ;;
    --print-aide-rules) PRINT_RULES=1 ;;
    --rollback) ROLLBACK=1; PULL=0 ;;
    -h|--help) sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
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
# Next to it, under the same rules: the commit the last update replaced (the rollback
# target), and after a rollback, the commit rolled back from (for the refusal message).
PREV_FILE=$(dirname "$STATE_FILE")/previous_commit
FROM_FILE=$(dirname "$STATE_FILE")/rolled_back_from

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
  for sub in lake rollup tmp enrichment spool; do
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
# The changed paths that matter most first (system configuration, programs, the install
# area, service data: /etc, /usr, /opt, /var/lib), then the rest, up to LIST_MAX, then a
# count per top folder, so a busy folder such as /run cannot push an important path out
# of the list (owner, 2026-11-01).
LIST_MAX=25
show_outside() {
  all=$1
  n=$(printf '%s\n' "$all" | wc -l)
  echo "Changed outside $INSTALL_DIR: $n paths."
  important=$(printf '%s\n' "$all" | grep -E '^/(etc|usr|opt|var/lib)(/|$)' || true)
  rest=$(printf '%s\n' "$all" | grep -vE '^/(etc|usr|opt|var/lib)(/|$)' || true)
  printf '%s\n%s\n' "$important" "$rest" | grep . | head -n "$LIST_MAX" | sed 's/^/  /'
  if [ "$n" -gt "$LIST_MAX" ]; then
    echo "  ... and $((n - LIST_MAX)) more. By folder:"
    printf '%s\n' "$all" \
      | awk -F/ '{ top = "/" $2; if ($2 == "var" && NF > 2) top = top "/" $3; n[top]++ }
                 END { for (t in n) printf "%d %s\n", n[t], t }' \
      | sort -k1,1nr -k2 \
      | awk '{ printf "  %s: %d %s\n", $2, $1, ($1 == 1 ? "entry" : "entries") }'
    echo "  (aide --check lists them all)"
  fi
}

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
  # Paths only from the entry lists (Added, Removed, Changed: "f+++++: /path",
  # "f   ...    .C... : /path"), never from the details after them, where a hash or its
  # continuation line can start with "/" (owner, 2026-11-03: hashes were listed as paths).
  paths=$(awk '/^Detailed information/ { exit }
               /^[a-zA-Z!][^:]*: \// { sub(/^[^:]*: /, ""); print }' "$report" | sort -u)
  inst=$(re_escape "$INSTALL_DIR")
  outside=$(printf '%s\n' "$paths" | grep -vE "^$inst(/|\$)" \
    | grep -vxF -e "$STATE_FILE" -e "$PREV_FILE" -e "$FROM_FILE" -e "$AIDE_CONF_D/90_aide_remnant" \
    | grep . || true)
  rm -f "$report"
  if [ -n "$outside" ]; then
    AIDE_STATE=outside
    show_outside "$outside"
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

# Only with AIDE installed; one file at this exact path, overwritten, never a second one.
# Written before the --aide check, so the check runs with this install's current rules:
# rules left by an older script (no spool rule) otherwise flagged the spool on every
# check and stopped the run before they could be replaced (owner, 2026-11-04).
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

# a+rX, but only on what lacks it: chmod changes a file's ctime even when the mode is
# already right, and AIDE then reports every file (owner, 2026-11-01).
make_readable() {
  find "$1" \( \( -type d ! -perm -0555 \) -o \( -type f ! -perm -0444 \) \
    -o \( -type f -perm /0111 ! -perm -0111 \) \) -exec chmod a+rX {} +
}

stopped=0
ACTION=Update; [ "$ROLLBACK" -eq 1 ] && ACTION=Rollback
restart_on_error() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$stopped" -eq 1 ]; then
    echo "$ACTION failed (exit $status). Starting the service on whatever is installed." >&2
    make_readable "$INSTALL_DIR" || true
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
read_record() {  # $1 file, $2 what ignoring it means
  if [ -e "$1" ] || [ -L "$1" ]; then
    if [ ! -L "$1" ] && [ -f "$1" ] && [ "$(stat -c '%u:%g %a' "$1")" = "$STATE_OWNER 644" ]; then
      head -n 1 "$1" | tr -dc '0-9a-f'
    else
      echo "Ignoring $1: not a root:root 0644 file. $2" >&2
    fi
  fi
}
write_record() {  # $1 file, $2 commit: root-owned 0644, replaced in one step
  mkdir -p "$(dirname "$1")"
  record_tmp=$(mktemp "$1.XXXXXX")
  printf '%s\n' "$2" > "$record_tmp"
  chown "$STATE_OWNER" "$record_tmp"
  chmod 0644 "$record_tmp"
  mv -f "$record_tmp" "$1"
}
short() { printf '%.7s' "$1"; }
installed=$(read_record "$STATE_FILE" "The update will build.")
shown_installed=${installed:+$(short "$installed")}
shown_installed=${shown_installed:-unknown}
before_full=$(git_ rev-parse HEAD)

if [ "$ROLLBACK" -eq 1 ]; then
  prev=$(read_record "$PREV_FILE" "Rolling back needs a record written by the update script.")
  if [ -z "$prev" ]; then
    from=$(read_record "$FROM_FILE" "")
    if [ -n "$from" ]; then
      echo "Already rolled back from $(short "$from") to $shown_installed. A second rollback is refused: it goes back one update only. To roll forward: sudo sh $INSTALL_DIR/scripts/update-systemd.sh. Nothing was changed." >&2
    else
      echo "No previous version is recorded in $PREV_FILE, so there is nothing to roll back to (one is recorded by every successful update). Nothing was changed." >&2
    fi
    exit 1
  fi
  if ! prev_full=$(git_ rev-parse -q --verify "$prev^{commit}"); then
    echo "The previous version $(short "$prev") is not in $INSTALL_DIR. Nothing was changed." >&2
    exit 1
  fi
  if ! git_ merge-base --is-ancestor "$prev_full" HEAD; then
    echo "The previous version $(short "$prev") is not an ancestor of the checkout ($before). Nothing was changed." >&2
    exit 1
  fi
  if [ -n "$(git_ status --porcelain --untracked-files=no)" ]; then
    echo "$INSTALL_DIR has uncommitted changes (git -C $INSTALL_DIR status). Rolling back would mix them in; commit or discard them first. Nothing was changed." >&2
    exit 1
  fi
  rolled_from=${installed:-$before_full}
  step "Rolling back $SERVICE"
  echo "$(short "$rolled_from") -> $(short "$prev_full") (the version before the last update)"
fi

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
  # Detached after a rollback: the move puts $BRANCH back at $REMOTE/$BRANCH, but only
  # when that loses no local commit on it.
  attach=0
  if ! git_ symbolic-ref -q HEAD >/dev/null; then
    attach=1
    if git_ rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null \
      && ! git_ merge-base --is-ancestor "refs/heads/$BRANCH" "refs/remotes/$REMOTE/$BRANCH"; then
      echo "Local $BRANCH has commits that are not on $REMOTE/$BRANCH. Nothing was changed." >&2
      exit 1
    fi
  fi
fi

step "Stopping $SERVICE"
systemctl stop "$SERVICE"
stopped=1

if [ "$PULL" -eq 1 ]; then
  step "Moving to $REMOTE/$BRANCH"
  if [ "$attach" -eq 1 ]; then
    git_ checkout -q -B "$BRANCH" "refs/remotes/$REMOTE/$BRANCH"
  else
    git_ merge --ff-only "refs/remotes/$REMOTE/$BRANCH"
  fi
  if [ "$(git_ rev-parse HEAD)" != "$(git_ rev-parse "refs/remotes/$REMOTE/$BRANCH")" ]; then
    echo "HEAD is $(git_ rev-parse --short HEAD), not $REMOTE/$BRANCH ($target)." >&2
    exit 1
  fi
fi
if [ "$ROLLBACK" -eq 1 ]; then
  step "Checking out $(short "$prev_full") (detached)"
  git_ checkout -q --detach "$prev_full"
  if [ "$(git_ rev-parse HEAD)" != "$prev_full" ]; then
    echo "HEAD is $(git_ rev-parse --short HEAD), not $(short "$prev_full")." >&2
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
make_readable "$INSTALL_DIR"

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
now_full=$(git_ rev-parse HEAD)
if [ "$ROLLBACK" -eq 1 ]; then
  # One step back only: the target is used up, so a second rollback is refused rather
  # than swapping back to the newer build without the update's fetch and checks.
  write_record "$FROM_FILE" "$rolled_from"
  write_record "$STATE_FILE" "$now_full"
  rm -f "$PREV_FILE"
else
  replaced=${installed:-$before_full}  # what the service ran, or else the old checkout
  if [ "$replaced" != "$now_full" ]; then write_record "$PREV_FILE" "$replaced"; fi
  write_record "$STATE_FILE" "$now_full"
  rm -f "$FROM_FILE"
fi

if [ "$AIDE" -eq 1 ] && [ "$BASELINE_OK" -eq 1 ]; then aide_baseline; fi

if [ "$ROLLBACK" -eq 1 ]; then
  printf '\nRolled back %s from %s to %s. The database keeps what the newer version added; it is used again after the next update.\n' \
    "$SERVICE" "$(short "$rolled_from")" "$after"
  printf 'Re-baseline any file integrity monitor that watches %s.\n' "$INSTALL_DIR"
else
  printf '\nUpdated %s to %s. Re-baseline any file integrity monitor that watches %s.\n' \
    "$SERVICE" "$after" "$INSTALL_DIR"
fi
