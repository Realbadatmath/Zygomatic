# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The identity-QC logic of stage 3.5, tested without a GPU for the first time.

`stage_035_image_generation` was 309 lines in one def, and the per-scene identity QC at its
tail — the gate that exists because job 10c84d83 shipped 17 wrong-character frames
undetected — lived inside it behind a FLUX render. Nothing in it had ever been exercised:
checking the no-face rule meant running a GPU job. The 2026-10-09 split gave each phase a
helper, and these tests pin the behaviours the old block promised: which renders ArcFace
must not judge, how a frame with no detectable face is counted, what reaches the pipeline
state, and that identity QC is never fatal.
"""

from __future__ import annotations

import types

import pytest

from zyg_workflows.storyteller import stage_035_image_gen as S


class FakeCtx:
    """The RunContext fields the identity-QC helpers read, with the log lines kept."""

    def __init__(self, *, char_id='char-1', animated=False, restyle=False, script=None):
        self.char_id = char_id
        self._animated_render = animated
        self._restyle_render = restyle
        self.pipeline_state = {} if script is None else {'script': script}
        self.logs = []

    def _log(self, level, stage, msg):
        self.logs.append((level, stage, msg))

    def said(self, needle):
        """True when any log line mentions needle."""
        return any(needle in m for _, _, m in self.logs)


class FakeIdqc:
    """identity_qc_service's two scoring calls: a fixed threshold and a dict-driven cosine."""

    def __init__(self, sims, threshold=0.4):
        self.sims = sims
        self.threshold = threshold

    def threshold_for(self, kind):
        assert kind == 'front'
        return self.threshold

    def cosine(self, ref, emb):
        return self.sims[emb]


def test_shot_types_lowercases_the_script_and_survives_a_broken_one():
    """The no-face rule reads shot_type off the script; an unusable script yields no shots."""
    state = {'script': [{'shot_type': 'WIDE'}, {}, None, {'shot_type': None}, {'shot_type': 'Close-Up'}]}
    assert S._shot_types(state) == ['wide', '', '', '', 'close-up']
    assert S._shot_types({}) == []
    assert S._shot_types({'script': 'not a list of scenes'}) == []


@pytest.mark.parametrize(
    ('style', 'animated', 'restyle', 'expected'),
    [
        ('photorealistic', False, False, False),
        ('photoreal cinematic', False, False, False),
        ('3d-toon', False, False, True),
        ('anime', False, False, True),
        ('cartoon', False, False, True),
        ('stylized animation', False, False, True),
        ('photorealistic', True, False, True),
        ('photorealistic', False, True, True),
    ],
)
def test_arcface_is_skipped_for_every_render_it_cannot_embed(style, animated, restyle, expected):
    """A toon/anime/animated/restyle render goes to the VLM gate; photoreal stays on ArcFace."""
    ctx = FakeCtx(animated=animated, restyle=restyle)
    assert S._is_stylized_render(ctx, style) is expected


def test_a_face_framed_frame_with_no_face_is_a_defect_and_a_wide_one_is_not():
    """Only shot types that PROMISE a visible face count as no-face defects (r3 review fix)."""
    img_paths = ['f1.png', 'f2.png', 'f3.png', 'f4.png']
    embeds = {
        'f1.png': {'embedding': 'e1'},  # close-up, on-identity
        'f2.png': {},  # close-up, no face  -> defect
        'f3.png': {'embedding': None},  # wide, no face     -> allowed
        'f4.png': {'embedding': 'e4'},  # close-up, drifted
    }
    idqc = FakeIdqc({'e1': 0.81, 'e4': 0.2})
    drifted, no_face = S._score_identity(idqc, embeds, 'ref', img_paths, ['close-up', 'close-up', 'wide', 'close-up'])
    assert no_face == [2]
    assert drifted == [(4, 0.2)]


def test_a_frame_the_script_says_nothing_about_still_counts_as_a_no_face_defect():
    """A missing shot_type must not excuse a face-free frame — the list simply runs out."""
    drifted, no_face = S._score_identity(FakeIdqc({}), {'f1.png': {}}, 'ref', ['f1.png'], [])
    assert (drifted, no_face) == ([], [1])


def test_nothing_is_scored_without_an_anchor_embedding():
    """No reference embedding means no claim either way: neither drift nor a no-face defect."""
    embeds = {'f1.png': {}, 'f2.png': {'embedding': 'e2'}}
    assert S._score_identity(FakeIdqc({'e2': 0.0}), embeds, None, ['f1.png', 'f2.png'], []) == ([], [])


def test_the_scores_reach_the_pipeline_state_the_degradation_gate_reads():
    """Both defect lists are published under the keys later stages look for, and logged."""
    ctx = FakeCtx()
    S._report_identity_scores(ctx, ['a', 'b', 'c'], [(3, 0.11)], [2])
    assert ctx.pipeline_state['_st_no_face_scenes'] == [2]
    assert ctx.pipeline_state['_st_identity_drift_scenes'] == [(3, 0.11)]
    assert ctx.said('no face detected in scene(s) [2]')
    assert ctx.said('1/3 scenes below')
    assert not ctx.said('Identity QC passed')


def test_a_clean_sheet_is_reported_as_a_pass_and_publishes_nothing():
    """With no drift and no missing face the stage says so and leaves the state untouched."""
    ctx = FakeCtx()
    S._report_identity_scores(ctx, ['a', 'b'], [], [])
    assert ctx.pipeline_state == {}
    assert ctx.said('Identity QC passed: 2 scenes match the character anchor')


def test_a_stylized_render_is_routed_to_the_vlm_gate_not_to_arcface(monkeypatch):
    """The animated/restyle branch runs the attribute gate and never touches ArcFace."""
    ctx = FakeCtx(animated=True)
    monkeypatch.setattr(S, '_qc_char_style', lambda char_id: 'photorealistic')
    monkeypatch.setattr(S, '_arcface_identity_qc', lambda *a: pytest.fail('ArcFace must not run'))
    seen = []
    monkeypatch.setattr(S, '_animated_identity_qc', lambda c, paths: seen.append(list(paths)))

    S._identity_qc(ctx, ['f1.png'])
    assert seen == [['f1.png']]


def test_a_toon_character_skips_identity_qc_and_says_why(monkeypatch):
    """A toon render is neither animated nor restyle, so it is skipped with a reason logged."""
    ctx = FakeCtx()
    monkeypatch.setattr(S, '_qc_char_style', lambda char_id: '3d-toon')
    monkeypatch.setattr(S, '_arcface_identity_qc', lambda *a: pytest.fail('ArcFace must not run'))

    S._identity_qc(ctx, ['f1.png'])
    assert ctx.said('Identity QC skipped — stylized render (ArcFace is photoreal-only)')


def test_identity_qc_is_never_fatal_and_reports_the_repr_and_traceback(monkeypatch):
    """A broken gate must not sink a finished render; the repr is logged, not str(e).

    The 11:55 run logged the useless "error: 0" because str(KeyError(0)) is just "0".
    """
    ctx = FakeCtx()

    def boom(char_id):
        raise KeyError(0)

    monkeypatch.setattr(S, '_qc_char_style', boom)
    S._identity_qc(ctx, ['f1.png'])
    assert ctx.said('Identity QC skipped (error: KeyError(0))')
    assert ctx.said('Traceback (most recent call last)')


def test_an_unavailable_identity_service_is_reported_and_nothing_is_embedded(monkeypatch, stub_module):
    """Without insightface the gate says so instead of anchoring on nothing."""
    ctx = FakeCtx()
    stub_module('identity_qc_service', types.SimpleNamespace(available=lambda: (False, 'insightface missing')))
    monkeypatch.setattr(S, '_resolve_identity_anchor', lambda c: pytest.fail('no anchor without a service'))

    S._arcface_identity_qc(ctx, ['f1.png'])
    assert ctx.said('Identity QC unavailable (insightface missing) — skipped')
