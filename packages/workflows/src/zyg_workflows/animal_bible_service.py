# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
animal_bible_service.py
=======================
Persistent "synthetic animal" packages for long-form visual continuity.

Clone / animal-adaptation of ``character_bible_service.py``. Each animal has an
``animal_bible.json`` beside its dataset under
``lora-datasets/animals/<animal_id>/``.

The bible is stored CHARACTER-BIBLE-SHAPED (a conditioning block, not a
creature-manifest) so the *same* video renderer (``comfy_generation_service``)
consumes it. Every ``_bible.<fn>(character_package)`` call the renderer makes on
the human bible module is reproduced here with the identical signature so this
module is a drop-in for animals.

Design (confirmed 2026-07-29):
  • 2D  = FLUX photoreal   (render_style 'photorealistic')
  • 3D  = SDXL animated 3D-toon twin (sdxl_render_style 'animated')
  • Arcane = style_profile.restyle='arcane_animation' baked into the LoRA,
    rendered through the depth_controlnet engine.

FACELESS-SAFE: animals are quadrupeds with no human face to lock — InstantID /
face-lock / FaceDetailer are NEVER enabled. All human-only descriptor logic
(skin tone, hair colour, age band, smile, human anatomy) is a safe no-op here so
a human helper can never inject human text onto a quadruped.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


# ── SHARED CONTRACT roots (must match every animal module exactly) ────────────
_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'animals')
_OUTPUT_ROOT = str(paths.ZYG_LORA_OUTPUTS / 'animals')
_BIBLE_FILENAME = 'animal_bible.json'
_SCHEMA_VERSION = 1

# ── Sentinel value meaning "let the auto-defaults engine pick" ───────────────
AUTO = 'auto'


def _is_auto(v: Any) -> bool:
    """True if a value should be replaced by the auto-defaults engine."""
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip().lower()
        return s in ('', 'auto', 'none-selected', 'default', '(auto)')
    return False


def trigger_for(animal_id: str) -> str:
    """Deterministic trigger token per the shared contract."""
    return 'ZYG_ANIMAL_' + (animal_id or '')[:6].upper()


def bible_path(animal_id: str) -> str:
    return os.path.join(_DATASET_ROOT, animal_id, _BIBLE_FILENAME)


try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None


def _utc_now() -> str:
    """ISO timestamp in Europe/Amsterdam (function name is historical).

    The whole server speaks one timezone; the value is Amsterdam local time
    with offset (``+02:00`` summer / ``+01:00`` winter).
    """
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ).isoformat(timespec='milliseconds')
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timestamp unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


# ──────────────────────────────────────────────────────────────────────────────
# Reference-image selection
# ──────────────────────────────────────────────────────────────────────────────
def _pick_reference_images(dataset_dir: str, limit: int = 6) -> list[str]:
    """Prefer portrait / front / profile references for identity conditioning.

    Animal datasets reuse the storyteller preview naming where present; anything
    unmatched falls back to a size-filtered directory scan so a freshly-built
    animal set still yields references.
    """
    if not dataset_dir or not os.path.isdir(dataset_dir):
        return []
    priority = (
        'preview_sdxl_front.png',
        'preview_sdxl_side.png',
        'preview_flux_front.png',
        'preview_flux_side.png',
        'portrait_00_000deg.png',
        'side_profile_000deg.png',
        'full_neutral_000deg.png',
        'full_00_000deg.png',
    )
    found: list[str] = []
    for name in priority:
        p = os.path.join(dataset_dir, name)
        if os.path.isfile(p) and os.path.getsize(p) > 10_000:
            found.append(p)
    if len(found) >= limit:
        return found[:limit]
    extras = sorted(
        os.path.join(dataset_dir, f)
        for f in os.listdir(dataset_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('preview_')
    )
    for p in extras:
        if p not in found and os.path.getsize(p) > 10_000:
            found.append(p)
        if len(found) >= limit:
            break
    return found[:limit]


def _find_lora_path(animal_id: str, model_family: str | None = None) -> Optional[str]:
    """Resolve the newest trained LoRA for an animal, honouring the
    family-suffixed directory contract (``lora-weights-flux`` / ``-sdxl``)."""
    mf = (model_family or '').strip().lower() or None
    try:
        import importlib.util as _ilu

        spec = _ilu.find_spec('lora_trainer_service')
        if spec:
            from zyg_workflows import lora_trainer_service as _lts

            return _lts.get_trainer().get_lora_path(animal_id, model_family=mf)
    except Exception as _exc:
        _zyg_log.debug('lora path via the trainer service unavailable: %s', _exc)
    try:
        from zyg_workflows import lora_trainer_service as _lts_fb

        return _lts_fb._find_latest_checkpoint(
            os.path.join(_OUTPUT_ROOT, animal_id),
            model_family=mf,
        )
    except Exception as _exc:
        _zyg_log.debug('lora checkpoint scan fallback failed: %s', _exc)
    roots = []
    if mf:
        roots.append(os.path.join(_OUTPUT_ROOT, animal_id, f'lora-weights-{mf}'))
    roots.append(os.path.join(_OUTPUT_ROOT, animal_id, 'lora-weights'))
    best: Optional[str] = None
    best_step = -1
    for out in roots:
        if not os.path.isdir(out):
            continue
        for root, _, files in os.walk(out):
            for fn in files:
                if fn.endswith('.safetensors'):
                    full = os.path.join(root, fn)
                    import re

                    m = re.search(r'checkpoint-(\d+)', full)
                    step = int(m.group(1)) if m else 0
                    if step >= best_step:
                        best_step = step
                        best = full
    return best


# ──────────────────────────────────────────────────────────────────────────────
# Default package (contract schema)
# ──────────────────────────────────────────────────────────────────────────────
def default_package(
    animal_id: str,
    display_name: str = '',
    species: str = '',
) -> dict[str, Any]:
    tok = trigger_for(animal_id)
    return {
        'schema_version': _SCHEMA_VERSION,
        'animal_id': animal_id,
        'trigger_token': tok,
        'display_name': display_name or '',
        'species': species or '',
        'created_at': _utc_now(),
        'updated_at': _utc_now(),
        # ── Identity — permanent, stable across productions ──────────────────
        # Any value may be '' / 'auto' / None to defer; downstream code reads
        # missing keys defensively so an animal with only species set still
        # renders.
        'identity': {
            'species': species or '',
            'breed': '',
            'coat_color': '',
            'coat_pattern': '',  # solid / brindle / spotted / tabby / …
            'body_type': '',  # lean / stocky / muscular / slender …
            'size': '',  # tiny / small / medium / large / giant
            'distinctive_marks': '',  # blaze / white socks / torn ear — 'none' OK
            'quadruped': True,
        },
        # ── Default presentation (swappable per scene) ───────────────────────
        'default_presentation': {
            'pose': '',  # standing / lying / running / alert …
            'environment_hint': '',  # natural habitat cue for previews
        },
        # ── Style / render profile ───────────────────────────────────────────
        'style_profile': {
            'render_style': 'photorealistic',
            'genre': '',
            'restyle': None,  # None | 'arcane_animation'
            'lighting_profile': '',
        },
        # ── ComfyUI / FLUX + SDXL conditioning ───────────────────────────────
        'conditioning': {
            'model_family': 'flux',
            'lora_path': None,
            'flux_lora_path': None,
            'sdxl_lora_path': None,
            'lora_scale': 0.85,
            'sdxl_checkpoint': None,
            'sdxl_render_style': None,  # None | 'animated'
            'ipadapter_reference_images': [],
            'master_reference_image': '',
            'ipadapter_scale': 0.65,
            # FACELESS-SAFE: never lock a (non-existent) human face on a quadruped.
            'instantid_enabled': False,
            'face_detail_pass': False,
            'quality_suffix': '',
            'negative_prompt': '',
        },
        'voice_profile': {},
        'motion_profile': {},
        'scene_history': [],
        'generation_stats': {'total_stills': 0, 'drift_retries': 0},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Identity / prompt helpers (animal-adapted)
# ──────────────────────────────────────────────────────────────────────────────
_SIZE_PHRASE = {
    'tiny': 'tiny miniature-sized animal',
    'small': 'small-sized animal',
    'medium': 'medium-sized animal',
    'large': 'large-sized animal',
    'giant': 'giant massive animal',
    'huge': 'very large animal',
}


def _size_text(size: Any) -> str:
    s = (str(size or '')).strip().lower()
    if not s:
        return ''
    return _SIZE_PHRASE.get(s, f'{s} size')


def _species_noun(ident: dict[str, Any]) -> str:
    species = (ident.get('species') or '').strip()
    breed = (ident.get('breed') or '').strip()
    if breed and species:
        return f'{breed} {species}'
    if breed:
        return breed
    if species:
        return species
    return 'animal'


def _coat_phrase(coat_color: Any, coat_pattern: Any) -> str:
    color = (str(coat_color or '')).strip()
    pattern = (str(coat_pattern or '')).strip()
    if pattern.lower() in ('none', 'n/a'):
        pattern = ''
    if color.lower() in ('none', 'n/a'):
        color = ''
    if color and pattern:
        return f'{color} {pattern} coat'
    if color:
        return f'{color} coat'
    if pattern:
        return f'{pattern} coat pattern'
    return ''


def identity_prompt_prefix(package: dict[str, Any] | None) -> str:
    """Permanent identity tokens — species/breed, coat, body, size, marks.

    Excludes pose / environment so presentation can change per scene without
    identity drift. Contains NO human descriptors (no skin/hair/age/eye/face
    logic) — those would be nonsensical on a quadruped.
    """
    if not package:
        return ''
    trig = package.get('trigger_token', '')
    ident = package.get('identity', {}) or {}
    style = package.get('style_profile', {}) or {}

    parts: list[str] = []
    if trig:
        parts.append(trig)

    # Species / breed noun — the load-bearing identity class token.
    parts.append(_species_noun(ident))

    coat = _coat_phrase(ident.get('coat_color'), ident.get('coat_pattern'))
    if coat:
        parts.append(coat)

    body = (ident.get('body_type') or '').strip()
    if body and body.lower() not in ('none', 'n/a'):
        parts.append(body if 'build' in body.lower() or 'body' in body.lower() else f'{body} build')

    size_txt = _size_text(ident.get('size'))
    if size_txt:
        parts.append(size_txt)

    marks = (ident.get('distinctive_marks') or '').strip()
    if marks and marks.lower() not in ('', 'none', 'n/a'):
        parts.append(marks)

    # Reinforce animal (non-anthropomorphic) anatomy so the render never drifts
    # toward a humanoid — the faceless-safe counterpart to the human anatomy
    # tokens. Gated on quadruped so a (rare) non-quadruped animal is not forced
    # onto all fours.
    if ident.get('quadruped', True):
        parts.append('four-legged quadruped animal, natural animal anatomy, on all fours')
    else:
        parts.append('natural animal anatomy')

    render = (style.get('render_style') or '').strip()
    if render:
        # Insert render-style class token early (position 2-3) so FLUX sees it
        # during the high-impact early denoising steps.
        _insert_pos = min(2, len(parts))
        parts.insert(_insert_pos, render)

    return ', '.join([p for p in parts if p])


def _presentation_from_package(package: dict[str, Any] | None) -> dict[str, str]:
    """Resolve default presentation — pose + environment hint."""
    if not package:
        return {}
    pres = package.get('default_presentation') or {}
    out: dict[str, str] = {}
    for key in ('pose', 'environment_hint'):
        val = (pres.get(key) or '').strip()
        if val:
            out[key] = val
    return out


def presentation_prompt_fragment(
    package: dict[str, Any] | None,
    *,
    include_lighting: bool = False,
) -> str:
    """Default presentation layer — pose, environment, optional lighting."""
    if not package:
        return ''
    pres = _presentation_from_package(package)
    style = package.get('style_profile', {}) or {}
    parts: list[str] = []

    pose = pres.get('pose', '')
    if pose:
        parts.append(pose if 'pose' in pose.lower() or 'ing' in pose.lower() else f'{pose} pose')

    env = pres.get('environment_hint', '')
    if env and env.strip().lower() not in ('', 'none'):
        parts.append(env)

    if include_lighting:
        lp = (style.get('lighting_profile') or '').strip()
        if lp:
            parts.append(lp)

    return ', '.join(parts)


# ── Human-only no-ops (kept so a human helper never injects human text) ───────
# The renderer calls these with hasattr/try guards. For animals they MUST return
# '' so no skin-tone / hair-colour / age-band / smile text ever lands on a
# quadruped. Signatures mirror the human module exactly.
def skin_tone_negatives(skin_tone: str, heritage: str | None = None) -> str:
    return ''


def hair_color_negatives(hair_color: str, heritage: str | None = None) -> str:
    return ''


def age_negatives(age) -> str:
    return ''


def wants_visible_smile_package(package: dict[str, Any] | None) -> bool:
    """Animals do not smile on cue; a human smile-lock must never fire here."""
    return False


def preview_expression_boost(params: dict[str, Any] | None) -> str:
    return ''


def face_detail_wildcard_for_params(params: dict[str, Any] | None) -> str:
    """No human face to detail on a quadruped — FaceDetailer never runs for
    animals, so this returns no wildcard (safe no-op)."""
    return ''


def storyteller_face_detail_enabled(
    shot_type: str = 'medium',
    scene_emotion: str = '',
) -> bool:
    """FACELESS-SAFE: the human FaceDetailer second pass is never enabled for
    animals regardless of shot type — there is no human face to lock or repair."""
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Background / quality / negative helpers
# ──────────────────────────────────────────────────────────────────────────────
_SOLO_SUBJECT_NEG = (
    'multiple animals, two animals, three animals, duplicate, twins, pack, herd, '
    'group shot, character sheet, lineup, extra animal, clone, collage'
)
_PREVIEW_SCENE_NEG = (
    'office, classroom, desk, table, chair, window, sunset, sunrise, balcony, '
    'sea, ocean, horizon, skyscape, papers, books, laptop, furniture, outdoor, '
    'cityscape, interior clutter'
)
# Animal-anatomy negatives (the faceless-safe replacement for the human
# extra-fingers / deformed-face wall) plus a strong anti-anthropomorphic push.
_ANIMAL_ANATOMY_NEG = (
    'extra legs, extra tails, two tails, missing legs, fused limbs, deformed paws, '
    'malformed hooves, extra heads, mutated body, bad anatomy, deformed limbs, '
    'melted body, distorted proportions'
)
_ANTHRO_NEG = (
    'human face, human hands, human fingers, anthropomorphic, humanlike, '
    'standing upright on two legs, wearing clothes, cartoon human, furry costume'
)
# Photoreal-fur defence — the animal analogue of the anti-waxy-skin negative.
_PHOTOREAL_FUR_NEG = 'plastic-looking fur, waxy fur, overly smooth cgi, toy-like, taxidermy, doll-like, rubber texture'


def negative_prompt_for_package(
    package: dict[str, Any] | None,
    *,
    studio_preview: bool = False,
) -> str:
    """Negative-prompt string for ComfyUI node 21 (always populated).

    ``studio_preview`` gates the environment ban (``_PREVIEW_SCENE_NEG``) so it
    only reaches clean-studio animal previews, never scene renders that legitimately
    ask for a habitat.
    """
    if not package:
        base = 'blurry, low quality, deformed, bad anatomy, extra limbs, watermark, text'
    else:
        cond = package.get('conditioning', {}) or {}
        neg = (cond.get('negative_prompt') or '').strip()
        if neg:
            base = neg
        else:
            base = (
                'blurry, low quality, low resolution, jpeg artifacts, '
                'deformed, bad anatomy, extra limbs, mutated, '
                'watermark, text, signature'
            )
    low = base.lower()
    if 'multiple animals' not in low and 'character sheet' not in low:
        base = f'{base}, {_SOLO_SUBJECT_NEG}'
    if studio_preview and 'office' not in low and 'desk' not in low:
        base = f'{base}, {_PREVIEW_SCENE_NEG}'
    if 'extra legs' not in low:
        base = f'{base}, {_ANIMAL_ANATOMY_NEG}'
    if 'anthropomorphic' not in low:
        base = f'{base}, {_ANTHRO_NEG}'
    if package:
        _rs = ((package.get('style_profile') or {}).get('render_style') or '').strip().lower()
        if _rs == 'photorealistic' and 'plastic-looking fur' not in low:
            base = f'{base}, {_PHOTOREAL_FUR_NEG}'
    return base


def preview_studio_suffix(package: dict[str, Any] | None) -> str:
    """Background tokens for animal preview stills (empty stage, no props)."""
    style = (package or {}).get('style_profile', {}) or {}
    lp = (style.get('lighting_profile') or '').strip()
    bits = [
        'plain neutral gray studio backdrop',
        'seamless empty stage',
        'soft directional studio key light with gentle shadow modelling',
        'natural light falloff',
        'no furniture',
        'no desk',
        'no window',
        'no outdoor scenery',
        'animal centered',
    ]
    if lp:
        bits.append(lp)
    return ', '.join(bits)


def quality_suffix_for_package(package: dict[str, Any] | None) -> str:
    """Photographic/illustrative quality booster appended after the scene description."""
    if not package:
        # No package can mean no animal in frame (establishing shots) — never
        # request a subject here or FLUX conjures an animal into the scene.
        return 'highly detailed, sharp focus, natural lighting'
    cond = package.get('conditioning', {}) or {}
    qs = (cond.get('quality_suffix') or '').strip()
    return qs or ('highly detailed, sharp focus, natural fur and texture detail, realistic wildlife photography')


def quality_suffix(package: dict[str, Any] | None = None) -> str:
    """Alias for ``quality_suffix_for_package`` (some callers use the short name)."""
    return quality_suffix_for_package(package)


def indoor_style_suffix(package: dict[str, Any] | None) -> str:
    if not package:
        return 'cinematic set, photorealistic, consistent environment, no copyrighted landmarks'
    style = package.get('style_profile', {}) or {}
    lp = (style.get('lighting_profile') or '').strip()
    bits = [
        'photorealistic',
        'consistent animal identity',
        'natural environment',
    ]
    if lp:
        bits.append(lp)
    return ', '.join(bits)


def get_master_reference(package: dict[str, Any] | None) -> Optional[str]:
    if not package:
        return None
    cond = package.get('conditioning', {}) or {}
    master = cond.get('master_reference_image')
    if master and os.path.isfile(master):
        return master
    refs = cond.get('ipadapter_reference_images') or []
    for p in refs:
        if p and os.path.isfile(p):
            return p
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────────
def migrate_package(package: dict[str, Any] | None) -> dict[str, Any] | None:
    """In-place schema upgrades for older / partial animal bibles."""
    if not package:
        return package
    package.setdefault('identity', {})
    package.setdefault('default_presentation', {})
    package.setdefault('style_profile', {})
    package.setdefault('conditioning', {})
    package.setdefault('voice_profile', {})
    package.setdefault('motion_profile', {})
    package.setdefault('scene_history', [])
    package.setdefault('generation_stats', {})
    ident = package['identity']
    ident.setdefault('quadruped', True)
    style = package['style_profile']
    style.setdefault('render_style', 'photorealistic')
    style.setdefault('restyle', None)
    cond = package['conditioning']
    # FACELESS-SAFE invariants survive any migration.
    cond.setdefault('instantid_enabled', False)
    cond.setdefault('face_detail_pass', False)
    cond.setdefault('model_family', 'flux')
    cond.setdefault('lora_scale', 0.85)
    cond.setdefault('ipadapter_scale', 0.65)
    package['schema_version'] = _SCHEMA_VERSION
    return package


def load(animal_id: str) -> Optional[dict[str, Any]]:
    path = bible_path(animal_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('animal_id') != animal_id:
            data['animal_id'] = animal_id
        return migrate_package(data)
    except Exception:
        return None


# Identity keys whose DELIVERED (rendered) value must survive a QC re-save —
# the animal analogue of the human eye/hair/skin sync keys.
_SYNCED_IDENTITY_KEYS = ('coat_color', 'coat_pattern')


def save(package: dict[str, Any]) -> str:
    """Persist a bible, with a 'delivered-reality-wins' guard.

    Mirrors ``character_bible_service`` ~1537-1571: once ``sync_delivered_attributes``
    has recorded what the shipped anchor actually looks like (its real coat), a
    later QC / upsert re-save that carries the ORIGINAL spec must not silently
    clobber those synced descriptors back to values the LoRA does not render.
    If the on-disk bible was synced from the delivered anchor and the incoming
    package is NOT itself the sync writer, the delivered coat descriptors win.
    """
    animal_id = package.get('animal_id', '')
    if not animal_id:
        raise ValueError('animal_id required')

    incoming_ident = package.get('identity') or {}
    if not incoming_ident.get('attributes_synced_from_anchor'):
        try:
            prev = load(animal_id)
        except Exception:
            prev = None
        prev_ident = (prev or {}).get('identity') or {}
        if prev_ident.get('attributes_synced_from_anchor'):
            ident = package.setdefault('identity', {})
            ident['attributes_synced_from_anchor'] = True
            for _k in _SYNCED_IDENTITY_KEYS:
                _dv = (prev_ident.get(_k) or '').strip()
                if _dv:
                    ident[_k] = _dv

    package['updated_at'] = _utc_now()
    os.makedirs(os.path.dirname(bible_path(animal_id)), exist_ok=True)
    path = bible_path(animal_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(package, f, indent=2)
    return path


def sync_delivered_attributes(
    animal_id: str,
    observed: dict[str, str],
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Write DELIVERED anchor coat attributes into the bible when they differ
    from the spec. Scene prompts are built from the bible — a bible that says
    'black coat' while the LoRA renders 'grey' makes every future scene fight the
    LoRA. Once an anchor ships, delivered reality wins (see ``save``)."""
    pkg = load(animal_id)
    if not pkg:
        return
    ident = pkg.setdefault('identity', {})
    changed: dict[str, tuple] = {}
    for k, v in (observed or {}).items():
        v = (v or '').strip().lower()
        if (
            k in _SYNCED_IDENTITY_KEYS
            and v
            and v not in ('unclear', 'other')
            and (ident.get(k) or '').strip().lower() != v
        ):
            changed[k] = (ident.get(k), v)
            ident[k] = v
    if not changed:
        return
    ident['attributes_synced_from_anchor'] = True
    save(pkg)
    if log_fn:
        log_fn(
            'Animal bible synced to delivered anchor attributes: '
            + ', '.join(f"{k}: '{a}' -> '{b}'" for k, (a, b) in changed.items()),
        )


def update_lora(
    animal_id: str,
    model_family: str,
    lora_path: Optional[str],
    sdxl_checkpoint: str | None = None,
    sdxl_render_style: str | None = None,
    master_reference_image: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Record a freshly-trained LoRA on the animal bible, family-suffixed.

    The renderer rejects a flux LoRA on the sdxl leg via the path substring
    ``lora-weights-<family>`` — this writer keeps the two legs in separate
    conditioning keys (``flux_lora_path`` / ``sdxl_lora_path``) so both twins can
    coexist and FLUX stays the primary story LoRA when both exist.
    """
    pkg = load(animal_id) or default_package(animal_id)
    cond = pkg.setdefault('conditioning', {})
    mf = (model_family or cond.get('model_family') or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl'):
        mf = 'flux'
    cond['model_family'] = mf
    path_ok = lora_path if lora_path and os.path.isfile(lora_path) else None

    if mf == 'sdxl':
        cond['sdxl_lora_path'] = path_ok
        try:
            from zyg_workflows import comfy_generation_service as _cgs_lora

            cond['sdxl_train_repo'] = _cgs_lora._SDXL_TRAIN_REPO_ID
            # ISOLATED per-animal STYLE profile (arcane_restyle / Option 3). A
            # styled animal's SDXL LoRA was trained on tiles restyled through a
            # REALISTIC base (profile.render_checkpoint) + a style LoRA, so it must
            # RENDER on that realistic base with the style baked into the LoRA —
            # NOT on the global 3D-toon animated checkpoint, and it must NOT carry
            # the animated marker (the marker re-selects the toon base downstream).
            # This wins over any animated checkpoint the trainer passes in. Absent
            # restyle -> unchanged behaviour.
            _restyle = str(((pkg.get('style_profile') or {}).get('restyle')) or '').strip()
            _styled_rc = ''
            if _restyle:
                try:
                    _spp = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        'data',
                        'runtime',
                        'character_style_profiles.json',
                    )
                    with open(_spp, encoding='utf-8') as _spf:
                        _styled_rc = str(
                            (((json.load(_spf).get('profiles') or {}).get(_restyle)) or {}).get('render_checkpoint')
                            or ''
                        ).strip()
                except Exception:
                    _styled_rc = ''
            if _restyle and _styled_rc:
                # styled LoRA renders on its realistic base; ignore any animated
                # checkpoint the trainer passed in, and drop the toon marker so the
                # arcane (realistic-animated) leg keeps its realism passes.
                cond['sdxl_checkpoint'] = _styled_rc
                cond.pop('sdxl_render_style', None)
            else:
                _animated_on = os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no')
                ckpt = (sdxl_checkpoint or cond.get('sdxl_checkpoint') or '').strip()
                # SDXL is the ANIMATED path (FLUX stays photoreal). Default to the
                # 3D-toon checkpoint, AND overwrite a stale photoreal base (a
                # re-trained twin otherwise keeps its old sd_xl_base/Juggernaut
                # value while pointing at an animated LoRA).
                _photoreal_bases = {
                    (_cgs_lora._SDXL_ALIGNED_CKPT or '').strip(),
                    (_cgs_lora._SDXL_FALLBACK_CKPT or '').strip(),
                }
                if _animated_on and (not ckpt or (not sdxl_checkpoint and ckpt in _photoreal_bases)):
                    ckpt = _cgs_lora._SDXL_ANIMATED_CKPT
                elif not ckpt:
                    ckpt = _cgs_lora._SDXL_ALIGNED_CKPT
                cond['sdxl_checkpoint'] = ckpt
                # Mark the SDXL leg as animated (bible render_style stays
                # photorealistic for the FLUX primary). An explicit
                # sdxl_render_style arg overrides.
                cond['sdxl_render_style'] = sdxl_render_style or 'animated'
        except Exception:
            # Even without comfy_generation_service present, honour explicit args.
            if sdxl_checkpoint:
                cond['sdxl_checkpoint'] = sdxl_checkpoint
            if sdxl_render_style is not None:
                cond['sdxl_render_style'] = sdxl_render_style
        # Keep FLUX as primary story LoRA when both exist.
        if not cond.get('flux_lora_path'):
            cond['lora_path'] = path_ok
    else:
        cond['flux_lora_path'] = path_ok
        cond['lora_path'] = path_ok
        if sdxl_checkpoint:
            cond['sdxl_checkpoint'] = sdxl_checkpoint
        if sdxl_render_style is not None:
            cond['sdxl_render_style'] = sdxl_render_style

    if master_reference_image and os.path.isfile(master_reference_image):
        cond['master_reference_image'] = master_reference_image

    save(pkg)
    if log_fn:
        log_fn(f'Animal bible: {mf} lora_path -> {path_ok or "(none)"}')


def record_scene_shot(
    animal_id: str,
    scene_id: str,
    image_path: str,
    prompt: str = '',
    seed: int | None = None,
    drift_score: float | None = None,
) -> None:
    pkg = load(animal_id)
    if not pkg:
        return
    history = pkg.setdefault('scene_history', [])
    history.append(
        {
            'ts': _utc_now(),
            'scene_id': scene_id,
            'image_path': image_path,
            'prompt_snippet': (prompt or '')[:200],
            'seed': seed,
            'drift_score': drift_score,
        }
    )
    pkg['scene_history'] = history[-200:]
    stats = pkg.setdefault('generation_stats', {})
    stats['total_stills'] = int(stats.get('total_stills', 0)) + 1
    save(pkg)
