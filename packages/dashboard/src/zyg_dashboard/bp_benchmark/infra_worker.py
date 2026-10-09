# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""bp_benchmark — the infrastructure benchmark worker.

Moved verbatim out of bp_benchmark.py; see the package __init__ for the full rationale.
"""

from zyg_dashboard.crewai_web_gui import _bm_infra_lock
from zyg_dashboard.gui.runtime_state import _runtime_path
from zyg_workflows.bin import exe
import json
import os
from zyg_dashboard.bp_benchmark.state import _bm_infra_runs, _recent_state_files, _zyg_log


def _bm_infra_worker(run_id: str, pipeline: str, seed_id: str) -> None:
    """Quick infrastructure benchmark: file I/O, FFmpeg probe + thumbnail, text parsing, JSON I/O."""
    import time as _t
    import subprocess as _sp
    import tempfile as _tmp

    def _add(name: str, elapsed: float, detail: str, ok: bool) -> None:
        with _bm_infra_lock:
            if run_id not in _bm_infra_runs:
                return
            _bm_infra_runs[run_id]['stages'].append(
                {
                    'name': name,
                    'elapsed_s': round(elapsed, 4),
                    'detail': detail,
                    'status': 'completed' if ok else 'failed',
                }
            )

    def _setstatus(s: str) -> None:
        with _bm_infra_lock:
            if run_id in _bm_infra_runs:
                import time as _tt

                _bm_infra_runs[run_id]['status'] = s
                if s in ('completed', 'error'):
                    _bm_infra_runs[run_id]['ended_at'] = _tt.time()

    try:
        _setstatus('running')

        # ── Find seed state ──────────────────────────────────────────────
        seed = None
        if seed_id:
            _sf = _runtime_path(f'pipeline_{seed_id}_state.json')
            if os.path.exists(_sf):
                with open(_sf, 'r', encoding='utf-8') as _fh:
                    seed = json.load(_fh)
        if not seed:
            for _sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 200):
                try:
                    with open(_sf, 'r', encoding='utf-8') as _fh:
                        _s = json.load(_fh)
                    if (_s.get('department') or '').lower() == pipeline and _s.get('ended'):
                        seed = _s
                        break
                except Exception as _exc:
                    _zyg_log.debug('skipping candidate state file that could not be read: %s', _exc)
        if not seed:
            _add('Setup', 0, f'No completed {pipeline} run found — run a pipeline first', False)
            _setstatus('error')
            return

        # ── Stage 1: File I/O ────────────────────────────────────────────
        img_paths = seed.get('image_paths') or []
        existing = [p for p in img_paths if p and os.path.exists(p)]
        t0 = _t.time()
        total_bytes = 0
        for p in existing[:30]:
            with open(p, 'rb') as _fh:
                total_bytes += len(_fh.read())
        elapsed_io = _t.time() - t0
        _add(
            'File I/O',
            elapsed_io,
            f'{len(existing)}/{len(img_paths)} images on disk · {round(total_bytes / 1_048_576, 1)} MB read'
            if existing
            else 'no images found for seed job',
            bool(existing),
        )

        # ── Stage 2: FFmpeg probe ────────────────────────────────────────
        vpath = seed.get('video_path') or ''
        if vpath and os.path.exists(vpath):
            t0 = _t.time()
            try:
                _r = _sp.run(
                    [exe('ffprobe'), '-v', 'quiet', '-print_format', 'json', '-show_streams', vpath],
                    capture_output=True,
                    timeout=30,
                )
                elapsed_probe = _t.time() - t0
                vmb = round(os.path.getsize(vpath) / 1_048_576, 1)
                _add(
                    'FFmpeg Probe',
                    elapsed_probe,
                    f'{vmb} MB video · probed in {round(elapsed_probe * 1000)} ms',
                    _r.returncode == 0,
                )
            except Exception as _exc:
                _add('FFmpeg Probe', _t.time() - t0, str(_exc), False)
        else:
            _add('FFmpeg Probe', 0, 'No video file on disk for seed job', False)

        # ── Stage 3: FFmpeg thumbnail ────────────────────────────────────
        if vpath and os.path.exists(vpath):
            t0 = _t.time()
            try:
                with _tmp.TemporaryDirectory() as _td:
                    _out = os.path.join(_td, 'thumb.jpg')
                    _r2 = _sp.run(
                        [exe('ffmpeg'), '-y', '-ss', '5', '-i', vpath, '-vframes', '1', '-q:v', '2', _out],
                        capture_output=True,
                        timeout=60,
                    )
                    elapsed_thumb = _t.time() - t0
                    _sz = os.path.getsize(_out) / 1024 if os.path.exists(_out) else 0
                    _add(
                        'FFmpeg Thumbnail',
                        elapsed_thumb,
                        f'1 frame extracted · {round(_sz, 1)} KB · {round(elapsed_thumb * 1000)} ms',
                        _r2.returncode == 0,
                    )
            except Exception as _exc:
                _add('FFmpeg Thumbnail', _t.time() - t0, str(_exc), False)

        # ── Stage 4: Text processing ─────────────────────────────────────
        script = seed.get('script') or seed.get('essay_text') or ''
        if script:
            t0 = _t.time()
            words = len(script.split())
            lines = script.splitlines()
            _ = [len(ln.encode()) for ln in lines]
            elapsed_txt = _t.time() - t0
            _add(
                'Text Processing',
                elapsed_txt,
                f'{words:,} words · {len(lines):,} lines · {round(elapsed_txt * 1_000_000)} µs',
                True,
            )

        # ── Stage 5: JSON state I/O ──────────────────────────────────────
        t0 = _t.time()
        _ser = json.dumps(seed)
        _ = json.loads(_ser)
        elapsed_json = _t.time() - t0
        _add(
            'JSON State I/O',
            elapsed_json,
            f'{round(len(_ser) / 1024, 1)} KB round-tripped · {round(elapsed_json * 1_000_000)} µs',
            True,
        )

        # ── Stage 6: RAM throughput ───────────────────────────────────────
        try:
            _SIZE_MB = 256
            _SIZE = _SIZE_MB * 1_048_576
            t0 = _t.time()
            _buf = bytearray(_SIZE)
            for _i in range(0, _SIZE, 4096):
                _buf[_i] = _i & 0xFF
            _elapsed_w = _t.time() - t0
            t0 = _t.time()
            _mv = memoryview(_buf)
            _ = bytes(_mv[: _SIZE_MB * 1_048_576])
            _elapsed_r = _t.time() - t0
            del _buf, _mv, _
            _w_mbs = round(_SIZE_MB / max(_elapsed_w, 1e-6))
            _r_mbs = round(_SIZE_MB / max(_elapsed_r, 1e-6))
            _add(
                'RAM Throughput',
                _elapsed_w + _elapsed_r,
                f'{_SIZE_MB} MB · write {_w_mbs} MB/s · read {_r_mbs} MB/s',
                True,
            )
        except Exception as _exc:
            _add('RAM Throughput', 0, str(_exc), False)

        # ── Stage 7: GPU / VRAM snapshot (nvidia-smi) ────────────────────
        try:
            t0 = _t.time()
            _r = _sp.run(
                [
                    'nvidia-smi',
                    '--query-gpu=name,memory.used,memory.free,memory.total,utilization.gpu,temperature.gpu',
                    '--format=csv,noheader,nounits',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _elapsed_nv = _t.time() - t0
            if _r.returncode == 0 and _r.stdout.strip():
                _parts = [p.strip() for p in _r.stdout.strip().splitlines()[0].split(',')]
                _nm = _parts[0] if _parts else '?'

                def _f(v):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return None

                _mu, _mfr, _mt = _f(_parts[1]), _f(_parts[2]), _f(_parts[3])
                _util = _f(_parts[4]) if len(_parts) > 4 else None
                _temp = _f(_parts[5]) if len(_parts) > 5 else None
                _detail = f'{_nm}'
                if _mt:
                    _detail += f' · VRAM {round((_mu or 0) / 1024, 1)}/{round(_mt / 1024, 1)} GB'
                if _util is not None:
                    _detail += f' · {_util:.0f}% utilization'
                if _temp is not None:
                    _detail += f' · {_temp:.0f}°C'
                _add('GPU / VRAM', _elapsed_nv, _detail, True)
            else:
                _add('GPU / VRAM', _elapsed_nv, 'nvidia-smi returned no output', False)
        except FileNotFoundError:
            _add('GPU / VRAM', 0, 'nvidia-smi not found', False)
        except Exception as _exc:
            _add('GPU / VRAM', 0, str(_exc), False)

        # ── Stage 8: GPU compute (CUDA matmul via torch) ──────────────────
        try:
            import torch as _torch

            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
                _N = 4096
                _a = _torch.randn(_N, _N, device='cuda', dtype=_torch.float32)
                _b = _torch.randn(_N, _N, device='cuda', dtype=_torch.float32)
                _torch.cuda.synchronize()
                t0 = _t.time()
                _c = _torch.mm(_a, _b)
                _torch.cuda.synchronize()
                _elapsed_mm = _t.time() - t0
                _vm_mb = round(_torch.cuda.memory_allocated() / 1_048_576)
                _tflops = round(2 * _N**3 / max(_elapsed_mm, 1e-9) / 1e12, 2)
                del _a, _b, _c
                _torch.cuda.empty_cache()
                _add(
                    'GPU Compute',
                    _elapsed_mm,
                    f'{_N}×{_N} FP32 matmul · {round(_elapsed_mm * 1000)} ms · {_tflops} TFLOPS · {_vm_mb} MB VRAM peak',
                    True,
                )
            else:
                _add('GPU Compute', 0, 'CUDA not available (torch installed but no GPU)', False)
        except ImportError:
            _add('GPU Compute', 0, 'torch not installed', False)
        except Exception as _exc:
            _add('GPU Compute', 0, str(_exc), False)

        _setstatus('completed')

    except Exception as _exc:
        with _bm_infra_lock:
            if run_id in _bm_infra_runs:
                _bm_infra_runs[run_id]['stages'].append(
                    {
                        'name': 'Error',
                        'elapsed_s': 0,
                        'detail': str(_exc),
                        'status': 'failed',
                    }
                )
                _bm_infra_runs[run_id]['status'] = 'error'
                import time as _tt

                _bm_infra_runs[run_id]['ended_at'] = _tt.time()
