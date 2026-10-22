#!/usr/bin/env bash
# Known vulnerabilities in shipped frontend packages (docs/security/dependencies.md).
#
# Findings fail at once. Only an error from the audit service itself (network failure,
# timeout, HTTP 429 or 5xx) is retried, up to three tries, so a flaky endpoint does not
# fail the build and a real finding is never retried away. Run from frontend/.
set -uo pipefail

TRIES=${AUDIT_TRIES:-3}
WAIT_S=${AUDIT_WAIT_S:-15}
SERVICE_ERROR='ERR_PNPM_AUDIT_BAD_RESPONSE|responded with (429|5[0-9][0-9])|ECONNRESET|ECONNREFUSED|ETIMEDOUT|ESOCKETTIMEDOUT|EAI_AGAIN|ENOTFOUND|socket hang up|network timeout|timed out'

out=$(mktemp)
err=$(mktemp)
trap 'rm -f "$out" "$err"' EXIT

for try in $(seq 1 "$TRIES"); do
  pnpm audit --prod --json >"$out" 2>"$err"
  code=$?
  if [ "$code" -eq 0 ]; then
    echo "audit: no known vulnerabilities in production packages"
    exit 0
  fi
  # Findings: the audit answered, with a report that lists vulnerabilities.
  if python3 - "$out" <<'PY'
import json, sys
try:
    report = json.load(open(sys.argv[1]))
except ValueError:
    sys.exit(1)
counts = (report.get("metadata") or {}).get("vulnerabilities") or {}
if not any(counts.values()):
    sys.exit(1)
print("audit: FINDINGS, failing now (not retried): " + ", ".join(f"{k} {v}" for k, v in counts.items() if v))
for adv in (report.get("advisories") or {}).values():
    print(f"  {adv.get('severity')}: {adv.get('module_name')} {adv.get('github_advisory_id') or ''} {adv.get('title')}")
PY
  then
    exit 1
  fi
  if grep -Eqi "$SERVICE_ERROR" "$err" "$out"; then
    echo "audit: service error on try $try of $TRIES (not a finding):"
    head -c 600 "$err"; echo
    if [ "$try" -lt "$TRIES" ]; then sleep "$WAIT_S"; fi
    continue
  fi
  echo "audit: failed with an error that is neither a finding nor a service error (exit $code):"
  head -c 1200 "$err"; head -c 1200 "$out"; echo
  exit 1
done
echo "audit: the audit service failed $TRIES times; no result (not a finding)"
exit 1
