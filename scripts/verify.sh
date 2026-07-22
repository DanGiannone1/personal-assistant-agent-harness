#!/usr/bin/env bash
# Deterministic local verification only. This script deliberately never deploys
# infrastructure or runs Waza model gates.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repository_root}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required tool is unavailable: $1" >&2
    exit 127
  }
}

verify_skip_bicep="${CSA_VERIFY_SKIP_BICEP:-0}"
case "${verify_skip_bicep}" in
  0|1) ;;
  *)
    echo "CSA_VERIFY_SKIP_BICEP must be exactly 0 or 1" >&2
    exit 2
    ;;
esac

for tool in bash git node npm uv; do
  require_command "${tool}"
done

if [[ "${verify_skip_bicep}" == '0' ]]; then
  require_command az
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf "${temporary_dir}"' EXIT

uv lock --check
(cd session-container && uv lock --check)

PYTHONPATH="${repository_root}:${repository_root}/session-container" \
  uv run --project session-container --with pytest pytest -q \
  tests/test_dev_launcher.py tests/test_reset_demo_state.py tests/test_local_quality.py \
  tests/test_identity_modes.py tests/test_engagement_core.py tests/test_structured_control.py \
  tests/test_infra_entra_contract.py tests/test_release_boundaries.py tests/test_skill_runtime.py \
  tests/test_personal_workspace.py tests/test_reminder_dispatch.py

npm run test:mvp-evidence
npm run eval:waza:check
(cd frontend && npm run test:contract && npm run lint && npm run build)

bash -n scripts/verify.sh
bash -n infra/deploy.sh
if [[ "${verify_skip_bicep}" == '0' ]]; then
  az bicep build --file infra/foundation.bicep --outfile "${temporary_dir}/foundation.json"
  az bicep build --file infra/apps.bicep --outfile "${temporary_dir}/apps.json"
fi
git diff --check
