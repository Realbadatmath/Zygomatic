#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for character brief merge (no API calls)."""

import os
import sys

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)

from zyg_workflows import character_brief_service as cbs  # noqa: E402  deliberate late import, after the sys.path shim above
from zyg_workflows import character_bible_service as bible  # noqa: E402  deliberate late import, after the sys.path shim above


def test_flatten_accessories_none():
    assert (
        cbs.flatten_accessory_decisions(
            {
                'earrings': {'wear': False},
                'necklace': {'wear': False},
            }
        )
        == 'none'
    )


def test_flatten_accessories_mixed():
    out = cbs.flatten_accessory_decisions(
        {
            'earrings': {'wear': True, 'type': 'small gold hoops'},
            'watch': {'wear': True, 'type': 'thin leather strap watch'},
            'gloves': {'wear': False},
        }
    )
    assert 'gold hoops' in out
    assert 'watch' in out
    assert 'glove' not in out.lower()


def test_merge_respects_locked_identity():
    params = {
        'face_shape': 'square',
        'hair_length': 'auto',
        'accessories': 'auto',
        'default_clothing': 'auto',
    }
    brief = {
        'brief_prose': 'Test character.',
        'identity': {'face_shape': 'oval', 'hair_length': 'long', 'distinctive_marks': 'freckles'},
        'presentation': {
            'default_clothing': 'navy blazer',
            'accessories': 'none',
            'default_expression': 'warm smile',
            'posture': 'upright relaxed',
            'lighting_profile': 'soft studio key',
            'color_palette': 'navy, cream, gold',
        },
        'accessory_decisions': {'earrings': {'wear': False}},
    }
    merged = cbs.merge_brief_into_params(params, brief)
    assert merged['face_shape'] == 'square'
    assert merged['hair_length'] == 'long'
    assert merged['distinctive_marks'] == 'freckles'
    assert merged['default_clothing'] == 'navy blazer'
    assert merged['accessories'] == 'none'


def test_identity_presentation_split():
    pkg = bible.default_package('split_test', 'ZYG_CHAR_SPLIT')
    pkg['identity'].update(
        {
            'gender': 'female',
            'age': 25,
            'skin_tone': 'tan',
            'hair_color': 'brown',
            'eye_color': 'green',
            'face_shape': 'heart',
            'hair_texture': 'wavy',
            'distinctive_marks': 'light freckles',
        }
    )
    pkg['default_presentation'].update(
        {
            'default_clothing': 'casual denim jacket',
            'accessories': 'small gold hoops',
            'default_expression': 'neutral confident',
            'posture': 'upright relaxed',
        }
    )
    pkg['style_profile'].update(pkg['default_presentation'])
    ident = bible.identity_prompt_prefix(pkg)
    pres = bible.presentation_prompt_fragment(pkg)
    assert 'heart face' in ident
    assert 'freckles' in ident
    assert 'denim jacket' not in ident
    assert 'denim jacket' in pres
    assert 'gold hoop' in pres


def test_ensure_photoreal_skin_texture():
    p = {'style': 'photorealistic', 'extra_prompt': ''}
    out = cbs.ensure_photoreal_skin_texture(p)
    assert 'pore' in out['extra_prompt'].lower()
    locked = {'style': 'photorealistic', 'extra_prompt': 'visible skin pores already'}
    assert cbs.ensure_photoreal_skin_texture(locked)['extra_prompt'] == 'visible skin pores already'


def main():
    test_flatten_accessories_none()
    test_flatten_accessories_mixed()
    test_merge_respects_locked_identity()
    test_identity_presentation_split()
    test_ensure_photoreal_skin_texture()
    print('OK character brief merge tests')


if __name__ == '__main__':
    main()
