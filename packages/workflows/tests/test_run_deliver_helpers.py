# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `stage_deliver` was split into.

`stage_deliver` was 417 lines and had never been exercised below the level of a whole
kids_music_service run, so every behaviour asserted here — the picture leg's five
refusal reasons, the three commercial blockers, the drawn-vs-generated picture licence,
the manifest's key order — is being tested in isolation for the first time.

No GPU, no network, no services: the picture leg is a stub module, the melody
measurement is a recorder, and the manifest builders are pure.
"""

import json
import os
import types

import pytest

from zyg_workflows.kids_music_service import run_deliver as RD
from zyg_workflows.kids_music_service import run_deliver_manifest as MF

# ------------------------------------------------------------------ fixture data

SF_OK = {
    'ok': True,
    'basename': 'GeneralUser.sf2',
    'licence': 'free for commercial use',
    'sha256': 'abc123',
    'reason': '',
    'attribution': 'S. Christian Collins',
}
SF_BAD = dict(SF_OK, ok=False, reason='not on the allow list')

PLAN = {
    'bpm': 108,
    'bars': 16,
    'seconds': 35.5,
    'melody': [{'n': i} for i in range(23)],
    'order': ['A', 'A', 'B', 'A'],
    'sections': [{'progression': ['I', 'V', 'vi', 'IV']}, {'progression': ['I', 'IV']}],
    'lyric_fit': {'syllables': 44},
    'seed': 4242,
    'search': {'candidates_tried': 9, 'min_score': 70, 'met_min_score': True},
    'key': {'label': 'C major'},
    'voices': {'lead': 'flute'},
}
SC = {
    'total': 81.5,
    'ok': True,
    'metric_count': 11,
    'subscores': {'shape': 9.0},
    'metrics': {'range_low': 'C4', 'range_high': 'G5'},
    'invariants': {'a': True},
    'invariants_ok': True,
    'construction': {'kind': 'search'},
    'fails': [],
    'warnings': ['tail is long'],
}
BRIEF = {
    'title': 'The Rainy Day Song',
    'theme': 'rain',
    'age_band': 'preschool',
    'mood': 'gentle',
    'mode': 'major',
    'meter': '4/4',
    'form': 'AABA',
    'tonic': 'C',
    'bpm': 108,
    'seconds': 35,
    'sung': True,
    'singer': 'child',
    'style': 'storytime',
    'shelf': 'bedtime',
    'lyrics_truncated': 2,
}


def _video_module(result):
    """A stand-in kids_video_service: run() returns `result`, or raises when it is an Exception."""
    m = types.ModuleType('zyg_workflows.kids_video_service')
    m.calls = []

    def run(plan, brief, audio, out_dir, **kw):
        m.calls.append('run')
        if isinstance(result, BaseException):
            raise result
        return result

    m.run = run
    m.release_clip = lambda **kw: m.calls.append('release_clip')
    m.release_comfy_vram = lambda **kw: m.calls.append('release_comfy_vram')
    return m


def _leg(**over):
    """The keyword set `run_video_leg` takes, defaulted to a nominal illustrated run."""
    return dict(
        dict(
            abort=lambda: False,
            brief=dict(BRIEF),
            cinematic=False,
            log_fn=lambda _m: None,
            master='/tmp/master.mp3',
            out_dir='/tmp/out',
            pick='/tmp/song.mp3',
            plan=dict(PLAN),
            should_abort=lambda: False,
            stage=lambda *a, **k: None,
        ),
        **over,
    )


# ------------------------------------------------------------------ run_video_leg


def test_the_picture_leg_returns_what_kids_video_service_returned(stub_module):
    stub_module('kids_video_service', _video_module({'ok': True, 'generation': {'generated': 4}}))
    video, want_video = RD.run_video_leg(**_leg())
    assert want_video is True
    assert video == {'ok': True, 'generation': {'generated': 4}}


def test_a_cinematic_cue_is_never_illustrated_and_says_so(stub_module):
    kv = _video_module({'ok': True})
    stub_module('kids_video_service', kv)
    video, want_video = RD.run_video_leg(**_leg(cinematic=True))
    assert want_video is False
    assert video == {'ok': False, 'reason': 'not applicable — cinematic melodies carry no pictures'}
    assert kv.calls == [], 'the cinematic path must not call the picture leg at all'


@pytest.mark.parametrize(
    'over,reason',
    [
        ({'brief': dict(BRIEF, want_video=False)}, 'not requested'),
        ({'master': None, 'pick': None}, 'no delivered audio to illustrate'),
        ({'abort': lambda: True}, 'halted by operator'),
    ],
)
def test_each_refusal_carries_its_own_reason(stub_module, over, reason):
    stub_module('kids_video_service', _video_module({'ok': True}))
    video, _ = RD.run_video_leg(**_leg(**over))
    assert video == {'ok': False, 'reason': reason}


def test_a_failed_picture_leg_releases_the_gpu_and_never_takes_the_song_down(stub_module):
    kv = _video_module(RuntimeError('comfy went away'))
    stub_module('kids_video_service', kv)
    logs = []
    video, want_video = RD.run_video_leg(**_leg(log_fn=logs.append))
    assert video['ok'] is False
    assert video['reason'] == 'RuntimeError: comfy went away'
    assert logs == ['video: leg failed — RuntimeError: comfy went away']
    # the leg died before its own teardown, so stage_deliver must free the weights
    assert kv.calls == ['run', 'release_clip', 'release_comfy_vram']


def test_a_failing_release_is_swallowed_so_the_manifest_still_ships(stub_module):
    kv = _video_module(RuntimeError('boom'))

    def _die(**kw):
        raise OSError('nvml is gone')

    kv.release_clip = _die
    stub_module('kids_video_service', kv)
    video, _ = RD.run_video_leg(**_leg())
    assert video['reason'] == 'RuntimeError: boom'


def test_the_reason_string_is_capped_at_200_characters(stub_module):
    stub_module('kids_video_service', _video_module(RuntimeError('x' * 500)))
    video, _ = RD.run_video_leg(**_leg())
    assert len(video['reason']) == 200


# ------------------------------------------------------------------ licence block


def test_ok_commercial_needs_a_verified_soundfont_and_audio_that_exists():
    kw = dict(
        ace_info={},
        ace_mp3=None,
        master='/tmp/master.mp3',
        pick=None,
        sampler_block=None,
        sampler_credits={},
        sampler_res={},
        sf_info=SF_OK,
        video={},
        voice={},
    )
    assert RD.build_licence_block(**kw)['ok_commercial'] is True
    assert RD.build_licence_block(**dict(kw, master=None, pick=None))['ok_commercial'] is False
    assert RD.build_licence_block(**dict(kw, sf_info=SF_BAD))['ok_commercial'] is False


def test_the_soundfont_record_reports_the_refusal_reason():
    lic = RD.build_licence_block(
        ace_info={},
        ace_mp3=None,
        master='/tmp/m.mp3',
        pick=None,
        sampler_block=None,
        sampler_credits={},
        sampler_res={},
        sf_info=SF_BAD,
        video={},
        voice={},
    )
    assert lic['soundfont']['verified'] is False
    assert lic['soundfont']['reason'] == 'not on the allow list'
    assert lic['melody'] == 'composed by kids_music_theory.py — original, no model'
    assert 'instruments' not in lic and 'generator' not in lic and 'pictures' not in lic


def test_a_sample_licence_violation_is_a_commercial_blocker():
    lic = RD.build_licence_block(
        ace_info={},
        ace_mp3=None,
        master='/tmp/m.mp3',
        pick=None,
        sampler_block={'credits': 1},
        sampler_credits={'ok': False, 'violations': ['loop pack is NC'], 'attributions': []},
        sampler_res={'voices': {}},
        sf_info=SF_OK,
        video={},
        voice={},
    )
    assert lic['ok_commercial'] is False
    assert lic['instruments']['violations'] == ['loop pack is NC']


def test_a_failed_ace_attestation_is_a_commercial_blocker():
    base = dict(
        ace_mp3='/tmp/song.mp3',
        master='/tmp/m.mp3',
        pick='/tmp/song.mp3',
        sampler_block=None,
        sampler_credits={},
        sampler_res={},
        sf_info=SF_OK,
        video={},
        voice={},
    )
    good = RD.build_licence_block(ace_info={'checkpoint': 'c.ckpt', 'licence_attestation': {'ok': True}}, **base)
    bad = RD.build_licence_block(ace_info={'checkpoint': 'c.ckpt', 'licence_attestation': {'ok': False}}, **base)
    assert good['ok_commercial'] is True
    assert good['generator']['checkpoint'] == 'c.ckpt'
    assert bad['ok_commercial'] is False


def test_an_all_drawn_video_credits_no_image_model():
    pic = RD._picture_licence({'generated': 0, 'drawn': 9, 'drawn_count': 2, 'drawn_screen': 1})
    assert pic == {
        'family': 'none — every frame drawn by kids_video_service',
        'licence': 'original work',
        'frames_drawn': 12,
    }


def test_a_generated_video_sums_both_drawing_counters():
    pic = RD._picture_licence({'generated': 12, 'drawn': 2, 'drawn_count': 1, 'drawn_screen': 3, 'reused': 4})
    assert pic['frames_generated'] == 12
    assert pic['frames_drawn'] == 6
    assert pic['frames_reused'] == 4
    assert pic['family'], 'a generated video must name the image model family'


def test_a_refused_video_leg_contributes_no_picture_record():
    lic = RD.build_licence_block(
        ace_info={},
        ace_mp3=None,
        master='/tmp/m.mp3',
        pick=None,
        sampler_block=None,
        sampler_credits={},
        sampler_res={},
        sf_info=SF_OK,
        video={'ok': False, 'reason': 'not requested'},
        voice={},
    )
    assert 'pictures' not in lic


# ------------------------------------------------------------------ LICENSE.txt


def test_the_licence_file_names_the_converted_voice_only_when_one_shipped(tmp_path):
    common = dict(out_dir=str(tmp_path), sf_info=SF_OK, ace_mp3=None, video={}, sampler_block=None)
    RD.write_licence_file(**common, voice={})
    plain = (tmp_path / 'LICENSE.txt').read_text()
    RD.write_licence_file(**common, voice={'conversion': {'shipped': True, 'model': 'nina'}})
    converted = (tmp_path / 'LICENSE.txt').read_text()
    assert 'Voice conversion' not in plain
    assert converted.startswith(plain)
    assert 'Voice conversion' in converted and '"nina"' in converted


# ------------------------------------------------------------- melody follow


def test_no_produced_take_means_no_measurement(monkeypatch):
    monkeypatch.setattr(RD, 'chroma_follow', lambda *a, **k: pytest.fail('measured with nothing to measure'))
    assert RD.measure_melody_follow(out_dir='/tmp/out', pick=None, plan=PLAN, log_fn=lambda _m: None) == {}


def test_the_follow_verdict_is_logged_in_words(monkeypatch):
    monkeypatch.setattr(RD, '_null_plans', lambda exclude_dir=None: ['n1', 'n2', 'n3'])
    monkeypatch.setattr(RD, 'chroma_follow', lambda *a, **k: {'z': 1.875, 'nulls': 3, 'followed': True})
    logs = []
    follow = RD.measure_melody_follow(out_dir='/tmp/out', pick='/tmp/song.mp3', plan=PLAN, log_fn=logs.append)
    assert follow['followed'] is True
    assert logs == ['melody: chroma z +1.88 vs a 3-song null → follows the composed tune']


def test_a_measurement_without_a_z_score_logs_nothing(monkeypatch):
    monkeypatch.setattr(RD, '_null_plans', lambda exclude_dir=None: [])
    monkeypatch.setattr(RD, 'chroma_follow', lambda *a, **k: {'z': None, 'reason': 'no nulls'})
    logs = []
    RD.measure_melody_follow(out_dir='/tmp/o', pick='/tmp/s.mp3', plan=PLAN, log_fn=logs.append)
    assert logs == []


# ------------------------------------------------------------------ prune_takes


def test_the_takes_directory_goes_unless_the_switch_says_keep(tmp_path, monkeypatch):
    takes = tmp_path / '_takes'
    takes.mkdir()
    (takes / 'take1.mp3').write_text('x')
    monkeypatch.setenv('ZYG_KIDSMUSIC_KEEP_TAKES', '1')
    RD.prune_takes(str(tmp_path))
    assert takes.is_dir(), 'ZYG_KIDSMUSIC_KEEP_TAKES=1 must keep the per-take work'
    monkeypatch.setenv('ZYG_KIDSMUSIC_KEEP_TAKES', '')
    RD.prune_takes(str(tmp_path))
    assert not takes.exists()


def test_pruning_a_run_that_kept_no_takes_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv('ZYG_KIDSMUSIC_KEEP_TAKES', raising=False)
    RD.prune_takes(str(tmp_path))


# ------------------------------------------------------------------ rel_name


def test_rel_name_is_the_basename_only_when_the_file_is_there(tmp_path):
    f = tmp_path / 'master.mp3'
    f.write_text('audio')
    assert MF.rel_name(str(f)) == 'master.mp3'
    assert MF.rel_name(str(tmp_path / 'gone.mp3')) is None
    assert MF.rel_name(None) is None
    assert MF.rel_name('') is None
    assert MF.rel_name(str(tmp_path)) is None, 'a directory is not a deliverable'


# ------------------------------------------------------------- manifest sections


def test_the_manifest_head_names_the_workflow_not_the_shelf():
    song = MF._manifest_identity(brief=BRIEF, cinematic=False, family='kidsmusic', ok=True, t0=0.0)
    cue = MF._manifest_identity(brief=BRIEF, cinematic=True, family='melody', ok=False, t0=0.0)
    assert song['kind'] == 'kidsmusic' and cue['kind'] == 'melody'
    assert song['version'] == cue['version'] == 3
    assert song['ok'] is True and cue['ok'] is False
    assert song['title'] == 'The Rainy Day Song'
    assert song['shelf'] == 'bedtime'


def test_an_unstyled_brief_never_keyerrors_on_style():
    bare = {k: v for k, v in BRIEF.items() if k not in ('style', 'shelf')}
    head = MF._manifest_identity(brief=bare, cinematic=False, family=None, ok=True, t0=0.0)
    assert head['style'] is None and head['shelf'] is None
    assert head['brief']['style'] is None
    assert head['brief']['theme'] == 'rain'


def test_a_cinematic_card_says_instrumental_rather_than_the_table_label():
    cue = MF._manifest_labels(
        brief=dict(BRIEF, age_band='cinematic', sung=False), cinematic=True, family='melody', plan=PLAN, singer={}
    )
    song = MF._manifest_labels(brief=BRIEF, cinematic=False, family='kidsmusic', plan=PLAN, singer={'label': 'Child'})
    assert cue['age_band'] == 'Instrumental'
    assert cue['singer'] == 'Instrumental'
    assert song['singer'] == 'Child'
    assert song['key'] == 'C major'
    assert '(' not in cue['age_band']


def test_the_style_label_is_looked_up_per_family_not_per_key():
    # 'storytime' is a key in BOTH tables and means different things in each
    kids = MF._manifest_labels(brief=BRIEF, cinematic=False, family='kidsmusic', plan=PLAN, singer={'label': 'C'})
    unstyled = MF._manifest_labels(
        brief={k: v for k, v in BRIEF.items() if k != 'style'},
        cinematic=False,
        family='kidsmusic',
        plan=PLAN,
        singer={'label': 'C'},
    )
    assert kids['style'] == 'Storytime'
    assert 'style' not in unstyled, 'an unstyled brief must not grow an empty style label'


def test_the_render_section_counts_sample_files_rather_than_listing_them():
    sound = MF._manifest_sound(
        gates={'master': {}},
        plan=PLAN,
        render_engine='sampler',
        sampler_fallback='',
        sampler_res={'layers': {'lead': 'flute_a'}, 'files': {'lead': ['a.wav', 'b.wav'], 'pad': None}},
        sc=SC,
    )
    assert sound['render']['files'] == {'lead': 2, 'pad': 0}
    assert sound['render']['layers'] == {'lead': 'flute_a'}
    assert sound['music']['notes'] == 23
    assert sound['music']['range'] == 'C4–G5'
    # sorted and de-duplicated: the progression set, not the per-section list
    assert sound['music']['progressions'] == ['I/IV', 'I/V/vi/IV']
    assert sound['score']['seed'] == 4242
    assert sound['score']['candidates'] == 9


def test_an_empty_voices_dict_is_recorded_as_none_not_as_an_empty_dict():
    sound = MF._manifest_sound(
        gates={},
        plan=dict(PLAN, voices={}),
        render_engine='soundfont',
        sampler_fallback='no pack',
        sampler_res={},
        sc=SC,
    )
    assert sound['render']['voices'] is None
    assert sound['render']['layers'] == {}
    assert sound['render']['fallback_reason'] == 'no pack'


def test_the_rank_note_tells_a_single_take_from_a_best_of_n():
    one = MF._manifest_produced(ace_info={}, ace_mode='auto', ace_takes=[], attempts=1, n_takes=1, picked_take=None)
    many = MF._manifest_produced(
        ace_info={}, ace_mode='a2a', ace_takes=[{'take': 1}], attempts=3, n_takes=3, picked_take=1
    )
    assert one['ace']['rank_note'] == 'single take — no ranking'
    assert 'rank_score' in many['ace']['rank_note']
    assert one['produced']['attempts'] == 1 and many['produced']['attempts'] == 3


def test_an_auto_mode_that_resolved_to_nothing_is_recorded_as_none():
    auto = MF._manifest_produced(
        ace_info={'mode': None}, ace_mode='auto', ace_takes=[], attempts=1, n_takes=1, picked_take=None
    )
    asked = MF._manifest_produced(
        ace_info={'mode': None}, ace_mode='a2a', ace_takes=[], attempts=1, n_takes=1, picked_take=None
    )
    resolved = MF._manifest_produced(
        ace_info={'mode': 'cover'}, ace_mode='a2a', ace_takes=[], attempts=1, n_takes=1, picked_take=None
    )
    assert auto['ace'] == dict(auto['ace'], mode=None, mode_requested='auto')
    # a requested mode that did not resolve still shows what was ASKED for
    assert asked['ace']['mode'] == 'a2a'
    assert resolved['ace']['mode'] == 'cover' and resolved['ace']['mode_requested'] == 'a2a'


def test_the_lead_shift_defaults_to_zero_so_an_old_record_reads_as_unshifted():
    rec = MF._manifest_produced(ace_info={}, ace_mode='auto', ace_takes=[], attempts=0, n_takes=1, picked_take=None)
    assert rec['produced']['lead_shift_st'] == 0
    assert rec['produced']['ace_tags'] == '' and rec['produced']['lyrics_head'] == []


def test_the_files_section_names_only_what_is_on_disk(tmp_path):
    for n in ('master.mp3', 'roll.svg', 'voice_report.json'):
        (tmp_path / n).write_text('x')
    files = MF._manifest_files(
        ace_mp3=None,
        master=str(tmp_path / 'master.mp3'),
        midi=str(tmp_path / 'absent.mid'),
        out_dir=str(tmp_path),
        render_mp3=None,
        voice={'stems': {'vocals': 'v.flac'}},
    )
    assert files['master'] == 'master.mp3'
    assert files['roll'] == 'roll.svg'
    assert files['midi'] is None and files['produced'] is None and files['video'] is None
    assert files['plan'] == 'song.json', 'song.json is always written, so it is a constant'
    assert files['voice_report'] == 'voice_report.json'
    assert files['stems_vocals'] == 'v.flac'
    assert files['stems_backing'] is None


def test_delivery_picks_the_mastered_file_and_keeps_the_unmastered_one_on_record(tmp_path):
    master = tmp_path / 'master.mp3'
    pick = tmp_path / 'song.mp3'
    master.write_text('m')
    pick.write_text('p')
    d = MF._manifest_delivery(
        fallback_safe=True,
        follow={'followed': False, 'z': -0.2},
        gates={'master': {'checks': {'loudnorm': {'normalization_type': 'dynamic'}}}},
        master=str(master),
        pick=str(pick),
        picked_leg='produced',
        produced_status='ok',
        trimmed_s=0.8,
        why='',
    )
    assert d['picked'] == 'master.mp3'
    assert d['mastered_from'] == 'song.mp3'
    assert d['loudnorm'] == 'dynamic'
    assert d['melody_followed'] is False
    assert d['score_render_role'] == 'deliverable'


def test_an_unmastered_run_ships_the_pick_and_calls_the_render_diagnostic(tmp_path):
    pick = tmp_path / 'song.mp3'
    pick.write_text('p')
    d = MF._manifest_delivery(
        fallback_safe=False,
        follow={},
        gates={},
        master=None,
        pick=str(pick),
        picked_leg='render',
        produced_status='failed',
        trimmed_s=0.0,
        why='master gate failed',
    )
    assert d['picked'] == 'song.mp3'
    assert d['score_render_role'] == 'diagnostic'
    assert d['loudnorm'] is None
    assert d['melody_followed'] is None
    assert d['reason'] == 'master gate failed'


def test_the_lyric_tail_records_which_model_wrote_it():
    tail = MF._manifest_lyrics(
        brief=BRIEF,
        licence={'ok_commercial': True},
        lyric_info={'model': 'claude-opus-5', 'backend': 'subscription', 'fallback_backend': ''},
        lyric_src='llm',
    )
    assert tail['lyrics_model'] == 'claude-opus-5'
    assert tail['lyrics_backend_fallback'] is False
    assert tail['lyrics_truncated'] == 2
    assert tail['licence'] == {'ok_commercial': True}
    fallen = MF._manifest_lyrics(
        brief={}, licence={}, lyric_info={'fallback_backend': 'ollama', 'reason': 'weekly limit'}, lyric_src='template'
    )
    assert fallen['lyrics_backend_fallback'] is True
    assert fallen['lyrics_fallback_reason'] == 'weekly limit'
    assert fallen['lyrics_model'] == '' and fallen['lyrics_truncated'] == 0


# ------------------------------------------------------------------ build_manifest


def _manifest(tmp_path, **over):
    """A whole manifest for a nominal run, so the assembled key order can be asserted."""
    return MF.build_manifest(
        **dict(
            dict(
                ace_info={'checkpoint': 'c.ckpt'},
                ace_mode='a2a',
                ace_mp3=None,
                ace_takes=[],
                attempts=1,
                brief=BRIEF,
                cinematic=False,
                fallback_safe=True,
                family='kidsmusic',
                follow={'followed': True},
                gates={'master': {}},
                licence={'ok_commercial': True},
                lyric_info={'model': 'opus'},
                lyric_src='llm',
                master=None,
                midi=None,
                n_takes=1,
                ok=True,
                out_dir=str(tmp_path),
                pick=None,
                picked_leg='render',
                picked_take=None,
                plan=PLAN,
                produced_status='ok',
                render_engine='sampler',
                render_mp3=None,
                sampler_fallback='',
                sampler_res={},
                sc=SC,
                singer={'label': 'Child'},
                t0=0.0,
                trimmed_s=0.0,
                video={'ok': False, 'reason': 'not requested'},
                voice={'review': {'ok': True}, '_scratch': 'hidden'},
                why='',
            ),
            **over,
        )
    )


def test_the_manifest_key_order_is_the_published_shape(tmp_path):
    assert list(_manifest(tmp_path)) == [
        'kind',
        'version',
        'ok',
        'created',
        'elapsed_s',
        'title',
        'family',
        'style',
        'shelf',
        'brief',
        'labels',
        'render',
        'music',
        'score',
        'gates',
        'produced',
        'ace',
        'files',
        'voice',
        'video',
        'delivery',
        'lyrics_source',
        'lyrics_model',
        'lyrics_backend',
        'lyrics_backend_fallback',
        'lyrics_fallback_reason',
        'lyrics_keys_seen',
        'lyrics_truncated',
        'licence',
    ]


def test_the_underscore_keys_of_the_voice_leg_stay_out_of_the_manifest(tmp_path):
    assert _manifest(tmp_path)['voice'] == {'review': {'ok': True}}
    assert _manifest(tmp_path, voice={})['voice'] is None, 'no voice leg is None, not an empty dict'


def test_the_whole_manifest_round_trips_through_json(tmp_path):
    m = _manifest(tmp_path)
    assert json.loads(json.dumps(m, indent=1)) == m


def test_the_manifest_is_assembled_from_the_same_sections_it_publishes(tmp_path):
    m = _manifest(tmp_path)
    assert m['labels'] == MF._manifest_labels(
        brief=BRIEF, cinematic=False, family='kidsmusic', plan=PLAN, singer={'label': 'Child'}
    )
    assert m['files'] == MF._manifest_files(
        ace_mp3=None,
        master=None,
        midi=None,
        out_dir=str(tmp_path),
        render_mp3=None,
        voice={'review': {'ok': True}, '_scratch': 'hidden'},
    )


# ------------------------------------------------------------------ orchestration


def test_stage_deliver_writes_both_files_and_returns_the_manifest_it_wrote(tmp_path, monkeypatch, stub_module):
    stub_module('kids_video_service', _video_module({'ok': True, 'generation': {'generated': 3, 'drawn': 1}}))
    monkeypatch.setattr(RD, '_null_plans', lambda exclude_dir=None: ['n1'])
    monkeypatch.setattr(RD, 'chroma_follow', lambda *a, **k: {'z': 2.0, 'nulls': 1, 'followed': True})
    monkeypatch.delenv('ZYG_KIDSMUSIC_KEEP_TAKES', raising=False)
    master = tmp_path / 'master.mp3'
    master.write_text('m')
    (tmp_path / '_takes').mkdir()
    logs = []

    manifest, ok, video, want_video, why = RD.stage_deliver(
        abort=lambda: False,
        ace_info={'checkpoint': 'c.ckpt'},
        ace_mode='auto',
        ace_mp3=None,
        ace_takes=[],
        attempts=1,
        brief=dict(BRIEF),
        cinematic=False,
        fallback_safe=True,
        family='kidsmusic',
        gates={'master': {}},
        log_fn=logs.append,
        lyric_info={'model': 'opus'},
        lyric_src='llm',
        master=str(master),
        midi=None,
        n_takes=1,
        out_dir=str(tmp_path),
        pick=str(master),
        picked_leg='render',
        picked_take=None,
        plan=dict(PLAN),
        produced_status='ok',
        render_engine='soundfont',
        render_mp3=None,
        sampler_credits={},
        sampler_fallback='',
        sampler_res={},
        sc=dict(SC),
        sf_info=dict(SF_OK),
        should_abort=lambda: False,
        singer={'label': 'Child'},
        stage=lambda *a, **k: None,
        t0=0.0,
        trimmed_s=0.0,
        voice={},
        why='',
    )
    assert ok is True and want_video is True and why == ''
    assert video['ok'] is True
    assert os.path.isfile(tmp_path / 'LICENSE.txt')
    assert json.loads((tmp_path / 'manifest.json').read_text()) == manifest
    assert manifest['licence']['pictures']['frames_generated'] == 3
    assert manifest['delivery']['melody_followed'] is True
    assert not (tmp_path / '_takes').exists(), 'the per-take work is pruned by default'


def test_a_run_with_no_audio_is_not_ok_and_says_why(tmp_path, monkeypatch, stub_module):
    stub_module('kids_video_service', _video_module({'ok': True}))
    monkeypatch.setattr(RD, 'chroma_follow', lambda *a, **k: pytest.fail('nothing to measure'))
    monkeypatch.delenv('ZYG_KIDSMUSIC_KEEP_TAKES', raising=False)
    manifest, ok, video, _want, why = RD.stage_deliver(
        abort=lambda: False,
        ace_info={},
        ace_mode='auto',
        ace_mp3=None,
        ace_takes=[],
        attempts=0,
        brief=dict(BRIEF),
        cinematic=False,
        fallback_safe=False,
        family='kidsmusic',
        gates={},
        log_fn=lambda _m: None,
        lyric_info={},
        lyric_src='template',
        master=None,
        midi=None,
        n_takes=1,
        out_dir=str(tmp_path),
        pick=None,
        picked_leg=None,
        picked_take=None,
        plan=dict(PLAN),
        produced_status='failed',
        render_engine='soundfont',
        render_mp3=None,
        sampler_credits={},
        sampler_fallback='',
        sampler_res={},
        sc=dict(SC),
        sf_info=dict(SF_OK),
        should_abort=lambda: False,
        singer={'label': 'Child'},
        stage=lambda *a, **k: None,
        t0=0.0,
        trimmed_s=0.0,
        voice={},
        why='',
    )
    assert ok is False
    assert why == 'run produced no audio'
    assert manifest['ok'] is False
    assert manifest['delivery']['reason'] == 'run produced no audio'
    assert video == {'ok': False, 'reason': 'no delivered audio to illustrate'}
    # a verified soundfont cannot make a silent run commercially clear
    assert manifest['licence']['ok_commercial'] is False
