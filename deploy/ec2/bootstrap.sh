#!/usr/bin/env bash
# Idempotent host setup for the internal docs preview server.
# Safe to re-run; each step is a no-op if already satisfied.
#
# Runs as root when invoked via SSM (AWS-RunShellScript runs as root).
# Also runnable manually by a sudo-capable user.
#
# Expects DEPLOY_USER and REMOTE_DIR in env (set by the workflow / caller).

set -euo pipefail

: "${DEPLOY_USER:?DEPLOY_USER must be set}"
: "${REMOTE_DIR:=/opt/magic-cms-docs}"

# When run via SSM we're already root; otherwise prefix privileged ops with sudo.
# SUDO_E is the env-preserving variant. Defined separately so they collapse to
# nothing (not "-E") when we're already root.
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  SUDO_E=""
else
  SUDO="sudo"
  SUDO_E="sudo -E"
fi

if command -v apt-get >/dev/null 2>&1; then
  PKG=apt
elif command -v dnf >/dev/null 2>&1; then
  PKG=dnf
else
  echo "Unsupported distro: need apt-get or dnf" >&2
  exit 1
fi

install_pkgs() {
  case "$PKG" in
    apt)
      $SUDO apt-get update -y
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    dnf)
      $SUDO dnf install -y "$@"
      ;;
  esac
}

install_pkgs git rsync curl ca-certificates

# Python 3.13 for tools/build_openapi.py
if ! command -v python3.13 >/dev/null 2>&1; then
  case "$PKG" in
    apt)
      if ! grep -rq "deadsnakes" /etc/apt/sources.list.d/ 2>/dev/null; then
        install_pkgs software-properties-common
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        $SUDO apt-get update -y
      fi
      install_pkgs python3.13
      ;;
    dnf)
      install_pkgs python3.13
      ;;
  esac
fi

# Node 20 LTS via NodeSource
if ! command -v node >/dev/null 2>&1 || ! node -v | grep -q '^v20\.'; then
  case "$PKG" in
    apt)
      curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO_E bash -
      install_pkgs nodejs
      ;;
    dnf)
      curl -fsSL https://rpm.nodesource.com/setup_20.x | $SUDO_E bash -
      install_pkgs nodejs
      ;;
  esac
fi

# Mintlify CLI
if ! command -v mint >/dev/null 2>&1; then
  $SUDO npm install -g mint
fi

# Deploy dir ownership
$SUDO mkdir -p "$REMOTE_DIR"
$SUDO chown -R "$DEPLOY_USER:$DEPLOY_USER" "$REMOTE_DIR"

echo "bootstrap.sh: ok (deploy_user=$DEPLOY_USER, remote_dir=$REMOTE_DIR)"
