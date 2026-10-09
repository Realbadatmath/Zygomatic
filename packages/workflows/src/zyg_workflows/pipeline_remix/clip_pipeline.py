# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.clip_pipeline — the CLIP pipeline — start_remix and _run_remix.

Lines 1282-1518 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import traceback

from zyg_workflows import remix_ingest as RI
from zyg_workflows.bin import exe

from .constants import _OUT_ROOT, _env_i, _jobs, _marker, _marker_update, _now_iso

from .jobs import _Stopped, _check_stop, _finish, _log, _mk_job, _update_stage, disk_ok

from .media import _duration, _get_transcript, _rms_curve, _run, _silences

from .scoring import _fused_curve, _llm_spans, _ollama_release, _pick_windows, _snap_window

from .render import (
    _build_narration_track,
    _build_srt,
    _extract_broll_window,
    _narration_script,
    _phash_video,
    _qc_media,
    _render_vertical_clip,
    _slug,
)


# ── the CLIP pipeline ────────────────────────────────────────────────────────


def start_remix(source_url='', video_id='', pipeline_options=None, force=False, **_kw):
    """Start a Remix clip job. With no video given, remix the top ranked candidate."""
    vid = (video_id or '').strip()
    if not vid and source_url:
        m = re.search(r'(?:v=|youtu\.be/|/shorts/)([\w-]{11})', source_url)
        vid = m.group(1) if m else (source_url.strip() if re.match(r'^[\w-]{11}$', source_url.strip()) else '')
    cand = None
    if not vid:
        cands = RI.ranked_candidates(limit=5)
        if not cands:
            return {'error': 'no candidates — add channels or wait for uploads'}
        cand = cands[0]
        vid = cand['video_id']
    if not force and any(j.get('status') == 'running' for j in _jobs().values()):
        return {'error': 'pipeline_busy'}
    ok, why = disk_ok()
    if not ok:
        return {'error': f'disk gate: {why}'}
    pid = _mk_job(
        'clip', f'remix {vid}', params={'video_id': vid, 'candidate': cand, 'options': pipeline_options or {}}
    )
    threading.Thread(target=_run_remix, args=(pid,), name=f'remix-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'remix', 'video_id': vid}


def _run_remix(pid):
    j = _jobs().get(pid)
    vid = j['params']['video_id']
    out_dir = os.path.join(_OUT_ROOT, pid)
    src_dir = os.path.join(out_dir, 'source')
    work_dir = os.path.join(out_dir, 'work')
    for d in (out_dir, src_dir, work_dir):
        os.makedirs(d, exist_ok=True)
    mid = _marker(f'🎬 Remix {pid[:8]} — {vid}', pid)
    try:
        _update_stage(pid, 'Watch Channels', 2)
        _update_stage(pid, 'Score Candidates', 5)
        s = RI.settings()
        intel = RI.fetch_video_intel(vid, want_comments=True)
        if intel.get('error'):
            raise RuntimeError(f'metadata fetch failed: {intel["error"]}')
        title, channel = intel['title'], intel.get('channel') or intel.get('channel_id') or ''
        perm = {c['channel_id'] for c in RI.channels() if c.get('enabled') and c.get('clipping_permission')}
        if intel.get('channel_id') and intel['channel_id'] not in perm:
            _log(
                pid,
                'WARNING',
                'Score Candidates',
                f'channel {channel!r} is NOT in the permissioned registry — operator-forced run',
            )
        _check_stop(pid)

        _update_stage(pid, 'Download Source', 12)
        ok, why = disk_ok()
        if not ok:
            raise RuntimeError(f'disk gate: {why}')
        _log(pid, 'INFO', 'Download Source', why)
        src = RI.download_video(vid, src_dir, log=lambda m: _log(pid, 'WARNING', 'Download Source', m))
        if not src:
            raise RuntimeError('download failed')
        rc, _o, derr = _run(
            [exe('ffmpeg'), '-v', 'error', '-i', src, '-f', 'null', '-'], timeout=max(300, int(_duration(src)))
        )
        if rc != 0 or derr.strip():
            raise RuntimeError(f'source fails decode gate: {derr[:200]}')
        dur = _duration(src)
        _log(pid, 'INFO', 'Download Source', f'{title!r} — {dur / 60:.1f} min, {os.path.getsize(src) / 1e9:.2f} GB')
        _check_stop(pid)

        _update_stage(pid, 'Transcribe', 25)
        segments, tx_src = _get_transcript(pid, vid, src)
        _check_stop(pid)

        _update_stage(pid, 'Select Moments', 40)
        heatmap = intel.get('heatmap')
        _log(
            pid,
            'INFO',
            'Select Moments',
            f'heatmap={"100 buckets" if heatmap else "ABSENT (reweighted)"} '
            f'comments={len(intel.get("comments") or [])} transcript={tx_src}',
        )
        comments = RI.comment_timestamps(intel.get('comments') or [], dur)
        llm_spans = _llm_spans(pid, segments or [], dur) if segments else []
        rms = _rms_curve(src, dur)
        S, active = _fused_curve(dur, heatmap, comments, llm_spans, rms)
        _log(pid, 'INFO', 'Select Moments', f'signal fusion: {active}')
        min_len = _env_i('ZYG_REMIX_CLIP_MIN_S', 30)
        max_len = _env_i('ZYG_REMIX_CLIP_MAX_S', 180)
        n_clips = int(s.get('clips_per_source') or 3)
        picks = _pick_windows(S, n_clips, min_len, max_len)
        if not picks:
            raise RuntimeError('no clip windows found (flat score curve)')
        silences = _silences(src)
        plans = []
        for p in picks:
            a, b = _snap_window(p['start'], p['end'], segments, silences, dur, min_len, max_len)
            plans.append({'start': a, 'end': b, 'mean_score': p['mean_score']})
        _log(pid, 'INFO', 'Select Moments', 'windows: ' + ', '.join(f'{p["start"]:.0f}-{p["end"]:.0f}s' for p in plans))
        j['params']['plans'] = plans
        _check_stop(pid)

        _update_stage(pid, 'Write Narration', 55)
        narr_floor = float(s.get('narration_min_pct') or 12)
        for i, p in enumerate(plans):
            clip_txt = ' '.join(
                sg['text'] for sg in segments or [] if sg['end'] >= p['start'] and sg['start'] <= p['end']
            )[:2000]
            lines, narr_src = _narration_script(pid, clip_txt, title, channel, p['end'] - p['start'])
            mids = [(x + y) / 2 - p['start'] for x, y in silences if p['start'] <= x and y <= p['end']]
            track, cov, placed = _build_narration_track(pid, lines, p['end'] - p['start'], mids, work_dir, str(i))
            p.update(
                {
                    'narration_track': track,
                    'narration_pct': cov,
                    'narration_source': narr_src if track else 'none',
                    'narration_lines': [q['text'] for q in placed],
                }
            )
            if cov < narr_floor:
                _log(
                    pid,
                    'WARNING',
                    'Write Narration',
                    f'clip {i}: narration {cov:.0f}% < {narr_floor:.0f}% floor '
                    '(reused-content transformation is qualitative — review before publish)',
                )
        _ollama_release()
        _check_stop(pid)

        _update_stage(pid, 'Split-Screen Render', 70)
        slug = _slug(title)
        avoid, rendered = [], []
        for i, p in enumerate(plans):
            _check_stop(pid)
            need = p['end'] - p['start']
            broll = _extract_broll_window(pid, need, work_dir, str(i), avoid)
            if not broll:
                _log(pid, 'ERROR', 'Split-Screen Render', f'clip {i}: no b-roll window — skipped')
                continue
            srt = os.path.join(work_dir, f'cap_{i}.srt')
            has_caps = _build_srt(segments, p['start'], p['end'], srt) if segments else False
            final = os.path.join(out_dir, f'{slug}_clip{i + 1}_final.mp4')
            r = _render_vertical_clip(
                pid, src, p['start'], p['end'], broll, p.get('narration_track'), srt if has_caps else None, final
            )
            if r is None:
                continue
            if has_caps:
                shutil.copy2(srt, os.path.splitext(final)[0] + '.srt')
            p.update({'file': final, 'loudnorm': r.get('loudnorm')})
            rendered.append(p)
        if not rendered:
            raise RuntimeError('no clips rendered')

        _update_stage(pid, 'QC Gates', 85)
        delivered = []
        for _i, p in enumerate(rendered):
            qc = _qc_media(p['file'], 1080, 1920, p['end'] - p['start'])
            p['qc'] = qc
            if qc['ok']:
                delivered.append(p)
                _log(pid, 'INFO', 'QC Gates', f'clip {os.path.basename(p["file"])}: PASS')
            else:
                bad = p['file'] + '.qc_failed'
                os.rename(p['file'], bad)
                _log(pid, 'ERROR', 'QC Gates', f'clip {os.path.basename(p["file"])}: FAIL {qc["failed"]} — quarantined')
        if not delivered:
            raise RuntimeError('all clips failed QC')

        _update_stage(pid, 'Deliver', 92)
        attribution = {
            'source_video_id': vid,
            'source_url': f'https://www.youtube.com/watch?v={vid}',
            'source_title': title,
            'source_channel': channel,
            'channel_in_permission_registry': intel.get('channel_id') in perm,
            'broll': 'self-recorded GameSim Minecraft (Mojang usage guidelines: own gameplay)',
            'created_at': _now_iso(),
            'clips': [
                {
                    'file': os.path.basename(p['file']),
                    'range': [p['start'], p['end']],
                    'narration_pct': p['narration_pct'],
                    'narration_source': p['narration_source'],
                    'narration_lines': p['narration_lines'],
                }
                for p in delivered
            ],
        }
        RI._save(os.path.join(out_dir, 'attribution.json'), attribution)
        for i, p in enumerate(delivered):
            RI.library_register(
                {
                    'clip_id': f'{pid}_{i}',
                    'job_id': pid,
                    'source_video_id': vid,
                    'source_title': title,
                    'source_channel': channel,
                    'start': p['start'],
                    'end': p['end'],
                    'mean_score': p['mean_score'],
                    'file': p['file'],
                    'created_at': _now_iso(),
                    'narration_pct': p['narration_pct'],
                    'phash': _phash_video(p['file']),
                    'used_in_compilation': False,
                    'deleted': False,
                }
            )

        _update_stage(pid, 'Cleanup', 97)
        # user spec 2026-08-05: delete the downloaded episode the moment clips exist
        shutil.rmtree(src_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        _log(
            pid,
            'INFO',
            'Cleanup',
            'source download + work dir deleted; '
            f'{len(delivered)} clip(s) live for '
            f'{_env_i("ZYG_REMIX_CLIP_TTL_H", 72)} h',
        )
        _finish(pid, True, result=f'{len(delivered)} clip(s) → {out_dir}')
        _marker_update(mid, status='done')
    except _Stopped:
        _finish(pid, False, error='stopped by user')
        _marker_update(mid, status='done', label=f'🎬 Remix {pid[:8]} — stopped')
    except Exception as e:
        _log(pid, 'ERROR', 'Deliver', f'{e}')
        _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:600]}')
        _marker_update(mid, status='done', label=f'🎬 Remix {pid[:8]} — failed')
