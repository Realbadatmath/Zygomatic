"""pipeline_scholarly.render_kb — the shared Ken-Burns still renderer.

Lines 1427-1599 of the original pipeline_scholarly.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from zyg_workflows.bin import exe
from zyg_workflows.encode_utils import _cq_for_crf
from zyg_workflows.encode_utils import _kb_encode_wait_seconds
from zyg_workflows.encode_utils import _nvenc_vcodec_args
from zyg_workflows.encode_utils import _x264_vcodec_args
from zyg_workflows.pipeline_config import _FORCE_CPU_POST_ENCODE
from zyg_workflows.runtime import _NVENC_SEM
import os
import logging as _zyg_logging

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


def _render_kb_pil_shared(
    img_path_, out_path_, dur_, fps_, slot_idx_, shot_type_, emotion_, focal_zone_, slide_w=1920, slide_h=1080
):
    """Module-level Ken Burns PIL renderer. Used by the Storyteller pipeline."""
    from PIL import Image as _PIL_I
    import subprocess as _sp_kb

    try:
        _img = _PIL_I.open(img_path_).convert('RGB')
    except Exception as _ie:
        _zyg_log.info(
            f'[KB-shared] PIL open failed for slot {slot_idx_}: {_ie}'
        )  # 2026-07-24: _log was a closure NameError here
        return False
    _IW, _IH = _img.size
    _n = max(2, round(dur_ * fps_))
    _sl = (shot_type_ or '').lower()
    _emo = (emotion_ or 'calm').lower()
    _fz = (focal_zone_ or 'center').lower()

    _spd = {
        'shock': 1.5,
        'tension': 1.4,
        'triumph': 1.1,
        'awe': 1.0,
        'unease': 0.85,
        'mystery': 0.8,
        'calm': 0.7,
        'grief': 0.55,
    }.get(_emo, 1.0)

    if _fz == 'center':
        _ctr_anchors = [
            (0.50, 0.45),
            (0.55, 0.50),
            (0.50, 0.55),
            (0.45, 0.50),
            (0.50, 0.50),
            (0.52, 0.47),
            (0.48, 0.52),
            (0.52, 0.53),
        ]
        _ax, _ay = _ctr_anchors[slot_idx_ % len(_ctr_anchors)]
    else:
        _ax = {'left': 0.25, 'right': 0.75}.get(_fz, 0.50)
        _ay = {'top': 0.20, 'bottom': 0.80}.get(_fz, 0.50)

    _z_delta = 0.0
    _z_fixed = 1.0
    if 'extreme' in _sl or 'tight' in _sl:
        _motion = 'push_in'
        _z_delta = 0.06 * _spd
    elif 'close' in _sl:
        _motion = 'push_in'
        _z_delta = 0.10 * _spd
    elif any(_k in _sl for _k in ('overhead', 'drone', 'aerial', 'bird')):
        _motion = 'drift'
        _z_fixed = 1.0 + 0.07 * _spd
    elif 'wide' in _sl or 'establishing' in _sl:
        _motion = 'pan_r' if slot_idx_ % 2 == 0 else 'pan_l'
        _z_fixed = 1.0 + 0.08 * _spd
    else:
        _motion = 'pull_out' if slot_idx_ % 3 == 2 else 'push_in'
        _z_delta = 0.10 * _spd

    _z_max = 1.0 + _z_delta

    try:
        _EXTENT_M = _PIL_I.Transform.EXTENT
        _BICUBIC_R = _PIL_I.Resampling.BICUBIC
    except AttributeError:
        _EXTENT_M = _PIL_I.EXTENT  # type: ignore[attr-defined]
        _BICUBIC_R = _PIL_I.BICUBIC  # type: ignore[attr-defined]

    _kb_prefix = [
        exe('ffmpeg'),
        '-y',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        '-s',
        f'{slide_w}x{slide_h}',
        '-r',
        str(fps_),
        '-i',
        'pipe:0',
    ]
    _kb_cmd = _kb_prefix + _nvenc_vcodec_args(_cq_for_crf(15), 'p3') + [out_path_]
    _kb_cmd_cpu = _kb_prefix + _x264_vcodec_args(15, 'ultrafast') + [out_path_]
    _kb_wait_s = _kb_encode_wait_seconds(dur_)

    def _kb_run_encode(_proc):
        for _t in range(_n):
            _prog = _t / (_n - 1) if _n > 1 else 0.0

            if _motion == 'push_in':
                _z = 1.0 + _z_delta * _prog
            elif _motion == 'pull_out':
                _z = _z_max - _z_delta * _prog
            else:
                _z = _z_fixed

            _vw = _IW / _z
            _vh = _IH / _z

            if _motion in ('push_in', 'pull_out'):
                _cx = _ax * _IW
                _cy = _ay * _IH
            elif _motion == 'pan_r':
                _x0 = _vw / 2
                _x1 = _IW - _vw / 2
                _cx = _x0 + (_x1 - _x0) * _prog
                _cy = _ay * _IH
            elif _motion == 'pan_l':
                _x0 = _IW - _vw / 2
                _x1 = _vw / 2
                _cx = _x0 + (_x1 - _x0) * _prog
                _cy = _ay * _IH
            else:
                _xrng = max(0.0, _IW - _vw)
                _yrng = max(0.0, _IH - _vh)
                if slot_idx_ % 2 == 0:
                    _cx = _vw / 2 + _xrng * 0.5 * _prog
                    _cy = _vh / 2 + _yrng * 0.3 * _prog
                else:
                    _cx = _IW - _vw / 2 - _xrng * 0.5 * _prog
                    _cy = _vh / 2 + _yrng * 0.3 * _prog

            _left = max(0.0, min(_cx - _vw / 2, _IW - _vw))
            _top = max(0.0, min(_cy - _vh / 2, _IH - _vh))
            _right = _left + _vw
            _bottom = _top + _vh

            _frame = _img.transform(
                (slide_w, slide_h),
                _EXTENT_M,
                (_left, _top, _right, _bottom),
                resample=_BICUBIC_R,
            )
            _proc.stdin.write(_frame.tobytes())

        _proc.stdin.close()
        _proc.wait(timeout=_kb_wait_s)
        return _proc.returncode == 0 and os.path.getsize(out_path_) > 1000

    try:
        if _FORCE_CPU_POST_ENCODE:
            _proc = _sp_kb.Popen(_kb_cmd_cpu, stdin=_sp_kb.PIPE, stderr=_sp_kb.DEVNULL)
            return _kb_run_encode(_proc)
        with _NVENC_SEM:
            _proc = _sp_kb.Popen(_kb_cmd, stdin=_sp_kb.PIPE, stderr=_sp_kb.DEVNULL)
            return _kb_run_encode(_proc)
    except BrokenPipeError:
        try:
            _proc.wait()
        except Exception as _exc:  # noqa: BLE001 — _proc is unbound when Popen itself failed
            _zyg_log.debug('KB encoder not reaped after a broken pipe, init may have failed: %s', _exc)
        return False
    except Exception as _re:
        _zyg_log.info(
            f'[KB-shared] PIL render error slot {slot_idx_}: {_re}'
        )  # 2026-07-24: _log was a closure NameError here
        try:
            _proc.kill()
        except Exception as _exc:  # noqa: BLE001 — _proc is unbound when Popen itself failed
            _zyg_log.debug('KB encoder not killed after a render error, it may leak: %s', _exc)
        return False
    finally:
        try:
            _img.close()
        except OSError as _exc:
            _zyg_log.debug('KB source image not closed for slot %s: %s', slot_idx_, _exc)
