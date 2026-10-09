# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import json
import os
from flask import (
    Blueprint,
    jsonify,
    request,
)
from zyg_workflows.bin import exe

bp = Blueprint('claude_clip', __name__)
from zyg_dashboard.gui.timeutil import _ams_now  # noqa: E402
from zyg_dashboard.crewai_web_gui import (  # noqa: E402
    _ASSETS_SFX_DIR,
    _CCL_AR_VF,
    _CCL_OUTPUT_BASE,
    _CONTEXT_LEDGER_PATH,
    _MODEL_CTX_WINDOWS,
    _TOKEN_USAGE_LOCK,
    _TOKEN_USAGE_PATH,
    _agent_log,
    _ccl_json,
    _ccl_re,
    _ccl_threading,
    limiter,
    sanitize_filename,
)

_zyg_log = _zyg_logging.getLogger(__name__)


_TOKEN_USAGE_LOG: list = []


def _record_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pipeline_id: str = '',
    vid_id: str = '',
    stage: str = '',
    pipeline_type: str = '',
    caveman_level: str = '',
    caveman_mode: str = '',
):
    """Append a token usage entry to the in-memory log, token_usage.json (rolling 1000), and context_ledger.jsonl (permanent)."""
    _now = _ams_now()
    _ml = (model or '').lower()
    _ctx_win = next((v for k, v in _MODEL_CTX_WINDOWS.items() if _ml.startswith(k)), 128_000)
    entry = {
        'timestamp': _now.isoformat(timespec='milliseconds'),
        'date': _now.strftime('%Y-%m-%d'),
        'model': model,
        'stage': stage,
        'pipeline_type': pipeline_type,
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': prompt_tokens + completion_tokens,
        'context_pct': round((prompt_tokens + completion_tokens) / _ctx_win * 100, 2),
        'pipeline_id': pipeline_id,
        'vid_id': vid_id,
        'caveman_level': caveman_level or 'off',
        'caveman_mode': caveman_mode or '',
    }
    # P-03 (2026-08-25): smoke/gatecheck runs still count in memory (the live
    # GUI can show them) but leave no row in token_usage.json or the permanent
    # context ledger — those feed the cost metrics.
    try:
        from zyg_workflows.pipeline_common import is_test_pipeline_id as _is_test_pid

        _persist = not _is_test_pid(pipeline_id)
    except Exception:
        _persist = True
    with _TOKEN_USAGE_LOCK:
        _TOKEN_USAGE_LOG.append(entry)
        # keep last 1000 entries in memory
        if len(_TOKEN_USAGE_LOG) > 1000:
            _TOKEN_USAGE_LOG.pop(0)
        if not _persist:
            return
        # Rolling JSON (capped at 1000 entries — existing behaviour)
        try:
            existing = []
            if os.path.exists(_TOKEN_USAGE_PATH):
                with open(_TOKEN_USAGE_PATH) as _f:
                    existing = json.load(_f)
            existing.append(entry)
            if len(existing) > 1000:
                existing = existing[-1000:]
            with open(_TOKEN_USAGE_PATH, 'w') as _f:
                json.dump(existing, _f, indent=2)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('token usage record not persisted: %s', _exc)
        # Permanent context ledger (JSONL append — never rotated)
        try:
            os.makedirs(os.path.dirname(_CONTEXT_LEDGER_PATH), exist_ok=True)
            with open(_CONTEXT_LEDGER_PATH, 'a') as _cl:
                _cl.write(json.dumps(entry) + '\n')
        except OSError as _exc:
            _zyg_log.warning('context ledger append failed, this call is not recorded: %s', _exc)


def _hms_to_seconds(hms: str) -> float:
    """Convert HH:MM:SS, MM:SS, or raw float-seconds string to float seconds."""
    parts = str(hms).strip().split(':')
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(vals) == 3:
        return vals[0] * 3600 + vals[1] * 60 + vals[2]
    if len(vals) == 2:
        return vals[0] * 60 + vals[1]
    return vals[0]


def _ccl_log(level: str, msg: str, pipeline_id: str = 'claude_plan'):
    """Log to stdout + agent logbook."""
    _zyg_log.info(f'[CCL:{level}] {msg}')
    _agent_log(level, 'CLAUDE_PLAN', pipeline_id, 'claude_execution', msg)


def _ccl_build_srt(tx_path: str, clip_start: float, clip_dur: float, out_prefix: str) -> 'str | None':
    """
    Generate a .srt subtitle file from a transcript JSON,
    with timestamps relative to the clip start.  Returns path or None.
    """
    if not tx_path or not os.path.exists(tx_path):
        return None
    try:
        with open(tx_path) as _f:
            tx = _ccl_json.load(_f)
        segs = tx.get('segments') or tx.get('timestamped_transcript') or []
        clip_end = clip_start + clip_dur
        lines = []
        idx = 1
        for seg in segs:
            # support both float-second keys and HH:MM:SS string keys
            _s_raw = seg.get('start', 0)
            _e_raw = seg.get('end', 0)
            _ss = _hms_to_seconds(str(_s_raw)) if isinstance(_s_raw, str) else float(_s_raw)
            _ee = _hms_to_seconds(str(_e_raw)) if isinstance(_e_raw, str) else float(_e_raw)
            if _ee < clip_start or _ss > clip_end:
                continue
            _rs = max(0.0, _ss - clip_start)
            _re = min(clip_dur, _ee - clip_start)

            def _srt_ts(t):
                h = int(t // 3600)
                m = int((t % 3600) // 60)
                s = t % 60
                return f'{h:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')

            text = seg.get('text', '').strip()
            if text:
                lines.append(f'{idx}\n{_srt_ts(_rs)} --> {_srt_ts(_re)}\n{text}\n')
                idx += 1
        if not lines:
            return None
        srt_path = out_prefix + '_ccl.srt'
        with open(srt_path, 'w') as _sf2:
            _sf2.write('\n'.join(lines))
        return srt_path
    except Exception:
        return None


def _render_clip_direct(job: dict) -> str:
    """
    Render one clip from a Claude job_config dict using ffmpeg directly.

    Required keys : input_video, clip_start (HH:MM:SS), clip_end (HH:MM:SS)
    Optional keys : aspect_ratio (9:16|1:1|16:9), output_name, output_dir,
                    generate_subtitles (bool), transcript_path, auto_publish
    Returns output file path on success, raises RuntimeError on failure.
    """
    import subprocess as _sp_r

    _start_s = _hms_to_seconds(job['clip_start'])
    _end_s = _hms_to_seconds(job['clip_end'])
    _dur = max(1.0, _end_s - _start_s)
    _ar = job.get('aspect_ratio', '16:9')
    _vf_base = _CCL_AR_VF.get(_ar, _CCL_AR_VF['16:9'])
    _out_dir = job.get('output_dir') or _CCL_OUTPUT_BASE
    os.makedirs(_out_dir, exist_ok=True)
    _safe = sanitize_filename(job.get('output_name', 'clip'))
    _out = os.path.join(_out_dir, f'{_safe}.mp4')
    _tmp_pfx = os.path.join(_out_dir, _safe)

    # Fade in/out – 0.5 s each side (matches main pipeline)
    _fo_st = max(0.0, _dur - 0.5)
    _vf = f'fade=t=in:st=0:d=0.5,fade=t=out:st={_fo_st:.3f}:d=0.5,{_vf_base}'
    _af = f'afade=t=in:st=0:d=0.5,afade=t=out:st={_fo_st:.3f}:d=0.5'

    # Generate SRT alongside clip (not burned in — delivered to YouTube)
    _srt = None
    if job.get('generate_subtitles') and job.get('transcript_path'):
        _srt = _ccl_build_srt(job['transcript_path'], _start_s, _dur, _tmp_pfx)

    _base_args = [
        '-y',
        '-ss',
        str(_start_s),
        '-i',
        job['input_video'],
        '-t',
        str(_dur),
        '-vf',
        _vf,
        '-af',
        _af,
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-movflags',
        '+faststart',
    ]
    _cmds = [
        [exe('ffmpeg')] + _base_args + ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '23', _out],
        [exe('ffmpeg')] + _base_args + ['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', _out],
    ]
    for _cmd in _cmds:
        _res = _sp_r.run(_cmd, capture_output=True, timeout=600)
        if _res.returncode == 0 and os.path.exists(_out) and os.path.getsize(_out) > 10000:
            return _out
    raise RuntimeError(f'ffmpeg failed rendering {_safe}')


def analyze_video_for_claude(video_path: str, output_path: str = None) -> dict:
    """
    Phase 1 — Analyse a video and produce analysis_bundle.json for Claude.

    Generates:
      • timestamped_transcript  (Whisper)
      • audio_peaks             (ffmpeg RMS energy, normalised 0-1)
      • scene_cuts              (ffmpeg scene-change detection)

    Writes bundle to output_path (default: <video>_analysis_bundle.json).
    Returns the bundle dict.
    """
    import subprocess as _sp_a

    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f'Video not found: {video_path}')

    bundle: dict = {
        'video_path': video_path,
        'timestamped_transcript': [],
        'audio_peaks': [],
        'scene_cuts': [],
    }

    # ── 1. Transcript via faster-whisper large-v3 + VAD ───────────────────
    #   2026-07-28: upgraded from openai-whisper `base` (no silence gating).
    #   Shared loader (zyg_whisper) is VRAM-aware + CPU-safe. Numeric times are
    #   kept for speaker assignment, then formatted HH:MM:SS.mmm for the bundle.
    _num_segments = []  # [(start_f, end_f, text), ...]
    try:
        import zyg_whisper as _zw

        _ccl_log('INFO', f'Transcribing {os.path.basename(video_path)} (large-v3+VAD) …')
        _segs, _info = _zw.transcribe_segments(video_path, language='en', want_words=False, vad=True)
        for _s in _segs:
            _num_segments.append((_s['start'], _s['end'], _s['text']))
        _ccl_log('INFO', f'Transcript: {len(_num_segments)} segments (lang={getattr(_info, "language", "?")})')
    except Exception as _e:
        _ccl_log('WARN', f'Whisper transcription failed: {_e}')

    # ── 1b. Speaker diarization via NeMo Sortformer (env-gated, fail-safe) ─
    #   ZYG_DIARIZATION=0 to disable. Never blocks the transcript: any failure
    #   or a missing NeMo venv just yields an unlabelled transcript.
    _spk_by_idx = {}
    if _num_segments:
        try:
            from zyg_workflows import diarize_sortformer as _diar

            _diar_segments = _diar.diarize(video_path)  # None if disabled/unavailable
            if _diar_segments:
                _spk_by_idx = _diar.assign_speakers(_num_segments, _diar_segments)
                _speakers = sorted(set(_spk_by_idx.values()))
                bundle['speakers'] = _speakers
                _ccl_log('INFO', f'Diarization: {len(_speakers)} speaker(s) across {len(_diar_segments)} turns')
        except Exception as _e:
            _ccl_log('WARN', f'Diarization failed (transcript kept unlabelled): {_e}')

    # ── 1c. Emit transcript (with speaker labels when available) ──────────
    def _fmt_t(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f'{h:02d}:{m:02d}:{s:06.3f}'

    for _i, (_st, _en, _tx) in enumerate(_num_segments):
        _entry = {'start': _fmt_t(_st), 'end': _fmt_t(_en), 'text': _tx}
        if _i in _spk_by_idx:
            _entry['speaker'] = _spk_by_idx[_i]
        bundle['timestamped_transcript'].append(_entry)

    # Free the Whisper model's VRAM before the ComfyUI-heavy stages downstream.
    try:
        import zyg_whisper as _zwf

        _zwf.unload_models()
    except Exception as _exc:
        _zyg_log.debug('whisper vram release skipped: %s', _exc)

    # ── 2. Audio energy peaks via ffmpeg astats ────────────────────────────
    try:
        _ccl_log('INFO', 'Analysing audio energy …')
        _ae_cmd = [
            'ffmpeg',
            '-i',
            video_path,
            '-af',
            'astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-',
            '-f',
            'null',
            '-',
        ]
        _ae = _sp_a.run(_ae_cmd, capture_output=True, text=True, timeout=300)
        _cur_t = None
        for _ln in _ae.stderr.split('\n'):
            _m = _ccl_re.search(r'pts_time:([\d.]+)', _ln)
            if _m:
                _cur_t = float(_m.group(1))
            _m2 = _ccl_re.search(r'lavfi\.astats\.Overall\.RMS_level=([-\d.inf]+)', _ln)
            if _m2 and _cur_t is not None:
                try:
                    _rms = float(_m2.group(1))
                    _norm = max(0.0, min(1.0, (_rms + 60.0) / 60.0))
                    if _norm > 0.5:
                        _h2 = int(_cur_t // 3600)
                        _m3 = int((_cur_t % 3600) // 60)
                        _s2 = _cur_t % 60
                        bundle['audio_peaks'].append(
                            {
                                'time': f'{_h2:02d}:{_m3:02d}:{_s2:06.3f}',
                                'level': round(_norm, 3),
                            }
                        )
                except ValueError as _exc:
                    _zyg_log.debug('skipping astats frame with an unparseable level: %s', _exc)
        _ccl_log('INFO', f'Audio peaks: {len(bundle["audio_peaks"])} above 0.5 threshold')
    except Exception as _e:
        _ccl_log('WARN', f'Audio analysis failed: {_e}')

    # ── 3. Scene cut detection via ffmpeg select filter ───────────────────
    try:
        _ccl_log('INFO', 'Detecting scene cuts …')
        _sc_cmd = [
            'ffmpeg',
            '-i',
            video_path,
            '-vf',
            "select='gt(scene,0.35)',metadata=print:key=lavfi.scene_score:file=-",
            '-vsync',
            'vfr',
            '-f',
            'null',
            '-',
        ]
        _sc = _sp_a.run(_sc_cmd, capture_output=True, text=True, timeout=300)
        _seen = set()
        for _ln in _sc.stderr.split('\n'):
            _m = _ccl_re.search(r'pts_time:([\d.]+)', _ln)
            if _m:
                _t = float(_m.group(1))
                _h3 = int(_t // 3600)
                _m4 = int((_t % 3600) // 60)
                _s3 = _t % 60
                _ts = f'{_h3:02d}:{_m4:02d}:{_s3:06.3f}'
                _seen.add(_ts)
        bundle['scene_cuts'] = sorted(_seen)
        _ccl_log('INFO', f'Scene cuts: {len(bundle["scene_cuts"])} detected')
    except Exception as _e:
        _ccl_log('WARN', f'Scene detection failed: {_e}')

    # ── 4. Write bundle ────────────────────────────────────────────────────
    if output_path is None:
        output_path = os.path.splitext(video_path)[0] + '_analysis_bundle.json'
    with open(output_path, 'w') as _fh:
        _ccl_json.dump(bundle, _fh, indent=2)
    _ccl_log('INFO', f'Analysis bundle written → {output_path}')
    return bundle


def execute_claude_clip_plan(plan_path: str) -> dict:
    """
    Phase 3a — Execute a Claude clip_plan.json.

    Expected schema:
      { "video_id": "...", "source_video_path": "...",
        "clips": [{"start":"HH:MM:SS","end":"HH:MM:SS","title":"...","format":"16:9"}] }

    Returns {'success': int, 'failed': int, 'outputs': [...], 'errors': [...]}.
    """
    plan_path = os.path.abspath(plan_path)
    _ccl_log('INFO', f'Loading clip plan: {plan_path}')
    if not os.path.exists(plan_path):
        raise FileNotFoundError(f'Clip plan not found: {plan_path}')
    with open(plan_path) as _fh:
        plan = _ccl_json.load(_fh)

    for _req in ('source_video_path', 'clips'):
        if _req not in plan:
            raise ValueError(f'clip_plan.json missing required field: {_req}')
    if not isinstance(plan['clips'], list) or not plan['clips']:
        raise ValueError('"clips" must be a non-empty list')

    _vpath = plan['source_video_path']
    if not os.path.exists(_vpath):
        raise FileNotFoundError(f'Source video not found: {_vpath}')

    _vid_id = plan.get('video_id') or os.path.splitext(os.path.basename(_vpath))[0]
    _out_dir = os.path.join(_CCL_OUTPUT_BASE, sanitize_filename(_vid_id))
    os.makedirs(_out_dir, exist_ok=True)

    # Look for an existing transcript next to the video
    _tx = next(
        (
            p
            for p in [
                os.path.splitext(_vpath)[0] + '_transcript.json',
                os.path.join(os.path.dirname(_vpath), f'{_vid_id}_transcript.json'),
                os.path.join(os.path.dirname(_vpath), f'{_vid_id}_analysis_bundle.json'),
            ]
            if os.path.exists(p)
        ),
        None,
    )

    _ccl_log(
        'INFO',
        f'Plan loaded — video_id={_vid_id}, clips={len(plan["clips"])}'
        + (f', transcript={os.path.basename(_tx)}' if _tx else ', no transcript'),
    )

    results: dict = {'success': 0, 'failed': 0, 'outputs': [], 'errors': []}
    for _idx, clip in enumerate(plan['clips'], 1):
        _title = clip.get('title', f'clip_{_idx}')
        _ccl_log(
            'INFO', f'Queuing clip {_idx}/{len(plan["clips"])}: "{_title}" [{clip.get("start")} → {clip.get("end")}]'
        )
        try:
            job = {
                'input_video': _vpath,
                'clip_start': clip['start'],
                'clip_end': clip['end'],
                'aspect_ratio': clip.get('format', '16:9'),
                'output_name': f'{_vid_id}_clip{_idx:02d}_{sanitize_filename(_title)}',
                'output_dir': _out_dir,
                'generate_subtitles': True,
                'transcript_path': _tx,
                'auto_publish': False,
            }
            _out = _render_clip_direct(job)
            _ccl_log('INFO', f'✅ Clip {_idx} rendered → {os.path.basename(_out)}')
            results['success'] += 1
            results['outputs'].append(_out)
        except Exception as _e:
            _msg = f'Clip {_idx} "{_title}" failed: {_e}'
            _ccl_log('ERROR', _msg)
            results['failed'] += 1
            results['errors'].append(_msg)

    _ccl_log('INFO', f'Plan complete — {results["success"]} rendered, {results["failed"]} failed. Output: {_out_dir}')
    return results


def execute_sfx_plan(plan_path: str) -> dict:
    """
    Phase 3b — Apply SFX placements from a Claude sfx_plan.json.

    Expected schema:
      { "clips": [{"clip_path":"...","sfx":[{"file":"boom.mp3","time":"HH:MM:SS"}]}] }

    Mixes each SFX into the clip at the given timestamp using ffmpeg adelay.
    Returns {'success': int, 'failed': int, 'outputs': [...]}.
    """
    import subprocess as _sp_s

    plan_path = os.path.abspath(plan_path)
    _ccl_log('INFO', f'Loading SFX plan: {plan_path}')
    if not os.path.exists(plan_path):
        raise FileNotFoundError(f'SFX plan not found: {plan_path}')
    with open(plan_path) as _fh:
        plan = _ccl_json.load(_fh)

    _entries = plan.get('clips', [])
    _ccl_log('INFO', f'SFX plan: {len(_entries)} clips to process')
    results: dict = {'success': 0, 'failed': 0, 'outputs': []}

    for _entry in _entries:
        _cp = _entry.get('clip_path', '')
        if not os.path.exists(_cp):
            _ccl_log('WARN', f'Clip not found, skipping: {_cp}')
            results['failed'] += 1
            continue
        _sfx_list = [
            s
            for s in _entry.get('sfx', [])
            if os.path.exists(os.path.join(_ASSETS_SFX_DIR, os.path.basename(s.get('file', ''))))
        ]
        if not _sfx_list:
            continue
        _base, _ext = os.path.splitext(_cp)
        _out = _base + '_sfx' + _ext
        try:
            _inputs = ['-i', _cp]
            _fp = ['[0:a]aformat=fltp,volume=1.0[main]']
            _mix = ['[main]']
            for _si, _sfx in enumerate(_sfx_list, 1):
                _sf_path = os.path.join(_ASSETS_SFX_DIR, os.path.basename(_sfx['file']))
                _delay_ms = int(_hms_to_seconds(_sfx.get('time', '0')) * 1000)
                _inputs += ['-i', _sf_path]
                _fp.append(f'[{_si}:a]adelay={_delay_ms}|{_delay_ms},volume=0.6[sfx{_si}]')
                _mix.append(f'[sfx{_si}]')
            _fp.append(f'{"".join(_mix)}amix=inputs={len(_mix)}:duration=first:normalize=0[out]')
            _cmd = (
                [exe('ffmpeg'), '-y']
                + _inputs
                + [
                    '-filter_complex',
                    ';'.join(_fp),
                    '-map',
                    '0:v',
                    '-map',
                    '[out]',
                    '-c:v',
                    'copy',
                    '-c:a',
                    'aac',
                    '-b:a',
                    '192k',
                    _out,
                ]
            )
            _res = _sp_s.run(_cmd, capture_output=True, timeout=300)
            if _res.returncode == 0:
                _ccl_log('INFO', f'✅ SFX mixed → {os.path.basename(_out)}')
                results['success'] += 1
                results['outputs'].append(_out)
            else:
                raise RuntimeError(_res.stderr.decode()[-400:])
        except Exception as _e:
            _ccl_log('ERROR', f'SFX mix failed for {os.path.basename(_cp)}: {_e}')
            results['failed'] += 1

    _ccl_log('INFO', f'SFX plan complete — {results["success"]} mixed, {results["failed"]} failed')
    return results


def execute_caption_plan(plan_path: str) -> dict:
    """
    Phase 3c — Apply caption overlays from a Claude caption_plan.json.

    Expected schema:
      { "clips": [{"clip_path":"...", "captions":[
            {"text":"...","start":"HH:MM:SS","end":"HH:MM:SS","style":"top|center|bottom"}
        ]}] }

    Renders text via ffmpeg drawtext filter.
    Returns {'success': int, 'failed': int, 'outputs': [...]}.
    """
    import subprocess as _sp_c

    plan_path = os.path.abspath(plan_path)
    _ccl_log('INFO', f'Loading caption plan: {plan_path}')
    if not os.path.exists(plan_path):
        raise FileNotFoundError(f'Caption plan not found: {plan_path}')
    with open(plan_path) as _fh:
        plan = _ccl_json.load(_fh)

    _entries = plan.get('clips', [])
    _ccl_log('INFO', f'Caption plan: {len(_entries)} clips to process')
    results: dict = {'success': 0, 'failed': 0, 'outputs': []}

    _STYLE_Y = {'top': 'h*0.08', 'center': '(h-text_h)/2', 'bottom': 'h*0.85'}
    for _entry in _entries:
        _cp = _entry.get('clip_path', '')
        if not os.path.exists(_cp):
            _ccl_log('WARN', f'Clip not found, skipping: {_cp}')
            results['failed'] += 1
            continue
        _caps = _entry.get('captions', [])
        if not _caps:
            continue
        _base, _ext = os.path.splitext(_cp)
        _out = _base + '_captions' + _ext
        try:
            _dt_parts = []
            for _cap in _caps:
                _st = _hms_to_seconds(_cap.get('start', '0'))
                _et = _hms_to_seconds(_cap.get('end', '0'))
                _y = _STYLE_Y.get(_cap.get('style', 'bottom'), _STYLE_Y['bottom'])
                _txt = _cap.get('text', '').replace("'", "\\'").replace(':', '\\:')
                _dt_parts.append(
                    f"drawtext=text='{_txt}':fontsize=36:fontcolor=white:borderw=2"
                    f':bordercolor=black:x=(w-text_w)/2:y={_y}'
                    f":enable='between(t,{_st},{_et})'"
                )
            _cmd = [
                'ffmpeg',
                '-y',
                '-i',
                _cp,
                '-vf',
                ','.join(_dt_parts),
                '-c:v',
                'libx264',
                '-preset',
                'fast',
                '-crf',
                '20',
                '-c:a',
                'copy',
                _out,
            ]
            _res = _sp_c.run(_cmd, capture_output=True, timeout=300)
            if _res.returncode == 0:
                _ccl_log('INFO', f'✅ Captions applied → {os.path.basename(_out)}')
                results['success'] += 1
                results['outputs'].append(_out)
            else:
                raise RuntimeError(_res.stderr.decode()[-400:])
        except Exception as _e:
            _ccl_log('ERROR', f'Caption failed for {os.path.basename(_cp)}: {_e}')
            results['failed'] += 1

    _ccl_log('INFO', f'Caption plan complete — {results["success"]} applied, {results["failed"]} failed')
    return results


@bp.route('/api/zero/analyze', methods=['POST'])
@limiter.limit('10/hour')
def api_analyze_video():
    """Trigger video analysis for Claude. POST {video_path, output_path?}"""
    data = request.get_json(silent=True) or {}
    video_path = (data.get('video_path') or '').strip()
    if not video_path:
        return jsonify({'success': False, 'error': 'video_path required'}), 400
    output_path = data.get('output_path') or None

    def _run():
        try:
            analyze_video_for_claude(video_path, output_path)
        except Exception as _e:
            _agent_log('ERROR', 'API', 'api', 'analyze_video', str(_e))

    _ccl_threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'message': 'Analysis started — check Live Tail for progress'})


@bp.route('/api/zero/execute_plan', methods=['POST'])
@limiter.limit('10/hour')
def api_execute_plan():
    """
    Execute a Claude plan JSON.
    POST { plan_type: "clip" | "sfx" | "caption", plan_path: "..." }
    """
    data = request.get_json(silent=True) or {}
    plan_type = (data.get('plan_type') or 'clip').strip()
    plan_path = (data.get('plan_path') or '').strip()
    if not plan_path:
        return jsonify({'success': False, 'error': 'plan_path required'}), 400

    _fn_map = {
        'clip': execute_claude_clip_plan,
        'sfx': execute_sfx_plan,
        'caption': execute_caption_plan,
    }
    if plan_type not in _fn_map:
        return jsonify({'success': False, 'error': f'plan_type must be one of: {list(_fn_map.keys())}'}), 400

    def _run():
        try:
            _fn_map[plan_type](plan_path)
        except Exception as _e:
            _agent_log('ERROR', 'API', 'api', f'execute_{plan_type}_plan', str(_e))

    _ccl_threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'message': f'{plan_type} plan execution started — check Live Tail'})


@bp.route('/api/zero/token_usage')
@limiter.exempt
def api_token_usage():
    """Return token usage log and session totals."""
    # Load from disk (full history) then merge with in-memory (latest)
    try:
        if os.path.exists(_TOKEN_USAGE_PATH):
            with open(_TOKEN_USAGE_PATH) as _f:
                entries = json.load(_f)
        else:
            entries = list(_TOKEN_USAGE_LOG)
    except Exception:
        entries = list(_TOKEN_USAGE_LOG)

    total_prompt = sum(e.get('prompt_tokens', 0) for e in entries)
    total_completion = sum(e.get('completion_tokens', 0) for e in entries)
    total_tokens = total_prompt + total_completion
    by_model: dict = {}
    for e in entries:
        m = e.get('model', 'unknown')
        if m not in by_model:
            by_model[m] = {'prompt': 0, 'completion': 0, 'calls': 0}
        by_model[m]['prompt'] += e.get('prompt_tokens', 0)
        by_model[m]['completion'] += e.get('completion_tokens', 0)
        by_model[m]['calls'] += 1

    return jsonify(
        {
            'entries': list(reversed(entries[-200:])),  # newest first, max 200
            'totals': {
                'prompt_tokens': total_prompt,
                'completion_tokens': total_completion,
                'total_tokens': total_tokens,
                'calls': len(entries),
            },
            'by_model': by_model,
        }
    )
