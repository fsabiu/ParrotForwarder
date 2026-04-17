#!/usr/bin/env bash
#
# ParrotForwarder v2 bootstrap for Ubuntu 24.04 ARM64.
#
# Idempotent: safe to re-run. Every step logs one structured line so you
# can re-run after a failure and see where it picks up.
#
# What it does:
#   1. Check OS (warn only if not Ubuntu 24.04).
#   2. apt-get install the GStreamer / SDL / OpenCV / build toolchain.
#   3. Install pyenv if missing (pinned commit).
#   4. Install Python 3.11.11 via pyenv if missing.
#   5. Create project-local .venv against that interpreter.
#   6. pip install -e . plus requirements-dev.txt.
#   7. Force-reinstall protobuf 3.20.3 over Olympe's 3.7.1 transitive.
#   8. Verify GStreamer elements the pipeline needs (mpegtsmux, srtsink).
#   9. Copy config.yaml.example to /etc/parrot-forwarder/config.yaml if missing.
#  10. Print a concise "you're good" summary.
#
# Flags: none. Set env PF_SKIP_APT=1 to skip apt (useful in containers where
# apt is already done); set PF_SKIP_PYENV=1 to skip pyenv (when you already
# have python3.11 on PATH).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Pin pyenv to a specific commit for reproducibility. Update deliberately.
readonly PYENV_REPO="https://github.com/pyenv/pyenv.git"
readonly PYENV_PIN="v2.4.17"

readonly PYTHON_VERSION="3.11.11"

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly VENV_DIR="${REPO_ROOT}/.venv"
readonly SYSTEM_CONFIG="/etc/parrot-forwarder/config.yaml"
readonly EXAMPLE_CONFIG="${REPO_ROOT}/config.yaml.example"

# ---------------------------------------------------------------------------
# Logging helpers - single-line JSON-ish so re-runs are debuggable.
# ---------------------------------------------------------------------------

log_step() {
    printf '[install.sh] step=%-20s  %s\n' "$1" "$2"
}
log_warn() {
    printf '[install.sh] step=%-20s  WARN  %s\n' "$1" "$2" >&2
}
log_fail() {
    printf '[install.sh] step=%-20s  FAIL  %s\n' "$1" "$2" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# 1. OS check (warn-only)
# ---------------------------------------------------------------------------

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_warn "os-check" "no /etc/os-release - cannot verify distribution"
        return
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
        log_warn "os-check" "expected ubuntu 24.04, got ${ID:-unknown}/${VERSION_ID:-unknown}; continuing"
    else
        log_step "os-check" "ubuntu 24.04 confirmed"
    fi
}

# ---------------------------------------------------------------------------
# 2. apt packages
# ---------------------------------------------------------------------------

install_apt() {
    if [[ "${PF_SKIP_APT:-0}" == "1" ]]; then
        log_step "apt" "skipped (PF_SKIP_APT=1)"
        return
    fi
    if ! command -v apt-get >/dev/null 2>&1; then
        log_warn "apt" "apt-get not found; skipping system package install"
        return
    fi

    log_step "apt" "updating package index"
    sudo apt-get update -y

    log_step "apt" "installing gstreamer + sdl + jpeg + build toolchain"
    sudo apt-get install -y \
        build-essential \
        curl \
        git \
        libbz2-dev \
        libffi-dev \
        libjpeg-dev \
        liblzma-dev \
        libncurses-dev \
        libopencv-dev \
        libreadline-dev \
        libsdl2-2.0-0 \
        libsdl2-dev \
        libsqlite3-dev \
        libssl-dev \
        libxml2-dev \
        libxmlsec1-dev \
        tk-dev \
        xz-utils \
        zlib1g-dev \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav \
        gstreamer1.0-rtsp
}

# ---------------------------------------------------------------------------
# 3. pyenv
# ---------------------------------------------------------------------------

install_pyenv() {
    if [[ "${PF_SKIP_PYENV:-0}" == "1" ]]; then
        log_step "pyenv" "skipped (PF_SKIP_PYENV=1)"
        return
    fi

    local pyenv_root="${PYENV_ROOT:-$HOME/.pyenv}"
    export PYENV_ROOT="$pyenv_root"

    if [[ -d "$pyenv_root/.git" ]]; then
        log_step "pyenv" "present at $pyenv_root; pinning to $PYENV_PIN"
        git -C "$pyenv_root" fetch --tags --quiet origin || true
        git -C "$pyenv_root" checkout --quiet "$PYENV_PIN"
    else
        log_step "pyenv" "cloning $PYENV_REPO $PYENV_PIN to $pyenv_root"
        git clone --quiet --branch "$PYENV_PIN" --depth 1 "$PYENV_REPO" "$pyenv_root"
    fi
    export PATH="$pyenv_root/bin:$pyenv_root/shims:$PATH"
    eval "$(pyenv init --path)"
}

# ---------------------------------------------------------------------------
# 4. Python 3.11.11
# ---------------------------------------------------------------------------

install_python() {
    if [[ "${PF_SKIP_PYENV:-0}" == "1" ]]; then
        # Honor whatever python3.11 is on PATH.
        if ! command -v python3.11 >/dev/null 2>&1; then
            log_fail "python" "PF_SKIP_PYENV=1 but python3.11 not found on PATH"
        fi
        log_step "python" "using $(command -v python3.11)"
        return
    fi

    if pyenv versions --bare | grep -Fxq "$PYTHON_VERSION"; then
        log_step "python" "pyenv already has $PYTHON_VERSION"
    else
        log_step "python" "building $PYTHON_VERSION via pyenv (this takes 2-5 min)"
        pyenv install --skip-existing "$PYTHON_VERSION"
    fi
}

# ---------------------------------------------------------------------------
# 5. .venv
# ---------------------------------------------------------------------------

create_venv() {
    local python_bin
    if [[ "${PF_SKIP_PYENV:-0}" == "1" ]]; then
        python_bin="$(command -v python3.11)"
    else
        python_bin="${PYENV_ROOT}/versions/${PYTHON_VERSION}/bin/python"
    fi
    if [[ ! -x "$python_bin" ]]; then
        log_fail "venv" "python interpreter not found at $python_bin"
    fi

    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        local existing
        existing="$("${VENV_DIR}/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
        log_step "venv" ".venv exists with python $existing"
    else
        log_step "venv" "creating .venv with $python_bin"
        "$python_bin" -m venv "$VENV_DIR"
    fi

    # shellcheck disable=SC1091
    . "${VENV_DIR}/bin/activate"
    python -m pip install --upgrade --quiet pip setuptools wheel
}

# ---------------------------------------------------------------------------
# 6. pip install
# ---------------------------------------------------------------------------

pip_install() {
    log_step "pip" "installing package (editable) + dev deps"
    pip install --quiet -e "${REPO_ROOT}" -r "${REPO_ROOT}/requirements-dev.txt"
}

# ---------------------------------------------------------------------------
# 7. protobuf pin
# ---------------------------------------------------------------------------

pin_protobuf() {
    log_step "protobuf" "force-reinstalling protobuf==3.20.3 over Olympe's 3.7.1 transitive"
    pip install --quiet --force-reinstall "protobuf==3.20.3"
}

# ---------------------------------------------------------------------------
# 8. GStreamer verification
# ---------------------------------------------------------------------------

verify_gst() {
    if ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
        log_fail "gst-verify" "gst-inspect-1.0 not on PATH"
    fi
    for element in mpegtsmux srtsink; do
        if ! gst-inspect-1.0 --exists "$element"; then
            log_fail "gst-verify" "required GStreamer element '$element' missing"
        fi
    done
    log_step "gst-verify" "mpegtsmux and srtsink available"
}

# ---------------------------------------------------------------------------
# 9. system config
# ---------------------------------------------------------------------------

seed_config() {
    if [[ ! -f "$EXAMPLE_CONFIG" ]]; then
        log_warn "config" "example config missing at $EXAMPLE_CONFIG; skipping"
        return
    fi
    if [[ -f "$SYSTEM_CONFIG" ]]; then
        log_step "config" "$SYSTEM_CONFIG already exists; leaving it alone"
        return
    fi
    log_step "config" "seeding $SYSTEM_CONFIG from config.yaml.example"
    sudo install -d -m 0755 "$(dirname "$SYSTEM_CONFIG")"
    sudo install -m 0644 "$EXAMPLE_CONFIG" "$SYSTEM_CONFIG"
}

# ---------------------------------------------------------------------------
# 10. summary
# ---------------------------------------------------------------------------

summary() {
    cat <<EOF

ParrotForwarder v2 bootstrap complete.
  venv:    ${VENV_DIR}
  config:  ${SYSTEM_CONFIG}
  run:     source ${VENV_DIR}/bin/activate && parrot-forwarder --help

EOF
}

main() {
    check_os
    install_apt
    install_pyenv
    install_python
    create_venv
    pip_install
    pin_protobuf
    verify_gst
    seed_config
    summary
}

main "$@"
