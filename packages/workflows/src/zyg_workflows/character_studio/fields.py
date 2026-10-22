# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The constants and the first half of the ``FIELDS`` registry.

Moved verbatim from ``character_studio.py`` lines 36-419 by the 2026-10-06
modularization split; the registry dict is closed here and the second half is
appended by ``fields_new``.
"""

from __future__ import annotations

import os
import re
from typing import Any
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.character_studio')


_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)
LORA_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_LORAS)

MAX_TEXT = 2000  # a free-text bible field; negative_prompt is the long one
MAX_EDITS = 60  # one panel writes one field; a batch apply writes a section


# ── the registry ─────────────────────────────────────────────────────────────
# path -> spec.  t: text | area | enum | int | float | bool | ro
#   choices  — offered in the picker; `open` means free text is also accepted
#   min/max/step — numeric bounds, enforced on write
#   ro       — read-only: served to the client, refused on write
#
# The enum choice lists are the values that ACTUALLY OCCUR across the bibles on
# disk plus the documented ones from default_package()'s comments. They are
# open where the corpus is open (hair_style has 26 distinct values across 132
# characters — closing that list would delete descriptions), closed where the
# field is a switch the pipeline branches on (model_family, render_style).
FIELDS: dict[str, dict[str, Any]] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    'display_name': {
        't': 'text',
        'sec': 'identity',
        'label': 'Display name',
        'help': 'The name the library, the kanban board and every picker show. Not the trigger token.',
    },
    'character_id': {'t': 'ro', 'sec': 'identity', 'label': 'Character id'},
    'trigger_token': {
        't': 'ro',
        'sec': 'identity',
        'label': 'Trigger token',
        'help': 'The token the LoRA was trained on. Changing it '
        'here would not retrain the weights, so it is '
        'read-only — the renders would stop matching.',
    },
    'schema_version': {'t': 'ro', 'sec': 'identity', 'label': 'Schema version'},
    'created_at': {'t': 'ro', 'sec': 'identity', 'label': 'Created'},
    'updated_at': {'t': 'ro', 'sec': 'identity', 'label': 'Last saved'},
    'identity.gender': {
        't': 'enum',
        'sec': 'identity',
        'label': 'Gender',
        'open': True,
        'choices': ['female', 'male', 'non-binary'],
    },
    'identity.age': {
        't': 'int',
        'sec': 'identity',
        'label': 'Age',
        'min': 1,
        'max': 99,
        'help': 'The numeric age is authoritative. Saving it '
        'recomputes age_range, and age_range decides which '
        'safety negatives fire at render time.',
    },
    'identity.age_range': {
        't': 'ro',
        'sec': 'identity',
        'label': 'Age range',
        'help': 'Derived from age on save — not edited directly.',
    },
    'identity.ethnic_heritage': {
        't': 'text',
        'sec': 'identity',
        'label': 'Heritage',
        'open': True,
        'help': 'Cultural hint. Independent of skin tone — any tone pairs with any heritage.',
    },
    'identity.height_m': {'t': 'float', 'sec': 'identity', 'label': 'Height (m)', 'min': 0.6, 'max': 2.5, 'step': 0.01},
    # ── Face ─────────────────────────────────────────────────────────────────
    'identity.face_shape': {
        't': 'enum',
        'sec': 'face',
        'label': 'Face shape',
        'open': True,
        'choices': ['oval', 'round', 'square', 'heart', 'long', 'diamond'],
    },
    'identity.nose_shape': {
        't': 'enum',
        'sec': 'face',
        'label': 'Nose',
        'open': True,
        'choices': ['balanced', 'aquiline', 'button', 'broad', 'narrow', 'straight and strong', 'small and straight'],
    },
    'identity.lip_shape': {
        't': 'enum',
        'sec': 'face',
        'label': 'Lips',
        'open': True,
        'choices': ['natural', 'natural full', 'full', 'thin', 'wide'],
    },
    'identity.eyebrow_style': {
        't': 'enum',
        'sec': 'face',
        'label': 'Eyebrows',
        'open': True,
        'choices': ['natural', 'natural arched', 'arched', 'thick', 'sparse', 'straight'],
    },
    'identity.facial_hair': {
        't': 'enum',
        'sec': 'face',
        'label': 'Facial hair',
        'open': True,
        'choices': ['none', 'stubble', 'short beard', 'full beard', 'goatee', 'moustache', 'clean-shaven'],
    },
    'identity.skin_tone': {
        't': 'enum',
        'sec': 'face',
        'label': 'Skin tone',
        'open': True,
        'choices': ['fair', 'light', 'medium', 'olive', 'tan', 'dark', 'deep'],
        'help': 'Decoupled from heritage on purpose — the two are separate fields and either may be set alone.',
    },
    'identity.distinctive_marks': {
        't': 'area',
        'sec': 'face',
        'label': 'Distinctive marks',
        'help': 'Freckles, scars, dimples, beauty marks, tattoos. '
        '"none" is a valid value and is not the same as empty.',
    },
    # ── Eyes ─────────────────────────────────────────────────────────────────
    'identity.eye_color': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Eye colour',
        'open': True,
        'choices': ['brown', 'blue', 'green', 'hazel', 'amber', 'grey', 'grey-blue'],
    },
    'identity.eye_shape': {
        't': 'enum',
        'sec': 'eyes',
        'label': 'Eye shape',
        'open': True,
        'choices': ['almond', 'round', 'hooded', 'monolid', 'upturned', 'downturned', 'deep-set'],
    },
    # ── Hair ─────────────────────────────────────────────────────────────────
    'identity.hair_color': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Hair colour',
        'open': True,
        'choices': [
            'black',
            'dark brown',
            'brown',
            'light brown',
            'auburn',
            'red',
            'blonde',
            'dark blond',
            'grey',
            'white',
        ],
    },
    'identity.hair_length': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Hair length',
        'open': True,
        'choices': ['shaved', 'short', 'medium', 'shoulder', 'long', 'waist-length'],
    },
    'identity.hair_texture': {
        't': 'enum',
        'sec': 'hair',
        'label': 'Hair texture',
        'open': True,
        'choices': ['straight', 'wavy', 'curly', 'coily', 'kinky'],
    },
    'identity.hair_style': {
        't': 'area',
        'sec': 'hair',
        'label': 'Hair style',
        'help': 'The cut itself, in words — "collar-length side-swept", "tight curls", "1mm shave".',
    },
    # ── Body ─────────────────────────────────────────────────────────────────
    'identity.body_build': {
        't': 'enum',
        'sec': 'body',
        'label': 'Build',
        'open': True,
        'choices': ['slender build', 'average build', 'athletic build', 'muscular build', 'heavy build'],
        'help': 'Some older bibles hold a bare number here — the legacy '
        'raw muscle slider. A descriptor is what the prompt builder '
        'wants.',
    },
    'identity.muscle_mass': {
        't': 'int',
        'sec': 'body',
        'label': 'Muscle mass',
        'min': 1,
        'max': 100,
        'help': '1–100. Mapped to words by the prompt builder, not sent raw.',
    },
    # ── Wardrobe ─────────────────────────────────────────────────────────────
    'default_presentation.default_clothing': {
        't': 'area',
        'sec': 'wardrobe',
        'label': 'Clothing',
        'mirror': 'style_profile.default_clothing',
        'help': 'Default outfit. Presentation, not identity — a scene may override it.',
    },
    'default_presentation.accessories': {
        't': 'area',
        'sec': 'accessories',
        'label': 'Accessories',
        'mirror': 'style_profile.accessories',
    },
    # ── Expression / pose ────────────────────────────────────────────────────
    'default_presentation.default_expression': {
        't': 'area',
        'sec': 'expression',
        'label': 'Default expression',
        'mirror': 'style_profile.default_expression',
        'help': 'Naming a smile here arms the smile-intent path — the face-detail wildcard changes with it.',
    },
    'default_presentation.posture': {'t': 'area', 'sec': 'pose', 'label': 'Posture', 'mirror': 'style_profile.posture'},
    # ── Render / staging ─────────────────────────────────────────────────────
    'style_profile.render_style': {
        't': 'enum',
        'sec': 'render',
        'label': 'Render style',
        'choices': ['photorealistic', 'animated', 'cinematic illustration'],
    },
    'style_profile.genre': {
        't': 'enum',
        'sec': 'render',
        'label': 'Genre',
        'open': True,
        'choices': ['general', 'action', 'romance', 'religion', 'finance', 'medieval', 'education', 'historical drama'],
    },
    'style_profile.indoor_stage': {'t': 'bool', 'sec': 'render', 'label': 'Indoor stage'},
    'style_profile.lighting_profile': {'t': 'area', 'sec': 'render', 'label': 'Lighting'},
    'style_profile.color_palette': {'t': 'area', 'sec': 'render', 'label': 'Colour palette'},
    'style_profile.camera_language': {'t': 'area', 'sec': 'render', 'label': 'Camera language'},
    'style_profile.restyle': {
        't': 'enum',
        'sec': 'render',
        'label': 'Restyle',
        'open': True,
        'choices': ['', 'arcane_animation'],
        'help': 'Which restyle pass the finished stills go through.',
    },
    'style_profile.character_brief_prose': {
        't': 'area',
        'sec': 'render',
        'label': 'Brief (prose)',
        'help': 'The written brief this character was built from.',
    },
    # ── Model / conditioning ─────────────────────────────────────────────────
    'conditioning.model_family': {
        't': 'enum',
        'sec': 'model',
        'label': 'Model family',
        'choices': ['flux', 'sdxl', 'klein', 'qwen'],
        'help': 'Decides which LoRA path and which workflow the renderer picks.',
    },
    'conditioning.lora_scale': {
        't': 'float',
        'sec': 'model',
        'label': 'LoRA scale',
        'min': 0.0,
        'max': 1.5,
        'step': 0.05,
    },
    'conditioning.ipadapter_scale': {
        't': 'float',
        'sec': 'model',
        'label': 'IPAdapter scale',
        'min': 0.0,
        'max': 1.5,
        'step': 0.05,
    },
    'conditioning.instantid_enabled': {'t': 'bool', 'sec': 'model', 'label': 'InstantID'},
    'conditioning.instantid_weight': {
        't': 'float',
        'sec': 'model',
        'label': 'InstantID weight',
        'min': 0.0,
        'max': 1.0,
        'step': 0.05,
    },
    'conditioning.face_detail_pass': {'t': 'bool', 'sec': 'model', 'label': 'Face-detail pass'},
    'conditioning.face_detail_strength': {
        't': 'float',
        'sec': 'model',
        'label': 'Face-detail strength',
        'min': 0.0,
        'max': 1.0,
        'step': 0.05,
        'help': 'Measured 2026-07-09: at 0.45 the detailer '
        're-synthesised about half the face with the '
        'smooth-skin prior and erased base-pass texture. '
        '0.30 is the ceiling that kept it.',
    },
    'conditioning.hand_detail_pass': {'t': 'bool', 'sec': 'model', 'label': 'Hand-detail pass'},
    'conditioning.hand_detail_strength': {
        't': 'float',
        'sec': 'model',
        'label': 'Hand strength',
        'min': 0.0,
        'max': 1.0,
        'step': 0.05,
    },
    'conditioning.quality_suffix': {'t': 'area', 'sec': 'model', 'label': 'Quality suffix'},
    'conditioning.negative_prompt': {
        't': 'area',
        'sec': 'model',
        'label': 'Negative prompt',
        'help': "Sent on every render. Watch for a negative that bans the character's own anatomy.",
    },
    'conditioning.sdxl_checkpoint': {
        't': 'enum',
        'sec': 'model',
        'label': 'SDXL checkpoint',
        'open': True,
        'choices': [
            'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors',
            'sd_xl_base_1.0.safetensors',
            'DynaVisionXL.safetensors',
        ],
    },
    'conditioning.lora_path': {'t': 'ro', 'sec': 'model', 'label': 'LoRA path'},
    'conditioning.flux_lora_path': {'t': 'ro', 'sec': 'model', 'label': 'FLUX LoRA'},
    'conditioning.sdxl_lora_path': {'t': 'ro', 'sec': 'model', 'label': 'SDXL LoRA'},
    'conditioning.klein_lora_path': {'t': 'ro', 'sec': 'model', 'label': 'klein LoRA'},
    'conditioning.qwen_lora_path': {'t': 'ro', 'sec': 'model', 'label': 'Qwen LoRA'},
    'conditioning.master_reference_image': {'t': 'ro', 'sec': 'model', 'label': 'Master reference'},
    # WRITABLE 2026-09-02 (S05), with a validator rather than a free path. The
    # renderer loads whatever string is here as a ControlNet input, so an
    # arbitrary path is an arbitrary image reaching the render: the only values
    # accepted are plates geom.body_plates rendered for THIS character, or ''
    # to clear it. That is a whitelist of files, not a shape check on a string.
    'conditioning.controlnet_pose_reference': {
        't': 'plate',
        'sec': 'model',
        'label': 'Pose reference',
        'help': 'A depth / normal / matte plate '
        "rendered from this character's own "
        'registered body. Anything else is '
        'refused.',
    },
    # ── Voice ────────────────────────────────────────────────────────────────
    'voice_profile.character_voice': {
        't': 'text',
        'sec': 'voice',
        'label': 'Character voice',
        'help': 'Either a voice id or a written description of how this character speaks — both occur in the corpus.',
    },
    'voice_profile.character_voice_profile': {'t': 'text', 'sec': 'voice', 'label': 'Voice profile'},
    'voice_profile.narrator_hint': {'t': 'area', 'sec': 'voice', 'label': 'Narrator hint'},
    # ── Motion ───────────────────────────────────────────────────────────────
    'motion_profile.default_emotion': {
        't': 'enum',
        'sec': 'motion',
        'label': 'Default emotion',
        'open': True,
        'choices': ['neutral', 'warm', 'stern', 'weary', 'alert', 'sad', 'amused'],
    },
    'motion_profile.pacing': {
        't': 'enum',
        'sec': 'motion',
        'label': 'Pacing',
        'open': True,
        'choices': ['measured', 'brisk', 'slow', 'restless'],
    },
    # ── Dataset (read-only) ──────────────────────────────────────────────────
    'dataset_dir': {'t': 'ro', 'sec': 'dataset', 'label': 'Dataset dir'},
    'source_manifest': {'t': 'ro', 'sec': 'dataset', 'label': 'Source manifest'},
}
