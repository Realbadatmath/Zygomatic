# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the rungs ``step_attribute_gate`` was split into.

``attribute_spec``, ``merge_negative``, ``eye_negatives``, ``iris_edit_prompt``
and ``iris_fix_kwargs`` were all inline in the 304-line gate — two of them as
closures over its locals — so this is the first time any of them can be called
with a hand-made input. No VLM, no generation service and no network: every
helper below is string and dict arithmetic, with a stub judge module standing in
for the vocabulary lookup.
"""

from __future__ import annotations

import os

import pytest

from zyg_workflows.contact_sheet_pipeline_steps.anchor_ctx import AnchorCtx
from zyg_workflows.contact_sheet_pipeline_steps.anchor_attribute_gate_rungs import (
    AttrGate,
    attribute_spec,
    boost_tokens,
    clear_scratch,
    eye_negatives,
    iris_edit_prompt,
    iris_fix_kwargs,
    merge_negative,
)

EYE_VOCAB = ('brown', 'green', 'blue', 'hazel', 'gray', 'amber')


class _OldJudge:
    """A judge module from before ``normalize_color`` existed."""

    EYE_VOCAB = EYE_VOCAB


class _Judge(_OldJudge):
    """The two attributes the pure rungs read off the judge module."""

    def normalize_color(self, colour):
        """Identity normalisation — enough to exercise the hasattr branch."""
        return colour.strip().lower()


def _ctx(tmp_path, **over):
    """An AnchorCtx with the fields the pure rungs read and dummies elsewhere."""
    cell = tmp_path / 'cell00.png'
    cell.write_text('ANCHOR')
    fields = dict(
        char_id='cid',
        params={'eye_color': 'Green'},
        log_fn=None,
        cell_path=str(cell),
        anchor_path=str(cell),
        gen_kwargs={'extra_negative': 'blurry', 'flux_guidance': 3.0, 'steps': 20},
        prompt='a studio portrait',
        pkg={},
        progress_job=None,
        anchor_family='fam',
        cell0_reused=False,
        render_style='photoreal',
        realism_lora_path='',
        realism_lora_scale=0.0,
        anchor_skin='',
        anchor_cfg=1.0,
        dark_retry_cfg=1.0,
        qwen_ok=True,
        base_seed=1,
        unet='u',
        skin_clause='',
        style_extra='',
        trigger='t',
        body_anchor_path='',
        photoreal=True,
    )
    fields.update(over)
    return AnchorCtx(**fields)


def _gate(tmp_path, *, spec=None, judge=None, **over):
    """An AttrGate wired to a stub judge and no generation service."""
    ctx = _ctx(tmp_path, **over)
    return AttrGate(
        ctx=ctx,
        cgs=None,
        avj=judge if judge is not None else _Judge(),
        spec=spec if spec is not None else {'eye_color': 'green'},
        eye_colors=EYE_VOCAB,
        retries=2,
        best_anchor=ctx.cell_path + '.attr_best.png',
        pregate_anchor=ctx.cell_path + '.attr_orig.png',
    )


# ---------------------------------------------------------------- attribute_spec


def test_attribute_spec_keeps_only_what_the_run_asked_for():
    """Lower-cased, stripped, and the blanks dropped entirely."""
    spec = attribute_spec({'eye_color': '  Green ', 'hair_color': '', 'skin_tone': 'OLIVE', 'age': 30})
    assert spec == {'eye_color': 'green', 'skin_tone': 'olive'}


def test_attribute_spec_of_an_unspecified_run_is_empty():
    """An empty spec is one of the three conditions that switch the gate off."""
    assert attribute_spec({}) == {}
    assert attribute_spec({'eye_color': '   ', 'hair_color': None}) == {}


def test_attribute_spec_tolerates_non_string_values():
    """A param that is not a string is treated as absent, not crashed on."""
    assert attribute_spec({'eye_color': 0, 'hair_color': False}) == {}


# ---------------------------------------------------------------- merge_negative


def test_merge_negative_appends_rather_than_replaces():
    """Replacing the run's negatives invited back the skin lightening."""
    assert merge_negative('blurry, lowres', 'brown eyes') == 'blurry, lowres, brown eyes'


@pytest.mark.parametrize(
    ('existing', 'addition', 'want'),
    [
        (None, 'brown eyes', 'brown eyes'),
        ('', 'brown eyes', 'brown eyes'),
        (', blurry, ', 'brown eyes', 'blurry, brown eyes'),
        ('blurry', '', 'blurry'),
        (None, '', ''),
    ],
)
def test_merge_negative_drops_the_empty_parts(existing, addition, want):
    """Commas only ever appear between two real clauses."""
    assert merge_negative(existing, addition) == want


# ---------------------------------------------------------------- eye_negatives


def test_eye_negatives_pushes_away_every_other_colour(tmp_path):
    """A bare positive loses to the prior, so the wrong colours are named."""
    got = eye_negatives(_gate(tmp_path), 'green')
    assert got == 'brown eyes, blue eyes, hazel eyes, gray eyes, amber eyes'


def test_eye_negatives_never_fights_the_spec_colour(tmp_path):
    """The specified colour, and anything containing it, is excluded."""
    for colour in EYE_VOCAB:
        assert f'{colour} eyes' not in eye_negatives(_gate(tmp_path), colour)


def test_eye_negatives_substring_match_is_symmetric(tmp_path):
    """'dark brown' keeps 'brown eyes' out — the spec contains the vocab word."""
    assert 'brown eyes' not in eye_negatives(_gate(tmp_path), 'dark brown')


def test_eye_negatives_works_without_a_normalize_color(tmp_path):
    """An older judge module with no normaliser must not break the rung."""
    gate = _gate(tmp_path, judge=_OldJudge())
    assert not hasattr(gate.avj, 'normalize_color')
    assert eye_negatives(gate, 'blue').startswith('brown eyes, green eyes')


# ---------------------------------------------------------------- boost_tokens


def test_boost_tokens_front_loads_the_eye_colour_and_its_negatives(tmp_path):
    """The eye branch is self-contained: a positive pair plus the symmetric push."""
    gate = _gate(tmp_path)
    boost, negs = boost_tokens(gate, {'eye_color': 'brown'})
    assert boost == ['striking green eyes, vivid green irises']
    assert negs == [eye_negatives(gate, 'green')]


def test_boost_tokens_of_no_mismatch_is_empty(tmp_path):
    """Nothing wrong, nothing to boost."""
    assert boost_tokens(_gate(tmp_path), {}) == ([], [])


# ---------------------------------------------------------------- the iris rung


def test_iris_edit_prompt_keeps_the_anti_neon_wording():
    """'muted and desaturated' is load-bearing: run 1415cfdf shipped neon irises."""
    prompt = iris_edit_prompt('green')
    assert 'natural, realistic green' in prompt
    assert 'muted and desaturated' in prompt
    assert 'NOT bright, glowing or saturated' in prompt
    # and it must forbid every other kind of change
    for promise in ('do not lighten', 'the same hairstyle', 'do not zoom in or out'):
        assert promise in prompt


def test_iris_fix_kwargs_switches_to_the_qwen_edit_on_the_current_anchor(tmp_path):
    """The edit reads the delivered anchor and drops the flux-only guidance."""
    gate = _gate(tmp_path)
    kw = iris_fix_kwargs(gate, 'green')
    assert kw['force_workflow'] == 'qwen_edit_angle'
    assert kw['reference_image'] == gate.ctx.cell_path
    assert 'flux_guidance' not in kw
    assert kw['steps'] == 20, 'the rest of the run kwargs survive'
    assert isinstance(kw['seed'], int)


def test_iris_fix_kwargs_merges_both_negative_sets_into_the_run_s_own(tmp_path):
    """The run's negatives (the skin defence among them) are kept, not replaced."""
    gate = _gate(tmp_path)
    kw = iris_fix_kwargs(gate, 'green')
    neg = kw['extra_negative']
    assert neg.startswith('blurry, ')
    assert 'brown eyes' in neg
    assert 'colored contact lenses' in neg
    assert 'green eyes' not in neg


def test_iris_fix_kwargs_does_not_mutate_the_run_kwargs(tmp_path):
    """A rung that edited gen_kwargs in place would poison every later cell."""
    gate = _gate(tmp_path)
    before = dict(gate.ctx.gen_kwargs)
    iris_fix_kwargs(gate, 'green')
    assert gate.ctx.gen_kwargs == before


# ---------------------------------------------------------------- clear_scratch


def test_clear_scratch_removes_both_anchors_and_tolerates_a_missing_one(tmp_path):
    """The gate's two scratch copies go; an already-gone one is not an error."""
    gate = _gate(tmp_path)
    with open(gate.pregate_anchor, 'w', encoding='utf-8') as fh:
        fh.write('PREGATE')
    clear_scratch(gate)
    assert not os.path.exists(gate.best_anchor)
    assert not os.path.exists(gate.pregate_anchor)
    assert os.path.isfile(gate.ctx.cell_path), 'the anchor itself is untouched'
