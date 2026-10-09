# Voice bridge — TLS front door for `studio.zygomaticszero.com`

The browser will not hand out the microphone over plain HTTP. The studio GUI on
`127.0.0.1:8899` (`inspection.html`, served by `kanban_server.py`) therefore has to be
reached over HTTPS, and nginx terminates TLS in front of it.

Files in this repo (nothing is installed until the operator runs the deploy script):

| File | Deploys to |
|---|---|
| `config/nginx/studio.zygomaticszero.com.conf` | `/etc/nginx/sites-available/` + symlink in `sites-enabled/` |
| `config/nginx/upgrade_map.conf` | `/etc/nginx/sites-available/` + symlink in `conf.d/` (http context) |
| `config/nginx/_selftest.conf` | never deployed — throwaway wrapper for `nginx -t` without root |
| `tools/deploy_studio_tls.sh` | run by the operator with sudo |

The existing site `/etc/nginx/sites-enabled/zygomaticszero`
(`listen 80; server_name ZygomaticsZero.local _;` → `127.0.0.1:5001`) is **not modified**.
The new port-80 block uses the exact name `studio.zygomaticszero.com`, which nginx prefers
over the other site's catch-all name, so the two coexist.

---

## The three operator commands

### 1. Deploy and reload

```bash
cd "/home/zygomatic/Zygomatic Full/agents/crews"
sudo bash tools/deploy_studio_tls.sh
```

It backs up anything it would overwrite, installs the two files, runs `nginx -t`, and only
then `systemctl reload nginx`. It refuses to run as a non-root user, and it refuses to
reload if the certificate is missing. Read the `nginx -t` output before trusting the reload.

The certificate must already exist at:

```
/home/zygomatic/.config/zygomatic/letsencrypt/live/studio.zygomaticszero.com/fullchain.pem
/home/zygomatic/.config/zygomatic/letsencrypt/live/studio.zygomaticszero.com/privkey.pem
```

(the nginx master runs as root, so it can read them under `/home/zygomatic`).

### 2. Let certificate renewal reload nginx unattended

Create `/etc/sudoers.d/zyg-nginx`, mode `0440`, owner `root:root`, containing exactly:

```
zygomatic ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload, /usr/sbin/nginx -t
```

Never edit a sudoers file with a plain editor — validate first:

```bash
sudo sh -c "printf '%s\n' 'zygomatic ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload, /usr/sbin/nginx -t' > /etc/sudoers.d/zyg-nginx.new \
  && visudo -cf /etc/sudoers.d/zyg-nginx.new \
  && install -m 0440 -o root -g root /etc/sudoers.d/zyg-nginx.new /etc/sudoers.d/zyg-nginx \
  && rm -f /etc/sudoers.d/zyg-nginx.new"
```

### 3. Make the name resolve on the LAN

Until public DNS points at the box, add the host by hand — either in the router's local DNS,
or on each client machine in `/etc/hosts` (`C:\Windows\System32\drivers\etc\hosts` on Windows):

```
<lan-ip> studio.zygomaticszero.com
```

---

## Why the directives are what they are

- **`proxy_buffering off;`** — the voice bridge streams Server-Sent Events on
  `/inspect/api/voice/events`. With buffering on, nginx holds the response and the browser
  never sees an `event: action` until the stream ends, i.e. never. `proxy_cache off;` and
  `chunked_transfer_encoding on;` are there for the same stream.
- **`Upgrade` / `Connection $connection_upgrade`** — `$connection_upgrade` comes from the
  `map` in `upgrade_map.conf`. nginx only accepts `map` in the *http* context, which is why
  it is a separate file destined for `conf.d/` rather than part of the server block.
- **`proxy_read_timeout 3600s; proxy_send_timeout 3600s;`** — an idle SSE stream or a long
  render must not be cut at the 60 s default.
- **`client_max_body_size 0;`** — utterance audio blobs are POSTed whole; renders come back
  as large downloads.
- **`listen 443 ssl http2;` and not `http2 on;`** — the installed nginx is **1.24.0
  (Ubuntu)**. The standalone `http2 on;` directive only exists from nginx 1.25.1; on 1.24 it
  is rejected with `unknown directive "http2"`. Switch to the `http2 on;` form if nginx is
  ever upgraded past 1.25.1, where the `listen` flag is deprecated.

## Mixed content

Once the page is served over `https://`, the browser blocks every sub-resource and every
`fetch()` to a plain `http://` URL, and blocked requests are silent in the network tab
apart from a console warning. The page must use same-origin relative URLs only.

Measured on 2026-09-15 in `agents/crews`:

```
$ grep -c 'http://' inspection.html
0
```

Zero — `inspection.html` contains no absolute `http://` URL at all today (not to another
port, not to anything). Keep it that way: any new call to a sibling service must go through
a relative path on `:8899` that `kanban_server.py` forwards (the `_km_forward` pattern), not
through an absolute `http://127.0.0.1:PORT/...` URL from the browser.

## Checking the config without root

`tools/deploy_studio_tls.sh` needs root. To syntax-check the two fragments as the
`zygomatic` user:

```bash
cd "/home/zygomatic/Zygomatic Full/agents/crews"
mkdir -p /tmp/vb_nginx_selftest
nginx -t -c "$(pwd)/config/nginx/_selftest.conf"
```

Two things will still stop a non-root run after `syntax is ok` is printed:

1. **Missing certificate** — `cannot load certificate ... No such file or directory`.
   Before certbot has issued anything, stand in a throwaway self-signed pair:
   ```bash
   openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
       -subj "/CN=studio.zygomaticszero.com" \
       -keyout /tmp/vb_nginx_selftest/privkey.pem \
       -out    /tmp/vb_nginx_selftest/fullchain.pem
   mkdir -p /home/zygomatic/.config/zygomatic/letsencrypt/live
   ln -sfn /tmp/vb_nginx_selftest \
       /home/zygomatic/.config/zygomatic/letsencrypt/live/studio.zygomaticszero.com
   ```
   **Remove that symlink again before certbot runs** — certbot will not write into a
   `live/<name>` that it did not create:
   ```bash
   rm /home/zygomatic/.config/zygomatic/letsencrypt/live/studio.zygomaticszero.com
   ```
2. **`bind() to 0.0.0.0:80 failed (13: Permission denied)`** — ports below 1024 need root,
   and `nginx -t` really does open the listening sockets. This is expected for a non-root
   check and does not appear when the deploy script runs `nginx -t` as root. To get a clean
   exit 0 without root, test a port-rewritten copy:
   ```bash
   sed 's/listen 80;/listen 8080;/; s/listen \[::\]:80;/listen [::]:8080;/;
        s/listen 443 ssl http2;/listen 8443 ssl http2;/;
        s/listen \[::\]:443 ssl http2;/listen [::]:8443 ssl http2;/' \
       config/nginx/studio.zygomaticszero.com.conf > /tmp/vb_nginx_selftest/highport_site.conf
   sed 's#studio.zygomaticszero.com.conf#/tmp/vb_nginx_selftest/highport_site.conf#' \
       config/nginx/_selftest.conf > /tmp/vb_nginx_selftest/highport.conf
   nginx -t -c /tmp/vb_nginx_selftest/highport.conf
   ```
