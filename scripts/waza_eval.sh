#!/usr/bin/env bash
set -euo pipefail

WAZA_VERSION="0.38.3"
WAZA_RELEASE="v${WAZA_VERSION}"
REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${REPOSITORY_ROOT}/evidence/mvp/local-synthetic/tools/waza/${WAZA_RELEASE}"
WAZA_BIN="${INSTALL_ROOT}/waza"
RESULTS_ROOT="${REPOSITORY_ROOT}/evidence/mvp/local-synthetic/waza"
EVAL_FILE="${REPOSITORY_ROOT}/tests/evals/waza/engagement-meeting-prep/eval.yaml"
SKILL_DIR="${REPOSITORY_ROOT}/session-container/product-skills/engagement-meeting-prep"

platform_asset() {
  local os arch asset checksum
  case "$(uname -s)" in
    Linux*) os="linux" ;;
    Darwin*) os="darwin" ;;
    *) echo "Unsupported Waza demo OS: $(uname -s)" >&2; return 1 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) echo "Unsupported Waza demo architecture: $(uname -m)" >&2; return 1 ;;
  esac
  asset="waza-${os}-${arch}"
  case "${asset}" in
    waza-linux-amd64) checksum="168e3562deeaa1958d44366b37d963b48b091c325c6c9b5b2613e5399ff077b9" ;;
    waza-linux-arm64) checksum="ab5d6a3e502a0f7f5a48149e034fa07875a2fe02addddec6b9b9dba14f3b4685" ;;
    waza-darwin-amd64) checksum="f2a0c6952abbb5ad75bf17e2769c34c480093c269574839368b82d40b3c5dec9" ;;
    waza-darwin-arm64) checksum="99aa4366b198f319145cffeef42d500eb9f6178235a0537d34c19dd8f2f46fec" ;;
    *) echo "No pinned checksum for ${asset}" >&2; return 1 ;;
  esac
  printf '%s %s\n' "${asset}" "${checksum}"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "A SHA-256 utility (sha256sum or shasum) is required" >&2
    return 1
  fi
}

install_waza() {
  local platform asset checksum temporary actual
  platform="$(platform_asset)"
  asset="${platform%% *}"
  checksum="${platform##* }"
  if [[ -x "${WAZA_BIN}" ]]; then
    actual="$(sha256_file "${WAZA_BIN}")"
    if [[ "${actual}" == "${checksum}" ]] && "${WAZA_BIN}" --version | grep -q "${WAZA_VERSION}"; then
      return
    fi
    echo "Pinned Waza binary failed its version/checksum check: ${WAZA_BIN}" >&2
    return 1
  fi
  mkdir -p "${INSTALL_ROOT}"
  temporary="$(mktemp "${INSTALL_ROOT}/waza.download.XXXXXX")"
  trap 'rm -f "${temporary}"' EXIT
  curl -fL "https://github.com/microsoft/waza/releases/download/${WAZA_RELEASE}/${asset}" -o "${temporary}"
  actual="$(sha256_file "${temporary}")"
  if [[ "${actual}" != "${checksum}" ]]; then
    echo "Waza checksum mismatch for ${asset}: expected ${checksum}, got ${actual}" >&2
    return 1
  fi
  chmod 0755 "${temporary}"
  mv "${temporary}" "${WAZA_BIN}"
  trap - EXIT
  "${WAZA_BIN}" --version
}

run_eval() {
  local tag="${1:-}" run_stamp run_dir result_path before_hash after_hash
  local source_revision source_revision_after source_dirty_before source_dirty_after
  run_stamp="$(date -u +%Y-%m-%dT%H%M%SZ)-$$"
  run_dir="${RESULTS_ROOT}/${run_stamp}"
  result_path="${run_dir}/waza.json"
  mkdir -p "${run_dir}/transcripts"
  before_hash="$(sha256_file "${SKILL_DIR}/SKILL.md")"
  source_revision="$(git rev-parse HEAD)"
  source_dirty_before="false"
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    source_dirty_before="true"
  fi
  local args=(run "${EVAL_FILE}" --output "${result_path}" --transcript-dir "${run_dir}/transcripts" --interpret --no-cache)
  if [[ -n "${tag}" ]]; then
    args+=(--tags "${tag}")
  fi
  WAZA_NO_UPDATE_CHECK=1 "${WAZA_BIN}" "${args[@]}"
  after_hash="$(sha256_file "${SKILL_DIR}/SKILL.md")"
  if [[ "${before_hash}" != "${after_hash}" ]]; then
    echo "Product skill changed during the Waza run; refusing unbound evidence" >&2
    return 1
  fi
  source_revision_after="$(git rev-parse HEAD)"
  source_dirty_after="false"
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    source_dirty_after="true"
  fi
  node - "${result_path}" "${before_hash}" "${tag:-all}" "${source_revision}" \
    "${source_revision_after}" "${source_dirty_before}" "${source_dirty_after}" <<'NODE'
const fs = require("node:fs");
const [resultPath, skillSha256, tag, sourceRevision, sourceRevisionAfter, sourceDirtyBefore, sourceDirtyAfter] = process.argv.slice(2);
const report = JSON.parse(fs.readFileSync(resultPath, "utf8"));
report.csaMvpProvenance = {
  runner: "scripts/waza_eval.sh",
  wazaVersion: "0.38.3",
  sourceRevision,
  sourceRevisionAfter,
  sourceDirtyBefore: sourceDirtyBefore === "true",
  sourceDirtyAfter: sourceDirtyAfter === "true",
  tag,
  skill: {
    name: "engagement-meeting-prep",
    path: "session-container/product-skills/engagement-meeting-prep/SKILL.md",
    sha256: skillSha256,
  },
  eval: "tests/evals/waza/engagement-meeting-prep/eval.yaml",
  recordedAt: new Date().toISOString(),
};
fs.writeFileSync(resultPath, `${JSON.stringify(report, null, 2)}\n`);
NODE
  echo "CSA MVP provenance recorded in: ${result_path}"
}

check_skill() {
  local result
  result="$(mktemp)"
  if ! WAZA_NO_UPDATE_CHECK=1 "${WAZA_BIN}" check "${SKILL_DIR}" --format json >"${result}"; then
    rm -f "${result}"
    return 1
  fi
  if ! node -e '
    const report = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
    if (!Array.isArray(report.skills) || report.skills.length !== 1 || report.skills[0].ready !== true) {
      console.error("Waza readiness did not approve exactly one skill");
      process.exit(1);
    }
  ' "${result}"; then
    rm -f "${result}"
    return 1
  fi
  rm -f "${result}"
  WAZA_NO_UPDATE_CHECK=1 "${WAZA_BIN}" check "${SKILL_DIR}"
}

install_waza
cd "${REPOSITORY_ROOT}"

case "${1:-check}" in
  install|version)
    "${WAZA_BIN}" --version
    ;;
  check)
    check_skill
    ;;
  gate)
    run_eval gate
    ;;
  advisory)
    run_eval advisory
    ;;
  run)
    run_eval
    ;;
  *)
    echo "Usage: scripts/waza_eval.sh [install|version|check|gate|advisory|run]" >&2
    exit 2
    ;;
esac
