#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Invariants of the Movement Studio option surface — the 2026-09-02 additions.

What these guard is the thing the file's own docstring calls its discipline: no
inert levers. A dial that sanitises, appears in defaults() and is written into a
preset, but never reaches generate_vace_static_clip, looks exactly like a
working control from the GUI. Every test below follows one of the new keys all
the way to the argument a render would receive.

The two additions under test:
  PROP PLATES  -> prop_plates=[{plate, meta, quad, strength}] on the render call
  CONTROL PATH -> control_dir= / mask_path= plus ZYG_VACE_MASK_SEQ per job

Run:  .venv-test/bin/python -m pytest tests/test_movement_studio.py -q
"""

import inspect
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _HERE)

from zyg_workflows import movement_studio as MS  # noqa: E402


# ── the keys exist and clamp ────────────────────────────────────────────────
NEW_KEYS = (
    'plate_object',
    'plate_view',
    'plate_kind',
    'plate_box',
    'plate_auto',
    'plate_phrase',
    'plate_strength',
    'control_dir',
    'mask_dir',
    'driver_clip',
)


def test_new_keys_are_in_the_spec():
    d = MS.defaults()
    missing = [k for k in NEW_KEYS if k not in d]
    assert not missing, f'not in defaults(): {missing}'


def test_defaults_leave_everything_off():
    """The whole point of the default state: a render with untouched dials must
    be byte-identical to one from before these racks existed."""
    kw = MS.render_kwargs({})
    assert kw['prop_plates'] is None
    assert MS.control_kwargs({}) == {}
    assert MS.env_overrides({})['ZYG_VACE_MASK_SEQ'] == ''


def test_plate_strength_clamps_and_object_falls_back():
    p = MS.sanitize({'plate_strength': 99, 'plate_object': 'no-such-asset'})
    assert p['plate_strength'] == 1.0
    assert p['plate_object'] == 'none'  # select membership, not free text
    assert MS.sanitize({'plate_strength': -5})['plate_strength'] == 0.05


def test_plate_object_options_are_the_registry():
    vals = [o['v'] for o in MS._object_options()]
    assert vals[0] == 'none'
    from zyg_workflows import prop_mesh_library as PML

    assert set(vals[1:]) == {r['id'] for r in PML.list_assets()}


# ── the box parser refuses rather than guesses ─────────────────────────────
@pytest.mark.parametrize(
    'raw', ['', 'nonsense', '0.1,0.1', '0.1,0.1,0,0.2', '0.9,0.1,0.5,0.2', '-0.1,0.1,0.2,0.2', '0.1,0.1,0.2,1.5']
)
def test_bad_boxes_are_none(raw):
    assert MS._typed_box(raw) is None


def test_good_box_parses():
    assert MS._typed_box('0.30, 0.35, 0.28, 0.30') == (0.30, 0.35, 0.28, 0.30)


def test_object_without_a_box_leaves_the_plate_off():
    """A chosen object and no placement is the documented no-op — it must not
    become a plate at a guessed position."""
    assert MS.prop_plates({'plate_object': 'pufferball', 'plate_box': ''}) is None


# ── the plate that a real registered asset produces ────────────────────────
def _pufferball_or_skip():
    """Skip where a plate genuinely cannot be built rather than fail there.

    mesh_control imports cv2, which .venv-test does not have; the server and the
    render both run in agents/.venv, which does. So these tests are REAL in the
    venv that ships the feature and skipped in the one that cannot see it — and
    the skip is on the capability, never on the assertion."""
    if 'pufferball' not in [o['v'] for o in MS._object_options()]:
        pytest.skip('no registered asset to plate')
    try:
        from zyg_workflows import mesh_control  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:  # noqa: BLE001
        pytest.skip(f'plate deps unavailable in this interpreter: {e}')
    if MS.build_plate('pufferball', MS.resolve_view('pufferball', 'auto'), 'depth')[0] is None:
        pytest.skip('no control maps built for pufferball')


def test_plate_shape_is_what_prop_control_consumes():
    _pufferball_or_skip()
    pl = MS.prop_plates({'plate_object': 'pufferball', 'plate_box': '0.30,0.35,0.28,0.30', 'plate_strength': 0.6})
    assert pl and len(pl) == 1
    p = pl[0]
    # composite_into_control reads exactly these four; anything else is decoration
    assert set(p) == {'plate', 'meta', 'quad', 'strength'}
    assert os.path.isfile(p['plate'])
    assert p['strength'] == 0.6
    assert len(p['quad']) == 4 and all(len(q) == 2 for q in p['quad'])
    assert all(0.0 <= v <= 1.0 for q in p['quad'] for v in q)


def test_plate_meta_matches_warp_plate_s_contract():
    _pufferball_or_skip()
    p = MS.prop_plates({'plate_object': 'pufferball', 'plate_box': '0.30,0.35,0.28,0.30'})[0]
    m = p['meta']
    assert len(m['page_quad_render']) == 4  # warp_plate refuses without it
    w, h = m['size']
    assert m['page_quad_render'] == [[0, 0], [w, 0], [w, h], [0, h]]
    from PIL import Image

    im = Image.open(p['plate'])
    assert im.mode == 'RGBA', 'an opaque plate paints the render background in too'
    assert im.size == (w, h)


def test_the_quad_is_the_box_the_operator_typed():
    _pufferball_or_skip()
    p = MS.prop_plates({'plate_object': 'pufferball', 'plate_box': '0.30,0.35,0.28,0.30'})[0]
    xs = [q[0] for q in p['quad']]
    ys = [q[1] for q in p['quad']]
    assert (min(xs), max(xs)) == pytest.approx((0.30, 0.58))
    assert (min(ys), max(ys)) == pytest.approx((0.35, 0.65))


def test_unknown_view_falls_back_to_a_built_one():
    _pufferball_or_skip()
    assert MS.resolve_view('pufferball', 'not_a_view') in MS.resolve_view.__doc__ or True
    v = MS.resolve_view('pufferball', 'not_a_view')
    from zyg_workflows import mesh_control as MC

    assert v in MC.ensure('pufferball')['views']


# ── control folders ────────────────────────────────────────────────────────
def test_control_dir_needs_images(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(ValueError, match='no images'):
        MS.control_kwargs({'control_dir': str(empty)})


def test_control_dir_refuses_when_the_render_cannot_take_it(tmp_path):
    """S01 owns control_dir=. Until it exists the job must FAIL, not quietly
    render off the still and look driven."""
    d = tmp_path / 'ctrl'
    d.mkdir()
    (d / 'f0001.png').write_bytes(b'x')

    def fake_generate(still_path, prompt, out_dir, num_frames=65):
        return None

    with pytest.raises(ValueError, match='S01'):
        MS.control_kwargs({'control_dir': str(d)}, generate_fn=fake_generate)


def test_control_dir_passes_when_the_render_can_take_it(tmp_path):
    d = tmp_path / 'ctrl'
    d.mkdir()
    (d / 'f0001.png').write_bytes(b'x')

    def fake_generate(still_path, prompt, out_dir, num_frames=65, control_dir=None):
        return None

    out = MS.control_kwargs({'control_dir': str(d)}, generate_fn=fake_generate)
    assert out == {'control_dir': str(d)}


def test_mask_dir_becomes_mask_path_and_sets_the_env_flag(tmp_path):
    d = tmp_path / 'masks'
    d.mkdir()
    (d / 'm0001.png').write_bytes(b'x')
    assert MS.control_kwargs({'mask_dir': str(d)}) == {'mask_path': str(d)}
    assert MS.env_overrides({'mask_dir': str(d)})['ZYG_VACE_MASK_SEQ'] == '1'
    assert 'ZYG_VACE_MASK_SEQ' in MS._ENV_KEYS, 'must be restored after the job'


# ── the whole call, against a fake renderer ────────────────────────────────
def test_a_fake_render_receives_the_plate_and_the_folders(tmp_path):
    """The end-to-end property: the dial state arrives at the render function
    with prop_plates and control_dir in the shape the real one consumes."""
    _pufferball_or_skip()
    seen = {}
    d = tmp_path / 'ctrl'
    d.mkdir()
    (d / 'f0001.png').write_bytes(b'x')

    def fake_generate(still_path, prompt, out_dir, prop_plates=None, control_dir=None, mask_path=None, **kw):
        seen.update(prop_plates=prop_plates, control_dir=control_dir, kw=kw)
        return 'clip.mp4'

    params = {
        'plate_object': 'pufferball',
        'plate_box': '0.30,0.35,0.28,0.30',
        'plate_strength': 0.45,
        'control_dir': str(d),
    }
    kw = MS.render_kwargs(params)
    kw.update(MS.control_kwargs(params, generate_fn=fake_generate))
    fake_generate('still.png', 'walks forward', str(tmp_path), **kw)

    assert seen['control_dir'] == str(d)
    assert len(seen['prop_plates']) == 1
    assert seen['prop_plates'][0]['strength'] == 0.45
    assert os.path.isfile(seen['prop_plates'][0]['plate'])
    # and nothing the plate rack added leaked into the sampler kwargs
    assert not [k for k in seen['kw'] if k.startswith('plate_')]


def test_render_kwargs_still_matches_the_real_signature():
    """Every key render_kwargs emits must be a parameter the installed
    generate_vace_static_clip actually has — the check that would have caught a
    dial named after an argument that was renamed."""
    from zyg_workflows import wan_vace_service as V

    sig = set(inspect.signature(V.generate_vace_static_clip).parameters)
    emitted = set(MS.render_kwargs({}))
    assert emitted <= sig, f'not on the render signature: {sorted(emitted - sig)}'


def test_plate_chip_reports_the_map_it_would_use():
    _pufferball_or_skip()
    chip = MS.plate_chip({'plate_object': 'pufferball', 'plate_box': '0.3,0.3,0.3,0.3'})
    assert chip['on'] and chip['map_exists'] and os.path.isfile(chip['map'])
    assert MS.plate_chip({})['on'] is False


def test_spec_is_json_serialisable():
    json.dumps(MS.spec())
