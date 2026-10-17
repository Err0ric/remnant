#!/usr/bin/env bash
# Architecture guardrails enforced in CI (CLAUDE.md sections 2 and 8).
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0

# Rule 2: only llm/gate.py (and tests) may import provider adapters.
if grep -rnE "(from|import) +app\.llm\.providers" backend/app \
    --include=*.py | grep -v "^backend/app/llm/gate.py:" ; then
  echo "error: provider adapters may only be imported by backend/app/llm/gate.py" >&2
  fail=1
fi

# Rule 15: the CLI is an API client and never touches engine, ingest, or metadata code.
if grep -rnE "(from|import) +app\.(engine|ingest|meta)" backend/app/cli --include=*.py ; then
  echo "error: backend/app/cli must not import engine, ingest, or meta (CLAUDE.md rule 15)" >&2
  fail=1
fi

# Rule 11: the product name lives in one constant. Keep it out of code elsewhere.
name=$(sed -nE 's/^PRODUCT_NAME: Final\[str\] = "(.+)"$/\1/p' backend/app/core/branding.py)
if [ -z "$name" ]; then
  echo "error: could not read PRODUCT_NAME from backend/app/core/branding.py" >&2
  fail=1
elif grep -rnI "$name" backend/app frontend/src frontend/index.html \
    | grep -v "^backend/app/core/branding.py:" ; then
  echo "error: product name hardcoded outside the branding constant" >&2
  fail=1
fi

# Section 8 rule 6: no em dashes in code, docs, or UI copy.
if grep -rnI $'\xe2\x80\x94' --exclude-dir=node_modules --exclude-dir=.venv \
    --exclude-dir=dist --exclude-dir=.git --exclude=pnpm-lock.yaml --exclude=uv.lock . ; then
  echo "error: em dash found" >&2
  fail=1
fi

# DESIGN.md: no dangerouslySetInnerHTML anywhere in the frontend.
if grep -rn "dangerouslySetInnerHTML" frontend/src ; then
  echo "error: dangerouslySetInnerHTML is banned" >&2
  fail=1
fi

# Security rule 11: base images by digest, workflow actions by commit.
if grep -nE '^FROM ' Dockerfile | grep -v '@sha256:' ; then
  echo "error: Dockerfile base image not pinned by digest" >&2
  fail=1
fi
if grep -nE '^\s+image: ' docker-compose.yml | grep -vE '@sha256:|image: app:' ; then
  echo "error: compose image not pinned by digest" >&2
  fail=1
fi
if grep -nE '^\s+(- )?uses: ' .github/workflows/*.yml | grep -vE '@[0-9a-f]{40}( |$)' ; then
  echo "error: workflow action not pinned to a commit" >&2
  fail=1
fi

[ "$fail" -eq 0 ] && echo "architecture checks passed"
exit "$fail"
