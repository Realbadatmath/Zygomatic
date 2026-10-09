# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Created 2026-08-03 — server-side autosave for the Creator Nexus app (:8090).
#
# Why this exists: Creator Nexus is a static frontend with no backend. Its entire
# channel registry lived only in browser localStorage, and a bug in init()
# (seedAllPolicyRules -> saveState on every page load) could overwrite that store
# with an empty list. One page load on the wrong origin was enough to lose it.
#
# This blueprint gives the app a durable copy on the workstation: it autosaves the
# raw localStorage keys and hands them back when the browser store comes up empty.
#
# The same failure mode must not be reproduced here, so the write path REFUSES to
# replace a non-empty channel list with an empty one, and every accepted save also
# lands in a timestamped snapshot that is never overwritten.
#
# Contract: the blueprint is self-contained — it reaches the shared runtime through
# zyg_workflows.runtime only, so it can be registered on any Flask app (the
# dashboard at boot, or a bare app in a test).
import glob
import json
import logging as _zyg_logging
import os
import time
from datetime import datetime

from flask import Blueprint, jsonify, request
from zyg_workflows import runtime

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('creator_nexus', __name__)


def _limit(rule: str | None = None):
    """Rate-limit decorator that degrades to a no-op without the dashboard.

    ``runtime.limiter`` is registered by the dashboard at boot and is None when
    this blueprint runs on a bare app (a test, or the site alone), so the limiter
    is looked up through the module — never from-imported — and simply skipped
    when absent. ``rule=None`` means "exempt from the app-wide default", which is
    what these autosave routes need: the browser beacons on every edit.
    """

    def deco(fn):
        limiter = runtime.limiter
        if limiter is None:
            return fn
        return limiter.exempt(fn) if rule is None else limiter.limit(rule)(fn)

    return deco


# ── Storage layout ────────────────────────────────────────────────────────────
# Resolved lazily: ZYG_DATA_ROOT may be set after this module is imported, and a
# test must be able to point the store somewhere else.
def _cn_dir() -> str:
    return os.path.join(runtime.runtime_dir(), 'creator_nexus')


def _cn_current() -> str:
    return os.path.join(_cn_dir(), 'state_current.json')


def _cn_snap_dir() -> str:
    return os.path.join(_cn_dir(), 'snapshots')


# localStorage keys the app owns. Anything outside this list is ignored so a
# compromised or buggy client cannot use the endpoint as general-purpose storage.
_CN_ALLOWED_KEYS = (
    'creator_nexus_channels_v2',
    'creator_nexus_channels_v1',
    'creator_nexus_adsense_v1',
    'creator_nexus_upload_v1',
    'creator_nexus_mkt_v1',
    'creator_nexus_mkt_log_v1',
)

_CN_CHANNEL_KEYS = ('creator_nexus_channels_v2', 'creator_nexus_channels_v1')
_CN_MAX_BYTES = 12 * 1024 * 1024  # reject absurd payloads outright
_CN_KEEP_SNAPS = 60  # rotating history


# The static site is served from :8090 while this API lives on the dashboard, so
# a cross-origin grant is needed — but never a wildcard one: these responses carry
# the vault (see _cn_ensure_dirs). Only origins named in ZYG_CORS_ORIGINS (a
# comma-separated allowlist, e.g. 'http://workstation:8090') are echoed back; with
# the variable unset no CORS header is sent at all and the API is same-origin only.
def _cn_allowed_origins() -> frozenset:
    raw = os.environ.get('ZYG_CORS_ORIGINS', '')
    return frozenset(o.strip().rstrip('/') for o in raw.split(',') if o.strip())


def _cn_cors(resp):
    """Echo the request Origin when it is on the allowlist; otherwise send no grant."""
    origin = (request.headers.get('Origin') or '').rstrip('/')
    if origin and origin in _cn_allowed_origins():
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Vary'] = 'Origin'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _cn_ensure_dirs():
    # The Creator Nexus vault holds passwords, API keys, OAuth client secrets and
    # access tokens in cleartext (that is how the app stores them in localStorage).
    # Mirroring them here must not widen who can read them: owner-only, always.
    os.makedirs(_cn_snap_dir(), exist_ok=True)
    for d in (_cn_dir(), _cn_snap_dir()):
        try:
            os.chmod(d, 0o700)
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _cn_count_channels(keys: dict) -> int:
    """Number of top-level channels in a payload, or -1 when no channel key is present."""
    for k in _CN_CHANNEL_KEYS:
        raw = keys.get(k)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if isinstance(parsed, list):
            return len(parsed)
    return -1


def _cn_read_current() -> dict:
    path = _cn_current()
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            return doc
    except FileNotFoundError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except Exception as e:
        _zyg_log.info(f'[CREATOR-NEXUS] Could not read {path}: {e}')
    return {}


def _cn_write_atomic(path: str, doc: dict):
    tmp = path + '.tmp'
    # Create owner-only from the start — never briefly world-readable while the
    # credentials are being written.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _cn_rotate_snapshots():
    snaps = sorted(glob.glob(os.path.join(_cn_snap_dir(), 'state_*.json')))
    for old in snaps[:-_CN_KEEP_SNAPS]:
        try:
            os.remove(old)
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


@bp.route('/api/creator-nexus/state', methods=['GET', 'POST', 'OPTIONS'])
@_limit()
def creator_nexus_state():
    """GET returns the stored localStorage keys; POST accepts a new snapshot."""
    if request.method == 'OPTIONS':
        return _cn_cors(jsonify({'ok': True}))

    if request.method == 'GET':
        doc = _cn_read_current()
        return _cn_cors(
            jsonify(
                {
                    'success': True,
                    'keys': doc.get('keys', {}),
                    'saved_at': doc.get('saved_at'),
                    'channel_count': doc.get('channel_count', -1),
                    'exists': bool(doc),
                }
            )
        )

    # ── POST ──────────────────────────────────────────────────────────────────
    raw_len = request.content_length or 0
    if raw_len > _CN_MAX_BYTES:
        return _cn_cors(jsonify({'success': False, 'error': f'payload too large ({raw_len} bytes)'})), 413

    # force=True so navigator.sendBeacon() can post as text/plain. A beacon cannot
    # survive a CORS preflight, and application/json would require one — this is how
    # the last edit before a tab closes still reaches disk.
    body = request.get_json(silent=True, force=True) or {}
    incoming = body.get('keys')
    if not isinstance(incoming, dict) or not incoming:
        return _cn_cors(jsonify({'success': False, 'error': 'missing or empty "keys" object'})), 400

    keys = {k: v for k, v in incoming.items() if k in _CN_ALLOWED_KEYS and isinstance(v, str)}
    if not keys:
        return _cn_cors(jsonify({'success': False, 'error': 'no recognised Creator Nexus keys in payload'})), 400

    current = _cn_read_current()

    # Merge onto what is already stored rather than replacing it. A payload that
    # omits a key (partial save, or a client whose localStorage lost one) must not
    # be able to drop that key from the durable copy.
    merged = dict(current.get('keys', {}))
    merged.update(keys)
    keys = merged

    new_count = _cn_count_channels(keys)
    old_count = current.get('channel_count', -1)
    force = bool(body.get('force'))

    # THE guard. This is the exact mistake the browser-side code made: writing an
    # empty list over good data. Refuse it, and say so loudly enough to notice.
    if not force and new_count == 0 and old_count > 0:
        _zyg_log.info(
            f'[CREATOR-NEXUS] REFUSED autosave: 0 channels would replace {old_count}. '
            f'Client likely loaded with an empty localStorage.'
        )
        return _cn_cors(
            jsonify(
                {
                    'success': False,
                    'error': 'refused: would overwrite %d stored channels with 0' % old_count,
                    'stored_count': old_count,
                    'hint': 'GET /api/creator-nexus/state to restore, or resend with force=true',
                }
            )
        ), 409

    if not force and 0 < new_count < old_count:
        # Legitimate (the user deleted channels) but worth a breadcrumb. Snapshots
        # make it recoverable either way, so do not block.
        _zyg_log.info(
            f'[CREATOR-NEXUS] Channel count dropped {old_count} -> {new_count} '
            f'(allowed; previous state kept in snapshots/).'
        )

    now = datetime.now()
    doc = {
        'keys': keys,
        'saved_at': now.isoformat(timespec='seconds'),
        'saved_ts': time.time(),
        'channel_count': new_count,
        'client': (request.headers.get('User-Agent') or '')[:200],
        'origin': (request.headers.get('Origin') or '')[:120],
    }

    try:
        _cn_ensure_dirs()
        # A snapshot is history: it must never be overwritten. Second-resolution
        # names collide when two saves land in the same second, so disambiguate.
        # The suffix keeps lexical order chronological ('.' < '_' < the next second).
        base = now.strftime('%Y%m%d_%H%M%S')
        snap = os.path.join(_cn_snap_dir(), f'state_{base}.json')
        _dup = 0
        while os.path.exists(snap):
            _dup += 1
            snap = os.path.join(_cn_snap_dir(), f'state_{base}_{_dup:02d}.json')
        _cn_write_atomic(snap, doc)
        _cn_write_atomic(_cn_current(), doc)
        _cn_rotate_snapshots()
    except Exception as e:
        _zyg_log.info(f'[CREATOR-NEXUS] Save failed: {e}')
        return _cn_cors(jsonify({'success': False, 'error': str(e)})), 500

    return _cn_cors(
        jsonify(
            {
                'success': True,
                'saved_at': doc['saved_at'],
                'channel_count': new_count,
                'keys_stored': sorted(keys.keys()),
            }
        )
    )


@bp.route('/api/creator-nexus/snapshots', methods=['GET', 'OPTIONS'])
@_limit()
def creator_nexus_snapshots():
    """List the rotating history, newest first."""
    if request.method == 'OPTIONS':
        return _cn_cors(jsonify({'ok': True}))
    out = []
    for path in sorted(glob.glob(os.path.join(_cn_snap_dir(), 'state_*.json')), reverse=True):
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
            out.append(
                {
                    'name': os.path.basename(path),
                    'saved_at': doc.get('saved_at'),
                    'channel_count': doc.get('channel_count', -1),
                    'size': os.path.getsize(path),
                }
            )
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    return _cn_cors(jsonify({'success': True, 'snapshots': out, 'total': len(out)}))


@bp.route('/api/creator-nexus/snapshots/<name>', methods=['GET', 'OPTIONS'])
@_limit()
def creator_nexus_snapshot_one(name):
    """Return one snapshot verbatim so it can be restored into the browser."""
    if request.method == 'OPTIONS':
        return _cn_cors(jsonify({'ok': True}))
    safe = os.path.basename(name)
    if not safe.startswith('state_') or not safe.endswith('.json'):
        return _cn_cors(jsonify({'success': False, 'error': 'bad snapshot name'})), 400
    path = os.path.join(_cn_snap_dir(), safe)
    if not os.path.isfile(path):
        return _cn_cors(jsonify({'success': False, 'error': 'not found'})), 404
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        return _cn_cors(jsonify({'success': False, 'error': str(e)})), 500
    return _cn_cors(
        jsonify(
            {
                'success': True,
                'name': safe,
                'keys': doc.get('keys', {}),
                'saved_at': doc.get('saved_at'),
                'channel_count': doc.get('channel_count', -1),
            }
        )
    )
