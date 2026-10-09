# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.render — narration, captions, the encoders, the three renderers and the QC gates.

Lines 646-1281 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re
import shutil

from zyg_workflows import provenance_seal as _seal
from zyg_workflows import remix_ingest as RI
from zyg_workflows.bin import exe

from .constants import _FONT, _nvenc_sem

from .jobs import _log

from .media import _duration, _enc_timeout, _ffprobe, _run

from .scoring import _ollama_json

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── narration (the transformation layer — see bp_remix docstring) ────────────


def _narration_script(pid, clip_txt, title, channel, clip_dur):
    short = clip_dur < 60
    resp = _ollama_json(
        'You are an energetic video narrator adding original commentary to a clip. '
        f'The clip is from "{title}" by {channel}. Clip transcript excerpt:\n'
        f'"{clip_txt[:1500]}"\n\n'
        'Write punchy, spoken-style narration that adds YOUR take (context, why it '
        'matters, a reaction) — do NOT quote or paraphrase the transcript lines. '
        'Answer STRICT JSON: {"hook": "<max 14 words>", '
        '"insights": [{"at_pct": <0.2..0.8>, "text": "<max 20 words>"}'
        + ('' if short else ', {"at_pct": <0.2..0.8>, "text": "<max 20 words>"}')
        + '], "outro": "<max 12 words>"}',
        num_predict=400,
    )
    if resp and resp.get('hook'):
        lines = [{'at_pct': 0.0, 'text': str(resp['hook'])[:140]}]
        for ins in (resp.get('insights') or [])[: (1 if short else 2)]:
            try:
                lines.append({'at_pct': max(0.15, min(0.85, float(ins['at_pct']))), 'text': str(ins['text'])[:140]})
            except (KeyError, TypeError, ValueError) as _exc:
                _zyg_log.debug('unparseable LLM insight line dropped: %s', _exc)
                continue
        if not short and resp.get('outro'):
            lines.append({'at_pct': 1.0, 'text': str(resp['outro'])[:120]})
        return lines, 'llm'
    _log(pid, 'WARNING', 'Write Narration', 'LLM unavailable — template narration')
    lines = [
        {'at_pct': 0.0, 'text': f'This {channel} moment is everywhere right now — watch how it lands.'},
        {'at_pct': 0.45, 'text': 'This is the part everyone keeps replaying.'},
    ]
    if not short:
        lines.append({'at_pct': 1.0, 'text': 'Follow for the best moments, every day.'})
    return lines, 'template'


def _tts_line(pid, text, wav_path):
    try:
        from zyg_workflows import tts_service as _tts

        def _lf(level, stage, msg):
            _log(pid, level if level in ('INFO', 'WARNING', 'ERROR') else 'INFO', 'Write Narration', msg)

        ok, _ = _tts._tts_shared(
            text, wav_path, 'Write Narration', log_fn=_lf, voice_id=os.environ.get('ZYG_REMIX_VOICE', '')
        )
        return bool(ok) and os.path.isfile(wav_path) and os.path.getsize(wav_path) > 1000
    except Exception as e:
        _log(pid, 'WARNING', 'Write Narration', f'TTS failed: {e}')
        return False


def _build_narration_track(pid, lines, clip_dur, clip_silence_mids, work_dir, tag):
    """TTS each line, place hook at 0.15 s / insights near silence gaps / outro at the
    tail, mix onto an anullsrc timeline. Returns (track_path, coverage_pct, placed)."""
    placed = []
    for i, ln in enumerate(lines):
        wav = os.path.join(work_dir, f'narr_{tag}_{i}.wav')
        if not _tts_line(pid, ln['text'], wav):
            continue
        d = _duration(wav)
        if d <= 0.2:
            continue
        placed.append({'text': ln['text'], 'wav': wav, 'dur': d, 'at_pct': ln['at_pct']})
    if not placed:
        return None, 0.0, []
    # placement
    used = []
    for p in placed:
        if p['at_pct'] <= 0.01:
            t = 0.15
        elif p['at_pct'] >= 0.99:
            t = max(0.5, clip_dur - p['dur'] - 0.6)
        else:
            want = p['at_pct'] * clip_dur
            near = [m for m in clip_silence_mids if abs(m - want) < clip_dur * 0.2]
            t = min(near, key=lambda m: abs(m - want)) if near else want
        for a, b in used:  # nudge to avoid overlap
            if t < b + 0.4 and t + p['dur'] > a - 0.4:
                t = b + 0.5
        t = max(0.0, min(t, max(0.0, clip_dur - p['dur'] - 0.2)))
        used.append((t, t + p['dur']))
        p['at'] = round(t, 2)
    track = os.path.join(work_dir, f'narr_track_{tag}.wav')
    cmd = [
        exe('ffmpeg'),
        '-y',
        '-hide_banner',
        '-loglevel',
        'error',
        '-f',
        'lavfi',
        '-i',
        f'anullsrc=r=48000:cl=stereo:d={clip_dur:.2f}',
    ]
    fc, mix_in = [], '[0:a]'
    for i, p in enumerate(placed):
        cmd += ['-i', p['wav']]
        ms = int(p['at'] * 1000)
        fc.append(f'[{i + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={ms}|{ms}[d{i}]')
        mix_in += f'[d{i}]'
    fc.append(f'{mix_in}amix=inputs={len(placed) + 1}:duration=first:normalize=0[a]')
    cmd += ['-filter_complex', ';'.join(fc), '-map', '[a]', '-c:a', 'pcm_s16le', track]
    rc, _o, err = _run(cmd, timeout=300)
    if rc != 0:
        _log(pid, 'WARNING', 'Write Narration', f'track mix failed: {err[-200:]}')
        return None, 0.0, []
    coverage = 100.0 * sum(p['dur'] for p in placed) / max(clip_dur, 1e-6)
    return track, round(coverage, 1), placed


# ── captions ─────────────────────────────────────────────────────────────────


def _fmt_srt_ts(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}'


def _build_srt(segments, a, b, path):
    idx, out = 1, []
    for s in segments or []:
        if s['end'] < a or s['start'] > b:
            continue
        s0, s1 = max(0.0, s['start'] - a), min(b - a, s['end'] - a)
        if s1 - s0 < 0.2:
            continue
        out.append(f'{idx}\n{_fmt_srt_ts(s0)} --> {_fmt_srt_ts(s1)}\n{s["text"][:120]}\n')
        idx += 1
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return idx > 1


# ── encoding ─────────────────────────────────────────────────────────────────


def _vcodec_nvenc(cq=21):
    return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', str(cq), '-b:v', '0', '-pix_fmt', 'yuv420p']


def _vcodec_x264(crf=22):
    return ['-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf), '-pix_fmt', 'yuv420p']


_AUDIO_ARGS = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000']


def _encode_nvenc_first(pid, pre_args, post_args, out_path, dur, cq=21, crf=22, stage='Split-Screen Render'):
    """NVENC primary (Semaphore(4) respected via lazy _NVENC_SEM), x264 fallback."""
    timeout = _enc_timeout(dur)
    sem = _nvenc_sem()
    acquired = False
    try:
        if sem is not None:
            acquired = sem.acquire(timeout=120)
        rc, _o, err = _run(pre_args + _vcodec_nvenc(cq) + post_args + [out_path], timeout=timeout)
    finally:
        if acquired:
            sem.release()
    if rc == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return True
    _log(pid, 'WARNING', stage, f'NVENC failed ({(err or "")[-160:]}) — x264 fallback')
    rc, _o, err = _run(pre_args + _vcodec_x264(crf) + post_args + [out_path], timeout=timeout * 2)
    if rc != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        _log(pid, 'ERROR', stage, f'encode failed: {(err or "")[-300:]}')
        return False
    return True


_NORM = "fps=30,scale='trunc(iw*sar/2)*2':ih,setsar=1,settb=AVTB,setpts=PTS-STARTPTS"


def _pane(idx, w, h, ybias=0.5):
    """Normalize + fill-crop one input to a pane (the mandatory prefix — without it
    vstack silently falls back to 25 fps, drops frames and corrupts SAR)."""
    return (
        f'[{idx}:v]{_NORM},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,'
        f'crop={w}:{h}:x=(iw-ow)/2:y=(ih-oh)*{ybias},setsar=1[p{idx}]'
    )


def _extract_broll_window(pid, need, work_dir, tag, avoid):
    win = RI.pick_broll_window(need + 1.0, avoid=avoid)
    if not win:
        return None
    out = os.path.join(work_dir, f'broll_{tag}.mp4')
    rc, _o, err = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-hide_banner',
            '-loglevel',
            'error',
            '-ss',
            f'{win["offset"]:.2f}',
            '-t',
            f'{need + 1.0:.2f}',
            '-i',
            win['path'],
            '-an',
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '18',
            out,
        ],
        timeout=_enc_timeout(need),
    )
    if rc != 0:
        _log(pid, 'WARNING', 'Split-Screen Render', f'b-roll extract failed: {err[-160:]}')
        return None
    win['file'] = out
    avoid.append(win)
    return out


def _loudnorm_master(pid, mix_path, final_path, stage):
    """Two-pass loudnorm to −14 LUFS (linear), then mux with -c:v copy. Detects
    ffmpeg's silent fallback to dynamic AGC (audio_mix.py:186-199 hazard).

    This is the single funnel every remix deliverable leaves through — vertical clips
    and long-form compilations alike — so the C2PA content credential is stamped here,
    once, after all three exits (normalised mux, and the two un-normalised copy
    fallbacks) have converged on final_path."""
    rc, _o, err = _run(
        [
            exe('ffmpeg'),
            '-hide_banner',
            '-nostats',
            '-i',
            mix_path,
            '-af',
            'loudnorm=I=-14:TP=-1:LRA=11:print_format=json',
            '-f',
            'null',
            '-',
        ],
        timeout=600,
    )
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', err, re.S)
    ln_args = 'loudnorm=I=-14:TP=-1:LRA=11'
    if rc == 0 and m:
        try:
            meas = json.loads(m.group(0))
            lra_eff = max(11.0, float(meas.get('input_lra') or 0) + 1.0)
            ln_args = (
                'loudnorm=I=-14:TP=-1:LRA={lra:.0f}:linear=true:'
                'measured_I={i}:measured_TP={tp}:measured_LRA={lra_m}:'
                'measured_thresh={th}:offset={off}:print_format=json'
            ).format(
                lra=lra_eff,
                i=meas.get('input_i'),
                tp=meas.get('input_tp'),
                lra_m=meas.get('input_lra'),
                th=meas.get('input_thresh'),
                off=meas.get('target_offset'),
            )
        except (TypeError, ValueError) as _exc:
            _zyg_log.warning('loudnorm measurement unusable, falling back to single-pass normalisation: %s', _exc)
    wav = mix_path + '.ln.wav'
    rc, _o, err = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-hide_banner',
            '-nostats',
            '-i',
            mix_path,
            '-vn',
            '-af',
            ln_args,
            '-ar',
            '48000',
            '-c:a',
            'pcm_s16le',
            wav,
        ],
        timeout=600,
    )
    if rc != 0:
        _log(pid, 'WARNING', stage, 'loudnorm failed — shipping un-normalized audio')
        shutil.copy2(mix_path, final_path)
        ntype = 'skipped'
    else:
        ntype = (
            'linear'
            if '"normalization_type" : "Linear"' in err or '"normalization_type": "linear"' in err.lower()
            else 'dynamic'
        )
        if ntype != 'linear':
            _log(pid, 'WARNING', stage, 'loudnorm fell back to DYNAMIC (speech may pump)')
        rc, _o, err = _run(
            [
                exe('ffmpeg'),
                '-y',
                '-hide_banner',
                '-loglevel',
                'error',
                '-i',
                mix_path,
                '-i',
                wav,
                '-map',
                '0:v',
                '-c:v',
                'copy',
                '-map',
                '1:a',
            ]
            + _AUDIO_ARGS
            + ['-movflags', '+faststart', final_path],
            timeout=600,
        )
        try:
            os.remove(wav)
        except OSError as _exc:
            _zyg_log.debug('loudnorm scratch wav cleanup skipped: %s', _exc)
        if rc != 0:
            shutil.copy2(mix_path, final_path)
            ntype = 'skipped'
    _seal.seal(
        final_path,
        pipeline='remix',
        run_id=pid,
        extra={'loudnorm': ntype},
        log_fn=lambda msg: _log(pid, 'INFO', stage, msg),
    )
    return ntype


# MarginV=90 DELIBERATELY breaks the action-safe rule the other two burn sites
# follow (kanban_server._SUBBURN_STYLE and tools/audio_tools' ASS header, both
# at 5% of frame height). Reviewed 2026-08-20 and kept on operator direction.
#
# ffmpeg's SRT decoder emits PlayResY=288 and libass scales it to the frame, so
# on this 1080x1920 stack one unit is 6.67 px: 90 → 600 px up → the caption's
# bottom lands at y=1320, inside the b-roll pane, 356 px under the divider.
# Action-safe (5% = 93 px, MarginV=14) would put it at y=1827 — which on a 9:16
# short is exactly where Shorts/TikTok draw the progress bar, title and action
# rail, so the captions would ship obscured. Action-safe is a 16:9 broadcast
# rule measured off the frame edge, and on a vertical short that edge is not
# the viewer's edge. Do NOT "align" this with the other two.
_SUB_STYLE = (
    'FontName=DejaVu Sans,Fontsize=15,PrimaryColour=&H00FFFFFF,'
    'OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=90'
)


def _render_vertical_clip(pid, src, a, b, broll_file, narr_track, srt_path, out_path):
    """Fused cut+stack+narrate+caption+encode: 1080×1920, content top / Minecraft
    bottom, content audio ducked under narration, game audio dropped (Content ID)."""
    d = b - a
    pre = [
        exe('ffmpeg'),
        '-y',
        '-hide_banner',
        '-loglevel',
        'error',
        '-ss',
        f'{a:.2f}',
        '-to',
        f'{b:.2f}',
        '-i',
        src,
        '-i',
        broll_file,
    ]
    if narr_track:
        pre += ['-i', narr_track]
    vf = [
        _pane(0, 1080, 960, ybias=0.35),
        _pane(1, 1080, 960, ybias=0.5),
        '[p0][p1]vstack=inputs=2,drawbox=x=0:y=956:w=1080:h=8:color=black@0.9:t=fill[stk]',
    ]
    tail = f'[stk]trim=duration={d:.2f},setpts=PTS-STARTPTS'
    if srt_path:
        tail += f",subtitles={srt_path}:force_style='{_SUB_STYLE}'"
    vf.append(tail + ',format=yuv420p[vout]')
    af = [
        f'[0:a]aresample=48000:async=1:first_pts=0,'
        f'aformat=sample_fmts=fltp:channel_layouts=stereo,'
        f'atrim=duration={d:.2f},asetpts=PTS-STARTPTS[ca]'
    ]
    if narr_track:
        af += [
            '[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[nk][nm]',
            '[ca][nk]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=400[cd]',
            '[cd][nm]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]',
        ]
    else:
        af.append('[ca]alimiter=limit=0.95[aout]')
    pre += ['-filter_complex', ';'.join(vf + af), '-map', '[vout]', '-map', '[aout]']
    post = _AUDIO_ARGS + ['-movflags', '+faststart']
    mix = out_path + '.mix.mp4'
    if not _encode_nvenc_first(pid, pre, post, mix, d, cq=21, crf=22):
        return None
    ntype = _loudnorm_master(pid, mix, out_path, 'Split-Screen Render')
    try:
        os.remove(mix)
    except OSError as _exc:
        _zyg_log.debug('split-screen scratch mix cleanup skipped: %s', _exc)
    return {'loudnorm': ntype}


def _render_wide_segment(pid, src, a, b, broll_file, narr_track, out_path, is_reuse_clip=False):
    """Compilation segment: 1920×1080, content 1920×700 top / Minecraft 1920×380
    bottom (equal-width unequal panes — the least-bad horizontal split on 16:9)."""
    d = b - a
    pre = [
        exe('ffmpeg'),
        '-y',
        '-hide_banner',
        '-loglevel',
        'error',
        '-ss',
        f'{a:.2f}',
        '-to',
        f'{b:.2f}',
        '-i',
        src,
        '-i',
        broll_file,
    ]
    if narr_track:
        pre += ['-i', narr_track]
    content_src = '[0:v]'
    crop_pane_first = ''
    if is_reuse_clip:
        # stored vertical clip: content lives in the top 1080×960 pane — crop it out first
        crop_pane_first = '[0:v]crop=1080:960:0:0[cc];'
        content_src = '[cc]'
    vf = [
        crop_pane_first + f'{content_src}{_NORM},scale=1920:700:force_original_aspect_ratio=increase:flags=lanczos,'
        f'crop=1920:700:x=(iw-ow)/2:y=(ih-oh)*0.35,setsar=1[p0]',
        _pane(1, 1920, 380, ybias=0.5),
        '[p0][p1]vstack=inputs=2,drawbox=x=0:y=696:w=1920:h=8:color=black@0.9:t=fill[stk]',
        f'[stk]trim=duration={d:.2f},setpts=PTS-STARTPTS,format=yuv420p[vout]',
    ]
    af = [
        f'[0:a]aresample=48000:async=1:first_pts=0,'
        f'aformat=sample_fmts=fltp:channel_layouts=stereo,'
        f'atrim=duration={d:.2f},asetpts=PTS-STARTPTS[ca]'
    ]
    if narr_track:
        af += [
            '[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[nk][nm]',
            '[ca][nk]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=400[cd]',
            '[cd][nm]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]',
        ]
    else:
        af.append('[ca]alimiter=limit=0.95[aout]')
    pre += ['-filter_complex', ';'.join(vf + af), '-map', '[vout]', '-map', '[aout]']
    post = _AUDIO_ARGS + ['-movflags', '+faststart']
    return _encode_nvenc_first(pid, pre, post, out_path, d, cq=23, crf=23, stage='Compilation Render')


def _render_title_card(pid, title_text, narr_wav, broll_file, out_path, dur=6.0):
    """Narrated intro/outro card: blurred Minecraft b-roll + title band."""
    txt = out_path + '.title.txt'
    with open(txt, 'w', encoding='utf-8') as f:
        f.write(title_text[:80])
    pre = [exe('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error', '-i', broll_file]
    if narr_wav:
        pre += ['-i', narr_wav]
    else:
        pre += ['-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={dur:.2f}']
    vf = (
        f'[0:v]{_NORM},scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,'
        f'scale=192:108,gblur=sigma=4,scale=1920:1080:flags=bilinear,'
        f'drawbox=x=0:y=440:w=1920:h=200:color=black@0.65:t=fill,'
        f'drawtext=fontfile={_FONT}:textfile={txt}:fontsize=64:fontcolor=white:'
        f'x=(w-text_w)/2:y=(h-text_h)/2,'
        f'trim=duration={dur:.2f},setpts=PTS-STARTPTS,format=yuv420p[vout]'
    )
    af = (
        f'[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
        f'apad,atrim=duration={dur:.2f},asetpts=PTS-STARTPTS[aout]'
    )
    pre += ['-filter_complex', vf + ';' + af, '-map', '[vout]', '-map', '[aout]']
    post = _AUDIO_ARGS + ['-movflags', '+faststart']
    ok = _encode_nvenc_first(pid, pre, post, out_path, dur, cq=23, crf=23, stage='Compilation Render')
    try:
        os.remove(txt)
    except OSError as _exc:
        _zyg_log.debug('concat list cleanup skipped: %s', _exc)
    return ok


# ── QC gates ─────────────────────────────────────────────────────────────────


def _qc_media(path, want_w, want_h, want_dur):
    g = {}
    info = _ffprobe(path)
    streams = info.get('streams') or []
    v = next((s for s in streams if s.get('codec_type') == 'video'), None)
    a = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    g['streams'] = {'ok': bool(v and a), 'detail': f'v={bool(v)} a={bool(a)}'}
    if v:
        g['geometry'] = {
            'ok': int(v.get('width') or 0) == want_w
            and int(v.get('height') or 0) == want_h
            and (v.get('sample_aspect_ratio') in (None, '1:1', '0:1')),
            'detail': f'{v.get("width")}x{v.get("height")} sar={v.get("sample_aspect_ratio")}',
        }
        g['fps'] = {'ok': v.get('r_frame_rate') == '30/1', 'detail': str(v.get('r_frame_rate'))}
    dur = _duration(path)
    g['duration'] = {'ok': abs(dur - want_dur) <= 1.0, 'detail': f'{dur:.2f}s vs plan {want_dur:.2f}s'}
    info2 = _ffprobe(path, ignore_editlist=True)
    try:
        d2 = float((info2.get('format') or {}).get('duration') or 0)
    except (TypeError, ValueError):
        d2 = 0.0
    g['no_hidden_preroll'] = {'ok': abs(dur - d2) <= 0.25, 'detail': f'{dur:.2f} vs editlist-off {d2:.2f}'}
    g['size'] = {'ok': os.path.getsize(path) > 1_000_000, 'detail': f'{os.path.getsize(path)} B'}
    # full-frame black
    _rc, _o, err = _run(
        [
            exe('ffmpeg'),
            '-hide_banner',
            '-nostats',
            '-i',
            path,
            '-vf',
            'blackdetect=d=0.5:pic_th=0.98:pix_th=0.10',
            '-an',
            '-f',
            'null',
            '-',
        ],
        timeout=max(120, int(dur * 2)),
    )
    blacks = re.findall(r'black_duration:([\d.]+)', err)
    g['black_frames'] = {'ok': sum(float(x) for x in blacks) <= 0.02 * dur, 'detail': f'{len(blacks)} interval(s)'}
    # both panes alive (the highest-damage silent failure: half-black published at scale)
    half = want_h // 2
    pane_ok, pane_notes = True, []
    for name, crop in (('top', f'crop=iw:{half}:0:0'), ('bottom', f'crop=iw:ih-{half}:0:{half}')):
        _rc, _o, perr = _run(
            [
                exe('ffmpeg'),
                '-hide_banner',
                '-nostats',
                '-i',
                path,
                '-vf',
                f'{crop},blackdetect=d=0.3:pic_th=0.98',
                '-an',
                '-f',
                'null',
                '-',
            ],
            timeout=max(120, int(dur * 2)),
        )
        n_black = len(re.findall(r'black_start', perr))
        yavgs = []
        for frac in (0.15, 0.4, 0.65, 0.9):
            _rc2, _o2, serr = _run(
                [
                    exe('ffmpeg'),
                    '-hide_banner',
                    '-nostats',
                    '-ss',
                    f'{dur * frac:.2f}',
                    '-i',
                    path,
                    '-frames:v',
                    '1',
                    '-vf',
                    f'{crop},signalstats,metadata=print',
                    '-f',
                    'null',
                    '-',
                ],
                timeout=60,
            )
            m = re.search(r'YAVG=([\d.]+)', serr)
            if m:
                yavgs.append(float(m.group(1)))
        varies = len(set(round(y, 1) for y in yavgs)) > 1
        lum_ok = yavgs and all(10 <= y <= 245 for y in yavgs)
        ok = n_black == 0 and lum_ok and varies
        pane_ok = pane_ok and ok
        pane_notes.append(f'{name}: black={n_black} yavg={[round(y, 1) for y in yavgs]} varies={varies}')
    g['panes_alive'] = {'ok': pane_ok, 'detail': '; '.join(pane_notes)}
    # loudness (advisory ±1.5 LU)
    _rc, _o, err = _run(
        [exe('ffmpeg'), '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128', '-vn', '-f', 'null', '-'],
        timeout=max(120, int(dur * 2)),
    )
    m = re.search(r'I:\s*(-?[\d.]+)\s*LUFS', err)
    lufs = float(m.group(1)) if m else None
    g['loudness'] = {'ok': lufs is not None and abs(lufs + 14.0) <= 1.5, 'detail': f'{lufs} LUFS', 'advisory': True}
    critical = [k for k, r in g.items() if not r.get('advisory') and not r['ok']]
    return {'ok': not critical, 'failed': critical, 'gates': g}


def _phash_video(path, n=8):
    """64-bit DCT pHash per sampled frame (cv2+numpy only; drop degenerate 0x0)."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    dur = _duration(path)
    hashes = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        cap = cv2.VideoCapture(path)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(frame, (32, 32)), cv2.COLOR_BGR2GRAY).astype('float32')
        d = cv2.dct(g)[:8, :8].flatten()
        med = float(np.median(d[1:]))
        bits = 0
        for j, v in enumerate(d):
            if v > med:
                bits |= 1 << j
        if bits:
            hashes.append(f'{bits:016x}')
    return hashes


def _slug(title, n=44):
    s = re.sub(r'[^a-z0-9]+', '_', (title or 'remix').lower()).strip('_')
    return s[:n] or 'remix'
