# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage 4b clip post-processing: bleep, loudnorm, narrator mix."""

import os
from zyg_workflows.pipeline_config import _NARRATOR_OUTRO
from zyg_workflows.runtime import _POSTPROC_SEM
from zyg_workflows.tts_service import _bleep_audio_in_clip
from zyg_workflows.subproc_registry import _finish_subproc
from zyg_workflows.subproc_registry import _register_subproc
from zyg_workflows.bin import exe
from zyg_workflows import gui_state

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.stage_runner')


def _make_post_process_clip(_log_err, _log_info, _log_warn, pipeline_id):
    """Build Stage 4b's clip post-processor.

    The ``if True`` is an indentation guard: it keeps the block below at the
    depth it had inside _stage_preflight, so the move is byte-for-byte
    (original lines 1870-2077).
    """
    if True:

        def _post_process_clip(
            clip_path_: str,
            vid_id_: str,
            clip_start_: float,
            clip_dur_: float,
            tx_path_: str,
            clip_idx_: int,
            clip_title_: str = '',
            narrator_line_: str = '',
            sfx_plan_: list = None,
            react_plan_: list = None,
        ) -> str:
            """Apply outro text overlay, audio bleep and loudness normalisation.
            All ffmpeg subprocesses are registered so Stop kills them immediately.
            Runs under _POSTPROC_SEM to cap concurrent GPU/CPU post-process load."""
            import tempfile as _tmpp
            import subprocess as _spp
            import shutil as _shu

            try:
                from zyg_workflows import cpu_cap as _cpu_cap_pp

                _PPtaskset = _cpu_cap_pp.taskset_prefix()
            except Exception:
                _PPtaskset = ['taskset', '-c', '0-19']

            _log_info(
                f'Stage 4b FX {vid_id_} clip{clip_idx_}: post-process start (title="{clip_title_[:40]}", dur={clip_dur_:.0f}s)'
            )

            if not os.path.exists(clip_path_):
                _log_warn(f'Stage 4b FX {vid_id_} clip{clip_idx_}: clip file missing — skipping post-process')
                return clip_path_

            with _POSTPROC_SEM:
                # ── Check stop flag before starting any work ──
                if gui_state._pipeline_stop_flag:
                    _log_info(f'Stage 4b FX {vid_id_} clip{clip_idx_}: stopped by user — skipping post-process')
                    return clip_path_

                # ── OUTRO: text overlay on playing video (no TTS, no freeze) ──
                _outro_line = _NARRATOR_OUTRO
                tmp_dir_ = _tmpp.mkdtemp(prefix='zyg_fx_')
                try:
                    _words_o = _outro_line.split()
                    _lines_o, _cur_o = [], ''
                    for _w in _words_o:
                        if len(_cur_o) + len(_w) + 1 > 45:
                            _lines_o.append(_cur_o.strip())
                            _cur_o = _w + ' '
                        else:
                            _cur_o += _w + ' '
                    if _cur_o.strip():
                        _lines_o.append(_cur_o.strip())
                    _outro_txt_file = os.path.join(tmp_dir_, 'outro.txt')
                    with open(_outro_txt_file, 'w') as _otf:
                        _otf.write('\n'.join(_lines_o))

                    _show_from = max(clip_dur_ - 8.0, clip_dur_ * 0.90)
                    _out_outro = os.path.join(tmp_dir_, 'fx_outro.mp4')
                    cmd_outro = _PPtaskset + [
                        exe('ffmpeg'),
                        '-y',
                        '-i',
                        clip_path_,
                        '-vf',
                        (
                            f"drawtext=textfile='{_outro_txt_file}':"
                            f'fontcolor=white:fontsize=30:borderw=2:bordercolor=black@0.9:'
                            f'box=1:boxcolor=black@0.5:boxborderw=10:'
                            f'x=(w-text_w)/2:y=40:line_spacing=6:'
                            f"enable='gte(t,{_show_from:.3f})'"
                        ),
                        '-c:v',
                        'libx264',
                        '-preset',
                        'veryfast',
                        '-crf',
                        '20',
                        '-threads',
                        '2',
                        '-c:a',
                        'copy',
                        _out_outro,
                    ]
                    _proc_outro = _spp.Popen(cmd_outro, stdout=_spp.PIPE, stderr=_spp.PIPE)
                    _register_subproc(_proc_outro.pid, f'outro-overlay {vid_id_} clip{clip_idx_}', pipeline_id)
                    _stdout_o, _stderr_o = _proc_outro.communicate(timeout=600)
                    _finish_subproc(_proc_outro.pid, ok=(_proc_outro.returncode == 0))
                    if _proc_outro.returncode == 0 and os.path.exists(_out_outro) and os.path.getsize(_out_outro) > 0:
                        _shu.move(_out_outro, clip_path_)
                        _log_info(f'Stage 4b FX {vid_id_} clip{clip_idx_}: outro text overlay from {_show_from:.1f}s ✓')
                    else:
                        _log_warn(
                            f'Stage 4b FX {vid_id_} clip{clip_idx_}: ⚠ outro overlay failed '
                            f'(rc={_proc_outro.returncode}) — {_stderr_o.decode(errors="replace")[-200:].strip()}'
                        )
                except Exception as _fxe:
                    _log_err(f'Stage 4b post-process {vid_id_} clip{clip_idx_}', str(_fxe))
                finally:
                    try:
                        import shutil as _shu2

                        _shu2.rmtree(tmp_dir_, ignore_errors=True)
                    except Exception as _exc:
                        _zyg_log.debug('temp dir %s cleanup skipped: %s', tmp_dir_, _exc)

                # ── Check stop flag between steps ──
                if gui_state._pipeline_stop_flag:
                    return clip_path_

                # ── Audio bleep pass ──
                _bleep_audio_in_clip(
                    clip_path_, tx_path_, clip_start_, clip_dur_, vid_id_, clip_idx_, _log_info, pipeline_id
                )

                # ── Check stop flag before loudnorm ──
                if gui_state._pipeline_stop_flag:
                    return clip_path_

                # ── Loudness normalization: EBU R128 — -14 LUFS / -1 dBTP true peak ──
                try:
                    import subprocess as _sp_ln
                    import tempfile as _tm_ln
                    import shutil as _sh_ln
                    import json as _js_ln

                    _ln_tmp = _tm_ln.mkdtemp(prefix='zyg_ln_')
                    _ln_out = os.path.join(_ln_tmp, 'norm.mp4')
                    # Pass 1 — measure loudness (analysis only, no output file)
                    _proc_ln1 = _sp_ln.Popen(
                        [
                            exe('ffmpeg'),
                            '-y',
                            '-i',
                            clip_path_,
                            '-af',
                            'loudnorm=I=-14:TP=-1:LRA=11:print_format=json',
                            '-f',
                            'null',
                            '-',
                        ],
                        stdout=_sp_ln.PIPE,
                        stderr=_sp_ln.PIPE,
                    )
                    _register_subproc(_proc_ln1.pid, f'loudnorm-pass1 {vid_id_} clip{clip_idx_}', pipeline_id)
                    _, _ln1_stderr = _proc_ln1.communicate(timeout=600)
                    _finish_subproc(_proc_ln1.pid, ok=True)
                    _stderr_lines = _ln1_stderr.decode(errors='replace').split('\n')
                    _ln_json = None
                    for _li, _ll in enumerate(_stderr_lines):
                        if '{' in _ll and 'input_i' in '\n'.join(_stderr_lines[_li : _li + 12]):
                            try:
                                _ln_json = _js_ln.loads('\n'.join(_stderr_lines[_li : _li + 12]))
                                break
                            except Exception as _exc:
                                _zyg_log.debug('loudnorm json not at stderr line %s, trying the next: %s', _li, _exc)
                    if _ln_json:
                        _af2 = (
                            f'loudnorm=I=-14:TP=-1:LRA=11:linear=true:'
                            f'measured_I={_ln_json["input_i"]}:measured_TP={_ln_json["input_tp"]}:'
                            f'measured_LRA={_ln_json["input_lra"]}:measured_thresh={_ln_json["input_thresh"]}:'
                            f'offset={_ln_json.get("target_offset", "0")}:print_format=summary'
                        )
                    else:
                        _af2 = 'loudnorm=I=-14:TP=-1:LRA=11'
                    # Pass 2 — apply correction
                    _proc_ln2 = _sp_ln.Popen(
                        [
                            exe('ffmpeg'),
                            '-y',
                            '-i',
                            clip_path_,
                            '-af',
                            _af2,
                            '-c:v',
                            'copy',
                            '-c:a',
                            'aac',
                            '-b:a',
                            '192k',
                            _ln_out,
                        ],
                        stdout=_sp_ln.PIPE,
                        stderr=_sp_ln.PIPE,
                    )
                    _register_subproc(_proc_ln2.pid, f'loudnorm-pass2 {vid_id_} clip{clip_idx_}', pipeline_id)
                    _, _ln2_stderr = _proc_ln2.communicate(timeout=600)
                    _finish_subproc(_proc_ln2.pid, ok=(_proc_ln2.returncode == 0))
                    if _proc_ln2.returncode == 0 and os.path.exists(_ln_out) and os.path.getsize(_ln_out) > 0:
                        _sh_ln.move(_ln_out, clip_path_)
                        _log_info(f'Stage 4b LOUDNORM {vid_id_} clip{clip_idx_}: normalised to -14 LUFS ✓')
                    else:
                        _log_warn(
                            f'Stage 4b LOUDNORM {vid_id_} clip{clip_idx_}: ⚠ loudnorm failed '
                            f'(rc={_proc_ln2.returncode}) — {_ln2_stderr.decode(errors="replace")[-200:].strip()}'
                        )
                except Exception as _lne:
                    _log_warn(f'Stage 4b LOUDNORM {vid_id_} clip{clip_idx_}: ⚠ exception — {_lne}')
                finally:
                    try:
                        import shutil as _sh_ln2

                        _sh_ln2.rmtree(_ln_tmp, ignore_errors=True)
                    except Exception as _exc:
                        _zyg_log.debug('temp dir %s cleanup skipped: %s', _ln_tmp, _exc)

            return clip_path_

        return _post_process_clip
