#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
bundle_root="$(cd "${script_dir}/.." && pwd -P)"
codex_home="${CODEX_HOME:-${HOME}/.codex}"
force=false
temporary=""

cleanup() {
  if [[ -n "${temporary}" ]]; then
    rm -f "${temporary}"
  fi
}
trap cleanup EXIT

if [[ "${1:-}" == "--force" ]]; then
  force=true
  shift
fi
if (( $# != 0 )); then
  printf 'usage: %s [--force]\n' "$0" >&2
  exit 2
fi

if [[ "${codex_home}" != /* ]]; then
  printf '%s\n' "CODEX_HOME must be an absolute path" >&2
  exit 1
fi
case "/${codex_home}/" in
  *"/../"*|*"/./"*)
    printf '%s\n' "CODEX_HOME must not contain path traversal" >&2
    exit 1
    ;;
esac
if [[ "${codex_home}" == "${bundle_root}" || "${codex_home}" == "${bundle_root}/"* ]]; then
  printf '%s\n' "refusing to write inside the portable bundle" >&2
  exit 1
fi

refuse_symlink_path() {
  local cursor="$1"
  while true; do
    if [[ -L "${cursor}" ]]; then
      printf 'refusing symlink in destination path: %s\n' "${cursor}" >&2
      exit 1
    fi
    if [[ "${cursor}" == "/" ]]; then
      break
    fi
    cursor="$(dirname "${cursor}")"
  done
}

ensure_directory() {
  local directory="$1"
  refuse_symlink_path "${directory}"
  if [[ -e "${directory}" && ! -d "${directory}" ]]; then
    printf 'expected directory: %s\n' "${directory}" >&2
    exit 1
  fi
  mkdir -p "${directory}"
  refuse_symlink_path "${directory}"
  if [[ ! -d "${directory}" || -L "${directory}" ]]; then
    printf 'failed to create regular directory: %s\n' "${directory}" >&2
    exit 1
  fi
}

preflight_regular() {
  local source="$1"
  local destination="$2"
  if [[ ! -f "${source}" || -L "${source}" ]]; then
    printf 'expected non-symlink regular source: %s\n' "${source}" >&2
    exit 1
  fi
  refuse_symlink_path "${destination}"
  if [[ -e "${destination}" && ! -f "${destination}" ]]; then
    printf 'refusing non-file destination: %s\n' "${destination}" >&2
    exit 1
  fi
  if [[ -e "${destination}" && "${force}" != true ]]; then
    printf 'refusing to overwrite existing file without --force: %s\n' "${destination}" >&2
    exit 1
  fi
}

verify_installed() {
  local destination="$1"
  if [[ ! -f "${destination}" || -L "${destination}" ]]; then
    printf 'failed to install regular file: %s\n' "${destination}" >&2
    exit 1
  fi
}

install_regular() {
  local source="$1"
  local destination="$2"
  install -m 600 "${source}" "${destination}"
  chmod 600 "${destination}"
  verify_installed "${destination}"
}

render_profile() {
  local source="$1"
  local destination="$2"
  local escaped_home
  escaped_home="$(printf '%s' "${codex_home}" | sed 's/[&|\\]/\\\\&/g')"
  temporary="$(mktemp)"
  sed "s|@CODEX_HOME@|${escaped_home}|g" "${source}" > "${temporary}"
  install -m 600 "${temporary}" "${destination}"
  chmod 600 "${destination}"
  rm -f "${temporary}"
  temporary=""
  verify_installed "${destination}"
}

ensure_directory "${codex_home}"
ensure_directory "${codex_home}/agents"

preflight_regular "${script_dir}/PPEL.md" "${codex_home}/PPEL.md"
preflight_regular "${script_dir}/PPEL.config.toml.template" "${codex_home}/PPEL.config.toml"
for worker in luna terra sol; do
  preflight_regular "${script_dir}/agents/${worker}.toml" "${codex_home}/agents/${worker}.toml"
done

install_regular "${script_dir}/PPEL.md" "${codex_home}/PPEL.md"
render_profile "${script_dir}/PPEL.config.toml.template" "${codex_home}/PPEL.config.toml"
for worker in luna terra sol; do
  install_regular "${script_dir}/agents/${worker}.toml" "${codex_home}/agents/${worker}.toml"
done

printf '%s\n' "installed PPEL profile and workers under ${codex_home}"
