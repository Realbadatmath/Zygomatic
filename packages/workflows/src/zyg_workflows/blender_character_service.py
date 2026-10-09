# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
blender_character_service.py
============================
Wrapper around the Blender headless character generation script.

Usage::

    from zyg_workflows.blender_character_service import BlenderCharacterService
    svc  = BlenderCharacterService()
    info = svc.generate(
        char_id='abc123',
        params={
            'hair_color': 'auburn',
            'eye_color':  'blue',
            'skin_tone':  'medium',
            'gender':     'female',
            'height':     '1.70',
            'style':      'animated',     # 'animated' | 'photorealistic'
        }
    )
    # info = {'char_id': ..., 'images': [...paths...], 'trigger_token': 'ZYG_CHAR_abc123',
    #         'style': 'animated', 'dataset_dir': ..., 'manifest': {...}}

Falls back to FLUX-text-to-image reference renders if Blender is unavailable or fails.
The FLUX fallback generates 20 diverse-pose images using the character description as
the text prompt, ensuring LoRA training still receives sufficient variety.
"""

import os
import json
import shutil
import logging
import subprocess
from typing import Optional

from zyg_workflows import paths

logger = logging.getLogger(__name__)

# ── Pipeline DSL + caveman adapter (env-gated, soft-fail) ───────────────────
try:
    from zyg_workflows import pipeline_dsl_adapter as _dsl
except ImportError:
    _dsl = None

try:
    from zyg_workflows import _comfy_client as _comfy
except ImportError:
    _comfy = None

# ── Paths ───────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_BLENDER_BIN = str(paths.BLENDER_BIN)
_BLENDER_SCRIPT = os.path.join(_HERE, 'blender_scripts', 'generate_character.py')
_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')


# ── FLUX model reuse: defer to main app's global cache when available ────────────
# This prevents a second 36GB FLUX load when character gen runs inside the server.
def _get_or_load_flux(flux_path: str):
    """
    Return the global _FLUX_DEV_PIPELINE_CACHE if already loaded in the main server
    process, otherwise create and return a fresh pipeline.  The caller is responsible
    for teardown (set to None + gc + empty_cache) once it has finished using it.
    """
    import sys

    main = sys.modules.get('zyg_dashboard.crewai_web_gui') or sys.modules.get('__main__')
    if main and hasattr(main, '_FLUX_DEV_PIPELINE_CACHE') and main._FLUX_DEV_PIPELINE_CACHE is not None:
        logger.info('[BlenderCharSvc] Reusing existing FLUX pipeline from global cache')
        return main._FLUX_DEV_PIPELINE_CACHE, False  # (pipe, we_own_it)
    from diffusers import FluxPipeline as _FP
    import torch

    logger.info('[BlenderCharSvc] Loading FLUX for character reference generation…')
    pipe = _FP.from_pretrained(flux_path, torch_dtype=torch.bfloat16).to('cuda')
    return pipe, True  # (pipe, we_own_it)


def _release_flux(pipe, we_own_it: bool):
    """Only tear down VRAM if we were the ones who loaded the pipeline."""
    if not we_own_it:
        return
    try:
        del pipe
        import gc
        import torch

        gc.collect()
        torch.cuda.empty_cache()
        logger.info('[BlenderCharSvc] FLUX unloaded — VRAM freed')
    except Exception as exc:
        logger.warning(f'[BlenderCharSvc] VRAM teardown warning: {exc}')


# Caption templates for each render slot — used as LoRA training captions.
# Richer captions = better prompt adherence and identity consistency.
# Fields: trigger, gender, angle, skin_tone, hair_color, eye_color, style,
#         pose, lighting, camera_framing, expression
_FULL_CAPTION_TPL = (
    '{trigger} {gender} character, full body, {angle} view, '
    '{skin_tone} skin, {hair_color} hair, {eye_color} eyes, '
    '{pose}, {lighting}, {camera_framing}, {expression}, {style} style'
)
_FACE_CAPTION_TPL = (
    '{trigger} {gender} character, face portrait, {angle} view, '
    '{skin_tone} skin, {hair_color} hair, {eye_color} eyes, '
    '{lighting}, close-up portrait framing, {expression}, {style} style'
)

# Cycling metadata arrays for varied training captions
_CAPTION_POSES = [
    'standing relaxed',
    'standing arms crossed',
    'standing arms at sides',
    'walking pose',
    'sitting pose',
    'standing three-quarter turn',
]
_CAPTION_LIGHTINGS = [
    'warm daylight lighting',
    'soft studio lighting',
    'cool neutral lighting',
    'bright high-key lighting',
    'warm golden hour light',
    'clean indoor lighting',
]
_CAPTION_FRAMINGS = [
    'full body shot',
    'medium shot waist up',
    'wide establishing shot',
    'full body front view',
    'medium shot',
    'full body side view',
]
_CAPTION_EXPRESSIONS = [
    'neutral expression',
    'slight smile',
    'calm expression',
    'thoughtful expression',
    'confident expression',
    'relaxed expression',
]

# ── Angle descriptions for captions ─────────────────────────────────────────────
_FULL_ANGLE_DESCS = [
    'front',
    '22.5deg',
    '45deg',
    '67.5deg',
    'right side',
    '112.5deg',
    '135deg',
    '157.5deg',
    'back',
    '202.5deg',
    '225deg',
    '247.5deg',
    'left side',
    '292.5deg',
    '315deg',
    '337.5deg',
]
_FACE_ANGLE_DESCS = ['front face', 'three-quarter left face', 'right side face', 'back of head']


def caption_style_description(style: str) -> str:
    """LoRA caption style phrase — must match preview prompts and Blender render mode."""
    s = (style or '').strip().lower()
    if s == 'animated':
        return 'toon animated 3D render'
    if s == 'photorealistic':
        # No 'cinematic lighting' / '8k portrait' — waxy-attractor tokens on
        # FLUX; keep in sync with contact_sheet_pipeline.caption_style_description.
        return 'photorealistic, film photography, natural skin texture, visible pores, unretouched, fine film grain'
    return 'stylized realistic 3D render'


class BlenderCharacterService:
    """Generate character reference images for LoRA training."""

    def __init__(self):
        self._blender_ok: Optional[bool] = None  # None = not yet tested

    # ── Public API ────────────────────────────────────────────────────────────────
    def generate(self, char_id: str, params: dict) -> dict:
        """
        Generate ~20 character reference images.

        Returns a dict with keys:
            char_id, images, trigger_token, style, dataset_dir, manifest
        """
        os.makedirs(_DATASET_ROOT, exist_ok=True)
        dataset_dir = os.path.join(_DATASET_ROOT, char_id)
        os.makedirs(dataset_dir, exist_ok=True)

        trigger = f'ZYG_CHAR_{char_id[:6].upper()}'
        style = (params.get('style') or 'animated').strip().lower()

        _use_flux_dataset = os.environ.get(
            'ZYG_PHOTOREAL_FLUX_DATASET',
            '0',
        ).strip().lower() in ('1', 'true', 'yes', 'on')
        if style == 'photorealistic' and _use_flux_dataset:
            logger.info(
                '[BlenderCharSvc] Photoreal FLUX dataset mode '
                '(set ZYG_PHOTOREAL_FLUX_DATASET=0 to use Blender Cycles instead)',
            )
            images, manifest = self._flux_fallback(params, dataset_dir, trigger)
        else:
            images, manifest = self._try_blender(params, dataset_dir)
            if not images:
                logger.warning('[BlenderCharSvc] Blender failed — falling back to FLUX text-to-image')
                images, manifest = self._flux_fallback(params, dataset_dir, trigger)

        if not images:
            raise RuntimeError(f'[BlenderCharSvc] Both Blender and FLUX fallback failed for char {char_id}')

        # Write captions (.txt files beside each image)
        self._write_captions(images, params, trigger)

        # ── DSL: persist a Scene snapshot for this character (env-gated) ──
        if _dsl is not None and _dsl.is_enabled('character'):
            try:
                _char_scene = _dsl.build_scene_from_metadata(
                    {
                        'subject': (
                            f'{params.get("gender", "person")} character with '
                            f'{params.get("hair_color", "brown")} hair, '
                            f'{params.get("eye_color", "brown")} eyes, '
                            f'{params.get("skin_tone", "medium")} skin'
                        ),
                        'setting': f'reference dataset for {style} style character',
                        'lighting_style': 'soft_studio',
                        'aspect_ratio': '1:1',
                        'composition': 'character reference, multi-angle',
                        'tags': [
                            'character',
                            style,
                            params.get('gender', ''),
                            params.get('genre', '') or 'general',
                        ],
                    },
                    pipeline='character',
                    scene_id=f'char_{char_id[:8]}',
                )
                _dsl_path = _dsl.persist_scene(_char_scene, dataset_dir, filename=f'character_{char_id[:8]}.scene.yaml')
                if _dsl_path:
                    logger.info(f'[BlenderCharSvc] DSL: persisted scene → {_dsl_path}')
            except Exception as _dsl_exc:
                logger.warning(f'[BlenderCharSvc] DSL hook failed (non-fatal): {_dsl_exc}')

        info = {
            'char_id': char_id,
            'images': images,
            'trigger_token': trigger,
            'style': style,
            'dataset_dir': dataset_dir,
            'manifest': manifest or {},
        }
        try:
            from zyg_workflows import character_bible_service as _cbs

            _cbs.build_from_character_generate(
                char_id,
                params,
                info,
                log_fn=lambda m: logger.info(f'[BlenderCharSvc] {m}'),
            )
        except Exception as _cbs_exc:
            logger.warning(f'[BlenderCharSvc] character bible build failed: {_cbs_exc}')
        return info

    # ── Blender path ─────────────────────────────────────────────────────────────
    def _try_blender(self, params: dict, output_dir: str):
        """Run Blender headlessly. Returns (images_list, manifest_dict) or ([], None)."""
        if not os.path.isfile(_BLENDER_BIN):
            logger.warning(f'[BlenderCharSvc] Blender binary not found at {_BLENDER_BIN}')
            return [], None
        if not os.path.isfile(_BLENDER_SCRIPT):
            logger.warning(f'[BlenderCharSvc] Blender script not found at {_BLENDER_SCRIPT}')
            return [], None

        cmd = [
            _BLENDER_BIN,
            '--background',
            '--python',
            _BLENDER_SCRIPT,
            '--',
            '--hair-color',
            str(params.get('hair_color', 'brown')),
            '--eye-color',
            str(params.get('eye_color', 'brown')),
            '--skin-tone',
            str(params.get('skin_tone', 'medium')),
            '--gender',
            str(params.get('gender', 'female')),
            '--height',
            str(params.get('height', '1.70')),
            '--style',
            str(params.get('style', 'animated')),
            '--output-dir',
            output_dir,
            '--resolution',
            '768',
            '--hair-style',
            str(params.get('hair_style', 'auto')),
            '--facial-hair',
            str(params.get('facial_hair', 'none')),
            '--muscle-mass',
            str(params.get('muscle_mass', '2')),
        ]
        logger.info(f'[BlenderCharSvc] Launching: {" ".join(cmd[:6])} … --output-dir {output_dir}')

        env = os.environ.copy()
        env['DISPLAY'] = ''  # suppress X11 errors in headless mode

        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                logger.error(f'[BlenderCharSvc] Blender exited {proc.returncode}:\n{proc.stderr[-2000:]}')
                return [], None
        except subprocess.TimeoutExpired:
            logger.error('[BlenderCharSvc] Blender timed out after 5 min')
            return [], None
        except Exception as exc:
            logger.error(f'[BlenderCharSvc] Blender subprocess error: {exc}')
            return [], None

        manifest_path = os.path.join(output_dir, 'manifest.json')
        if not os.path.isfile(manifest_path):
            logger.error('[BlenderCharSvc] Blender completed but no manifest.json found')
            return [], None

        with open(manifest_path) as mf:
            manifest = json.load(mf)

        # Preserve name, genre, facial_hair, muscle_mass from params (Blender script doesn't know about them)
        if params.get('name') or params.get('genre') or params.get('facial_hair') or params.get('muscle_mass'):
            if params.get('name'):
                manifest['name'] = params['name']
            if params.get('genre'):
                manifest['genre'] = params['genre']
            if params.get('facial_hair'):
                manifest['facial_hair'] = params['facial_hair']
            if params.get('muscle_mass') is not None:
                manifest['muscle_mass'] = params['muscle_mass']
            with open(manifest_path, 'w') as mf:
                json.dump(manifest, mf, indent=2)

        images = [p for p in manifest.get('images', []) if os.path.isfile(p)]
        if len(images) < 10:
            logger.warning(f'[BlenderCharSvc] Only {len(images)} images produced — likely partial failure')
            return [], None

        logger.info(f'[BlenderCharSvc] Blender rendered {len(images)} images ✓')
        return images, manifest

    # ── FLUX fallback ─────────────────────────────────────────────────────────────
    def _flux_fallback(self, params: dict, output_dir: str, trigger: str):
        """
        Generate character images using FLUX text-to-image as fallback.
        Produces 20 images with varied angle/pose prompts.
        """
        try:
            import torch  # noqa: F401  availability probe: the FLUX fallback needs torch present
            from diffusers import FluxPipeline as _FP  # noqa: F401  availability probe for the same fallback
        except ImportError:
            logger.error('[BlenderCharSvc] diffusers not available for FLUX fallback')
            return [], None

        gender = params.get('gender', 'person')
        hair = params.get('hair_color', 'brown')
        eyes = params.get('eye_color', 'brown')
        skin = params.get('skin_tone', 'medium')
        style = params.get('style', 'animated')
        genre = (params.get('genre') or 'general').lower()
        facial_hair = (params.get('facial_hair') or 'none').lower()
        muscle_mass = max(1, min(100, int(params.get('muscle_mass') or 20)))
        style_str = (
            'flat toon 3D render, cel shaded'
            if style == 'animated'
            else 'photorealistic, film photography, natural skin texture, visible pores, '
            'unretouched, fine film grain, cinematic lighting, 8k portrait'
        )

        def _muscle_desc(v):
            if v <= 20:
                return 'slender build'
            if v <= 40:
                return 'average build'
            if v <= 60:
                return 'athletic build'
            if v <= 80:
                return 'muscular build'
            return 'very muscular bodybuilder build'

        muscle_desc = _muscle_desc(muscle_mass)
        facial_hair_str = f', {facial_hair} facial hair' if facial_hair not in ('none', '') else ''

        _GENRE_SUFFIX = {
            'action': 'battle-ready outfit, armored details, intense expression, dynamic pose',
            'romance': 'elegant attire, soft warm lighting, gentle expression, flowing outfit',
            'religion': 'traditional robes, serene expression, sacred setting, graceful posture',
            'finance': 'sharp business suit, professional setting, confident posture, modern office',
            'medieval': 'medieval clothing, castle backdrop, era-appropriate attire, period-accurate details',
            'education': 'academic attire, bookish setting, thoughtful expression, scholarly appearance',
        }
        genre_suffix = _GENRE_SUFFIX.get(genre, '')

        angle_prompts = [
            'front view, full body',
            '3/4 left view, full body',
            '3/4 right view, full body',
            'side view left, full body',
            'side view right, full body',
            'back view, full body',
            'front view, medium shot',
            '3/4 left view, medium shot',
            '3/4 right view, medium shot',
            'back view, medium shot',
            'front face, close-up portrait',
            '3/4 left face, close-up portrait',
            '3/4 right face, close-up portrait',
            'side face left, close-up portrait',
            'front, sitting pose',
            '3/4 sitting pose',
            'front, walking pose',
            'front, arms crossed',
            'front, arms relaxed',
            '3/4, head tilted slightly',
        ]

        base_prompt = (
            f'{trigger} {gender}, {hair} hair, {eyes} eyes, {skin} skin tone,'
            f' {muscle_desc}{facial_hair_str},'
            f' white studio background, clean neutral background,'
            f' {style_str}, high quality character reference' + (f', {genre_suffix}' if genre_suffix else '')
        )

        if _comfy is not None and _comfy.is_enabled() and _comfy.server_reachable():
            images = self._flux_fallback_comfy(angle_prompts, base_prompt, output_dir)
            if images:
                manifest = {
                    'name': params.get('name', ''),
                    'style': style,
                    'gender': gender,
                    'hair_color': hair,
                    'eye_color': eyes,
                    'genre': genre,
                    'images': images,
                    'total': len(images),
                    'source': 'flux_fallback_comfy',
                }
                with open(os.path.join(output_dir, 'manifest.json'), 'w') as mf:
                    json.dump(manifest, mf, indent=2)
                return images, manifest
            logger.warning('[BlenderCharSvc] ComfyUI path returned no images — falling back to diffusers')

        flux_path = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
        if not os.path.isdir(flux_path):
            logger.error(f'[BlenderCharSvc] FLUX schnell model not found at {flux_path}')
            return [], None

        try:
            pipe, _we_own = _get_or_load_flux(flux_path)
        except Exception as exc:
            logger.error(f'[BlenderCharSvc] Failed to load FLUX: {exc}')
            return [], None

        images = []
        try:
            for i, angle in enumerate(angle_prompts):
                prompt = f'{base_prompt}, {angle}'
                try:
                    result = pipe(
                        prompt=prompt,
                        height=512,
                        width=512,
                        num_inference_steps=4,
                        guidance_scale=0.0,
                    ).images[0]
                    img_path = os.path.join(output_dir, f'flux_{i:02d}.png')
                    result.save(img_path)
                    images.append(img_path)
                except Exception as exc:
                    logger.warning(f'[BlenderCharSvc] FLUX slot {i} failed: {exc}')
        finally:
            _release_flux(pipe, _we_own)

        manifest = {
            'name': params.get('name', ''),
            'style': style,
            'gender': gender,
            'hair_color': hair,
            'eye_color': eyes,
            'genre': genre,
            'images': images,
            'total': len(images),
            'source': 'flux_fallback',
        }
        manifest_path = os.path.join(output_dir, 'manifest.json')
        with open(manifest_path, 'w') as mf:
            json.dump(manifest, mf, indent=2)

        return images, manifest

    # ── FLUX fallback via ComfyUI ────────────────────────────────────────────────
    def _flux_fallback_comfy(self, angle_prompts: list, base_prompt: str, output_dir: str) -> list:
        """Submit the flux_txt2img workflow once per angle. Schnell-class quality:
        25 steps, cfg 1.0 (matches workflow defaults). Returns the list of paths."""
        images: list = []
        try:
            workflow = _comfy.load_workflow('flux_txt2img')
        except _comfy.ComfyUIError as exc:
            logger.error(f'[BlenderCharSvc] ComfyUI workflow load failed: {exc}')
            return []

        for i, angle in enumerate(angle_prompts):
            prompt = f'{base_prompt}, {angle}'
            try:
                outputs = _comfy.submit(
                    workflow,
                    overrides={
                        '10': {'unet_name': 'flux1-schnell.safetensors'},
                        '20': {'text': prompt[:600]},
                        '30': {'width': 512, 'height': 512, 'batch_size': 1},
                        '31': {'seed': 100 + i, 'steps': 4, 'cfg': 1.0},
                    },
                )
                if not outputs:
                    continue
                dst = os.path.join(output_dir, f'flux_{i:02d}.png')
                shutil.copy2(outputs[0], dst)
                images.append(dst)
            except Exception as exc:
                logger.warning(f'[BlenderCharSvc] ComfyUI slot {i} failed: {exc}')

        return images

    # ── Captions ─────────────────────────────────────────────────────────────────
    def _write_captions(self, images: list, params: dict, trigger: str):
        """Write a .txt caption file alongside each image with rich metadata for LoRA training."""
        gender = params.get('gender', 'person')
        hair = params.get('hair_color', 'brown')
        eyes = params.get('eye_color', 'brown')
        skin = params.get('skin_tone', 'medium')
        style = params.get('style', 'animated')
        style_desc = caption_style_description(style)

        for i, img_path in enumerate(images):
            basename = os.path.basename(img_path)
            is_face = basename.startswith('face_') or basename.startswith('flux_1')
            if is_face:
                angle_desc = _FACE_ANGLE_DESCS[i % len(_FACE_ANGLE_DESCS)]
                tpl = _FACE_CAPTION_TPL
                caption = tpl.format(
                    trigger=trigger,
                    gender=gender,
                    angle=angle_desc,
                    skin_tone=skin,
                    hair_color=hair,
                    eye_color=eyes,
                    lighting=_CAPTION_LIGHTINGS[i % len(_CAPTION_LIGHTINGS)],
                    expression=_CAPTION_EXPRESSIONS[i % len(_CAPTION_EXPRESSIONS)],
                    style=style_desc,
                )
            else:
                angle_desc = _FULL_ANGLE_DESCS[i % len(_FULL_ANGLE_DESCS)]
                tpl = _FULL_CAPTION_TPL
                caption = tpl.format(
                    trigger=trigger,
                    gender=gender,
                    angle=angle_desc,
                    skin_tone=skin,
                    hair_color=hair,
                    eye_color=eyes,
                    pose=_CAPTION_POSES[i % len(_CAPTION_POSES)],
                    lighting=_CAPTION_LIGHTINGS[i % len(_CAPTION_LIGHTINGS)],
                    camera_framing=_CAPTION_FRAMINGS[i % len(_CAPTION_FRAMINGS)],
                    expression=_CAPTION_EXPRESSIONS[i % len(_CAPTION_EXPRESSIONS)],
                    style=style_desc,
                )
            txt_path = os.path.splitext(img_path)[0] + '.txt'
            with open(txt_path, 'w') as tf:
                tf.write(caption)


# ── Module-level singleton ───────────────────────────────────────────────────────
_service_instance: Optional[BlenderCharacterService] = None


def get_service() -> BlenderCharacterService:
    global _service_instance
    if _service_instance is None:
        _service_instance = BlenderCharacterService()
    return _service_instance
