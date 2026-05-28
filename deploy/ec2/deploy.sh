#!/usr/bin/env bash
# Run on the EC2 host after bootstrap.
# Regenerates the OpenAPI spec, refreshes the systemd unit, restarts mint dev,
# and refreshes the nginx + Basic Auth + Let's Encrypt fronting.
#
# Expects in env:
#   DEPLOY_USER, REMOTE_DIR
#   PREVIEW_DOMAIN          — DNS name pointed at this host (e.g. internal-docs-preview.magic-cms.com)
#   BASIC_AUTH_USER         — htpasswd username
#   BASIC_AUTH_PASSWORD     — htpasswd password (cleartext; hashed before writing to disk)
#   LETSENCRYPT_EMAIL       — contact for Let's Encrypt registration

set -euo pipefail

: "${DEPLOY_USER:?DEPLOY_USER must be set}"
: "${REMOTE_DIR:=/opt/magic-cms-docs}"
: "${PREVIEW_DOMAIN:?PREVIEW_DOMAIN must be set}"
: "${BASIC_AUTH_USER:?BASIC_AUTH_USER must be set}"
: "${BASIC_AUTH_PASSWORD:?BASIC_AUTH_PASSWORD must be set}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL must be set}"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

UNIT_SRC="$REMOTE_DIR/deploy/ec2/mint-internal.service"
UNIT_DST=/etc/systemd/system/mint-internal.service
NGINX_SRC="$REMOTE_DIR/deploy/ec2/nginx-mint-internal.conf"
NGINX_DST=/etc/nginx/conf.d/mint-internal.conf
HTPASSWD_DST=/etc/nginx/htpasswd-mint-internal
RENDERED_UNIT=$(mktemp)
RENDERED_NGINX=$(mktemp)
RENDERED_HTPASSWD=$(mktemp)
trap 'rm -f "$RENDERED_UNIT" "$RENDERED_NGINX" "$RENDERED_HTPASSWD"' EXIT

cd "$REMOTE_DIR"

# Regenerate the merged internal OpenAPI spec.
python3.13 tools/build_openapi.py

MINT_BIN="$(command -v mint || true)"
if [ -z "$MINT_BIN" ]; then
  echo "mint CLI not found on PATH — bootstrap.sh should have installed it" >&2
  exit 1
fi

# --- systemd unit for mint dev ---
sed \
  -e "s|__DEPLOY_USER__|$DEPLOY_USER|g" \
  -e "s|^ExecStart=.*|ExecStart=$MINT_BIN dev|" \
  "$UNIT_SRC" > "$RENDERED_UNIT"

if ! $SUDO cmp -s "$RENDERED_UNIT" "$UNIT_DST" 2>/dev/null; then
  $SUDO install -m 0644 "$RENDERED_UNIT" "$UNIT_DST"
  $SUDO systemctl daemon-reload
fi

$SUDO systemctl enable mint-internal.service
$SUDO systemctl restart mint-internal.service

# --- htpasswd for basic auth ---
htpasswd -nbB "$BASIC_AUTH_USER" "$BASIC_AUTH_PASSWORD" > "$RENDERED_HTPASSWD"
if ! $SUDO cmp -s "$RENDERED_HTPASSWD" "$HTPASSWD_DST" 2>/dev/null; then
  $SUDO install -m 0640 -o root -g www-data "$RENDERED_HTPASSWD" "$HTPASSWD_DST" 2>/dev/null \
    || $SUDO install -m 0640 "$RENDERED_HTPASSWD" "$HTPASSWD_DST"
fi

# --- Let's Encrypt cert (first run only; certbot's systemd timer handles renewal) ---
CERT_DIR="/etc/letsencrypt/live/$PREVIEW_DOMAIN"
if [ ! -s "$CERT_DIR/fullchain.pem" ]; then
  # nginx may not be holding port 80 yet (first deploy) — stop it just in case.
  $SUDO systemctl stop nginx 2>/dev/null || true
  $SUDO certbot certonly --standalone \
    -d "$PREVIEW_DOMAIN" \
    --non-interactive --agree-tos \
    -m "$LETSENCRYPT_EMAIL"
fi

# --- nginx site config ---
sed -e "s|__DOMAIN__|$PREVIEW_DOMAIN|g" "$NGINX_SRC" > "$RENDERED_NGINX"

# On Debian/Ubuntu the default site grabs port 80 — disable it so our server_name wins.
if [ -e /etc/nginx/sites-enabled/default ]; then
  $SUDO rm -f /etc/nginx/sites-enabled/default
fi

if ! $SUDO cmp -s "$RENDERED_NGINX" "$NGINX_DST" 2>/dev/null; then
  $SUDO install -m 0644 "$RENDERED_NGINX" "$NGINX_DST"
fi

$SUDO nginx -t
$SUDO systemctl reload nginx 2>/dev/null || $SUDO systemctl start nginx

echo "deploy.sh: ok"
