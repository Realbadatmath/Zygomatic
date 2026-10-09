#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for character_photo_analysis_service normalize + merge."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import character_photo_analysis_service as cpas


def test_normalize_enums():
    raw = {
        'gender': 'woman',
        'hair_color': 'blonde',
        'eye_color': 'blue',
        'skin_tone': 'light',
        'age': '32',
        'height': 1.73,
        'muscle_mass': 45,
        'facial_hair': 'none',
        'hair_length': 'shoulder',
        'face_shape': 'oval',
    }
    out = cpas.normalize_analysis(raw)
    assert out['gender'] == 'female'
    assert out['hair_color'] == 'blonde'
    assert out['age'] == 32
    assert out['height'] in cpas.HEIGHT_VALUES
    assert out['muscle_mass'] == 45


def test_merge_respects_locked():
    params = {
        'gender': 'female',
        'hair_color': 'brown',
        'eye_color': 'brown',
        'hair_style': 'auto',
        'face_shape': 'auto',
    }
    analysis = {
        'fields': {
            'gender': 'male',
            'hair_color': 'blonde',
            'eye_color': 'blue',
            'hair_style': 'long wavy',
            'face_shape': 'heart',
        }
    }
    merged = cpas.merge_analysis_into_params(
        params,
        analysis,
        locked_fields={'hair_color'},
        only_auto=True,
    )
    assert merged['hair_color'] == 'brown'
    assert merged['gender'] == 'male'
    assert merged['eye_color'] == 'blue'
    assert merged['face_shape'] == 'heart'


def test_reconcile_backends_agrees():
    results = [
        ('model_a', {'gender': 'female', 'hair_color': 'blonde', 'eye_color': 'blue'}),
        ('model_b', {'gender': 'female', 'hair_color': 'blonde', 'eye_color': 'blue'}),
    ]
    merged, ambiguous, confidence = cpas._reconcile_backends(results)
    assert confidence == 'agreed'
    assert ambiguous == []
    assert merged['gender'] == 'female'
    assert merged['hair_color'] == 'blonde'


def test_reconcile_backends_disputes_core_field():
    results = [
        ('model_a', {'gender': 'female', 'hair_color': 'blonde', 'eye_color': 'blue'}),
        ('model_b', {'gender': 'male', 'hair_color': 'blonde', 'eye_color': 'green'}),
    ]
    merged, ambiguous, confidence = cpas._reconcile_backends(results)
    assert confidence == 'disputed'
    assert set(ambiguous) == {'gender', 'eye_color'}
    assert 'gender' not in merged
    assert 'eye_color' not in merged
    assert merged['hair_color'] == 'blonde'  # both agreed, kept


def test_reconcile_backends_single_result():
    results = [('model_a', {'gender': 'female', 'hair_color': 'blonde'})]
    merged, ambiguous, confidence = cpas._reconcile_backends(results)
    assert confidence == 'single_backend'
    assert ambiguous == []
    assert merged['gender'] == 'female'


def test_write_training_captions(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, 'photo_000.jpg')
        with open(img, 'wb') as fh:
            fh.write(b'\xff\xd8\xff')
        analysis = {
            'ok': True,
            'image_captions': [
                {
                    'index': 0,
                    'path': img,
                    'caption': 'TRIGGER_TOKEN woman, blonde hair, portrait',
                }
            ],
        }
        params = {'gender': 'female', 'hair_color': 'blonde', 'style': 'photorealistic'}
        n = cpas.write_training_captions(
            [img],
            params,
            'zygchartest1',
            analysis=analysis,
        )
        assert n == 1
        cap_path = os.path.join(td, 'photo_000.txt')
        assert os.path.isfile(cap_path)
        text = open(cap_path, encoding='utf-8').read()
        assert 'zygchartest1' in text
        assert 'blonde' in text


if __name__ == '__main__':
    test_normalize_enums()
    test_merge_respects_locked()
    test_reconcile_backends_agrees()
    test_reconcile_backends_disputes_core_field()
    test_reconcile_backends_single_result()
    test_write_training_captions()
    print('OK — all character photo analysis tests passed')
