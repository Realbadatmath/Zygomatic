# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_abort.py — make a 90-minute render stoppable (2026-08-01).

THE PROBLEM THIS FIXES, IN THE OPERATOR'S WORDS:
    "why dont they get flagged earlier in to run? so we can actually stop a run and fix it
     instead of waiting many hours for each scene to complete???"

They are right, and it was by construction rather than by oversight. Three pieces of
early-warning machinery exist and NOT ONE of them can stop anything:

  1. the 81-frame probe is BYPASSED on every run — its gates were calibrated on 341-frame
     clips and reject every probe (see probe_floors.py for the fix);
  2. preview_judge.py is ADVISORY BY DESIGN — its own docstring says "It NEVER interrupts,
     kills or /free's anything"; it writes <run_dir>/PREVIEW_ALERT and keeps going;
  3. the driver only READS that alert AFTER the render returns, ~90 minutes later.

So a run that is visibly wrong at minute 5 still costs the full 90, and the operator has
spent roughly six hours across v15-v17 finding that out three times.

DESIGN — THE ABORT DECISION STAYS WITH THE DRIVER.
preview_judge keeps its advisory contract and is NOT given kill authority: a VLM verdict on
a TAESD preview is exactly the kind of signal that should not be able to destroy 40 minutes
of sampling on its own. Instead the DRIVER (which owns the run, the run_dir and the exit
code) starts this watchdog, and the watchdog is the only thing that calls interrupt.

TRIGGERS, in the order they matter:
  * <run_dir>/ABORT        — the OPERATOR touches this file. Highest value trigger in the
                             whole module: it turns "watch it go wrong for an hour" into
                             `touch ABORT`. No judgement, no thresholds, no false positives.
  * <run_dir>/PREVIEW_ALERT — written by preview_judge on a critical streak. Requires
                             require_streak>=1 ticks and is only honoured when
                             ZYG_ABORT_ON_PREVIEW=1, because it is a model's opinion.
  * a caller-supplied predicate (used for the probe verdict).

WHAT ABORT MEANS: POST /interrupt to ComfyUI. The blocking submit in wan_vace_service then
returns empty and the driver takes its normal render-failed path, so nothing downstream has
to learn a new failure mode. An ABORTED.json is written so the post-mortem can tell an abort
apart from a crash — those look identical in the logs otherwise.
"""

import json
import os
import threading
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


POLL_S = float(os.environ.get('ZYG_ABORT_POLL_S', '5'))
ABORT_ON_PREVIEW = os.environ.get('ZYG_ABORT_ON_PREVIEW', '0') == '1'


def _log_noop(_m):
    pass


def _interrupt(log):
    """POST /interrupt. -> True when ComfyUI accepted it."""
    try:
        from zyg_workflows import _comfy_client as CC
    except Exception as e:
        log(f'[abort] cannot import _comfy_client ({e}) — CANNOT INTERRUPT')
        return False
    fn = getattr(CC, 'interrupt_execution', None)
    if not callable(fn):
        log('[abort] _comfy_client has no interrupt_execution — CANNOT INTERRUPT')
        return False
    try:
        ok = bool(fn())
        log(f'[abort] POST /interrupt -> {"accepted" if ok else "REFUSED"}')
        return ok
    except Exception as e:
        log(f'[abort] interrupt raised ({e})')
        return False


class RenderAbortWatchdog:
    """Polls for abort triggers during a blocking render and interrupts ComfyUI.

    wd = RenderAbortWatchdog(OUT, log_fn=log)
    wd.start()
    try:
        clip = V.generate_vace_static_clip(...)
    finally:
        wd.stop()
    if wd.fired:
        ...   # aborted on purpose, not a crash
    """

    def __init__(self, run_dir, log_fn=None, poll_s=None, predicate=None, abort_on_preview=None):
        self.run_dir = run_dir
        self.log = log_fn or _log_noop
        self.poll_s = float(poll_s or POLL_S)
        self.predicate = predicate
        self.abort_on_preview = ABORT_ON_PREVIEW if abort_on_preview is None else bool(abort_on_preview)
        self.abort_file = os.path.join(run_dir, 'ABORT')
        self.alert_file = os.path.join(run_dir, 'PREVIEW_ALERT')
        self.result_file = os.path.join(run_dir, 'ABORTED.json')
        self._stop = threading.Event()
        self._t = None
        self.fired = False
        self.reason = None
        self.fired_at_s = None
        self._t0 = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self):
        # A stale ABORT from a previous run would kill this one instantly, and the
        # symptom (render returns empty in 5s) looks nothing like the cause.
        for p in (self.abort_file, self.result_file):
            if os.path.exists(p):
                try:
                    os.remove(p)
                    self.log(f'[abort] cleared stale {os.path.basename(p)}')
                except OSError as _exc:
                    _zyg_log.warning(
                        'stale %s could not be cleared, the watchdog may abort at once: %s', os.path.basename(p), _exc
                    )
        self._t0 = time.time()
        self._t = threading.Thread(target=self._run, name='render-abort', daemon=True)
        self._t.start()
        self.log(
            f'[abort] watchdog armed on {self.run_dir} '
            f'(poll {self.poll_s:.0f}s; touch {self.abort_file} to stop this render; '
            f'preview-alert abort {"ON" if self.abort_on_preview else "off"})'
        )
        return self

    def stop(self):
        self._stop.set()
        if self._t and self._t.is_alive():
            self._t.join(timeout=self.poll_s + 2)
        return self.fired

    # ── the loop ─────────────────────────────────────────────────────────────
    def _check(self):
        if os.path.isfile(self.abort_file):
            txt = ''
            try:
                with open(self.abort_file, 'r', encoding='utf-8', errors='replace') as fh:
                    txt = fh.read().strip()[:300]
            except OSError as _exc:
                _zyg_log.debug('ABORT file note unreadable: %s', _exc)
            return 'operator', f'operator touched ABORT{(": " + txt) if txt else ""}'
        if self.abort_on_preview and os.path.isfile(self.alert_file):
            txt = ''
            try:
                with open(self.alert_file, 'r', encoding='utf-8', errors='replace') as fh:
                    txt = fh.read().strip()[:300]
            except OSError as _exc:
                _zyg_log.debug('PREVIEW_ALERT note unreadable: %s', _exc)
            return 'preview_judge', f'PREVIEW_ALERT raised{(": " + txt) if txt else ""}'
        if self.predicate:
            try:
                v = self.predicate()
            except Exception as e:
                self.log(f'[abort] predicate raised ({e}) — ignored')
                v = None
            if v:
                return 'predicate', str(v)
        return None, None

    def _run(self):
        # KEEPS INTERRUPTING — it must not fire once and stop watching. Measured on v21:
        # the abort landed during the 81-frame PROBE, /interrupt was accepted, and the
        # watchdog then returned. generate_vace_with_probe judged the truncated probe
        # PASS and went straight on to the FULL 341-frame render inside the same blocking
        # call, with nothing left watching it — so an abort the operator had already
        # requested bought 28 minutes and then started the 85-minute render anyway. The
        # driver's `if ABORT_WD.fired` check could not help: it only runs after that call
        # returns. So while the trigger is still present, every poll re-interrupts.
        n_int = 0
        while not self._stop.is_set():
            src, why = self._check()
            if src:
                first = not self.fired
                if first:
                    self.fired = True
                    self.reason = why
                    self.fired_at_s = round(time.time() - self._t0, 1)
                    mins = self.fired_at_s / 60.0
                    self.log(f'[abort] *** ABORTING RENDER at {mins:.1f} min *** [{src}] {why}')
                ok = _interrupt(self.log if first else _log_noop)
                n_int += 1
                if first:
                    try:
                        with open(self.result_file, 'w') as fh:
                            json.dump(
                                {
                                    'aborted': True,
                                    'source': src,
                                    'reason': why,
                                    'at_s': self.fired_at_s,
                                    'at_min': round(self.fired_at_s / 60.0, 2),
                                    'interrupt_accepted': ok,
                                    'run_dir': self.run_dir,
                                },
                                fh,
                                indent=1,
                            )
                    except OSError as e:
                        self.log(f'[abort] could not write ABORTED.json ({e})')
                    self.log(
                        f'[abort] saved {self.fired_at_s / 60.0:.1f} min of GPU time'
                        if ok
                        else '[abort] interrupt NOT accepted'
                    )
                    self.log(
                        '[abort] will KEEP interrupting while ABORT is present, so a '
                        'follow-on render in the same call cannot slip past'
                    )
                elif n_int % 12 == 0:
                    self.log(
                        f'[abort] still aborting (interrupt #{n_int}) — '
                        f'remove {os.path.basename(self.abort_file)} to allow renders'
                    )
            self._stop.wait(self.poll_s)


def watchdog(run_dir, **kw):
    return RenderAbortWatchdog(run_dir, **kw)


if __name__ == '__main__':  # the CLI lives in render_abort_cli
    from zyg_workflows.render_abort_cli import main as _cli_main

    raise SystemExit(_cli_main())
