# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.compilation — the COMPILATION pipeline and the retention sweep.

Lines 1519-1807 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import traceback

from zyg_workflows import remix_ingest as RI
from zyg_workflows.bin import exe

from .constants import _OUT_ROOT, _env_i, _jobs, _marker, _marker_update, _now_iso

from .jobs import _Stopped, _check_stop, _finish, _log, _mk_job, _tree_gb, _update_stage, disk_ok

from .media import _duration, _run

from .scoring import _ollama_json, _ollama_release

from .render import (
    _extract_broll_window,
    _loudnorm_master,
    _qc_media,
    _render_title_card,
    _render_wide_segment,
    _slug,
    _tts_line,
)


# ── the COMPILATION pipeline ─────────────────────────────────────────────────


def start_compilation(clip_ids=None, target_minutes=None, title='', pipeline_options=None, force=False, **_kw):
    """Long-form 16:9 compilation from proven clips (8-30 min → mid-roll ads).
    NOT exempt from the reused-content bar — the narrated intro/transitions/outro
    ARE the 'storyline and commentary' YouTube's policy names as monetizable."""
    if not force and any(jj.get('status') == 'running' for jj in _jobs().values()):
        return {'error': 'pipeline_busy'}
    ok, why = disk_ok()
    if not ok:
        return {'error': f'disk gate: {why}'}
    s = RI.settings()
    mins = float(target_minutes or s.get('compile_minutes') or 10)
    mins = max(8.0, min(30.0, mins))
    pid = _mk_job(
        'compilation',
        f'compilation {mins:.0f}min',
        params={
            'clip_ids': list(clip_ids or []),
            'target_minutes': mins,
            'title': title,
            'options': pipeline_options or {},
        },
    )
    threading.Thread(target=_run_compilation, args=(pid,), name=f'remix-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'remix', 'mode': 'compilation'}


def _pick_compilation_segments(pid, clip_ids, target_s):
    lib = RI.library().get('clips') or []
    if clip_ids:
        chosen = [c for c in lib if c.get('clip_id') in clip_ids]
    else:
        chosen = sorted([c for c in lib if not c.get('used_in_compilation')], key=lambda c: -(c.get('mean_score') or 0))
    out, total = [], 0.0
    for c in chosen:
        seg_d = float(c['end']) - float(c['start'])
        if total + seg_d > target_s * 1.15 and len(out) >= 3:
            break
        out.append(c)
        total += seg_d
    return out, total


def _run_compilation(pid):
    j = _jobs().get(pid)
    p = j['params']
    out_dir = os.path.join(_OUT_ROOT, pid)
    src_dir = os.path.join(out_dir, 'source')
    work_dir = os.path.join(out_dir, 'work')
    for d in (out_dir, src_dir, work_dir):
        os.makedirs(d, exist_ok=True)
    mid = _marker(f'🎞 Remix compilation {pid[:8]}', pid)
    try:
        _update_stage(pid, 'Score Candidates', 5)
        target_s = p['target_minutes'] * 60.0
        segs, total = _pick_compilation_segments(pid, p.get('clip_ids'), target_s)
        if len(segs) < 3:
            raise RuntimeError(f'only {len(segs)} usable segment(s) in the library — need ≥3')
        _log(pid, 'INFO', 'Score Candidates', f'{len(segs)} segments, {total / 60:.1f} min of proven content')
        _check_stop(pid)

        _update_stage(pid, 'Download Source', 15)
        for i, c in enumerate(segs):
            _check_stop(pid)
            media = ''
            mode = ''
            path = RI.download_section(
                c['source_video_id'],
                float(c['start']),
                float(c['end']),
                src_dir,
                log=lambda m: _log(pid, 'WARNING', 'Download Source', m),
            )
            if path:
                media, mode = path, 'section'
                c['_a'], c['_b'] = 3.0, 3.0 + (float(c['end']) - float(c['start']))
            elif c.get('file') and os.path.isfile(c['file']) and not c.get('deleted'):
                media, mode = c['file'], 'reuse_clip'
                c['_a'], c['_b'] = 0.0, _duration(c['file'])
            if not media:
                _log(pid, 'WARNING', 'Download Source', f'segment {i}: source gone and clip deleted — skipped')
            c['_media'], c['_mode'] = media, mode
        segs = [c for c in segs if c.get('_media')]
        if len(segs) < 3:
            raise RuntimeError('fewer than 3 segments obtainable (sources gone + clips expired)')
        _check_stop(pid)

        _update_stage(pid, 'Write Narration', 30)
        comp_title = p.get('title') or f'Best of {segs[0].get("source_channel") or "the week"}'
        resp = _ollama_json(
            f'You are narrating a highlights compilation titled "{comp_title}". Segments:\n'
            + '\n'.join(f'{i + 1}. {c.get("source_title")} ({c.get("source_channel")})' for i, c in enumerate(segs))
            + '\n\nWrite spoken narration with YOUR editorial framing (why these moments '
            'belong together, what to watch for). Answer STRICT JSON: '
            '{"intro": "<max 30 words>", "transitions": ["<max 14 words per segment, '
            'one entry per segment>"], "outro": "<max 16 words>"}',
            num_predict=700,
        )
        intro_txt = (resp or {}).get('intro') or (
            f'The moments everyone kept replaying — {comp_title}. Stick around, number one is wild.'
        )
        trans = (resp or {}).get('transitions') or []
        outro_txt = (resp or {}).get('outro') or 'Subscribe for the best moments, every single week.'
        narr_files = {}
        for key, txt in [('intro', intro_txt), ('outro', outro_txt)] + [
            (f't{i}', (trans[i] if i < len(trans) else f'Next up: {c.get("source_channel")}.'))
            for i, c in enumerate(segs)
        ]:
            wav = os.path.join(work_dir, f'comp_narr_{key}.wav')
            if _tts_line(pid, str(txt)[:200], wav):
                narr_files[key] = wav
        _ollama_release()
        _check_stop(pid)

        _update_stage(pid, 'Compilation Render', 45)
        parts, avoid = [], []
        broll_intro = _extract_broll_window(pid, 8.0, work_dir, 'intro', avoid)
        if broll_intro:
            card = os.path.join(work_dir, 'part_intro.mp4')
            if _render_title_card(pid, comp_title, narr_files.get('intro'), broll_intro, card, dur=6.0):
                parts.append(card)
        total_parts = len(segs)
        for i, c in enumerate(segs):
            _check_stop(pid)
            need = c['_b'] - c['_a']
            broll = _extract_broll_window(pid, need, work_dir, f'seg{i}', avoid)
            if not broll:
                continue
            # per-segment transition narration ducked over the segment head
            tr_wav = narr_files.get(f't{i}')
            tr_track = None
            if tr_wav:
                # place the single transition line at t=0.2 on a clip-length track
                tr_track = os.path.join(work_dir, f'tr_track_{i}.wav')
                rc, _o, _e = _run(
                    [
                        exe('ffmpeg'),
                        '-y',
                        '-hide_banner',
                        '-loglevel',
                        'error',
                        '-f',
                        'lavfi',
                        '-i',
                        f'anullsrc=r=48000:cl=stereo:d={need:.2f}',
                        '-i',
                        tr_wav,
                        '-filter_complex',
                        '[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                        'adelay=200|200[d0];[0:a][d0]amix=inputs=2:duration=first:normalize=0[a]',
                        '-map',
                        '[a]',
                        '-c:a',
                        'pcm_s16le',
                        tr_track,
                    ],
                    timeout=120,
                )
                if rc != 0:
                    tr_track = None
            part = os.path.join(work_dir, f'part_{i:02d}.mp4')
            if _render_wide_segment(
                pid, c['_media'], c['_a'], c['_b'], broll, tr_track, part, is_reuse_clip=(c['_mode'] == 'reuse_clip')
            ):
                parts.append(part)
            _update_stage(pid, 'Compilation Render', 45 + int(40 * (i + 1) / total_parts))
        broll_outro = _extract_broll_window(pid, 6.0, work_dir, 'outro', avoid)
        if broll_outro:
            card = os.path.join(work_dir, 'part_outro.mp4')
            if _render_title_card(pid, 'Thanks for watching', narr_files.get('outro'), broll_outro, card, dur=4.0):
                parts.append(card)
        if len(parts) < 3:
            raise RuntimeError(f'only {len(parts)} part(s) rendered')
        lst = os.path.join(work_dir, 'concat.txt')
        with open(lst, 'w', encoding='utf-8') as f:
            for part in parts:
                f.write(f"file '{part}'\n")
        mix = os.path.join(work_dir, 'compilation_mix.mp4')
        rc, _o, err = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-hide_banner',
                '-loglevel',
                'error',
                '-f',
                'concat',
                '-safe',
                '0',
                '-i',
                lst,
                '-c',
                'copy',
                '-movflags',
                '+faststart',
                mix,
            ],
            timeout=900,
        )
        if rc != 0:
            raise RuntimeError(f'concat failed: {err[-300:]}')
        slug = _slug(comp_title)
        final = os.path.join(out_dir, f'{slug}_compilation_final.mp4')
        _loudnorm_master(pid, mix, final, 'Compilation Render')
        _check_stop(pid)

        _update_stage(pid, 'QC Gates', 90)
        final_dur = _duration(final)
        qc = _qc_media(final, 1920, 1080, final_dur)
        if not qc['ok']:
            raise RuntimeError(f'compilation failed QC: {qc["failed"]}')
        if final_dur < 8 * 60:
            _log(
                pid, 'WARNING', 'QC Gates', f'compilation is {final_dur / 60:.1f} min — under the 8-min mid-roll floor'
            )

        _update_stage(pid, 'Deliver', 95)
        RI._save(
            os.path.join(out_dir, 'attribution.json'),
            {
                'mode': 'compilation',
                'title': comp_title,
                'created_at': _now_iso(),
                'segments': [
                    {
                        'clip_id': c.get('clip_id'),
                        'source_video_id': c.get('source_video_id'),
                        'source_channel': c.get('source_channel'),
                        'range': [c.get('start'), c.get('end')],
                        'mode': c.get('_mode'),
                    }
                    for c in segs
                ],
                'narration': {'intro': intro_txt, 'outro': outro_txt, 'transitions': trans},
            },
        )
        RI.library_update([c.get('clip_id') for c in segs], {'used_in_compilation': True})

        _update_stage(pid, 'Cleanup', 98)
        shutil.rmtree(src_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        _finish(pid, True, result=f'{final_dur / 60:.1f} min compilation → {final}')
        _marker_update(mid, status='done')
    except _Stopped:
        _finish(pid, False, error='stopped by user')
        _marker_update(mid, status='done', label=f'🎞 Compilation {pid[:8]} — stopped')
    except Exception as e:
        _log(pid, 'ERROR', 'Deliver', f'{e}')
        _finish(pid, False, error=f'{e}\n{traceback.format_exc()[:600]}')
        _marker_update(mid, status='done', label=f'🎞 Compilation {pid[:8]} — failed')


# ── retention (called by the bp_remix cleaner thread) ────────────────────────


def retention_sweep(log=print) -> dict:
    """User spec 2026-08-05: finished clips live 72 h (ample upload window), then the
    whole job dir goes; library metadata survives for compilations + dedupe."""
    ttl_h = _env_i('ZYG_REMIX_CLIP_TTL_H', 72)
    now = time.time()
    removed, freed = [], 0
    if not os.path.isdir(_OUT_ROOT):
        return {'removed': 0, 'freed_gb': 0.0}
    for name in sorted(os.listdir(_OUT_ROOT)):
        d = os.path.join(_OUT_ROOT, name)
        if not os.path.isdir(d) or name.startswith('_'):
            continue
        j = _jobs().get(name)
        if j and j.get('status') == 'running':
            continue
        age_h = (now - os.path.getmtime(d)) / 3600.0
        if age_h >= ttl_h:
            sz = _tree_gb(d)
            shutil.rmtree(d, ignore_errors=True)
            RI.library_mark_deleted_for_job(name)
            removed.append(name)
            freed += sz
        else:
            # crashed-job residue: source/work dirs older than 12 h with no live job
            for sub in ('source', 'work'):
                sd = os.path.join(d, sub)
                if os.path.isdir(sd) and (now - os.path.getmtime(sd)) / 3600.0 > 12 and not j:
                    freed += _tree_gb(sd)
                    shutil.rmtree(sd, ignore_errors=True)
    if removed:
        log(f'[REMIX-CLEANER] removed {len(removed)} job dir(s), freed {freed:.1f} GB')
    return {'removed': len(removed), 'freed_gb': round(freed, 2)}
