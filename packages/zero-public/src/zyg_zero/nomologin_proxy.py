# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_proxy.py — the per-persona proxy shim. 2026-09-22.

Chrome cannot be given an authenticated upstream proxy: `--proxy-server` takes a host and
port and nothing else, and a proxy that answers 407 makes Chrome pop a credentials dialog
that no automation can dismiss. So every persona that has a proxy gets its own loopback
shim: Chrome talks plain unauthenticated HTTP-proxy to 127.0.0.1:<port>, and the shim adds
the credentials on the way out to the real upstream.

One shim per persona, never shared. Two personas behind one shim would share a socket pool
and a keep-alive connection to the upstream, which is exactly the correlation the profiles
exist to prevent.

Upstreams supported: http://, https:// (CONNECT-style HTTP proxies) and socks5://, each
with optional user:pass. socks5h is accepted as a synonym — this shim always resolves the
target name at the upstream, never locally, because a DNS lookup from this machine for a
host the persona is about to visit is its own leak ([[project_nomologin]]).

FAIL CLOSED is the whole point. If the shim is not listening, Chrome cannot reach the
network at all — it does not silently fall back to the direct connection. nomologin.py
therefore starts the shim and *probes the egress IP* before it launches Chrome, and refuses
to launch if the probe fails or returns this machine's own address. A persona that quietly
posts from the host IP is worse than a persona that does not open.

Run standalone for a smoke test:

    python3 nomologin_proxy.py --listen 41001 --upstream socks5://user:pass@host:1080
    python3 nomologin_proxy.py --probe socks5://user:pass@host:1080
"""

from __future__ import annotations

import base64
import select
import socket
import socketserver
import ssl
import struct
import sys
import threading
import time
import urllib.parse
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# Hop-by-hop headers, RFC 7230 6.1. These describe the client→shim connection and must not
# be relayed to the upstream; Proxy-Authorization in particular would be the *client's*
# (Chrome sends none) and would collide with the one we add.
_HOP_BY_HOP = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
    'proxy-connection',
}

CONNECT_TIMEOUT = 20.0
IDLE_TIMEOUT = 300.0
PROBE_TIMEOUT = 15.0

# Egress probes. Two independent services so one being down is not read as "the proxy is
# broken"; both return a bare IP as text/plain.
PROBE_URLS = ('https://api.ipify.org', 'https://ifconfig.me/ip')


class Upstream:
    """A parsed proxy URL. `socks5h` is folded into `socks5` — see the module docstring."""

    def __init__(self, url: str):
        self.url = url
        p = urllib.parse.urlparse(url)
        scheme = (p.scheme or '').lower()
        if scheme == 'socks5h':
            scheme = 'socks5'
        if scheme not in ('http', 'https', 'socks5'):
            raise ValueError(f'unsupported proxy scheme {p.scheme!r} (want http, https, socks5 or socks5h)')
        if not p.hostname:
            raise ValueError(f'proxy url has no host: {url!r}')
        self.scheme = scheme
        self.host = p.hostname
        self.port = p.port or (1080 if scheme == 'socks5' else 8080)
        self.user = urllib.parse.unquote(p.username) if p.username else None
        self.password = urllib.parse.unquote(p.password) if p.password else None

    @property
    def safe(self) -> str:
        """The URL with the password masked, for logs and for the board."""
        auth = f'{self.user}:***@' if self.user else ''
        return f'{self.scheme}://{auth}{self.host}:{self.port}'

    def _basic(self) -> str:
        raw = f'{self.user or ""}:{self.password or ""}'.encode()
        return 'Basic ' + base64.b64encode(raw).decode('ascii')

    # ── dialling ──────────────────────────────────────────────────────────────────────
    def connect(self, host: str, port: int, timeout: float = CONNECT_TIMEOUT) -> socket.socket:
        """Return a socket tunnelled to host:port through this upstream."""
        if self.scheme == 'socks5':
            return self._connect_socks5(host, port, timeout)
        return self._connect_http(host, port, timeout)

    def _raw(self, timeout: float) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.scheme == 'https':
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=self.host)
        return sock

    def _connect_http(self, host: str, port: int, timeout: float) -> socket.socket:
        sock = self._raw(timeout)
        try:
            head = [f'CONNECT {host}:{port} HTTP/1.1', f'Host: {host}:{port}']
            if self.user is not None:
                head.append(f'Proxy-Authorization: {self._basic()}')
            head += ['Connection: keep-alive', '', '']
            sock.sendall('\r\n'.join(head).encode('latin-1'))
            status, _hdrs = _read_head(sock)
            code = _status_code(status)
            if code != 200:
                raise OSError(f'upstream refused CONNECT {host}:{port} — {status.strip()!r}')
            return sock
        except Exception:
            _shut(sock)
            raise

    def _connect_socks5(self, host: str, port: int, timeout: float) -> socket.socket:
        sock = self._raw(timeout)
        try:
            # greeting: offer no-auth and, when we hold credentials, username/password
            methods = b'\x00' if self.user is None else b'\x00\x02'
            sock.sendall(b'\x05' + bytes([len(methods)]) + methods)
            ver, method = _recv_exact(sock, 2)
            if ver != 5:
                raise OSError(f'upstream is not SOCKS5 (version byte {ver})')
            if method == 0xFF:
                raise OSError('upstream rejected every offered auth method')
            if method == 2:
                if self.user is None:
                    raise OSError('upstream demands username/password, none configured')
                u = (self.user or '').encode()
                pw = (self.password or '').encode()
                if len(u) > 255 or len(pw) > 255:
                    raise OSError('SOCKS5 username/password limited to 255 bytes each')
                sock.sendall(b'\x01' + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
                _sub, status = _recv_exact(sock, 2)
                if status != 0:
                    raise OSError('upstream rejected the proxy credentials')
            elif method != 0:
                raise OSError(f'upstream chose unsupported auth method {method}')

            # CONNECT, always by DOMAINNAME so the upstream does the DNS
            target = host.encode('idna') if _is_hostname(host) else host.encode('ascii')
            if len(target) > 255:
                raise OSError('hostname too long for SOCKS5')
            sock.sendall(b'\x05\x01\x00\x03' + bytes([len(target)]) + target + struct.pack('!H', port))
            rep = _recv_exact(sock, 4)
            if rep[1] != 0:
                raise OSError(f'upstream refused CONNECT {host}:{port} — {_SOCKS_ERR.get(rep[1], f"code {rep[1]}")}')
            # drain the bound address so the stream starts clean
            atyp = rep[3]
            if atyp == 1:
                _recv_exact(sock, 4)
            elif atyp == 4:
                _recv_exact(sock, 16)
            elif atyp == 3:
                _recv_exact(sock, _recv_exact(sock, 1)[0])
            else:
                raise OSError(f'upstream replied with unknown address type {atyp}')
            _recv_exact(sock, 2)
            return sock
        except Exception:
            _shut(sock)
            raise


_SOCKS_ERR = {
    1: 'general SOCKS server failure',
    2: 'connection not allowed by ruleset',
    3: 'network unreachable',
    4: 'host unreachable',
    5: 'connection refused',
    6: 'TTL expired',
    7: 'command not supported',
    8: 'address type not supported',
}


# ── small socket helpers ──────────────────────────────────────────────────────────────
def _is_hostname(host: str) -> bool:
    try:
        socket.inet_aton(host)
        return False
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return False
    except OSError:
        return True


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError('upstream closed the connection mid-handshake')
        buf += chunk
    return buf


def _read_head(sock: socket.socket) -> tuple[str, list[str]]:
    """Read one HTTP message head. Returns (start-line, header lines)."""
    buf = b''
    while b'\r\n\r\n' not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            raise OSError('connection closed before the headers were complete')
        buf += chunk
        if len(buf) > 65536:
            raise OSError('header block over 64 KiB — refusing')
    head = buf.split(b'\r\n\r\n', 1)[0].decode('latin-1')
    lines = head.split('\r\n')
    return lines[0], lines[1:]


def _status_code(start_line: str) -> int:
    try:
        return int(start_line.split(' ', 2)[1])
    except (IndexError, ValueError):
        return 0


def _shut(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        sock.close()
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Relay bytes both ways until either side closes or both go idle."""
    socks = [a, b]
    try:
        while True:
            ready, _, err = select.select(socks, [], socks, IDLE_TIMEOUT)
            if err or not ready:
                return
            for src in ready:
                dst = b if src is a else a
                try:
                    data = src.recv(65536)
                except OSError:
                    return
                if not data:
                    # Half-close so the peer sees EOF rather than a reset; an upload that
                    # ends before the response arrives is normal, not an error.
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError as _exc:
                        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                    return
                try:
                    dst.sendall(data)
                except OSError:
                    return
    finally:
        _shut(a)
        _shut(b)


# ── the shim server ───────────────────────────────────────────────────────────────────
class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # noqa: C901 - protocol code
        up: Upstream = self.server.upstream  # type: ignore[attr-defined]
        client = self.request
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client.settimeout(IDLE_TIMEOUT)
        try:
            start, headers = _read_head(client)
        except OSError:
            return
        try:
            method, target, version = start.split(' ', 2)
        except ValueError:
            return self._fail(400, 'malformed request line')

        self.server.note_request()  # type: ignore[attr-defined]

        if method.upper() == 'CONNECT':
            host, _, port_s = target.rpartition(':')
            try:
                port = int(port_s)
            except ValueError:
                return self._fail(400, 'CONNECT needs host:port')
            try:
                remote = up.connect(host, port)
            except Exception as e:  # noqa: BLE001
                self.server.note_error(str(e))  # type: ignore[attr-defined]
                return self._fail(502, str(e))
            try:
                client.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            except OSError:
                return _shut(remote)
            return _pipe(client, remote)

        # Absolute-form request (plain http://). Chrome sends these to a proxy for
        # non-TLS origins; everything else arrives as CONNECT above.
        if not target.lower().startswith('http://'):
            return self._fail(400, 'expected an absolute http:// target or CONNECT')
        parts = urllib.parse.urlsplit(target)
        host, port = parts.hostname or '', parts.port or 80
        if not host:
            return self._fail(400, 'target has no host')
        try:
            remote = up.connect(host, port)
        except Exception as e:  # noqa: BLE001
            self.server.note_error(str(e))  # type: ignore[attr-defined]
            return self._fail(502, str(e))

        kept = [h for h in headers if h.split(':', 1)[0].strip().lower() not in _HOP_BY_HOP]
        if up.scheme == 'socks5':
            # Through a SOCKS tunnel we are the origin client, so the request-line must be
            # origin-form; an absolute URI here makes some servers 400.
            path = urllib.parse.urlunsplit(('', '', parts.path or '/', parts.query, ''))
            line = f'{method} {path} {version}'
        else:
            line = start
            if up.user is not None:
                kept.append(f'Proxy-Authorization: {up._basic()}')
        out = '\r\n'.join([line] + kept + ['Connection: close', '', '']).encode('latin-1')
        try:
            remote.sendall(out)
        except OSError as e:
            _shut(remote)
            return self._fail(502, f'upstream write failed — {e}')
        return _pipe(client, remote)

    def _fail(self, code: int, why: str) -> None:
        # The body matters: this is what the operator sees in the tab when a persona's
        # proxy is down, and "ERR_TUNNEL_CONNECTION_FAILED" alone explains nothing.
        body = (f'Nomologin proxy shim: {why}\n').encode('utf-8', 'replace')
        try:
            self.request.sendall(
                f'HTTP/1.1 {code} Proxy Error\r\nContent-Type: text/plain; charset=utf-8\r\n'
                f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode('latin-1')
                + body
            )
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


class ShimServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, listen_port: int, upstream: Upstream, bind: str = '127.0.0.1'):
        self.upstream = upstream
        self.requests_served = 0
        self.last_error: str | None = None
        self.started = time.time()
        self._lock = threading.Lock()
        super().__init__((bind, listen_port), _Handler)

    def note_request(self) -> None:
        with self._lock:
            self.requests_served += 1

    def note_error(self, why: str) -> None:
        with self._lock:
            self.last_error = why

    def handle_error(self, request, client_address) -> None:
        # The stdlib default prints a traceback per dropped connection. A browser closing
        # a keep-alive socket is normal and must not spam the log.
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        self.note_error(repr(exc))


def serve(listen_port: int, upstream_url: str) -> None:
    up = Upstream(upstream_url)
    srv = ShimServer(listen_port, up)
    _zyg_log.info(f'[NOMOLOGIN-PROXY] 127.0.0.1:{listen_port} -> {up.safe}')
    srv.serve_forever()


# ── egress probe ──────────────────────────────────────────────────────────────────────
def probe(upstream_url: str, timeout: float = PROBE_TIMEOUT) -> dict:
    """Ask the upstream what IP the world sees. This is the launch gate.

    Returns {'ok': bool, 'ip': str|None, 'via': str|None, 'error': str|None, 'ms': int}.
    Tries each probe URL in turn so one dead service is not reported as a dead proxy.
    """
    up = Upstream(upstream_url)
    t0 = time.time()
    errors = []
    for url in PROBE_URLS:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ''
        port = parts.port or 443
        try:
            raw = up.connect(host, port, timeout)
            try:
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(raw, server_hostname=host)
                sock.settimeout(timeout)
                path = parts.path or '/'
                sock.sendall(
                    f'GET {path} HTTP/1.1\r\nHost: {host}\r\n'
                    f'User-Agent: Nomologin/1.0\r\nAccept: text/plain\r\n'
                    f'Connection: close\r\n\r\n'.encode('latin-1')
                )
                buf = b''
                while len(buf) < 8192:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            finally:
                _shut(raw)
            head, _, body = buf.partition(b'\r\n\r\n')
            code = _status_code(head.split(b'\r\n', 1)[0].decode('latin-1', 'replace'))
            if code != 200:
                errors.append(f'{host} returned HTTP {code}')
                continue
            ip = body.decode('utf-8', 'replace').strip().splitlines()[-1].strip()
            if _looks_like_ip(ip):
                return {'ok': True, 'ip': ip, 'via': host, 'error': None, 'ms': int((time.time() - t0) * 1000)}
            errors.append(f'{host} did not return an IP')
        except Exception as e:  # noqa: BLE001
            errors.append(f'{host}: {e}')
    return {
        'ok': False,
        'ip': None,
        'via': None,
        'error': '; '.join(errors) or 'no probe ran',
        'ms': int((time.time() - t0) * 1000),
    }


def direct_ip(timeout: float = PROBE_TIMEOUT) -> str | None:
    """This machine's own egress IP, with no proxy. The value a persona must never show."""
    import urllib.request

    for url in PROBE_URLS:
        if urllib.parse.urlsplit(url).scheme.lower() not in ('http', 'https'):
            _zyg_log.debug('skipping probe URL with a non-HTTP scheme: %s', url)
            continue
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Nomologin/1.0'})  # noqa: S310  scheme checked above
            with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # noqa: S310  scheme checked above
                ip = r.read().decode('utf-8', 'replace').strip()
            if _looks_like_ip(ip):
                return ip
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    return None


def _looks_like_ip(s: str) -> bool:
    if not s or len(s) > 45:
        return False
    for fam in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(fam, s)
            return True
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    return False


if __name__ == '__main__':  # the CLI lives in nomologin_proxy_cli
    from zyg_zero.nomologin_proxy_cli import main as _cli_main

    raise SystemExit(_cli_main())
