# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""media — media section of pipeline_remixai (verbatim split).

Moved unchanged from pipeline_remixai.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import _AUDIO_ARGS, _duration, _env_f, _env_i, _log, _run, exe, os, random, re


# ── output geometry: MATCH THE SOURCE ───────────────────────────────────────


def output_geometry(src_info: dict) -> dict:
    """Mirror the source's shape. Operator decision 2026-08-29: a vertical short
    in gives a vertical short out, 16:9 long-form gives 16:9 — the format is part
    of what is working, so normalising everything to one canvas would discard it.

    Image sizes are the diffusion-friendly neighbours of each canvas (multiples of
    16, ~1 MP) rather than the delivery size; the Ken-Burns pass upscales 2× and
    crops back to canvas, so a 1 MP still is sharp at 1080p output."""
    a = float(src_info.get('aspect') or 0) or 16 / 9
    if a < 0.72:  # vertical short (9:16 ≈ 0.5625)
        return {'w': 1080, 'h': 1920, 'iw': 768, 'ih': 1360, 'label': 'vertical 9:16'}
    if a < 1.15:  # square-ish (1:1, 4:5)
        return {'w': 1080, 'h': 1080, 'iw': 1024, 'ih': 1024, 'label': 'square 1:1'}
    if a < 1.55:  # 4:3
        return {'w': 1440, 'h': 1080, 'iw': 1168, 'ih': 880, 'label': 'classic 4:3'}
    return {'w': 1920, 'h': 1080, 'iw': 1344, 'ih': 768, 'label': 'widescreen 16:9'}


def target_seconds(src_info: dict) -> float:
    """Match the source's duration, clamped. The floor keeps a 6-second source
    from producing something with no room for a script; the ceiling is a GPU
    budget — one still per beat, and a 20-minute source would ask for 60 of them."""
    d = float(src_info.get('duration') or 0)
    lo = _env_f('ZYG_REMIXAI_MIN_SEC', 20)
    hi = _env_f('ZYG_REMIXAI_MAX_SEC', 180)
    return max(lo, min(d or 45.0, hi))


# ── image generation ────────────────────────────────────────────────────────


def _model_family() -> str:
    """klein (FLUX.2 klein-4B) is the licence-clean commercial default: Apache-2.0
    for both render and train. qwen is the fallback. FLUX.1-dev is NOT reachable
    from here — the channel is monetised and dev is non-commercial."""
    return os.environ.get('ZYG_REMIXAI_MODEL_FAMILY', 'klein').strip() or 'klein'


def _gen_still(pid, prompt, dest, geo, log_stage='AI Image Generation'):
    try:
        from zyg_workflows import comfy_generation_service as cgs
    except Exception as e:
        _log(pid, 'ERROR', log_stage, f'comfy service unavailable: {e}')
        return False
    if not cgs.is_available():
        _log(pid, 'ERROR', log_stage, 'ComfyUI not available')
        return False
    fam = _model_family()
    seed = random.randint(0, 2**32 - 1)
    try:
        ok, backend = cgs.generate_still(
            dest,
            prompt,
            width=geo['iw'],
            height=geo['ih'],
            steps=_env_i('ZYG_REMIXAI_STEPS', 20),
            cfg=_env_f('ZYG_REMIXAI_CFG', 3.5),
            seed=seed,
            model_family=fam,
            human_subject=False,
            solo_subject=False,
            log_fn=lambda m: _log(pid, 'INFO', log_stage, m),
        )
    except Exception as e:
        _log(pid, 'WARNING', log_stage, f'generate_still raised: {e}')
        return False
    if ok and os.path.isfile(dest):
        _log(pid, 'INFO', log_stage, f'{os.path.basename(dest)} via {backend} ({geo["iw"]}×{geo["ih"]} seed={seed})')
        return True
    _log(pid, 'WARNING', log_stage, f'still failed ({backend})')
    return False


def _build_image_prompt(visual: str, style: dict, frame_hint: dict = None) -> str:
    """Beat visual + the fused style contract → one generation prompt.

    The style suffix is what makes the set cohere and what makes the output read
    as the same KIND of video as the source. `frame_hint` contributes the source
    frame's shot/lighting language for the nearest beat — treatment, never
    content."""
    bits = [(visual or '').strip()]
    if frame_hint:
        for k in ('shot', 'lighting'):
            v = (frame_hint.get(k) or '').strip()
            if v:
                bits.append(v)
    suffix = (style.get('style_suffix') or '').strip()
    if not suffix:
        suffix = ', '.join(
            x
            for x in [
                (style.get('aesthetic') or '').strip(),
                (style.get('palette') or '').strip(),
                (style.get('lighting') or '').strip(),
            ]
            if x
        )
    if suffix:
        bits.append(suffix)
    prompt = ', '.join(b for b in bits if b)
    return re.sub(r'\s+', ' ', prompt).strip()[:900]


# ── TTS ─────────────────────────────────────────────────────────────────────


def _tts_line(pid, text, wav_path):
    try:
        from zyg_workflows import tts_service as _tts

        def _lf(level, _stage, msg):
            _log(pid, level if level in ('INFO', 'WARNING', 'ERROR') else 'INFO', 'TTS Narration', msg)

        ok, _ = _tts._tts_shared(
            text, wav_path, 'TTS Narration', log_fn=_lf, voice_id=os.environ.get('ZYG_REMIXAI_VOICE', '')
        )
        return bool(ok) and os.path.isfile(wav_path) and os.path.getsize(wav_path) > 1000
    except Exception as e:
        _log(pid, 'WARNING', 'TTS Narration', f'TTS failed: {e}')
        return False


# ── Ken Burns ───────────────────────────────────────────────────────────────


def _ken_burns_segment(img, wav, out, geo, fps=30, min_seconds=2.0, lead_in=0.25, tail=0.35, direction=0):
    """One still + one narration wav → one uniformly-encoded clip for -c copy concat.

    zoompan runs on a 2×-upscaled still so the crop never softens the picture
    (briefing_video.py:1075 precedent). Zoom is capped at 1.08: past that the crop
    eats enough of every edge to clip anything composed near the frame border.
    `direction` alternates the drift so consecutive beats do not all push the same
    way, which reads as a mechanical slideshow."""
    a_dur = _duration(wav) if (wav and os.path.isfile(wav)) else 0.0
    total = max(min_seconds, a_dur + lead_in + tail)
    if total <= 0.3:
        return None, 0.0, 'segment shorter than 0.3s'
    W, H = geo['w'], geo['h']
    frames = max(2, int(total * fps))
    # four drift patterns, chosen by beat index
    xy = [
        ('iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)'),
        ('iw/2-(iw/zoom/2)+(on/{n})*(iw*0.04)'.format(n=frames), 'ih/2-(ih/zoom/2)'),
        ('iw/2-(iw/zoom/2)-(on/{n})*(iw*0.04)'.format(n=frames), 'ih/2-(ih/zoom/2)'),
        ('iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)+(on/{n})*(ih*0.04)'.format(n=frames)),
    ]
    x_expr, y_expr = xy[direction % len(xy)]
    vf = [
        f'scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase',
        f'crop={W * 2}:{H * 2}',
        f"zoompan=z='min(zoom+0.00035,1.08)':d={frames}:x='{x_expr}':y='{y_expr}':s={W}x{H}:fps={fps}",
        'setsar=1',
    ]
    cmd = [exe('ffmpeg'), '-y', '-hide_banner', '-loglevel', 'error', '-loop', '1', '-framerate', str(fps), '-i', img]
    if a_dur > 0:
        cmd += [
            '-i',
            wav,
            '-filter_complex',
            f'[1:a]aresample=48000,adelay={int(lead_in * 1000)}|{int(lead_in * 1000)},apad=whole_dur={total:.3f}[a]',
            '-map',
            '0:v',
            '-map',
            '[a]',
        ]
    else:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a']
    cmd += (
        [
            '-vf',
            ','.join(vf),
            '-t',
            f'{total:.3f}',
            '-r',
            str(fps),
            '-c:v',
            'libx264',
            '-preset',
            'medium',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
        ]
        + _AUDIO_ARGS
        + ['-movflags', '+faststart', out]
    )
    rc, _o, err = _run(cmd, timeout=max(300, int(total * 14)))
    if rc != 0 or not os.path.isfile(out):
        # Always report the RETURN CODE, not just stderr. A run killed mid-encode
        # (the service restarting under it, which happened twice on 2026-08-29)
        # exits with empty stderr, so the log read 'beat 5 segment failed:' with
        # nothing after the colon and looked like an ffmpeg bug worth chasing.
        # rc=-9/-15 says "something killed me" and rc=1 says "I failed"; those
        # need different responses and the message has to tell them apart.
        why = (err or '').strip()[-300:]
        if not why:
            why = f'rc={rc}, no stderr (killed?)' if rc < 0 or not os.path.isfile(out) else f'rc={rc}, no stderr'
        return None, 0.0, why
    return out, _duration(out), ''


def _concat(parts, out, work_dir):
    lst = os.path.join(work_dir, 'concat.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
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
            out,
        ],
        timeout=1200,
    )
    return rc == 0 and os.path.isfile(out), err[-300:] if err else ''


# ── subtitles ───────────────────────────────────────────────────────────────


def _srt_ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


_NUM_UNITS = {
    'zero': 0,
    'one': 1,
    'two': 2,
    'three': 3,
    'four': 4,
    'five': 5,
    'six': 6,
    'seven': 7,
    'eight': 8,
    'nine': 9,
    'ten': 10,
    'eleven': 11,
    'twelve': 12,
    'thirteen': 13,
    'fourteen': 14,
    'fifteen': 15,
    'sixteen': 16,
    'seventeen': 17,
    'eighteen': 18,
    'nineteen': 19,
}
_NUM_TENS = {
    'twenty': 20,
    'thirty': 30,
    'forty': 40,
    'fifty': 50,
    'sixty': 60,
    'seventy': 70,
    'eighty': 80,
    'ninety': 90,
}
_NUM_SCALES = {'hundred': 100, 'thousand': 1000, 'million': 1_000_000, 'billion': 1_000_000_000}
_NUM_ANY = set(_NUM_UNITS) | set(_NUM_TENS) | set(_NUM_SCALES)
_NUM_TOKEN_RE = re.compile(r'[A-Za-z]+(?:-[A-Za-z]+)*|[^A-Za-z]+')


def _compose_number_words(words) -> str:
    """Compose one run of number words into a single integer string.

    A word-by-word map cannot do this: 'five hundred ninety three' is 593, not
    '5 100 90 3'. Scale words MULTIPLY what is accumulated before them, so the
    run has to be folded rather than substituted term by term.

    A run of bare units with no tens and no scale word ('nine eleven') is read
    as a DIGIT SEQUENCE and left as separate numbers — that shape is someone
    reading digits aloud, not naming a quantity.
    """
    if not words:
        return ''
    if len(words) > 1 and all(w in _NUM_UNITS for w in words):
        return ' '.join(str(_NUM_UNITS[w]) for w in words)
    total, current = 0, 0
    for w in words:
        if w in _NUM_UNITS:
            current += _NUM_UNITS[w]
        elif w in _NUM_TENS:
            current += _NUM_TENS[w]
        elif w == 'hundred':
            current = (current or 1) * 100
        else:  # thousand / million / billion
            total += (current or 1) * _NUM_SCALES[w]
            current = 0
    return str(total + current)


def _subtitle_digits(text: str) -> str:
    """STANDING operator rule: subtitles use DIGITS ("593"). Converted in the
    SUBTITLE WRITER only — never in the TTS source, because the synthesiser reads
    spelled-out numerals correctly and bare digits inconsistently.

    'and' is absorbed only INSIDE a run ('two hundred and five'), never at its
    edges, so ordinary prose keeps its conjunction."""
    parts = _NUM_TOKEN_RE.findall(text or '')
    out, run, pending = [], [], []
    for tok in parts:
        low = tok.lower()
        # a hyphenated numeral ('twenty-three') is one token to the reader
        sub = low.split('-') if '-' in low else [low]
        if sub and all(x in _NUM_ANY for x in sub):
            run.extend(sub)
            pending = []
            continue
        if run and (low == 'and' or not low.strip()):
            pending.append(tok)  # might sit inside the run — decide later
            continue
        if run:
            out.append(_compose_number_words(run))
            run = []
        out.extend(pending)
        pending = []
        out.append(tok)
    if run:
        out.append(_compose_number_words(run))
    out.extend(pending)
    return ''.join(out)


def _sub_helpers():
    """The Abel scene's subtitle helpers, reused rather than reimplemented.

    Operator direction 2026-08-30: "make sure the subtitles are like those of
    abel scene, we build that good." They are genuinely better than what was
    here — `_sub_wrap` breaks at the highest SYNTACTIC boundary available
    (sentence end > clause end > before a conjunction) and only uses balance to
    settle ties, where this module was splitting a beat down the middle by word
    count; `_sub_split` keeps sentences whole and merges them back only while
    the merge still fits two lines. Importing beats copying: one implementation,
    one place to fix, and the two departments cannot drift apart.

    storyteller_scene_service imports clean (~0.5 s, no module-level threads).
    Falls back to the local versions if that ever stops being true."""
    try:
        from zyg_workflows import storyteller_scene_service as _S

        return _S._sub_digits, _S._sub_split, _S._sub_wrap, _S._SUB_MIN_S
    except Exception:
        return _subtitle_digits, (lambda t: [t]), (lambda t, **k: None), 0.9


def _write_srt(beats, path):
    """Beat timings → SRT, cued the way the Abel scene cues them.

    A beat is 1-3 spoken sentences, which is far too much for one cue: the first
    delivered episode put a whole beat on screen at once and measured FOUR
    rendered lines against the two-line broadcast working limit. So each beat is
    SPLIT into cue-sized chunks and its own span divided among them by character
    count — the same approach as the scene service, and for the same reason
    given there: the span's ends are already exact, so per-word alignment would
    buy nothing."""
    digits, split, wrap, min_s = _sub_helpers()
    cues = []
    for b in beats:
        txt = digits((b.get('text') or '').strip())
        dur = float(b.get('dur') or 0)
        if not txt or dur <= 0:
            continue
        t0 = float(b.get('start') or 0)
        t1 = t0 + dur
        chunks = [c for c in (split(txt) or [txt]) if c]
        total = sum(len(c) for c in chunks) or 1
        cur = t0
        for i, c in enumerate(chunks):
            end = t1 if i == len(chunks) - 1 else cur + (t1 - t0) * len(c) / total
            cues.append((cur, max(end, cur + min_s), c))
            cur = end
    if not cues:
        return None
    with open(path, 'w', encoding='utf-8') as f:
        for i, (a, b_, c) in enumerate(cues, 1):
            lines = wrap(c) or [c]
            f.write(f'{i}\n{_srt_ts(a)} --> {_srt_ts(b_)}\n' + '\n'.join(lines) + '\n\n')
    return path if os.path.getsize(path) > 0 else None


def _write_vtt(srt_path, vtt_path):
    """Sibling WebVTT — the inspection Videos tab mounts a <track> when one sits
    beside the mp4, which is what puts Captions in the player's menu."""
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            body = f.read().replace(',', '.')
        with open(vtt_path, 'w', encoding='utf-8') as f:
            f.write('WEBVTT\n\n' + body)
        return vtt_path
    except Exception:
        return None


# Subtitle burn style — TAKEN VERBATIM FROM THE ABEL SCENE (kanban_server
# _SUBBURN_STYLE), by operator direction 2026-08-30.
#
# WHY THESE ARE BARE NUMBERS AND NOT SCALED BY FRAME HEIGHT — the mistake this
# replaces. ffmpeg converts an SRT to an ASS script on a fixed PlayResY=288
# canvas and libass then scales that to the frame, so one style unit is H/288 px
# and every value here is ALREADY a percentage of frame height. The first version
# computed FontSize = height*0.030 and MarginV = height*0.06, which on 1080p came
# out as 32 and 64 — i.e. 32/288 = 11.1% of frame height for the type (against
# Abel's 6.6%) and 64/288 = 22.2% for the margin (against 5.2%). That is why the
# captions rendered oversized and sat a fifth of the way up the picture. Scaling
# by frame height double-applies a scale libass has already applied.
#
# Measured on the Abel scene (frame height 768): MarginV 28 -> 10.0% (SMPTE/EBU
# TITLE safe), 23 -> 8.3% (typical streaming), 14 -> 5.2% (SMPTE/EBU ACTION safe).
# 14 is the operator's pick — 28 read as too high there. Because the canvas is
# fixed, the same numbers land in the same RELATIVE place on any output geometry,
# so 9:16 / 1:1 / 4:3 / 16:9 all match without a per-aspect branch.
_SUB_STYLE_ABEL = (
    'FontName=DejaVu Sans,FontSize=19,PrimaryColour=&H00FFFFFF&,BorderStyle=1,Outline=0,Shadow=0,MarginV=14'
)


def _burn_subs(src, srt, out, geo):
    """Burn the SRT in the Abel scene's style. `geo` is unused for styling on
    purpose — see the note above; taking geometry into account here is precisely
    the bug this replaced."""
    style = os.environ.get('ZYG_REMIXAI_SUB_STYLE', '') or _SUB_STYLE_ABEL
    esc = srt.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
    rc, _o, err = _run(
        [
            exe('ffmpeg'),
            '-y',
            '-hide_banner',
            '-loglevel',
            'error',
            '-i',
            src,
            '-vf',
            f"subtitles='{esc}':force_style='{style}'",
            '-c:v',
            'libx264',
            '-preset',
            'medium',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
            '-c:a',
            'copy',
            '-movflags',
            '+faststart',
            out,
        ],
        timeout=1800,
    )
    return (rc == 0 and os.path.isfile(out)), (err[-300:] if err else '')
