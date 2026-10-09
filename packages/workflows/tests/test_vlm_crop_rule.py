#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
The crop rule, enforced.

A question must be asked of evidence that can answer it. Measured failure this
guards: `pipe_held_by_stem` was asked on the BOWL crop and failed at all 6
timestamps with the judge's own reason — "the stem is not visible in any of the
frames" — while the identical question on the `pipe` crop PASSED. One mis-mapping
produced a critical FAIL on a correct render.

    .venv-test/bin/python -m pytest tests/test_vlm_crop_rule.py -q
"""

import os
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

vlm = pytest.importorskip('vlm_report', reason='vlm_report unavailable')


@pytest.mark.parametrize('item', sorted(vlm.ITEM_TARGETS))
def test_every_item_has_an_answerable_crop(item):
    role = vlm.first_answerable_target(item)
    assert role is not None, (
        f'{item!r} has no crop in ITEM_TARGETS that can show '
        f'{vlm.ITEM_REQUIRES_VISIBLE.get(item)}. Asking it anyway produces a '
        f'FAIL that means "I could not see it".'
    )


def test_the_bowl_crop_cannot_answer_a_question_about_the_stem():
    """The exact regression. If someone re-points this at 'bowl', this fails."""
    assert vlm.item_answerable_on('pipe_held_by_stem', 'bowl') is False
    assert vlm.item_answerable_on('pipe_held_by_stem', 'pipe') is True
    assert vlm.first_answerable_target('pipe_held_by_stem') == 'pipe'


def test_first_listed_target_is_the_answerable_one():
    """Order matters: the first target is the one actually used."""
    broken = [
        i for i in vlm.ITEM_TARGETS if vlm.ITEM_TARGETS[i] and not vlm.item_answerable_on(i, vlm.ITEM_TARGETS[i][0])
    ]
    assert not broken, f'these items ask their FIRST crop something it cannot show: {broken}'


def test_every_item_declares_what_it_needs_to_see():
    missing = sorted(set(vlm.ITEM_TARGETS) - set(vlm.ITEM_REQUIRES_VISIBLE))
    assert not missing, f'no evidence requirement declared for: {missing}'


def test_beat_scoped_items_are_declared():
    """'pipe_at_lips' is beat-unaware by nature: the scene deliberately has the
    pipe away from the lips between draws, so a 'no' at a rest beat is a SPEC
    error, not a render defect."""
    assert 'pipe_at_lips' in vlm.ITEM_BEAT_SCOPED
    assert vlm.ITEM_BEAT_SCOPED['pipe_at_lips']['beats']


def test_unreliable_pass_items_are_still_declared_unreliable():
    """A PASS from a judge with 0/7 recall is not evidence of cleanliness."""
    assert 'ink_off_page' in vlm.VLM_UNRELIABLE_PASS
