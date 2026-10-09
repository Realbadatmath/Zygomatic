# Voice bridge — the certificate for studio.zygomaticszero.com

Done 2026-09-15 by the creator session (the tree's task 1 could not read the token file).

| Item | Where |
|---|---|
| Cloudflare API token (Zone:Read, DNS:Edit, zone zygomaticszero.com only) | `~/.config/zygomatic/cloudflare_dns.ini`, mode 600 |
| DNS record | `studio.zygomaticszero.com` A `<lan-ip>`, **DNS-only (grey cloud)** — never proxy it, or LAN traffic goes via Cloudflare |
| certbot 5.8.0 + certbot-dns-cloudflare | `~/.local/certbot-venv/bin/certbot` (user venv, no root) |
| Certificate + key | `~/.config/zygomatic/letsencrypt/live/studio.zygomaticszero.com/{fullchain,privkey}.pem` (ECDSA, Let's Encrypt, 90 days) |
| Renewal | user timer `zyg-certbot-renew.timer` (daily, randomized 1 h, persistent) → `zyg-certbot-renew.service` → `certbot renew` with deploy hook `sudo -n /usr/sbin/nginx -s reload` |

## Issue / renew by hand
```
D=~/.config/zygomatic/letsencrypt
~/.local/certbot-venv/bin/certbot renew --config-dir $D --work-dir $D/work --logs-dir $D/logs
~/.local/certbot-venv/bin/certbot certonly --dns-cloudflare --dns-cloudflare-credentials ~/.config/zygomatic/cloudflare_dns.ini \
  --dns-cloudflare-propagation-seconds 30 -d studio.zygomaticszero.com --config-dir $D --work-dir $D/work --logs-dir $D/logs \
  --non-interactive --agree-tos --register-unsafely-without-email --key-type ecdsa
```
No e-mail is registered with Let's Encrypt on purpose; expiry warnings therefore never arrive — the timer is the safety net,
and `systemctl --user list-timers | grep zyg-certbot` shows it is armed.

## The deploy hook needs one sudoers line
`/etc/sudoers.d/zyg-nginx` (see `docs/voice_bridge_nginx.md` section 2). Until it exists a renewal still succeeds but nginx
keeps serving the old certificate until it is reloaded by hand (`sudo nginx -s reload`).

## Revoke
```
~/.local/certbot-venv/bin/certbot revoke --cert-path $D/live/studio.zygomaticszero.com/cert.pem --config-dir $D --work-dir $D/work --logs-dir $D/logs
```
## LAN fallback when the internet is down
The name lives in public DNS. Add `<lan-ip> studio.zygomaticszero.com` to the router's local DNS or the viewing PC's hosts
file so it resolves offline.
