# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 5 — the script-mode probe and the capability gates built on it.

Moved verbatim out of the old single-file gates.py (lines 6550-7086).
"""

import json
import os
import subprocess
import sys
import tempfile

from zyg_workflows.geom.anthro.gates.policy import ERROR, FAIL, PASS, REPORT, _zyg_log
from zyg_workflows.geom.anthro.gates.gate import RECEIPT_KEY, _result
from zyg_workflows.geom.anthro.gates.tier5_form import ZYG_TIER5_FLAG, _FORM_MODULES, _tier5_enabled, form_module


# -- the import gate ---------------------------------------------------------------
# THE SCRIPT-MODE PROBE.
#
# THE DEFECT THIS CLOSES (D4). This gate used to test for the SUBSTRING 'sys.path.insert'
# in the module's source text. That is a spelling test, not a property test, and it fails
# in both directions — verified against a lesion module whose only occurrence of the string
# is inside a docstring: the gate returned PASS with missing_script_bootstrap=[] while the
# module genuinely raised ModuleNotFoundError in script mode. Symmetrically it would
# false-FAIL a module that bootstraps with sys.path.append, and pass one that inserts its
# OWN directory instead of the repo root.
#
# What is tested now is the property itself: run the file the way `python <file>` runs it —
# sys.path[0] is the file's own directory, the cwd is somewhere else entirely — and then ask
# whether `geom` is importable.
#
# THE FLAGS, and why they are exactly these. `-E` plus an env with PYTHONPATH/PYTHONHOME
# removed is what stops an inherited path from masking the failure, which was the original
# and correct objection to spawning a process. `-s` and `-I` are deliberately NOT used:
# they drop the USER site-packages, where this box keeps numpy and torch, so every module
# would fail on `ModuleNotFoundError: No module named 'numpy'` — measured, and it is the
# same class of false-FAIL as the sys.path.append case this fix exists to remove. A gate
# that fails everything is as useless as one that passes everything.
#
# The probe is falsified before it is trusted: _script_mode_negative_control() runs it
# against a generated module that has NO bootstrap, and the gate reports ERROR if that
# control does not come back MISSING. A probe that cannot fail is not evidence either.
#
# The result is a property of the REPOSITORY, not of a subject, so it is computed once per
# process and reused. A probe that cannot run is recorded as UNRESOLVED with its stderr, and
# an unresolved probe makes this gate ERROR — never a pass (rule 4).
_SCRIPT_MODE_PROBE = {}
_SCRIPT_MODE_PROBE_SRC = r"""
import os, runpy, sys
f = sys.argv[1]
sys.path[0] = os.path.dirname(os.path.abspath(f))   # exactly what `python <file>` does
try:
    runpy.run_path(f, run_name='__zyg_script_probe__')
except BaseException as e:
    sys.stdout.write('RUN_FAILED %s: %s\n' % (type(e).__name__, e))
    raise SystemExit(0)
import importlib.util as u
try:
    ok = u.find_spec('geom') is not None
except BaseException as e:
    ok = False
sys.stdout.write('GEOM_%s\n' % ('OK' if ok else 'MISSING'))
"""


def script_mode_probe(path, timeout=120.0):
    """(ok, how, code). `ok` is None when the probe itself could not run — never a pass.

    `code` is what a caller must branch on, and the reason it exists is that branching on
    the PROSE is the same class of defect as testing for a substring in a module's source:
    the negative control has to tell "rejected for the right reason" from "rejected because
    the probe is mis-configured", and it may not do that by looking for words.
      geom_ok        ran, and `geom` resolves afterwards
      geom_missing   ran, and `geom` does not resolve — the defect this gate is for
      run_failed     the module raised while being run as a script
      probe_failed / no_verdict   the probe itself did not produce an answer
    """
    key = os.path.abspath(path)
    if key in _SCRIPT_MODE_PROBE:
        return _SCRIPT_MODE_PROBE[key]
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONHOME')}
    try:
        with tempfile.TemporaryDirectory() as cwd:
            p = subprocess.run(
                [sys.executable, '-E', '-c', _SCRIPT_MODE_PROBE_SRC, key],
                cwd=cwd,
                env=env,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        out = (p.stdout or b'').decode('utf-8', 'replace')
        err = (p.stderr or b'').decode('utf-8', 'replace')
    except Exception as e:  # noqa: BLE001
        res = (
            None,
            'the script-mode probe could not be run (%s: %s), so this module was NOT checked' % (type(e).__name__, e),
            'probe_failed',
        )
        _SCRIPT_MODE_PROBE[key] = res
        return res
    if 'GEOM_OK' in out:
        res = (
            True,
            'ran as a script from a foreign cwd with PYTHONPATH scrubbed; `geom` '
            'resolves afterwards, so the module puts the repo root on sys.path '
            'itself',
            'geom_ok',
        )
    elif 'GEOM_MISSING' in out:
        res = (
            False,
            'ran as a script from a foreign cwd with PYTHONPATH scrubbed and '
            '`geom` DOES NOT resolve afterwards: every lazy `from geom import ...` '
            'inside this module will raise ModuleNotFoundError when a gate asks '
            'it for a number',
            'geom_missing',
        )
    elif 'RUN_FAILED' in out:
        res = (False, 'raised in script mode: %s' % out.split('RUN_FAILED', 1)[1].strip().splitlines()[0], 'run_failed')
    else:
        res = (
            None,
            'the script-mode probe produced no verdict (rc=%s). stderr tail: %s'
            % (getattr(p, 'returncode', '?'), (err or '').strip()[-300:]),
            'no_verdict',
        )
    _SCRIPT_MODE_PROBE[key] = res
    return res


_SCRIPT_MODE_CONTROL_SRC = (
    '"""A module with NO repo-root bootstrap. The words sys.path.insert appear in this\n'
    'docstring and nowhere else, which is exactly the lesion the old substring test\n'
    'passed. It must FAIL the script-mode probe."""\n'
    'import numpy as np\n'
    'VALUE = 1\n'
)
_SCRIPT_MODE_CONTROL = {}


def _script_mode_negative_control():
    """(ok, how). Does the probe REJECT a module that genuinely has no bootstrap?

    A test that has never rejected anything is not calibrated, and this one replaces a test
    that passed its own broken control. The lesion is the reviewer's: a module whose only
    occurrence of 'sys.path.insert' is inside a docstring. It also imports numpy, so a
    probe misconfigured to drop the user site-packages fails the control for the WRONG
    reason and is caught here rather than in the verdict.
    """
    if _SCRIPT_MODE_CONTROL:
        return _SCRIPT_MODE_CONTROL['result']
    try:
        d = tempfile.mkdtemp(prefix='zyg_script_control_')
        path = os.path.join(d, 'zyg_no_bootstrap_control.py')
        with open(path, 'w') as fh:
            fh.write(_SCRIPT_MODE_CONTROL_SRC)
        ok, how, code = script_mode_probe(path)
        try:  # the verdict is cached; the file is not
            os.remove(path)
            os.rmdir(d)
        except OSError as _exc:
            _zyg_log.debug('negative control temp cleanup skipped: %s', _exc)
    except Exception as e:  # noqa: BLE001
        res = (None, 'the negative control could not be built (%s: %s)' % (type(e).__name__, e))
        _SCRIPT_MODE_CONTROL['result'] = res
        return res
    if code == 'geom_missing':
        res = (
            True,
            'a module with no repo-root bootstrap is correctly REJECTED by the '
            'probe, and rejected for the RIGHT reason (code %r, not an import '
            'error): %s' % (code, how),
        )
    elif code == 'run_failed':
        # Rejected, but on an import error rather than on the missing bootstrap: the probe
        # is mis-configured (usually a dropped site-packages, e.g. -s or -I taking numpy
        # away) and its verdicts on the real modules are noise, not findings.
        res = (
            None,
            'the negative control was rejected for the WRONG reason (code %r: '
            '%s), so the probe is mis-configured and its verdicts cannot be '
            'trusted' % (code, how),
        )
    elif code == 'geom_ok':
        res = (
            False,
            'THE PROBE PASSED A MODULE WITH NO BOOTSTRAP. `geom` resolved from a '
            'foreign cwd anyway, so something outside these modules is putting '
            'the repo root on sys.path and this gate proves nothing: %s' % how,
        )
    else:
        res = (None, 'the negative control produced no verdict (code %r): %s' % (code, how))
    _SCRIPT_MODE_CONTROL['result'] = res
    return res


# The band, MIRRORED as a literal rather than imported at module scope. geom.mvconsist_band
# pulls in geom.mvconsist, which loads pycolmap — a 95 MB stripped extension — and the gate
# REGISTRY is built at import time, so importing it here would make every `python -m
# geom.anthro` invocation pay for a library that four of the five characters never touch.
#
# A mirrored constant is a drift risk, so it is not trusted: t4_multiview_consistency
# compares this literal against the live MVB.BAND on every run and reports a mismatch
# instead of grading against a stale copy. Source of truth remains geom/mvconsist_band.py.
_MVCONSIST_BAND = {'registration_rate': 0.56, 'mean_track_length': 5.48}

MVCONSIST_ALL48_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'data',
    'assets',
    'anthro_reports',
    'mvconsist',
    'all48',
)


_SFM_CAPABILITY_CACHE = {}


def t4_sfm_capability(sub):
    """Can the photogrammetry stack still do what we believe it can?

    THIS GATE IS ABOUT THE MACHINE, NOT ABOUT THE SUBJECT, and it is registered anyway —
    deliberately. On 2026-08-08 we decided not to build a CUDA COLMAP, for reasons that
    were good and are written down in docs/cuda_colmap_build.md. The risk a decision like
    that carries is not that it was wrong; it is that it gets FORGOTTEN. geom/scan_ingest.py
    silently degrades its dense stage to two-view cv2.StereoSGBM when patch-match stereo is
    unavailable, and a degraded run still produces a mesh. Someone photographs a real person
    months from now, gets a soft outlier-ridden surface, and starts tuning the residual
    filter to fix what is actually "the dense stage never ran". Putting the absence in front
    of every suite run is what stops that afternoon happening.

    NOTHING HERE READS A FLAG AND BELIEVES IT. pycolmap.has_cuda is a compile-time constant
    describing the wheel, not the machine: a driver change, a broken toolkit or a dead GPU
    cannot move it. geom/sfm_capability.py probes each capability by RUNNING the smallest
    real instance of it, and separates three states that must never be confused —
    AVAILABLE, ABSENT (known, documented, degraded path stated) and BROKEN (something claims
    a capability the probe disagrees with, or the machine has drifted off its recorded
    baseline). Only BROKEN is an alarm; today's honest ABSENT is not.

    It also carries the one check that can take this workstation down: a DRIVER STACK SPLIT,
    where nvidia-smi reports one version and the installed driver packages are another. That
    is what installing Ubuntu's nvidia-cuda-toolkit over a hand-managed driver does, this
    project has already lost time to it, and every GPU service on the box — ComfyUI first —
    dies of it.

    Probed ONCE per process and cached: the machine does not change between characters, and
    running it five times would be four wasted probes.
    """
    try:
        from zyg_workflows.geom import sfm_capability as SC
    except Exception as e:  # noqa: BLE001
        return _result(
            REPORT,
            'geom/sfm_capability.py could not be imported (%s: %s), so the '
            'photogrammetry stack is UNVERIFIED. That is not the same as '
            'working.' % (type(e).__name__, e),
        )
    if 'rec' not in _SFM_CAPABILITY_CACHE:
        try:
            _SFM_CAPABILITY_CACHE['rec'] = SC.probe()
        except Exception as e:  # noqa: BLE001
            _SFM_CAPABILITY_CACHE['rec'] = {
                'status': SC.UNKNOWN,
                'broken': [],
                'probe_error': '%s: %s' % (type(e).__name__, e),
                'derived': {},
                'degraded': {},
                'driver_stack': {},
                'capabilities': {},
            }
    rec = _SFM_CAPABILITY_CACHE['rec']

    if rec.get('probe_error'):
        return _result(REPORT, 'the capability probe itself failed: %s. The stack is UNVERIFIED.' % rec['probe_error'])

    ds = rec.get('driver_stack') or {}
    broken = list(rec.get('broken') or [])
    if broken:
        # The loud one. Phrased so the first line of the report says what to stop doing.
        return _result(
            REPORT,
            'STOP — the GPU stack is BROKEN, not merely limited: %s. %s '
            'Every CUDA process on this machine is affected, ComfyUI included. '
            'See docs/cuda_colmap_build.md.' % (', '.join(broken), ds.get('reason', '')),
            observed=rec.get('derived'),
            source='geom/sfm_capability.py probe',
            driver_stack=ds,
            baseline=rec.get('baseline'),
            capabilities=rec.get('capabilities'),
        )

    derived = rec.get('derived') or {}
    missing = sorted(k for k, v in derived.items() if v != SC.AVAILABLE)
    if not missing:
        return _result(
            REPORT,
            'full photogrammetry capability: %s all available; driver %s agrees '
            'with its installed packages.' % (', '.join(sorted(derived)), ds.get('running_driver')),
            observed=derived,
            source='geom/sfm_capability.py probe',
            driver_stack=ds,
            baseline=rec.get('baseline'),
        )

    dense = derived.get('colmap_cuda_dense')
    head = (
        'dense patch-match stereo CANNOT RUN on this machine, so geom/scan_ingest.py '
        'falls back to two-view cv2.StereoSGBM and produces a worse surface than the '
        'pipeline is designed for. '
        if dense != SC.AVAILABLE
        else ''
    )
    return _result(
        REPORT,
        '%sunavailable: %s. This is the EXPECTED, RECORDED state (deferred '
        '2026-08-08) — the build recipe is docs/cuda_colmap_build.md and the '
        'driver stack is healthy (%s). Do not read this as a defect; read it as '
        'the reason a scan ingested today would be degraded.' % (head, ', '.join(missing), ds.get('running_driver')),
        observed=derived,
        source='geom/sfm_capability.py probe',
        degraded=rec.get('degraded'),
        driver_stack=ds,
        baseline=rec.get('baseline'),
    )


def t4_multiview_consistency(sub):
    """Does this character's 48-cell contact sheet depict ONE consistent 3D object?

    The measurement is geom/mvconsist.py: run COLMAP structure-from-motion over the 48
    cells and read off how many of them register into a single reconstruction
    (registration_rate) and how many views the average feature track survives across
    (mean_track_length). A sheet of 48 renders of the same person from 48 angles should
    reconstruct; a sheet of 48 pictures of 48 slightly different people should not.

    REPORTING ONLY, AND ON PURPOSE. This gate is brand new and has never been run against
    the full cast, so it is registered at severity 'report' and returns REPORT for every
    outcome including a band failure. A gate that has not yet been shown to behave on the
    cast it will judge has not earned the right to fail a build. Promoting it is a separate,
    deliberate act; see the handover note.

    IT DOES NOT MEASURE ANYTHING HERE. It reads artefacts that geom/mvconsist.py already
    wrote, because the measurement takes SfM minutes per sheet and a gate suite must not
    turn into a render farm. A character with no artefact reports that, and never passes.

    THE MESH-TO-SHEET LINK IS DECLARED, NOT GUESSED. `contact_sheet_id` is a spec key the
    recipe sets. There is deliberately no name-to-charid table in this file: the mesh
    registry carries no contact-sheet id, so any mapping written here would be a guess
    dressed as a fact, and grading a sheet against the wrong body is the exact failure this
    whole gate exists to catch. Nothing declares one yet, so every character currently
    reports 'undeclared' — which is the point: the missing wiring is now VISIBLE instead of
    absent.
    """
    cid = sub.spec.get('contact_sheet_id')
    if not cid:
        return _result(
            REPORT,
            'no contact_sheet_id declared, so no multi-view-consistency '
            'measurement can be located for this character. NOT a pass: the '
            'sheet was not judged.',
            observed=None,
            source='spec key contact_sheet_id (unset)',
            **{
                RECEIPT_KEY: True,
                'wiring': 'set spec["contact_sheet_id"] to the storyteller '
                'character id whose contact_sheet/cells directory was '
                'measured, e.g. "c3345deb5bde" for abel',
            },
        )
    try:
        from zyg_workflows.geom import mvconsist_band as MVB
    except Exception as e:  # noqa: BLE001
        return _result(REPORT, 'geom.mvconsist_band did not import: %s: %s' % (type(e).__name__, e), observed=None)

    # The mirrored literal is never trusted. If mvconsist_band's band has moved, say so
    # rather than grade a sheet against a threshold this file merely remembers.
    live = dict(getattr(MVB, 'BAND', {}) or {})
    mirrored = {k: v.get('min') for k, v in live.items() if isinstance(v, dict)}
    if mirrored != _MVCONSIST_BAND:
        return _result(
            REPORT,
            'REGISTRY DRIFT: gates.py mirrors the band as %r but '
            'geom.mvconsist_band.BAND is now %r. Refusing to grade against a '
            'stale copy; update _MVCONSIST_BAND.' % (_MVCONSIST_BAND, live),
            observed=None,
            source='geom/mvconsist_band.py BAND (source of truth)',
        )

    import glob as _glob

    paths = sorted(_glob.glob(os.path.join(MVCONSIST_ALL48_DIR, '%s.r*.json' % cid)))
    if not paths:
        return _result(
            REPORT,
            'contact_sheet_id %r is declared but no 48-cell measurement exists '
            'at %s. NOT a pass: the sheet was not judged.'
            % (cid, os.path.join(MVCONSIST_ALL48_DIR, '%s.r*.json' % cid)),
            observed=None,
            source='geom/mvconsist.py artefacts (absent)',
        )

    repeats, bad = [], []
    for p in paths:
        try:
            with open(p) as fh:
                res = json.load(fh)
        except Exception as e:  # noqa: BLE001
            bad.append('%s: %s' % (os.path.basename(p), e))
            continue
        v = MVB.verdict(res)
        repeats.append(
            {
                'file': os.path.basename(p),
                'verdict': v.get('verdict'),
                'reason': v.get('reason'),
                'registration_rate': res.get('registration_rate'),
                'mean_track_length': res.get('mean_track_length'),
            }
        )
    if not repeats:
        return _result(
            REPORT, 'every measurement file for %r failed to load: %s' % (cid, '; '.join(bad)), observed=None
        )

    verdicts = sorted({r['verdict'] for r in repeats})
    rr = [r['registration_rate'] for r in repeats if r['registration_rate'] is not None]
    mt = [r['mean_track_length'] for r in repeats if r['mean_track_length'] is not None]
    obs = {
        'registration_rate': [min(rr), max(rr)] if rr else None,
        'mean_track_length': [min(mt), max(mt)] if mt else None,
        'repeats': len(repeats),
    }
    # The RANGE across repeats, never a single draw. SfM on this instrument is stochastic
    # enough that one run of one sheet reproduced a different verdict on re-measurement,
    # which is why the band was re-derived with repeats in the first place.
    if len(verdicts) > 1:
        line = (
            'the %d repeats DISAGREE (%s) — this sheet straddles the band and a single '
            'run of it would have reported whichever side it landed on' % (len(repeats), ', '.join(verdicts))
        )
    else:
        line = 'all %d repeats agree: %s' % (len(repeats), verdicts[0])
    return _result(
        REPORT,
        '%s. registration_rate %s, mean_track_length %s (band %s). Reported, '
        'not gated: this gate is new and has never been run against the full '
        'cast.'
        % (
            line,
            ('%.4f-%.4f' % (min(rr), max(rr))) if rr else 'n/a',
            ('%.4f-%.4f' % (min(mt), max(mt))) if mt else 'n/a',
            MVB.BAND,
        ),
        observed=obs,
        band=dict(MVB.BAND),
        source='geom/mvconsist.py artefacts, graded by geom.mvconsist_band.verdict',
        **{RECEIPT_KEY: True, 'repeats': repeats, 'unreadable': bad or None, 'contact_sheet_id': cid},
    )


def t4_form_modules_importable(sub):
    """Every tier-5 module imports, BOTH as a package module and as a script.

    Registered because of a measured failure, not a hypothetical one: on 2026-08-06
    `python geom/form/hands.py --digits` from any cwd but the repo root raised
    `ModuleNotFoundError: No module named 'geom'` at hands.py:2791, because every geom
    import in that file is lazy and inside a function. The module imported clean and only
    broke once a gate asked it for a number. The other four modules carried the repo-root
    bootstrap; hands.py did not. Without this gate the symptom of that class of break is a
    character silently recorded UNGATED.

    See _SCRIPT_MODE_PROBE for why the second half is now a spawned probe and not a grep.
    """
    ctrl_ok, ctrl_how = _script_mode_negative_control()
    rows, broken, no_bootstrap, unresolved = {}, [], [], []
    for key, dotted in _FORM_MODULES:
        M, err = form_module(key)
        if M is None:
            rows[dotted] = {'import': (err or '').splitlines()[0], 'script_mode': None}
            broken.append(dotted)
            continue
        ok, how, code = script_mode_probe(getattr(M, '__file__', '') or '')
        rows[dotted] = {
            'import': 'ok',
            'script_mode': ok,
            'script_mode_code': code,
            'script_mode_how': how,
            'file': getattr(M, '__file__', None),
        }
        if ok is False:
            no_bootstrap.append(dotted)
        elif ok is None:
            unresolved.append(dotted)
    bad = broken + no_bootstrap
    # A probe whose negative control did not reject is not evidence in EITHER direction, so
    # it may not produce a pass and it may not produce a fail: it is an ERROR about the
    # probe, stated as one.
    if ctrl_ok is not True:
        st = ERROR
    elif unresolved:
        st = ERROR
    else:
        st = PASS if not bad else FAIL
    return _result(
        st,
        '%d/%d tier-5 modules import as packages; %d fail the SCRIPT-MODE probe '
        '(run from a foreign cwd with PYTHONPATH scrubbed, `geom` does not '
        'resolve afterwards)%s%s. Probe negative control: %s — %s'
        % (
            len(_FORM_MODULES) - len(broken),
            len(_FORM_MODULES),
            len(no_bootstrap),
            '' if not bad else ': ' + ', '.join(bad),
            ''
            if not unresolved
            else ' — and %d module(s) COULD NOT BE PROBED, which is not a pass: %s'
            % (len(unresolved), ', '.join(unresolved)),
            {
                True: 'REJECTS a module with no bootstrap',
                False: 'BROKEN — it passed a module with no bootstrap',
                None: 'UNRESOLVED',
            }[ctrl_ok],
            ctrl_how,
        ),
        observed={
            'importable': len(_FORM_MODULES) - len(broken),
            'modules': len(_FORM_MODULES),
            'failing_script_mode': len(no_bootstrap),
            'script_mode_unresolved': len(unresolved),
            'negative_control_rejects': ctrl_ok,
        },
        band=[len(_FORM_MODULES), len(_FORM_MODULES)],
        source='HOUSE: geom/mesh_skeletons.py::_ensure_repo_importable exists '
        'for this exact failure mode; this gate asserts the same '
        'PROPERTY (not the spelling of the fix) of the five tier-5 '
        'modules, by running each one the way `python <file>` runs it',
        per_module=rows,
        broken=broken,
        failing_script_mode=no_bootstrap,
        script_mode_unresolved=unresolved,
        negative_control={
            'rejects_a_module_with_no_bootstrap': ctrl_ok,
            'how': ctrl_how,
            'lesion': 'a generated module whose only occurrence '
            'of "sys.path.insert" is inside its '
            'docstring — the exact case the previous '
            'substring test passed',
        },
        tier5_enabled=_tier5_enabled(),
        rollback_flag=ZYG_TIER5_FLAG,
    )
