#!/usr/bin/env bash
# Pilotfish scripted install bootstrap.
#
# Local checkouts are preferred. When this file is streamed from a URL, the
# installer is downloaded from the selected GitHub ref into a private temp
# directory and then delegated to install/install.py.
#
# Local:
#   bash install/install.sh --dry-run --codex-home "$CODEX_HOME"
#
# Pinned remote:
#   curl -fsSL \
#     https://raw.githubusercontent.com/miyago9267/pilotfish-codex/<release-tag-or-commit-sha>/install/install.sh \
#     | bash -s -- --ref <release-tag-or-commit-sha> --dry-run

set -Eeuo pipefail

REPO="miyago9267/pilotfish-codex"
REF="${PILOTFISH_REF:-main}"
FORWARDED_ARGS=()

usage() {
  cat <<'EOF'
Usage: install/install.sh [wrapper options] [installer options]

Wrapper options:
  --help             Show this help and exit without checking Codex.
  --ref REF         Download the GitHub source at REF when no local checkout
                     is available. The same value may be written --ref=REF.

Installer options are forwarded unchanged to install.py. Supported options
include --dry-run, --codex-home, --follow-policy-symlink,
--policy-root, --reconcile-current, --allow-plugin-downgrade,
--replace-drifted-role, and --replace-drifted-roles.

PILOTFISH_REF is used when --ref is not supplied; the default is main. A local
checkout containing install/install.py and templates/agents is always preferred
over a remote download, so use the pinned raw script URL for a pinned remote
install.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 2
}

validate_ref() {
  local ref="$1"
  if [[ -z "$ref" ]]; then
    fail "ref must not be empty"
  fi
  case "$ref" in
    *..*) fail "ref contains '..' and is not allowed" ;;
    /*) fail "ref must not start with '/'" ;;
    *//*) fail "ref must not contain '//'" ;;
    */) fail "ref must not end with '/'" ;;
    *[!A-Za-z0-9._/-]*) fail "ref contains unsafe characters" ;;
  esac
}

while (($# > 0)); do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --ref)
      (($# >= 2)) || fail "--ref requires a value"
      REF="$2"
      shift 2
      ;;
    --ref=*)
      REF="${1#--ref=}"
      shift
      ;;
    --)
      shift
      FORWARDED_ARGS+=("$@")
      break
      ;;
    *)
      FORWARDED_ARGS+=("$1")
      shift
      ;;
  esac
done

validate_ref "$REF"

script_source="${BASH_SOURCE[0]:-}"
local_root=""
if [[ -n "$script_source" && -f "$script_source" ]]; then
  local_root="$(cd -- "$(dirname -- "$script_source")/.." && pwd -P)"
fi

if [[ -n "$local_root" \
  && -f "$local_root/install/install.py" \
  && -d "$local_root/templates/agents" ]]; then
  echo "selected source: local checkout ($local_root)" >&2
  echo "selected ref: $REF (used only for a remote archive)" >&2
  command -v python3 >/dev/null 2>&1 || fail "python3 is required"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "python3 >= 3.11 is required (tomllib)"
  command -v codex >/dev/null 2>&1 || fail "codex CLI is required"
  exec python3 "$local_root/install/install.py" "${FORWARDED_ARGS[@]}"
fi

echo "selected source: https://codeload.github.com/${REPO}/tar.gz/${REF}" >&2
echo "selected ref: $REF" >&2

command -v python3 >/dev/null 2>&1 || fail "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "python3 >= 3.11 is required (tomllib)"
command -v codex >/dev/null 2>&1 || fail "codex CLI is required"
command -v curl >/dev/null 2>&1 || fail "curl is required for a remote install"
command -v tar >/dev/null 2>&1 || fail "tar is required for a remote install"

workdir="$(mktemp -d "${TMPDIR:-/tmp}/pilotfish-install.XXXXXX")"
cleanup() {
  if [[ -n "${workdir:-}" && -d "$workdir" ]]; then
    rm -rf -- "$workdir"
  fi
}
trap cleanup EXIT

archive_url="https://codeload.github.com/${REPO}/tar.gz/${REF}"
if ! curl -fsSL "$archive_url" | tar -xz -C "$workdir"; then
  fail "could not download ${REPO}@${REF}"
fi

source_root="$(find "$workdir" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -n "$source_root" && -f "$source_root/install/install.py" \
  && -d "$source_root/templates/agents" ]] \
  || fail "downloaded archive does not look like pilotfish-codex"

python3 "$source_root/install/install.py" "${FORWARDED_ARGS[@]}"
