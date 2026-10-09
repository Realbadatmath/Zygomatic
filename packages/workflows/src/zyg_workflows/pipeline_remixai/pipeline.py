# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline — the Remix Ai orchestrator: the fourteen stages in order, and the error funnel.

The stages themselves live in ``pipeline_stages`` (extracted 2026-10-09 from the
488-line ``_run_pipeline``); this module is the sequence, the ``_Stopped``/failure
handling, and the ``_seal.seal`` content credential, which ``check_seal_hooks.py``
requires to be inside ``_run_pipeline`` itself.
"""

from __future__ import annotations

from .core import (
    RA,
    _finish,
    _log,
    _marker_update,
    _seal,
    _Stopped,
    _update_stage,
    _zyg_log,
    os,
    traceback,
)
from .pipeline_stages import (
    new_run,
    stage_analysis,
    stage_assembly,
    stage_delivery,
    stage_script,
    stage_soundtrack,
    stage_source,
    stage_title,
    stage_visuals,
)


# ── the pipeline ────────────────────────────────────────────────────────────


def _run_pipeline(pid, video_id, force=False):
    run = new_run(pid)

    try:
        stage_source(run, video_id)
        stage_analysis(run)
        stage_soundtrack(run)
        stage_script(run)
        stage_title(run)
        stage_visuals(run)
        stage_assembly(run)

        # ── Stage 14: Delivery ──────────────────────────────────────────────
        _update_stage(pid, 'Delivery', 98)
        # Both exits of the subtitle burn (burned or unburned) have landed
        # FINAL_<stem>.mp4 by now: stamp the content credential before anything
        # measures or records the file.
        _seal.seal(
            run.final,
            pipeline='remixai',
            run_id=pid,
            title=run.title,
            log_fn=lambda msg: _log(pid, 'INFO', 'Delivery', msg),
        )
        _finish(pid, True, result=stage_delivery(run))
        _marker_update(run.mid, status='done')
        return

    except _Stopped as e:
        _log(pid, 'WARNING', 'Stopped', str(e))
        _finish(pid, False, error=str(e))
        _marker_update(run.mid, status='stopped')
    except Exception as e:
        _log(pid, 'ERROR', 'Failed', f'{e}\n{traceback.format_exc()[-1200:]}')
        _finish(pid, False, error=str(e))
        _marker_update(run.mid, status='failed')
    finally:
        try:
            RA._ollama_release()
        except Exception as _exc:
            _zyg_log.debug('ollama model release skipped: %s', _exc)
        # never leave a downloaded source on disk, on any exit path
        try:
            if run.src_path and os.path.isfile(run.src_path):
                os.remove(run.src_path)
        except OSError as _exc:
            _zyg_log.warning('downloaded source removal failed, it stays on disk at %s: %s', run.src_path, _exc)
