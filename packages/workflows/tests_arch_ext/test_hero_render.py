# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_hero_render.py — the photoreal hand-over picture (2026-09-16).

The assistant's preview used to be one of present()'s 800 px EEVEE JPEGs,
inlined as a data URL. It is now a CYCLES frame rendered on the GPU after the
drawing is finished, written to data/architecture/renders/ and served by URL.

Proves, on the live tower fixtures:
  (a) hero_render() renders through Blender — CYCLES, on the GPU (this machine
      has a 4090 with OptiX; a CPU fall-back is a FAIL, not a warning), at the
      size asked for, with per-pixel detail (luminance std-dev > 15) so a flat
      grey massing frame cannot pass;
  (b) the /picture route hands back bytes for a real file and refuses a path;
  (c) hero_images() is the shape the chat panel renders;
  (d) ONE real 4K pass at the default 128 samples, timed and measured — not a
      threshold, a number for the record.

2026-09-16 (the hero SET): the hand-over is four frames — hero, approach,
LOBBY, aerial. The lobby is the one camera that stands inside, so it also
proves the two things an interior needs and the exterior never did:
  * the room's own lamps are WHERE THEIR RECORDS ARE. A kind builder is handed
    only (bm, p), so the real bpy light light_lamps_env makes used to stay at
    the drawing origin while its fitting hung from the ceiling; the bpy pass
    below lists every light object's world location against its record's
    (x, -z, y) and fails over 0.05 m.
  * the interior is neither black nor blown at HERO_EV_VIEW's own stop.

VENV: "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" (PIL lives there).
"""

import json
import math
import os
import subprocess
import sys
import threading
import time
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
B = A.EXT_MODULES['blender_power']

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(HERE, 'tests_arch_ext', 'fixtures', 'live_tower_20260911.json')
# the LIVE acceptance drawing (job aba5ab20, 983 records): the only fixture with
# a furnished, lit lobby — 16 light_point records — so every interior frame and
# the lamp-transform pass are rendered on this one.
FIX16 = os.path.join(HERE, 'tests_arch_ext', 'fixtures', 'live_tower_20260916.json')


def _load(path=FIX):
    return A.Drawing(json.load(open(path, encoding='utf-8')))


def _load16():
    return _load(FIX16)


def _lum_stats(path):
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        g = im.convert('L')
        st = ImageStat.Stat(g)
        return im.size, st.mean[0], st.stddev[0]


def _ndc(cam, pts, aspect):
    """The test's own statement of the lens the render uses, so a wrong
    distance / shift / target shows up here and not only in a picture.

    Blender, sensor_fit HORIZONTAL: u spans [-1, 1] over sensor_width, v over
    sensor_width * H/W, and shift_y is given in SENSOR-WIDTH units — so it moves
    the image by 2 * shift_y * (W/H) in v. `tilt` is a pitch about the right
    axis, applied to the (depth, height) pair before the divide."""
    import math

    lx, ly, lz = [float(c) for c in cam['loc']]
    fx, fy = float(cam['target'][0]) - lx, float(cam['target'][1]) - ly
    n = math.hypot(fx, fy) or 1.0
    fx, fy = fx / n, fy / n
    f, half = float(cam['focal']), float(cam['sensor']) / 2.0
    ct, st = math.cos(float(cam['tilt'])), math.sin(float(cam['tilt']))
    sy = 2.0 * float(cam['shift_y']) * aspect
    out = []
    for px, py, pz in pts:
        dx, dy, dz = px - lx, py - ly, pz - lz
        depth, lat = dx * fx + dy * fy, dx * fy - dy * fx
        d2, z2 = depth * ct + dz * st, -depth * st + dz * ct
        out.append(((f * lat / d2) / half, (f * z2 / d2) / (half / aspect) - sy))
    return out


def _skyline(path, thresh=18.0, run=3):
    """The topmost row of the PNG that holds the building, as a fraction of the
    image height — measured on the pixels, not on the camera. The Nishita sky is
    a vertical gradient, so every row is compared with ITS OWN edge colour (the
    outer 4 % left and right, which the framing keeps clear of the envelope);
    `run` consecutive different pixels in the middle are the silhouette.
    Returns (fraction, x of the hit) or (None, None) when nothing is found."""
    from PIL import Image

    with Image.open(path) as im:
        rgb = im.convert('RGB')
        w, h = rgb.size
        px = rgb.load()
        edge = max(2, int(w * 0.04))
        for y in range(h):
            ref = [0.0, 0.0, 0.0]
            cols = list(range(edge)) + list(range(w - edge, w))
            for x in cols:
                c = px[x, y]
                for i in range(3):
                    ref[i] += c[i] / float(len(cols))
            hit = 0
            for x in range(edge, w - edge):
                c = px[x, y]
                if max(abs(c[i] - ref[i]) for i in range(3)) > thresh:
                    hit += 1
                    if hit >= run:
                        return y / float(h), x
                else:
                    hit = 0
    return None, None


def _nvidia_peak(stop, out):
    """nvidia-smi memory.used, sampled every 2 s until `stop` is set."""
    while not stop.is_set():
        try:
            r = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for ln in (r.stdout or '').splitlines():
                if ln.strip().isdigit():
                    out.append(int(ln.strip()))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('nvidia-smi poll skipped: %s: %s', type(_exc).__name__, _exc)
        stop.wait(2.0)


# ── the module's own contract ────────────────────────────────────────────────
check('cycles is an engine', 'cycles' in B.ENGINES, B.ENGINES)
check('cycles is not a tool argument', 'cycles' not in B.TOOL_ENGINES, B.TOOL_ENGINES)
check(
    'hero timeout is its own',
    B.HERO_TIMEOUT >= 900 and B.HERO_TIMEOUT != B.PASS_TIMEOUT,
    f'HERO_TIMEOUT={B.HERO_TIMEOUT} PASS_TIMEOUT={B.PASS_TIMEOUT}',
)
check('default samples 128', B.BP_CY_SAMPLES in (128, B.hero_samples()), B.BP_CY_SAMPLES)
check(
    '_second_pass takes a timeout',
    'timeout' in B._second_pass.__code__.co_varnames,
    B._second_pass.__code__.co_varnames,
)
check(
    'render dir is under data/architecture',
    B.RENDER_DIR.endswith(os.path.join('data', 'architecture', 'renders')),
    B.RENDER_DIR,
)

# (c) the payload shape the chat panel renders — no Blender needed
imgs = B.hero_images(
    [
        {'title': 'approach', 'png': '/r/j1-hero-approach.png', 'jpeg': '/r/j1-hero-approach.jpg'},
        {'title': 'aerial', 'png': '/r/j1-hero-aerial.png', 'jpeg': ''},
    ]
)
check('hero_images: two records', len(imgs) == 2, imgs)
check('hero_images: keys', all(set(i) == {'title', 'data_url', 'full'} for i in imgs), imgs)
check('hero_images: title says photoreal 4K', imgs[0]['title'] == 'photoreal 4K · approach', imgs[0])
check('hero_images: the panel loads the JPEG', imgs[0]['data_url'].endswith('picture?f=j1-hero-approach.jpg'), imgs[0])
check('hero_images: full is the PNG', imgs[0]['full'].endswith('picture?f=j1-hero-approach.png'), imgs[0])
check(
    'hero_images: no jpeg falls back to the png', imgs[1]['data_url'].endswith('picture?f=j1-hero-aerial.png'), imgs[1]
)
check('hero_images: never a data url', not any('data:' in i['data_url'] for i in imgs), imgs)

# ── the hero view: the operator's preview picture ────────────────────────────
# "a photorealistic 4K render of the building as preview picture" — the FIRST
# picture has to be the whole building, not two storeys of the entrance.
check('hero is the first hero view', B.HERO_VIEWS[0] == 'hero', B.HERO_VIEWS)
check(
    'the four hand-over views, in order', tuple(B.HERO_VIEWS) == ('hero', 'approach', 'lobby', 'aerial'), B.HERO_VIEWS
)
check('hero lens is 24 mm', B.HERO_FOCAL_MM == 24.0, B.HERO_FOCAL_MM)
check('hero is three-quarter', B.HERO_OFF_AXIS_DEG == 35.0, B.HERO_OFF_AXIS_DEG)
check('hero timeout still covers four 4K frames', B.HERO_TIMEOUT >= 900, B.HERO_TIMEOUT)
# the interior stop: a camera inside the building sees the Nishita sky only
# through the glass, so -3.0 (the exterior stop) renders it as a dark box.
check('the lobby has its own exposure', B.HERO_EV_VIEW.get('lobby') == -1.0, B.HERO_EV_VIEW)
check(
    'the interior stop is brighter than the exterior one',
    B.HERO_EV_VIEW['lobby'] > B.HERO_EV,
    (B.HERO_EV_VIEW['lobby'], B.HERO_EV),
)
check('only a view that stands inside gets one', set(B.HERO_EV_VIEW) == {'lobby'}, B.HERO_EV_VIEW)
check(
    'the render script carries the per-view stop',
    'BP_HERO_EV_VIEW' in B._FRAME,
    'BP_HERO_EV_VIEW is not in the second-pass script',
)

d = _load()
check('fixture loaded', len(d.objs) == 336, len(d.objs))
_shots, _door, ENV, _yc = B._present_shots(d, '')
AR = B.HERO_W / float(B.HERO_H)
hshot = B._hero_shot(d, ENV, _door, B._sun_hour(d), AR)
HCAM = hshot[2]
check('the hero shot is titled hero', hshot[0] == 'hero', hshot[0])
check('the hero shot has a camera', isinstance(HCAM, dict) and HCAM.get('kind') == 'hero', HCAM)

# a person standing on the ground, never a drone
_y0, _y1 = float(ENV.get('y0') or 0.0), float(ENV['y1'])
check(
    'hero stands at eye height',
    abs(float(HCAM['loc'][2]) - (float(_door.get('y') or _y0) + B.EYE_HEIGHT_M)) < 1e-6,
    f'cam z {HCAM["loc"][2]}, EYE_HEIGHT_M {B.EYE_HEIGHT_M}',
)
check(
    'hero aims near the envelope mid-height',
    abs(float(HCAM['target'][2]) - (_y0 + _y1) / 2.0) <= 0.12 * (_y1 - _y0),
    (HCAM['target'], _y0, _y1),
)
check('hero shift stays inside SHIFT_MAX', abs(float(HCAM['shift_y'])) <= B.SHIFT_MAX, HCAM['shift_y'])
check('hero needs no tilt', abs(float(HCAM['tilt'])) < 1e-9, HCAM['tilt'])
check(
    'hero stands at least 1.35 x the building back',
    float(HCAM['dist'])
    >= B.HERO_DIST_K * max(_y1 - _y0, ((ENV['x1'] - ENV['x0']) ** 2 + (ENV['z1'] - ENV['z0']) ** 2) ** 0.5) - 1e-6,
    f'dist {HCAM["dist"]}, height {_y1 - _y0:.1f}',
)
check('the visible facades are the lit ones', HCAM['lit'] is True, (HCAM['side'], HCAM['lit']))

# every solid the frame has to hold, projected through the camera that was built
_PTS = B._hero_points(d, ENV)
check('the fit is made of the records, not the bounding box', len(_PTS) > 100, len(_PTS))
check(
    'the point set reaches the top of the building',
    abs(max(p[2] for p in _PTS) - _y1) <= 0.5,
    (max(p[2] for p in _PTS), _y1),
)
_nd = _ndc(HCAM, _PTS, AR)
_vs = [p[1] for p in _nd]
_us = [abs(p[0]) for p in _nd]
TOP_NDC, BOT_NDC = (1.0 - max(_vs)) / 2.0, (1.0 - min(_vs)) / 2.0
print(
    f'  .. hero camera: {HCAM["dist"]} m out ({HCAM["side"]} chose the side), '
    f'shift_y {HCAM["shift_y"]}, envelope {_y1 - _y0:.1f} m tall',
    flush=True,
)
print(
    f'  .. hero framing: top edge {TOP_NDC * 100:.1f} % from the top, ground line '
    f'{BOT_NDC * 100:.1f} % down, silhouette {(BOT_NDC - TOP_NDC) * 100:.1f} % of the '
    f'image height, {max(_us) * 100:.1f} % of the half-width',
    flush=True,
)
check(
    'the WHOLE envelope is in frame',
    max(_us) <= 1.0 and max(_vs) <= 1.0 and min(_vs) >= -1.0,
    f'u max {max(_us):.3f}, v {min(_vs):.3f}..{max(_vs):.3f}',
)
check(
    'the building fills >= 55 % of the frame height', (BOT_NDC - TOP_NDC) >= 0.55, f'{(BOT_NDC - TOP_NDC) * 100:.1f} %'
)
check('the top edge is within 10 % of the top', 0.0 < TOP_NDC <= 0.10, f'{TOP_NDC * 100:.1f} %')
check('the ground line is in the lower third', BOT_NDC >= 2.0 / 3.0, f'{BOT_NDC * 100:.1f} %')

# no door -> no entrance side to stand off: the 'eye' walk, never a crash
_nodoor = B._hero_shot(
    A.Drawing(None), {'x0': 0.0, 'x1': 10.0, 'z0': 0.0, 'z1': 10.0, 'y0': 0.0, 'y1': 8.0}, None, None, AR
)
check('no door falls back to the eye walk', _nodoor == ('hero', 'eye', None, None), _nodoor)

# ── the live acceptance drawing: the lobby camera and the lobby's lamps ──────
D16 = _load16()
check('the live fixture loaded', len(D16.objs) == 983, len(D16.objs))
LAMPS = [o for o in D16.objs if str(o.get('kind') or '').startswith('light_')]
check('the live lobby has lamps in it', len(LAMPS) == 16, f'{len(LAMPS)} light_* records')
S16, DOOR16, ENV16, _yc16 = B._present_shots(D16, '')
LOBBY = [s for s in S16 if s[0] == 'lobby'][0]
LCAM = LOBBY[2]
# the hero lobby is present()'s OWN lobby camera — same standpoint, same retreat
check('the lobby shot is a lobby camera', LCAM.get('kind') == 'lobby', LCAM)
check(
    'the lobby camera stands LOBBY_INSIDE_M inside the door',
    abs(
        math.hypot(LCAM['loc'][0] - B._door_axis(D16, DOOR16)[0], LCAM['loc'][1] + B._door_axis(D16, DOOR16)[1])
        - B.LOBBY_INSIDE_M
    )
    < 1e-6,
    (LCAM['loc'], B._door_axis(D16, DOOR16), B.LOBBY_INSIDE_M),
)
check(
    'the lobby camera keeps its retreat rule',
    LCAM['retreat_max'] == round(B.LOBBY_INSIDE_M - B.LOBBY_MIN_INSIDE_M, 3),
    LCAM,
)
check(
    'the lobby camera is at eye height',
    abs(LCAM['loc'][2] - (float(DOOR16.get('y') or 0.0) + B.LOBBY_EYE_M)) < 1e-6,
    LCAM['loc'],
)
H16 = B._hero_shot(D16, ENV16, DOOR16, B._sun_hour(D16), AR)
_nd16 = B._hero_ndc(H16[2], B._hero_points(D16, ENV16), AR)
TOP16 = (1.0 - max(v for _u, v in _nd16)) / 2.0

# every real bpy lamp must sit on its record. The builder is handed only (bm, p),
# so arch_blender_build.adopt_builder_objects parents whatever a builder made to
# the record's own object; without it all sixteen fire from (0, 0, 0).
LAMP_PROBE = os.path.join(B.BLEND_DIR, '_lamp_probe.py')
os.makedirs(B.BLEND_DIR, exist_ok=True)
with open(LAMP_PROBE, 'w', encoding='utf-8') as fh:
    fh.write(
        'import bpy, json\n'
        'out = []\n'
        'for o in bpy.data.objects:\n'
        "    if o.type == 'LIGHT':\n"
        '        w = o.matrix_world.translation\n'
        "        out.append({'name': o.name, 'id': o.get('studio_id'),\n"
        "                    'loc': [round(c, 4) for c in w],\n"
        "                    'parent': (o.parent.name if o.parent else None),\n"
        "                    'energy': round(o.data.energy, 3)})\n"
        "print('BP_LAMPS ' + json.dumps(out))\n"
    )
_blend16, _note16 = B._build(D16)
_rc, _out, _ = B._second_pass(_blend16, user_file=LAMP_PROBE)
_seen = [json.loads(ln[len('BP_LAMPS ') :]) for ln in _out.splitlines() if ln.startswith('BP_LAMPS ')]
BULBS = _seen[-1] if _seen else []
print(f'  .. build: {_note16}; {len(BULBS)} bpy lights in the .blend', flush=True)
check(
    'every lamp record made a real bpy light',
    len(BULBS) == len(LAMPS),
    f'{len(BULBS)} lights for {len(LAMPS)} records; {B._tail(_out, 300)}',
)
_byid = {str(o['id']): o for o in LAMPS}
_off = []
for b in BULBS:
    rec = _byid.get(str(b.get('id')))
    if rec is None:
        _off.append((b.get('name'), 'no record id on the light object'))
        continue
    want = (float(rec.get('x') or 0.0), -float(rec.get('z') or 0.0), float(rec.get('y') or 0.0))
    dist = max(abs(b['loc'][i] - want[i]) for i in range(3))
    if dist > 0.05:
        _off.append((rec['id'], b['loc'], list(want), round(dist, 3)))
print('  .. lamp positions (world vs record, blender x = studio x, y = -studio z, z = studio y):', flush=True)
for b in BULBS[:4]:
    rec = _byid.get(str(b.get('id')))
    print(
        f'     {b["id"]} light at {b["loc"]} · record '
        f'{[round(float(rec.get("x") or 0), 3), round(-float(rec.get("z") or 0), 3), round(float(rec.get("y") or 0), 3)]}'
        f' · parent {b["parent"]} · {b["energy"]} W',
        flush=True,
    )
print(f'     ... {len(BULBS)} lights, {len(_off)} off their record', flush=True)
check('every lamp is within 0.05 m of its record', BULBS and not _off, _off[:4])
check(
    'every lamp rides the record object',
    all(b['parent'] for b in BULBS),
    [b['name'] for b in BULBS if not b['parent']][:4],
)
check(
    'no lamp is left at the drawing origin',
    all(max(abs(c) for c in b['loc']) > 0.5 for b in BULBS),
    [b for b in BULBS if max(abs(c) for c in b['loc']) <= 0.5][:2],
)

# ── (a) a real Blender run, small and cheap ──────────────────────────────────
os.environ['ZYG_ARCH_HERO_SAMPLES'] = '8'
t0 = time.time()
try:
    small = B.hero_render(D16, 'test-hero-small', width=960, height=540)
    err = ''
except Exception as e:  # noqa: BLE001
    small, err = [], f'{type(e).__name__}: {e}'
print(f'  .. small pass: {round(time.time() - t0, 1)} s', flush=True)
check('hero_render: four frames', len(small) == 4, err or small)
check(
    'hero_render: hero, approach, lobby, aerial in that order',
    [h['title'] for h in small] == list(B.HERO_VIEWS),
    [h['title'] for h in small],
)

for h in small:
    t = h['title']
    print(
        f'  .. {t}: {h["seconds"]} s, {h["bytes"] // 1024} KB, engine {h["engine"]}, '
        f'device {h["device"]} {h["backend"]}, {h["samples"]} samples, sky {h["sky"]}, '
        f'EV {h["exposure"]}, ground {h["ground"] or "(the drawing brought its own)"}',
        flush=True,
    )
    check(f'{t}: the PNG exists', os.path.isfile(h['png']), h['png'])
    check(f'{t}: engine CYCLES', h['engine'] == 'CYCLES', h['engine'])
    # a 4090 with OptiX is on this machine: a CPU fall-back would make a 4K
    # frame an hour, so it is a failure, not a note.
    check(
        f'{t}: device GPU',
        h['device'] == 'GPU',
        f'device={h["device"]} backend={h["backend"]}; stderr tail: {B._tail(h["out"], 600)}',
    )
    check(f'{t}: samples honour the env', h['samples'] == 8, h['samples'])
    check(f'{t}: a physical sky', h['sky'] == 'NISHITA', h['sky'])
    check(f'{t}: the JPEG is beside it', os.path.isfile(h['jpeg'] or ''), h['jpeg'])
    size, mean, sd = _lum_stats(h['png'])
    print(f'  .. {t}: {size[0]}x{size[1]}, luminance mean {mean:.1f}, std-dev {sd:.2f}', flush=True)
    check(f'{t}: 960x540', size == (960, 540), size)
    # textured, not a flat grey massing render
    check(f'{t}: luminance std-dev > 15', sd > 15.0, f'std-dev {sd:.2f}')
    if t == 'lobby':
        # the interior: neither a black box nor a blown-out white one. The lamps
        # are in the room and the stop is HERO_EV_VIEW's, not the exterior's.
        check(
            'lobby: the interior stop was used',
            h['exposure'] == B.HERO_EV_VIEW['lobby'],
            f'exposure {h["exposure"]}, wanted {B.HERO_EV_VIEW["lobby"]}',
        )
        check('lobby: lit, not black and not blown', 40.0 <= mean <= 200.0, f'mean luminance {mean:.1f}')
        check('lobby: a room, not a flat wall', sd > 15.0, f'std-dev {sd:.2f}')
    else:
        check(f'{t}: the exterior stop', h['exposure'] == B.HERO_EV, h['exposure'])

if small:
    check(
        'the frames are named for the job',
        all(os.path.basename(h['png']) == f'test-hero-small-hero-{h["title"]}.png' for h in small),
        [os.path.basename(h['png']) for h in small],
    )
    panel = B.hero_images(small)
    check(
        'the panel gets four pictures, hero first, lobby third',
        len(panel) == 4 and panel[0]['title'] == 'photoreal 4K · hero' and panel[2]['title'] == 'photoreal 4K · lobby',
        [p['title'] for p in panel],
    )
    check(
        'every panel picture opens the 4K PNG',
        all(p['full'].endswith('.png') for p in panel),
        [p['full'] for p in panel],
    )

    # the pixels, not the camera: where the silhouette really starts. The sky is
    # the only thing above the parapet, so the first row that differs from its
    # own left/right edge colour IS the top of the building.
    hp = [h for h in small if h['title'] == 'hero']
    if hp:
        sk, skx = _skyline(hp[0]['png'])
        print(
            f'  .. hero skyline (PIL): top edge at {"none" if sk is None else f"{sk * 100:.1f} %"}'
            f' of the image height, x={skx}',
            flush=True,
        )
        check(
            'the render agrees: the building starts in the top tenth',
            sk is not None and 0.0 < sk <= 0.10,
            f'skyline {sk}',
        )
        check(
            'the render agrees with the camera to within 4 % of the height',
            sk is not None and abs(sk - TOP16) <= 0.04,
            f'PIL {sk}, projected {TOP16:.4f}',
        )
        ap = [h for h in small if h['title'] == 'approach']
        check(
            'the hero is not the approach frame',
            bool(ap) and open(hp[0]['png'], 'rb').read() != open(ap[0]['png'], 'rb').read(),
            'the two frames are byte-identical' if ap else 'no approach frame',
        )

# ── (b) the picture route ────────────────────────────────────────────────────
for bad in ('../x', 'a/b.png', '..', '', 'x.png\x00', 'note.txt', 'nothing-here.png'):
    out, code = A.handle_get(A.PREFIX + '/picture', {'f': bad})
    check(f'picture refuses {bad!r}', code in (400, 404) and isinstance(out, dict), (code, out))

if small:
    got, code = A.handle_get(A.PREFIX + '/picture', {'f': os.path.basename(small[0]['jpeg'])})
    check(
        'picture serves the JPEG',
        code == 200 and isinstance(got, tuple) and isinstance(got[0], bytes) and got[1] == 'image/jpeg',
        (code, type(got), got[1] if isinstance(got, tuple) else None),
    )
    check(
        'picture serves the JPEG bytes',
        isinstance(got, tuple) and got[0][:2] == b'\xff\xd8' and len(got[0]) == os.path.getsize(small[0]['jpeg']),
        len(got[0]) if isinstance(got, tuple) else got,
    )
    gotp, codep = A.handle_get(A.PREFIX + '/picture', {'f': os.path.basename(small[0]['png'])})
    check(
        'picture serves the 4K PNG as image/png',
        codep == 200 and isinstance(gotp, tuple) and gotp[1] == 'image/png' and gotp[0][:4] == b'\x89PNG',
        (codep, gotp[1] if isinstance(gotp, tuple) else gotp),
    )

# ── (d) real 4K frames at the shipped sample count ───────────────────────────
# The whole building and the LOBBY, both at 3840x2160 and 128 samples on the
# live acceptance drawing — one build, two frames, timed for the record.
os.environ.pop('ZYG_ARCH_HERO_SAMPLES', None)
stop, mem = threading.Event(), []
threading.Thread(target=_nvidia_peak, args=(stop, mem), daemon=True).start()
t0 = time.time()
try:
    big = B.hero_render(_load16(), 'test-hero-4k', views=('hero', 'lobby'), width=B.HERO_W, height=B.HERO_H)
    berr = ''
except Exception as e:  # noqa: BLE001
    big, berr = [], f'{type(e).__name__}: {e}'
wall = round(time.time() - t0, 1)
stop.set()
peak = max(mem) if mem else 0
check('4K: the whole building and the lobby at the shipped settings', len(big) == 2, berr or big)
check('4K: the hero comes first', [h['title'] for h in big] == ['hero', 'lobby'], [h['title'] for h in big])
for h in big:
    t = h['title']
    size, mean, sd = _lum_stats(h['png'])
    jb = os.path.getsize(h['jpeg']) if h['jpeg'] and os.path.exists(h['jpeg']) else 0
    print(f'\n  === 4K MEASUREMENT: {t} (the record, not a threshold) ===', flush=True)
    print(f'  view          {t}', flush=True)
    print(f'  size          {size[0]}x{size[1]}', flush=True)
    print(f'  samples       {h["samples"]} ({h["device"]} {h["backend"]}, denoised)', flush=True)
    print(f'  exposure      {h["exposure"]} EV{" (the interior stop)" if h["ev_view"] else ""}', flush=True)
    print(f'  seconds       {h["seconds"]}  (both frames {wall} s, HERO_TIMEOUT {B.HERO_TIMEOUT} s)', flush=True)
    print(f'  png bytes     {h["bytes"]} ({h["bytes"] / 1e6:.2f} MB)', flush=True)
    print(f'  jpeg bytes    {jb} ({jb / 1e6:.2f} MB, {B.HERO_JPEG_W} px wide, q{B.HERO_JPEG_Q})', flush=True)
    print(f'  nvidia-smi    peak memory.used {peak} MiB over {len(mem)} samples', flush=True)
    print(f'  luminance     mean {mean:.1f}, std-dev {sd:.2f}', flush=True)
    print(f'  file          {h["png"]}', flush=True)
    print('  ===================================================\n', flush=True)
    check(f'4K {t}: really 3840x2160', size == (B.HERO_W, B.HERO_H), size)
    check(
        f'4K {t}: CYCLES on the GPU',
        h['engine'] == 'CYCLES' and h['device'] == 'GPU',
        f'{h["engine"]} {h["device"]} {h["backend"]}',
    )
    check(f'4K {t}: the shipped 128 samples', h['samples'] == 128, h['samples'])
    check(
        f'4K {t}: finished inside HERO_TIMEOUT',
        h['seconds'] < B.HERO_TIMEOUT,
        f'{h["seconds"]} s of {B.HERO_TIMEOUT} s',
    )
    check(f'4K {t}: textured', sd > 15.0, f'std-dev {sd:.2f}')
    check(f'4K {t}: the panel JPEG is far lighter than the PNG', 0 < jb < h['bytes'], (jb, h['bytes']))
    if t == 'lobby':
        check('4K lobby: the interior stop', h['exposure'] == B.HERO_EV_VIEW['lobby'], h['exposure'])
        check('4K lobby: lit, not black and not blown', 40.0 <= mean <= 200.0, f'mean {mean:.1f}')

finish()
