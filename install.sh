#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MACOS_PYTHON_URL='https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg'
MACOS_PYTHON_SHA256='8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4'

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

run_as_admin() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    printf '%s\n' 'Installing system requirements needs administrator access, but sudo is unavailable.' >&2
    return 1
  fi
}

git_works() {
  command -v git >/dev/null 2>&1 && git --version >/dev/null 2>&1
}

install_macos_python() {
  command -v curl >/dev/null 2>&1 || {
    printf '%s\n' 'macOS dependency setup needs curl, which is not available.' >&2
    return 1
  }
  command -v shasum >/dev/null 2>&1 || {
    printf '%s\n' 'macOS dependency setup needs shasum, which is not available.' >&2
    return 1
  }
  TEMP_DIR=$(mktemp -d) || return 1
  PACKAGE_PATH="$TEMP_DIR/python.pkg"
  printf '%s\n' 'Downloading the release-pinned Python 3.12 installer from python.org...'
  if ! curl -fL --retry 2 -o "$PACKAGE_PATH" "$MACOS_PYTHON_URL"; then
    rmdir "$TEMP_DIR" 2>/dev/null || true
    return 1
  fi
  ACTUAL_SHA256=$(shasum -a 256 "$PACKAGE_PATH" | awk '{print $1}')
  if [ "$ACTUAL_SHA256" != "$MACOS_PYTHON_SHA256" ]; then
    printf '%s\n' 'The downloaded Python installer failed checksum verification. Nothing was installed.' >&2
    rm -f "$PACKAGE_PATH"
    rmdir "$TEMP_DIR" 2>/dev/null || true
    return 1
  fi
  run_as_admin installer -pkg "$PACKAGE_PATH" -target /
  rm -f "$PACKAGE_PATH"
  rmdir "$TEMP_DIR" 2>/dev/null || true
}

install_core_requirements() {
  printf '%s\n' 'Manageroo needs Python 3.11+ and Git. One or both are missing.'
  if [ -t 0 ]; then
    printf '%s' 'Install the missing requirements now? [Y/n]: '
    read -r ANSWER
    case "$ANSWER" in n|N|no|NO|No) return 1 ;; esac
  else
    printf '%s\n' 'Rerun in an interactive terminal so Manageroo can offer guided dependency setup.' >&2
    return 1
  fi

  if [ "$(uname -s)" = "Darwin" ]; then
    if ! find_python >/dev/null 2>&1; then
      install_macos_python || return 1
    fi
    if ! git_works; then
      if command -v brew >/dev/null 2>&1; then
        brew install git
      elif command -v xcode-select >/dev/null 2>&1; then
        printf '%s\n' 'macOS will open its Command Line Tools installer for Git.'
        xcode-select --install || true
        printf '%s\n' 'Finish the Apple installer, then rerun Manageroo.'
        return 1
      else
        printf '%s\n' 'Git could not be installed automatically on this Mac.' >&2
        return 1
      fi
    fi
  elif command -v brew >/dev/null 2>&1; then
    brew install python@3.12 git
  elif command -v apt-get >/dev/null 2>&1; then
    run_as_admin apt-get update
    run_as_admin apt-get install -y python3 git
  elif command -v dnf >/dev/null 2>&1; then
    run_as_admin dnf install -y python3 git
  elif command -v yum >/dev/null 2>&1; then
    run_as_admin yum install -y python3 git
  elif command -v pacman >/dev/null 2>&1; then
    run_as_admin pacman -Sy --needed --noconfirm python git
  elif command -v zypper >/dev/null 2>&1; then
    run_as_admin zypper --non-interactive install python311 git
  else
    printf '%s\n' 'No supported package manager was found. Install Python 3.11+ and Git, then rerun.' >&2
    return 1
  fi
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ] || ! git_works; then
  install_core_requirements || exit 2
  PYTHON=$(find_python || true)
fi

[ -n "$PYTHON" ] || {
  printf '%s\n' 'The package manager completed, but Python 3.11+ is still unavailable.' >&2
  exit 2
}

git_works || {
  printf '%s\n' 'The package manager completed, but Git is still unavailable.' >&2
  exit 2
}

PREFIX_VALUE="$HOME/.local/share/manageroo"
EXPECT_PREFIX=0
for ARG in "$@"; do
  if [ "$EXPECT_PREFIX" -eq 1 ]; then
    PREFIX_VALUE=$ARG
    EXPECT_PREFIX=0
    continue
  fi
  case "$ARG" in
    --prefix) EXPECT_PREFIX=1 ;;
    --prefix=*) PREFIX_VALUE=${ARG#--prefix=} ;;
  esac
done

"$PYTHON" "$SCRIPT_DIR/scripts/install.py" "$@"
"$PYTHON" "$SCRIPT_DIR/scripts/finalize_gitnexus.py" --prefix "$PREFIX_VALUE"

printf '%s\n' ''
printf '%s\n' "Host profile: run \`manageroo capacity\` to inspect this machine's CPU, RAM, GPU/VRAM, and free disk."
printf '%s\n' 'Manageroo itself is hardware-agnostic: the profile is context only and never auto-tunes worker concurrency.'
