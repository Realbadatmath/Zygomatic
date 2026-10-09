# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vocal_analysis.py — the singer, measured on his own track, line by line.

ACE-Step renders ONE mixed track: voice and band come out baked together. Until
2026-09-15 the only look at the voice was gate_singer_age — split the take with
demucs, read ONE median pitch, check it against the singer's band, throw the
split away (into /tmp, where 288 of them were still lying). A take whose median
passed could still sing whole lines an octave up (bumblebee 82b8bc806676: median
258 Hz, three 5-second stretches above 290 Hz), and nothing looked at level,
key, peaks or whether it was the voice that was cast.

This module measures the separated VOCAL STEM against the plan it came from:

  lines     each lyric line's window from the plan (melody notes carry `line`;
            beats -> seconds at the plan's bpm; ACE-Step holds tempo, measured
            lag ~0.1 s), with its text
  register  per line: F0 median, p95 peak, share of voiced time above the
            singer's band ceiling
  key       per line: share of STABLE sung frames whose pitch class is in the
            song's scale, and median |cents| off the nearest semitone
  level     per line: vocal vs backing dB from the two stems; stem sample peak
  identity  TitaNet-large voice embedding of the voiced audio vs the singer's
            reference take, placed against a null of other voices
            (tools/voice_embed_worker.py in the NeMo venv)

Nothing here renders, re-mixes or decides a take; the decisions and fixes live
in kids_music_service.run(). Every threshold used there comes from
tools/voice_analysis_calibrate.py and is quoted where it is defined.
"""

import json
import os
import subprocess
import tempfile

import numpy as np
from zyg_workflows.bin import exe

HERE = os.path.dirname(os.path.abspath(__file__))
EMBED_PY = os.environ.get('ZYG_VOICE_EMBED_PY') or os.path.abspath(
    os.path.join(HERE, '..', '..', 'models', 'diarization', '.venv', 'bin', 'python')
)
EMBED_WORKER = os.path.join(HERE, 'tools', 'voice_embed_worker.py')

HOP_S = 0.01  # RMVPE frame hop
STABLE_CENTS = 40.0  # a frame is part of a held note if its neighbours stay within this
STABLE_RUN = 5  # ... over this many frames (50 ms)


def _log_noop(_m):
    pass


def db(x):
    return float(20.0 * np.log10(max(float(x), 1e-9)))


# ── stems ────────────────────────────────────────────────────────────────────


def separate(take, stems_dir, *, log_fn=None):
    """demucs two-stem split of `take` into `stems_dir` (vocals.wav, no_vocals.wav)."""
    from zyg_workflows import kids_music_service as K  # lazy: K imports this module

    os.makedirs(stems_dir, exist_ok=True)
    return K.separate_vocal(take, stems_dir, log_fn=log_fn)


def _load_mono(path, sr):
    import librosa

    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y.astype(np.float32)


# ── pitch ────────────────────────────────────────────────────────────────────


def pitch_track(vocals_wav):
    """RMVPE over the stem: arrays t (s), f0 (Hz), conf, voiced (bool)."""
    from zyg_workflows import sung_pitch as SP

    y16 = _load_mono(vocals_wav, SP.RMVPE_SR)
    t, f0, conf, _act = SP._rmvpe('cpu').predict(y16, SP.RMVPE_SR)
    t, f0, conf = (np.asarray(x, dtype=float) for x in (t, f0, conf))
    voiced = (conf >= SP.CONF_MIN) & (f0 >= 70.0) & (f0 <= 1400.0)
    return {'t': t, 'f0': f0, 'conf': conf, 'voiced': voiced, 'seconds': float(len(y16) / SP.RMVPE_SR)}


def _cents(f0):
    return 1200.0 * np.log2(np.maximum(f0, 1e-6) / 440.0) + 6900.0  # MIDI x 100


def stable_mask(track):
    """Frames inside a held note: voiced, and every neighbour within ±STABLE_RUN//2
    frames stays inside STABLE_CENTS. Glides, scoops and vibrato peaks are out."""
    v = track['voiced']
    c = _cents(track['f0'])
    half = STABLE_RUN // 2
    ok = np.zeros_like(v)
    for i in range(half, len(c) - half):
        if v[i - half : i + half + 1].all():
            seg = c[i - half : i + half + 1]
            ok[i] = (seg.max() - seg.min()) <= STABLE_CENTS
    return ok


# ── the plan's lines ─────────────────────────────────────────────────────────


def line_windows(plan):
    """[{line, text, start_s, end_s}] from the plan's melody notes."""
    bpm = float(plan.get('bpm') or 120.0)
    spb = 60.0 / bpm
    spans = {}
    for n in plan.get('melody') or []:
        li = n.get('line')
        if li is None:
            continue
        s, e = float(n['t']), float(n['t']) + float(n['d'])
        lo, hi = spans.get(li, (s, e))
        spans[li] = (min(lo, s), max(hi, e))
    texts = plan.get('lyrics') if isinstance(plan.get('lyrics'), list) else []
    out = []
    for li in sorted(spans):
        s, e = spans[li]
        out.append(
            {
                'line': int(li),
                'text': texts[li] if li < len(texts) else '',
                'start_s': round(s * spb, 2),
                'end_s': round(e * spb, 2),
            }
        )
    return out


ASR_PY = os.environ.get('ZYG_LYRIC_ASR_PY') or os.path.abspath(os.path.join(HERE, '..', '.venv', 'bin', 'python'))
ASR_WORKER = os.path.join(HERE, 'tools', 'lyric_align_worker.py')
LINE_SUNG_COVERAGE = 0.6  # share of a line's words heard, in order, for it to count as sung
# THE PROMPTED DECODE CANNOT JUDGE INTELLIGIBILITY (2026-10-02, 8 songs / 206 lines).
# The decode that places lines is prompted with the song's own lyrics, and a prompted
# Whisper reproduces the sheet off audio a listener cannot make out. Measured, one
# recogniser, identical chunk boundaries, only the source and the prompt varied:
#
#   stem + prompt (what this module used to report)   95.8 % line coverage
#   stem, bare                                        66.9 %
#   MIX, bare                                         73.6 %   <- what a listener gets
#   mix + prompt                                      95.3 %
#
# The prompt is worth ~+22 points; stem-vs-mix is worth -7 (the demucs stem is WORSE
# than the mix, so the honest read is taken on the TAKE, not on the stem). Of the 197
# lines the prompted decode passed, 33 (17 %) fell under 60 % bare and 5 were not heard
# at all — df012ec48502's hook "We love our little brown dog" repeats 5x, scored 5/5
# prompted, and was heard 0/5 bare. The old muted-line calibration ("4/4 caught, 0
# false") is not evidence against this: digital silence gives a prompt nothing to hang
# on, while a line sung as mush does. A prompted recogniser must be validated against a
# BARE decode, never against silence.
# Same 0.6 bar as LINE_SUNG_COVERAGE, deliberately: a line whose words cannot be
# recovered without handing over the answer sheet is not a line a child can sing along to.
LINE_CLEAR_COVERAGE = 0.6  # share of a line's words heard with NO lyric prompt, on the mix


def phrase_chunks(track, *, max_s=12.0, min_gap_s=0.35, pad_s=0.25):
    """The stem cut at silences into phrases of <= max_s, for the recogniser.
    Gaps shorter than min_gap_s do not split; runs longer than max_s are cut."""
    v, t = track['voiced'], track['t']
    gap = max(1, int(min_gap_s / HOP_S))
    runs, i, n = [], 0, len(v)
    while i < n:
        if not v[i]:
            i += 1
            continue
        j = i
        while j < n and (v[j] or v[j : j + gap].any()):
            j += 1
        runs.append([max(0.0, float(t[i]) - pad_s), float(t[min(j, n - 1)]) + pad_s])
        i = j
    out = []
    for s, e in runs:
        while e - s > max_s:
            out.append([round(s, 2), round(s + max_s, 2)])
            s += max_s
        if out and s - out[-1][1] < 0.5 and e - out[-1][0] <= max_s:
            out[-1][1] = round(e, 2)
        else:
            out.append([round(s, 2), round(e, 2)])
    return out


BARE_ASR = os.environ.get('ZYG_KIDSMUSIC_BARE_ASR', '1') not in ('0', 'false', 'no')


def _mix_for_asr(take, work_dir, *, log_fn=None):
    """The take decoded to 16 kHz mono WAV for the bare decode, or None.

    The worker reads with soundfile, which will not open every mp3 the pipeline
    produces, so the mix is handed over as a WAV rather than by path. Returns
    None on any failure: a bare decode that could not run is reported as
    unmeasured (`clear: None`), never as clear.
    """
    log_fn = log_fn or _log_noop
    try:
        os.makedirs(work_dir, exist_ok=True)
        dst = os.path.join(work_dir, '_mix_asr.wav')
        r = subprocess.run(
            [exe('ffmpeg'), '-v', 'error', '-y', '-i', take, '-ac', '1', '-ar', '16000', dst],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) < 1000:
            log_fn(f'voice: could not decode the mix for the bare pass ({r.stderr[-120:]})')
            return None
        return dst
    except (subprocess.SubprocessError, OSError) as e:
        log_fn(f'voice: could not decode the mix for the bare pass ({type(e).__name__})')
        return None


def lyric_prompt(plan):
    return ' '.join(str(x) for x in (plan.get('lyrics') or []) if x)


def transcribe(vocals, *, log_fn=None, timeout_s=900):
    """Whisper on the vocal stem(s), phrase by phrase, prompted with the lyrics.

    `vocals` is {id: {'wav', 'chunks', 'prompt'}} (batch) or one such dict.
    Returns {id: words} / words; {} / None when the recogniser could not run — a
    lyric check that did not run is reported as unmeasured, never as 'all lines
    sung'. Why chunked and prompted: tools/lyric_align_worker.py docstring."""
    log_fn = log_fn or _log_noop
    batch = 'wav' not in vocals
    if not (os.path.isfile(ASR_PY) and os.path.isfile(ASR_WORKER)):
        log_fn('voice: lyric recogniser missing — lyrics unmeasured')
        return {} if batch else None
    items = vocals if batch else {'_': vocals}
    with tempfile.TemporaryDirectory(prefix='lyricasr_') as tmp:
        dst = os.path.join(tmp, 'out.json')
        src = os.path.join(tmp, 'in.json')
        with open(src, 'w') as fh:
            json.dump({'items': [dict(v, id=k) for k, v in items.items()]}, fh)
        try:
            subprocess.run(
                [ASR_PY, ASR_WORKER, src, dst],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=dict(os.environ, HF_HUB_OFFLINE='1'),
            )
            res = json.load(open(dst))
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            log_fn(f'voice: lyric recogniser failed ({type(e).__name__})')
            return {} if batch else None
    got = {k: r['words'] for k, r in (res.get('results') or {}).items() if r.get('ok')}
    return got if batch else got.get('_')


def _norm_word(w):
    return ''.join(ch for ch in w.lower() if ch.isalnum() or ch == "'").strip("'")


def align_lines(plan, words):
    """Which planned lines were sung, where, and how completely.

    Global word alignment (match +2 scaled by spelling similarity, mismatch -1,
    gap -1; leading/trailing sung words free) between the plan's lyric words
    and Whisper's words. Returns one row per planned line:
    {line, text, coverage, sung, start_s, end_s, heard}. `extra_words` counts
    sung words matched to no planned word (a repeated refrain, garbling)."""
    from difflib import SequenceMatcher

    texts = plan.get('lyrics') if isinstance(plan.get('lyrics'), list) else []
    P = [(li, _norm_word(w)) for li, line in enumerate(texts) for w in str(line).split()]
    P = [(li, w) for li, w in P if w]
    S = [dict(x, n=_norm_word(x['w'])) for x in (words or [])]
    S = [x for x in S if x['n']]
    n, m = len(P), len(S)
    rows = [
        {'line': li, 'text': t, 'coverage': 0.0, 'sung': False, 'start_s': None, 'end_s': None, 'heard': ''}
        for li, t in enumerate(texts)
    ]
    if not n or not m:
        return {'lines': rows, 'extra_words': m, 'aligned': bool(m)}

    def sim(a, b):
        return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()

    NEG = -1e9
    score = np.full((n + 1, m + 1), NEG)
    back = np.zeros((n + 1, m + 1), dtype=np.int8)  # 1 diag, 2 up (skip plan), 3 left (skip sung)
    score[0, :] = 0.0  # free leading sung words
    for i in range(1, n + 1):
        score[i, 0] = score[i - 1, 0] - 1.0
        back[i, 0] = 2
    for i in range(1, n + 1):
        pw = P[i - 1][1]
        for j in range(1, m + 1):
            s = sim(pw, S[j - 1]['n'])
            d = score[i - 1, j - 1] + (2.0 * s if s >= 0.75 else -1.0)
            u = score[i - 1, j] - 1.0
            l_ = score[i, j - 1] - (0.0 if i == n else 1.0)  # free trailing sung words
            best = max(d, u, l_)
            score[i, j] = best
            back[i, j] = 1 if best == d else (2 if best == u else 3)
    i, j = n, int(np.argmax(score[n, :]))
    pairs = []
    while i > 0 and j > 0:
        b = back[i, j]
        if b == 1:
            if sim(P[i - 1][1], S[j - 1]['n']) >= 0.75:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif b == 2:
            i -= 1
        else:
            j -= 1
    matched_s = {pj for _pi, pj in pairs}
    per_line = {}
    for pi, sj in pairs:
        per_line.setdefault(P[pi][0], []).append(sj)
    for li, row in enumerate(rows):
        total = sum(1 for x in P if x[0] == li)
        got = sorted(per_line.get(li, []))
        row['coverage'] = round(len(got) / total, 2) if total else 0.0
        row['sung'] = row['coverage'] >= LINE_SUNG_COVERAGE
        if got:
            row['start_s'] = S[got[0]]['start']
            row['end_s'] = S[got[-1]]['end']
            row['heard'] = ' '.join(S[k]['w'] for k in range(got[0], got[-1] + 1))
    return {'lines': rows, 'extra_words': m - len(matched_s), 'aligned': True}


def scale_pcs(plan):
    from zyg_workflows import kids_music_theory as T

    key = plan.get('key') or {}
    mode = key.get('mode') or 'major'
    parent = T.PARENT_OF.get(mode, mode)
    steps = (T.MODES.get(parent) or T.MODES['major'])['steps']
    tonic = int(key.get('tonic_pc') or 0)
    return sorted({(tonic + s) % 12 for s in steps})


# ── level ────────────────────────────────────────────────────────────────────


def _rms_db(y):
    return db(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) if y.size else -180.0


# ── the report ───────────────────────────────────────────────────────────────


def measure(vocals_wav, rest_wav, plan, singer, *, track=None, words=None, words_bare=None):
    """Everything except identity, on an existing pair of stems.

    `singer` is a kids_music_theory.SINGERS entry; its `band` sets the register
    ceiling. `words` (from transcribe) places each line where it was actually
    sung; without them the plan's own line windows are used and every line is
    marked `aligned: False` — ACE-Step does not hold the plan's timing (the
    bumblebee take started its first line 3.3 s after the plan said).

    `words_bare` is the UNPROMPTED decode of the mix (see LINE_CLEAR_COVERAGE).
    It never moves a line — placement stays with the prompted decode, which is
    the better aligner — it only answers whether the line can be made out. Each
    line gains `coverage_bare`/`heard_bare`/`clear`; `clear` is None when the
    bare decode did not run, so an unmeasured line is never reported as clear.

    Returns {'lines': [...], 'lyrics': {...}, 'lyrics_bare': {...},
    'register': {...}, 'key': {...}, 'level': {...}, 'track': <not JSON>}.
    """
    SR = 44100
    track = track or pitch_track(vocals_wav)
    t, f0, v = track['t'], track['f0'], track['voiced']
    stab = stable_mask(track)
    lo, hi = singer.get('band') or (80.0, 1400.0)
    ceiling = singer.get('line_ceiling_hz') or hi
    pcs = set(scale_pcs(plan))
    cents = _cents(f0)
    voc = _load_mono(vocals_wav, SR)
    rest = _load_mono(rest_wav, SR) if rest_wav and os.path.isfile(rest_wav) else None

    def span_stats(s, e):
        m = (t >= s) & (t < e)
        fv = f0[m & v]
        st = m & stab
        row = {'voiced_s': round(float((m & v).sum()) * HOP_S, 2)}
        if fv.size >= 10:
            row.update(
                {
                    'f0_median_hz': round(float(np.median(fv)), 1),
                    'f0_p95_hz': round(float(np.percentile(fv, 95)), 1),
                    'above_band_share': round(float((fv > hi).mean()), 3),
                    'above_ceiling_share': round(float((fv > ceiling).mean()), 3),
                }
            )
        else:
            row.update({'f0_median_hz': None, 'f0_p95_hz': None, 'above_band_share': None, 'above_ceiling_share': None})
        if st.sum() >= 10:
            near = np.round(cents[st] / 100.0)
            row['in_key_share'] = round(float(np.mean([(int(n) % 12) in pcs for n in near])), 3)
            row['intonation_cents'] = round(float(np.median(np.abs(cents[st] - near * 100.0))), 1)
        else:
            row['in_key_share'], row['intonation_cents'] = None, None
        a, b = int(s * SR), int(e * SR)
        vseg = voc[a:b]
        row['vocal_db'] = round(_rms_db(vseg), 1)
        if rest is not None:
            row['backing_db'] = round(_rms_db(rest[a:b]), 1)
            row['vocal_over_backing_db'] = round(row['vocal_db'] - row['backing_db'], 1)
        return row

    lines = []
    planned = {w['line']: w for w in line_windows(plan)}
    al = align_lines(plan, words) if words is not None else None
    # The bare decode is aligned on its own, then joined to the prompted rows by
    # line number. It contributes no timing: a bare decode that missed the line
    # entirely has no span to offer, and the prompted decode places lines better.
    alb = align_lines(plan, words_bare) if words_bare is not None else None
    bare = {r['line']: r for r in alb['lines']} if alb else {}
    if al:
        for r in al['lines']:
            row = {
                'line': r['line'],
                'text': r['text'],
                'aligned': True,
                'sung': r['sung'],
                'coverage': r['coverage'],
                'heard': r['heard'],
                'start_s': r['start_s'],
                'end_s': r['end_s'],
            }
            if alb:
                b = bare.get(r['line']) or {}
                cb = float(b.get('coverage') or 0.0)
                row.update(
                    {
                        'coverage_bare': round(cb, 2),
                        'heard_bare': b.get('heard') or '',
                        'clear': cb >= LINE_CLEAR_COVERAGE,
                    }
                )
            else:
                row.update({'coverage_bare': None, 'heard_bare': '', 'clear': None})
            if r['sung'] and r['start_s'] is not None:
                row.update(span_stats(r['start_s'], r['end_s']))
            lines.append(row)
        lyr = {
            'measured': True,
            'lines': len(al['lines']),
            'sung': sum(1 for r in al['lines'] if r['sung']),
            'missing': [r['line'] for r in al['lines'] if not r['sung']],
            'extra_words': al['extra_words'],
        }
    else:
        for _li, w in planned.items():
            lines.append(
                dict(w, aligned=False, sung=None, coverage=None, heard='', **span_stats(w['start_s'], w['end_s']))
            )
        lyr = {'measured': False}

    fv = f0[v]
    st_all = stab
    reg = {
        'band_hz': [lo, hi],
        'f0_median_hz': round(float(np.median(fv)), 1) if fv.size else None,
        'f0_p95_hz': round(float(np.percentile(fv, 95)), 1) if fv.size else None,
        'above_band_share': round(float((fv > hi).mean()), 3) if fv.size else None,
        'voiced_s': round(float(v.sum()) * HOP_S, 2),
    }
    if st_all.sum() >= 10:
        near = np.round(cents[st_all] / 100.0)
        key = {
            'scale_pcs': sorted(pcs),
            'in_key_share': round(float(np.mean([(int(n) % 12) in pcs for n in near])), 3),
            'intonation_cents': round(float(np.median(np.abs(cents[st_all] - near * 100.0))), 1),
        }
    else:
        key = {'scale_pcs': sorted(pcs), 'in_key_share': None, 'intonation_cents': None}
    level = {
        'vocal_db': round(_rms_db(voc), 1),
        'stem_peak_dbfs': round(db(float(np.abs(voc).max()) if voc.size else 0.0), 2),
    }
    if rest is not None:
        level['backing_db'] = round(_rms_db(rest), 1)
        level['vocal_over_backing_db'] = round(level['vocal_db'] - level['backing_db'], 1)
    if alb:
        clear_n = sum(1 for ln in lines if ln.get('clear'))
        # 'unclear' is the false-pass set: placed and scored sung by the prompted
        # decode, yet under the bar without the prompt. Those are the lines that
        # used to ship silently.
        lyr_bare = {
            'measured': True,
            'lines': len(lines),
            'clear': clear_n,
            'unclear': [ln['line'] for ln in lines if ln.get('sung') and ln.get('clear') is False],
            'extra_words': alb['extra_words'],
            'coverage_mean': round(float(np.mean([ln.get('coverage_bare') or 0.0 for ln in lines])), 3)
            if lines
            else None,
        }
    else:
        lyr_bare = {'measured': False}
    return {
        'lines': lines,
        'lyrics': lyr,
        'lyrics_bare': lyr_bare,
        'register': reg,
        'key': key,
        'level': level,
        'track': track,
    }


# ── identity ─────────────────────────────────────────────────────────────────


def voiced_clip(vocals_wav, dst, *, track=None, start_s=None, end_s=None):
    """16 kHz mono file of only the voiced frames (10 ms fades), for embedding."""
    import soundfile as sf
    from zyg_workflows import sung_pitch as SP

    sr = SP.RMVPE_SR
    track = track or pitch_track(vocals_wav)
    y = _load_mono(vocals_wav, sr)
    hop = int(HOP_S * sr)
    keep = track['voiced'].copy()
    if start_s is not None:
        keep &= track['t'] >= start_s
    if end_s is not None:
        keep &= track['t'] < end_s
    parts, i = [], 0
    n = len(keep)
    fade = np.linspace(0.0, 1.0, hop, dtype=np.float32)
    while i < n:
        if not keep[i]:
            i += 1
            continue
        j = i
        while j < n and keep[j]:
            j += 1
        seg = y[i * hop : j * hop].copy()
        if seg.size > 2 * hop:
            seg[:hop] *= fade
            seg[-hop:] *= fade[::-1]
            parts.append(seg)
        i = j
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    sf.write(dst, audio, sr, subtype='PCM_16')
    return {'path': dst, 'seconds': round(len(audio) / sr, 2)}


def embed(clips, *, log_fn=None, timeout_s=600):
    """{id: wav} -> {id: unit vector (np.ndarray)} via the NeMo worker."""
    log_fn = log_fn or _log_noop
    if not (os.path.isfile(EMBED_PY) and os.path.isfile(EMBED_WORKER)):
        log_fn('voice: embedding venv or worker missing — identity unmeasured')
        return {}
    with tempfile.TemporaryDirectory(prefix='voiceembed_') as tmp:
        src, dst = os.path.join(tmp, 'in.json'), os.path.join(tmp, 'out.json')
        with open(src, 'w') as fh:
            json.dump({'items': [{'id': k, 'wav': w} for k, w in clips.items()]}, fh)
        env = dict(os.environ, HF_HUB_OFFLINE='1')
        try:
            subprocess.run(
                [EMBED_PY, EMBED_WORKER, src, dst], capture_output=True, text=True, timeout=timeout_s, env=env
            )
            res = json.load(open(dst))
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            log_fn(f'voice: embedding failed ({type(e).__name__}) — identity unmeasured')
            return {}
    if res.get('errors'):
        log_fn(f'voice: {len(res["errors"])} clip(s) could not be embedded')
    return {k: np.asarray(v, dtype=float) for k, v in (res.get('embeddings') or {}).items()}


def cosine(a, b):
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


# ── decisions: what counts as a problem ──────────────────────────────────────
#
# Every threshold below was read off tools/voice_analysis_calibrate.py
# (output/kidsmusic/_voice_build/calibration.json, 112 takes, 2026-09-15):
#
#   line register   lines of takes that passed as male: median 218 Hz, p90 281;
#                   lines of takes that sang high: median 373, p10 330. The
#                   ceiling sits in the gap -> SINGERS[*]['line_ceiling_hz'].
#                   A line is flagged by the SHARE of its voiced time above the
#                   ceiling, not its median. Pass 1 (plan windows): male-take
#                   lines p50 2 % / p90 48 %, high-take lines p10 66 % / p50 97 %.
#                   Pass 2 (lines placed by Whisper, 132 takes): male-take lines
#                   p50 2 % / p90 59 %, high-take lines p10 43 % / p50 95 %. The
#                   labels are per TAKE, not per line — a take that passed as
#                   male can hold genuinely high lines (bumblebee L9/L11,
#                   confirmed by two trackers) — so the overlap is expected and
#                   0.5 stays. The median was tried first
#                   and is unstable on a line that jumps the octave half way —
#                   bumblebee line 9 read 221 or 439 Hz depending on a 0.2 s
#                   shift of its window, while RMVPE and SwiftF0 agreed its
#                   share above 300 Hz was 41-49 %.
LINE_HIGH_SHARE = 0.5
#   key             in-key share of held notes 0.94 (p10 0.84) in the true key vs
#                   0.33 (p90 0.48) scored a semitone off -> below 0.80 is off-key.
#   level           sung-line vocal-over-backing median -2.2 dB, p10 -6.9, p90
#                   +2.8 -> a take whose median line sits outside -6..+3 dB is
#                   rebalanced from the stems toward -2 dB.
#   lyrics          a planned line is missing when fewer than 60 % of its words
#                   are heard in order (the muted-line test: 4/4 caught, 0 false).
#                   Words aligned against ANOTHER song's lyrics: 0 % sung on 119
#                   takes; no-vocal takes: 3.5 %. ACE-Step skips or garbles lines
#                   on most takes (106/119 had at least one; median 67 % sung) —
#                   an unintelligible line counts as missing, which for a
#                   children's song it is.
#   identity        NOT a gate. TitaNet-large on the vocal stems: same take
#                   halves 0.69, male vs female 0.27 — but the same caption across
#                   songs 0.45-0.46 vs a different caption across songs 0.39, and
#                   different captions on ONE song 0.49: the song outweighs the
#                   voice, and the paired test (stock vs m05/m06/m08 on the same
#                   song) went 1 of 3.
KEY_MIN_IN_KEY = 0.80
LEVEL_TARGET_DB = -2.0
LEVEL_LOW_DB = -6.0
LEVEL_HIGH_DB = 3.0
LEVEL_MAX_GAIN_DB = 4.0


def problems(report, singer):
    """[{kind, line?, start_s?, end_s?, detail, fix}] from a measure() report.

    kinds: no_vocal, register (whole take), line_high, line_missing, off_key,
    level. `fix` names what run() may do about it: 'rerender', 'repaint' or
    'remix'."""
    out = []
    reg = report.get('register') or {}
    lo, hi = reg.get('band_hz') or (None, None)
    if not reg.get('voiced_s'):
        out.append({'kind': 'no_vocal', 'detail': 'no singing found on the vocal stem', 'fix': 'rerender'})
        return out
    med = reg.get('f0_median_hz')
    if med is not None and lo is not None and not (lo <= med <= hi):
        out.append(
            {'kind': 'register', 'detail': f'take median {med:.0f} Hz outside {lo:.0f}-{hi:.0f} Hz', 'fix': 'rerender'}
        )
    ceiling = singer.get('line_ceiling_hz')
    lines_all = report.get('lines') or []
    last_line = max((ln['line'] for ln in lines_all), default=None)
    seconds = report.get('seconds')
    for ln in lines_all:
        if (
            ln.get('sung') is False
            and ln['line'] == last_line
            and seconds
            and (ln.get('coverage') or 0) >= 0.3
            and ln.get('end_s') is not None
            and ln['end_s'] >= seconds - 2.0
        ):
            # The song ENDS inside its last line (bumblebee: "He buzzes and
            # visits..." at 55.7 s of 57.4). No repaint can add time — two tries
            # on the trial take left it at 57 % — so it is reported, not repaired.
            out.append(
                {
                    'kind': 'line_cut',
                    'line': ln['line'],
                    'text': ln.get('text', ''),
                    'detail': f'line {ln["line"] + 1} cut off by the end of the song '
                    f'({int(round((ln.get("coverage") or 0) * 100))}% sung)',
                    'fix': 'none',
                }
            )
        elif ln.get('sung') is False:
            out.append(
                {
                    'kind': 'line_missing',
                    'line': ln['line'],
                    'text': ln.get('text', ''),
                    'detail': f'line {ln["line"] + 1} not sung '
                    f'({int(round((ln.get("coverage") or 0) * 100))}% of its words heard)',
                    'fix': 'repaint',
                }
            )
        elif (
            ceiling
            and ln.get('sung')
            and ln.get('above_ceiling_share') is not None
            and ln['above_ceiling_share'] >= LINE_HIGH_SHARE
        ):
            out.append(
                {
                    'kind': 'line_high',
                    'line': ln['line'],
                    'text': ln.get('text', ''),
                    'start_s': ln.get('start_s'),
                    'end_s': ln.get('end_s'),
                    'detail': f'line {ln["line"] + 1} sung too high — '
                    f'{ln["above_ceiling_share"]:.0%} of it above {ceiling:.0f} Hz',
                    'fix': 'repaint',
                }
            )
        elif ln.get('sung') and ln.get('clear') is False:
            # Sung, placed, in range — and still not recoverable without the
            # lyric sheet. Repainted over its own span, like line_high.
            out.append(
                {
                    'kind': 'line_unclear',
                    'line': ln['line'],
                    'text': ln.get('text', ''),
                    'start_s': ln.get('start_s'),
                    'end_s': ln.get('end_s'),
                    'detail': f'line {ln["line"] + 1} cannot be made out — '
                    f'{int(round((ln.get("coverage_bare") or 0) * 100))}% of its '
                    f'words heard with no lyric prompt'
                    + (f' (heard "{ln["heard_bare"]}")' if ln.get('heard_bare') else ''),
                    'fix': 'repaint',
                }
            )
    k = (report.get('key') or {}).get('in_key_share')
    if k is not None and k < KEY_MIN_IN_KEY:
        out.append(
            {
                'kind': 'off_key',
                'detail': f'{k:.0%} of held notes in key (below {KEY_MIN_IN_KEY:.0%})',
                'fix': 'rerender',
            }
        )
    ratios = [
        ln['vocal_over_backing_db']
        for ln in report.get('lines') or []
        if ln.get('sung') and ln.get('vocal_over_backing_db') is not None
    ]
    if ratios:
        mr = float(np.median(ratios))
        if mr < LEVEL_LOW_DB or mr > LEVEL_HIGH_DB:
            out.append(
                {
                    'kind': 'level',
                    'detail': f'voice sits {mr:+.1f} dB against the band '
                    f'(normal {LEVEL_LOW_DB:+.0f} to {LEVEL_HIGH_DB:+.0f})',
                    'gain_db': round(max(-LEVEL_MAX_GAIN_DB, min(LEVEL_MAX_GAIN_DB, LEVEL_TARGET_DB - mr)), 1),
                    'fix': 'remix',
                }
            )
    return out


def severity(probs):
    """One number to compare takes and repairs by: lower is better."""
    # line_unclear sits just under line_missing: the words are there but cannot be
    # made out, which for a sing-along is nearly as bad as not singing them at all.
    w = {
        'no_vocal': 100,
        'register': 50,
        'off_key': 30,
        'line_missing': 6,
        'line_unclear': 5,
        'line_high': 4,
        'line_cut': 2,
        'level': 1,
    }
    return sum(w.get(p['kind'], 1) for p in probs)


def repair_windows(report, probs, *, min_s=1.5, pad_s=0.2, seconds=None):
    """Where to repaint, one window per fixable line problem (merged if they touch).

    A sung-too-high line is repainted over its own sung span. A missing line has
    no span of its own: its window runs from the end of the last reliably placed
    line before it to the start of the first reliably placed line after it. A
    placed line whose words span more than 1.5x its planned duration swallowed
    a gap (the bumblebee's refrain matched across a skipped line), so only its
    far edge is trusted and the near edge is estimated from the planned length.
    """
    lines = {ln['line']: ln for ln in report.get('lines') or []}
    planned = {w['line']: w['end_s'] - w['start_s'] for w in report.get('planned_windows') or []}
    planned_start = {w['line']: w['start_s'] for w in report.get('planned_windows') or []}

    def edges(ln):
        s, e = ln.get('start_s'), ln.get('end_s')
        if s is None or e is None:
            return None, None
        dur = planned.get(ln['line'])
        if dur and (e - s) > 1.5 * dur:
            return e - dur, s + dur  # (trusted start if seen from after, end if seen from before)
        return s, e

    wins = []
    for p in probs:
        if p['kind'] in ('line_high', 'line_unclear') and p.get('start_s') is not None:
            wins.append([p['start_s'] - pad_s, p['end_s'] + pad_s, [p['line']]])
        elif p['kind'] == 'line_missing':
            li = p['line']
            prev = next((lines[j] for j in range(li - 1, -1, -1) if lines.get(j, {}).get('sung')), None)
            nxt = next((lines[j] for j in range(li + 1, max(lines) + 1) if lines.get(j, {}).get('sung')), None)
            # Nothing sung before it: start where the plan put the line, not at
            # 0 s — the intro in front of the first line is the band's, and a
            # repaint from 0 s would re-generate it.
            s = edges(prev)[1] if prev else planned_start.get(li, 0.0)
            e = edges(nxt)[0] if nxt else (seconds or s + (planned.get(li) or 4.0))
            if s is None or e is None:
                continue
            wins.append([s - pad_s, e + pad_s, [li]])
    wins = [w for w in wins if w[1] - w[0] >= min_s]
    wins.sort()
    merged = []
    for w in wins:
        if merged and w[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], w[1])
            merged[-1][2] += w[2]
        else:
            merged.append(w)
    if seconds:
        merged = [
            [max(0.5, s), min(seconds - 0.5, e), ls]
            for s, e, ls in merged
            if min(seconds - 0.5, e) - max(0.5, s) >= min_s
        ]
    return [{'start_s': round(s, 2), 'end_s': round(e, 2), 'lines': sorted(set(ls))} for s, e, ls in merged]


def review(take, plan, singer, work_dir, *, sep=None, log_fn=None, bare_take=None):
    """The whole look at one take: stems, lyrics, per-line measures, problems.

    `sep` is a separate_vocal() result when the caller already split the take
    (gate_singer_age does, into work_dir/stems). Returns a JSON-safe report
    with 'problems', 'severity' and 'stems' paths; identity is not part of it
    (see identity_note in the calibration).

    `bare_take` is the audio the UNPROMPTED pass listens to, when that is not
    `take` itself. The voice-conversion check needs it: there `sep` carries a
    CONVERTED vocal while `take` is still the unconverted mix, so a bare decode
    of `take` would grade the wrong audio and miss exactly the damage the check
    exists to catch (RVC cost 8.6 points of coverage over 16 songs, worse on 13)."""
    log_fn = log_fn or _log_noop
    rep = {'take': os.path.basename(take), 'ok': False, 'error': ''}
    try:
        if not (sep and sep.get('ok') and os.path.isfile(sep.get('vocals') or '')):
            sep = separate(take, os.path.join(work_dir, 'stems'), log_fn=log_fn)
        if not sep.get('ok'):
            rep['error'] = f'separation failed: {sep.get("error")}'
            return rep
        voc, rest = sep['vocals'], sep.get('rest') or ''
        track = pitch_track(voc)
        chunks = phrase_chunks(track)
        # TWO decodes, one model load. The prompted one on the stem places the
        # lines (it aligns best); the bare one on the MIX says whether a listener
        # could make them out. Same chunk boundaries so the two are comparable.
        items = {'prompted': {'wav': voc, 'chunks': chunks, 'prompt': lyric_prompt(plan)}}
        mix_wav = _mix_for_asr(bare_take or take, work_dir, log_fn=log_fn) if BARE_ASR else None
        if mix_wav:
            items['bare'] = {'wav': mix_wav, 'chunks': chunks}
        got = transcribe(items, log_fn=log_fn) or {}
        words = got.get('prompted')
        words_bare = got.get('bare')
        if BARE_ASR and words_bare is None:
            log_fn('voice: bare decode did not run — intelligibility UNMEASURED')
        m = measure(voc, rest, plan, singer, track=track, words=words, words_bare=words_bare)
        m.pop('track', None)
        rep.update(m)
        rep['seconds'] = round(float(track.get('seconds') or 0.0), 2)
        rep['planned_windows'] = line_windows(plan)
        rep['words'] = words or []
        rep['words_bare'] = words_bare or []
        rep['stems'] = {'vocals': voc, 'rest': rest}
        rep['problems'] = problems(rep, singer)
        rep['severity'] = severity(rep['problems'])
        rep['ok'] = True
    except Exception as e:  # noqa: BLE001 — a measurement
        rep['error'] = f'{type(e).__name__}: {e}'[:200]
        log_fn(f'voice: review failed ({rep["error"]})')
    return rep


def summary_line(rep):
    """One log line a person can read."""
    if not rep.get('ok'):
        return f'voice review unmeasured — {rep.get("error")}'
    ly = rep.get('lyrics') or {}
    reg = rep.get('register') or {}
    probs = rep.get('problems') or []
    lyb = rep.get('lyrics_bare') or {}
    clear = f'{lyb.get("clear")}/{lyb.get("lines")} clear' if lyb.get('measured') else 'clarity unmeasured'
    head = (
        f'{ly.get("sung", "?")}/{ly.get("lines", "?")} lines sung, {clear}, median '
        f'{reg.get("f0_median_hz")} Hz, key {(rep.get("key") or {}).get("in_key_share")}'
    )
    return head + (' — ' + '; '.join(p['detail'] for p in probs[:4]) if probs else ' — clean')
