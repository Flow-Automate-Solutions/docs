#!/usr/bin/env bash
# Idempotent host setup for the internal docs preview server.
# Safe to re-run; each step is a no-op if already satisfied.

set -euo pipefail

REMOTE_DIR=/opt/magic-cms-docs

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
      sudo apt-get update -y
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    dnf)
      sudo dnf install -y "$@"
      ;;
  esac
}

# Base tooling
install_pkgs git rsync curl ca-certificates

# Python 3.13 — required by tools/build_openapi.py
if ! command -v python3.13 >/dev/null 2>&1; then
  case "$PKG" in
    apt)
      if ! grep -rq "deadsnakes" /etc/apt/sources.list.d/ 2>/dev/null; then
        install_pkgs software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get update -y
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
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
      install_pkgs nodejs
      ;;
    dnf)
      curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo -E bash -
      install_pkgs nodejs
      ;;
  esac
fi

# Mintlify CLI
if ! command -v mint >/dev/null 2>&1; then
  sudo npm install -g mint
fi

# Deploy dir ownership — rsync target must be writable by the SSH user
if [ ! -d "$REMOTE_DIR" ]; then
  sudo mkdir -p "$REMOTE_DIR"
fi
sudo chown -R "$USER:$USER" "$REMOTE_DIR"

echo "bootstrap.sh: ok"
