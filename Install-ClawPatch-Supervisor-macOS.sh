#!/bin/bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 /absolute/path/to/git-repository" >&2
    exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer must be run natively on macOS." >&2
    exit 2
fi

# Exact versions from the verified supervisor source.
MANAGEROO_COMMIT="9c5c0a3eda772cac7be0a846508796cd69dee49f"
MANAGEROO_SOURCE="git+https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git@${MANAGEROO_COMMIT}"
CODEX_PACKAGE="@openai/codex@0.144.4"
CLAWPATCH_PACKAGE="clawpatch@0.7.2"

INSTALL_ROOT="${HOME}/Library/Application Support/ManagerooClawPatchSupervisor"
VENV="${INSTALL_ROOT}/venv"
NPM_ROOT="${INSTALL_ROOT}/npm"
NPM_BIN_DIR="${NPM_ROOT}/node_modules/.bin"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/clawpatch-supervise"

mkdir -p "${INSTALL_ROOT}" "${NPM_ROOT}" "${BIN_DIR}"

BREW_BIN="$(command -v brew || true)"
if [[ -z "${BREW_BIN}" ]]; then
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [[ -x "${candidate}" ]]; then
            BREW_BIN="${candidate}"
            export PATH="$(dirname "${candidate}"):${PATH}"
            break
        fi
    done
fi

install_with_brew() {
    local formula="$1"
    local display_name="$2"
    if [[ -z "${BREW_BIN}" ]]; then
        echo "${display_name} is missing and Homebrew is unavailable." >&2
        echo "Install ${display_name}, or install Homebrew from https://brew.sh and rerun this installer." >&2
        exit 1
    fi
    echo "Installing or updating ${display_name} with Homebrew..."
    "${BREW_BIN}" install "${formula}"
}

GIT_BIN="$(command -v git || true)"
if [[ -z "${GIT_BIN}" ]] || ! "${GIT_BIN}" --version >/dev/null 2>&1; then
    install_with_brew "git" "Git"
    GIT_BIN="$(command -v git || true)"
fi
if [[ -z "${GIT_BIN}" ]] || ! "${GIT_BIN}" --version >/dev/null 2>&1; then
    echo "Git is unavailable after installation." >&2
    exit 1
fi

NODE_BIN="$(command -v node || true)"
NODE_MAJOR=0
if [[ -n "${NODE_BIN}" ]]; then
    NODE_MAJOR_TEXT="$("${NODE_BIN}" -p "process.versions.node.split('.')[0]" 2>/dev/null || true)"
    if [[ "${NODE_MAJOR_TEXT}" =~ ^[0-9]+$ ]]; then
        NODE_MAJOR="${NODE_MAJOR_TEXT}"
    fi
fi
if (( NODE_MAJOR < 22 )); then
    install_with_brew "node@22" "Node.js 22"
    NODE_PREFIX="$("${BREW_BIN}" --prefix node@22)"
    export PATH="${NODE_PREFIX}/bin:${PATH}"
    NODE_BIN="$(command -v node || true)"
    NODE_MAJOR_TEXT="$("${NODE_BIN}" -p "process.versions.node.split('.')[0]" 2>/dev/null || true)"
    if [[ "${NODE_MAJOR_TEXT}" =~ ^[0-9]+$ ]]; then
        NODE_MAJOR="${NODE_MAJOR_TEXT}"
    else
        NODE_MAJOR=0
    fi
fi
if [[ -z "${NODE_BIN}" ]] || (( NODE_MAJOR < 22 )); then
    echo "ClawPatch requires Node.js 22 or newer." >&2
    exit 1
fi

NPM_BIN="$(command -v npm || true)"
if [[ -z "${NPM_BIN}" ]]; then
    echo "Node.js is available, but npm could not be found." >&2
    exit 1
fi

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    candidate_path="$(command -v "${candidate}" || true)"
    if [[ -n "${candidate_path}" ]] && "${candidate_path}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="${candidate_path}"
        break
    fi
done
if [[ -z "${PYTHON_BIN}" ]]; then
    install_with_brew "python@3.12" "Python 3.12"
    PYTHON_PREFIX="$("${BREW_BIN}" --prefix python@3.12)"
    for candidate_path in "${PYTHON_PREFIX}/bin/python3.12" "${PYTHON_PREFIX}/bin/python3"; do
        if [[ -x "${candidate_path}" ]] && "${candidate_path}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            PYTHON_BIN="${candidate_path}"
            break
        fi
    done
fi
if [[ -z "${PYTHON_BIN}" ]]; then
    echo "Python 3.11 or newer is unavailable after installation." >&2
    exit 1
fi

echo "Installing the exact Codex and ClawPatch versions used by the verified supervisor..."
"${NPM_BIN}" install --prefix "${NPM_ROOT}" --no-fund --no-audit "${CODEX_PACKAGE}" "${CLAWPATCH_PACKAGE}"

CODEX_BIN="${NPM_BIN_DIR}/codex"
CLAWPATCH_BIN="${NPM_BIN_DIR}/clawpatch"
if [[ ! -x "${CODEX_BIN}" ]]; then
    echo "Codex installed without creating ${CODEX_BIN}." >&2
    exit 1
fi
if [[ ! -x "${CLAWPATCH_BIN}" ]]; then
    echo "ClawPatch installed without creating ${CLAWPATCH_BIN}." >&2
    exit 1
fi

CODEX_VERSION="$("${CODEX_BIN}" --version | tail -n 1)"
if [[ "${CODEX_VERSION}" != *"0.144.4"* ]]; then
    echo "Expected Codex CLI 0.144.4, found: ${CODEX_VERSION}" >&2
    exit 1
fi
CLAWPATCH_VERSION="$("${CLAWPATCH_BIN}" --version | tail -n 1)"
if [[ "${CLAWPATCH_VERSION}" != *"0.7.2"* ]]; then
    echo "Expected ClawPatch 0.7.2, found: ${CLAWPATCH_VERSION}" >&2
    exit 1
fi

if [[ ! -d "${VENV}" ]]; then
    echo "Creating the dedicated supervisor environment..."
    "${PYTHON_BIN}" -m venv "${VENV}"
fi

VENV_PYTHON="${VENV}/bin/python"
SUPERVISOR_BIN="${VENV}/bin/clawpatch-supervise"
echo "Installing the repaired Manageroo supervisor at ${MANAGEROO_COMMIT}..."
"${VENV_PYTHON}" -m pip install --disable-pip-version-check --no-cache-dir --upgrade --force-reinstall "${MANAGEROO_SOURCE}" 'pytest>=8,<10'
if [[ ! -x "${SUPERVISOR_BIN}" ]]; then
    echo "Manageroo installed without creating ${SUPERVISOR_BIN}." >&2
    exit 1
fi

printf '%s\n' \
    '#!/bin/bash' \
    'set -euo pipefail' \
    'INSTALL_ROOT="${HOME}/Library/Application Support/ManagerooClawPatchSupervisor"' \
    'SUPERVISOR_VENV="${INSTALL_ROOT}/venv"' \
    'NPM_BIN_DIR="${INSTALL_ROOT}/npm/node_modules/.bin"' \
    'export PATH="${SUPERVISOR_VENV}/bin:${NPM_BIN_DIR}:${PATH}"' \
    'exec "${SUPERVISOR_VENV}/bin/clawpatch-supervise" "$@"' \
    > "${LAUNCHER}"
chmod 0755 "${LAUNCHER}"

"${SUPERVISOR_BIN}" --help >/dev/null

echo "Checking Codex login..."
if ! "${CODEX_BIN}" login status; then
    echo "Complete the one-time Codex browser login on this Mac."
    "${CODEX_BIN}" login
fi

REPO_INPUT="$1"
if [[ ! -d "${REPO_INPUT}" ]]; then
    echo "The supplied repository directory does not exist: ${REPO_INPUT}" >&2
    exit 1
fi
RESOLVED_REPO="$(cd "${REPO_INPUT}" && pwd -P)"
"${GIT_BIN}" -C "${RESOLVED_REPO}" rev-parse --show-toplevel >/dev/null

GIT_USER_NAME="$("${GIT_BIN}" -C "${RESOLVED_REPO}" config user.name || true)"
GIT_USER_EMAIL="$("${GIT_BIN}" -C "${RESOLVED_REPO}" config user.email || true)"
if [[ -z "${GIT_USER_NAME}" ]] || [[ -z "${GIT_USER_EMAIL}" ]]; then
    echo "Git commit identity is missing. Set git config user.name and user.email, then rerun this installer." >&2
    exit 1
fi
if ! "${GIT_BIN}" -C "${RESOLVED_REPO}" remote get-url origin >/dev/null 2>&1; then
    echo "The repository has no origin remote, so the supervisor cannot push successful fixes." >&2
    exit 1
fi

export PATH="${NPM_BIN_DIR}:${PATH}"
if [[ ! -d "${RESOLVED_REPO}/.clawpatch" ]]; then
    echo "Initializing ClawPatch in the target repository..."
    (cd "${RESOLVED_REPO}" && "${CLAWPATCH_BIN}" init)
fi
(cd "${RESOLVED_REPO}" && "${CLAWPATCH_BIN}" doctor)

INSTALLED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
"${VENV_PYTHON}" -c 'import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({"installedAt": sys.argv[2], "managerooCommit": sys.argv[3], "codexVersion": sys.argv[4], "clawpatchVersion": sys.argv[5], "launcher": sys.argv[6], "repository": sys.argv[7]}, indent=2) + "\n", encoding="utf-8")' \
    "${INSTALL_ROOT}/installed.json" \
    "${INSTALLED_AT}" \
    "${MANAGEROO_COMMIT}" \
    "${CODEX_VERSION}" \
    "${CLAWPATCH_VERSION}" \
    "${LAUNCHER}" \
    "${RESOLVED_REPO}"

printf -v QUOTED_REPO '%q' "${RESOLVED_REPO}"
printf -v QUOTED_LAUNCHER '%q' "${LAUNCHER}"

echo
echo "INSTALLATION VERIFIED. The supervisor was installed but was not started."
echo "Run it with this exact Terminal command:"
echo
echo "cd ${QUOTED_REPO} && ${QUOTED_LAUNCHER} --repo . --branch current --push each --fresh"
echo
echo "If an older supervisor stopped with checkpoint-owned source changes, use --resume-stopped instead of --fresh."
