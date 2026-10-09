#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The SCENE PLATE SET dropdown — one option that drives VACE from a Blender shot.

Same discipline as test_movement_studio.py: no inert levers. Choosing a scene has
to reach SEVEN real arguments at once — control_dir=, mask_path=, num_frames,
width, height, the still, and two per-job environment switches — and the whole
value of the dropdown is that it is impossible to get six of the seven right and
quietly render a still instead of a shot. Every one of them is followed here from
the dial state to the argument a render would receive.

The other half of the contract is that 'none' changes NOTHING: the kwargs dicts
are compared whole against the pre-feature ones, not spot-checked.

Run:  .venv-test/bin/python -m pytest tests/test_scene_plateset.py -q
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

from zyg_workflows import movement_studio as MS  # noqa: E402

FRAMES, W, H = 49, 832, 480


@pytest.fixture
def plates(tmp_path, monkeypatch):
    """A minimal but REAL scene_plates export: the plateset.json scene_plates.py
    writes (schema zyg.plateset/1), one ctrl frame, one mask frame, one still.

    The option list is frozen into RACKS at import, and sanitize() checks select
    membership against that frozen list, so the temp directory is patched into
    the spec's own options — patching only _plateset_options would leave
    sanitize() rejecting the value and the test would pass on a default."""
    d = tmp_path / 'shot_x' / 'plates'
    d.mkdir(parents=True)
    (d / 'plateset.json').write_text(
        json.dumps(
            {
                'schema': 'zyg.plateset/1',
                'shot': 'shot_x',
                'frames': FRAMES,
                'fps': 24,
                'width': W,
                'height': H,
                'ctrl': 'ctrl_%05d.png',
                'mask': 'm_%05d.png',
                'still': 'still.png',
            }
        ),
        encoding='utf-8',
    )
    (d / 'ctrl_00001.png').write_bytes(b'x')
    (d / 'm_00001.png').write_bytes(b'x')
    (d / 'still.png').write_bytes(b'x')

    opts = [{'v': 'none', 'l': 'none — render from the still'}, {'v': str(d), 'l': 'shot_x'}]
    monkeypatch.setattr(MS, '_plateset_options', lambda: list(opts))
    monkeypatch.setitem(MS._PARAMS['scene_plateset'], 'options', opts)
    return str(d)


def fake_generate(still_path, prompt, out_dir, control_dir=None, mask_path=None, **kw):
    """Stands in for the installed generate_vace_static_clip — control_kwargs
    introspects this signature and refuses a control folder a build cannot take."""
    return None


# ── the key exists and survives sanitize ───────────────────────────────────
def test_scene_plateset_is_in_the_spec():
    assert 'scene_plateset' in MS.defaults()
    assert MS.defaults()['scene_plateset'] == 'none'


def test_it_is_the_first_param_of_the_control_path_rack():
    rack = next(r for r in MS.RACKS if r['id'] == 'ctrlpath')
    assert [p['key'] for p in rack['params']][0] == 'scene_plateset'


def test_options_are_the_shots_actually_exported():
    """Same rule as _lora_options: what is on disk, never a placeholder."""
    vals = [o['v'] for o in MS._plateset_options()]
    assert vals[0] == 'none'
    for v in vals[1:]:
        assert os.path.isfile(os.path.join(v, 'plateset.json'))


def test_an_unknown_scene_falls_back_to_none():
    assert MS.sanitize({'scene_plateset': '/no/such/shot'})['scene_plateset'] == 'none'


# ── the seven arguments ────────────────────────────────────────────────────
def test_control_dir_and_mask_path_are_the_plates_directory(plates):
    out = MS.control_kwargs({'scene_plateset': plates}, generate_fn=fake_generate)
    assert out == {'control_dir': plates, 'mask_path': plates}


def test_frame_count_and_resolution_come_from_plateset_json(plates):
    kw = MS.render_kwargs({'scene_plateset': plates})
    assert kw['num_frames'] == FRAMES
    assert (kw['width'], kw['height']) == (W, H)
    # ...and not from the Engine rack, whose defaults differ on all three
    d = MS.defaults()
    assert int(d['num_frames']) != FRAMES or d['resolution'] != f'{W}x{H}'


@pytest.mark.parametrize('frames,want', [(49, 49), (50, 49), (52, 49), (53, 53)])
def test_the_frame_count_is_truncated_down_to_4n_plus_1(plates, frames, want):
    """4n+1 or WanVideoVACEEncode silently truncates — and truncating DOWN is the
    only safe direction here: a count above the plate count would pad the tail of
    the shot with a repeat of its last frame."""
    ps = os.path.join(plates, 'plateset.json')
    d = json.load(open(ps, encoding='utf-8'))
    d['frames'] = frames
    json.dump(d, open(ps, 'w', encoding='utf-8'))
    assert MS.render_kwargs({'scene_plateset': plates})['num_frames'] == want


def test_the_still_is_the_shot_s_own_beauty_frame(plates):
    assert MS.still_for({'scene_plateset': plates}, '/canon/portrait.png') == os.path.join(plates, 'still.png')


def test_a_scene_without_a_still_keeps_the_subject_s(plates):
    os.remove(os.path.join(plates, 'still.png'))
    assert MS.still_for({'scene_plateset': plates}, '/canon/portrait.png') == '/canon/portrait.png'


def test_the_two_env_switches_are_set_and_restorable(plates):
    env = MS.env_overrides({'scene_plateset': plates})
    assert env['ZYG_VACE_MASK_SEQ'] == '1'
    assert env['ZYG_VACE_CTRL_BLEND'] == 'raw'
    # bp_movement._env_scope only saves/restores what is in _ENV_KEYS
    assert 'ZYG_VACE_CTRL_BLEND' in MS._ENV_KEYS
    assert 'ZYG_VACE_MASK_SEQ' in MS._ENV_KEYS


# ── precedence and refusals ────────────────────────────────────────────────
def test_an_explicit_control_folder_wins_over_the_scene(tmp_path, plates):
    typed = tmp_path / 'typed'
    typed.mkdir()
    (typed / 'f0001.png').write_bytes(b'x')
    out = MS.control_kwargs({'scene_plateset': plates, 'control_dir': str(typed)}, generate_fn=fake_generate)
    assert out['control_dir'] == str(typed)
    assert out['mask_path'] == plates  # the scene still supplies the masks


def test_a_probe_frame_count_wins_over_the_scene_s(plates):
    assert MS.render_kwargs({'scene_plateset': plates}, num_frames_override=17)['num_frames'] == 17


def test_a_scene_deleted_since_the_options_were_built_is_simply_off(plates):
    os.remove(os.path.join(plates, 'plateset.json'))
    p = {'scene_plateset': plates}
    assert MS.plateset_dir(p) == '' and MS.plateset_meta(p) == {}
    assert MS.control_kwargs(p, generate_fn=fake_generate) == {}
    assert MS.env_overrides(p)['ZYG_VACE_CTRL_BLEND'] == ''


def test_a_build_without_control_dir_refuses_the_scene_too(plates):
    """The same loud failure a typed folder gets: a scene render that quietly
    falls back to the still is a clip that looks driven and is not."""

    def old_build(still_path, prompt, out_dir, num_frames=65):
        return None

    with pytest.raises(ValueError, match='S01'):
        MS.control_kwargs({'scene_plateset': plates}, generate_fn=old_build)


# ── 'none' is byte-identical to the pre-feature behaviour ──────────────────
def test_none_changes_nothing(plates):
    """Whole-dict comparison, not a spot check: the scene rack must be invisible
    to every render that did not ask for it."""
    off = {'scene_plateset': 'none'}
    assert MS.render_kwargs(off) == MS.render_kwargs({})
    assert MS.control_kwargs(off, generate_fn=fake_generate) == {}
    assert MS.env_overrides(off) == MS.env_overrides({})
    assert MS.env_overrides(off)['ZYG_VACE_CTRL_BLEND'] == ''
    assert MS.still_for(off, '/canon/portrait.png') == '/canon/portrait.png'


# ── the whole call, against a fake renderer ────────────────────────────────
def test_a_fake_render_receives_the_scene(plates):
    seen = {}

    def generate(still_path, prompt, out_dir, control_dir=None, mask_path=None, **kw):
        seen.update(still=still_path, control_dir=control_dir, mask_path=mask_path, kw=kw)
        return 'clip.mp4'

    params = {'scene_plateset': plates}
    kw = MS.render_kwargs(params, still_path='/canon/portrait.png')
    kw.update(MS.control_kwargs(params, generate_fn=generate))
    generate(MS.still_for(params, '/canon/portrait.png'), 'walks forward', '/tmp', **kw)

    assert seen['control_dir'] == plates
    assert seen['mask_path'] == plates
    assert seen['still'] == os.path.join(plates, 'still.png')
    assert seen['kw']['num_frames'] == FRAMES
    assert (seen['kw']['width'], seen['kw']['height']) == (W, H)
    # the dropdown itself must not leak into the sampler kwargs
    assert 'scene_plateset' not in seen['kw']


def test_every_emitted_key_is_still_on_the_real_signature(plates):
    """render_kwargs + control_kwargs together must remain a legal call."""
    import inspect
    from zyg_workflows import wan_vace_service as V

    sig = set(inspect.signature(V.generate_vace_static_clip).parameters)
    params = {'scene_plateset': plates}
    emitted = set(MS.render_kwargs(params)) | set(MS.control_kwargs(params, generate_fn=V.generate_vace_static_clip))
    assert emitted <= sig, f'not on the render signature: {sorted(emitted - sig)}'
