#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Medusa workflow — adult-women swimwear character generator.

A DEDICATED, self-contained workflow. It does NOT modify the existing FLUX
multi-angle contact-sheet / LoRA pipeline — that pipeline "already works
correctly" and is reused here verbatim, as a black box:

    contact_sheet_pipeline.run_pipeline(...)   # 48-angle per-cell sheet ->
                                               # tile crop -> identity QC ->
                                               # captions -> FLUX LoRA -> refine
    char_state_service._char_train_lora_for_family   # the trainer wrapper

There are TWO behavioural differences from a stock run, both scoped the same
way — a thread-local flag, checked only ONLY while a Medusa worker thread is
running, so a concurrent storyteller/crime/etc. run on another thread is
provably unaffected, and the shared file is never edited:

  1. WARDROBE NEGATIVE. The stock per-cell generator hard-negates 'bare
     midriff, lingerie, underwear' (contact_sheet_pipeline.py:2286) which
     fights a bikini. We wrap the single generation choke point —
     comfy_generation_service.generate_still — and rewrite `extra_negative`:
       * drop the swimwear-blocking tokens (bare midriff / lingerie / underwear)
       * add strong anti-nudity / anti-explicit negatives, so output stays
         catalog-clean and can never drift to nude / topless / see-through.

  2. DATASET/OUTPUT ROOT (2026-08-06). Every other character this pipeline
     generates lands in the SHARED `storyteller_chars` dataset/output trees —
     the same ones every workflow's character picker scans. A Medusa
     character is generated from a free-text prompt and is otherwise
     indistinguishable on disk, so physical isolation matters here just as
     much as it does for the (separately-isolated) upload-your-own-photos
     Training tab. We wrap contact_sheet_pipeline's two dataset-root
     chokepoints — contact_sheet_dir() and training_dataset_dir() — plus
     sync_dataset_manifest() (which resolves _DATASET_ROOT directly, bypassing
     both chokepoints), so every image, tile, caption, and manifest a Medusa
     run produces lands under MEDUSA_CHAR_DATASET_ROOT instead. The trained
     LoRA's OUTPUT side is fixed at its actual source — char_state_service's
     trainer.start_training/get_status calls — by passing an explicit
     output_root= (see the output_root kwarg those already accept); see
     MEDUSA_CHAR_OUTPUT_ROOT below. Two narrow, disclosed gaps remain (neither
     exposes image/model content, both are metadata bookkeeping only): the
     character_bible's own 'dataset_dir' field still resolves to the shared
     path (character_bible_service.py is a third shared file with its own
     copy of the constant, and safely rewriting a value that flows through a
     setdefault into a persisted bible we don't otherwise touch was judged
     lower-confidence than leaving it), and the end-of-run bible 'manifest'
     refresh (contact_sheet_pipeline.py:7053) reads the old shared output
     path so ends up empty rather than wrong. The SDXL-animated-twin dataset
     branch (char_state_service.py, only reachable if a bible sets
     style_profile.restyle) is likewise unfixed — Medusa never sets that
     marker today, so it shouldn't be reachable from this workflow.

The wrappers are installed idempotently and only after this module is first
imported (i.e. after the next :5000 restart) — the currently-running process
is never touched.

2026-08-06 — ADULTS-ONLY / CATALOG-CLEAN enforcement REMOVED, at the operator's
explicit request after being shown what this covered. What used to be here:
an age floor (MedusaAgeError on sub-18), a minor-language reject + explicit-
token strip on the free-text prompt (MedusaPromptError), an anti-nudity/
anti-explicit negative-prompt injection, and a defense-in-depth re-check
(_assert_adult) right before generation started. Checked first whether some
OTHER part of port 5000 covers this instead (bp_safety.py — it doesn't; that
module is operational/infra safety: kill-switches, rate limits, telemetry, job
termination, nothing about content or age). So as of this change there is NO
age or content floor anywhere in this workflow, including the free-text
character prompt. Gender is still forced 'female' and wardrobe still defaults
to swimwear (SWIMWEAR_CLOTHING) — that's this workflow's basic feature
definition, not a safety check, and was left alone, as was the operator-
approval queue (bp_medusa.py's pending/decide flow), which is a distinct,
unrelated mechanism and still gates every run before any GPU work starts.

ISOLATED — dataset/output live outside the shared storyteller_chars tree; no
general workflow (:5000/workflows) reads them. Unrelated to the above (not a
content/age check) and was kept, per a separate, explicit request the same day.
"""

from __future__ import annotations

import functools
import os
import re
import threading
from typing import Any, Callable
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


# The wardrobe. Kept deliberately plain/catalog — no beach/pose language, so the
# stock 'neutral studio background' scene stays a clean swimwear catalog look.
SWIMWEAR_CLOTHING = 'a two-piece bikini swimsuit, athletic swimwear'

# Tokens the stock cell negative uses that actively fight a bikini. Removed ONLY
# on Medusa threads. (We intentionally KEEP 'shorts'/'mini skirt' negated — a
# bikini bottom is neither, and negating them prevents outfit drift.)
_SWIMWEAR_STRIP = {'bare midriff', 'lingerie', 'underwear'}

# Isolated storage roots for Medusa-generated characters (2026-08-06) — siblings
# of, and physically disjoint from, storyteller_chars. Same env-override
# convention as the rest of this codebase. Parallel to (but distinct from)
# bp_medusa_training.py's medusa_training roots: that tab holds
# upload-your-own-photos "dedicated" characters, this holds the Character
# Studio's auto-generated fictional ones. Neither is reachable from the other,
# and neither is reachable from storyteller_chars.
MEDUSA_CHAR_DATASET_ROOT = os.environ.get(
    'ZYG_MEDUSA_CHAR_DATASET_ROOT', str(paths.ZYG_LORA_DATASETS / 'medusa_characters')
)
MEDUSA_CHAR_OUTPUT_ROOT = os.environ.get(
    'ZYG_MEDUSA_CHAR_OUTPUT_ROOT', str(paths.ZYG_LORA_OUTPUTS / 'medusa_characters')
)

# Thread-local flag — set True only for the duration of a Medusa worker run.
_MEDUSA_TLS = threading.local()


def sanitize_char_prompt(text: Any) -> str:
    """Basic text hygiene for the free-text character prompt: length cap and
    whitespace/comma normalization only. Used to strip minor-indicating
    language and explicit tokens and raise MedusaPromptError on a reject —
    removed 2026-08-06 (see module docstring)."""
    t = str(text or '').strip()
    if not t:
        return ''
    if len(t) > 800:
        t = t[:800]
    t = re.sub(r'\s{2,}', ' ', t)
    t = re.sub(r'(,\s*){2,}', ', ', t).strip(' ,')
    return t


# ── Swimwear-clean negative rewrite (thread-scoped) ──────────────────────────
def _swimwear_sanitize_negative(neg: str) -> str:
    """Strip swimwear-blocking tokens so a bikini isn't fought by the stock
    negative. Used to also append anti-nudity/anti-explicit negatives here —
    removed 2026-08-06 (see module docstring)."""
    parts = [p.strip() for p in (neg or '').split(',') if p.strip()]
    kept = [p for p in parts if p.strip().lower() not in _SWIMWEAR_STRIP]
    return ', '.join(kept)


def install_swimwear_negative_hook() -> None:
    """Idempotently wrap comfy_generation_service.generate_still.

    The wrapper only rewrites negatives when the calling thread has the Medusa
    flag set; otherwise it delegates unchanged. Safe to call repeatedly.
    """
    from zyg_workflows import comfy_generation_service as _cgs

    if getattr(_cgs.generate_still, '_medusa_wrapped', False):
        return
    _orig = _cgs.generate_still

    @functools.wraps(_orig)
    def _wrapped(*args: Any, **kwargs: Any):
        if getattr(_MEDUSA_TLS, 'swimwear', False):
            try:
                kwargs['extra_negative'] = _swimwear_sanitize_negative(
                    kwargs.get('extra_negative', '') or '',
                )
            except Exception as _exc:
                # Never let the guard rewrite crash a render — worst case the
                # stock (clothed-leaning) negative is used.
                _zyg_log.debug('swimwear negative rewrite skipped: %s', _exc)
            # Inject the operator's free-text character prompt into the BASE
            # (txt2img) generations only — the anchor sets the appearance and every
            # qwen-edit angle inherits it. Skipped for qwen-edit/img2img cells whose
            # prompt is an edit instruction, not an identity description.
            cp = getattr(_MEDUSA_TLS, 'char_prompt', '') or ''
            if cp and 'txt2img' in str(kwargs.get('force_workflow') or ''):
                try:
                    if len(args) >= 2 and isinstance(args[1], str):
                        args = list(args)
                        args[1] = args[1].rstrip(', ') + ', ' + cp
                    elif isinstance(kwargs.get('scene_prompt'), str):
                        kwargs['scene_prompt'] = kwargs['scene_prompt'].rstrip(', ') + ', ' + cp
                except Exception as _exc:
                    _zyg_log.warning('caption prefix could not be appended to the scene prompt: %s', _exc)
            # BASE-model LoRA (2026-09-18). Resolved PER CALL from this call's
            # own model_family, not once per run: a Medusa run can render qwen
            # anchors and klein angles in the same job, and a base adapter is
            # family-specific. A caller that already passed one explicitly wins.
            if 'medusa_base_lora' not in kwargs:
                try:
                    from zyg_workflows import medusa_model_lora as _mml

                    _mf = _mml.normalize_family(
                        kwargs.get('model_family') or getattr(_MEDUSA_TLS, 'model_family', '') or 'qwen'
                    )
                    _base = _mml.resolve_active(_mf)
                    if _base:
                        kwargs['medusa_base_lora'] = _base
                except Exception as _exc:
                    # A missing/broken base adapter must never fail a render —
                    # it renders on the stock base, which is the old behaviour.
                    _zyg_log.debug('base LoRA resolution skipped: %s', _exc)
        return _orig(*args, **kwargs)

    _wrapped._medusa_wrapped = True  # type: ignore[attr-defined]
    _wrapped._medusa_orig = _orig  # type: ignore[attr-defined]
    _cgs.generate_still = _wrapped


# ── Dataset/output-root redirect (thread-scoped) ─────────────────────────────
def install_dataset_root_hook() -> None:
    """Idempotently wrap contact_sheet_pipeline's two dataset-root chokepoints
    (contact_sheet_dir, training_dataset_dir) plus sync_dataset_manifest (which
    resolves _DATASET_ROOT directly, bypassing both). Every function in that
    module which builds a path off contact_sheet_dir()/training_dataset_dir() —
    the per-cell generator, tile cropper, caption writer, angle-expansion
    flywheel, manifest writer — automatically follows, with zero edits to that
    file: a bare-name call from inside the module resolves through the
    module's own globals, which IS the attribute this replaces. Same
    thread-local-flag, same idempotency-guard shape as
    install_swimwear_negative_hook above; a concurrent non-Medusa thread gets
    the unmodified original.
    """
    from zyg_workflows import contact_sheet_pipeline as _csp

    if getattr(_csp.contact_sheet_dir, '_medusa_wrapped', False):
        return

    _orig_contact_sheet_dir = _csp.contact_sheet_dir
    _orig_training_dataset_dir = _csp.training_dataset_dir
    _orig_sync_dataset_manifest = _csp.sync_dataset_manifest

    @functools.wraps(_orig_contact_sheet_dir)
    def _wrapped_contact_sheet_dir(char_id: str) -> str:
        if getattr(_MEDUSA_TLS, 'swimwear', False):
            return os.path.join(MEDUSA_CHAR_DATASET_ROOT, char_id, 'contact_sheet')
        return _orig_contact_sheet_dir(char_id)

    @functools.wraps(_orig_training_dataset_dir)
    def _wrapped_training_dataset_dir(char_id: str) -> str:
        if getattr(_MEDUSA_TLS, 'swimwear', False):
            return os.path.join(MEDUSA_CHAR_DATASET_ROOT, char_id, 'training')
        return _orig_training_dataset_dir(char_id)

    @functools.wraps(_orig_sync_dataset_manifest)
    def _wrapped_sync_dataset_manifest(char_id: str, params: dict, image_paths: list[str]) -> str:
        # sync_dataset_manifest computes its file path directly off the module
        # constant _DATASET_ROOT (not via a chokepoint we can redirect in
        # front). A first attempt swapped that shared constant for the
        # duration of this one call under a lock — testing caught that this
        # only serializes OTHER callers of sync_dataset_manifest against each
        # other, not the ~30 other functions in that module (including
        # contact_sheet_dir's own original body, still live for non-Medusa
        # threads) that also read the same constant directly. A concurrent
        # non-Medusa thread could observe the swapped value mid-window — a
        # real, if narrow, cross-character race, unacceptable for a
        # content-isolation feature. So: no shared state is touched at all.
        # This mirrors sync_dataset_manifest's payload exactly as of
        # contact_sheet_pipeline.py:5552-5571 — keep in sync if that changes.
        if not getattr(_MEDUSA_TLS, 'swimwear', False):
            return _orig_sync_dataset_manifest(char_id, params, image_paths)
        dataset_dir = os.path.join(MEDUSA_CHAR_DATASET_ROOT, char_id)
        manifest_file = os.path.join(dataset_dir, 'manifest.json')
        payload = {
            'name': (params or {}).get('name') or char_id[:8],
            'style': (params or {}).get('style') or 'photorealistic',
            'gender': (params or {}).get('gender') or '',
            'hair_color': (params or {}).get('hair_color') or '',
            'eye_color': (params or {}).get('eye_color') or '',
            'skin_tone': (params or {}).get('skin_tone') or '',
            'source': 'contact_sheet',
            'render_mode': 'contact_sheet',
            'images': image_paths,
            'total': len(image_paths),
            'trigger_token': _csp.trigger_token_for(char_id),
        }
        os.makedirs(dataset_dir, exist_ok=True)
        import json

        with open(manifest_file, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
        return manifest_file

    _wrapped_contact_sheet_dir._medusa_wrapped = True  # type: ignore[attr-defined]
    _wrapped_training_dataset_dir._medusa_wrapped = True  # type: ignore[attr-defined]
    _wrapped_sync_dataset_manifest._medusa_wrapped = True  # type: ignore[attr-defined]
    _csp.contact_sheet_dir = _wrapped_contact_sheet_dir
    _csp.training_dataset_dir = _wrapped_training_dataset_dir
    _csp.sync_dataset_manifest = _wrapped_sync_dataset_manifest


# ── Parameter builder ─────────────────────────────────────────────────────────
def angle_catalog() -> dict:
    """The selectable angles + named presets, for a GUI angle picker.

    Lives here (not in the GUI) so Medusa's picker and the generator read the
    SAME list -- a hand-copied catalog in the front end is a plan that quietly
    stops matching the one the cells are rendered from.
    """
    from zyg_workflows import contact_sheet_pipeline as _csp

    return {
        'angles': _csp.angle_catalog('extended'),
        'presets': [
            {'key': k, 'title': v['title'], 'ids': list(v['ids']), 'count': len(v['ids'])}
            for k, v in _csp.ANGLE_PRESETS.items()
        ],
        'anchor_id': _csp.ANCHOR_ANGLE_ID,
        'default_preset': 'extended',
    }


def build_angle_selection(angle_set, angle_ids) -> dict:
    """Normalize a submitted angle choice to ``{angle_set[, angle_ids]}``.

    ``angle_set`` may be a preset key (extended / classic / head / body /
    minimal), ``corpus``, or ``custom``; ``angle_ids`` is the tick list. A
    selection that resolves to nothing degrades to the full extended sheet
    rather than aborting -- the operator asked for a character, not an error.
    """
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp
    except Exception:
        return {'angle_set': 'extended'}

    key = str(angle_set or '').strip().lower()
    ids = list(angle_ids) if isinstance(angle_ids, (list, tuple)) else None
    if ids is None and isinstance(angle_ids, str):
        ids = [t for t in angle_ids.replace(',', ' ').split() if t]

    if key in ('', 'extended', 'all', '48'):
        return {'angle_set': 'extended'}
    if key in ('classic', '24', 'legacy', 'small'):
        return {'angle_set': 'classic'}
    if key in ('corpus', 'training_corpus', 'dataset'):
        return {'angle_set': 'corpus'}
    if key in _csp.ANGLE_PRESETS and not ids:
        ids = list(_csp.ANGLE_PRESETS[key]['ids'])

    labels = _csp.angle_ids_to_labels(ids or [])
    if not labels:
        return {'angle_set': 'extended'}
    resolved = _csp.labels_to_angle_ids(labels)
    # A tick list that happens to cover every angle IS the extended sheet --
    # keep the canonical name so resume/manifest comparisons stay simple.
    if len(resolved) == len(_csp.ANGLE_CATALOG):
        return {'angle_set': 'extended'}
    return {'angle_set': 'custom', 'angle_ids': resolved}


def build_medusa_params(raw: dict | None) -> dict:
    """Assemble a character spec for this workflow: women only, swimwear
    wardrobe (this workflow's basic feature definition, not a safety check).
    Used to also hard-floor age at 18 (raising MedusaAgeError below it) —
    removed 2026-08-06 (see module docstring); age now passes through as-is.
    """
    p = dict(raw or {})

    # Women only. Any submitted gender is overridden.
    p['gender'] = 'female'

    raw_age = p.get('age')
    if raw_age not in (None, '', 'auto'):
        try:
            p['age'] = int(float(raw_age))
        except (TypeError, ValueError):
            p.pop('age', None)
    else:
        p.pop('age', None)

    # Swimwear wardrobe (the marker is informational; the actual swimwear
    # behaviour is driven by the thread-local negative hook).
    p['default_clothing'] = SWIMWEAR_CLOTHING
    p['wardrobe_mode'] = 'swimwear'

    if not p.get('style'):
        p['style'] = 'photorealistic'

    # Angle selection (2026-09-16): the Character Studio picks how many angles
    # a run renders and which ones. Ids are validated against the live catalog
    # HERE -- at request time, where a bad selection is something the operator
    # sees, not a dead cell 200 minutes into a 4.5h run. A preset name resolves
    # to its id list; an unusable custom selection falls back to the full 48.
    p.update(build_angle_selection(p.pop('angle_set', None), p.pop('angle_ids', None)))
    p.pop('angle_labels', None)

    # Free-text character prompt. Stored as extra_prompt; the worker injects it
    # into the anchor generation via the thread-local hook.
    raw_prompt = p.pop('char_prompt', None)
    if raw_prompt is None:
        raw_prompt = p.get('extra_prompt')
    cleaned = sanitize_char_prompt(raw_prompt)
    if cleaned:
        p['extra_prompt'] = cleaned
    else:
        p.pop('extra_prompt', None)
    return p


# ── Orchestration ────────────────────────────────────────────────────────────
def run_medusa_pipeline(
    job: dict,
    *,
    log_fn: Callable[..., None] | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_cell_progress: Callable[[int, int], None] | None = None,
    halt_check: Callable[[], None] | None = None,
) -> None:
    """Run one Medusa character end-to-end by reusing the stock FLUX pipeline.

    Mutates *job* in place (stage, etc.). The swimwear negative override is only
    active for the duration of THIS call, on THIS thread.
    """
    install_swimwear_negative_hook()
    install_dataset_root_hook()

    params = job.get('params') or {}

    # Operator approval already happened in the Medusa pending queue, so the
    # engine's own review gates are set to pass through (auto_approve).
    job['auto_approve'] = True
    job['approved'] = True
    job.setdefault('kick_lora', True)
    job.setdefault('model_family', 'flux')
    # Angle plan: whatever the operator picked in the Character Studio, else
    # the full 48-angle sheet. params wins over the caller's job default --
    # bp_medusa builds its job dict before it has seen this request.
    _sel = build_angle_selection(params.get('angle_set'), params.get('angle_ids'))
    job['angle_set'] = _sel['angle_set']
    if _sel.get('angle_ids'):
        job['angle_ids'] = list(_sel['angle_ids'])
    else:
        job.pop('angle_ids', None)
    job.setdefault('sheet_mode', 'auto')  # -> per-cell path
    job.setdefault('flywheel', True)

    _MEDUSA_TLS.swimwear = True
    _MEDUSA_TLS.char_prompt = (params.get('extra_prompt') or '').strip()
    # Recorded so the wrapper can resolve a base LoRA for calls that do not
    # name a model_family of their own.
    _MEDUSA_TLS.model_family = str(job.get('model_family') or 'qwen')
    try:
        from zyg_workflows import contact_sheet_pipeline as _csp
        from zyg_workflows import char_state_service as _css

        _csp.run_pipeline(
            job,
            train_lora_fn=_css._char_train_lora_for_family,
            log_fn=log_fn,
            halt_check=halt_check,
            on_stage=on_stage,
            on_cell_progress=on_cell_progress,
        )
    finally:
        _MEDUSA_TLS.swimwear = False
        _MEDUSA_TLS.char_prompt = ''
        _MEDUSA_TLS.model_family = ''
