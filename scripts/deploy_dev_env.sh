#!/usr/bin/env bash
# Launch the dev (demo-mode) environment deployment with fixed dev parameters.
# Preview by default; pass --apply to actually build. Runs from a clean
# temporary checkout of HEAD so the main worktree's local changes don't block it.
set -euo pipefail

APPLY_FLAG=false
[[ "${1:-}" == "--apply" ]] && APPLY_FLAG=true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${CSA_DEV_DEPLOY_DIR:-/tmp/csa-deploy}"

if [[ ! -d "$DEPLOY_DIR/.git" && ! -f "$DEPLOY_DIR/.git" ]]; then
  git -C "$ROOT" worktree add "$DEPLOY_DIR" HEAD
else
  git -C "$DEPLOY_DIR" checkout --detach HEAD >/dev/null 2>&1 || true
fi

if [[ -z "${DEMO_PASSWORD:-}" ]]; then
  # shellcheck disable=SC1091
  [[ -f /tmp/eval-infra.env ]] && source /tmp/eval-infra.env
  DEMO_PASSWORD="${DEVPW:-}"
fi
[[ -n "${DEMO_PASSWORD:-}" ]] || { echo "ERROR: set DEMO_PASSWORD (or DEVPW in /tmp/eval-infra.env)" >&2; exit 1; }

cd "$DEPLOY_DIR"
APPLY="$APPLY_FLAG" \
RESOURCE_GROUP="${RESOURCE_GROUP:-csa-workbench-dev-rg}" \
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-csa-workbench-dev-env}" \
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-csa-workbench-dev-frontend}" \
API_APP_NAME="${API_APP_NAME:-csa-workbench-dev-api}" \
RUNTIME_APP_NAME="${RUNTIME_APP_NAME:-csa-workbench-dev-runtime}" \
COSMOS_ACCOUNT_NAME="${COSMOS_ACCOUNT_NAME:-csawbdev71944}" \
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-csawbdevsa71944}" \
ACR_NAME="${ACR_NAME:-csawbdevacr71944}" \
AOAI_NAME="${AOAI_NAME:-csa-workbench-dev-ai}" \
IDENTITY_MODE=demo DEMO_PASSWORD="$DEMO_PASSWORD" \
bash infra/deploy.sh
