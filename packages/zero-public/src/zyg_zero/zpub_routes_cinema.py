#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zero Cinema routes — everything behind the fingerprint gate.

Access model
------------
The fingerprint on the public gate page opens a password prompt. A correct
password sets ``session['cinema_ok']`` and NOTHING ELSE — it is deliberately
not the zpub admin flag, so the cinema cannot reach the pipeline, the invite
system, or the admin API.

The password is short, and this app is reachable from the public internet
through the Cloudflare tunnel, so ``/api/cinema/unlock`` is the one route that
really matters: it is rate-limited AND carries its own per-IP lockout with
exponential backoff. Without that, 8 digits is a weekend of guessing.
"""

import hashlib
import mimetypes
import os
import re
import threading
import time

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

from zyg_zero import zpub_cinema as cine
from zyg_zero.zpub_gate import limiter, _client_ip
from zyg_zero.zpub_store import _zpub_log
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('zpub_cinema', __name__)

# pbkdf2:sha256 over the operator's passphrase. Override with ZYG_CINEMA_PASSWORD
# (plaintext) or ZYG_CINEMA_PASSWORD_HASH (a werkzeug hash) to rotate without
# touching source.
_DEFAULT_HASH = 'pbkdf2:sha256:600000$w76K3npbByxPBfnP$d48372033c0691337d801372f85f6ef1b212cc577f8b34da467de222d8c7c35e'


def _password_hash() -> str:
    plain = (os.environ.get('ZYG_CINEMA_PASSWORD') or '').strip()
    if plain:
        return generate_password_hash(plain, method='pbkdf2:sha256:600000')
    return (os.environ.get('ZYG_CINEMA_PASSWORD_HASH') or '').strip() or _DEFAULT_HASH


_PW_HASH = _password_hash()

# ── Brute-force lockout ───────────────────────────────────────────────────────
_FAILS: dict[str, dict] = {}
_FAIL_LOCK = threading.Lock()
_FREE_TRIES = 5  # attempts before backoff starts
_MAX_DELAY = 15 * 60  # cap the lockout so a typo can't lock you out for a day


def _lockout_remaining(key: str) -> int:
    with _FAIL_LOCK:
        rec = _FAILS.get(key)
        if not rec:
            return 0
        if rec['count'] <= _FREE_TRIES:
            return 0
        delay = min(_MAX_DELAY, 2 ** (rec['count'] - _FREE_TRIES) * 5)
        remain = int(rec['last'] + delay - time.time())
        return max(0, remain)


def _note_fail(key: str) -> None:
    with _FAIL_LOCK:
        rec = _FAILS.setdefault(key, {'count': 0, 'last': 0.0})
        rec['count'] += 1
        rec['last'] = time.time()


def _clear_fails(key: str) -> None:
    with _FAIL_LOCK:
        _FAILS.pop(key, None)


def _unlocked() -> bool:
    return bool(session.get('cinema_ok'))


def _require():
    """Guard for every cinema route. Returns a response when denied, else None."""
    if not _unlocked():
        return jsonify({'success': False, 'error': 'locked'}), 403
    return None


# ── Gate ──────────────────────────────────────────────────────────────────────
@bp.route('/api/cinema/unlock', methods=['POST'])
@limiter.limit('20 per hour; 6 per minute')
def cinema_unlock():
    ip = _client_ip()
    key = hashlib.sha1(ip.encode('utf-8', 'replace'), usedforsecurity=False).hexdigest()[:16]
    wait = _lockout_remaining(key)
    if wait:
        return jsonify({'success': False, 'error': f'Too many attempts — wait {wait}s', 'retry_after': wait}), 429
    data = request.get_json(silent=True) or request.form or {}
    pw = (data.get('password') or '').strip()
    if pw and check_password_hash(_PW_HASH, pw):
        _clear_fails(key)
        session['cinema_ok'] = True
        session.permanent = True
        _zpub_log('cinema_unlock', ip=ip, result='ok')
        return jsonify({'success': True, 'redirect': '/cinema'})
    _note_fail(key)
    _zpub_log('cinema_unlock', ip=ip, result='denied')
    return jsonify({'success': False, 'error': 'Incorrect password'}), 401


@bp.route('/api/cinema/lock', methods=['POST'])
def cinema_lock():
    session.pop('cinema_ok', None)
    return jsonify({'success': True})


@bp.route('/cinema')
def cinema_page():
    if not _unlocked():
        return redirect('/')
    return render_template('zero_cinema.html')


# ── Library ───────────────────────────────────────────────────────────────────
@bp.route('/api/cinema/board')
@limiter.exempt
def cinema_board():
    denied = _require()
    if denied:
        return denied
    return jsonify({'success': True, **cine.board()})


@bp.route('/api/cinema/item/<item_id>')
@limiter.exempt
def cinema_item(item_id):
    denied = _require()
    if denied:
        return denied
    detail = cine.item_detail(item_id)
    if not detail:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'item': detail})


@bp.route('/api/cinema/thumb/<item_id>.jpg')
@limiter.exempt
def cinema_thumb(item_id):
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item:
        abort(404)
    path = cine.thumb_path(item_id)
    if not os.path.isfile(path):
        path = cine.build_thumb(item) or ''
    if not path or not os.path.isfile(path):
        abort(404)
    resp = send_file(path, mimetype='image/jpeg', conditional=True)
    resp.headers['Cache-Control'] = 'private, max-age=86400'
    return resp


# ── Playback ──────────────────────────────────────────────────────────────────
@bp.route('/api/cinema/play/<item_id>')
@limiter.exempt
def cinema_play(item_id):
    """Direct byte-range stream — the original file, untouched."""
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item or not os.path.isfile(item.get('path', '')):
        abort(404)
    mime = mimetypes.guess_type(item['path'])[0] or 'video/mp4'
    # conditional=True is what makes scrubbing work: it turns Range requests
    # into 206 responses instead of streaming the whole 3 GB from byte 0.
    resp = send_file(item['path'], mimetype=mime, conditional=True)
    resp.headers['Accept-Ranges'] = 'bytes'
    return resp


@bp.route('/api/cinema/transcode/<item_id>')
@limiter.exempt
def cinema_transcode(item_id):
    """Live-transcoded fragmented MP4 starting at ``?t=`` seconds.

    Seeking is a NEW REQUEST, not a Range: the output is generated on the fly so
    there is no byte offset to ask for. The client tracks ``t`` as its own time
    origin and adds the element's currentTime to it.
    """
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item or not os.path.isfile(item.get('path', '')):
        abort(404)
    try:
        start = max(0.0, float(request.args.get('t', 0) or 0))
    except ValueError:
        start = 0.0
    duration = float(item.get('duration') or 0)
    if duration and start > duration - 1:
        start = max(0.0, duration - 1)
    audio_id = request.args.get('a')
    burn = (request.args.get('burn') or '').strip()

    resp = Response(
        cine.stream_transcode(item, start, audio_id, burn),
        mimetype='video/mp4',
        direct_passthrough=True,
    )
    resp.headers['Cache-Control'] = 'no-store'
    # No Accept-Ranges: this body is generated, so a Range request cannot be
    # honoured and advertising support would make the browser ask for one.
    resp.headers['Accept-Ranges'] = 'none'
    return resp


@bp.route('/api/cinema/seek/<item_id>')
@limiter.exempt
def cinema_seek(item_id):
    """Report the timestamp a transcode at ``?t=`` will REALLY start at.

    On the ``-c:v copy`` path ffmpeg can only begin at a keyframe, so the client
    must be told where it actually landed — otherwise the reported time and every
    subtitle cue drift by up to the keyframe interval (measured: 3.7 s on Gods of
    Egypt, 5.2 s on Thunderbolts).
    """
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    try:
        t = max(0.0, float(request.args.get('t', 0) or 0))
    except ValueError:
        t = 0.0
    duration = float(item.get('duration') or 0)
    if duration and t > duration - 1:
        t = max(0.0, duration - 1)
    burn = (request.args.get('burn') or '').strip()
    return jsonify({'success': True, 'requested': t, 'start': round(cine.exact_start(item, t, burn), 3)})


# ── HLS playback ──────────────────────────────────────────────────────────────
# Preferred over /api/cinema/transcode for every re-encoded title. Same ffmpeg
# ladder, same time-origin model (the stream starts at ``offset`` and the client
# adds the element's currentTime) — the difference is that hls.js owns the buffer
# and will run ~90 s ahead instead of the ~2.4 s a bare <video src> allows.
_HLS_ID_RE = re.compile(r'^[0-9a-f]{16}$')
_HLS_FILE_RE = re.compile(r'^(init\.mp4|seg\d{5}\.m4s)$')


@bp.route('/api/cinema/hls/start/<item_id>', methods=['POST'])
@limiter.limit('240 per hour')
def cinema_hls_start(item_id):
    """Open a session at ``?t=`` and return once its first segment is playable."""
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item or not os.path.isfile(item.get('path', '')):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    try:
        t = max(0.0, float(request.args.get('t', 0) or 0))
    except ValueError:
        t = 0.0
    duration = float(item.get('duration') or 0)
    if duration and t > duration - 1:
        t = max(0.0, duration - 1)
    audio_id = request.args.get('a')
    burn = (request.args.get('burn') or '').strip()
    # Resolve the true start here so the client needs one round trip, not two.
    start = cine.exact_start(item, t, burn)
    out = cine.start_hls(item, start, audio_id, burn)
    if out.get('error'):
        # 'low_disk' and 'transcode_failed' are both recoverable by the client:
        # it falls back to /api/cinema/transcode, which needs no scratch space.
        return jsonify({'success': False, **out}), 503
    return jsonify({'success': True, **out})


@bp.route('/api/cinema/hls/<sess_id>/index.m3u8')
@limiter.exempt
def cinema_hls_playlist(sess_id):
    denied = _require()
    if denied:
        return denied
    if not _HLS_ID_RE.match(sess_id or ''):
        abort(404)
    sess = cine.get_hls(sess_id)
    if not sess:
        abort(410)  # session reaped — the client restarts it
    text = cine._hls_read_playlist(sess['dir'])[0]
    if not text:
        abort(404)
    resp = Response(text, mimetype='application/vnd.apple.mpegurl')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@bp.route('/api/cinema/hls/<sess_id>/<path:name>')
@limiter.exempt
def cinema_hls_segment(sess_id, name):
    denied = _require()
    if denied:
        return denied
    # Names are matched against a literal pattern rather than sanitised: the
    # only two shapes ffmpeg writes are init.mp4 and seg%05d.m4s, so anything
    # else — traversal included — cannot be a legitimate request.
    if not _HLS_ID_RE.match(sess_id or '') or not _HLS_FILE_RE.match(name or ''):
        abort(404)
    sess = cine.get_hls(sess_id)
    if not sess:
        abort(410)
    path = os.path.join(sess['dir'], name)
    if not os.path.isfile(path):
        abort(404)
    if name.startswith('seg'):
        cine.note_hls_segment(sess, int(name[3:8]))
    resp = send_file(path, mimetype='video/mp4', conditional=True)
    # Segments are immutable for the life of the session and the session dies
    # with the tab, so letting the browser keep them makes a backwards seek free.
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@bp.route('/api/cinema/hls/<sess_id>/close', methods=['POST'])
@limiter.exempt
def cinema_hls_close(sess_id):
    denied = _require()
    if denied:
        return denied
    if not _HLS_ID_RE.match(sess_id or ''):
        return jsonify({'success': True})
    cine.close_hls(sess_id)
    return jsonify({'success': True})


@bp.route('/api/cinema/subtitle/<item_id>/<sub_id>.vtt')
@limiter.exempt
def cinema_subtitle(item_id, sub_id):
    denied = _require()
    if denied:
        return denied
    item = cine.get_item(item_id)
    if not item:
        abort(404)
    path = cine.subtitle_vtt(item, sub_id)
    if not path or not os.path.isfile(path):
        abort(404)
    try:
        shift = float(request.args.get('shift', 0) or 0)
    except ValueError:
        shift = 0.0
    if not shift:
        resp = send_file(path, mimetype='text/vtt', conditional=True)
        resp.headers['Cache-Control'] = 'private, max-age=3600'
        return resp
    # A transcoded stream restarts its clock at the seek point, so the cues have
    # to be rebased to match. Generated per-request; the file itself stays cached.
    try:
        with open(path, encoding='utf-8') as f:
            body = cine.shift_vtt(f.read(), shift)
    except OSError:
        abort(404)
    resp = Response(body, mimetype='text/vtt')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ── Scanning ──────────────────────────────────────────────────────────────────
def _browse_roots() -> list[str]:
    roots = [os.path.expanduser('~')]
    for extra in ('/media', '/mnt'):
        if os.path.isdir(extra):
            roots.append(extra)
    for r in cine.load_library().get('roots') or []:
        if r not in roots:
            roots.append(r)
    return roots


def _within_roots(path: str) -> bool:
    """True when ``path`` sits inside a browsable root (symlinks resolved)."""
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    for root in _browse_roots():
        rr = os.path.realpath(root)
        if real == rr or real.startswith(rr + os.sep):
            return True
    return False


@bp.route('/api/cinema/browse')
@limiter.exempt
def cinema_browse():
    """List sub-folders of ``?path=`` so the upload button can pick a scan target."""
    denied = _require()
    if denied:
        return denied
    raw = (request.args.get('path') or '').strip()
    if not raw:
        return jsonify(
            {
                'success': True,
                'path': '',
                'parent': None,
                'roots': _browse_roots(),
                'dirs': [{'name': os.path.basename(r) or r, 'path': r} for r in _browse_roots()],
            }
        )
    path = os.path.abspath(os.path.expanduser(raw))
    if not _within_roots(path) or not os.path.isdir(path):
        return jsonify({'success': False, 'error': 'Folder not accessible'}), 400
    dirs, videos = [], 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append({'name': entry.name, 'path': os.path.join(path, entry.name)})
                    elif os.path.splitext(entry.name)[1].lower() in cine.VIDEO_EXTS:
                        videos += 1
                except OSError as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                    continue
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    dirs.sort(key=lambda d: d['name'].lower())
    parent = os.path.dirname(path.rstrip(os.sep))
    return jsonify(
        {
            'success': True,
            'path': path,
            'videos': videos,
            'parent': parent if _within_roots(parent) else None,
            'roots': _browse_roots(),
            'dirs': dirs,
        }
    )


@bp.route('/api/cinema/scan', methods=['POST'])
@limiter.limit('30 per hour')
def cinema_scan():
    denied = _require()
    if denied:
        return denied
    data = request.get_json(silent=True) or request.form or {}
    root = (data.get('path') or '').strip()
    if not root:
        return jsonify({'success': False, 'error': 'No folder given'}), 400
    path = os.path.abspath(os.path.expanduser(root))
    if not _within_roots(path):
        return jsonify({'success': False, 'error': 'Folder is outside the allowed roots'}), 400
    result = cine.start_scan(path)
    if result.get('error'):
        return jsonify({'success': False, **result}), 400
    _zpub_log('cinema_scan', ip=_client_ip(), path=path)
    return jsonify({'success': True, **result})


@bp.route('/api/cinema/scan/<scan_id>')
@limiter.exempt
def cinema_scan_status(scan_id):
    denied = _require()
    if denied:
        return denied
    status = cine.scan_status(scan_id)
    if not status:
        return jsonify({'success': False, 'error': 'Unknown scan'}), 404
    return jsonify({'success': True, **status})


@bp.route('/api/cinema/forget/<item_id>', methods=['POST'])
@limiter.exempt
def cinema_forget(item_id):
    """Remove a title from the library index. Never touches the file on disk."""
    denied = _require()
    if denied:
        return denied
    lib = cine.load_library()
    if (lib.get('items') or {}).pop(item_id, None) is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    cine.save_library(lib)
    return jsonify({'success': True})


@bp.route('/api/cinema/prefs')
@limiter.exempt
def cinema_prefs():
    """Playback preferences: global defaults plus every per-show override."""
    denied = _require()
    if denied:
        return denied
    data = cine.load_prefs()
    return jsonify({'success': True, 'defaults': data.get('defaults') or {}, 'shows': data.get('shows') or {}})


@bp.route('/api/cinema/prefs', methods=['POST'])
@limiter.exempt
def cinema_prefs_save():
    """Patch the defaults, or one show's overrides when ``show`` is given.

    A value of ``null`` clears that key (back to the global default). Only keys
    the module knows survive, coerced to the shape of their default — this is a
    public-facing route and a stray string where a number belongs would
    otherwise break every subsequent open of that show.
    """
    denied = _require()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    patch = body.get('prefs')
    if not isinstance(patch, dict):
        return jsonify({'success': False, 'error': 'prefs must be an object'}), 400
    show = str(body.get('show') or '')
    data = cine.update_prefs(patch, show)
    key = cine.show_key(show)
    return jsonify(
        {
            'success': True,
            'show': key,
            'defaults': data.get('defaults') or {},
            'overrides': (data.get('shows') or {}).get(key) or {},
        }
    )


@bp.route('/api/cinema/series_name', methods=['POST'])
@limiter.exempt
def cinema_series_name():
    """Name a series whose files don't carry one ('01. Season 1 + Special').

    ``{show: <name as currently shown>, name: <the real name>}``; an empty
    ``name`` drops the override and lets the derived name come back.
    """
    denied = _require()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    current = str(body.get('show') or '').strip()
    name = str(body.get('name') or '').strip()
    if not current:
        return jsonify({'success': False, 'error': 'Which series?'}), 400
    out = cine.set_series_name(current, name)
    if out.get('error'):
        return jsonify({'success': False, **out}), 404
    _zpub_log('cinema_series_named', ip=_client_ip(), was=current, now=name, folders=len(out.get('folders') or []))
    return jsonify({'success': True, **out})
