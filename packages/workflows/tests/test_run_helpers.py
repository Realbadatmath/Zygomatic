# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Movement Studio anatomy proof's stage helpers, unit by unit.

``check_movement_anatomy.run`` used to be one 772-line function that could only
be exercised by launching Chrome against a live studio tab. Its stages now live
in ``run_skeleton`` and ``run_ecorche`` and take the Playwright page as an
argument, so a recording stub drives them: every assertion the proof makes is
tested here against a passing probe and against the failure it was written for.
No browser, no GPU, no network.
"""

import pytest

from zyg_workflows.tools.studio_verify.check_movement_anatomy import constants as K
from zyg_workflows.tools.studio_verify.check_movement_anatomy import run_ecorche as EC
from zyg_workflows.tools.studio_verify.check_movement_anatomy import run_skeleton as SK


class StubPage:
    """A recording fake page: ``evaluate`` answers from *answers*, in order."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls = []
        self.handlers = {}

    def evaluate(self, js, arg=None):
        self.calls.append(('evaluate', js, arg))
        return self.answers.pop(0)

    def wait_for_timeout(self, ms):
        self.calls.append(('wait', ms))

    def click(self, sel):
        self.calls.append(('click', sel))

    def hover(self, sel):
        self.calls.append(('hover', sel))

    def goto(self, url, wait_until=None, timeout=None):
        self.calls.append(('goto', url, wait_until, timeout))

    def on(self, event, fn):
        self.calls.append(('on', event))
        self.handlers[event] = fn

    def screenshot(self, path=None, clip=None):
        self.calls.append(('screenshot', path, clip))

    def evaluated(self):
        """The JavaScript sources passed to ``evaluate``, in call order."""
        return [c[1] for c in self.calls if c[0] == 'evaluate']


def a_hand(**kw):
    """A FINGERS row for a relaxed hand measured at 0.19 m."""
    fh = {
        'near': 20,
        'len': 0.19,
        'lag': 1e-06,
        'index': 0.17,
        'middle': 0.18,
        'ring': 0.16,
        'little': 0.15,
        'thumb': 0.12,
    }
    fh.update(kw)
    return fh


def a_body(**kw):
    """A PROBE row for a solved 1.8 m actor on the 31-channel rig."""
    st = {
        'ready': True,
        'why': '',
        'actor': 'actor_42',
        'base': 'base_body_7',
        'meta': {'name': 'cmu_mb'},
        'rig': K.RIG_CHANNELS,
        'counts': {'joint': 204, 'link': 161, 'bone': K.SKEL_PIECES, 'muscle': 1},
        'on': {'bone': True, 'joint': True, 'muscle': True},
        'splitSide': True,
        'ms': 812.0,
        'vert': 24518,
        'stature': 1.8,
        'ankleIn': True,
        'hand': {'len': 0.19, 'width': 0.09, 'thick': 0.03},
        'foot': {'len': 0.25, 'width': 0.1},
        'torso': 26,
    }
    st.update(kw)
    return st


def a_column(**kw):
    """A COLUMN row: 30 levels, coccyx to C1, every joint on the rig."""
    names = ['Co'] + ['S%d' % i for i in range(5, 0, -1)] + ['L%d' % i for i in range(5, 0, -1)]
    names += ['T%d' % i for i in range(12, 0, -1)] + ['C%d' % i for i in range(7, 0, -1)]
    struct = {
        'levels': 30,
        'names': names,
        'mono': True,
        'lo': 0.91,
        'hi': 1.62,
        'total': 204,
        'worst': 0.1,
        'at': [0.1, 1.2, 0.0],
        'stature': 1.8,
    }
    struct.update(kw)
    return struct


def a_skeleton(**kw):
    """A SKEL row for the GLB's own skeleton on the body's own rig."""
    sk = {
        'found': True,
        'name': 'skeleton',
        'isSkinnedMesh': True,
        'layer': 'bone',
        'vertices': 61234,
        'tris': 30617.0,
        'bones': K.RIG_CHANNELS,
        'sameRigAsSkin': True,
        'skinName': 'body_skin',
        'skinVisible': True,
        'skinSideU': -1,
        'visible': True,
        'renderOrder': 5,
        'frustumCulled': False,
        'castShadow': False,
        'colour': '#e8e2d4',
        'roughness': 0.42,
        'hasSide': True,
        'sideHist': {'0': 25000, '1': 25000, '3': 11234},
        'sideU': -1,
    }
    sk.update(kw)
    return sk


def an_ecorche(**kw):
    """An EC_PROBE row: the body geometry wearing the 8192x4096 atlas."""
    p = {
        'isSkinned': True,
        'name': 'ecorche',
        'layer': 'muscle',
        'sameSkeleton': True,
        'sibling': True,
        'renderOrder': 3,
        'frustumCulled': False,
        'bindMode': 'attached',
        'bodyBindMode': 'attached',
        'verts': 24518,
        'bodyVerts': 24518,
        'aSide': 24518,
        'uvAtlas': '8192x4096',
        'uvMiss': 0,
        'bodyUvAtlas': '',
        'mapW': 8192,
        'mapH': 4096,
        'bumpW': 8192,
        'bumpScale': 0.3,
        'roughness': 0.6,
        'ecName': 'ecorche_v3',
        'ecSize': '8192x4096',
        'ecNote': '',
        'countsMuscle': 1,
        'ms': 812.0,
    }
    p.update(kw)
    return p


def halves(mus=1, **over):
    """A (4c) rows table: the écorché on the muscle half, the skeleton on the other."""
    rows = {
        'halfbare': {
            'ec': {'v': 1, 'vis': True},
            'skel': {'v': 0, 'vis': True},
            'skin': {'v': 0, 'vis': False},
            'mus': mus,
        },
        'halfskin': {
            'ec': {'v': 1, 'vis': True},
            'skel': {'v': 0, 'vis': True},
            'skin': {'v': 0, 'vis': True},
            'mus': mus,
        },
        'skin': {
            'ec': {'v': 1, 'vis': False},
            'skel': {'v': -1, 'vis': True},
            'skin': {'v': -1, 'vis': True},
            'mus': 0,
        },
    }
    for view, patch in over.items():
        rows[view].update(patch)
    return rows


def held_samples(**kw):
    """A HELD row: the halves held over eight frames of a moving clip."""
    h = {
        'base': {
            'joint': 204,
            'jointH': 12,
            'link': 161,
            'skelSide': 0,
            'ecSide': 1,
            'skelSideAttr': 1,
            'ecSideAttr': 1,
            'skelSideVer': 0,
            'ecSideVer': 0,
        },
        'bad': [],
        'frames': 8,
        'moved': 0.0731,
    }
    h.update(kw)
    return h


# ── open_page: the two error channels ────────────────────────────────────


class FakeChromium:
    """Records the launch arguments and hands back a fake browser."""

    def __init__(self, page):
        self.page = page
        self.launched = None
        self.viewport = None

    def launch(self, **kw):
        self.launched = kw
        return self

    def new_context(self, **kw):
        self.viewport = kw
        return self

    def new_page(self):
        return self.page


class FakePlaywright:
    """A ``sync_playwright()`` handle whose chromium is the fake above."""

    def __init__(self, page):
        self.chromium = FakeChromium(page)


class ConsoleMessage:
    """A console message as Playwright hands it to the listener."""

    def __init__(self, type_, text):
        self.type = type_
        self.text = text


def test_open_page_launches_swiftshader_at_the_asked_for_viewport():
    pg = StubPage()
    pw = FakePlaywright(pg)
    br, got = SK.open_page(pw, 2507, 1567, [])
    assert got is pg
    assert br is pw.chromium
    assert pw.chromium.launched['executable_path'] == '/usr/bin/google-chrome'
    assert '--use-angle=swiftshader' in pw.chromium.launched['args']
    assert pw.chromium.viewport == {'viewport': {'width': 2507, 'height': 1567}}
    assert ('goto', K.URL, 'load', 120_000) in pg.calls


def test_open_page_collects_page_errors_and_only_console_errors():
    pg = StubPage()
    errs = []
    SK.open_page(FakePlaywright(pg), 100, 100, errs)
    pg.handlers['pageerror'](RuntimeError('MVA is not defined'))
    pg.handlers['console'](ConsoleMessage('error', 'WebGL: INVALID_OPERATION'))
    pg.handlers['console'](ConsoleMessage('log', 'atlas decoded'))
    assert errs == ['pageerror: MVA is not defined', 'console.error: WebGL: INVALID_OPERATION']


# ── check 1: the measured body ───────────────────────────────────────────


def test_check_measured_body_returns_the_probe_after_the_atlas_decodes():
    pg = StubPage([a_body(), {'on': True, 'why': ''}])
    st = SK.check_measured_body(pg)
    assert st['actor'] == 'actor_42'
    assert pg.evaluated() == [K.PROBE, K.EC_READY]


def test_check_measured_body_rejects_a_rig_that_is_no_longer_cmu_mb():
    pg = StubPage([a_body(rig=65)])
    with pytest.raises(AssertionError, match='not cmu_mb any more: 65'):
        SK.check_measured_body(pg)


def test_check_measured_body_rejects_a_tab_opened_without_the_three_layers():
    pg = StubPage([a_body(on={'bone': True, 'joint': True, 'muscle': False})])
    with pytest.raises(AssertionError, match='did not open with all three layers'):
        SK.check_measured_body(pg)


def test_check_measured_body_rejects_an_unmeasured_body():
    pg = StubPage([a_body(vert=12)])
    with pytest.raises(AssertionError, match='was not measured: 12 vertices'):
        SK.check_measured_body(pg)


@pytest.mark.parametrize(
    ('patch', 'msg'),
    [
        ({'stature': 250.0}, 'stature came out 250.00 m'),
        ({'hand': {'len': 1.4, 'width': 0.09, 'thick': 0.03}}, 'hand measures 1.400 m'),
        ({'hand': {'len': 0.19, 'width': 0.4, 'thick': 0.03}}, 'hand is 0.400 m across'),
        ({'foot': {'len': 0.9, 'width': 0.1}}, 'foot measures 0.900 m forward'),
        ({'ankleIn': False}, 'ankle joint is not inside its own foot'),
    ],
)
def test_check_proportions_rejects_a_measurement_no_body_has(patch, msg):
    with pytest.raises(AssertionError, match=msg):
        SK._check_proportions(a_body(**patch))


def test_check_proportions_accepts_a_body():
    assert SK._check_proportions(a_body()) is None


# ── check 2: the joint cloud and the fingers ─────────────────────────────


def test_check_counts_accepts_an_anatomical_cloud():
    assert SK._check_counts(a_body()['counts']) is None


def test_check_counts_rejects_the_rigs_own_joint_set():
    with pytest.raises(AssertionError, match='only 31 joints'):
        SK._check_counts({'joint': 31, 'link': 30, 'bone': 135, 'muscle': 1})


def test_check_counts_rejects_too_few_links():
    with pytest.raises(AssertionError, match='only 44 joint links'):
        SK._check_counts({'joint': 204, 'link': 44, 'bone': 135, 'muscle': 1})


def test_check_hand_accepts_a_relaxed_hand():
    assert SK._check_hand(0, a_hand()) is None


def test_check_hand_rejects_a_hand_that_never_solved():
    with pytest.raises(AssertionError, match='no hand solved on the right'):
        SK._check_hand(1, None)


def test_check_hand_names_the_side_it_rejected():
    with pytest.raises(AssertionError, match='the right hand is solved 0.0400 m'):
        SK._check_hand(1, a_hand(lag=0.04))


def test_check_hand_rejects_a_wrist_with_no_fingers_past_it():
    with pytest.raises(AssertionError, match='has 12 joints past the wrist; a hand has 19'):
        SK._check_hand(0, a_hand(near=12))


def test_check_hand_rejects_an_anatomy_a_frame_behind_the_actor():
    with pytest.raises(AssertionError, match='is solved 0.0400 m from its own wrist bone'):
        SK._check_hand(0, a_hand(lag=0.04))


def test_check_hand_rejects_a_middle_ray_off_the_measured_hand():
    with pytest.raises(AssertionError, match='middle finger reaches 0.120 down a hand measured at 0.190'):
        SK._check_hand(0, a_hand(middle=0.12, index=0.11, ring=0.10, little=0.09, thumb=0.05))


def test_check_hand_rejects_rays_out_of_order():
    with pytest.raises(AssertionError, match='rays are out of order'):
        SK._check_hand(0, a_hand(index=0.185))


def test_check_hand_rejects_a_ring_outside_the_middle_and_little():
    with pytest.raises(AssertionError, match='ring finger is not between the middle and the little'):
        SK._check_hand(0, a_hand(ring=0.145))


def test_check_hand_rejects_a_little_finger_of_the_wrong_length():
    with pytest.raises(AssertionError, match='little finger reaches 0.100'):
        SK._check_hand(0, a_hand(little=0.1, thumb=0.05))


def test_check_hand_rejects_a_thumb_past_the_little_finger():
    with pytest.raises(AssertionError, match='thumb reaches 0.160, past the little finger at 0.150'):
        SK._check_hand(0, a_hand(thumb=0.16))


def test_check_joint_cloud_asks_for_the_fingers_then_the_column():
    pg = StubPage([[a_hand(), a_hand()], a_column()])
    assert SK.check_joint_cloud(pg, a_body()) is None
    assert pg.evaluated() == [SK.FINGERS, SK.COLUMN]


# ── check 2b: the column ─────────────────────────────────────────────────


def test_check_column_accepts_thirty_levels_coccyx_to_c1():
    assert SK._check_column(StubPage([a_column()])) is None


def test_check_column_rejects_a_short_column():
    with pytest.raises(AssertionError, match='column has 24 levels, not 30'):
        SK._check_column(StubPage([a_column(levels=24)]))


def test_check_column_rejects_a_column_that_is_not_ordered_bottom_to_top():
    with pytest.raises(AssertionError, match='not ordered bottom to top'):
        SK._check_column(StubPage([a_column(mono=False)]))


def test_check_column_rejects_a_joint_that_left_the_skeleton():
    with pytest.raises(AssertionError, match='stands 0.900 m from the nearest rig joint on a 1.80 m'):
        SK._check_column(StubPage([a_column(worst=0.9)]))


# ── check 3: the skeleton mesh ───────────────────────────────────────────


def test_skeleton_identity_returns_the_probe_of_the_glbs_own_skeleton():
    pg = StubPage([None, a_skeleton()])
    sk = SK._skeleton_identity(pg)
    assert sk['vertices'] == 61234
    assert pg.evaluated()[1] == K.SKEL


def test_skeleton_identity_rejects_an_empty_bones_layer():
    pg = StubPage([None, {'found': False, 'note': 'no sidecar skeleton'}])
    with pytest.raises(AssertionError, match='no sidecar skeleton'):
        SK._skeleton_identity(pg)


def test_skeleton_identity_rejects_a_skeleton_skinned_to_another_rig():
    pg = StubPage([None, a_skeleton(sameRigAsSkin=False)])
    with pytest.raises(AssertionError, match='DIFFERENT set of Bone objects'):
        SK._skeleton_identity(pg)


def test_skeleton_identity_rejects_a_decimated_skeleton():
    pg = StubPage([None, a_skeleton(vertices=1200)])
    with pytest.raises(AssertionError, match='only 1200 vertices'):
        SK._skeleton_identity(pg)


def test_bones_switch_toggles_twice_then_turns_the_body_off():
    pg = StubPage(
        [
            None,
            a_skeleton(visible=False),
            None,
            a_skeleton(visible=True),
            None,
            a_skeleton(visible=True, skinVisible=False),
        ]
    )
    assert SK._bones_switch(pg) is None
    clicks = [js for js in pg.evaluated() if 'click()' in js]
    assert clicks == [
        "() => document.getElementById('mva-bone').click()",
        "() => document.getElementById('mva-bone').click()",
        "() => document.getElementById('mva-body-off').click()",
    ]


def test_bones_switch_rejects_body_off_hiding_the_layers():
    pg = StubPage(
        [
            None,
            a_skeleton(visible=False),
            None,
            a_skeleton(visible=True),
            None,
            a_skeleton(visible=False, skinVisible=False),
        ]
    )
    with pytest.raises(AssertionError, match='`body: off` hid the skeleton'):
        SK._bones_switch(pg)


def test_check_pass_counts_accepts_absent_solid_and_socket_pools():
    gfx = {'joint': 204, 'link': 161}
    assert SK._check_pass_counts({'joint': 204, 'bone': K.SKEL_PIECES}, gfx) is None


def test_check_pass_counts_rejects_a_bone_count_that_is_not_the_fitted_mesh():
    with pytest.raises(AssertionError, match='MVA.counts.bone is 97, not the 135 pieces'):
        SK._check_pass_counts({'joint': 204, 'bone': 97}, {'joint': 204})


def test_check_pass_counts_rejects_a_resurrected_solid_pool():
    with pytest.raises(AssertionError, match='solid/socket counts are 8/None'):
        SK._check_pass_counts({'joint': 204, 'bone': K.SKEL_PIECES, 'solid': 8}, {'joint': 204})


def test_check_pass_counts_rejects_a_joint_mesh_that_stopped_drawing():
    with pytest.raises(AssertionError, match='joint mesh stopped drawing: undefined'):
        SK._check_pass_counts({'joint': 204, 'bone': K.SKEL_PIECES}, {'joint': 'undefined'})


def test_check_side_histogram_accepts_the_skeleton_on_its_own_half():
    hb = a_skeleton(sideU=K.SIDE_L)
    assert SK._check_side_histogram(hb, a_body(splitSide=True)) is None


def test_check_side_histogram_follows_the_swapped_halves():
    hb = a_skeleton(sideU=K.SIDE_R)
    assert SK._check_side_histogram(hb, a_body(splitSide=False)) is None
    with pytest.raises(AssertionError, match='cut to side 1 but the skeleton half is 0'):
        SK._check_side_histogram(hb, a_body(splitSide=True))


def test_check_side_histogram_rejects_a_geometry_with_no_baked_side():
    with pytest.raises(AssertionError, match='no aSide attribute'):
        SK._check_side_histogram(a_skeleton(hasSide=False, sideU=K.SIDE_L), a_body())


def test_check_side_histogram_rejects_a_half_with_no_vertices():
    hb = a_skeleton(sideU=K.SIDE_L, sideHist={'0': 25000, '3': 11234})
    with pytest.raises(AssertionError, match=r'no right \(aSide=1\) vertices'):
        SK._check_side_histogram(hb, a_body())


def test_check_side_histogram_rejects_an_unmarked_column():
    hb = a_skeleton(sideU=K.SIDE_L, sideHist={'0': 25000, '1': 25000, '3': 12})
    with pytest.raises(AssertionError, match='only 12 axial vertices'):
        SK._check_side_histogram(hb, a_body())


def test_tick_drift_is_the_distance_between_two_samples():
    a = {'p': [0.0, 0.0, 0.0]}
    b = {'p': [0.3, 0.4, 0.0]}
    assert SK._tick_drift(a, b) == pytest.approx(0.5)
    assert SK._tick_drift(a, a) == 0.0


def test_skeleton_tick_rejects_a_rig_the_clip_is_not_driving():
    pg = StubPage([None, {'ms': 1.1, 'p': [0.0, 0.0, 0.0]}, {'ms': 1.2, 'p': [0.0, 0.0, 0.0]}])
    with pytest.raises(AssertionError, match='did not move in half a second'):
        SK._skeleton_tick(pg)


def test_skeleton_tick_rejects_a_tick_over_budget():
    pg = StubPage([None, {'ms': 1.1, 'p': [0.0, 0.0, 0.0]}, {'ms': 9.5, 'p': [0.5, 0.0, 0.0]}])
    with pytest.raises(AssertionError, match='a tick costs 9.50 ms'):
        SK._skeleton_tick(pg)


# ── check 4: the écorché ─────────────────────────────────────────────────


def test_check_ecorche_probe_accepts_the_body_wearing_the_atlas():
    assert EC._check_ecorche_probe(an_ecorche()) is None


def test_check_ecorche_probe_rejects_an_ecorche_off_the_body_geometry():
    with pytest.raises(AssertionError, match='not on the body geometry: 9000 vs 24518'):
        EC._check_ecorche_probe(an_ecorche(verts=9000))


def test_check_ecorche_probe_rejects_a_remapped_clay_body():
    with pytest.raises(AssertionError, match='CLAY body was remapped too'):
        EC._check_ecorche_probe(an_ecorche(bodyUvAtlas='8192x4096'))


def test_check_ecorche_probe_rejects_uvs_outside_the_atlas_tiles():
    with pytest.raises(AssertionError, match='17 uv pairs fell outside'):
        EC._check_ecorche_probe(an_ecorche(uvMiss=17))


def test_check_ecorche_probe_rejects_an_albedo_that_is_not_the_manifests():
    with pytest.raises(AssertionError, match='albedo is 2048x1024'):
        EC._check_ecorche_probe(an_ecorche(mapW=2048, mapH=1024))


def test_check_ecorche_probe_reports_the_pages_own_note():
    with pytest.raises(AssertionError, match='MVA.ecNote: atlas 404'):
        EC._check_ecorche_probe(an_ecorche(ecNote='atlas 404'))


def test_check_layer_halves_accepts_the_ecorche_on_the_muscle_half():
    assert EC._check_layer_halves(halves()) is None


def test_check_layer_halves_follows_a_split_that_was_not_swapped():
    rows = halves(
        mus=0,
        halfbare={'ec': {'v': 0, 'vis': True}, 'skel': {'v': 1, 'vis': True}, 'skin': {'v': 1, 'vis': False}},
        halfskin={'ec': {'v': 0, 'vis': True}, 'skel': {'v': 1, 'vis': True}, 'skin': {'v': 1, 'vis': True}},
    )
    assert EC._check_layer_halves(rows) is None


def test_check_layer_halves_rejects_the_skeleton_on_the_muscle_half():
    with pytest.raises(AssertionError, match='halfbare: the skeleton keeps side 1, not 0'):
        EC._check_layer_halves(halves(halfbare={'skel': {'v': 1, 'vis': True}}))


def test_check_layer_halves_rejects_halfbare_showing_the_skin():
    with pytest.raises(AssertionError, match='halfbare still shows the skin'):
        EC._check_layer_halves(halves(halfbare={'skin': {'v': 0, 'vis': True}}))


def test_check_layer_halves_rejects_the_skin_view_still_showing_the_ecorche():
    with pytest.raises(AssertionError, match="view 'skin' still shows the écorché"):
        EC._check_layer_halves(halves(skin={'ec': {'v': 1, 'vis': True}}))


def test_layer_halves_visits_the_three_views_in_order():
    answers = []
    for _ in range(3):
        answers += [None, {'v': 1, 'vis': True}, {'v': 0, 'vis': True}, {'v': 0, 'vis': False}, 1]
    answers[8] = {'v': 0, 'vis': True}  # halfskin shows the skin
    answers[11] = {'v': 1, 'vis': False}  # the skin view hides the écorché
    pg = StubPage(answers)
    assert EC._layer_halves(pg) is None
    want = []
    for view in ('halfbare', 'halfskin', 'skin'):
        want += [view, 'ec', 'skel', 'skin']
    assert [c[2] for c in pg.calls if c[0] == 'evaluate' and c[2]] == want


def test_check_red_accepts_a_red_figure():
    assert EC._check_red({'n': 18244, 'r': 151.2, 'g': 98.4}) is None


def test_check_red_rejects_a_figure_out_of_the_frame():
    with pytest.raises(AssertionError, match='only 40 lit pixels'):
        EC._check_red({'n': 40, 'r': 151.2, 'g': 98.4})


def test_check_red_rejects_a_grey_figure():
    with pytest.raises(AssertionError, match=r'not red: mean R 100.0, G 99.0 \(R - G = \+1.0'):
        EC._check_red({'n': 18244, 'r': 100.0, 'g': 99.0})


def test_anatomy_frame_cost_rejects_an_anatomy_over_budget():
    pg = StubPage([{'mean': 7.4, 'med': 7.1, 'max': 9.0, 'n': 40}])
    with pytest.raises(AssertionError, match='costs 7.400 ms a frame'):
        EC._anatomy_frame_cost(pg, an_ecorche())


# ── checks 5/6 to 9: what is drawn, the skin, the clip ───────────────────


def test_check_drawn_accepts_passes_that_drew_what_was_solved():
    c = {'joint': 204, 'link': 161}
    gfx = {'cap': {'joint': 4096, 'link': 4096}, 'count': {'joint': 204, 'link': 161}, 'jointH': 12}
    assert EC._check_drawn(c, gfx) is None


def test_check_drawn_rejects_a_pass_clipped_by_its_buffer():
    c = {'joint': 5000, 'link': 161}
    gfx = {'cap': {'joint': 4096, 'link': 4096}, 'count': {'joint': 4096, 'link': 161}, 'jointH': 12}
    with pytest.raises(AssertionError, match='joint clipped: solved 5000, buffer holds 4096'):
        EC._check_drawn(c, gfx)


def test_check_drawn_rejects_a_pass_that_drew_less_than_it_solved():
    c = {'joint': 204, 'link': 161}
    gfx = {'cap': {'joint': 4096, 'link': 4096}, 'count': {'joint': 204, 'link': 7}, 'jointH': 12}
    with pytest.raises(AssertionError, match='link: solved 161 but drew 7'):
        EC._check_drawn(c, gfx)


def test_skin_translucent_rejects_an_opaque_body():
    pg = StubPage([{'opacity': 1.0, 'transparent': False, 'depthWrite': True, 'visible': True}])
    with pytest.raises(AssertionError, match='body is still opaque'):
        EC._skin_translucent(pg)


def test_tracks_the_clip_rejects_a_frozen_anatomy():
    pg = StubPage([{'dt': 0.9, 'moved': 0.0001}])
    with pytest.raises(AssertionError, match='frozen while the clip plays'):
        EC._tracks_the_clip(pg, False)


def test_tracks_the_clip_shoots_only_when_asked():
    quiet = StubPage([{'dt': 0.9, 'moved': 0.05}])
    EC._tracks_the_clip(quiet, False)
    assert [c for c in quiet.calls if c[0] == 'screenshot'] == []
    shot = StubPage([{'dt': 0.9, 'moved': 0.05}])
    EC._tracks_the_clip(shot, True)
    assert ('screenshot', K.SHOT, None) in shot.calls


def test_frame_cost_rejects_a_stall():
    with pytest.raises(AssertionError, match='costs 6.2 ms — that is a stall'):
        EC._frame_cost(StubPage([6.21]))


# ── checks 10 and 10b: the view menu, and the halves holding ─────────────


def test_check_menu_accepts_a_preview_for_every_view():
    menu = {'open': True, 'thumbs': 6, 'ms': 1420, 'err': '', 'small': 0}
    assert EC._check_menu(menu, ['a', 'b', 'c', 'd', 'e', 'f']) is None


def test_check_menu_rejects_a_menu_that_did_not_open():
    menu = {'open': False, 'thumbs': 6, 'ms': 0, 'err': '', 'small': 0}
    with pytest.raises(AssertionError, match='did not open on the icon'):
        EC._check_menu(menu, ['a', 'b', 'c', 'd', 'e', 'f'])


def test_check_menu_rejects_a_missing_preview_and_names_the_pages_error():
    menu = {'open': True, 'thumbs': 4, 'ms': 900, 'err': 'thumb target lost', 'small': 0}
    with pytest.raises(AssertionError, match=r'only 4 of 6 previews were built \(thumb target lost\)'):
        EC._check_menu(menu, ['a', 'b', 'c', 'd', 'e', 'f'])


def test_check_menu_rejects_blank_previews():
    menu = {'open': True, 'thumbs': 6, 'ms': 900, 'err': '', 'small': 2}
    with pytest.raises(AssertionError, match='2 previews came back blank'):
        EC._check_menu(menu, ['a', 'b', 'c', 'd', 'e', 'f'])


def test_view_menu_previews_clicks_the_icon_and_hovers_the_first_view():
    views = ['all', 'anat', 'bones', 'skin', 'halfbare', 'halfskin']
    pg = StubPage([views, True, {'open': True, 'thumbs': 6, 'ms': 1420, 'err': '', 'small': 0}, True])
    assert EC._view_menu_previews(pg) == views
    assert ('click', '#mva-view') in pg.calls
    assert ('hover', '#mva-viewmenu .mva-vi[data-k="all"]') in pg.calls


def test_view_menu_previews_rejects_a_menu_of_fewer_than_six_views():
    pg = StubPage([['all', 'anat']])
    with pytest.raises(AssertionError, match='view menu offers 2 views'):
        EC._view_menu_previews(pg)


def test_view_menu_previews_rejects_a_hover_with_no_picture():
    views = ['all', 'anat', 'bones', 'skin', 'halfbare', 'halfskin']
    pg = StubPage([views, True, {'open': True, 'thumbs': 6, 'ms': 1420, 'err': '', 'small': 0}, False])
    with pytest.raises(AssertionError, match='hovering a view shows no preview image'):
        EC._view_menu_previews(pg)


def test_split_plane_tracks_rejects_a_menu_that_stayed_open():
    pg = StubPage([{'split': 1, 'name': 'Half bare', 'hidden': False, 'moved': 0.004}])
    with pytest.raises(AssertionError, match='did not apply it and close the menu'):
        EC._split_plane_tracks(pg)


def test_split_plane_tracks_rejects_a_plane_that_does_not_ride_the_body():
    pg = StubPage([{'split': 1, 'name': 'Half bare', 'hidden': True, 'moved': 0.0}])
    with pytest.raises(AssertionError, match='split plane does not follow the moving body'):
        EC._split_plane_tracks(pg)


def test_check_held_accepts_halves_that_held_over_eight_frames():
    assert EC._check_held(held_samples()) is None


def test_check_held_rejects_a_body_that_never_moved():
    with pytest.raises(AssertionError, match='the test would prove nothing'):
        EC._check_held(held_samples(moved=0.001))


def test_check_held_rejects_membership_that_churns_with_the_pose():
    bad = ['joint f0=204 f3=201', 'link f0=161 f3=158']
    with pytest.raises(AssertionError, match='membership is still a function'):
        EC._check_held(held_samples(bad=bad))


def test_check_held_rejects_a_replaced_aside_attribute():
    base = dict(held_samples()['base'], ecSideAttr=0)
    with pytest.raises(AssertionError, match='aSide attribute was replaced between frames'):
        EC._check_held(held_samples(base=base))


def test_custom_after_manual_toggle_leaves_the_all_view_applied():
    pg = StubPage([None, 'Custom', None])
    assert EC._custom_after_manual_toggle(pg) is None
    assert pg.evaluated()[-1] == "() => MVA.applyView('all')"


def test_custom_after_manual_toggle_rejects_an_icon_still_naming_a_preset():
    pg = StubPage([None, 'Half bare'])
    with pytest.raises(AssertionError, match='still names a preset'):
        EC._custom_after_manual_toggle(pg)


def test_shoot_hand_clips_the_shot_to_the_zoomed_rect():
    frame = {'x': 0, 'y': 0, 'width': 1670, 'height': 1040}
    pg = StubPage([None, None, frame, None])
    assert EC.shoot_hand(pg) is None
    assert ('screenshot', K.SHOT_HAND, frame) in pg.calls
    assert pg.evaluated()[0] == "() => MVA.applyView('bones')"
    assert pg.evaluated()[1] == K.BIND


# ── the stage groups keep their order and their return values ────────────


def test_check_skeleton_mesh_returns_the_identity_probe():
    pg = StubPage(
        [
            None,
            a_skeleton(),
            None,
            a_skeleton(visible=False),
            None,
            a_skeleton(visible=True),
            None,
            a_skeleton(visible=True, skinVisible=False),
            dict(dict.fromkeys(('bone', 'solid', 'socket', 'boneH', 'solidH', 'socketH'), 'undefined'), joint=204),
            {'joint': 204, 'bone': K.SKEL_PIECES},
            None,
            a_skeleton(sideU=K.SIDE_L),
            a_body(),
            None,
            a_skeleton(sideU=-1),
            None,
            {'ms': 1.1, 'p': [0.0, 0.0, 0.0]},
            {'ms': 1.2, 'p': [0.02, 0.0, 0.0]},
        ]
    )
    sk = SK.check_skeleton_mesh(pg)
    assert sk['name'] == 'skeleton'
    assert pg.answers == []


def test_check_drawn_and_tracking_returns_the_counts_the_cli_prints():
    pg = StubPage(
        [
            None,
            {'joint': 204, 'link': 161},
            {'cap': {'joint': 4096, 'link': 4096}, 'count': {'joint': 204, 'link': 161}, 'jointH': 12},
            {'opacity': 0.42, 'transparent': True, 'depthWrite': False, 'visible': True},
            {'dt': 0.9, 'moved': 0.05},
            2.54,
        ]
    )
    assert EC.check_drawn_and_tracking(pg, False) == {'joint': 204, 'link': 161}
    assert pg.answers == []


def test_check_ecorche_runs_4a_to_4e_in_order_and_returns_the_probe():
    answers = [an_ecorche()]
    # (4b) the Muscles switch: on, off, on, then `body: off`
    answers += [None, {'v': 1, 'vis': True}, None, {'v': 1, 'vis': False}]
    answers += [None, {'v': 1, 'vis': True}, None, {'v': 1, 'vis': True}]
    # (4c) the three views, each probed ec / skel / skin then MVA.splitSide
    halves_rows = []
    for _ in range(3):
        halves_rows += [None, {'v': 1, 'vis': True}, {'v': 0, 'vis': True}, {'v': 0, 'vis': False}, 1]
    halves_rows[8] = {'v': 0, 'vis': True}  # halfskin shows the skin
    halves_rows[11] = {'v': 1, 'vis': False}  # the skin view hides the écorché
    answers += halves_rows
    # (4d) the pixel probe, then (4e) the tick spread
    answers += [None, None, {'n': 9000, 'box': [0, 0, 400, 900], 'r': 160.0, 'g': 70.0, 'b': 66.0, 'redFrac': 0.82}]
    answers += [{'n': 40, 'mean': 1.2, 'med': 1.1, 'max': 2.4}]
    pg = StubPage(answers)
    assert EC.check_ecorche(pg, False) == an_ecorche()
    assert pg.answers == []
    assert pg.evaluated()[0] == K.EC_PROBE
    assert pg.evaluated()[-1] == EC.TICK_SPREAD


def test_check_view_menu_runs_10_then_10b_and_leaves_the_all_view():
    views = ['all', 'anat', 'bones', 'skin', 'halfbare', 'halfskin']
    pg = StubPage(
        [
            views,
            True,
            {'open': True, 'thumbs': 6, 'ms': 1420, 'err': '', 'small': 0},
            True,
            {'split': 1, 'name': 'Half bare', 'hidden': True, 'moved': 0.0042},
            held_samples(),
            None,
            'Custom',
            None,
        ]
    )
    assert EC.check_view_menu(pg) is None
    assert pg.answers == []
    assert pg.evaluated()[4] == EC.SPLIT
    assert pg.evaluated()[5] == EC.HELD
    assert pg.evaluated()[-1] == "() => MVA.applyView('all')"
