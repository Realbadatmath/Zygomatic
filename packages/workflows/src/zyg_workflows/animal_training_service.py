# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
animal_training_service.py
==========================
Animal Creation — multi-angle quadruped reference dataset + SimpleTuner LoRA
training. Produces a custom animal identity LoRA (2D FLUX photoreal, optional 3D
SDXL animated / Arcane twin) and — unlike the creature service — writes the
trained weights back into the animal's CHARACTER-BIBLE-SHAPED conditioning block
(via animal_bible_service.update_lora) so the video renderer can consume it.

Cloned from creature_training_service.py. Structure, error-handling and
robustness are preserved; only the human/creature specifics were adapted to
quadruped animals, and the bible write-back was added.

SHARED CONTRACT (honoured exactly):
  DATASET_ROOT = $ZYG_LORA_DATASETS/animals
  OUTPUT_ROOT  = $ZYG_LORA_OUTPUTS/animals
  bible file   = animal_bible.json
  animal_id    = uuid4().hex[:12]  (^[a-f0-9]{12}$)
  trigger      = 'ZYG_ANIMAL_' + animal_id[:6].upper()
  LoRA dirs are family-suffixed: OUTPUT_ROOT/<id>/lora-weights-flux and
  OUTPUT_ROOT/<id>/lora-weights-sdxl (handled by lora_trainer_service).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

_AMS = ZoneInfo('Europe/Amsterdam')
DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'animals')
OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'animals')
BIBLE_FILE = 'animal_bible.json'

_ID_RE = re.compile(r'^[a-f0-9]{12}$')

# ~20 quadruped reference angles (front / three-quarter L+R / side L+R / rear /
# low + high angle / close-up head / full body standing / walking + fills).
ANIMAL_ANGLE_PROMPTS = [
    'front view, full body standing, centered',
    'three-quarter front-left view, full body standing',
    'three-quarter front-right view, full body standing',
    'left side profile, full body standing',
    'right side profile, full body standing',
    'rear view, full body standing, tail visible',
    'three-quarter rear-left view, full body',
    'three-quarter rear-right view, full body',
    'low angle hero shot, full body, looking ahead',
    'high angle overhead three-quarter view, full body',
    'front view, medium shot, head and chest',
    'three-quarter left, medium shot',
    'three-quarter right, medium shot',
    'front close-up, head detail, eyes and muzzle',
    'three-quarter left close-up, head detail',
    'side profile close-up, head detail',
    'full body walking pose, side view',
    'full body walking pose, three-quarter view',
    'full body standing alert pose, ears forward',
    'extreme close-up, fur or coat texture detail',
]

_PREVIEW_SLOTS = [
    ('preview_front', 'front view, full body standing, dramatic natural lighting'),
    ('preview_three_quarter', 'three-quarter left view, medium shot, cinematic wildlife'),
    ('preview_closeup', 'close-up head portrait, detailed eyes and coat texture'),
]

# photoreal FLUX default conditioning (bible-shaped)
_DEFAULT_QUALITY_SUFFIX = (
    'single animal subject, quadruped, clean neutral background or natural habitat, '
    'high detail reference image, sharp fur feather or scale texture, natural lighting, '
    'no humans, no people'
)
_DEFAULT_NEGATIVE = (
    'human, person, man, woman, people, portrait, office, classroom, text, watermark, '
    'signature, duplicate animal, two animals, extra limbs, extra legs, missing legs, '
    'deformed anatomy, fused limbs, bipedal, anthropomorphic, cartoon, anime, chibi, '
    'lowres, blurry'
)


def _ensure_comfy_env() -> None:
    try:
        from zyg_workflows import _comfy_client as _cc
    except ImportError:
        return
    if _cc.server_reachable():
        os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
        os.environ.setdefault('ZYG_USE_COMFYUI', '1')


def _runtime_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'runtime')


def _state_path(animal_id: str) -> str:
    safe_id = ''.join(c for c in (animal_id or '') if c.isalnum() or c in '-_')
    return os.path.join(_runtime_dir(), f'animal_gen_{safe_id or "unknown"}.json')


def _ams_iso() -> str:
    return datetime.now(_AMS).isoformat()


def _generate_animal_brief(directive: str, log_fn) -> dict:
    """Claude (or heuristic fallback) → bible-shaped identity fields for a quadruped."""
    ak = os.environ.get('ANTHROPIC_API_KEY', '')
    fallback = {
        'display_name': directive[:60].strip() or 'Animal',
        'description': directive[:300],
        'species': 'animal',
        'breed': '',
        'coat_color': '',
        'coat_pattern': '',
        'body_type': '',
        'size': '',
        'distinctive_marks': '',
        'visual_traits': directive[:200],
    }
    if not ak:
        return fallback

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ak)
        resp = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1024,
            system=(
                'You write concise animal identity briefs for LoRA training datasets. '
                'The subject is always a real-world-style quadruped animal (four-legged, '
                'non-anthropomorphic). Output ONLY valid JSON.'
            ),
            messages=[
                {
                    'role': 'user',
                    'content': (
                        f'Animal concept:\n"{directive}"\n\n'
                        'Return JSON with keys: display_name, description (<=250 chars, '
                        'visual only), species (common animal species, e.g. dog, horse, '
                        'wolf, tiger), breed (or "" if none), coat_color, coat_pattern '
                        '(e.g. solid, brindle, spotted, tabby, "" if none), body_type '
                        '(e.g. lean, muscular, stocky), size (e.g. small, medium, large), '
                        'distinctive_marks (scars, blaze, socks, "" if none), '
                        'visual_traits (colors, size, distinctive features, <=180 chars)'
                    ),
                }
            ],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
        data = json.loads(raw)
        return {
            'display_name': str(data.get('display_name') or fallback['display_name'])[:80],
            'description': str(data.get('description') or fallback['description'])[:300],
            'species': str(data.get('species') or 'animal')[:80],
            'breed': str(data.get('breed') or '')[:80],
            'coat_color': str(data.get('coat_color') or '')[:80],
            'coat_pattern': str(data.get('coat_pattern') or '')[:80],
            'body_type': str(data.get('body_type') or '')[:80],
            'size': str(data.get('size') or '')[:40],
            'distinctive_marks': str(data.get('distinctive_marks') or '')[:160],
            'visual_traits': str(data.get('visual_traits') or fallback['visual_traits'])[:200],
        }
    except Exception as exc:
        log_fn(f'Animal brief parse failed ({exc}) — using heuristic brief')
        return fallback


def _build_base_prompt(trigger: str, brief: dict) -> str:
    desc = brief.get('description') or brief.get('visual_traits') or 'animal'
    identity_bits = [
        brief.get('coat_color', ''),
        brief.get('coat_pattern', ''),
        brief.get('body_type', ''),
        brief.get('size', ''),
        brief.get('breed', ''),
        brief.get('species', ''),
    ]
    identity = ', '.join(b for b in identity_bits if b)
    marks = brief.get('distinctive_marks', '')
    parts = [trigger, desc, identity, marks, brief.get('visual_traits', '')]
    parts.append(
        'single animal subject, quadruped, four legs, non-anthropomorphic, '
        'clean neutral background or natural habitat, high detail reference image, '
        'photorealistic, no humans, no people'
    )
    return ', '.join(p for p in parts if p)


def _generate_reference_images(
    animal_id: str,
    brief: dict,
    dataset_dir: str,
    trigger: str,
    log_fn,
    uploaded_paths: list[str] | None = None,
) -> list[str]:
    os.makedirs(dataset_dir, exist_ok=True)

    if uploaded_paths:
        images: list[str] = []
        for idx, src in enumerate(uploaded_paths[:20]):
            if not src or not os.path.isfile(src):
                continue
            ext = os.path.splitext(src)[1].lower() or '.png'
            dst = os.path.join(dataset_dir, f'upload_{idx:02d}{ext}')
            shutil.copy2(src, dst)
            images.append(dst)
        if images:
            log_fn(f'Using {len(images)} uploaded reference photo(s)')
            return images

    _ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as _cgs

    if not _cgs.is_available():
        raise RuntimeError('ComfyUI required for animal reference generation (ZYG_COMFY_PRIMARY=1)')

    base = _build_base_prompt(trigger, brief)
    neg = _DEFAULT_NEGATIVE
    images = []
    for idx, angle in enumerate(ANIMAL_ANGLE_PROMPTS):
        prompt = f'{base}, {angle}'
        dest = os.path.join(dataset_dir, f'ref_{idx:02d}.png')
        ok, backend = _cgs.generate_still(
            dest,
            prompt,
            width=768,
            height=768,
            steps=20,
            cfg=3.5,
            seed=1000 + idx,
            model_family='flux',
            log_fn=log_fn,
            extra_negative=neg,
            skip_qa=True,
            # No package here, so the bible hands this render its package-less
            # base + _ANATOMY_NEG — "extra fingers, three fingers, four fingers,
            # malformed hands, claw hands, asymmetric earrings". Person-only
            # clauses on a quadruped (2026-08-26, same defect as the creature path).
            human_subject=False,
        )
        if ok and os.path.isfile(dest):
            images.append(dest)
            log_fn(f'Reference {idx + 1}/{len(ANIMAL_ANGLE_PROMPTS)} OK ({backend})')
        else:
            log_fn(f'Reference {idx + 1} failed ({backend})')

    if len(images) < 8:
        raise RuntimeError(f'Only {len(images)} reference images generated — need at least 8 for LoRA training')
    return images


def _write_captions(images: list[str], brief: dict, trigger: str) -> int:
    """One .txt per image; each caption BEGINS with the trigger token."""
    species = brief.get('species') or 'animal'
    desc = brief.get('description') or brief.get('visual_traits') or species
    identity_bits = [
        brief.get('coat_color', ''),
        brief.get('coat_pattern', ''),
        brief.get('body_type', ''),
        brief.get('size', ''),
        brief.get('breed', ''),
    ]
    identity = ', '.join(b for b in identity_bits if b)
    marks = brief.get('distinctive_marks', '')

    for idx, img_path in enumerate(images):
        angle = ANIMAL_ANGLE_PROMPTS[idx % len(ANIMAL_ANGLE_PROMPTS)]
        caption = ', '.join(
            p
            for p in (
                trigger,
                desc,
                identity,
                species,
                marks,
                angle,
                'photorealistic animal reference, quadruped, detailed coat texture',
            )
            if p
        )
        with open(os.path.splitext(img_path)[0] + '.txt', 'w', encoding='utf-8') as fh:
            fh.write(caption)
    return len(images)


def _wait_for_lora_training(
    animal_id: str,
    model_family: str,
    log_fn,
    timeout_s: int = 3600,
    halt_check=None,
) -> dict:
    from zyg_workflows import lora_trainer_service as _lts

    trainer = _lts.get_trainer()
    elapsed = 0
    last_pct = -1
    status: dict = {}
    while elapsed < timeout_s:
        if callable(halt_check):
            halt_check()
        time.sleep(10)
        elapsed += 10
        status = trainer.get_status(animal_id, model_family=model_family, output_root=OUTPUT_ROOT)
        pct = int(status.get('pct') or 0)
        if pct != last_pct and pct > 0 and pct % 10 == 0:
            log_fn(
                f'{model_family.upper()} LoRA training {pct}% '
                f'({status.get("step", 0)}/{status.get("total_steps", 0)} steps)'
            )
            last_pct = pct
        if status.get('done'):
            log_fn(f'{model_family.upper()} LoRA training complete: {status.get("lora_path") or "checkpoint saved"}')
            return status
        if status.get('failed'):
            raise RuntimeError(status.get('error') or f'{model_family} LoRA training failed')
    raise RuntimeError(f'{model_family.upper()} LoRA training timed out after {timeout_s // 60} min')


def _clip_desc(desc: str, limit: int = 220) -> str:
    """Trim a brief's description for a validation prompt.

    A validation prompt is encoded once per sample and every family truncates
    (CLIP hardest), so a runaway brief pushes the trigger token — the one word
    the sample exists to test — out of the useful end of the context. Prefer the
    last SENTENCE that fits; fall back to a word boundary only when that would
    throw away most of the description.
    """
    desc = ' '.join((desc or '').split())
    if len(desc) <= limit:
        return desc.rstrip(' ,;.')
    head = desc[:limit]
    dot = head.rfind('. ')
    if dot >= int(limit * 0.6):
        return head[:dot].rstrip(' ,;.')
    return head.rsplit(' ', 1)[0].rstrip(' ,;.')


def _val_prompt(brief: dict, trigger: str) -> str:
    """The prompt SimpleTuner validates an ANIMAL LoRA with.

    See lora_trainer_service._validation_prompt: both of its train_mode branches
    describe a human, so without this an animal LoRA renders its validation
    samples as "<trigger> person, head and shoulders portrait ... visible pores".
    Shaped like the front slot of _PREVIEW_SLOTS so the validation frame and
    preview_front differ only by training step.
    """
    desc = _clip_desc(brief.get('description') or brief.get('visual_traits') or brief.get('species') or 'animal')
    return (
        f'{trigger}, {desc}, front view, full body standing, dramatic '
        f'natural lighting, cinematic animal portrait, quadruped, highly detailed'
    )


def _train_one_leg(
    animal_id: str,
    dataset_dir: str,
    trigger: str,
    model_family: str,
    log_fn,
    halt_check=None,
    brief: dict | None = None,
) -> dict:
    """Start + wait for one SimpleTuner leg. Returns the trainer status dict."""
    from zyg_workflows import lora_trainer_service as _lts

    trainer = _lts.get_trainer()
    # Step-scaled kill budget (mirrors char_state_service): a flat hour SIGKILLs
    # 1024px SDXL / FLUX runs that legitimately take longer.
    _steps = int(os.environ.get('ZYG_LORA_TRAIN_STEPS', '1200'))
    _timeout = int(os.environ.get('ZYG_LORA_TIMEOUT_SEC', str(_steps * 6 + 30 * 60)))
    trainer.start_training(
        animal_id,
        dataset_dir,
        trigger_token=trigger,
        model_family=model_family,
        output_root=OUTPUT_ROOT,
        # Same defect as creatures: the trainer's own validation prompt describes
        # a HUMAN under both train_mode branches, so an animal LoRA was validated
        # as "<trigger> person, head and shoulders portrait ... visible pores".
        # Shaped like the front slot of _PREVIEW_SLOTS so the validation frame and
        # preview_front differ only by training step.
        validation_prompt=_val_prompt(brief or {}, trigger),
    )
    status = _wait_for_lora_training(
        animal_id,
        model_family,
        log_fn,
        timeout_s=_timeout,
        halt_check=halt_check,
    )
    lora_path = status.get('lora_path') or trainer.get_lora_path(
        animal_id,
        model_family=model_family,
        output_root=OUTPUT_ROOT,
    )
    status['lora_path'] = lora_path
    return status


def _build_sdxl_dataset(
    animal_id: str,
    photoreal_dir: str,
    restyle: str,
    log_fn,
) -> str:
    """Restyle the photoreal FLUX tiles into the SDXL training set.

    style_profile.restyle set  -> arcane_restyle.build_styled_sdxl_dataset
    otherwise                  -> animated_sdxl_dataset.build_animated_sdxl_dataset
    """
    if restyle:
        from zyg_workflows import arcane_restyle as _styled

        prof = _styled.load_profile(restyle)
        if not (prof and prof.get('restyle')):
            # Fail LOUD — a silent fall-through to the global 3D-toon dataset would
            # ship a toon twin for an animal explicitly flagged for an isolated style.
            raise RuntimeError(
                f'style_profile.restyle={restyle!r} did not resolve to a valid restyle '
                f'profile in character_style_profiles.json — refusing to silently fall '
                f'back to the global 3D-toon dataset (use the exact profile key, '
                f"e.g. 'arcane_animation')"
            )
        out = _styled.build_styled_sdxl_dataset(
            animal_id,
            photoreal_dir,
            style_cfg=prof['restyle'],
            log_fn=log_fn,
        )
        log_fn(f'SDXL styled dataset ({restyle}) ready → {out}')
        return out

    from zyg_workflows import animated_sdxl_dataset as _anim_ds

    out = _anim_ds.build_animated_sdxl_dataset(animal_id, photoreal_dir, log_fn=log_fn)
    log_fn(f'SDXL animated dataset ready → {out}')
    return out


def _write_bible_lora(
    animal_id: str,
    model_family: str,
    lora_path: str | None,
    sdxl_checkpoint: str | None,
    log_fn,
) -> None:
    """KEY DIVERGENCE FROM CREATURES: populate the animal bible conditioning block
    so the video renderer can consume the trained LoRA. Best-effort + fail-safe —
    a failed write-back must not fail the (successful) training."""
    try:
        from zyg_workflows import animal_bible_service as _abs
    except Exception as exc:
        log_fn(f'animal_bible_service unavailable — LoRA not written to bible ({exc})')
        return
    try:
        # Preferred keyword form (mirrors character_bible_service.update_lora).
        _abs.update_lora(
            animal_id,
            lora_path=lora_path,
            model_family=model_family,
            sdxl_checkpoint=sdxl_checkpoint,
            log_fn=log_fn,
        )
    except TypeError:
        # Tolerate a leaner signature (positional lora_path, no sdxl_checkpoint).
        try:
            _abs.update_lora(animal_id, lora_path, model_family=model_family)
        except Exception as exc:
            log_fn(f'animal_bible update_lora failed ({model_family}): {exc}')
    except Exception as exc:
        log_fn(f'animal_bible update_lora failed ({model_family}): {exc}')


def _render_previews(
    animal_id: str,
    brief: dict,
    lora_path: str,
    dataset_dir: str,
    trigger: str,
    log_fn,
) -> list[str]:
    if not lora_path or not os.path.isfile(lora_path):
        log_fn('Preview skipped — no trained LoRA checkpoint')
        return []

    _ensure_comfy_env()
    from zyg_workflows import comfy_generation_service as _cgs

    if not _cgs.is_available():
        log_fn('Preview skipped — ComfyUI unavailable')
        return []

    desc = brief.get('description') or brief.get('visual_traits') or 'animal'
    rendered: list[str] = []
    for stem, angle in _PREVIEW_SLOTS:
        prompt = f'{trigger}, {desc}, {angle}, cinematic animal portrait, quadruped, highly detailed'
        dest = os.path.join(dataset_dir, f'{stem}.png')
        ok, backend = _cgs.generate_still(
            dest,
            prompt,
            width=1024,
            height=1024,
            steps=20,
            cfg=3.5,
            seed=42 + len(rendered),
            model_family='flux',
            log_fn=log_fn,
            extra_negative=_DEFAULT_NEGATIVE,
            style_lora_path=lora_path,
            style_lora_scale=0.85,
            skip_qa=True,
            human_subject=False,
        )
        if ok and os.path.isfile(dest):
            rendered.append(dest)
            log_fn(f'Preview {stem} OK ({backend})')
    return rendered


# ── Orchestrator ────────────────────────────────────────────────────────────────

_STAGE_KEYS = {
    'Animal Brief': 'animal_brief',
    'Reference Image Generation': 'reference_gen',
    'Caption Generation': 'captions',
    'LoRA Training': 'lora_training',
    'Preview Render': 'preview_render',
}


def run_animal_training(job: dict) -> None:
    """Train an animal identity LoRA (FLUX always; SDXL twin when 3D requested)
    and write the weights back into the animal bible. Mutates *job* in place and
    persists progress to data/runtime/animal_gen_<id>.json (department='animal').

    Expected job keys:
      animal_id   : uuid4().hex[:12] (required)
      directive   : free-text concept (required)
      image_paths : optional list[str] of uploaded reference photos
      model_family: 'flux' | 'sdxl' (sdxl ⇒ also train the 3D twin)
      want_3d     : optional bool alias forcing the SDXL leg
      style_profile.restyle / restyle : optional isolated style (e.g. 'arcane_animation')
      stop_event  : optional threading.Event for cooperative halt
    """
    animal_id = str(job.get('animal_id') or job.get('id') or '').strip()
    directive = str(job.get('directive') or job.get('prompt') or job.get('topic') or '').strip()

    if not _ID_RE.match(animal_id):
        raise ValueError(f'animal_id must match ^[a-f0-9]{{12}}$ (got {animal_id!r})')

    dataset_dir = os.path.join(DATASET_ROOT, animal_id)
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(_runtime_dir(), exist_ok=True)
    trigger = f'ZYG_ANIMAL_{animal_id[:6].upper()}'

    model_family = str(job.get('model_family') or 'flux').strip().lower()
    if model_family not in ('flux', 'sdxl'):
        model_family = 'flux'
    want_3d = bool(
        model_family == 'sdxl'
        or job.get('want_3d')
        or job.get('train_3d')
        or job.get('render_3d')
        or job.get('train_sdxl')
    )
    restyle = str((job.get('style_profile') or {}).get('restyle') or job.get('restyle') or '').strip()

    image_paths = job.get('image_paths') or []

    job['animal_id'] = animal_id
    job['department'] = 'animal'
    job['dataset_dir'] = dataset_dir
    job['trigger_token'] = trigger
    job['output_root'] = OUTPUT_ROOT
    job.setdefault('status', 'running')
    job.setdefault('started', _ams_iso())
    job.setdefault('stage_timeline', [])

    def _save_state() -> None:
        try:
            snapshot = dict(job)
            evs = snapshot.get('debug_events') or []
            if len(evs) > 50:
                snapshot['debug_events'] = evs[-50:]
            snapshot.pop('stop_event', None)  # not JSON-serialisable
            tmp = _state_path(animal_id) + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(snapshot, fh, default=str)
            os.replace(tmp, _state_path(animal_id))
        except Exception as exc:
            _zyg_log.info(f'[ANIMAL-STATE] save failed for {animal_id}: {exc}')

    def _slog(msg: str, stage: str = 'Animal', level: str = 'INFO') -> None:
        ev = {'ts': _ams_iso(), 'level': level, 'stage': stage, 'msg': msg}
        job.setdefault('debug_events', []).append(ev)
        if len(job['debug_events']) > 500:
            job['debug_events'] = job['debug_events'][-300:]
        _zyg_log.info(f'[ANIMAL-TRAIN][{level}][{stage}] {msg}')

    def _set_stage(name: str, status: str = 'running') -> None:
        job['current_stage'] = name
        job['stage'] = _STAGE_KEYS.get(name, name.lower().replace(' ', '_'))
        tl = job.setdefault('stage_timeline', [])
        for entry in tl:
            if entry['name'] == name:
                entry['status'] = status
                if status == 'completed' and not entry.get('ended_at'):
                    entry['ended_at'] = _ams_iso()
                _save_state()
                return
        tl.append({'name': name, 'status': status, 'ts': _ams_iso(), 'started_at': _ams_iso()})
        _save_state()

    def _complete_stage(name: str) -> None:
        _set_stage(name, 'completed')

    def _fail_stage(name: str, err: str) -> None:
        _set_stage(name, 'failed')
        job['error'] = err
        job['status'] = 'failed'
        job['ended'] = _ams_iso()
        _save_state()

    def _halt() -> None:
        ev = job.get('stop_event')
        if ev is not None and ev.is_set():
            raise RuntimeError('Animal training stopped by user')

    try:
        _halt()
        # ── Stage 1: Animal Brief ────────────────────────────────────────────
        _set_stage('Animal Brief')
        _slog(f'Animal brief: {directive[:120]}', 'Stage 1')
        brief = _generate_animal_brief(directive, lambda m: _slog(m, 'Stage 1'))
        job['brief'] = brief
        job['display_name'] = brief.get('display_name')
        job['species'] = brief.get('species')
        _complete_stage('Animal Brief')

        # ── Stage 2: Reference Image Generation ──────────────────────────────
        _halt()
        _set_stage('Reference Image Generation')
        images = _generate_reference_images(
            animal_id,
            brief,
            dataset_dir,
            trigger,
            lambda m: _slog(m, 'Stage 2'),
            uploaded_paths=image_paths,
        )
        job['image_count'] = len(images)
        manifest = {
            'animal_id': animal_id,
            'display_name': brief.get('display_name'),
            'description': brief.get('description'),
            'species': brief.get('species'),
            'trigger_token': trigger,
            'images': images,
            'total': len(images),
            'source': 'uploaded_photos' if image_paths else 'flux_reference_gen',
        }
        with open(os.path.join(dataset_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, indent=2)
        _complete_stage('Reference Image Generation')

        # ── Stage 3: Caption Generation ──────────────────────────────────────
        _halt()
        _set_stage('Caption Generation')
        cap_n = _write_captions(images, brief, trigger)
        _slog(f'{cap_n} training captions written (each begins with trigger {trigger})', 'Stage 3')
        _complete_stage('Caption Generation')

        # ── Stage 4: LoRA Training (FLUX always; SDXL twin when 3D) ───────────
        _halt()
        _set_stage('LoRA Training')

        # FLUX leg — always.
        _slog('Training FLUX (2D photoreal) LoRA leg', 'Stage 4')
        flux_status = _train_one_leg(
            animal_id,
            dataset_dir,
            trigger,
            'flux',
            lambda m: _slog(m, 'Stage 4'),
            halt_check=_halt,
            brief=brief,
        )
        flux_lora = flux_status.get('lora_path')
        job['flux_lora_path'] = flux_lora
        job['lora_path'] = flux_lora
        _write_bible_lora(animal_id, 'flux', flux_lora, None, lambda m: _slog(m, 'Stage 4'))

        # SDXL leg — only when a 3D twin is requested.
        sdxl_lora = None
        if want_3d:
            _halt()
            _slog(
                f'Training SDXL (3D {"arcane " + restyle if restyle else "animated"}) twin leg',
                'Stage 4',
            )
            sdxl_dataset = _build_sdxl_dataset(
                animal_id,
                dataset_dir,
                restyle,
                lambda m: _slog(m, 'Stage 4'),
            )
            sdxl_status = _train_one_leg(
                animal_id,
                sdxl_dataset,
                trigger,
                'sdxl',
                lambda m: _slog(m, 'Stage 4'),
                halt_check=_halt,
                brief=brief,
            )
            sdxl_lora = sdxl_status.get('lora_path')
            job['sdxl_lora_path'] = sdxl_lora
            _write_bible_lora(
                animal_id,
                'sdxl',
                sdxl_lora,
                sdxl_status.get('sdxl_comfy_checkpoint'),
                lambda m: _slog(m, 'Stage 4'),
            )
        _complete_stage('LoRA Training')

        # ── Stage 5: Preview Render (FLUX photoreal) ─────────────────────────
        _halt()
        _set_stage('Preview Render')
        previews = _render_previews(
            animal_id,
            brief,
            flux_lora or '',
            dataset_dir,
            trigger,
            lambda m: _slog(m, 'Stage 5'),
        )
        job['preview_images'] = previews
        _complete_stage('Preview Render')

        job['status'] = 'completed'
        job['stage'] = 'done'
        job['current_stage'] = 'done'
        job['result'] = {
            'animal_id': animal_id,
            'trigger_token': trigger,
            'dataset_dir': dataset_dir,
            'flux_lora_path': flux_lora,
            'sdxl_lora_path': sdxl_lora,
            'output_root': OUTPUT_ROOT,
            'preview_images': previews,
            'image_count': len(images),
            'trained_3d': bool(sdxl_lora),
        }
        job['ended'] = _ams_iso()
        _save_state()
        _slog(f'Animal LoRA ready — trigger {trigger}, flux={flux_lora}, sdxl={sdxl_lora}', 'Done')

    except RuntimeError as stop_exc:
        if 'stopped by user' in str(stop_exc).lower():
            job['status'] = 'stopped'
            job['error'] = str(stop_exc)
            job['ended'] = _ams_iso()
            _set_stage(job.get('current_stage') or 'LoRA Training', 'failed')
            _slog(str(stop_exc), 'Animal Training', 'WARN')
            _save_state()
            return
        import traceback

        _fail_stage(job.get('current_stage') or 'Animal Training', str(stop_exc))
        _slog(traceback.format_exc()[-800:], 'Animal Training', 'ERROR')
    except Exception as exc:
        import traceback

        _fail_stage(job.get('current_stage') or 'Animal Training', str(exc))
        _slog(traceback.format_exc()[-800:], 'Animal Training', 'ERROR')
