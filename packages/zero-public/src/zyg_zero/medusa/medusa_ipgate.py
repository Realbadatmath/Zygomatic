#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
medusa_ipgate.py — shared client-IP allowlist for the Medusa apps (2026-08-08).

WHY THIS EXISTS. Both Medusa front-ends bind 0.0.0.0 and neither has a session
or login, yet both proxy to the crews API (:5000) whose own guard is
`path.startswith('/api/medusa/') and request.remote_addr in ('127.0.0.1','::1')`.
Because these processes make that upstream call FROM 127.0.0.1, each one
launders a LAN request into an API that believes it is localhost-only — a
confused deputy. There are TWO of them:

    medusa_server.py   :5300  — Character Studio, Inspection, Training tab
                                (scan-folder reads directory listings off disk)
    medusa_presets.py  :5301  — proxies /api/medusa/pending and
                                /api/medusa/pending/<id>/decide, i.e. ANY LAN
                                device could approve or reject items in the
                                operator approval queue.

Gating only :5300 would have left :5301 wide open, so the gate lives here and
both import it. Keep it that way — a copy-pasted second implementation is how
the two drift apart.

Binding to 127.0.0.1 instead was considered and rejected: the operator's browser
may connect from another machine on the LAN, so localhost binding would lock
them out of their own tool.

TRUST MODEL. No reverse proxy fronts these ports (bare Flask/Werkzeug), so
request.remote_addr is the real peer and is trustworthy. X-Forwarded-For is
deliberately IGNORED — nothing sets it here, so honouring it would let any
client forge an allowed address with a single header.

LOCKOUT SAFETY. Loopback is ALWAYS allowed and cannot be configured away, so a
malformed allowlist can never permanently lock the operator out — they can
always reach the app from the box itself, or through
`ssh -L 5300:127.0.0.1:5300 <user>@<host>`, to fix the config.

NOTE: this is reachability reduction, not authentication. Anything that can
present an allowed source address is inside.
"""

import ipaddress
import json
import os

from flask import Response, request
import logging as _zyg_logging

from zyg_zero import settings

_zyg_log = _zyg_logging.getLogger(__name__)


_ALWAYS_ALLOWED = ('127.0.0.1/32', '::1/128')

# Nothing beyond loopback by default: an install that names no address is reachable from
# the box itself and from nowhere else. A deployment lists the addresses it wants in
# ZYG_LAN_ALLOWLIST (MEDUSA_ALLOWED_IPS still wins, for the existing unit files) — usually
# the operator's workstation AND the box's own LAN address, because `ip route get` resolves
# the URL every entry point advertises to that address, so omitting it denies the machine
# access to itself.
DEFAULT_ALLOWED = settings.ZYG_LAN_ALLOWLIST


def parse_allowlist(raw):
    """Build the allowed-network list. Accepts bare IPs and CIDR ranges.

    A CIDR with host bits set (e.g. a single host written with a /24 suffix) is accepted
    but WARNED about loudly, because it silently widens the allowlist to the whole range —
    that is a 256-address grant from what looks like a single-host entry.
    """
    nets = [ipaddress.ip_network(c) for c in _ALWAYS_ALLOWED]
    for item in (raw or '').replace(';', ',').split(','):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=True))
            continue
        except ValueError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            _zyg_log.warning(f'[medusa-ipgate] WARNING: ignoring invalid MEDUSA_ALLOWED_IPS entry {item!r}')
            continue
        _zyg_log.warning(
            f'[medusa-ipgate] WARNING: {item!r} has host bits set; widened to '
            f'{net} — that admits {net.num_addresses} addresses.'
        )
        nets.append(net)
    return nets


ALLOWED_NETS = parse_allowlist(os.environ.get('MEDUSA_ALLOWED_IPS', DEFAULT_ALLOWED))


def client_allowed(addr, nets=None):
    nets = ALLOWED_NETS if nets is None else nets
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # An IPv4-mapped IPv6 address (::ffff:a.b.c.d) must be compared as the IPv4 address
    # it represents, or every allowlist entry would miss it.
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    return any(ip in net for net in nets)


_denied_counts = {}


def _note_denial(addr, method, path):
    """Log the first denial per address, then every 100th.

    The training routes are per-object (/characters/<id>/images/<id>), so a
    scanner or a stale browser tab can produce thousands of distinct paths;
    logging every one buries the signal.
    """
    n = _denied_counts.get(addr, 0) + 1
    _denied_counts[addr] = n
    if n == 1 or n % 100 == 0:
        _zyg_log.warning(f'[medusa-ipgate] DENIED {addr} ({n} total) {method} {path}')


def install(app, service_name='medusa'):
    """Attach the gate to EVERY route on `app` — pages, static and /api alike."""
    _zyg_log.warning(f'[medusa-ipgate] {service_name}: allowlist active: ' + ', '.join(str(n) for n in ALLOWED_NETS))

    @app.before_request
    def _gate_by_client_ip():
        if client_allowed(request.remote_addr):
            return None
        _note_denial(request.remote_addr, request.method, request.path)
        return Response(
            json.dumps(
                {
                    'ok': False,
                    'error': 'This Medusa instance only accepts connections from '
                    'approved addresses. Set ZYG_LAN_ALLOWLIST to add one.',
                }
            ),
            status=403,
            content_type='application/json',
        )

    return app
