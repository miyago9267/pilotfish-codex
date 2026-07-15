#!/usr/bin/env bash
# Pilotfish scripted install bootstrap.
#
#   curl -fsSL https://raw.githubusercontent.com/miyago9267/pilotfish-codex/main/install/install.sh | bash
#
# Pin a version (recommended for teams) by pinning BOTH the script URL ref and
# the templates ref:
#
#   curl -fsSL https://raw.githubusercontent.com/miyago9267/pilotfish-codex/<tag-or-sha>/install/install.sh | PILOTFISH_REF=<tag-or-sha> bash
#
# Extra arguments are passed to install.py, e.g. `| bash -s -- --dry-run`.
# Inside a local clone, `bash install/install.sh` uses the checkout directly.

set -euo pipefail

REPO="miyago9267/pilotfish-codex"
REF="${PILOTFISH_REF:-main}"

fail() {
  echo "error: $*" >&2
  exit 2
}

command -v python3 >/dev/null 2>&1 || fail "python3 is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "python3 >= 3.11 is required (tomllib)"
command -v codex >/dev/null 2>&1 || fail "codex CLI is required"

script_source="${BASH_SOURCE[0]:-}"
if [ -n "$script_source" ] && [ -f "$script_source" ]; then
  local_root="$(cd "$(dirname "$script_source")/.." && pwd)"
  if [ -f "$local_root/install/install.py" ] \
    && [ -d "$local_root/templates/agents" ]; then
    exec python3 "$local_root/install/install.py" "$@"
  fi
fi

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

workdir="$(mktemp -d "${TMPDIR:-/tmp}/pilotfish-install.XXXXXX")"
trap 'rm -rf "$workdir"' EXIT

echo "fetching ${REPO}@${REF} ..." >&2
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/${REF}" \
  | tar -xz -C "$workdir" \
  || fail "could not download ${REPO}@${REF}"

source_root="$(find "$workdir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$source_root" ] && [ -f "$source_root/install/install.py" ] \
  || fail "downloaded archive does not look like pilotfish-codex"

python3 "$source_root/install/install.py" "$@"
