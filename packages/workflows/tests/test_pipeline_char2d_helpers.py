#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The helpers `pipeline_char2d.run_char2d` was split into.

    scripts/run_tests.sh tests/test_pipeline_char2d_helpers.py

Until 2026-10-09 all of this was inline in one 419-line function, so the only
way to reach the hand gate's three verdicts or the demo reel's concat graph was
a full five-minute Blender run. These tests drive the pure helpers with plain
dicts: no Blender, no ffmpeg, no MediaPipe, nothing written outside tmp_path.
"""

import os

import pytest

from zyg_workflows import pipeline_char2d as C
from zyg_workflows import pipeline_char2d_stages as S


def _view(yaw, file, mouth_w=12.0):
    """One views.json entry, with the five measured anchors the stage reads."""
    return {
        'yaw': yaw,
        'file': file,
        'mouth_px': [512, 300],
        'mouth_w_px': mouth_w,
        'chin_px': [512, 340],
        'head_top_px': [512, 140],
    }


def _frame(gesture, n, view, tags=(), ok=False):
    """One hand-gate frame row as `run_hand_gate` builds it."""
    return {
        'gesture': gesture,
        'key': n,
        'key_name': 'k%d' % n,
        'view': view,
        'file': 'gestures/%s/%d_%s.png' % (gesture, n, view),
        'ok': ok,
        'detected': 2,
        'issues': [{'tag': t, 'severity': 'hard'} for t in tags],
    }


# ── 6. Mouth Anchors ─────────────────────────────────────────────────────────


def test_collect_anchors_classifies_each_view_and_keeps_its_anchors():
    """Every view gets its kind from the yaw and its anchors verbatim."""
    anchors = S.collect_anchors({'front': _view(0.0, 'views/front.png'), 'back': _view(180.0, 'views/back.png')})
    assert set(anchors) == {'front', 'back'}
    assert anchors['front']['kind'] == 'front'
    assert anchors['back']['kind'] == 'back'
    assert anchors['front']['mouth_px'] == [512, 300]
    assert anchors['front']['chin_px'] == [512, 340]
    assert anchors['front']['file'] == 'views/front.png'


def test_collect_anchors_rounds_the_effective_mouth_width_to_two_places():
    """The drawn wedge needs a scale, and sprites.json carries it at 2 dp."""
    anchors = S.collect_anchors({'front': _view(0.0, 'f.png', mouth_w=12.3456)})
    assert anchors['front']['effective_mouth_w_px'] == 12.35
    assert anchors['front']['mouth_w_px'] == 12.3456


def test_collect_anchors_derives_a_scale_for_an_edge_on_profile():
    """A profile reports a ~0 mouth width, so the width comes off the head height."""
    anchors = S.collect_anchors({'profileL': _view(90.0, 'p.png', mouth_w=0.8)})
    assert anchors['profileL']['kind'] == 'profile'
    assert anchors['profileL']['effective_mouth_w_px'] >= 8.0


def test_anchors_line_names_every_view_with_its_kind_and_width():
    """The log line the card shows for stage 6."""
    line = S.anchors_line(S.collect_anchors({'front': _view(0.0, 'f.png')}))
    assert line == 'anchors: front front/12.0px'


# ── 8. Lip-Sync Timing ───────────────────────────────────────────────────────


def test_resolve_wav_takes_an_absolute_option_as_given(tmp_path):
    """An absolute path that exists is used untouched."""
    wav = tmp_path / 'line.wav'
    wav.write_bytes(b'RIFF')
    assert S.resolve_wav({'wav': str(wav)}) == str(wav)


def test_resolve_wav_resolves_a_relative_option_against_the_package():
    """A relative option is taken against the package dir, not the cwd."""
    with pytest.raises(RuntimeError) as exc:
        S.resolve_wav({'wav': 'output/nowhere/missing.wav'})
    assert os.path.join(C._HERE, 'output', 'nowhere', 'missing.wav') in str(exc.value)


def test_resolve_wav_refuses_a_missing_file():
    """A talking clip with no audio is not a clip — fail the run, do not guess."""
    with pytest.raises(RuntimeError, match='lip-sync WAV not found'):
        S.resolve_wav({'wav': '/nonexistent/line.wav'})


def test_resolve_wav_falls_back_to_the_house_default():
    """No option means the house default, whether or not it is on this machine."""
    if os.path.isfile(C.DEFAULT_WAV):
        assert S.resolve_wav({}) == C.DEFAULT_WAV
    else:
        with pytest.raises(RuntimeError, match='lip-sync WAV not found'):
            S.resolve_wav({})


def test_timing_line_reports_the_cadence():
    """The log line the card shows for stage 8."""
    timing = {'duration_s': 6.25, 'n_frames': 150, 'changes': 8, 'changes_per_s': 1.28, 'min_run_frames': 6}
    assert S.timing_line(timing) == 'timing: 6.25 s, 150 frames, 8 changes (1.28/s), min run 6'


# ── 11. Hand Anatomy Gate ────────────────────────────────────────────────────


def test_a_clean_gate_ships_clean():
    """Nothing flagged, nothing hard: the verdict is clean and nothing else is set."""
    gate = {'frames': [], 'flagged': [], 'hard': [], 'unknown': 3, 'n_frames': 30}
    updates, lines = S.gate_verdict(gate)
    assert updates == {'hand_gate': 'clean'}
    assert lines == ['hand gate: clean over 30 frames (3 unverifiable)']


def test_a_flagged_gate_ships_degraded():
    """A soft issue degrades the delivery: no error, but the frames are named."""
    row = _frame('point', 2, 'front45L', tags=('chirality-ambiguous',))
    gate = {'frames': [row], 'flagged': [row], 'hard': [], 'unknown': 0, 'n_frames': 1}
    updates, lines = S.gate_verdict(gate)
    assert updates['hand_gate'] == 'flagged'
    assert 'hand_gate_error' not in updates
    assert updates['hand_gate_frames'] == ['point k2 front45L: chirality-ambiguous']
    assert lines == ['hand gate: FLAGGED — 1 of 1 frames (chirality-ambiguous); sprites ship degraded']


def test_a_hard_tag_fails_the_run_but_still_names_the_evidence():
    """A broken hand ends the job red — and says exactly which frames, so it can be seen."""
    row = _frame('wave', 1, 'front', tags=('fused-fingers',))
    gate = {'frames': [row], 'flagged': [row], 'hard': [dict(row, tag='fused-fingers')], 'unknown': 0, 'n_frames': 4}
    updates, lines = S.gate_verdict(gate)
    assert updates['hand_gate'] == 'failed'
    assert updates['hand_gate_error'].startswith('hand anatomy gate: 1 frame(s) carry a hard tag (fused-fingers)')
    assert 'wave k1 front' in updates['hand_gate_error']
    assert updates['hand_gate_frames'] == ['wave k1 front: fused-fingers']
    assert lines[0].startswith('hand gate: FAILED — 1 of 4 frames carry fused-fingers')


def test_a_hard_tag_outranks_a_flag():
    """Hard and flagged together is 'failed': the worse verdict wins."""
    row = _frame('wave', 1, 'front', tags=('chirality-flip',))
    gate = {
        'frames': [row],
        'flagged': [row],
        'hard': [dict(row, tag='chirality-flip')],
        'unknown': 0,
        'n_frames': 1,
    }
    assert S.gate_verdict(gate)[0]['hand_gate'] == 'failed'


def test_the_hard_tags_are_deduplicated_and_sorted():
    """Two frames carrying the same tag name it once, in sorted order."""
    rows = [
        dict(_frame('a', 1, 'front', tags=('hand-count-mismatch',)), tag='hand-count-mismatch'),
        dict(_frame('b', 2, 'front', tags=('fused-fingers',)), tag='fused-fingers'),
        dict(_frame('c', 3, 'front', tags=('fused-fingers',)), tag='fused-fingers'),
    ]
    gate = {'frames': rows, 'flagged': [], 'hard': rows, 'unknown': 0, 'n_frames': 3}
    assert 'a hard tag (fused-fingers, hand-count-mismatch)' in S.gate_verdict(gate)[0]['hand_gate_error']


# ── 13. Sprite Manifest ──────────────────────────────────────────────────────


def _rendered():
    """One gesture row as `render_gesture_keyframes` returns it."""
    spec = {'name': 'wave', 'label': 'Wave', 'meaning': 'hello', 'hands': 1, 'reads_well': True}
    render = {'res': [768, 1152], 'keys': [{'n': 0, 'name': 'up', 'hold_frames': 6, 'files': {'front': '0_front.png'}}]}
    return [{'spec': spec, 'render': render}]


def test_gesture_manifest_entry_makes_every_path_relative_to_the_run():
    """sprites.json must be portable: the run directory is the only root in it."""
    item = _rendered()[0]
    entry = S.gesture_manifest_entry(
        item['spec'], item['render'], {'wave': {'front': 'gestures/wave/front.mp4'}}, '/run/gestures', '/run'
    )
    assert entry['label'] == 'Wave'
    assert entry['clips'] == {'front': 'gestures/wave/front.mp4'}
    assert entry['keys'] == [{'name': 'up', 'hold_frames': 6, 'files': {'front': 'gestures/wave/0_front.png'}}]


def test_gesture_manifest_entry_has_no_clips_when_none_encoded():
    """A gesture whose views all came out empty still appears, with no clips."""
    item = _rendered()[0]
    entry = S.gesture_manifest_entry(item['spec'], item['render'], {}, '/run/gestures', '/run')
    assert entry['clips'] == {}


def test_build_manifest_delivers_every_section_the_board_reads():
    """The whole sprites.json shape, with the licences and the gate verdict in it."""
    views = {'front': _view(0.0, 'views/front.png')}
    anchors = S.collect_anchors(views)
    gate = {'n_frames': 12, 'flagged': []}
    manifest = S.build_manifest(
        brief={'name': 'Mika'},
        views_doc={'height_m': 1.68},
        res_wh=(1024, 1536),
        views=views,
        anchors=anchors,
        turnaround='/run/turnaround.png',
        mouth_files={'front': {'closed': 'mouth/front_closed.png'}},
        wav='/elsewhere/line.wav',
        timing={'changes_per_s': 1.28},
        timing_path='/run/timing.json',
        talk_mp4='/run/talk/talk_front.mp4',
        hand_gate='clean',
        anatomy_path='/run/gestures/anatomy.json',
        gate=gate,
        rendered=_rendered(),
        clips={'wave': {'front': 'gestures/wave/front.mp4'}},
        gestures_dir='/run/gestures',
        out_dir='/run',
    )
    assert manifest['brief'] == {'name': 'Mika'}
    assert manifest['height_m'] == 1.68
    assert manifest['res'] == [1024, 1536]
    assert manifest['fps'] == C.FPS
    assert manifest['turnaround'] == 'turnaround.png'
    assert manifest['talk'] == {
        'wav': '/elsewhere/line.wav',
        'timing': 'timing.json',
        'clip': 'talk/talk_front.mp4',
        'changes_per_s': 1.28,
    }
    assert manifest['hand_gate'] == {
        'verdict': 'clean',
        'file': 'gestures/anatomy.json',
        'frames': 12,
        'flagged': 0,
    }
    assert manifest['licences'] == C.LICENCES
    assert manifest['views']['front']['mouth'] == anchors['front']
    assert list(manifest['gestures']) == ['wave']


def test_build_manifest_copies_the_brief_and_the_licences():
    """A manifest that aliased them would mutate the job's own dicts."""
    brief = {'name': 'Mika'}
    manifest = S.build_manifest(
        brief=brief,
        views_doc={},
        res_wh=(1, 1),
        views={},
        anchors={},
        turnaround='/run/t.png',
        mouth_files={},
        wav='/w.wav',
        timing={'changes_per_s': 0.0},
        timing_path='/run/t.json',
        talk_mp4='/run/talk.mp4',
        hand_gate='clean',
        anatomy_path='/run/a.json',
        gate={'n_frames': 0, 'flagged': []},
        rendered=[],
        clips={},
        gestures_dir='/run/gestures',
        out_dir='/run',
    )
    assert manifest['brief'] is not brief
    assert manifest['licences'] is not C.LICENCES


# ── 14. Demo Reel ────────────────────────────────────────────────────────────


def test_demo_reel_args_normalise_every_input_before_the_concat():
    """One filter graph takes the talking clip and the gesture clips together."""
    args = S.demo_reel_args(['/run/talk.mp4', '/run/wave.mp4'], (1024, 1536), '/run/demo.mp4')
    assert args[:4] == ['-i', '/run/talk.mp4', '-i', '/run/wave.mp4']
    graph = args[args.index('-filter_complex') + 1]
    assert '[0:v]scale=1024:1536,setsar=1,fps=%d[v0];' % C.FPS in graph
    assert '[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];' in graph
    assert graph.endswith('[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]')
    assert args[-1] == '/run/demo.mp4'


def test_demo_reel_args_map_the_concat_outputs_and_encode_both_streams():
    """The mapped labels are the concat's, not an input's — and both are re-encoded."""
    args = S.demo_reel_args(['/a.mp4'], (10, 20), '/out.mp4')
    assert args[args.index('-map') : args.index('-map') + 4] == ['-map', '[v]', '-map', '[a]']
    assert args[args.index('-c:v') + 1] == 'libx264'
    assert args[args.index('-c:a') + 1] == 'aac'


def test_demo_reel_args_handle_a_single_clip_reel():
    """A run whose gestures all failed still delivers the talking clip as the reel."""
    graph = S.demo_reel_args(['/a.mp4'], (10, 20), '/out.mp4')[2:][1]
    assert graph.endswith('[v0][a0]concat=n=1:v=1:a=1[v][a]')
