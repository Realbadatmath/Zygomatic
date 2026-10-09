#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Deploy the TLS front door for studio.$ZYG_PUBLIC_DOMAIN -> 127.0.0.1:8899.
#
#   sudo ZYG_PUBLIC_DOMAIN=example.com bash tools/deploy_studio_tls.sh
#
# $ZYG_LETSENCRYPT_DIR overrides where the issued certificates are looked for.
#
# Installs config/nginx/studio.$ZYG_PUBLIC_DOMAIN.conf and config/nginx/upgrade_map.conf,
# tests the whole nginx configuration, and reloads nginx. It never touches the existing
# apex site of $ZYG_PUBLIC_DOMAIN in /etc/nginx/sites-enabled (port 80 -> :5001).
set -euo pipefail

STUDIO_HOST="studio.${ZYG_PUBLIC_DOMAIN:?set ZYG_PUBLIC_DOMAIN to the public apex domain}"
SITE="$STUDIO_HOST.conf"
MAP="upgrade_map.conf"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/nginx"
AVAIL="/etc/nginx/sites-available"
ENABLED="/etc/nginx/sites-enabled"
CONFD="/etc/nginx/conf.d"
# The certificates live in the operator's own tree, not in /etc/letsencrypt. This script runs
# under sudo, so the invoking user's home is the one that counts, never root's.
OWNER_HOME="${ZYG_HOME:-$(getent passwd "${SUDO_USER:-$(id -un)}" | cut -d: -f6)}"
CERT_DIR="${ZYG_LETSENCRYPT_DIR:-$OWNER_HOME/.config/zygomatic/letsencrypt}/live/$STUDIO_HOST"

if [ "$(id -u)" -ne 0 ]; then
    echo "deploy_studio_tls.sh: must run as root (sudo bash tools/deploy_studio_tls.sh)" >&2
    exit 1
fi

for f in "$SITE" "$MAP"; do
    if [ ! -s "$SRC_DIR/$f" ]; then
        echo "deploy_studio_tls.sh: missing source $SRC_DIR/$f" >&2
        exit 1
    fi
done

for d in "$AVAIL" "$ENABLED" "$CONFD"; do
    if [ ! -d "$d" ]; then
        echo "deploy_studio_tls.sh: $d does not exist — is this nginx layout Debian/Ubuntu?" >&2
        exit 1
    fi
done

stamp="$(date +%Y%m%d_%H%M%S)"
for f in "$SITE" "$MAP"; do
    if [ -f "$AVAIL/$f" ]; then
        cp -a "$AVAIL/$f" "$AVAIL/$f.bak-$stamp"
        echo "backed up $AVAIL/$f -> $AVAIL/$f.bak-$stamp"
    fi
done

install -m 0644 -o root -g root "$SRC_DIR/$SITE" "$AVAIL/$SITE"
install -m 0644 -o root -g root "$SRC_DIR/$MAP"  "$AVAIL/$MAP"
ln -sfn "$AVAIL/$SITE" "$ENABLED/$SITE"
ln -sfn "$AVAIL/$MAP"  "$CONFD/$MAP"
echo "installed $ENABLED/$SITE and $CONFD/$MAP"

if [ ! -s "$CERT_DIR/fullchain.pem" ] || [ ! -s "$CERT_DIR/privkey.pem" ]; then
    echo >&2
    echo "deploy_studio_tls.sh: certificate not found under $CERT_DIR" >&2
    echo "  nginx -t will refuse the config until fullchain.pem and privkey.pem exist there." >&2
    echo "  Issue them first (certbot), then re-run this script." >&2
    exit 1
fi

echo "running nginx -t ..."
nginx -t

echo "reloading nginx ..."
systemctl reload nginx
echo "nginx reloaded. https://$STUDIO_HOST now fronts 127.0.0.1:8899"

cat <<'SUDOERS'

--------------------------------------------------------------------------------
One more step, by hand, so certificate renewals can reload nginx unattended.
Create /etc/sudoers.d/zyg-nginx, mode 0440, owned by root:root, containing:

zygomatic ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload, /usr/sbin/nginx -t

Write it safely (never edit sudoers with a plain editor):

  printf '%s\n' 'zygomatic ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload, /usr/sbin/nginx -t' \
      > /etc/sudoers.d/zyg-nginx.new
  visudo -cf /etc/sudoers.d/zyg-nginx.new \
      && install -m 0440 -o root -g root /etc/sudoers.d/zyg-nginx.new /etc/sudoers.d/zyg-nginx \
      && rm -f /etc/sudoers.d/zyg-nginx.new
--------------------------------------------------------------------------------
SUDOERS
