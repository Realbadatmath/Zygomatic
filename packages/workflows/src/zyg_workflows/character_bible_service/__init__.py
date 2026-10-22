# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
character_bible_service.py
==========================
Persistent "synthetic actor" packages for long-form visual continuity.

Each character has a ``character_bible.json`` beside their dataset under
``lora-datasets/storyteller_chars/<char_id>/``.

The bible is consumed by ``comfy_generation_service`` (Comfy graphs) and
``consistency_qa_service`` (drift detection).  Python orchestration remains
the source of truth for pipeline state.

Schema v3 separates permanent identity from default presentation (swappable
per scene).  The bible is consumed by ``comfy_generation_service`` (Comfy graphs)
and ``consistency_qa_service`` (drift detection).

Permanent identity: face/hair structure, marks — stable across productions.
Default presentation: clothing, accessories, expression, posture — may change.
"""

# The submodule imports below re-export the whole namespace of the module this
# package replaces, in the original section order of the pre-split file.
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional
import logging as _zyg_logging

from zyg_workflows import paths

# Submodules, in the original section order of character_bible_service.py.
from .smile import (
    _DATASET_ROOT,
    _OUTPUT_ROOT,
    _BIBLE_FILENAME,
    _SCHEMA_VERSION,
    AUTO,
    _is_auto,
    text_requests_smile,
    expression_has_smile,
    format_expression_for_prompt,
    resolve_open_smile_expression,
    apply_smile_intent,
    wants_visible_smile,
    wants_visible_smile_package,
    face_detail_wildcard_for_params,
    preview_expression_boost,
    bible_path,
    PHOTOREAL_STYLE_PHRASE,
    SMILE_EXPRESSION_OPEN,
    SMILE_EXPRESSION_WARM,
    SMILE_EXPRESSION_PLAYFUL,
    _SMILE_HINT_RE,
    _SERIOUS_EXPR_RE,
)
from .references import (
    _utc_now,
    _env_on,
    _PREVIEW_REF_NAMES,
    _CONTACT_SHEET_REF_NAMES,
    _ROOT_REF_NAMES,
    _preview_provenance_ok,
    _pick_reference_images_legacy,
    _pick_reference_images,
    _find_lora_path,
    default_package,
    _AMS_TZ,
)

# `ZoneInfo` was bound by an import inside a try/except in the module this
# package replaces: absent, not None, when zoneinfo is unavailable.  The
# `hasattr` re-binding that goes with it is at the foot of the file, so the
# import block stays unbroken.
from . import references as _references
from .genre_tables import (
    _GENRE_WARDROBE,
    _GENRE_WARDROBE_POOL,
    _GENRE_LIGHTING_POOL,
    _GENRE_ACCESSORY_POOL,
    _GENRE_PALETTE,
)
from .appearance_negatives import (
    PHOTOREAL_SKIN_EXTRA,
    PHOTOREAL_SKIN_NEG,
    _SKIN_TONE_PHRASE,
    _DARK_SKIN_TONES,
    _SKIN_TONE_PHRASE_NEUTRAL,
    _SKIN_SCALE_ORDER,
    _SKIN_NEG_PHRASE,
    skin_tone_negatives,
    _HAIR_NEG_BY_COLOR,
    hair_color_negatives,
    age_negatives,
    _MINOR_SAFETY_NEG,
    _AGED_UP_NEG,
    _MINOR_AGE_RANGES,
    _MINOR_GENDER_NOUN,
    is_minor_identity,
    minor_safety_negatives,
    age_prompt_phrase,
    describe_skin_tone,
)
from .trait_tables import (
    _GENRE_LIGHTING,
    _GENRE_ACCESSORY,
    _HAIRCOLOR_TEXTURE,
    _GENDER_DEFAULTS,
    _SKIN_TONE_POOL,
    _HERITAGE_BY_SKIN,
    _AFRICAN_HERITAGES,
    _SKIN_BY_HERITAGE,
    _EYES_LIGHT_SKIN,
    _EYES_DEEP_SKIN,
    _HAIR_LIGHT_SKIN,
    _HAIR_DEEP_SKIN,
    _FACE_SHAPE_POOL,
    _EYE_SHAPE_POOL,
    _EYE_SHAPE_POOL_ASIAN,
    _BROW_POOL,
    _NOSE_POOL,
    _LIP_POOL,
    _HAIR_COMBOS,
    _MARKS_POOL,
    _MUSCLE_POOL,
    _muscle_text,
    _height_text,
    _age_range_from_age,
)
from .names import (
    _FIRST_NAMES_FEMALE,
    _FIRST_NAMES_MALE,
    _LAST_NAMES,
    _EYE_COLOR_WORDS,
    _title_word,
    _random_last_name,
    _NARRATOR_VOICES_PATH,
    _auto_character_voice,
    _existing_display_names,
    generate_random_full_name,
    resolve_character_display_name,
    format_library_label,
)
from .auto_defaults import (
    apply_auto_defaults,
)
from .store import (
    migrate_package,
    load,
    _enforce_age_invariant,
    save,
    build_from_character_generate,
    sync_delivered_attributes,
    update_lora,
    record_scene_shot,
    _presentation_from_package,
)
from .prompt_identity import (
    _APPEARANCE_CLAUSES,
    _WARDROBE_CLAUSES,
    _ACCESSORY_CLAUSES,
    _GROOMING_CLAUSES,
    _GRIME_THRESHOLD,
    _studio_clauses,
    _grime_clauses,
    identity_prompt_prefix,
    presentation_prompt_fragment,
    enhance_accessories_for_prompt,
    full_character_descriptor,
)
from .prompt_suffixes import (
    _SOLO_SUBJECT_NEG,
    _PREVIEW_SCENE_NEG,
    _ANATOMY_NEG,
    SCHOLARLY_ANATOMY_POSITIVE,
    SCHOLARLY_CN_CONDITIONING_SCALE,
    apply_scholarly_conditioning_defaults,
    scholarly_anatomy_prompt_suffix,
    scholarly_controlnet_scale,
    scholarly_flux_negative_prompt,
    negative_prompt_for_package,
    preview_studio_suffix,
    quality_suffix_for_package,
    storyteller_quality_suffix,
    storyteller_face_detail_enabled,
    storyteller_identity_snippet,
    compose_storyteller_render_prompt,
    indoor_style_suffix,
    get_master_reference,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'json',
    'os',
    're',
    'datetime',
    'timezone',
    'Any',
    'Callable',
    'Optional',
    'paths',
    '_DATASET_ROOT',
    '_OUTPUT_ROOT',
    '_BIBLE_FILENAME',
    '_SCHEMA_VERSION',
    'AUTO',
    '_is_auto',
    'text_requests_smile',
    'expression_has_smile',
    'format_expression_for_prompt',
    'resolve_open_smile_expression',
    'apply_smile_intent',
    'wants_visible_smile',
    'wants_visible_smile_package',
    'face_detail_wildcard_for_params',
    'preview_expression_boost',
    'bible_path',
    'PHOTOREAL_STYLE_PHRASE',
    'SMILE_EXPRESSION_OPEN',
    'SMILE_EXPRESSION_WARM',
    'SMILE_EXPRESSION_PLAYFUL',
    '_SMILE_HINT_RE',
    '_SERIOUS_EXPR_RE',
    '_utc_now',
    '_env_on',
    '_PREVIEW_REF_NAMES',
    '_CONTACT_SHEET_REF_NAMES',
    '_ROOT_REF_NAMES',
    '_preview_provenance_ok',
    '_pick_reference_images_legacy',
    '_pick_reference_images',
    '_find_lora_path',
    'default_package',
    '_AMS_TZ',
    '_GENRE_WARDROBE',
    '_GENRE_WARDROBE_POOL',
    '_GENRE_LIGHTING_POOL',
    '_GENRE_ACCESSORY_POOL',
    '_GENRE_PALETTE',
    'PHOTOREAL_SKIN_EXTRA',
    'PHOTOREAL_SKIN_NEG',
    '_SKIN_TONE_PHRASE',
    '_DARK_SKIN_TONES',
    '_SKIN_TONE_PHRASE_NEUTRAL',
    '_SKIN_SCALE_ORDER',
    '_SKIN_NEG_PHRASE',
    'skin_tone_negatives',
    '_HAIR_NEG_BY_COLOR',
    'hair_color_negatives',
    'age_negatives',
    '_MINOR_SAFETY_NEG',
    '_AGED_UP_NEG',
    '_MINOR_AGE_RANGES',
    '_MINOR_GENDER_NOUN',
    'is_minor_identity',
    'minor_safety_negatives',
    'age_prompt_phrase',
    'describe_skin_tone',
    '_GENRE_LIGHTING',
    '_GENRE_ACCESSORY',
    '_HAIRCOLOR_TEXTURE',
    '_GENDER_DEFAULTS',
    '_SKIN_TONE_POOL',
    '_HERITAGE_BY_SKIN',
    '_AFRICAN_HERITAGES',
    '_SKIN_BY_HERITAGE',
    '_EYES_LIGHT_SKIN',
    '_EYES_DEEP_SKIN',
    '_HAIR_LIGHT_SKIN',
    '_HAIR_DEEP_SKIN',
    '_FACE_SHAPE_POOL',
    '_EYE_SHAPE_POOL',
    '_EYE_SHAPE_POOL_ASIAN',
    '_BROW_POOL',
    '_NOSE_POOL',
    '_LIP_POOL',
    '_HAIR_COMBOS',
    '_MARKS_POOL',
    '_MUSCLE_POOL',
    '_muscle_text',
    '_height_text',
    '_age_range_from_age',
    '_FIRST_NAMES_FEMALE',
    '_FIRST_NAMES_MALE',
    '_LAST_NAMES',
    '_EYE_COLOR_WORDS',
    '_title_word',
    '_random_last_name',
    '_NARRATOR_VOICES_PATH',
    '_auto_character_voice',
    '_existing_display_names',
    'generate_random_full_name',
    'resolve_character_display_name',
    'format_library_label',
    'apply_auto_defaults',
    'migrate_package',
    'load',
    '_enforce_age_invariant',
    'save',
    'build_from_character_generate',
    'sync_delivered_attributes',
    'update_lora',
    'record_scene_shot',
    '_presentation_from_package',
    '_APPEARANCE_CLAUSES',
    '_WARDROBE_CLAUSES',
    '_ACCESSORY_CLAUSES',
    '_GROOMING_CLAUSES',
    '_GRIME_THRESHOLD',
    '_studio_clauses',
    '_grime_clauses',
    'identity_prompt_prefix',
    'presentation_prompt_fragment',
    'enhance_accessories_for_prompt',
    'full_character_descriptor',
    '_SOLO_SUBJECT_NEG',
    '_PREVIEW_SCENE_NEG',
    '_ANATOMY_NEG',
    'SCHOLARLY_ANATOMY_POSITIVE',
    'SCHOLARLY_CN_CONDITIONING_SCALE',
    'apply_scholarly_conditioning_defaults',
    'scholarly_anatomy_prompt_suffix',
    'scholarly_controlnet_scale',
    'scholarly_flux_negative_prompt',
    'negative_prompt_for_package',
    'preview_studio_suffix',
    'quality_suffix_for_package',
    'storyteller_quality_suffix',
    'storyteller_face_detail_enabled',
    'storyteller_identity_snippet',
    'compose_storyteller_render_prompt',
    'indoor_style_suffix',
    'get_master_reference',
]

_zyg_log = _zyg_logging.getLogger(__name__)

if hasattr(_references, 'ZoneInfo'):
    ZoneInfo = _references.ZoneInfo
