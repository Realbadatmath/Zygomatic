# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bible persistence: migrate, load, save, build and update a package."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional
import logging as _zyg_logging

from zyg_workflows import paths

from .smile import (
    _DATASET_ROOT,
    _SCHEMA_VERSION,
    bible_path,
    face_detail_wildcard_for_params,
)
from .references import (
    _env_on,
    _find_lora_path,
    _pick_reference_images,
    _utc_now,
    default_package,
)
from .trait_tables import (
    _age_range_from_age,
)
from .names import (
    _auto_character_voice,
    resolve_character_display_name,
)
from .auto_defaults import (
    apply_auto_defaults,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_bible_service')


def migrate_package(package: dict[str, Any] | None) -> dict[str, Any] | None:
    """In-place schema upgrades for older bibles."""
    if not package:
        return package
    package.setdefault('default_presentation', {})
    package.setdefault('accessory_decisions', {})
    pres = package['default_presentation']
    style = package.setdefault('style_profile', {})
    for key in ('default_clothing', 'default_expression', 'accessories', 'posture'):
        if not pres.get(key) and style.get(key):
            pres[key] = style[key]
        if pres.get(key) and not style.get(key):
            style[key] = pres[key]
    package['schema_version'] = _SCHEMA_VERSION
    return package


def load(char_id: str) -> Optional[dict[str, Any]]:
    path = bible_path(char_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if data.get('character_id') != char_id:
            data['character_id'] = char_id
        return migrate_package(data)
    except Exception:
        return None


def _enforce_age_invariant(package: dict[str, Any]) -> None:
    """age_range MUST agree with age (2026-07-31).

    ``c3345deb5bde`` shipped with ``identity.age = 16`` and
    ``identity.age_range = 'child'`` — internally impossible: this module's own
    ``_age_range_from_age(16)`` says 'young adult', and the only consistent
    writer (build_from_character_generate) sets both from the same params dict.
    Downstream consumers (bp_storyteller list-chars, char_state_service,
    is_minor_identity) read whichever of the two suits them, so a contradiction
    means the same character is a child on one code path and an adult on
    another. Recompute from ``age`` (the numeric field is authoritative) and log
    loudly rather than silently persisting the contradiction.

    Only runs when ``age`` parses as an int — a bible with ``age: null`` and a
    hand-set ``age_range`` keeps its age_range (clobbering it with the
    'adult' default of _age_range_from_age would DELETE a minor marker).
    ``ZYG_BIBLE_AGE_INVARIANT=0`` disables.
    """
    if not _env_on('ZYG_BIBLE_AGE_INVARIANT'):
        return
    try:
        ident = package.get('identity')
        if not isinstance(ident, dict):
            return
        try:
            a = int(ident.get('age'))
        except (TypeError, ValueError):
            return
        want = _age_range_from_age(a)
        have = str(ident.get('age_range') or '').strip()
        if have.lower() == want:
            return
        cid = package.get('character_id', '?')
        msg = (
            f'[character_bible] AGE INVARIANT VIOLATION char={cid}: '
            f'identity.age={a} implies age_range={want!r} but bible holds '
            f'{have!r} — rewriting age_range to {want!r}. One of the two is '
            f'wrong at the SOURCE; a minor/adult mismatch here decides which '
            f'safety negatives fire.'
        )
        _logged = False
        try:
            import logging as _logging

            # channel kept from the pre-split module
            _lg = _logging.getLogger('zyg_workflows.character_bible_service')
            _lg.error(msg)
            # logging's lastResort handler already prints to stderr when the
            # process configured no handlers — don't double-log there.
            _logged = bool(_lg.handlers or _logging.getLogger().handlers)
        except Exception:
            _logged = False
        if not _logged:
            try:
                _zyg_log.warning(msg)
            except Exception as _exc:
                _zyg_log.debug('stderr echo of the age correction skipped: %s', _exc)
        ident['age_range'] = want
        # Breadcrumb so the corrected record is traceable after the fact.
        package.setdefault('integrity_notes', []).append(
            {
                'ts': _utc_now(),
                'check': 'age_range_vs_age',
                'was': have,
                'now': want,
                'age': a,
            }
        )
        notes = package.get('integrity_notes')
        if isinstance(notes, list) and len(notes) > 20:
            package['integrity_notes'] = notes[-20:]
    except Exception as _exc:
        # An invariant check must never block a bible save.
        _zyg_log.debug('integrity-note bookkeeping skipped: %s: %s', type(_exc).__name__, _exc)


def save(package: dict[str, Any]) -> str:
    char_id = package.get('character_id', '')
    if not char_id:
        raise ValueError('character_id required')
    _enforce_age_invariant(package)
    package['updated_at'] = _utc_now()
    os.makedirs(os.path.dirname(bible_path(char_id)), exist_ok=True)
    path = bible_path(char_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(package, f, indent=2)
    return path


def build_from_character_generate(
    char_id: str,
    params: dict,
    info: dict,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create or refresh bible after Blender / FLUX character dataset generation.

    *params* may contain any subset of UI fields with empty / 'auto' / None for
    unset values; apply_auto_defaults() fills the rest so the bible always has
    a fully-resolved descriptor set.
    """

    def _log(m: str) -> None:
        if log_fn:
            log_fn(m)

    # Auto-fill every descriptor *before* writing to the bible.
    params = apply_auto_defaults(params, seed_key=char_id)
    params['name'] = resolve_character_display_name(
        params.get('name'),
        params.get('gender', 'female'),
        params.get('eye_color'),
    )

    existing = load(char_id) or default_package(char_id, info.get('trigger_token', ''))
    existing['schema_version'] = _SCHEMA_VERSION
    existing.setdefault('identity', {})
    existing.setdefault('style_profile', {})
    existing.setdefault('default_presentation', {})
    existing.setdefault('accessory_decisions', {})
    existing.setdefault('conditioning', {})
    existing.setdefault('voice_profile', {})

    dataset_dir = info.get('dataset_dir') or os.path.join(_DATASET_ROOT, char_id)
    refs = _pick_reference_images(dataset_dir)
    _mf_early = (params.get('model_family') or info.get('model_family') or '').strip().lower()
    lora_path = _find_lora_path(
        char_id,
        _mf_early if _mf_early in ('flux', 'sdxl', 'qwen', 'klein') else None,
    )

    existing['trigger_token'] = info.get('trigger_token') or existing.get('trigger_token', '')
    existing['display_name'] = params.get('name') or existing.get('display_name', '')
    # Delivered-attribute sync must survive re-saves (2026-07-17). Once
    # sync_delivered_attributes() records what the shipped anchor actually
    # looks like, re-writing the ORIGINAL spec params over it (this upsert
    # runs on every bible save during identity QC) silently reverted the
    # bible to colours the LoRA does not render — run ac97acfb845b ended with
    # eye_color 'hazel' in the bible for a brown-eyed anchor. Delivered
    # reality wins over spec for the synced colour keys.
    _pre_ident = dict(existing.get('identity') or {})
    existing['identity'].update(
        {
            'gender': params['gender'],
            'age': params['age'],
            'age_range': params['age_range'],
            'height_m': params['height'],
            'skin_tone': params['skin_tone'],
            'hair_color': params['hair_color'],
            'hair_style': params['hair_style'],
            'hair_length': params['hair_length'],
            'hair_texture': params['hair_texture'],
            'eye_color': params['eye_color'],
            'eye_shape': params['eye_shape'],
            'eyebrow_style': params['eyebrow_style'],
            'face_shape': params['face_shape'],
            'nose_shape': params['nose_shape'],
            'lip_shape': params['lip_shape'],
            'body_build': params['body_build'],
            'muscle_mass': params['muscle_mass'],
            'facial_hair': params['facial_hair'],
            'distinctive_marks': params['distinctive_marks'],
            'ethnic_heritage': params.get('ethnic_heritage', ''),
        }
    )
    if _pre_ident.get('attributes_synced_from_anchor'):
        for _sync_key in ('eye_color', 'hair_color', 'skin_tone'):
            _dv = (_pre_ident.get(_sync_key) or '').strip()
            if _dv:
                existing['identity'][_sync_key] = _dv
    pres_block = {
        'default_clothing': params['default_clothing'],
        'default_expression': params['default_expression'],
        'accessories': params['accessories'],
        'posture': params['posture'],
    }
    existing['default_presentation'].update(pres_block)
    if isinstance(params.get('accessory_decisions'), dict):
        existing['accessory_decisions'] = params['accessory_decisions']
    existing['style_profile'].update(
        {
            'render_style': params['render_style'],
            'genre': params['genre'],
            'indoor_stage': True,
            'lighting_profile': params['lighting_profile'],
            'color_palette': params['color_palette'],
            'camera_language': params['camera_language'],
            **pres_block,
        }
    )
    _brief_prose = (params.get('character_brief_prose') or '').strip()
    if _brief_prose:
        existing['style_profile']['character_brief_prose'] = _brief_prose
    vp_in = params.get('voice_profile') or {}
    if isinstance(vp_in, dict):
        for vk in ('narrator_hint', 'character_voice'):
            vv = (vp_in.get(vk) or '').strip()
            if vv:
                existing['voice_profile'][vk] = vv
    cond = existing.setdefault('conditioning', {})
    _mf = (params.get('model_family') or info.get('model_family') or '').strip().lower()
    if _mf in ('flux', 'sdxl'):
        cond['model_family'] = _mf
    cond['ipadapter_reference_images'] = refs
    cond['master_reference_image'] = refs[0] if refs else cond.get('master_reference_image')
    cond['quality_suffix'] = params['quality_suffix']
    cond['negative_prompt'] = params['negative_prompt']
    cond.setdefault('lora_scale', 0.85)
    cond.setdefault('ipadapter_scale', 0.65)
    cond.setdefault('face_detail_pass', True)
    # 0.30 for flux (0.45 re-synthesized half the face with FLUX's smooth-skin
    # prior — 2026-07-09 audit); SDXL keeps 0.45, its detailer repairs small
    # mangled faces and has no waxy prior.
    cond.setdefault('face_detail_strength', 0.45 if _mf == 'sdxl' else 0.30)
    # 2026-07-26: isolated per-character STYLE profile (Option 3). If the START
    # payload carried style_profile_restyle=<name>, persist it so the training
    # hook restyles this character's tiles into that style (e.g. Arcane), and pin
    # the profile's render checkpoint so the styled LoRA renders on-model. Absent
    # → no effect (the public zpub flow never sets it). See arcane_restyle.py.
    _restyle_name = (params.get('style_profile_restyle') or '').strip()
    if _restyle_name:
        existing.setdefault('style_profile', {})['restyle'] = _restyle_name
        try:
            _spp = str(paths.DATA_DIR / 'runtime' / 'character_style_profiles.json')
            with open(_spp, encoding='utf-8') as _spf:
                _prof = (json.load(_spf).get('profiles') or {}).get(_restyle_name) or {}
            _rc = _prof.get('render_checkpoint')
            if _rc:
                cond['sdxl_checkpoint'] = _rc
        except Exception as _exc:
            _zyg_log.warning('style profile unreadable, render checkpoint left as it was: %s', _exc)
    if params.get('smile_requested') or params.get('smile_locked'):
        cond['smile_requested'] = True
        cond['smile_locked'] = True
        cond['face_detail_wildcard'] = face_detail_wildcard_for_params(params)
    cond.setdefault('instantid_enabled', True)
    cond.setdefault('instantid_weight', 0.85)
    _render_mode = str(info.get('render_mode') or params.get('render_mode') or '').strip().lower()
    _manifest_src = str((info.get('manifest') or {}).get('source') or info.get('source') or '').lower()
    if _render_mode == 'blender' or 'blender' in _manifest_src:
        cond['instantid_enabled'] = False

    # ── Honour explicit user overrides from the Advanced-Identity UI ────────
    # (the apply_auto_defaults() pass intentionally leaves conditioning
    # fields alone — they are merged in here so the bible reflects exactly
    # what the user toggled.)
    def _coerce_bool(v: Any) -> bool | None:
        """Robust bool cast — strings 'false'/'0'/'off'/'no' → False."""
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ('true', '1', 'on', 'yes', 'y'):
                return True
            if s in ('false', '0', 'off', 'no', 'n'):
                return False
        return None

    def _coerce_float(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for key, caster in (
        ('instantid_enabled', _coerce_bool),
        ('face_detail_pass', _coerce_bool),
        ('face_detail_strength', _coerce_float),
        ('instantid_weight', _coerce_float),
        ('lora_scale', _coerce_float),
        ('ipadapter_scale', _coerce_float),
    ):
        if key in params and params[key] not in (None, '', 'auto'):
            casted = caster(params[key])
            if casted is not None:
                cond[key] = casted
    if lora_path and os.path.isfile(lora_path):
        # 2026-07-31: family-aware LoRA write. This used to drop whatever
        # _find_lora_path() resolved into the FAMILY-AGNOSTIC `lora_path` key,
        # which is a real cross-family clobber for a twin character (Abel has
        # both flux_lora_path and sdxl_lora_path): an SDXL re-generation /
        # identity-QC upsert overwrote `lora_path` with the SDXL checkpoint,
        # breaking the invariant update_lora() maintains deliberately ("keep
        # FLUX as primary story LoRA when both exist"). Consumers that fall
        # back to the agnostic key for a FLUX render — comfy_generation_service
        # ~2294 `cond.get('flux_lora_path') or cond.get('lora_path')`,
        # char_state_service ~812 (same order), _resolve_unet ~1069 which reads
        # it as proof a FLUX dev UNet is wanted — would then load an SDXL
        # adapter into a FLUX pipeline. Mirror update_lora() instead: always
        # record the family-specific key, and only touch `lora_path` when it
        # does not contradict a live FLUX adapter.
        # ZYG_BIBLE_LORA_FAMILY_SAFE=0 restores the old unconditional write.
        _lora_fam = None
        if _env_on('ZYG_BIBLE_LORA_FAMILY_SAFE'):
            try:
                from zyg_workflows import character_lora_family as _clf_bib

                _lora_fam = _clf_bib.infer_lora_family_from_path(lora_path)
            except Exception:
                _lora_fam = None
            if _lora_fam is None and _mf in ('flux', 'sdxl', 'qwen', 'klein'):
                _lora_fam = _mf
        if _lora_fam in ('qwen', 'klein'):
            # Companion adapter only (2026-08-09; klein joined 2026-08-25): the
            # qwen/klein-primary cutover is a later, deliberate step — never let
            # either path reach the agnostic `lora_path` key (the else-branch
            # below would clobber the FLUX primary for every consumer that
            # falls back to it).
            cond[f'{_lora_fam}_lora_path'] = lora_path
        elif _lora_fam == 'sdxl':
            cond['sdxl_lora_path'] = lora_path
            _flux_lp = cond.get('flux_lora_path') or ''
            if not (_flux_lp and os.path.isfile(_flux_lp)):
                cond['lora_path'] = lora_path
            else:
                _log('Bible: kept FLUX lora_path as primary (SDXL adapter recorded as sdxl_lora_path)')
        elif _lora_fam == 'flux':
            cond['flux_lora_path'] = lora_path
            cond['lora_path'] = lora_path
        else:
            cond['lora_path'] = lora_path
    existing.setdefault('dataset_dir', dataset_dir)
    existing['source_manifest'] = info.get('manifest', {}).get('source', info.get('source', ''))

    # Voice auto-assignment (2026-07-18): match the rolled identity so the
    # character ships turnkey; an explicit/authored voice is never overwritten.
    _vp = existing.setdefault('voice_profile', {})
    if not (_vp.get('character_voice') or '').strip():
        _av = _auto_character_voice(params.get('gender'), params.get('age'), char_id)
        if _av and _av.get('voice'):
            _vp['character_voice'] = _av['voice']
            _vp['character_voice_profile'] = _av['profile_id']
            _vp['auto_assigned'] = True
            _log(f'Voice auto-assigned: {_av.get("label")} ({_av["voice"]})')

    path = save(existing)
    _log(
        f'Character bible saved → {path} ({len(refs)} reference image(s), {len(existing["identity"])} identity fields)'
    )
    return existing


def sync_delivered_attributes(
    char_id: str,
    observed: dict[str, str],
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Write DELIVERED anchor attributes into the bible when they differ from
    the spec (2026-07-16). Scene prompts are built from the bible — a bible
    that says 'green eyes' while the LoRA renders brown makes every future
    scene fight the LoRA. Once an anchor ships, delivered reality wins.
    """
    allowed = ('eye_color', 'hair_color', 'skin_tone')
    pkg = load(char_id)
    if not pkg:
        return
    ident = pkg.setdefault('identity', {})
    changed: dict[str, tuple] = {}
    for k, v in (observed or {}).items():
        v = (v or '').strip().lower()
        # 'other'/'unclear' are judge enum buckets, not colours — never write
        # them into the bible as literal attribute values.
        if k in allowed and v and v not in ('unclear', 'other') and (ident.get(k) or '').strip().lower() != v:
            changed[k] = (ident.get(k), v)
            ident[k] = v
    if not changed:
        return
    ident['attributes_synced_from_anchor'] = True
    save(pkg)
    if log_fn:
        log_fn(
            'Bible synced to delivered anchor attributes: '
            + ', '.join(f"{k}: '{a}' → '{b}'" for k, (a, b) in changed.items()),
        )


def update_lora(
    char_id: str,
    lora_path: Optional[str],
    log_fn: Callable[[str], None] | None = None,
    model_family: str | None = None,
    sdxl_checkpoint: str | None = None,
) -> None:
    pkg = load(char_id) or default_package(char_id)
    cond = pkg.setdefault('conditioning', {})
    mf = (model_family or cond.get('model_family') or 'flux').strip().lower()
    if mf not in ('flux', 'sdxl', 'qwen', 'klein'):
        mf = 'flux'
    # 2026-08-09: a qwen twin is a COMPANION adapter for now — the qwen-primary
    # cutover is a later, deliberate step, so the qwen branch never touches
    # cond['model_family'] or cond['lora_path'] (FLUX/SDXL keep primary).
    # 2026-08-25: klein (FLUX.2 [klein] 4B) joins on identical terms.
    if mf not in ('qwen', 'klein'):
        cond['model_family'] = mf
    path_ok = lora_path if lora_path and os.path.isfile(lora_path) else None
    if mf in ('qwen', 'klein'):
        cond[f'{mf}_lora_path'] = path_ok
    elif mf == 'sdxl':
        cond['sdxl_lora_path'] = path_ok
        try:
            from zyg_workflows import comfy_generation_service as _cgs_lora

            cond['sdxl_train_repo'] = _cgs_lora._SDXL_TRAIN_REPO_ID
            # 2026-07-26: ISOLATED per-character STYLE profile (arcane_restyle /
            # Option 3). A styled character's SDXL LoRA was trained on tiles
            # restyled through a REALISTIC base (profile.render_checkpoint, e.g.
            # Juggernaut) + a style LoRA, so it must RENDER on that realistic base
            # with the style baked into the LoRA — NOT on the global 3D-toon
            # animated checkpoint, and it must NOT carry the animated marker (the
            # marker forces style_profile.render_style='animated' downstream, which
            # re-selects the toon base at render AND disables the realism /
            # FaceDetailer pass — comfy_generation_service ~1424/2145,
            # pipeline_storyteller ~103). This wins over any animated checkpoint
            # the trainer passes in. Absent restyle → unchanged behaviour (the
            # public zero_public flow never sets style_profile.restyle).
            _restyle = str(((pkg.get('style_profile') or {}).get('restyle')) or '').strip()
            _styled_rc = ''
            if _restyle:
                try:
                    _spp = str(paths.DATA_DIR / 'runtime' / 'character_style_profiles.json')
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
                # arcane (realistic-animated) leg keeps its realism/QC passes.
                cond['sdxl_checkpoint'] = _styled_rc
                cond.pop('sdxl_render_style', None)
            else:
                _animated_on = os.environ.get('ZYG_SDXL_ANIMATED', '1').strip().lower() not in ('0', 'false', 'no')
                ckpt = (sdxl_checkpoint or cond.get('sdxl_checkpoint') or '').strip()
                # 2026-07-25: SDXL is the ANIMATED path — the LoRA trains + renders
                # on the 3D-toon checkpoint. Default to it, AND overwrite a stale
                # photoreal base (a re-trained twin keeps its old sd_xl_base/
                # Juggernaut value otherwise — the exact bug that shipped Runa's
                # animated LoRA pointing at sd_xl_base_1.0).
                _photoreal_bases = {
                    (_cgs_lora._SDXL_ALIGNED_CKPT or '').strip(),
                    (_cgs_lora._SDXL_FALLBACK_CKPT or '').strip(),
                }
                if _animated_on and (not ckpt or (not sdxl_checkpoint and ckpt in _photoreal_bases)):
                    ckpt = _cgs_lora._SDXL_ANIMATED_CKPT
                elif not ckpt:
                    ckpt = _cgs_lora._SDXL_ALIGNED_CKPT
                cond['sdxl_checkpoint'] = ckpt
                # Record that this SDXL twin is the animated style (bible render_style
                # stays photoreal for the FLUX primary; this marks the SDXL leg).
                cond['sdxl_render_style'] = 'animated'
        except Exception as _exc:
            _zyg_log.warning('sdxl checkpoint selection failed, leaving the existing value: %s', _exc)
        # Keep FLUX as primary story LoRA when both exist.
        if not cond.get('flux_lora_path'):
            cond['lora_path'] = path_ok
    else:
        cond['flux_lora_path'] = path_ok
        cond['lora_path'] = path_ok
    save(pkg)
    if log_fn:
        log_fn(f'Character bible: {mf} lora_path → {path_ok or "(none)"}')


def record_scene_shot(
    char_id: str,
    scene_id: str,
    image_path: str,
    prompt: str = '',
    seed: int | None = None,
    drift_score: float | None = None,
) -> None:
    pkg = load(char_id)
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


def _presentation_from_package(package: dict[str, Any] | None) -> dict[str, str]:
    """Resolve default presentation — prefers ``default_presentation``, falls back to style_profile."""
    if not package:
        return {}
    pres = package.get('default_presentation') or {}
    style = package.get('style_profile') or {}
    out: dict[str, str] = {}
    for key in ('default_clothing', 'default_expression', 'accessories', 'posture'):
        val = (pres.get(key) or style.get(key) or '').strip()
        if val:
            out[key] = val
    return out
