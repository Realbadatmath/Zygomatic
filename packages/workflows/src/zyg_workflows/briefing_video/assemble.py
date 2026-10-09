# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.briefing_video.assemble — segment render + concat, chapters, the QC gate.

Moved verbatim out of briefing_video.py (lines 1352-1592); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.briefing_video.base import FPS, H, W, _AUDIO_ARGS, _dur, _run, _vcodec, exe, json, os, re, shutil


# ── segment render + concat ─────────────────────────────────────────────────


def _render_segment(img, wav, out, use_nvenc, min_seconds=0.0, ken_burns=False, lead_in=0.0, tail=0.35):
    """One still + one narration wav → one clip, uniformly encoded for -c copy concat.

    `lead_in`/`tail` are silent padding so a panel is on screen fractionally before
    and after its line — without it, every cut lands on a word boundary and the
    episode feels like a slideshow being clicked through.
    """
    a_dur = _dur(wav) if wav and os.path.isfile(wav) else 0.0
    total = max(min_seconds, a_dur + lead_in + tail)
    if total <= 0.2:
        return None, 0.0

    vf = [
        f'scale={W}:{H}:force_original_aspect_ratio=decrease',
        f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black',
        'setsar=1',
    ]
    if ken_burns:
        frames = max(2, int(total * FPS))
        # zoompan on a pre-upscaled still: smooth, and text never softens because
        # the source is 2× the output. Charts never use this (moving axis labels
        # read as a rendering fault) — only photographs and badges do.
        # Capped at 1.05: at 1.09 the crop ate ~4% of every edge, which clipped
        # the header rule and the on-screen artwork credit off the focus cards.
        # Anything drawn inside 6% of an edge must survive this crop.
        vf = [
            f'scale={W * 2}:{H * 2}:force_original_aspect_ratio=decrease',
            f'pad={W * 2}:{H * 2}:(ow-iw)/2:(oh-ih)/2:color=black',
            f"zoompan=z='min(zoom+0.00025,1.05)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}",
            'setsar=1',
        ]

    cmd = [exe('ffmpeg'), '-y', '-loop', '1', '-framerate', str(FPS), '-i', img]
    if a_dur > 0:
        cmd += [
            '-i',
            wav,
            '-filter_complex',
            f'[1:a]adelay={int(lead_in * 1000)}|{int(lead_in * 1000)},apad=whole_dur={total}[a]',
            '-map',
            '0:v',
            '-map',
            '[a]',
        ]
    else:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a']
    cmd += ['-vf', ','.join(vf), '-t', f'{total:.3f}', '-r', str(FPS)]
    cmd += _vcodec(use_nvenc) + _AUDIO_ARGS + ['-movflags', '+faststart', out]
    r = _run(cmd, timeout=max(300, int(total * 12)))
    if r.returncode != 0 or not os.path.isfile(out):
        return None, 0.0
    return out, _dur(out)


def _concat(parts, out, work_dir):
    lst = os.path.join(work_dir, 'concat.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    r = _run(
        [exe('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', '-movflags', '+faststart', out],
        timeout=900,
    )
    return r.returncode == 0 and os.path.isfile(out)


def _loudnorm(src, dst, log=None):
    """Two-pass EBU R128 to −14 LUFS (the YouTube playback target)."""
    r = _run(
        [
            exe('ffmpeg'),
            '-hide_banner',
            '-i',
            src,
            '-af',
            'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json',
            '-f',
            'null',
            '-',
        ],
        timeout=900,
    )
    stats = {}
    try:
        txt = r.stderr or ''
        stats = json.loads(txt[txt.rfind('{') : txt.rfind('}') + 1])
    except Exception:
        stats = {}
    af = 'loudnorm=I=-14:TP=-1.5:LRA=11'
    if stats.get('input_i') and stats.get('input_i') != '-inf':
        af += (
            f':measured_I={stats["input_i"]}:measured_TP={stats["input_tp"]}'
            f':measured_LRA={stats["input_lra"]}:measured_thresh={stats["input_thresh"]}'
            f':offset={stats.get("target_offset", "0")}:linear=true'
        )
    r2 = _run(
        [exe('ffmpeg'), '-y', '-i', src, '-af', af, '-c:v', 'copy'] + _AUDIO_ARGS + ['-movflags', '+faststart', dst],
        timeout=900,
    )
    if r2.returncode != 0 or not os.path.isfile(dst):
        if log:
            log('WARNING', 'loudnorm pass failed — delivering the un-normalised master')
        shutil.copy2(src, dst)
    return dst


# ── chapters ────────────────────────────────────────────────────────────────


def _ts(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{h:d}:{m:02d}:{s:02d}' if h else f'{m:d}:{s:02d}'


def _build_chapters(marks: list, total: float) -> 'tuple[list, list]':
    """(chapters, warnings) obeying YouTube's three hard rules.

    marks = [{'at': seconds, 'title': str}]. Rules enforced: first mark at 0:00,
    at least three chapters, each at least 10 s long. Anything shorter is merged
    forward into its neighbour rather than silently shipped — YouTube drops the
    ENTIRE chapter list when one entry is too short, so a single 8-second segment
    would cost the whole playbar.
    """
    warn = []
    ms = sorted([m for m in (marks or []) if m.get('title')], key=lambda m: m['at'])
    if not ms:
        return [], ['no chapter marks']
    if ms[0]['at'] > 0.5:
        ms.insert(0, {'at': 0.0, 'title': 'Welcome'})
    ms[0]['at'] = 0.0

    merged = []
    for m in ms:
        if merged and (m['at'] - merged[-1]['at']) < 10.0:
            warn.append(f"merged '{m['title']}' — under YouTube's 10 s chapter floor")
            continue
        merged.append(dict(m))
    if merged and (total - merged[-1]['at']) < 10.0 and len(merged) > 1:
        warn.append(f"dropped trailing '{merged[-1]['title']}' — under 10 s")
        merged.pop()
    if len(merged) < 3:
        warn.append(f'only {len(merged)} chapters — YouTube needs 3 to show the segmented playbar')
    return merged, warn


def _ffmetadata(chapters, total, path):
    lines = [';FFMETADATA1']
    for i, c in enumerate(chapters):
        start = int(c['at'] * 1000)
        end = int((chapters[i + 1]['at'] if i + 1 < len(chapters) else total) * 1000)
        if end <= start:
            continue
        lines += ['[CHAPTER]', 'TIMEBASE=1/1000', f'START={start}', f'END={end}', f'title={c["title"]}']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


# ── QC ──────────────────────────────────────────────────────────────────────


def qc(path: str, want_dur: float, chapters: list, production: dict = None) -> dict:
    """Fail-closed gates. A red gate quarantines the file instead of delivering it.

    `production` = {'planned', 'rendered', 'with_text', 'narrated'}. Panels that
    fail to encode or fail TTS are logged as warnings and skipped, so without
    these two counts a run that silently lost three of its seven picks would
    deliver a short, coherent-looking episode that is simply missing content —
    and `duration within 5% of plan` cannot catch it, because the plan is summed
    from the parts that DID render.
    """
    production = production or {}
    res = {'passed': True, 'checks': []}

    def _chk(name, ok, detail=''):
        res['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        if not ok:
            res['passed'] = False

    r = _run(
        [exe('ffprobe'), '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', path], timeout=120
    )
    try:
        info = json.loads(r.stdout or '{}')
    except Exception:
        info = {}
    vs = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    aud = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), {})
    dur = float((info.get('format') or {}).get('duration') or 0)

    _chk('geometry 1920x1080', vs.get('width') == W and vs.get('height') == H, f'{vs.get("width")}x{vs.get("height")}')
    _chk('video stream present', bool(vs), vs.get('codec_name', ''))
    _chk('audio stream present', bool(aud), aud.get('codec_name', ''))
    _chk(
        'duration within 5% of plan',
        want_dur <= 0 or abs(dur - want_dur) <= max(6.0, want_dur * 0.05),
        f'{dur:.1f}s vs planned {want_dur:.1f}s',
    )
    _chk(
        'no panel silently dropped',
        production.get('rendered', 1) >= production.get('planned', 0),
        f'{production.get("rendered")}/{production.get("planned")} panels rendered',
    )
    _chk(
        'narration on every written panel',
        production.get('narrated', 1) >= production.get('with_text', 0),
        f'{production.get("narrated")}/{production.get("with_text")} panels spoken',
    )
    _chk('at least 90 seconds', dur >= 90, f'{dur:.1f}s')
    _chk('3+ chapters for the playbar', len(chapters) >= 3, f'{len(chapters)}')
    mono = all(chapters[i]['at'] < chapters[i + 1]['at'] for i in range(len(chapters) - 1))
    _chk('chapters strictly ascending', mono)
    _chk('first chapter at 0:00', bool(chapters) and chapters[0]['at'] == 0)

    # audio is actually audible (a silent master is the classic silent failure)
    rms = _run([exe('ffmpeg'), '-hide_banner', '-i', path, '-af', 'volumedetect', '-f', 'null', '-'], timeout=600)
    mean_db = None
    m = re.search(r'mean_volume:\s*(-?[\d.]+) dB', rms.stderr or '')
    if m:
        mean_db = float(m.group(1))
    _chk(
        'narration audible',
        mean_db is not None and mean_db > -45.0,
        f'mean {mean_db} dB' if mean_db is not None else 'no reading',
    )

    # not a black episode
    bl = _run(
        [exe('ffmpeg'), '-hide_banner', '-i', path, '-vf', 'blackdetect=d=4:pic_th=0.98', '-an', '-f', 'null', '-'],
        timeout=900,
    )
    blacks = re.findall(r'black_duration:(\d+\.?\d*)', bl.stderr or '')
    worst = max([float(b) for b in blacks], default=0.0)
    _chk('no 4s+ black hole', worst < 4.0, f'longest black run {worst:.1f}s')
    return res
