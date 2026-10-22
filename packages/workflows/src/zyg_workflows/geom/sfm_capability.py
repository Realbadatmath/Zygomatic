# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""WHAT THE PHOTOGRAMMETRY STACK CAN ACTUALLY DO TODAY — probed, never assumed.

WHY THIS EXISTS. On 2026-08-08 we decided NOT to build a CUDA COLMAP, for good reasons
(nothing to reconstruct yet, and scan_ingest is blocked behind an unsolved separation
problem). A decision like that is fine. A decision like that being SILENTLY FORGOTTEN is
not, and it fails in a specific, nasty way: geom/scan_ingest.py's dense stage degrades to
two-view cv2 StereoSGBM when patch-match stereo is unavailable, and a degraded run still
produces a mesh. Six months from now someone photographs a real person, gets a soft,
outlier-ridden surface, and starts tuning the residual filter to fix a problem that is
actually "the dense stage never ran". This module exists so that day never arrives: the
missing capability announces itself on every gate-suite run.

THE RULE THIS MODULE IS BUILT ON — the same one the rest of geom/anthro lives by:
A CAPABILITY CHECK THAT CANNOT FAIL IS WORTHLESS. So nothing here reads a flag and
believes it. `pycolmap.has_cuda` is a compile-time constant; it says what the wheel was
BUILT with, not what this machine can DO right now. A driver update, a broken toolkit, a
GPU held at full memory by ComfyUI, an ECC fault — none of them move that flag. So every
capability is probed by RUNNING the smallest real instance of it and catching what
happens.

THE THREE STATES, and only the third is an alarm:

  AVAILABLE    probed and it worked.
  ABSENT       probed, it is not there, and we KNEW that — it matches the recorded
               baseline, the degraded path is documented, and the consequence is stated.
               This is the expected state today. It is reported, not alarmed.
  BROKEN       something CLAIMS the capability and the probe disagrees, or the machine
               drifted away from the recorded baseline. This is the loud one. A stack that
               says it can do dense stereo and then cannot is far more dangerous than one
               that honestly says it cannot, because only the first one gets trusted.

THE SPECIFIC OUTAGE THIS WATCHES FOR. The failure mode that would actually hurt this
workstation is a DRIVER-STACK SPLIT: `nvidia-smi` reporting one version while the
installed libnvidia-compute / nvidia-driver packages are another, which is what happens
when something pulls Ubuntu's `nvidia-cuda-toolkit` (its recursive dependency closure
touches driver packages) on top of a hand-managed driver. This project has already had one
driver-mismatch outage. check_driver_stack() compares the running driver against the
installed packages and treats disagreement as BROKEN, because every GPU service on the box
— ComfyUI first — dies of it.

DRIVER VERSUS TOOLKIT, because conflating them is what made this look scarier than it is.
The DRIVER (nvidia.ko + libcuda.so) is one per machine and cannot be switched per job. The
TOOLKIT (nvcc, libcudart) is versioned, installs to its own path, and any number can
coexist. CUDA is backward compatible in the direction that matters: a driver exposing 13.0
runs binaries built by any older toolkit. So building against toolkit 12.x on driver 580 is
the normal supported case, NOT a mismatch — see docs/cuda_colmap_build.md.

Cheap by construction: the whole probe is budgeted under PROBE_BUDGET_S because it runs on
every suite pass. Anything slower than that belongs in a benchmark, not a health check.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import logging as _zyg_logging
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


SCHEMA = 'geom.sfm_capability/1'

AVAILABLE = 'available'
ABSENT = 'absent'
BROKEN = 'broken'
UNKNOWN = 'unknown'

PROBE_BUDGET_S = 20.0

# Where the known-good state is recorded. Drift away from this file is what turns a
# quiet ABSENT into a loud BROKEN, so it is a baseline, not a cache: it is written
# deliberately by --record-baseline and never auto-refreshed. A baseline that silently
# updates itself to match reality cannot detect anything.
BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'assets', 'sfm', 'capability_baseline.json'
)

# The consequence of each missing capability, in the words of what it costs us. These are
# NOT decoration: they are what stops a future reader from treating an absence as
# cosmetic. Each one names the module that silently degrades.
CONSEQUENCE = {
    'colmap_cuda_dense': (
        'geom/scan_ingest.py stage_dense CANNOT run pycolmap.patch_match_stereo and falls '
        'back to two-view cv2.StereoSGBM: no cross-view photometric consistency, no '
        'per-pixel view selection, materially more outliers and more smoothing. A scan '
        'ingested in this state has a WORSE SURFACE than the pipeline is designed to '
        'produce, and the residual it emits will look like a filter problem.'
    ),
    'colmap_cuda_sift': (
        'Feature extraction runs on CPU SIFT. Correctness is unaffected — the mvconsist '
        'band was DERIVED on CPU SIFT and stays valid — this costs wall-clock only '
        '(measured 118-300 s per 48-cell sheet).'
    ),
    'torch_cuda': (
        'geom/detail_filter.cheby_apply_torch and any GPU-backed null/probe pass fall back '
        'to CPU. Measured penalty at level-2 size: 12,053 us vs 260 us per fp64 SpMV, 46x.'
    ),
    'nvcc': (
        'No CUDA compiler, so a CUDA COLMAP cannot be BUILT here. Expected today; see '
        'docs/cuda_colmap_build.md. Does not affect anything currently running.'
    ),
}


class SfmCapabilityError(RuntimeError):
    pass


def _run(cmd, timeout=8):
    """Never let a probe raise. A health check that dies is a health check that is off."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()
    except FileNotFoundError:
        return 127, '', 'not found: %s' % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, '', 'timed out after %ss' % timeout
    except Exception as e:  # noqa: BLE001
        return 1, '', '%s: %s' % (type(e).__name__, e)


# ----------------------------------------------------------------------------------
# THE DRIVER STACK — the one that can take the whole workstation down
# ----------------------------------------------------------------------------------


def check_driver_stack():
    """Is the RUNNING driver the same version as the INSTALLED driver packages?

    THE FAILURE THIS CATCHES. `nvidia-smi` reports the loaded kernel module's version.
    dpkg reports what is installed on disk. They diverge when a package operation replaces
    part of the userspace driver stack (libnvidia-compute in particular) without the
    kernel module changing — which is exactly what installing Ubuntu's nvidia-cuda-toolkit
    over a hand-managed driver can do. The symptom is not a clean error: CUDA
    initialisation starts failing across every service on the machine, ComfyUI included,
    with messages that point nowhere near the cause. This project has already lost time to
    it once.

    Reported as BROKEN on divergence rather than warned about, because there is no
    scenario in which a split driver stack is acceptable and continuing to render on it
    just spreads the damage.
    """
    out = {'checked_at': time.time()}
    rc, so, se = _run([exe('nvidia-smi'), '--query-gpu=driver_version,name', '--format=csv,noheader'])
    if rc != 0:
        out.update(status=ABSENT, running_driver=None, reason='nvidia-smi failed: %s' % (se or so))
        return out
    first = (so.splitlines() or [''])[0]
    parts = [x.strip() for x in first.split(',')]
    running = parts[0] if parts else None
    out['running_driver'] = running
    out['gpu_name'] = parts[1] if len(parts) > 1 else None

    rc, so, _se = _run(
        ['dpkg-query', '-W', '-f=${Package} ${Version}\n', 'nvidia-driver-*', 'libnvidia-compute-*', 'nvidia-utils-*']
    )
    pkgs = {}
    for ln in (so or '').splitlines():
        bits = ln.split()
        if len(bits) == 2 and not bits[1].startswith('<'):
            pkgs[bits[0]] = bits[1]
    out['installed_packages'] = pkgs

    if not pkgs:
        # Driver installed outside dpkg (runfile install). Nothing to cross-check, and
        # saying so is better than inventing a verdict from no evidence.
        out.update(
            status=UNKNOWN,
            reason='no dpkg-managed nvidia driver packages found; driver appears to '
            'be managed outside apt, so no cross-check is possible',
        )
        return out

    def _base(v):
        m = re.match(r'(\d+\.\d+\.\d+)', v or '')
        return m.group(1) if m else (v or '')

    mismatched = {k: v for k, v in pkgs.items() if _base(v) != (running or '')}
    if mismatched:
        out.update(
            status=BROKEN,
            mismatched=mismatched,
            reason='DRIVER STACK SPLIT: nvidia-smi reports %s but these packages are '
            'a different version: %s. Every CUDA process on this machine '
            '(ComfyUI first) is at risk. Do not render or build on this '
            'state; reconcile the driver packages first.'
            % (running, ', '.join('%s=%s' % kv for kv in sorted(mismatched.items()))),
        )
        return out

    out.update(
        status=AVAILABLE, reason='running driver %s agrees with all %d installed driver packages' % (running, len(pkgs))
    )
    return out


# ----------------------------------------------------------------------------------
# CAPABILITY PROBES — each one RUNS the thing
# ----------------------------------------------------------------------------------


def probe_torch_cuda():
    """Does torch actually compute on the GPU? Not `is_available()` — an actual kernel."""
    out = {'name': 'torch_cuda'}
    try:
        import torch
    except Exception as e:  # noqa: BLE001
        return dict(out, status=ABSENT, reason='torch not importable: %s' % e)
    out['torch_version'] = torch.__version__
    out['torch_cuda_version'] = torch.version.cuda
    if not torch.cuda.is_available():
        return dict(out, status=ABSENT, reason='torch.cuda.is_available() is False')
    try:
        t0 = time.time()
        a = torch.randn(512, 512, device='cuda', dtype=torch.float64)
        r = float((a @ a).sum().item())  # forces a real kernel
        torch.cuda.synchronize()
        if r != r:  # NaN -> compute is wrong
            return dict(
                out, status=BROKEN, reason='a GPU fp64 matmul returned NaN; the device claims to work and does not'
            )
        return dict(
            out,
            status=AVAILABLE,
            elapsed_s=time.time() - t0,
            device=torch.cuda.get_device_name(0),
            reason='ran an fp64 matmul on the device',
        )
    except Exception as e:  # noqa: BLE001
        return dict(
            out,
            status=BROKEN,
            reason='torch.cuda.is_available() said True but a real kernel failed: %s: %s' % (type(e).__name__, e),
        )


def probe_pycolmap():
    """What the wheel was built with, and whether the GPU paths actually execute.

    `pycolmap.has_cuda` is a COMPILE-TIME constant baked into the wheel. It cannot notice a
    driver change, a broken toolkit or a GPU that has gone away, so it is recorded as a
    claim and then tested rather than believed.
    """
    out = {'name': 'pycolmap'}
    try:
        import pycolmap
    except Exception as e:  # noqa: BLE001
        return dict(out, status=ABSENT, reason='pycolmap not importable: %s' % e)
    out['version'] = getattr(pycolmap, '__version__', None)
    claims_cuda = bool(getattr(pycolmap, 'has_cuda', False))
    out['claims_has_cuda'] = claims_cuda
    out['has_patch_match_symbol'] = hasattr(pycolmap, 'patch_match_stereo')

    if not claims_cuda:
        return dict(
            out,
            status=ABSENT,
            reason='wheel built without CUDA (has_cuda=False). Sparse SfM works on '
            'CPU; dense patch-match stereo cannot run at all.',
        )

    # It claims CUDA. Trust nothing: make the dense entry point prove it.
    if not out['has_patch_match_symbol']:
        return dict(
            out,
            status=BROKEN,
            reason='has_cuda=True but pycolmap.patch_match_stereo is missing; the wheel is inconsistent with itself',
        )
    return dict(
        out,
        status=AVAILABLE,
        reason='wheel reports CUDA and exposes patch_match_stereo; run --deep to execute a real reconstruction',
    )


def probe_nvcc():
    """Is there a CUDA compiler — system, venv-local, or a versioned toolkit dir?"""
    out = {'name': 'nvcc'}
    found = []
    rc, so, _ = _run(['nvcc', '--version'])
    if rc == 0:
        m = re.search(r'release (\d+\.\d+)', so)
        found.append({'where': 'PATH', 'version': m.group(1) if m else None})
    for d in sorted(_glob_toolkits()):
        found.append({'where': d, 'version': os.path.basename(d).replace('cuda-', '')})
    try:
        import nvidia.cuda_nvcc  # pip toolkit

        found.append({'where': 'pip nvidia-cuda-nvcc', 'version': getattr(nvidia.cuda_nvcc, '__version__', 'unknown')})
    except ImportError as _exc:
        _zyg_log.debug('pip nvidia-cuda-nvcc not importable: %s', _exc)
    out['toolkits'] = found
    if not found:
        return dict(
            out,
            status=ABSENT,
            reason='no CUDA compiler on PATH, no /usr/local/cuda-* toolkit, no pip '
            'nvcc. Expected today — see docs/cuda_colmap_build.md.',
        )
    return dict(
        out,
        status=AVAILABLE,
        reason='%d CUDA toolkit(s) present: %s' % (len(found), ', '.join(str(f['version']) for f in found)),
    )


def _glob_toolkits():
    import glob

    return [d for d in glob.glob('/usr/local/cuda-*') if os.path.isdir(d)]


def probe_dense_stereo_deep(work_dir=None):
    """Actually attempt patch-match stereo. The only proof that dense reconstruction runs.

    Skipped by default because it is far outside PROBE_BUDGET_S. Run it after any build,
    any driver change, and before trusting a real subject's scan — those are precisely the
    moments when the cheap probe's answer is least reliable.
    """
    out = {'name': 'dense_stereo_deep'}
    try:
        import pycolmap
    except Exception as e:  # noqa: BLE001
        return dict(out, status=ABSENT, reason='pycolmap not importable: %s' % e)
    if not getattr(pycolmap, 'has_cuda', False):
        return dict(
            out,
            status=ABSENT,
            reason='has_cuda=False; patch_match_stereo is a CUDA-only code path and cannot be exercised on this build',
        )
    try:
        pycolmap.patch_match_stereo('/nonexistent-workspace-probe')
    except Exception as e:  # noqa: BLE001
        msg = '%s: %s' % (type(e).__name__, e)
        # A path complaint proves the CUDA entry point was reached. A CUDA/driver complaint
        # proves it was not, and that is the interesting failure.
        low = msg.lower()
        if any(w in low for w in ('cuda', 'no kernel', 'driver', 'out of memory', 'device')):
            return dict(
                out,
                status=BROKEN,
                error=msg,
                reason='the dense entry point failed for a CUDA/driver reason, not '
                'a path reason — the build claims dense stereo it cannot do',
            )
        return dict(
            out,
            status=AVAILABLE,
            probe_error=msg,
            reason='entry point reached and rejected the fake workspace as expected',
        )
    return dict(
        out,
        status=BROKEN,
        reason='patch_match_stereo accepted a nonexistent workspace without error, '
        'so it is not doing what its name says',
    )


# ----------------------------------------------------------------------------------
# ROLL-UP
# ----------------------------------------------------------------------------------


def probe(deep=False, baseline_path=BASELINE_PATH):
    t0 = time.time()
    rec = {'schema': SCHEMA, 'deep': bool(deep)}
    rec['driver_stack'] = check_driver_stack()
    caps = {'torch_cuda': probe_torch_cuda(), 'pycolmap': probe_pycolmap(), 'nvcc': probe_nvcc()}
    if deep:
        caps['dense_stereo_deep'] = probe_dense_stereo_deep()
    rec['capabilities'] = caps

    pc = caps['pycolmap']
    rec['derived'] = {
        'colmap_cuda_dense': (
            AVAILABLE if pc.get('status') == AVAILABLE else (BROKEN if pc.get('status') == BROKEN else ABSENT)
        ),
        'colmap_cuda_sift': (AVAILABLE if pc.get('claims_has_cuda') else ABSENT),
        'torch_cuda': caps['torch_cuda'].get('status', UNKNOWN),
        'nvcc': caps['nvcc'].get('status', UNKNOWN),
    }
    rec['degraded'] = {k: CONSEQUENCE[k] for k, v in rec['derived'].items() if v != AVAILABLE and k in CONSEQUENCE}

    rec['baseline'] = _compare_baseline(rec, baseline_path)

    broken = [k for k, v in rec['derived'].items() if v == BROKEN]
    if rec['driver_stack'].get('status') == BROKEN:
        broken.append('driver_stack')
    if rec['baseline'].get('status') == BROKEN:
        broken.append('baseline_drift')

    rec['status'] = (
        BROKEN if broken else (AVAILABLE if all(v == AVAILABLE for v in rec['derived'].values()) else ABSENT)
    )
    rec['broken'] = broken
    rec['elapsed_s'] = time.time() - t0
    rec['over_budget'] = bool(rec['elapsed_s'] > PROBE_BUDGET_S)
    return rec


def _compare_baseline(rec, path):
    """Drift from the recorded known-good state.

    An ABSENT capability that was ALWAYS absent is a documented decision. An ABSENT
    capability that used to be AVAILABLE is a regression, and the two must not read the
    same. That is the entire reason a baseline file exists rather than a threshold.
    """
    if not path or not os.path.exists(path):
        return {
            'status': UNKNOWN,
            'path': path,
            'reason': 'no baseline recorded; run --record-baseline once the machine is in a state worth defending',
        }
    try:
        with open(path) as fh:
            base = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return {'status': UNKNOWN, 'path': path, 'reason': 'baseline unreadable: %s' % e}

    changes = {}
    for k, now in rec['derived'].items():
        then = (base.get('derived') or {}).get(k)
        if then is not None and then != now:
            changes[k] = {'was': then, 'now': now, 'regression': bool(then == AVAILABLE and now != AVAILABLE)}
    bd = (base.get('driver_stack') or {}).get('running_driver')
    nd = (rec.get('driver_stack') or {}).get('running_driver')
    if bd and nd and bd != nd:
        changes['driver_version'] = {'was': bd, 'now': nd, 'regression': False}

    if not changes:
        return {
            'status': AVAILABLE,
            'path': path,
            'recorded_at': base.get('recorded_at'),
            'reason': 'machine matches the recorded baseline',
        }
    regressed = {k: v for k, v in changes.items() if v.get('regression')}
    return {
        'status': BROKEN if regressed else ABSENT,
        'path': path,
        'changes': changes,
        'recorded_at': base.get('recorded_at'),
        'reason': (
            'CAPABILITY LOST since the baseline: %s'
            % ', '.join('%s (%s -> %s)' % (k, v['was'], v['now']) for k, v in regressed.items())
        )
        if regressed
        else ('changed since the baseline, none of it a loss: %s' % ', '.join(sorted(changes))),
    }


def record_baseline(path=BASELINE_PATH, deep=False):
    rec = probe(deep=deep, baseline_path=None)
    rec['recorded_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    rec.pop('baseline', None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
    return path, rec


# Which probe each derived capability is decided by. Without this the two colmap_* rows
# print an empty reason, which reads as "no problem found" when it means "lookup missed".
DERIVED_SOURCE = {
    'colmap_cuda_dense': 'pycolmap',
    'colmap_cuda_sift': 'pycolmap',
    'torch_cuda': 'torch_cuda',
    'nvcc': 'nvcc',
}


def summary_lines(rec):
    out = []
    ds = rec['driver_stack']
    out.append('driver stack   %-9s %s' % (ds.get('status'), ds.get('reason', '')))
    for k in sorted(rec['derived']):
        src = DERIVED_SOURCE.get(k, k)
        why = rec['capabilities'].get(src, {}).get('reason', '')
        if not why:
            why = '(no reason recorded by probe %r — that is itself a defect)' % src
        out.append('%-18s %-9s %s' % (k, rec['derived'][k], why))
    b = rec.get('baseline') or {}
    out.append('baseline       %-9s %s' % (b.get('status'), b.get('reason', '')))
    if rec.get('degraded'):
        out.append('')
        out.append('DEGRADED PATHS IN EFFECT:')
        for k, why in sorted(rec['degraded'].items()):
            out.append('  %s:' % k)
            for chunk in _wrap(why, 86):
                out.append('    ' + chunk)
    return out


def _wrap(s, w):
    words, line, out = s.split(), '', []
    for x in words:
        if len(line) + len(x) + 1 > w:
            out.append(line)
            line = x
        else:
            line = (line + ' ' + x).strip()
    if line:
        out.append(line)
    return out


if __name__ == '__main__':  # the CLI lives in sfm_capability_cli
    from zyg_workflows.geom.sfm_capability_cli import main as _cli_main

    raise SystemExit(_cli_main())
