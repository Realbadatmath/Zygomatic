# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b's director brain: prompt assembly, GPT-4o/Ollama calls, output parsing.

Lifted out of ``stage4b_models._make_github_models``, which was one 409-line def
holding four nested ones (``_ask_github_models``, ``_ask_github_models_bulk`` and
the closures ``_parse_director_output`` / ``_call_one``).  The three values those
closures captured — the two log callables and the video-to-channel map — now
travel in a :class:`DirectorContext`.

The pure half (:func:`motion_peaks_str`, :func:`clip_picker_prompt`,
:func:`director_user_message`, :func:`strip_code_fences`,
:func:`parse_director_output`, :func:`transcript_scoring_lines`,
:func:`director_transcript_lines`) needs no network and is unit-tested in
``tests/test_stage4b_models_helpers.py``; everything named ``*_director`` or
``ask_*`` talks to GitHub Models or Ollama.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from zyg_workflows import http_json
from zyg_workflows.pipeline_config import _OLLAMA_BASE_URL
from zyg_workflows.pipeline_config import _caveman_kw
from zyg_workflows.pipeline_config import _dsl
from zyg_workflows.runtime import _record_token_usage
from zyg_workflows.stage_runner.prompts import _register_prompt

CLIP_PICKER_URL = 'https://models.inference.ai.azure.com/chat/completions'
DIRECTOR_OBJECTIVE = 'drive watch time and make viewer feel the emotional weight of what was said'
OLLAMA_DIRECTOR_MODEL = 'qwen3.6:35b-a3b'

DIRECTOR_SYSTEM = (
    'You are a video editing director AI. You receive two inputs:\n'
    '1. OBJECTIVE: One sentence describing the goal of the video\n'
    '2. TRANSCRIPT: A timestamped transcript of the raw clip footage.\n\n'
    'Your job is to output a complete structured video edit plan. Nothing else.\n\n'
    'PRE-PROCESSING RULE:\n'
    'If the transcript is longer than 10 minutes, process it in 10-minute chunks internally before producing final output. Never tell the user you are chunking. Just do it and output the final merged result.\n\n'
    'THINKING RULES (follow in this exact order):\n'
    '1. Read the full transcript before writing anything.\n'
    '2. Score every 30-second segment: KEEP / CUT / MAYBE.\n'
    '3. Identify the single best moment that serves the OBJECTIVE. Call this the PEAK MOMENT.\n'
    '4. Work backwards from the PEAK MOMENT to find what builds tension or curiosity toward it.\n'
    '5. The intro must tease the PEAK MOMENT without revealing the outcome.\n'
    '6. Every decision must be justifiable by something explicitly in the transcript. Never invent context.\n\n'
    'CUTTING RULES:\n'
    'KEEP a segment if it contains any of: Emotion (anger, excitement, fear, humor, surprise), Conflict or tension building, A revelation or unexpected information, A moment that directly leads to the PEAK MOMENT, A joke or comedic beat that lands.\n'
    'CUT a segment if it contains any of: Silence or dead air with no payoff, Filler words only with no substance, Repetition of something already said, Tangent that does not serve the OBJECTIVE, Technical difficulty with no dramatic value.\n'
    'MAYBE a segment if: It has partial value but is not clearly essential, Contains a joke that may not land, Removing it would not break the flow.\n\n'
    'CUTTING OUTPUT RULES:\n'
    '- Every segment must get a decision. No segment can be skipped.\n'
    '- Reason must be 5 words max.\n'
    '- After all cuts, output ESTIMATED FINAL DURATION.\n'
    '- If more than 60% of the transcript is CUT, output: WARNING: low value content.\n\n'
    'INTRO RULES:\n'
    '- The intro must be 1 sentence max, or map to 3 seconds of content.\n'
    '- The intro must be impossible to write without reading this specific transcript.\n'
    '- Never use generic hooks like "you won\'t believe this" unless transcript genuinely contains something unbelievable.\n'
    '- The intro must come from a KEEP segment.\n\n'
    'SOUND EFFECT RULES:\n'
    'Only add a sound effect if the transcript contains: Sudden reversal, Unexpected physical action, Loud crowd or emotional reaction, Comedic timing, A shocking number or stat.\n'
    'If triggered: timestamp inside a KEEP segment. Sound name must be specific: "cash register", "record scratch", "crowd gasp", "buzzer", "cinematic boom", "airhorn", "price is right fail". Max 2 SFX.\n'
    'If none triggered: SFX: NONE\n\n'
    'REACTION CLIP RULES:\n'
    'Only add if clip alone cannot convey emotional weight. Max 2 reactions, never stack within 30s. Duration 1-4 seconds only. Emotion: shocked/disgusted/impressed/confused/laughing/disbelief.\n\n'
    'OUTPUT FORMAT (use exactly this, nothing else):\n'
    'PEAK MOMENT: [timestamp] — [one sentence]\n'
    'INTRO: [your intro text]\n'
    'CUTS:\n'
    '[00:00-00:30] KEEP — [reason max 5 words]\n'
    '[continue for entire transcript]\n'
    'ESTIMATED FINAL DURATION: [X minutes X seconds]\n'
    'SFX: [timestamp | sound name | reason 5 words] or NONE\n'
    'REACTION: [timestamp | emotion | duration in seconds] or NONE\n'
    'EDIT NOTE: [one critical sentence for the editor] or NONE\n\n'
    'ABSOLUTE RULES:\n'
    '- Never explain your reasoning in the output.\n'
    '- Never add music suggestions unless asked.\n'
    '- Never suggest more than 2 SFX or 2 reaction clips.\n'
    '- Never tease a CUT segment in the intro.\n'
    '- Never place SFX or reaction clips on CUT segments.\n'
    '- If you are uncertain about a decision, default to MAYBE.\n'
    '- Output nothing outside the defined output format.'
)


@dataclass
class DirectorContext:
    """The three values Stage 4b's director closures used to capture.

    ``log_info``/``log_warn`` are the stage's own loggers and ``vid_channel_map``
    maps a video id to the channel it came from (used in the user message).
    """

    log_info: Callable[[str], None]
    log_warn: Callable[[str], None]
    vid_channel_map: dict


# ── pure helpers: transcripts, prompts, parsing ───────────────────────────────


def transcript_scoring_lines(tx_path_: str) -> list | None:
    """Read a Whisper transcript into ``'[12.3s] text'`` lines.

    Returns the lines, or None when the file is missing or unreadable — the
    caller then falls back to the motion-only scorer.
    """
    try:
        with open(tx_path_) as _tf:
            _tx_data = json.load(_tf)
        _segs = _tx_data.get('segments') or []
        return [f'[{s.get("start", 0):.1f}s] {s.get("text", "").strip()}' for s in _segs if s.get('text', '').strip()]
    except Exception:
        return None


def director_transcript_lines(tx_path_: str) -> list:
    """Read a transcript into ``'[mm:ss] text'`` lines, capped at 360 (~30 min).

    Never raises: an unreadable transcript becomes the single placeholder line
    ``'[transcript unavailable]'``, exactly as the director closure did.
    """
    try:
        with open(tx_path_) as _tf:
            _segs = json.load(_tf).get('segments') or []
        return [
            f'[{int(s.get("start", 0)) // 60:02d}:{int(s.get("start", 0)) % 60:02d}] {s.get("text", "").strip()}'
            for s in _segs
            if s.get('text', '').strip()
        ][:360]  # ~30 min at ~1 seg/5s
    except Exception:
        return ['[transcript unavailable]']


def motion_peaks_str(motion_: dict) -> str:
    """Format the 20 loudest audio-energy moments as ``'12s (0.91), …'``."""
    _top_motion = sorted(motion_.items(), key=lambda x: x[1], reverse=True)[:20]
    return ', '.join(f'{int(t)}s ({v:.2f})' for t, v in _top_motion)


def clip_picker_prompt(lines: list, motion_: dict, video_duration_: float, n_clips_: int) -> str:
    """Assemble the clip-picker user prompt (transcript capped at 300 lines).

    Takes the transcript lines, the audio-energy map, the video duration and how
    many clips are wanted; returns the prompt text before any DSL wrapping.
    """
    _motion_str = motion_peaks_str(motion_)
    return (
        f'You are a viral short-form video editor. Analyse this podcast/video transcript '
        f'and pick the {n_clips_} best moments to clip.\n\n'
        f'Video duration: {video_duration_:.0f} seconds\n\n'
        f'Audio energy peaks (timestamp: intensity 0-1):\n{_motion_str}\n\n'
        f'Transcript:\n' + '\n'.join(lines[:300]) + f'\n\nReturn ONLY valid JSON — no markdown, no explanation:\n'
        f'{{"clips":[{{"start_seconds":120,"reason":"hook"}}]}}\n\n'
        f'Rules:\n'
        f'- Return exactly {n_clips_} clips\n'
        f'- Each clip must be at least 90 seconds from the next\n'
        f'- Prefer moments with: punchlines, shocking statements, emotional peaks, '
        f'crowd reactions, controversy, humor\n'
        f'- start_seconds must be within 0 and {max(0, video_duration_ - 90):.0f}\n'
        f'- Return ONLY the JSON object, nothing else'
    )


def director_user_message(vid_id: str, channel: str, dur: float, lines: list) -> str:
    """Assemble the director user message: objective, video header, transcript."""
    return (
        f'OBJECTIVE: {DIRECTOR_OBJECTIVE}\n\n'
        f'VIDEO_ID: {vid_id} | CHANNEL: {channel} | DURATION: {int(dur // 60)}m{int(dur % 60)}s\n\n'
        'TRANSCRIPT:\n' + '\n'.join(lines)
    )


def strip_code_fences(text: str) -> str:
    """Drop the ``` fence lines a model may have wrapped its answer in."""
    if text.startswith('```'):
        return '\n'.join(ln for ln in text.split('\n') if not ln.startswith('```')).strip()
    return text


def parse_director_output(text_: str, dur_: float, n_clips: int) -> tuple:
    """Parse GPT-4o director output into starts, titles, sfx_plan, react_plan, intro.

    ``dur_`` drops clips past the end of the video and ``n_clips`` caps how many
    KEEP/MAYBE segments are selected; selection prefers the PEAK MOMENT and keeps
    picks at least 60 s apart.
    """
    _starts, _titles, _sfx, _react, _intro = [], [], [], [], ''
    # INTRO
    for _ln in text_.split('\n'):
        if _ln.startswith('INTRO:'):
            _intro = _ln[6:].strip()
            break
    # PEAK MOMENT timestamp
    _peak_ts = None
    for _ln in text_.split('\n'):
        if _ln.startswith('PEAK MOMENT:'):
            _m = re.search(r'(\d+):(\d+)', _ln)
            if _m:
                _peak_ts = int(_m.group(1)) * 60 + int(_m.group(2))
            break
    # KEEP segments → clip timestamps + titles
    _keep_segs = []
    for _ln in text_.split('\n'):
        _m = re.match(r'\[(\d+):(\d+)-(\d+):(\d+)\]\s+(KEEP|MAYBE)\s+—\s+(.+)', _ln.strip())
        if _m:
            _ts = int(_m.group(1)) * 60 + int(_m.group(2))
            _te = int(_m.group(3)) * 60 + int(_m.group(4))
            _reason = _m.group(6).strip()
            _keep_segs.append((_ts, _te, _reason))
    # Select up to n_clips KEEP segments spaced at least 60s apart, prefer peak moment first
    _keep_segs_sorted = sorted(_keep_segs, key=lambda x: x[0])
    if _peak_ts is not None:
        # Sort by distance from peak — pick peak first, then spread out
        _keep_segs_sorted = sorted(_keep_segs, key=lambda x: abs(x[0] - _peak_ts))
    _selected = []
    for _ts, _te, _reason in _keep_segs_sorted:
        if _ts >= dur_:
            continue
        if all(abs(_ts - _s) >= 60 for _s in _selected):
            _selected.append(_ts)
            _titles.append(_reason[:50])
            if len(_selected) >= n_clips:
                break
    _starts = sorted(_selected)
    _titles = [t for _, t in sorted(zip(_selected, _titles))]
    # SFX
    for _ln in text_.split('\n'):
        if re.match(r'SFX:\s*\d', _ln.strip()):
            _m = re.search(r'(\d+):(\d+)\s*\|\s*([^|]+)\|', _ln)
            if _m:
                _sfx_ts = int(_m.group(1)) * 60 + int(_m.group(2))
                _sfx_name = _m.group(3).strip()
                _sfx.append({'ts_secs': _sfx_ts, 'sound_name': _sfx_name})
    # REACTION
    for _ln in text_.split('\n'):
        if _ln.strip().startswith('REACTION:') and '|' in _ln:
            _m = re.search(r'(\d+):(\d+)\s*\|\s*(\w+)\s*\|\s*(\d+)', _ln)
            if _m:
                _react.append(
                    {
                        'ts_secs': int(_m.group(1)) * 60 + int(_m.group(2)),
                        'emotion': _m.group(3),
                        'duration': int(_m.group(4)),
                    }
                )
    return _starts, _titles, _sfx, _react, _intro


def director_system_prompt() -> str:
    """DSL-wrap :data:`DIRECTOR_SYSTEM`, register it in the prompt book, return it."""
    prompt = DIRECTOR_SYSTEM
    if _dsl is not None:
        prompt = _dsl.wrap_system_planner(prompt, 'clipfarm')
    _register_prompt(
        'video_editing',
        'Video Director System',
        'Clipfarm video editor AI — analyzes transcripts, plans cuts, intros, SFX, reaction clips',
        prompt,
        stage='director',
        topic='clipfarm',
    )
    return prompt


# ── the model calls ──────────────────────────────────────────────────────────


def ask_github_models(
    ctx: DirectorContext,
    tx_path_: str,
    motion_: dict,
    video_duration_: float,
    vid_id_: str,
    n_clips_: int = 5,
) -> list | None:
    """Send transcript + audio energy to GitHub Models (GPT-4o) for clip starts.

    Returns a sorted list of floats on success, None on any failure, so the
    caller can fall back to ``_pick_top_timestamps``.
    """
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if not token:
        ctx.log_warn(
            'GitHub Models: no GITHUB_TOKEN set — GPT-4o narrator and clip selection unavailable, using fallback scorer'
        )
        return None
    _lines = transcript_scoring_lines(tx_path_)
    if _lines is None:
        ctx.log_warn('GitHub Models: could not load transcript for scoring — using motion-only fallback')
        return None

    _prompt = clip_picker_prompt(_lines, motion_, video_duration_, n_clips_)
    if _dsl is not None:
        _prompt = _dsl.wrap_user_planner(_prompt, 'clipfarm')

    try:
        _resp = http_json.post_json(
            CLIP_PICKER_URL,
            {
                'model': 'gpt-4o',
                'messages': [{'role': 'user', 'content': _prompt}],
                'max_tokens': 512,
                'temperature': 0.3,
            },
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )
        # ── Record token usage ────────────────────────────────────
        _usage = _resp.get('usage', {})
        if _usage:
            _record_token_usage(
                model='gpt-4o',
                prompt_tokens=_usage.get('prompt_tokens', 0),
                completion_tokens=_usage.get('completion_tokens', 0),
                pipeline_id='',
                vid_id=vid_id_,
                stage='clip_picker',
                pipeline_type='clipfarm',
                **_caveman_kw('user_planner'),
            )
            ctx.log_info(
                f'GitHub Models tokens: prompt={_usage.get("prompt_tokens", 0)}, '
                f'completion={_usage.get("completion_tokens", 0)}, '
                f'total={_usage.get("total_tokens", 0)} '
                f'({round(_usage.get("total_tokens", 0) / 128000 * 100, 1)}% of context)'
            )
        _text = strip_code_fences(_resp['choices'][0]['message']['content'].strip())
        _data = json.loads(_text)
        _starts = sorted(
            [
                float(c['start_seconds'])
                for c in _data.get('clips', [])
                if 0 <= float(c.get('start_seconds', -1)) < video_duration_
            ]
        )
        if _starts:
            ctx.log_info(f'GitHub Models ✅ picked {len(_starts)} clips for {vid_id_}: {_starts}')
            return _starts
        ctx.log_warn('GitHub Models returned empty clips — using algorithmic fallback')
        return None
    except Exception as _e:
        ctx.log_warn(f'GitHub Models call failed ({_e}) — using fallback scorer')
        return None


def call_ollama_director(ctx: DirectorContext, vid_id: str, system_prompt: str, user_msg: str) -> str:
    """Run the Ollama director leg (two attempts, 5 s apart) and return its text.

    Records the prompt/completion token counts Ollama reports.  Re-raises the
    second failure so the caller's thread-error branch logs it.
    """
    _ol_payload = {
        'model': OLLAMA_DIRECTOR_MODEL,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_msg},
        ],
        'stream': False,
    }
    _resp = None
    for _attempt in range(2):
        try:
            _resp = http_json.post_json(_OLLAMA_BASE_URL + '/api/chat', _ol_payload, timeout=300)
            break
        except Exception as _retry_e:
            if _attempt < 1:
                ctx.log_info(f'Ollama director retry for {vid_id}: {_retry_e}')
                time.sleep(5)
            else:
                raise
    _text = (_resp or {}).get('message', {}).get('content', '').strip()
    _ol_p = (_resp or {}).get('prompt_eval_count', 0)
    _ol_c = (_resp or {}).get('eval_count', 0)
    if _ol_p or _ol_c:
        _record_token_usage(
            model=OLLAMA_DIRECTOR_MODEL,
            prompt_tokens=_ol_p,
            completion_tokens=_ol_c,
            vid_id=vid_id,
            stage='director',
            pipeline_type='clipfarm',
            **_caveman_kw('planner'),
        )
    return _text


def call_github_director(ctx: DirectorContext, vid_id: str, system_prompt: str, user_msg: str, token: str) -> str:
    """Run the GPT-4o director leg and return its text.

    Three attempts with 10/20 s backoff on a 429; any other error, and the third
    429, propagate to the caller's thread-error branch.
    """
    _payload = {
        'model': 'gpt-4o',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_msg},
        ],
        'max_tokens': 3000,
        'temperature': 0.2,
    }
    _resp = None
    for _attempt in range(3):
        try:
            _resp = http_json.post_json(
                CLIP_PICKER_URL,
                _payload,
                headers={'Authorization': f'Bearer {token}'},
                timeout=60,
            )
            break
        except Exception as _retry_e:
            if '429' in str(_retry_e) and _attempt < 2:
                _wait = 10 * (2**_attempt)
                ctx.log_info(f'GPT-4o rate limited for {vid_id} — retrying in {_wait}s (attempt {_attempt + 1}/3)')
                time.sleep(_wait)
            else:
                raise
    if _resp is None:
        raise RuntimeError('All retries exhausted')
    _usage = _resp.get('usage', {})
    if _usage:
        _record_token_usage(
            model='gpt-4o',
            prompt_tokens=_usage.get('prompt_tokens', 0),
            completion_tokens=_usage.get('completion_tokens', 0),
            vid_id=vid_id,
            stage='director',
            pipeline_type='clipfarm',
            **_caveman_kw('planner'),
        )
    return _resp['choices'][0]['message']['content'].strip()


def call_one_video(
    ctx: DirectorContext, sv_: dict, system_prompt: str, token: str, use_ollama: bool, n_clips: int
) -> tuple:
    """Direct one scored video.

    Returns ``(vid_id, starts, titles, sfx, react, intro)`` — ``starts`` is None
    when the model produced no usable clip, which puts that video back on the
    algorithmic fallback.
    """
    _vid_id = sv_['vid_id']
    _dur = sv_['vid_duration']
    _channel = ctx.vid_channel_map.get(_vid_id, '')
    _lines = director_transcript_lines(sv_['tx_path'])
    _user_msg = director_user_message(_vid_id, _channel, _dur, _lines)

    if use_ollama:
        _text = call_ollama_director(ctx, _vid_id, system_prompt, _user_msg)
    else:
        _text = call_github_director(ctx, _vid_id, system_prompt, _user_msg, token)

    _text = strip_code_fences(_text)
    _starts, _titles, _sfx, _react, _intro = parse_director_output(_text, _dur, n_clips)
    _brain = f'Ollama {OLLAMA_DIRECTOR_MODEL}' if use_ollama else 'GPT-4o'
    if _starts:
        ctx.log_info(
            f'{_brain} Director ✅ {_vid_id}: {len(_starts)} clips, {len(_sfx)} SFX, '
            f'{len(_react)} reactions, intro="{_intro[:60]}"'
        )
        return _vid_id, _starts, _titles, _sfx, _react, _intro
    ctx.log_warn(f'{_brain} returned no valid clips for {_vid_id} — using algorithmic fallback')
    return _vid_id, None, [], [], [], ''


def ask_github_models_bulk(ctx: DirectorContext, scored_raw_: list, n_clips: int = 5) -> tuple:
    """Per-video director AI calls — GPT-4o via GitHub Models when GITHUB_TOKEN set,
    Ollama qwen3.6:35b-a3b as fallback when not.
    Returns (moments_dict, titles_dict, sfx_dict, react_dict, intro_dict)
    """
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    _use_ollama = not token
    if _use_ollama:
        ctx.log_info('GPT-4o: no GITHUB_TOKEN — using Ollama qwen3.6:35b-a3b as director brain')
    if not scored_raw_:
        return {}, {}, {}, {}, {}

    _system = director_system_prompt()

    _out: dict = {}
    _out_titles: dict = {}
    _out_sfx: dict = {}
    _out_react: dict = {}
    _out_intro: dict = {}

    with ThreadPoolExecutor(max_workers=2) as _pool:  # max 2 concurrent to avoid rate limit bursts
        _futs = {}
        for _i, sv in enumerate(scored_raw_):
            if _i > 0:
                time.sleep(3)  # 3s gap between submissions
            _futs[_pool.submit(call_one_video, ctx, sv, _system, token, _use_ollama, n_clips)] = sv['vid_id']
        for _fut in as_completed(_futs):
            try:
                _vid_id, _starts, _titles, _sfx, _react, _intro = _fut.result()
                if _starts:
                    _out[_vid_id] = _starts
                    _out_titles[_vid_id] = _titles
                    _out_sfx[_vid_id] = _sfx
                    _out_react[_vid_id] = _react
                    _out_intro[_vid_id] = _intro
            except Exception as _fe:
                ctx.log_warn(f'GPT-4o thread error ({_fe})')
    if not _out:
        ctx.log_warn('GPT-4o: all per-video calls failed — ALL clips using algorithmic fallback')
    else:
        ctx.log_info(
            f'GPT-4o Director complete: {sum(len(v) for v in _out.values())} clips from '
            f'{len(_out)}/{len(scored_raw_)} videos'
        )
    return _out, _out_titles, _out_sfx, _out_react, _out_intro
