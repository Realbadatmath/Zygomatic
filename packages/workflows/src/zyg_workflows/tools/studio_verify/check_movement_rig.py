# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof — Movement Studio opens on the clay base body, and an injected
character arrives proportion-FITTED.

Headless WebGL through Playwright + SwiftShader, run at BOTH the operator's real
window (1920x1080) and the 67 %-zoom viewport (2507x1567). What it proves, in the
order the operator would check it:

  1. the tab opens on the CLAY BASE BODY with nothing injected — header
     'Base body · …', MVR.actor 'base_*' (operator ruling 2026-09-23 01:40)
  2. MVR.mixer.time moves between two samples a second apart — the clip is
     actually playing, not a frozen rest pose
  3. MVR.skeleton.bones.length == 31 — the cmu_mb joint set, drawn
  4. the Skeleton panel is OPEN by default and stands BESIDE the preview frame
     on its right: its rect never overlaps .cs-main and panel.left >= frame.right
  5. injecting Abel through mvstLoadSubject('character', …) builds and loads
     c3345deb5bde__capture_qa_sword, and the header says 'Abel Van Haren'
  6. the FIT section reports a real fit — 'fit: exact' or 'fit: clamped (…)',
     never 'none' — which is what the rebuilt base rig plus the non-fatal
     bone-length fitter bought
  7. Escape folds the panel away (display:none), and a fresh page context opens
     it again (the default is open)
  8. no page error

The wait is 240 s per load because a stale actor is rebuilt by proxy_actor +
rig_export_glb under Blender (~2-3 min of CPU). A second run answers `cached`
and fills the pane in under a second.

Run:  ~/zygomatics-zero/venv/bin/python tools/studio_verify/check_movement_rig.py
"""

import json
import os
from zyg_workflows import paths


HERE = os.path.dirname(os.path.abspath(__file__))
SHOT = os.path.join(HERE, 'movement_rig.png')
SHOT_FIT = os.path.join(HERE, 'movement_rig_fit.png')
URL = paths.ZYG_KANBAN_URL + '/inspection.html#movementstudio'

WANT_BONES = 31
WANT_CHAR_ID = 'c3345deb5bde'
WANT_CHAR_NAME = 'Abel Van Haren'
WANT_ACTOR = 'c3345deb5bde__capture_qa_sword'
READY_TIMEOUT_MS = 240_000
VIEWPORTS = [(1920, 1080), (2507, 1567)]

PROBE = """() => {
  const M = window.MVR;
  if (!M) return {ready:false, why:'no MVR'};
  const bones = (M.skeleton && M.skeleton.bones) ? M.skeleton.bones.length : 0;
  const panel = document.getElementById('mvr-panel');
  const main = document.querySelector('#view-movement .cs-main');
  const pr = panel ? panel.getBoundingClientRect() : null;
  const mr = main ? main.getBoundingClientRect() : null;
  return {
    ready: !!M.loaded && bones > 0,
    loaded: !!M.loaded,
    error: M.error || '',
    actor: M.actor || '',
    motion: M.motion || '',
    glb: M.glbUrl || '',
    bones: bones,
    dur: +(M.dur || 0).toFixed(3),
    mixerTime: M.mixer ? M.mixer.time : null,
    paused: !!M.paused,
    speed: M.speed,
    clips: (M.clips || []).length,
    fitStatus: (M.meta && M.meta.fit && M.meta.fit.status) || 'none',
    panel: !!panel,
    panelOpen: !!(panel && panel.classList.contains('on')),
    panelDisplay: panel ? getComputedStyle(panel).display : '',
    panelRect: pr ? {l:Math.round(pr.left), r:Math.round(pr.right),
                     t:Math.round(pr.top), b:Math.round(pr.bottom)} : null,
    frameRect: mr ? {l:Math.round(mr.left), r:Math.round(mr.right),
                     t:Math.round(mr.top), b:Math.round(mr.bottom)} : null,
    panelClips: panel ? panel.querySelectorAll('.mvr-clip').length : 0,
    panelSections: panel ? panel.querySelectorAll('.mvr-sec').length : 0,
    fitText: panel ? Array.prototype.map.call(
               panel.querySelectorAll('.mvr-sec'),
               s => s.textContent).filter(t => /^\\s*FIT/i.test(t)).join(' ') : '',
    cname: (document.getElementById('mvst-cname') || {}).textContent || '',
    csub: (document.getElementById('mvst-csub') || {}).textContent || '',
    status: (document.getElementById('mvst-status') || {}).textContent || '',
    videoShown: (document.getElementById('mvst-video') || {}).style
                  ? document.getElementById('mvst-video').style.display : '',
    glFailed: (window.MVST3 && MVST3.failed) || ''
  };
}"""


def _require(cond, msg):
    """Fail the proof when *cond* is false — an `assert` is removed by `python -O`."""
    if not cond:
        raise AssertionError(msg)


def wait_ready(pg, want_actor=None):
    """Poll until MVR has a drawn skeleton (and, when asked, that actor)."""
    waited = 0
    st = None
    while waited < READY_TIMEOUT_MS:
        st = pg.evaluate(PROBE)
        if st.get('ready') and (want_actor is None or st.get('actor') == want_actor):
            return st, waited
        if st.get('error'):
            raise AssertionError('the skeleton refused to load: %s' % st['error'])
        pg.wait_for_timeout(1000)
        waited += 1000
    raise AssertionError('no %s after %d s: %s' % (want_actor or 'skeleton', READY_TIMEOUT_MS // 1000, json.dumps(st)))


def assert_beside(st, where):
    """The panel stands to the RIGHT of the preview frame and never over it."""
    pr, mr = st['panelRect'], st['frameRect']
    _require(pr and mr, '%s: no panel/frame rect: %s' % (where, json.dumps(st)))
    _require(
        pr['l'] >= mr['r'],
        '%s: panel.left %d < frame.right %d — it sits over the preview'
        % (
            where,
            pr['l'],
            mr['r'],
        ),
    )
    overlap = pr['l'] < mr['r'] and pr['r'] > mr['l'] and pr['t'] < mr['b'] and pr['b'] > mr['t']
    _require(not overlap, '%s: panel %s overlaps frame %s' % (where, pr, mr))


def run(pw, width, height, shoot):
    errs = []
    br = pw.chromium.launch(
        executable_path='/usr/bin/google-chrome',
        args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required'],
    )
    ctx = br.new_context(viewport={'width': width, 'height': height})
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.goto(URL, wait_until='load', timeout=120_000)

    # 1. the boot state is the CLAY BASE BODY, not a character
    boot, waited = wait_ready(pg)
    _require(
        boot['cname'].strip().startswith('Base body'),
        'the tab did not open on the base body: header is %r' % boot['cname'],
    )
    _require(boot['actor'].startswith('base_'), 'the tab did not open on the base body: actor is %r' % boot['actor'])

    # 2. the clip is PLAYING: two samples a second apart, on the page's own clock
    t0 = pg.evaluate('() => MVR.mixer ? MVR.mixer.time : -1')
    pg.wait_for_timeout(1000)
    t1 = pg.evaluate('() => MVR.mixer ? MVR.mixer.time : -1')
    _require(t0 >= 0 and t1 > t0, 'the mixer did not advance: %.4f -> %.4f' % (t0, t1))

    # 3./4. the joint set, and the panel open BESIDE the frame by default
    _require(boot['bones'] == WANT_BONES, 'SkeletonHelper has %d bones, cmu_mb is %d' % (boot['bones'], WANT_BONES))
    _require(boot['panel'], 'no #mvr-panel')
    _require(
        boot['panelOpen'] and boot['panelDisplay'] != 'none',
        'the panel is not open by default: display=%r' % boot['panelDisplay'],
    )
    _require(boot['panelClips'] >= 4, 'the panel lists only %d clips' % boot['panelClips'])
    assert_beside(boot, 'boot %dx%d' % (width, height))

    # 5. inject Abel the way the Inject Subject button does
    pg.evaluate("() => mvstLoadSubject('character', {id:'%s', name:'%s'})" % (WANT_CHAR_ID, WANT_CHAR_NAME))
    st, waited_abel = wait_ready(pg, WANT_ACTOR)
    _require(st['cname'].strip() == WANT_CHAR_NAME, 'header is %r, expected %r' % (st['cname'], WANT_CHAR_NAME))

    # 6. the FIT section reports a real fit. The panel is ALREADY open — clicking
    #    #mvr-btn would fold it — so only the section header is clicked.
    if pg.evaluate("() => !!document.querySelector('#mvr-panel h4[data-sec=fit] + .mvr-bd.off')"):
        pg.click('#mvr-panel h4[data-sec=fit]')
        pg.wait_for_timeout(300)
    fit = pg.evaluate(PROBE)
    _require('fit:' in fit['fitText'], 'the FIT section shows no fit line: %r' % fit['fitText'][:400])
    _require(
        fit['fitStatus'] in ('exact', 'clamped'),
        'Abel is not fitted: status=%r, section=%r'
        % (
            fit['fitStatus'],
            fit['fitText'][:400],
        ),
    )
    _require(
        ('fit: ' + fit['fitStatus']) in fit['fitText'],
        'the FIT section does not print the status %r: %r'
        % (
            fit['fitStatus'],
            fit['fitText'][:400],
        ),
    )
    assert_beside(fit, 'abel %dx%d' % (width, height))
    if shoot:
        pg.screenshot(path=SHOT_FIT)

    # 7. Escape folds it away; a FRESH context opens it again (per-context
    #    localStorage, so a reload in a new page shows the default)
    pg.keyboard.press('Escape')
    pg.wait_for_timeout(200)
    folded = pg.evaluate("() => getComputedStyle(document.getElementById('mvr-panel')).display")
    _require(folded == 'none', 'Escape did not fold the panel: display=%r' % folded)

    pg2 = br.new_context(viewport={'width': width, 'height': height}).new_page()
    pg2.on('pageerror', lambda e: errs.append('pageerror(reload): ' + str(e)))
    pg2.goto(URL, wait_until='load', timeout=120_000)
    fresh, _ = wait_ready(pg2)
    _require(
        fresh['panelOpen'] and fresh['panelDisplay'] != 'none',
        'a fresh context did not open the panel by default: display=%r' % fresh['panelDisplay'],
    )
    assert_beside(fresh, 'fresh %dx%d' % (width, height))
    if shoot:
        pg2.screenshot(path=SHOT)

    real = [e for e in errs if 'favicon' not in e]
    out = {
        'viewport': '%dx%d' % (width, height),
        'boot_name': boot['cname'].strip(),
        'boot_actor': boot['actor'],
        'name': st['cname'].strip(),
        'actor': st['actor'],
        'motion': st['motion'],
        'glb': st['glb'],
        'bones': st['bones'],
        'duration_s': st['dur'],
        'mixer_time_t0': round(t0, 4),
        'mixer_time_t1': round(t1, 4),
        'advanced_s': round(t1 - t0, 4),
        'clips_in_library': st['clips'],
        'clips_in_panel': st['panelClips'],
        'panel_sections': st['panelSections'],
        'panel_open_by_default': bool(fresh['panelOpen']),
        'panel_folds_on_escape': folded == 'none',
        'panel_rect': fit['panelRect'],
        'frame_rect': fit['frameRect'],
        'fit_status': fit['fitStatus'],
        'fit_section': ' '.join(fit['fitText'].split()),
        'status_line': st['status'].strip(),
        'video_element_shown': st['videoShown'] == 'block',
        'webgl_failed': st['glFailed'],
        'pageerrors': real,
        'waited_boot_s': waited // 1000,
        'waited_abel_s': waited_abel // 1000,
    }
    br.close()
    _require(not out['pageerrors'], out['pageerrors'])
    _require(not out['video_element_shown'], 'the tab opened on a VIDEO, not the skeleton')
    return out


if __name__ == '__main__':  # the CLI lives in check_movement_rig_cli
    from zyg_workflows.tools.studio_verify.check_movement_rig_cli import main as _cli_main

    raise SystemExit(_cli_main())
