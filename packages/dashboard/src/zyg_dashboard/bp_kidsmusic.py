# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_kidsmusic.py — launch + status routes for the Children's Music workflow.

Why a dedicated blueprint rather than reusing /api/internal/pipeline/start: the
composer panel lives in the :8899 inspection page, which is a different origin
with no dashboard session, and the internal-API bypass in `require_login` is
keyed on ZERO_PUBLIC_TOKEN — which is not set on this box (both .env files are
empty), so that hop currently 503s.  These routes are therefore LOCALHOST-ONLY,
the same shape the medusa and storyteller-training routes already use: the
kanban server is same-host, an external caller still gets 401.

Additive.  Registers only /api/internal/kidsmusic/*.
"""

from __future__ import annotations

import os
from importlib import import_module

from flask import Blueprint, jsonify, request
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


bp = Blueprint('kidsmusic', __name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_ROOT = os.path.realpath(os.path.join(_HERE, 'output', 'kidsmusic'))
# Both trees this blueprint owns. The cinematic family is the same runner and
# the same department writing into its own output root, so delete has to know
# about both — an id that only ever resolved under output/kidsmusic left every
# cinematic folder undeletable from the UI.
_OUT_ROOTS = {'children': _OUT_ROOT, 'cinematic': os.path.realpath(os.path.join(_HERE, 'output', 'cinematic'))}


def _local_only():
    return request.remote_addr in ('127.0.0.1', '::1')


@bp.route('/api/internal/kidsmusic/spec', methods=['GET'])
def km_spec():
    """The option vocabulary the composer panel renders itself from.

    ONE owner: kids_music_theory.ui_spec(). This route and
    kanban_server._km_spec used to build the dict independently and had already
    drifted — one carried `syllables`, the other did not, and neither carried a
    singer.
    """
    from zyg_workflows import kids_music_theory as T

    return jsonify(T.ui_spec())


@bp.route('/api/internal/kidsmusic/start', methods=['POST'])
def km_start():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    data = request.get_json(silent=True) or {}
    song = data.get('song') or {}
    # 'facts' mode names its topic via `subject` ("train") rather than a free
    # `theme` phrase — either satisfies the requirement, and a bare subject is
    # copied into theme so every other brief consumer still has one.
    if not str(song.get('theme') or data.get('directive') or song.get('subject') or '').strip():
        return jsonify({'error': 'a theme or subject is required'}), 400
    if not str(song.get('theme') or '').strip() and str(song.get('subject') or '').strip():
        song['theme'] = song['subject']

    # REJECT an unknown singer rather than defaulting to one. A caller that asks
    # for a voice this workflow does not offer — 'child', 'teen', anything —
    # must be told no, not quietly given an adult and a manifest that claims the
    # request was honoured. Adults only: see kids_music_theory.SINGERS for the
    # measurements behind that.
    from zyg_workflows import kids_music_theory as _T

    if song.get('singer') not in (None, ''):
        if song.get('singer') not in _T.SINGERS:
            return jsonify(
                {
                    'error': f'unknown singer {str(song.get("singer"))[:40]!r}',
                    'allowed': sorted(_T.SINGERS),
                    'note': _T.ui_spec()['singer_note'],
                }
            ), 400
    elif song.get('sung', True):
        song['singer'] = _T.DEFAULT_SINGER

    # Which style table the key is looked up in. Absent means 'children', which
    # is what every caller that predates the cinematic family means — and it is
    # what resolves 'storytime', the one key that exists in both tables.
    fam = song.get('family')
    if fam in (None, ''):
        fam = 'children'
    if fam not in _T.STYLE_FAMILIES:
        return jsonify({'error': f'unknown family {str(fam)[:40]!r}', 'allowed': sorted(_T.STYLE_FAMILIES)}), 400
    song['family'] = fam
    _table = _T.STYLE_FAMILIES[fam]['styles']

    # Same rule for the style: an unknown key must be refused, not silently
    # dropped back to the mood defaults. A style that was withdrawn is refused
    # with the reason, so the caller can tell "never existed" from "retired".
    # Checked against the FAMILY'S table: a cinematic 'lullaby' does not exist,
    # and accepting it would compose a children's song on a cinematic board.
    st = song.get('style')
    if st not in (None, ''):
        if not isinstance(st, str):  # JSON can carry a list/dict here
            return jsonify({'error': f'unknown style {str(st)[:40]!r}', 'family': fam, 'allowed': sorted(_table)}), 400
        if fam == 'children' and st in _T.EXCLUDED_STYLES:
            return jsonify(
                {
                    'error': f'style {str(st)[:40]!r} is excluded: ' + _T.EXCLUDED_STYLES[st],
                }
            ), 400
        if st not in _table:
            return jsonify(
                {
                    'error': f'unknown style {str(st)[:40]!r}',
                    'family': fam,
                    'allowed': sorted(_table),
                }
            ), 400

    # One pipeline at a time, same rule the main dispatcher enforces — a song
    # render and a video render would fight over ComfyUI's single submit lock.
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        running = [pid for pid, j in _workflow_jobs.items() if j.get('status') == 'running']
        if running:
            return jsonify({'error': 'pipeline_busy', 'running_id': running[0]}), 409
    except Exception as _exc:  # noqa: BLE001 — never block on the check
        _zyg_log.warning('busy check failed, starting the song anyway: %s', _exc)

    from zyg_workflows import pipeline_kidsmusic as _km

    info = _km.start_kidsmusic(
        directive=str(data.get('directive') or ''), pipeline_options=data.get('pipeline_options'), song=song
    )
    if info.get('error'):
        return jsonify(info), 400
    try:
        from zyg_dashboard.appcore import _zero_audit_log

        _zero_audit_log(
            'kidsmusic_start',
            {
                'theme': str(song.get('theme'))[:200],
                'age_band': song.get('age_band'),
                'mood': song.get('mood'),
                'family': song.get('family'),
                'style': song.get('style'),
                'singer': song.get('singer'),
            },
        )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('kidsmusic start audit entry could not be written: %s', _exc)
    return jsonify(info)


@bp.route('/api/internal/kidsmusic/status', methods=['GET'])
def km_status():
    """Live view of the current/last children's-music job, for the panel's
    progress strip.  Read-only, so it is not localhost-gated."""
    try:
        from zyg_dashboard.appcore import _workflow_jobs
    except Exception:  # noqa: BLE001
        return jsonify({'jobs': []})
    out = []
    for pid, j in _workflow_jobs.items():
        if j.get('department') != 'kidsmusic':
            continue
        out.append(
            {
                'job_id': pid,
                'status': j.get('status'),
                'stage': j.get('current_stage'),
                'started': j.get('started'),
                'error': (j.get('error') or '')[:400],
                'song': j.get('kidsmusic') or {},
                'style': (j.get('song') or {}).get('style'),
                # debug_events are dicts (the kanban_status contract) — flatten to
                # display lines here so the panel does not have to know the shape.
                'log': [
                    f'{e.get("ts", "")} {e.get("msg", "")}' if isinstance(e, dict) else str(e)
                    # 60, not 14. A run's one explanatory line ("no shippable
                    # leg") could scroll out of a 14-event window before anyone
                    # looked, leaving an empty-looking failure with no reason.
                    for e in (j.get('debug_events') or [])[-60:]
                ],
                'timeline': [
                    {
                        'name': e.get('name'),
                        'status': e.get('status'),
                        'started_at': e.get('started_at'),
                        'ended_at': e.get('ended_at'),
                    }
                    for e in (j.get('stage_timeline') or [])
                ],
            }
        )
    out.sort(key=lambda r: r.get('started') or '', reverse=True)
    # import_module, not __import__: the latter returns the top-level zyg_workflows
    # package for a dotted name, which has no STAGES, so the route answered 500.
    return jsonify({'jobs': out[:8], 'stages': import_module('zyg_workflows.pipeline_kidsmusic').STAGES})


@bp.route('/api/internal/kidsmusic/stop', methods=['POST'])
def km_stop():
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    jid = str((request.get_json(silent=True) or {}).get('job_id') or '')
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        j = _workflow_jobs.get(jid)
        if not j or j.get('department') != 'kidsmusic':
            return jsonify({'error': 'unknown job'}), 404
        ev = j.get('stop_event')
        if ev is not None:
            ev.set()
        return jsonify(
            {
                'ok': True,
                'job_id': jid,
                'note': 'halt requested — the run stops before the next GPU stage; CPU stages already in flight finish',
            }
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': f'{type(e).__name__}: {e}'[:200]}), 500


@bp.route('/api/internal/kidsmusic/remix', methods=['POST'])
def km_remix():
    """Re-balance a finished song's voice against its band from the kept stems.

    Body: {id, vocal_db, backing_db} (each -12..+12 dB; 0/0 re-masters the
    original take). Writes a new master.mp3, puts it under the video, records
    manifest['voice']['mix']. Same id and containment rules as delete; refused
    while that job is still running."""
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    import re

    data = request.get_json(silent=True) or {}
    jid = str(data.get('id') or '')
    if not re.fullmatch(r'[a-f0-9]{12}|cli_[0-9_]{1,24}', jid):
        return jsonify({'error': 'bad id'}), 400
    try:
        vd = float(data.get('vocal_db') or 0.0)
        bd = float(data.get('backing_db') or 0.0)
    except (TypeError, ValueError):
        return jsonify({'error': 'vocal_db and backing_db must be numbers'}), 400
    d = None
    for root in _OUT_ROOTS.values():
        cand = os.path.realpath(os.path.join(root, jid))
        if cand.startswith(root + os.sep) and os.path.isdir(cand):
            d = cand
            break
    if d is None or not os.path.isfile(os.path.join(d, 'manifest.json')):
        return jsonify({'error': 'not found'}), 404
    try:
        from zyg_dashboard.appcore import _workflow_jobs

        j = _workflow_jobs.get(jid) or {}
        if j.get('status') in ('running', 'queued'):
            return jsonify({'error': 'this song is still being made'}), 409
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('job status check failed, continuing without the still-running guard: %s', _exc)
    from zyg_workflows import kids_music_service as K

    try:
        out = K.remix_job(d, vocal_db=vd, backing_db=bd)
    except Exception as e:  # noqa: BLE001
        return jsonify({'error': f'{type(e).__name__}: {e}'[:300]}), 500
    return jsonify(out), (200 if out.get('ok') else 400)


@bp.route('/api/internal/kidsmusic/delete', methods=['POST'])
def km_delete():
    """Remove one finished song folder.  Containment: the id must be the 12-hex
    job id and the resolved path must sit directly inside ONE OF the output
    roots this workflow owns — the containment check is re-made per root, so
    widening the search to the cinematic tree does not widen what may be
    deleted. No caller-supplied path fragment ever reaches the filesystem."""
    if not _local_only():
        return jsonify({'error': 'localhost only'}), 401
    import re
    import shutil

    jid = str((request.get_json(silent=True) or {}).get('id') or '')
    if not re.fullmatch(r'[a-f0-9]{12}|cli_[0-9_]{1,24}', jid):
        return jsonify({'error': 'bad id'}), 400
    d = None
    for root in _OUT_ROOTS.values():
        cand = os.path.realpath(os.path.join(root, jid))
        if cand.startswith(root + os.sep) and os.path.isdir(cand):
            d = cand
            break
    if d is None:
        return jsonify({'error': 'not found'}), 404
    # A manifest is the proof this workflow wrote the folder — but a run killed
    # mid-flight (the health probe restarted the GUI 30 times since 8 July)
    # never gets to write one, and the UI then refused to delete the wreckage
    # forever. So: a manifest still proves ownership, and in its absence the
    # folder may be deleted only if EVERY name in it is one this workflow
    # writes. That is a strictly narrower claim than "the id shape matched",
    # and it cannot be satisfied by a directory we did not create.
    _OURS = {
        'manifest.json',
        'song.json',
        'state.json',
        'lyrics.txt',
        'roll.svg',
        'melody.mid',
        'melody.mp3',
        'song.mp3',
        'master.mp3',
        'LICENSE.txt',
        'MEASUREMENT.json',
        '_render.wav',
        '_render_lvl.wav',
        '_master.wav',
        '_pre.wav',
        '_trim.wav',
        # The picture leg. Without these an interrupted illustrated run
        # leaves 'frames' and 'video.mp4' behind, they read as stray files,
        # and the UI then refuses to delete the wreckage forever — which is
        # the exact failure this whitelist was written to end.
        'video.mp4',
        'poster.jpg',
        'storyboard.json',
        'frames',
        '_clips',
        '_silent.mp4',
        # The voice leg (2026-09-15): kept stems, the review, per-take work
        # and the remix scratch files.
        'stems',
        'voice_report.json',
        '_takes',
        '_remix.wav',
        '_remix_master.mp3',
        '_remux.mp4',
        '_render_low.wav',
        # The voice conversion (2026-09-15): the A/B master and its scratch.
        'master_unconverted.mp3',
        '_vc',
        '_remix_vc.wav',
        '_remix_unconv.mp3',
        '_vc_master.mp3',
    }
    if not os.path.isfile(os.path.join(d, 'manifest.json')):
        try:
            names = set(os.listdir(d))
        except OSError:
            return jsonify({'error': 'not found'}), 404
        stray = sorted(names - _OURS)
        if stray:
            return jsonify({'error': 'not a kidsmusic folder', 'unexpected_files': stray[:10]}), 400
        shutil.rmtree(d, ignore_errors=True)
        return jsonify({'ok': True, 'deleted': jid, 'note': 'incomplete run (no manifest) — removed'})
    shutil.rmtree(d, ignore_errors=True)
    return jsonify({'ok': True, 'deleted': jid})
