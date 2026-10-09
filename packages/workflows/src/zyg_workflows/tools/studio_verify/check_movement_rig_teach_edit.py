# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof — TEACH and EDIT are driven from the Skeleton panel, not from a CLI.

Both legs of the Movement Studio panel that make NEW motion had only ever been
run from Python: EDIT (trim/speed/mirror/loop -> a clip in the ``edit`` bucket)
and TEACH (a video -> GEM-X -> a cmu_mb clip in the ``capture`` bucket). Their
forms rendered and nothing had ever clicked them. This drives both through the
real page, on the tab's own default subject — the clay base body — and proves
the result reached the library AND the stage:

  EDIT  mirror capture/qa_sword -> edit/qa_sword_mirror_ui, then pick the new
        clip in the MOVEMENT list and wait for the actor to be rebuilt on it:
        MVR.motion, MVR.actor and the served GLB url must all name the edit,
        and the mixer must advance on it.
  TEACH capture output/movement/_capture/qa_ui_short.mp4 (3 s, 72 frames) as
        capture/qa_ui_short and wait for it to appear in the clip list with a
        frame count that matches the footage.

Both legs are idempotent: motion_edit.save and motion_capture.register_capture
each replace a record of the same id, so this script can be re-run (it is the
task's verify_cmd) and will simply redo the work.

THE BUG THIS FOUND. The clip rows guarded their click with
``if (id === MVR.motion) return``, while both the edit handler and the capture
poller set ``MVR.motion`` to the clip they had just created. So the first click
on a clip you had just made was a dead one — the row highlighted, no build was
posted, and the actor went on playing the old motion. The guard now asks the
actor (``onStage()``, the server's actor-name rule), not the selection.

Run: <venv>/bin/python \
         tools/studio_verify/check_movement_rig_teach_edit.py
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright
from zyg_workflows import paths

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(os.path.dirname(HERE))
SHOT_EDIT = os.path.join(HERE, 'movement_rig_edit.png')
SHOT_TEACH = os.path.join(HERE, 'movement_rig_teach.png')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#movementstudio'

SRC_MOTION = 'capture/qa_sword'
EDIT_SLUG = 'qa_sword_mirror_ui'
EDIT_ID = 'edit/' + EDIT_SLUG
EDIT_LABEL = 'sword walk mirrored (UI)'
CAP_VIDEO = os.path.join(CREWS, 'output', 'movement', '_capture', 'qa_ui_short.mp4')
CAP_ID = 'capture/qa_ui_short'
CAP_LABEL = 'sword (UI capture, 3 s)'
CAP_FRAMES_MIN, CAP_FRAMES_MAX = 60, 80  # 3 s x 23.976 fps = 72

BOOT_TIMEOUT_MS = 240_000
SAVE_TIMEOUT_MS = 60_000
# EVERY run rebuilds: saving the edit rewrites edit/<slug>.bvh, and _glb_is_fresh
# compares mtimes, so the actor is stale again each time and proxy_actor +
# rig_export_glb run in full. Measured 456 s on a box carrying ~30 parallel
# sessions (load 13 on 24 cores); 2-3 min when it is quiet.
REBUILD_TIMEOUT_MS = 900_000
CAPTURE_TIMEOUT_MS = 600_000
VIEWPORT = {'width': 1920, 'height': 1080}

PROBE = """() => {
  const M = window.MVR;
  if (!M) return {ready:false, why:'no MVR'};
  const panel = document.getElementById('mvr-panel');
  const bones = (M.skeleton && M.skeleton.bones) ? M.skeleton.bones.length : 0;
  const secText = {};
  if (panel) Array.prototype.forEach.call(panel.querySelectorAll('.mvr-sec'), s => {
    const h = s.querySelector('h4[data-sec]');
    if (h) secText[h.getAttribute('data-sec')] = s.textContent.replace(/\\s+/g, ' ').trim();
  });
  return {
    ready: !!M.loaded && bones > 0,
    loaded: !!M.loaded, error: M.error || '', job: M.job || '',
    actor: M.actor || '', motion: M.motion || '', glb: M.glbUrl || '',
    bones: bones, dur: +(M.dur || 0).toFixed(3),
    mixerTime: M.mixer ? M.mixer.time : null,
    clipIds: Array.prototype.map.call(
      panel ? panel.querySelectorAll('.mvr-clip') : [], c => c.getAttribute('data-clip')),
    selected: Array.prototype.map.call(
      panel ? panel.querySelectorAll('.mvr-clip.on') : [], c => c.getAttribute('data-clip')),
    libIds: (M.clips || []).map(c => c.id),
    libFrames: Object.fromEntries((M.clips || []).map(c => [c.id, c.frames])),
    libLabels: Object.fromEntries((M.clips || []).map(c => [c.id, c.label])),
    sec: secText,
    cname: (document.getElementById('mvst-cname') || {}).textContent || '',
    status: (document.getElementById('mvst-status') || {}).textContent || '',
    glFailed: (window.MVST3 && MVST3.failed) || ''
  };
}"""


def poll(pg, ok, timeout_ms, what, step=1000):
    """Poll PROBE until ok(state). Returns (state, waited_ms)."""
    waited = 0
    st = pg.evaluate(PROBE)
    while True:
        if ok(st):
            return st, waited
        if waited >= timeout_ms:
            raise AssertionError('%s: gave up after %d s — %s' % (what, timeout_ms // 1000, json.dumps(st)[:900]))
        pg.wait_for_timeout(step)
        waited += step
        st = pg.evaluate(PROBE)


def open_section(pg, sec):
    if pg.evaluate("() => !!document.querySelector('#mvr-panel h4[data-sec=%s] + .mvr-bd.off')" % sec):
        pg.click('#mvr-panel h4[data-sec=%s]' % sec)
        pg.wait_for_timeout(250)


def advances(pg, seconds=1.0):
    t0 = pg.evaluate('() => MVR.mixer ? MVR.mixer.time : -1')
    pg.wait_for_timeout(int(seconds * 1000))
    t1 = pg.evaluate('() => MVR.mixer ? MVR.mixer.time : -1')
    return round(t0, 4), round(t1, 4)


def leg_edit(pg, out):
    """Mirror the loaded clip from the EDIT form, then play the result."""
    open_section(pg, 'edit')
    btn = pg.inner_text('#mvr-ed-go')
    if SRC_MOTION not in btn:
        raise RuntimeError('the EDIT button offers %r, not the loaded clip %r' % (btn, SRC_MOTION))

    pg.check('#mvr-ed-mirror')
    pg.fill('#mvr-ed-save', EDIT_SLUG)
    pg.fill('#mvr-ed-label', EDIT_LABEL)
    pg.click('#mvr-ed-go')

    # the section's own note is the only signal that says THIS click saved: the
    # clip id is already in the library on a re-run, so waiting for the list
    # would return before the POST had even answered
    st, waited_save = poll(
        pg,
        lambda s: 'saved ' + EDIT_ID in s['sec'].get('edit', '') or 'refused' in s['sec'].get('edit', ''),
        SAVE_TIMEOUT_MS,
        'the EDIT section never reported a save',
    )
    if 'saved ' + EDIT_ID not in st['sec'].get('edit', ''):
        raise RuntimeError('the edit was refused: %r' % st['sec'].get('edit', '')[:300])
    st, waited_list = poll(
        pg,
        lambda s: EDIT_ID in (s.get('clipIds') or []),
        SAVE_TIMEOUT_MS,
        'the new clip never became a row in the MOVEMENT list',
    )
    out['edit_note'] = st['sec'].get('edit', '')
    out['edit_label_in_list'] = (st.get('libLabels') or {}).get(EDIT_ID, '')
    out['edit_frames'] = (st.get('libFrames') or {}).get(EDIT_ID)
    out['waited_save_s'] = (waited_save + waited_list) // 1000

    # pick it the way the operator does — one click on the row
    before_actor = st['actor']
    pg.click('#mvr-panel .mvr-clip[data-clip="%s"]' % EDIT_ID)
    want_actor = 'base_male_realistic__edit_' + EDIT_SLUG
    st, waited_build = poll(
        pg,
        lambda s: s.get('actor') == want_actor and s.get('loaded') and want_actor in (s.get('glb') or ''),
        REBUILD_TIMEOUT_MS,
        'the actor was never rebuilt on ' + EDIT_ID,
    )
    t0, t1 = advances(pg)
    out.update(
        {
            'edit_id': EDIT_ID,
            'actor_before_click': before_actor,
            'edit_actor': st['actor'],
            'edit_motion': st['motion'],
            'edit_glb': st['glb'],
            'edit_bones': st['bones'],
            'edit_duration_s': st['dur'],
            'edit_mixer_t0': t0,
            'edit_mixer_t1': t1,
            'edit_advanced_s': round(t1 - t0, 4),
            'edit_selected_rows': st['selected'],
            'waited_rebuild_s': waited_build // 1000,
            'edit_status_line': ' '.join(st['status'].split()),
        }
    )
    if st['motion'] != EDIT_ID:
        raise RuntimeError('MVR.motion is %r' % st['motion'])
    if t1 <= t0:
        raise RuntimeError('the mixer did not advance on the edit: %.4f -> %.4f' % (t0, t1))
    if st['bones'] != 31:
        raise RuntimeError('the rebuilt actor has %d bones' % st['bones'])
    pg.screenshot(path=SHOT_EDIT)


def leg_teach(pg, out):
    """Capture a 3 s video into the library from the TEACH form."""
    if not os.path.isfile(CAP_VIDEO):
        raise FileNotFoundError('no source video at %s' % CAP_VIDEO)
    open_section(pg, 'teach')
    pg.fill('#mvr-cap-video', CAP_VIDEO)
    pg.fill('#mvr-cap-id', CAP_ID)
    pg.fill('#mvr-cap-label', CAP_LABEL)
    pg.click('#mvr-cap-go')

    # the refusal (409 heavy slot, bad path) is shown in the TEACH note
    pg.wait_for_timeout(1500)
    note = pg.evaluate(PROBE)['sec'].get('teach', '')
    if not ('refused' not in note and 'no such video' not in note):
        raise RuntimeError('the capture was refused: %r' % note[:400])

    # again the note, not the list: the clip id survives a previous run
    st, waited = poll(
        pg,
        lambda s: 'captured ' + CAP_ID in s['sec'].get('teach', '') or 'failed' in s['sec'].get('teach', ''),
        CAPTURE_TIMEOUT_MS,
        'the TEACH section never reported a capture',
        step=5000,
    )
    if 'captured ' + CAP_ID not in st['sec'].get('teach', ''):
        raise RuntimeError('the capture failed: %r' % st['sec'].get('teach', '')[:400])
    st, waited_list = poll(
        pg,
        lambda s: CAP_ID in (s.get('clipIds') or []),
        SAVE_TIMEOUT_MS,
        'the captured clip never became a row in the MOVEMENT list',
    )
    waited += waited_list
    frames = (st.get('libFrames') or {}).get(CAP_ID)
    out.update(
        {
            'capture_id': CAP_ID,
            'capture_video': CAP_VIDEO,
            'capture_frames': frames,
            'capture_label_in_list': (st.get('libLabels') or {}).get(CAP_ID, ''),
            'teach_note': st['sec'].get('teach', ''),
            'capture_motion_selected': st['motion'],
            'waited_capture_s': waited // 1000,
            'clips_after': len(st.get('libIds') or []),
        }
    )
    if 'captured ' + CAP_ID not in st['sec'].get('teach', ''):
        raise RuntimeError('the TEACH section does not report the capture: %r' % st['sec'].get('teach', '')[:300])
    if CAP_ID not in st.get('clipIds') or []:
        raise RuntimeError('the captured clip is not a row in the MOVEMENT list')
    if not (frames and CAP_FRAMES_MIN <= frames <= CAP_FRAMES_MAX):
        raise RuntimeError('captured %r frames, expected ~72 for a 3 s clip' % (frames,))
    pg.screenshot(path=SHOT_TEACH)


def main():
    out = {'ok': True, 'viewport': '%dx%d' % (VIEWPORT['width'], VIEWPORT['height'])}
    errs = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(
            executable_path='/usr/bin/google-chrome',
            args=[
                '--use-angle=swiftshader',
                '--enable-unsafe-swiftshader',
                '--autoplay-policy=no-user-gesture-required',
            ],
        )
        pg = br.new_context(viewport=VIEWPORT).new_page()
        pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        pg.goto(URL, wait_until='load', timeout=120_000)

        boot, waited_boot = poll(pg, lambda s: s.get('ready'), BOOT_TIMEOUT_MS, 'the tab never loaded a skeleton')
        out.update(
            {
                'boot_name': boot['cname'].strip(),
                'boot_actor': boot['actor'],
                'boot_motion': boot['motion'],
                'clips_before': len(boot['libIds']),
                'waited_boot_s': waited_boot // 1000,
            }
        )
        if not boot['actor'].startswith('base_'):
            raise RuntimeError('the tab did not open on the base body: actor %r' % boot['actor'])
        if boot['motion'] != SRC_MOTION:
            raise RuntimeError('the tab opened on %r, expected %r' % (boot['motion'], SRC_MOTION))

        leg_edit(pg, out)
        leg_teach(pg, out)
        br.close()

    out['pageerrors'] = [e for e in errs if 'favicon' not in e]
    out['screenshot_edit'] = SHOT_EDIT
    out['screenshot_edit_bytes'] = os.path.getsize(SHOT_EDIT)
    out['screenshot_teach'] = SHOT_TEACH
    out['screenshot_teach_bytes'] = os.path.getsize(SHOT_TEACH)
    print(json.dumps(out, indent=1))
    if out['pageerrors']:
        raise RuntimeError(out['pageerrors'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
