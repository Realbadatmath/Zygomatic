# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Contract tests for pipeline_char2d — the board join key and the Run string.

No Blender, no GPU, no Flask: everything here is pure data. The two things that
silently break the '2D Character Basics I' board are (a) a stage title that is a
substring of another, because bp_pipeline_api.kanban_status matches by substring
first-match-wins, and (b) a Run-button string the runner cannot parse.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import pipeline_char2d as C  # noqa: E402


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── the board join key ───────────────────────────────────────────────────────


def test_stage_titles_are_unique():
    assert len(C.STAGES) == len(set(C.STAGES)) == 14


def test_no_stage_title_is_a_substring_of_another():
    """kanban_status maps title -> [title.lower()] and matches by SUBSTRING,
    first-match-wins: a title inside another title stamps both cards from
    whichever ran first."""
    low = [s.lower() for s in C.STAGES]
    for i, a in enumerate(low):
        for j, b in enumerate(low):
            if i != j:
                assert a not in b, '%r is a substring of %r' % (C.STAGES[i], C.STAGES[j])


def test_stage_titles_match_the_board():
    """kanban_main.js TEMPLATES.char2d_basics_1 card prompts ARE these strings."""
    js = os.path.join(HERE, 'kanban_assets', 'kanban_main.js')
    if not os.path.isfile(js):
        pytest.skip('kanban_main.js not present')
    with open(js, 'r', encoding='utf-8') as fh:
        text = fh.read()
    start = text.index('T.char2d_basics_1')
    block = text[start : text.index('T.char2d_basics_2', start)]
    for title in C.STAGES:
        assert "prompt: '%s'" % title in block, 'no card titled %r' % title


# ── the Run-button string ────────────────────────────────────────────────────

RUN_STRING = 'Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a'


def test_parse_directive_run_button_string():
    brief = C.parse_directive(RUN_STRING)
    assert brief == {
        'name': 'Mika',
        'gender': 0.2,
        'age': 19.0,
        'height_m': 1.68,
        'hair_cut': 'bob',
        'skin': '#f5cfb5',
        'hair': '#2a1a12',
        'top': '#3b5fa3',
        'bottom': '#2b2f3a',
    }


def test_parse_directive_accepts_comma_separated_colours():
    brief = C.parse_directive('Bo, 0.9, 42, 1.81, short, #ccaa88, #111111, #557733, #222222')
    assert brief['name'] == 'Bo' and brief['hair_cut'] == 'short'
    assert brief['skin'] == '#ccaa88' and brief['bottom'] == '#222222'


def test_parse_directive_rejects_bad_input():
    for bad, needle in (
        ('', 'required'),
        ('Mika, 0.2, 19', 'field'),
        ('Mika, 0.2, 19, 1.68, mohawk, #fff #000 #123 #456', 'hair_cut'),
        ('Mika, 4.0, 19, 1.68, bob, #fff #000 #123 #456', 'gender'),
        ('Mika, 0.2, 19, 168, bob, #fff #000 #123 #456', 'height_m'),
        ('Mika, x, 19, 1.68, bob, #fff #000 #123 #456', 'number'),
    ):
        with pytest.raises(ValueError) as exc:
            C.parse_directive(bad)
        assert needle in str(exc.value)


def test_normalise_brief_prefers_the_dict():
    brief = C.normalise_brief(
        {'name': 'Zed', 'gender': 1.0, 'age': 30, 'height_m': 1.9, 'hair_cut': 'LONG'}, RUN_STRING
    )
    assert brief['name'] == 'Zed' and brief['hair_cut'] == 'long'


def test_normalise_brief_falls_back_to_the_directive():
    assert C.normalise_brief(None, RUN_STRING)['name'] == 'Mika'
    assert C.normalise_brief({}, RUN_STRING)['name'] == 'Mika'


def test_shipped_briefs_normalise():
    for name in sorted(os.listdir(C.BRIEF_DIR)):
        if not name.endswith('.json'):
            continue
        with open(os.path.join(C.BRIEF_DIR, name), 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
        brief = C.normalise_brief(raw, '')
        assert brief['name'] and brief['hair_cut'] in ('bob', 'short', 'long')


def test_describe_round_trips_through_the_parser():
    brief = C.parse_directive(RUN_STRING)
    assert C.parse_directive(C.describe(brief)) == brief


# ── the gesture set the runner will render ───────────────────────────────────


def test_gestures_are_present_and_idle_is_excluded():
    import glob

    paths = sorted(glob.glob(os.path.join(C.GESTURE_DIR, '*.json')))
    names = [os.path.basename(p) for p in paths]
    assert '00_idle.json' in names
    kept = [p for p in paths if not os.path.basename(p).startswith('00_idle')]
    assert len(kept) == 10, 'expected ten gestures, got %d' % len(kept)


def test_hard_hand_tags_are_the_three_the_brief_names():
    assert set(C.HARD_HAND_TAGS) == {'fused-fingers', 'hand-count-mismatch', 'chirality-flip'}
