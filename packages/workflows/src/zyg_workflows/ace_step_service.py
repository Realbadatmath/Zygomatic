# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ace_step_service.py — Local AI background music via ACE-Step 1.5 (MIT).

Replaces musicgen_service (facebook/musicgen-small — CC-BY-NC WEIGHTS, licence
fix 2026-08-09). Runs through the resident ComfyUI server (:8188) using native
ACE-Step 1.5 nodes (comfy_extras/nodes_ace.py) and the turbo AIO checkpoint
ace_step_1.5_turbo_aio.safetensors (Comfy-Org/ace_step_1.5_ComfyUI_files,
pinned rev 54b2ef4d8af5; engine weights MIT per ACE-Step/Ace-Step1.5 rev
19671f406d60 — licence texts pinned in the 2026-08-09 vault).

Same public contract as musicgen_service so callers stay interchangeable:
  generate(prompt, out_path, duration_s=60, *, seed=None, log_fn=None) → bool
  is_available() → bool
  model_id() → str
  unload()

VRAM: ComfyUI evicts the checkpoint after each job unless ZYG_COMFY_KEEP_LOADED
is set (same release path every other comfy render uses), so the WAN pre-check
in pipeline_video keeps its free-VRAM guarantee. duration is no longer capped
at 30 s — beds default to 60 s and may go to ZYG_ACE_MAX_SECONDS.
"""

from __future__ import annotations
import os
import shutil
import logging
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_log = logging.getLogger(__name__)

CHECKPOINT = os.environ.get('ZYG_ACE_STEP_CHECKPOINT', 'ace_step_1.5_turbo_aio.safetensors')
MAX_SECONDS = float(os.environ.get('ZYG_ACE_MAX_SECONDS', '180'))
_CKPT_DIR = str(paths.ZYG_COMFY_ROOT / 'models' / 'checkpoints')


def is_available() -> bool:
    """True when the ComfyUI server is reachable and the ACE checkpoint exists."""
    if not os.path.isfile(os.path.join(_CKPT_DIR, CHECKPOINT)):
        return False
    try:
        from zyg_workflows import _comfy_client as _cc

        return _cc.is_enabled() and _cc.server_reachable()
    except ImportError:
        return False


def model_id() -> str:
    return f'ACE-Step 1.5 turbo ({CHECKPOINT})'


def unload():
    """Free ComfyUI VRAM (idempotent; safe when the server is down)."""
    try:
        from zyg_workflows import _comfy_client as _cc

        if _cc.server_reachable(timeout_s=1.0):
            _cc.free_vram()
    except Exception as _exc:
        _zyg_log.debug('comfy vram release skipped: %s', _exc)


def generate(
    prompt: str,
    out_path: str,
    duration_s: int = 60,
    *,
    seed: int | None = None,
    log_fn=None,
) -> bool:
    """Generate an instrumental music bed from *prompt*, save as MP3 at *out_path*.

    prompt is an ACE-Step tag string (genre/mood/instrument descriptors — the
    existing mood prompt vocabulary works as-is). Returns True on success.
    """

    def _notify(msg):
        if log_fn:
            log_fn(msg)
        else:
            _log.info(msg)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
        _notify(f'ACE-Step: using cached track {os.path.basename(out_path)}')
        return True

    if not is_available():
        _notify('ACE-Step: unavailable (server down or checkpoint missing)')
        return False

    try:
        import random as _random_mod
        from zyg_workflows import _comfy_client as _cc

        if seed is None:
            seed = _random_mod.randint(0, 2**31 - 1)
        seconds = max(5.0, min(float(duration_s), MAX_SECONDS))

        _notify(f'ACE-Step: generating {seconds:.0f}s — "{prompt[:80]}" (seed={seed})')

        wf = _cc.load_workflow('ace_step_bgm')
        outputs = _cc.submit(
            wf,
            overrides={
                '1': {'ckpt_name': CHECKPOINT},
                '2': {'tags': prompt, 'seed': seed, 'duration': seconds},
                '4': {'seconds': seconds},
                '5': {'seed': seed},
            },
            timeout_s=float(os.environ.get('ZYG_ACE_TIMEOUT_S', '600')),
        )

        mp3s = [p for p in outputs if p.lower().endswith('.mp3') and os.path.isfile(p)]
        if not mp3s:
            _notify('ACE-Step: job completed but produced no MP3 output')
            return False

        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        shutil.copy2(mp3s[0], out_path)
        try:
            os.remove(mp3s[0])
        except OSError as _exc:
            _zyg_log.debug('ACE-Step source mp3 cleanup skipped: %s', _exc)

        if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
            sz_kb = os.path.getsize(out_path) // 1024
            _notify(f'ACE-Step: ✅ generated {os.path.basename(out_path)} ({sz_kb}KB, {seconds:.0f}s)')
            return True
        _notify('ACE-Step: output copy failed or file too small')
        return False

    except Exception as e:
        _notify(f'ACE-Step: generation error — {e}')
        return False
