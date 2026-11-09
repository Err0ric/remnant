#!/usr/bin/env bash
# Workspace hygiene for CI jobs on the self-hosted runner (D217, docs/dev/self-hosted-runner.md).
#   prep   after checkout: tool installs, caches, and browser downloads go to this job's temp
#          folder (the runner empties it at every job start), never the runner user's home
#   clean  last step, always: stop servers the job started and remove everything git does not
#          track, ignored files included (venvs, node_modules, build output, data folders)
set -euo pipefail
: "${RUNNER_TEMP:?run this from a CI job}" "${GITHUB_WORKSPACE:?run this from a CI job}"

case "${1:-}" in
  prep)
    : "${GITHUB_ENV:?}"
    {
      echo "UV_CACHE_DIR=$RUNNER_TEMP/uv-cache"
      echo "UV_PYTHON_INSTALL_DIR=$RUNNER_TEMP/uv-python"
      echo "UV_PYTHON_PREFERENCE=only-managed"  # never a Python installed on the host
      echo "UV_TOOL_DIR=$RUNNER_TEMP/uv-tools"
      echo "npm_config_store_dir=$RUNNER_TEMP/pnpm-store"
      echo "PLAYWRIGHT_BROWSERS_PATH=$RUNNER_TEMP/ms-playwright"
      echo "XDG_CACHE_HOME=$RUNNER_TEMP/xdg-cache"
      echo "XDG_DATA_HOME=$RUNNER_TEMP/xdg-data"
      echo "XDG_CONFIG_HOME=$RUNNER_TEMP/xdg-config"
    } >> "$GITHUB_ENV"
    echo "self-hosted prep done"
    ;;
  clean)
    # Servers started from this checkout's virtual environment (the layout check's app-server).
    pkill -f -- "$GITHUB_WORKSPACE/backend/.venv/" 2>/dev/null || true
    cd "$GITHUB_WORKSPACE"
    if [ -d .git ]; then
      git reset -q --hard
      git clean -ffdxq
    fi
    echo "self-hosted clean done"
    ;;
  *)
    echo "usage: $0 prep|clean" >&2
    exit 2
    ;;
esac
