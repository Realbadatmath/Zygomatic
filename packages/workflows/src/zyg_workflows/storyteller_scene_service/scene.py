# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.scene — the scene-build section — build_scene, the entry point (lines 3803-3850).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    _OUT_ROOT,
    os,
    time,
)
from zyg_workflows.storyteller_scene_service.frame import (
    _kb_keys_at,
    _kb_zoom_at,
)

# ── scene build ──────────────────────────────────────────────────────────────


def _tail_z_at_black(shot: dict, picture_end: float, tail_t0: float, tail_win_t1: float) -> float:
    """What the closing move had actually reached when the screen went black —
    the authored end of the move is deliberately never arrived at."""
    fx = shot.get('fx', {}) or {}
    tt = min(1.0, (picture_end - tail_t0) / max(1e-6, tail_win_t1 - tail_t0))
    if fx.get('kb_keys'):
        return _kb_keys_at(tt, fx['kb_keys'])[0]
    return _kb_zoom_at(tt, fx.get('kenburns', 'push_in'), float(fx.get('kb_amount', 0.06)), fx.get('kb_zoom'))


def build_scene(spec: dict, out_dir: str | None = None, log_fn=None) -> dict | None:
    """Render a scripted dialogue scene. Returns
    {'video','master_audio','stills':{...},'timeline':{...},'state'} or None.

    The stages live in storyteller_scene_service_steps, one `_step_*` per `# N`
    banner of the single 1,254-line function this used to be; the state they
    hand each other is `tl` (the timeline), `frames` and `mixed`."""
    from zyg_workflows import audio_mix
    from zyg_workflows import storyteller_scene_service_steps as steps
    import soundfile as sf

    log = log_fn or print
    W = int(spec.get('width', 1344))
    H = int(spec.get('height', 768))
    slug = spec.get('slug', 'scene')
    if out_dir is None:
        out_dir = os.path.join(_OUT_ROOT, f'scene_{slug}')
    os.makedirs(out_dir, exist_ok=True)
    t_start = time.time()
    gates = steps._GateReceipts(log)

    stills = steps._step_stills(spec, out_dir, W, H, log, gates)
    if stills is None:
        return None
    rendered = steps._step_voice_lines(spec, out_dir, log, gates)
    if rendered is None:
        return None
    lines, anchored = rendered
    tl = steps._step_timeline(spec, lines, anchored, log)
    stem_wav = steps._step_stem(spec, out_dir, log, tl, audio_mix, sf)
    mixed = steps._step_master(spec, out_dir, slug, log, tl, stem_wav, audio_mix, sf)
    frames = steps._step_frames(spec, out_dir, W, H, log, stills, tl)
    return steps._step_encode(spec, out_dir, slug, W, H, log, stills, tl, frames, mixed, t_start, gates)
