#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON=$(find_python) || {
  printf '%s\n' 'Python 3.11 or newer is required.' >&2
  printf '%s\n' 'Install Python 3.11+ with the normal package manager for this machine, then rerun.' >&2
  exit 2
}

command -v git >/dev/null 2>&1 || {
  printf '%s\n' 'Git is required.' >&2
  exit 2
}

"$PYTHON" "$SCRIPT_DIR/scripts/install.py" "$@"
printf '%s\n' ''
printf '%s\n' 'Host profile: run `manageroo capacity` to inspect this machine'''s CPU, RAM, GPU/VRAM, and free disk.'
printf '%s\n' 'Manageroo itself is hardware-agnostic: the profile is context only and never auto-tunes worker concurrency.'
