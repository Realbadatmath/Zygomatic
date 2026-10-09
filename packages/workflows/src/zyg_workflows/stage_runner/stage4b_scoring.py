# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b scoring and transcript helpers, hoisted out of ``_pf_stage_4b``.

Every function here was a closure inside ``_pf_stage_4b``; the enclosing
locals they read (the keyword tables, the SFX directory, the three log
callbacks) are now explicit parameters, so each one can be exercised on its
own with plain inputs.  Bodies are unchanged.
"""

import json
import os
import logging as _zyg_logging
from zyg_workflows.narrator_voice_service import _get_narrator_voice
from zyg_workflows.tts_service import _tts_shared
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')

_SFX_CATALOGUE = {
    'bonk.mp3': 'https://www.myinstants.com/media/sounds/bonk.mp3',
    'airhorn.mp3': 'https://www.myinstants.com/media/sounds/mlg-airhorn.mp3',
    'wrong_answer.mp3': 'https://www.myinstants.com/media/sounds/wronganswer.mp3',
    'sad_trombone.mp3': 'https://www.myinstants.com/media/sounds/sadtrombone.swf.mp3',
    'vine_boom.mp3': 'https://www.myinstants.com/media/sounds/vine-boom.mp3',
    'bruh.mp3': 'https://www.myinstants.com/media/sounds/bruh.mp3',
}


def _score_transcript(tx_path: str, video_duration: float, viral_keywords) -> dict:
    """Return dict of second -> transcript_score (0.0–1.0).

    ``tx_path`` is a Whisper-shaped JSON file with a ``segments`` list;
    ``viral_keywords`` is the lowercase keyword set to count hits against.
    A missing, unreadable or hit-less transcript gives ``{}``.
    """
    if not tx_path or not os.path.exists(tx_path):
        return {}
    try:
        with open(tx_path) as _tf:
            tx_data = json.load(_tf)
        segments = tx_data.get('segments', [])
    except Exception:
        return {}
    # Build per-second keyword hit counts
    sec_score = {}
    for seg in segments:
        start = float(seg.get('start', 0))
        text = seg.get('text', '').lower()
        hits = sum(1 for kw in viral_keywords if kw in text)
        # Exclamation marks add half a hit each
        hits += text.count('!') * 0.5
        # All-caps words (transcribed shouting) add 0.3 each
        hits += sum(0.3 for w in seg.get('text', '').split() if w.isupper() and len(w) > 2)
        sec = int(start)
        sec_score[sec] = sec_score.get(sec, 0.0) + hits
    if not sec_score:
        return {}
    max_score = max(sec_score.values()) or 1.0
    return {sec: round(val / max_score, 4) for sec, val in sec_score.items()}


def _score_motion(vid_path: str, _log_err) -> dict:
    """Return dict of second -> motion_score (0.0–1.0). 12 parallel chunks via ffmpeg.

    Takes the path of the source video and the stage's error logger; any
    failure of the vision tool is logged and reported as ``{}``.
    """
    try:
        from zyg_workflows.tools.vision_tools import MotionScorerTool

        raw = MotionScorerTool()._run(video_path=vid_path, sample_fps=1.0, resize_width=160, n_workers=10)
        result = json.loads(raw) if raw.strip().startswith('{') else {}
        all_scores = result.get('all_scores', [])
        if not all_scores:
            return {}
        max_m = max(s['motion_score'] for s in all_scores) or 1.0
        return {s['second']: round(s['motion_score'] / max_m, 4) for s in all_scores}
    except Exception as _e:
        _log_err('Stage 4b motion scorer', str(_e))
        return {}


def _pick_top_timestamps(
    motion: dict,
    transcript: dict,
    video_duration: float,
    n_clips: int = 5,
    clip_len: float = 360.0,
    motion_weight: float = 0.45,
    tx_weight: float = 0.55,
) -> list:
    """Combine motion + transcript scores, return top N non-overlapping start seconds.

    Both score maps are second -> 0.0–1.0.  With no scores at all (or none
    that survive the overlap filter) the result is evenly spaced fallbacks
    across ``video_duration``.
    """
    all_secs = sorted(set(list(motion.keys()) + list(transcript.keys())))
    if not all_secs:
        # Pure fallback — evenly spaced
        step = max(60, int(video_duration / (n_clips + 1)))
        return [step * i for i in range(1, n_clips + 1) if step * i < video_duration]

    combined = {}
    for sec in all_secs:
        m = motion.get(sec, 0.0)
        t = transcript.get(sec, 0.0)
        combined[sec] = round(motion_weight * m + tx_weight * t, 4)

    # Sort by score descending, pick non-overlapping windows
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    chosen = []
    for sec, _score in ranked:
        raw_start = max(0.0, sec - 5)  # center the clip 5s before the peak
        # Check no overlap with already chosen clips
        overlap = any(abs(raw_start - cs) < clip_len for cs in chosen)
        if not overlap:
            chosen.append(raw_start)
        if len(chosen) >= n_clips:
            break

    # If we didn't get enough, pad with evenly spaced fallbacks
    if not chosen:
        step = max(60, int(video_duration / (n_clips + 1)))
        chosen = [float(step * i) for i in range(1, n_clips + 1) if step * i < video_duration]

    return sorted(chosen)


def _snap_to_sentence_start(tx_path_: str, raw_start: float, window: float = 8.0) -> float:
    """Snap raw_start backwards to the nearest sentence-beginning in transcript.
    Looks up to window seconds before raw_start for a segment that follows a
    sentence-ending punctuation (. ? !). Falls back to raw_start if none found."""
    if not tx_path_ or not os.path.exists(tx_path_):
        return raw_start
    try:
        with open(tx_path_) as _tf:
            segs = json.load(_tf).get('segments', [])
    except Exception:
        return raw_start
    look_from = max(0.0, raw_start - window)
    # Collect segments in [look_from, raw_start+2]
    nearby = [s for s in segs if look_from <= float(s.get('start', 0)) <= raw_start + 2.0]
    if not nearby:
        return raw_start
    # Walk forward: find the first segment whose previous segment ended a sentence
    prev_text = ''
    for seg in nearby:
        seg_start = float(seg.get('start', 0))
        if prev_text.strip() and prev_text.strip()[-1] in '.?!' and seg_start <= raw_start + 1.0:
            # This segment starts after a sentence boundary — good start point
            if seg_start >= look_from:
                return seg_start
        prev_text = seg.get('text', '')
    return raw_start


def _get_natural_clip_duration(tx_path_: str, start_ts: float, min_dur: float = 90.0, max_dur: float = 360.0) -> float:
    """Find natural sentence boundary in transcript between min_dur and max_dur seconds
    from start_ts. Falls back to min_dur if no transcript or no suitable boundary."""
    if not tx_path_ or not os.path.exists(tx_path_):
        return min_dur
    try:
        with open(tx_path_) as _tf2:
            tx_data2 = json.load(_tf2)
        segments2 = tx_data2.get('segments', [])
    except Exception:
        return min_dur
    target_min_end = start_ts + min_dur
    target_max_end = start_ts + max_dur
    # Collect segments within our window
    window = [
        s for s in segments2 if float(s.get('start', 0)) >= start_ts and float(s.get('start', 0)) <= target_max_end
    ]
    if not window:
        return min_dur
    # 1st pass: look for sentence-ending segment (. ? !) past min_dur
    for seg in window:
        seg_end = float(seg.get('end', seg.get('start', 0)))
        if seg_end < target_min_end:
            continue
        txt = seg.get('text', '').strip()
        if txt and txt[-1] in '.?!':
            return min(max(seg_end - start_ts + 0.5, min_dur), max_dur)
    # 2nd pass: look for silence gap >= 0.8s past min_dur
    for idx in range(len(window) - 1):
        curr_end = float(window[idx].get('end', window[idx].get('start', 0)))
        next_start = float(window[idx + 1].get('start', 0))
        if curr_end < target_min_end:
            continue
        if (next_start - curr_end) >= 0.8:
            return min(max(curr_end - start_ts + 0.3, min_dur), max_dur)
    # Fallback: last segment end or max_dur
    last_end = float(window[-1].get('end', window[-1].get('start', target_max_end)))
    return min(max(last_end - start_ts, min_dur), max_dur)


def _find_stupid_moments_in_clip(tx_path_: str, clip_start: float, clip_end: float, cringe_keywords) -> list:
    """Return list of (relative_ts, text) for cringe/stupid moments within clip window.

    ``cringe_keywords`` is the lowercase keyword set; the result is ordered by
    descending cringe score and the timestamps are relative to ``clip_start``.
    """
    if not tx_path_ or not os.path.exists(tx_path_):
        return []
    try:
        with open(tx_path_) as _tf3:
            tx_data3 = json.load(_tf3)
        segments3 = tx_data3.get('segments', [])
    except Exception:
        return []
    moments_ = []
    for seg in segments3:
        seg_start = float(seg.get('start', 0))
        if seg_start < clip_start or seg_start > clip_end:
            continue
        text_ = seg.get('text', '').lower()
        score_ = sum(1 for kw in cringe_keywords if kw in text_)
        score_ += text_.count('?') * 0.4
        score_ += text_.count('!') * 0.3
        if score_ >= 1.0:
            moments_.append((seg_start - clip_start, seg.get('text', ''), score_))
    moments_.sort(key=lambda x: x[2], reverse=True)
    return [(ts_, txt_) for ts_, txt_, _ in moments_]


def _ensure_sfx(sfx_dir: str, _log_info, _log_warn) -> list:
    """Auto-download SFX if missing. Returns list of available .mp3 paths.

    ``sfx_dir`` is the directory the catalogue is mirrored into; a download
    that fails or lands under 500 bytes is warned about and skipped.
    """
    import subprocess as _sp_sfx

    for fname_, url_ in _SFX_CATALOGUE.items():
        fpath_ = os.path.join(sfx_dir, fname_)
        if not os.path.exists(fpath_) or os.path.getsize(fpath_) < 500:
            try:
                _log_info(f'Stage 4b: downloading missing SFX {fname_}')
                _sp_sfx.run([exe('wget'), '-q', '--timeout=10', '-O', fpath_, url_], timeout=20, capture_output=True)
                if os.path.exists(fpath_) and os.path.getsize(fpath_) > 500:
                    _log_info(f'Stage 4b: ✅ SFX {fname_} downloaded ({os.path.getsize(fpath_) // 1024} KB)')
                else:
                    _log_warn(f'Stage 4b: SFX asset download failed or empty — {fname_} (no sound effect this clip)')
            except Exception as _exc:
                _zyg_log.warning('sfx download of %s failed, the clip renders without it: %s', fname_, _exc)
    return [
        os.path.join(sfx_dir, f)
        for f in os.listdir(sfx_dir)
        if f.endswith('.mp3') and os.path.getsize(os.path.join(sfx_dir, f)) > 500
    ]


def _generate_tts(text_: str, out_path_: str, vid_id_: str = '', *, _log_err, _log_info, _log_warn) -> bool:
    """Generate TTS narration. Primary: IndexTTS-2. Fallback: Chatterbox.

    Writes ``text_`` to ``out_path_`` with the narrator voice registered for
    ``vid_id_`` and returns whether a file was produced.
    """

    def _log_adapt(lvl, stage, msg):
        (_log_warn if lvl in ('WARNING', 'ERROR') else _log_info)(f'{stage}: {msg}')

    _voice_name, _rate, _pitch = _get_narrator_voice(vid_id_)
    _ok, _ = _tts_shared(text_, out_path_, 'Smart Clip TTS', _log_adapt, voice_id=_voice_name)
    if _ok:
        return True
    _log_err('TTS generate', 'IndexTTS-2 and Chatterbox both failed')
    return False
