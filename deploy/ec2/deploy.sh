#!/usr/bin/env bash
# Run on the EC2 host after rsync + bootstrap.
# Regenerates the OpenAPI spec, refreshes the systemd unit, restarts mint dev.

set -euo pipefail

REMOTE_DIR=/opt/magic-cms-docs
UNIT_SRC="$REMOTE_DIR/deploy/ec2/mint-internal.service"
UNIT_DST=/etc/systemd/system/mint-internal.service
RENDERED=$(mktemp)
trap 'rm -f "$RENDERED"' EXIT

cd "$REMOTE_DIR"

python3.13 tools/build_openapi.py

MINT_BIN="$(command -v mint)"
if [ -z "$MINT_BIN" ]; then
  echo "mint CLI not found on PATH — bootstrap.sh should have installed it" >&2
  exit 1
fi

sed \
  -e "s|__DEPLOY_USER__|$USER|g" \
  -e "s|^ExecStart=.*|ExecStart=$MINT_BIN dev|" \
  "$UNIT_SRC" > "$RENDERED"

if ! sudo cmp -s "$RENDERED" "$UNIT_DST" 2>/dev/null; then
  sudo install -m 0644 "$RENDERED" "$UNIT_DST"
  sudo systemctl daemon-reload
fi

sudo systemctl enable mint-internal.service
sudo systemctl restart mint-internal.service

echo "deploy.sh: ok"
