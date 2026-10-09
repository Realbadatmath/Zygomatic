# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import subprocess

# 2026-07-17 batch-2 fix: subproc helpers moved to subproc_registry (direct import —
# main's re-export binds too late for the engine import chain)
from zyg_workflows.subproc_registry import _register_subproc, _finish_subproc
from zyg_workflows.pipeline_config import (
    _FORCE_CPU_POST_ENCODE,
    _KB_ENCODE_WAIT_MIN_S,
    _KB_ENCODE_WAIT_PAD_S,
    _KB_ENCODE_WAIT_PER_DUR_S,
)

# `_log` used to be read off the GUI module, where no such global exists; the one
# WARNING below is exactly what the runtime error-log hook takes.
from zyg_workflows.runtime import NVENC_SEM as _NVENC_SEM, _push_error_log as _log


def _kb_encode_wait_seconds(dur_s: float) -> int:
    """ffmpeg wait for one KB clip; scales with slot duration — do not hardcode timeout=120."""
    return max(
        _KB_ENCODE_WAIT_MIN_S,
        int(float(dur_s) * _KB_ENCODE_WAIT_PER_DUR_S) + _KB_ENCODE_WAIT_PAD_S,
    )


def _cq_for_crf(crf: int) -> int:
    """Map libx264 CRF to h264_nvenc CQ (visually similar at VBR)."""
    return max(15, min(30, int(crf) - 1))


def _nvenc_vcodec_args(cq: int = 20, preset: str = 'p4', pix_fmt: str = 'yuv420p') -> list:
    _args = ['-c:v', 'h264_nvenc', '-preset', preset, '-rc', 'vbr', '-cq', str(cq), '-b:v', '0']
    if pix_fmt:
        _args += ['-pix_fmt', pix_fmt]
    return _args


def _x264_vcodec_args(crf: int = 20, preset: str = 'fast', pix_fmt: str = 'yuv420p') -> list:
    _args = ['-c:v', 'libx264', '-preset', preset, '-crf', str(crf)]
    if pix_fmt:
        _args += ['-pix_fmt', pix_fmt]
    return _args


def _ffmpeg_run_nvenc_first(
    cmd_nvenc: list, cmd_x264: list, timeout: int, log_fn=None, label: str = 'ffmpeg'
) -> 'subprocess.CompletedProcess':
    """Run ffmpeg with NVENC; on failure run libx264 fallback."""
    import subprocess as _sp_enc

    if _FORCE_CPU_POST_ENCODE:
        return _sp_enc.run(cmd_x264, capture_output=True, timeout=timeout)
    try:
        with _NVENC_SEM:
            _r = _sp_enc.run(cmd_nvenc, capture_output=True, timeout=timeout)
        if _r.returncode == 0:
            if log_fn:
                log_fn(f'{label}: NVENC OK')
            return _r
        _err = (_r.stderr or b'').decode('utf-8', errors='replace')[-300:]
    except Exception as _nv_e:
        _err = str(_nv_e)
    if log_fn:
        log_fn(f'{label}: NVENC failed — libx264 fallback ({_err})')
    return _sp_enc.run(cmd_x264, capture_output=True, timeout=timeout)


def _ffmpeg_popen_nvenc_first(
    cmd_nvenc: list, cmd_x264: list, timeout: int, pipeline_id: str = '', label: str = 'ffmpeg'
) -> 'tuple[int, bytes, bytes]':
    """Popen + communicate with NVENC first; returns (returncode, stdout, stderr)."""
    import subprocess as _sp_enc

    if _FORCE_CPU_POST_ENCODE:
        _p = _sp_enc.Popen(cmd_x264, stdout=_sp_enc.PIPE, stderr=_sp_enc.PIPE)
        if pipeline_id:
            _register_subproc(_p.pid, f'{label}-cpu', pipeline_id)
        _out, _err = _p.communicate(timeout=timeout)
        if pipeline_id:
            _finish_subproc(_p.pid, ok=(_p.returncode == 0))
        return _p.returncode, _out, _err

    with _NVENC_SEM:
        _p = _sp_enc.Popen(cmd_nvenc, stdout=_sp_enc.PIPE, stderr=_sp_enc.PIPE)
    if pipeline_id:
        _register_subproc(_p.pid, label, pipeline_id)
    _out, _err = _p.communicate(timeout=timeout)
    if pipeline_id:
        _finish_subproc(_p.pid, ok=(_p.returncode == 0))
    if _p.returncode == 0:
        return 0, _out, _err

    if pipeline_id:
        _log(
            'WARNING',
            label,
            f'NVENC encode failed ({_p.returncode}) — libx264 fallback: {_err.decode(errors="replace")[-200:]}',
        )
    _p2 = _sp_enc.Popen(cmd_x264, stdout=_sp_enc.PIPE, stderr=_sp_enc.PIPE)
    if pipeline_id:
        _register_subproc(_p2.pid, f'{label}-cpu', pipeline_id)
    _out2, _err2 = _p2.communicate(timeout=timeout)
    if pipeline_id:
        _finish_subproc(_p2.pid, ok=(_p2.returncode == 0))
    return _p2.returncode, _out2, _err2
