# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_char2d.py — dispatch runner for the '2D Character Basics I' workflow.

Additive, in the shape pipeline_kidsmusic already established: register a job in
the shared `_workflow_jobs` registry (so the busy-check, the Kanban poll and the
Live Tail all see it), run the work on a daemon thread, update the card's stage
as it goes.  A new pipeline_type only — it cannot affect an existing pipeline.

Output tree: output/char2d/<job_id>/ — its own folder, per the house rule that
every workflow owns its output directory:

    brief.json          the parsed character brief the build was given
    character.blend     MPFB body + rig, saved by char2d_build.py
    views.json          per-view yaw, file, mouth/chin/head-top anchors, bbox
    views/<view>.png    the six cel-shaded, ink-lined stills
    turnaround.png      the six views stitched left→right by yaw
    anchors.json        the mouth anchors, one entry per view
    mouth/<view>_{closed,mid,open}.png
    timing.json         Rhubarb cues collapsed to three shapes and quantised
    talk/talk_front.mp4 the front view speaking the WAV
    gestures/<g>/<view>_k<n>.png + render.json + <view>.mp4
    gestures/anatomy.json  the hand gate's verdict per rendered key
    sprites.json        the delivered manifest
    demo.mp4            front talking clip + the ten front gesture clips

NO IN-FLIGHT HEARTBEAT.  pipeline_kidsmusic keeps a /var/tmp flag so the health
probe defers a restart while a song renders; this runner deliberately does not.
Every expensive step here is a SUBPROCESS (Blender, ffmpeg) — the Flask process
stays answering :5000 throughout — and a whole run is ~5 minutes, well inside
the probe's patience.  A flag that protects nothing is only a thing to leak.

STAGE HONESTY.  'MPFB Body Build', 'Cel Shader + Ink Lines' and 'Six-View
Render' are ONE Blender subprocess; the card advances by parsing that process's
own progress lines as they arrive: 'CLASSIFY …' (materials + show-mask done)
ends the body build, 'CAMERA …' (which char2d_build prints straight after
setup_render) starts the render.  Real boundaries in the one process, not three
sleeps pretending to be stages.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import traceback
import uuid
import logging as _zyg_logging

from zyg_workflows import provenance_seal as _seal
from zyg_workflows.runtime import ams_iso as _ams_iso, workflow_jobs as _workflow_jobs
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_ROOT = os.path.join(_HERE, 'output', 'char2d')

BLENDER = '/usr/local/bin/blender'
# Every Blender launch on this box goes through the same lock: two headless
# Blenders fighting over the one GPU is how the arch studio used to OOM.
# noqa reason: this exact literal is the package-wide flock path (arch_server_ext/*, scene_shot_run,
# studio_ext_server/*, blender_scripts/* and the tests all name it); a different path here would mean
# two Blenders holding two different locks, which is the OOM the comment above describes.
BLENDER_LOCK = '/tmp/claude-1000/arch_ext_blender.lock'  # nosec B108  # noqa: S108  shared flock path, not a temp file

GESTURE_DIR = os.path.join(_HERE, 'data', 'char2d', 'gestures')
BRIEF_DIR = os.path.join(_HERE, 'data', 'char2d', 'briefs')

VIEWS = ('front', 'front45L', 'front45R', 'profileL', 'profileR', 'back')
# The five views a gesture is rendered from; 'back' is left out because a hand
# gesture read from behind is not a gesture.
GESTURE_VIEWS = ('front', 'front45L', 'front45R', 'profileL', 'profileR')
# The views the hand gate is run on: the camera has to see the palm side for
# MediaPipe to have anything to measure.
GATE_VIEWS = ('front', 'front45L', 'front45R')

VIEW_RES = '1024x1536'
GESTURE_RES = '768x1152'
FPS = 24

# Turnaround order: ascending yaw, i.e. the character turning one way.
TURNAROUND_ORDER = ('front', 'front45L', 'profileL', 'back', 'profileR', 'front45R')

DEFAULT_WAV = os.path.join(_HERE, 'output', 'storyteller', 'scene_second_ledger_intro', 'line_01_abel.wav')

# Card titles the Kanban board matches against (kanban_main.js
# TEMPLATES.char2d_basics_1 — every card's `prompt` is one of these strings).
# bp_pipeline_api.kanban_status maps title → [title.lower()] and matches by
# SUBSTRING, FIRST-MATCH-WINS, so no title here may be a substring of another;
# tests/test_char2d_runner.py pins that.
STAGES = [
    'Character Brief',
    'MPFB Body Build',
    'Cel Shader + Ink Lines',
    'Six-View Render',
    'Turnaround Sheet',
    'Mouth Anchors',
    'Mouth Sprites',
    'Lip-Sync Timing (Rhubarb)',
    'Talking Clip',
    'Gesture Keyframes',
    'Hand Anatomy Gate',
    'Gesture Clips',
    'Sprite Manifest',
    'Demo Reel',
]

# A hand carrying one of these at severity 'hard' is a broken hand, not a
# so-so one: the run fails. Everything else the gate reports (chirality
# ambiguity on a 3/4 view, a non-monotonic joint, an implausible bone ratio)
# marks the run DEGRADED — the sprites still ship, flagged.
HARD_HAND_TAGS = ('fused-fingers', 'hand-count-mismatch', 'chirality-flip')

LICENCES = {
    'mpfb_assets': 'CC0 (MPFB / MakeHuman base meshes and targets)',
    'rhubarb': 'MIT (Rhubarb Lip Sync)',
    'mediapipe': 'Apache-2.0 (MediaPipe hand landmarker)',
}


class Halted(Exception):
    """The operator pressed stop."""


# ── brief parsing ────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b')
_HAIR_CUTS = ('bob', 'short', 'long')
_COLOUR_KEYS = ('skin', 'hair', 'top', 'bottom')


def parse_directive(text):
    """Parse the Run button's one-line brief into a char2d_build brief dict.

    The string the board sends looks like:
        'Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a'
    i.e. name, gender (0 female … 1 male), age in years, height in metres, hair
    cut, then the four colours.  The colours are pulled out by pattern first, so
    they may be separated by spaces, commas or both.
    """
    text = str(text or '').strip()
    if not text:
        raise ValueError('a character brief is required')
    colours = _HEX_RE.findall(text)
    fields = [p.strip() for p in _HEX_RE.sub('', text).split(',')]
    fields = [p for p in fields if p]
    if len(fields) < 5:
        raise ValueError(
            'brief must read "name, gender, age, height_m, hair_cut, '
            '#skin #hair #top #bottom" — got %d field(s) before the colours' % len(fields)
        )
    name, gender, age, height, cut = fields[:5]
    brief = {'name': name}
    for key, raw in (('gender', gender), ('age', age), ('height_m', height)):
        try:
            brief[key] = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError('%s must be a number, got %r' % (key, raw)) from exc
    if not 0.0 <= brief['gender'] <= 1.0:
        raise ValueError('gender must be 0..1 (0 female, 1 male), got %r' % brief['gender'])
    if not 0.5 <= brief['height_m'] <= 2.5:
        raise ValueError('height_m must be in metres, got %r' % brief['height_m'])
    cut = cut.strip().lower()
    if cut not in _HAIR_CUTS:
        raise ValueError('hair_cut must be one of %s, got %r' % ('|'.join(_HAIR_CUTS), cut))
    brief['hair_cut'] = cut
    for key, value in zip(_COLOUR_KEYS, colours):
        brief[key] = value
    return brief


def normalise_brief(brief=None, directive=''):
    """Either half of the request is enough: a dict brief, or the Run string."""
    if isinstance(brief, dict) and brief:
        out = dict(brief)
        if not str(out.get('name') or '').strip():
            raise ValueError('brief has no "name"')
        cut = str(out.get('hair_cut') or 'bob').strip().lower()
        if cut not in _HAIR_CUTS:
            raise ValueError('hair_cut must be one of %s, got %r' % ('|'.join(_HAIR_CUTS), cut))
        out['hair_cut'] = cut
        return out
    return parse_directive(directive)


def describe(brief):
    """The one-line directive a card shows for a brief dict."""
    return '%s, %s, %s, %s, %s, %s' % (
        brief.get('name'),
        brief.get('gender'),
        brief.get('age'),
        brief.get('height_m'),
        brief.get('hair_cut'),
        ' '.join(str(brief.get(k)) for k in _COLOUR_KEYS if brief.get(k)),
    )


# ── job registry plumbing (the pipeline_kidsmusic contract) ──────────────────


def _now_iso():
    return _ams_iso()


def _jobs():
    return _workflow_jobs


def _mk_job(directive, options, brief):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': 'char2d',
        'stop_event': threading.Event(),
        'stage': 'char2d_brief',
        'current_stage': STAGES[0],
        'started': _now_iso(),
        'directive': (directive or '').strip(),
        'model_family': 'sdxl',  # unused here; the poll expects a value
        'pipeline_options': options or {},
        'brief': dict(brief),
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'debug_events': [],
    }
    return pid


def _finish(pid, ok, result=None, error=None):
    """Close a job out. The stop event is read FIRST — a halted run is
    'stopped', not 'completed', and whatever reason the stop path recorded is
    preserved (the same fix pipeline_kidsmusic carries)."""
    j = _jobs().get(pid)
    if not j:
        return
    ev = j.get('stop_event')
    stopped = bool(ev is not None and ev.is_set())
    if stopped:
        j['status'] = 'stopped'
        j['current_stage'] = 'Stopped'
        j['error'] = j.get('error') or error or 'halted by operator'
    else:
        j['status'] = 'completed' if ok else 'failed'
        j['current_stage'] = 'Demo Reel' if ok else 'Error'
        j['error'] = error
    j['result'] = result
    j['ended'] = _now_iso()
    now = time.time()
    for entry in j.get('stage_timeline') or []:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'stopped' if stopped else 'completed' if ok else 'failed'
            entry['ended_at'] = now


def _log_for(pid):
    """Append one Live-Tail event.

    Entries MUST be dicts {level, ts, stage, msg}: `bp_pipeline_api.kanban_status`
    reads `ev.get('level')` off every event of the active job, so appending a
    bare string 500s /api/kanban/status for the WHOLE dashboard.
    """

    def _l(m):
        j = _jobs().get(pid)
        if j is None:
            return
        txt = str(m)[:200]
        low = txt.lower()
        lvl = (
            'WARN'
            if any(
                k in low
                for k in (
                    'fail',
                    'unavailable',
                    'error',
                    'could not',
                    'missing',
                    'halt',
                    'flagged',
                    'degraded',
                    'skipped',
                    'not verified',
                    'refused',
                    'no hands',
                    'gate',
                )
            )
            else 'INFO'
        )
        j.setdefault('debug_events', []).append(
            {
                'level': lvl,
                'ts': time.strftime('%H:%M:%S'),
                'stage': j.get('current_stage') or STAGES[0],
                'msg': txt,
            }
        )

    return _l


def _set_stage(pid, stage):
    """Advance the card and close the previous timeline row, so the card dialog
    has an end to time each stage against."""
    j = _jobs().get(pid)
    if j is None:
        return
    j['current_stage'] = stage
    now = time.time()
    tl = j.setdefault('stage_timeline', [])
    for entry in tl:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'completed'
            entry['ended_at'] = now
    tl.append({'name': stage, 'status': 'running', 'ts': now, 'started_at': now, 'ended_at': None})


# ── helpers ──────────────────────────────────────────────────────────────────


def _blender(args, log, on_line=None, should_abort=None):
    """Run one headless Blender under the shared lock, streaming its output.

    Returns the exit code. `on_line` is called with every stdout line so a
    caller can advance the card on the process's own progress prints.
    """
    cmd = ['flock', BLENDER_LOCK, BLENDER] + list(args)
    log('blender: ' + ' '.join(os.path.basename(a) if a.startswith('/') else a for a in cmd[2:]))
    proc = subprocess.Popen(cmd, cwd=_HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if on_line is not None and line:
                on_line(line)
            if should_abort is not None and should_abort():
                proc.terminate()
                raise Halted('halted during blender')
    finally:
        try:
            proc.stdout.close()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('stdout close before wait skipped: %s', _exc)
    return proc.wait()


def _ffmpeg(args, log):
    cmd = [exe('ffmpeg'), '-y', '-loglevel', 'error'] + list(args)
    res = subprocess.run(cmd, cwd=_HERE, capture_output=True, text=True)
    if res.returncode != 0:
        log('ffmpeg failed: ' + (res.stderr or '')[-300:])
        raise RuntimeError('ffmpeg exit %d' % res.returncode)
    return res


def _pipe_frames(frames_rgb, size, out_mp4, silent_audio=True):
    """Encode a list of raw RGB frame buffers into an h264 clip at FPS.

    A silent AAC track is written by default so every gesture clip has the same
    stream layout as the talking clip — which is what lets the demo reel be one
    concat filter rather than eleven special cases.
    """
    wide, high = size
    cmd = [
        exe('ffmpeg'),
        '-y',
        '-loglevel',
        'error',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        '-s',
        '%dx%d' % (wide, high),
        '-r',
        str(FPS),
        '-i',
        '-',
    ]
    if silent_audio:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100']
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p']
    if silent_audio:
        cmd += ['-c:a', 'aac', '-b:a', '96k', '-shortest']
    cmd += [str(out_mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for buf in frames_rgb:
            proc.stdin.write(buf)
    finally:
        proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError('ffmpeg exit %d writing %s' % (rc, out_mp4))
    return str(out_mp4)


def _on_white(png, size=None):
    from PIL import Image

    img = Image.open(png).convert('RGBA')
    if size and img.size != tuple(size):
        img = img.resize(tuple(size), Image.LANCZOS)
    base = Image.new('RGBA', img.size, (255, 255, 255, 255))
    base.alpha_composite(img)
    return base.convert('RGB')


# ── the stages ───────────────────────────────────────────────────────────────


def run_char2d(brief, out_dir, log, stage, options, should_abort):
    """The whole workflow, in order. Returns the sprites manifest dict.

    Each numbered stage below is a function in `pipeline_char2d_stages`; what
    stays here is the order, the card updates, the stop checks and the two
    content-credential seals (scripts/check_seal_hooks.py pins those to this
    function by name).
    """
    from zyg_workflows import char2d_mouth as M
    from zyg_workflows import pipeline_char2d_stages as _st

    def guard():
        if should_abort():
            raise Halted('halted by operator')

    os.makedirs(out_dir, exist_ok=True)
    result = {'out_dir': out_dir, 'brief': dict(brief)}

    # ── 1. Character Brief ───────────────────────────────────────────────────
    stage('Character Brief')
    brief_path = os.path.join(out_dir, 'brief.json')
    with open(brief_path, 'w', encoding='utf-8') as fh:
        json.dump(brief, fh, indent=2)
    log('brief: %s' % describe(brief))
    guard()

    # ── 2-4. one Blender: body → cel shader → six views ──────────────────────
    stage('MPFB Body Build')
    views_json, blend, views_doc, views, res_wh = _st.build_views(out_dir, brief_path, log, stage, should_abort)
    result['views'] = views_json
    guard()

    # ── 5. Turnaround Sheet ──────────────────────────────────────────────────
    stage('Turnaround Sheet')
    from PIL import Image

    order = [v for v in TURNAROUND_ORDER if v in views]
    cell = (res_wh[0] // 2, res_wh[1] // 2)
    sheet = Image.new('RGB', (cell[0] * len(order), cell[1]), (255, 255, 255))
    for i, name in enumerate(order):
        sheet.paste(_on_white(os.path.join(out_dir, views[name]['file']), cell), (i * cell[0], 0))
    turnaround = os.path.join(out_dir, 'turnaround.png')
    sheet.save(turnaround)
    _seal.seal(turnaround, pipeline='char2d', run_id=os.path.basename(out_dir), log_fn=log)
    log('turnaround: %s (%dx%d)' % (' → '.join(order), *sheet.size))
    result['turnaround'] = turnaround
    guard()

    # ── 6. Mouth Anchors ─────────────────────────────────────────────────────
    stage('Mouth Anchors')
    anchors = _st.collect_anchors(views)
    anchors_path = os.path.join(out_dir, 'anchors.json')
    with open(anchors_path, 'w', encoding='utf-8') as fh:
        json.dump(anchors, fh, indent=2)
    log(_st.anchors_line(anchors))
    result['anchors'] = anchors_path
    guard()

    # ── 7. Mouth Sprites ─────────────────────────────────────────────────────
    stage('Mouth Sprites')
    mouth_dir = os.path.join(out_dir, 'mouth')
    sets = M.draw_all_views(views_json, mouth_dir)
    mouth_files = {s['view']: {k: os.path.relpath(v, out_dir) for k, v in s['files'].items()} for s in sets}
    log('mouth sprites: %d views x %d shapes' % (len(sets), len(M.SHAPES)))
    guard()

    # ── 8. Lip-Sync Timing (Rhubarb) ─────────────────────────────────────────
    stage('Lip-Sync Timing (Rhubarb)')
    wav = _st.resolve_wav(options)
    timing = M.build_timing(wav, fps=FPS)
    timing_path = os.path.join(out_dir, 'timing.json')
    with open(timing_path, 'w', encoding='utf-8') as fh:
        json.dump(timing, fh, indent=2)
    log(_st.timing_line(timing))
    result['timing'] = timing_path
    guard()

    # ── 9. Talking Clip ──────────────────────────────────────────────────────
    stage('Talking Clip')
    talk_dir = os.path.join(out_dir, 'talk')
    talk_mp4 = os.path.join(talk_dir, 'talk_front.mp4')
    clip = M.render_talking_clip(
        os.path.join(out_dir, views['front']['file']), mouth_dir, wav, talk_mp4, fps=FPS, timing=timing
    )
    log('talking clip: %d frames at %d fps -> talk/talk_front.mp4' % (clip['frames'], FPS))
    result['talk'] = talk_mp4
    guard()

    # ── 10. Gesture Keyframes ────────────────────────────────────────────────
    stage('Gesture Keyframes')
    gestures_dir, rendered = _st.render_gesture_keyframes(blend, out_dir, log, should_abort, guard)
    guard()

    # ── 11. Hand Anatomy Gate ────────────────────────────────────────────────
    stage('Hand Anatomy Gate')
    gate = _st.run_hand_gate(rendered, gestures_dir, out_dir)
    anatomy_path = os.path.join(gestures_dir, 'anatomy.json')
    with open(anatomy_path, 'w', encoding='utf-8') as fh:
        json.dump(gate, fh, indent=2)
    updates, gate_lines = _st.gate_verdict(gate)
    result.update(updates)
    for line in gate_lines:
        log(line)
    result['anatomy'] = anatomy_path
    guard()

    # ── 12. Gesture Clips ────────────────────────────────────────────────────
    stage('Gesture Clips')
    clips, _gres = _st.encode_gesture_clips(rendered, gestures_dir, out_dir, log, guard)
    result['clips'] = sum(len(v) for v in clips.values())
    guard()

    # ── 13. Sprite Manifest ──────────────────────────────────────────────────
    stage('Sprite Manifest')
    manifest = _st.build_manifest(
        brief=brief,
        views_doc=views_doc,
        res_wh=res_wh,
        views=views,
        anchors=anchors,
        turnaround=turnaround,
        mouth_files=mouth_files,
        wav=wav,
        timing=timing,
        timing_path=timing_path,
        talk_mp4=talk_mp4,
        hand_gate=result['hand_gate'],
        anatomy_path=anatomy_path,
        gate=gate,
        rendered=rendered,
        clips=clips,
        gestures_dir=gestures_dir,
        out_dir=out_dir,
    )
    sprites_path = os.path.join(out_dir, 'sprites.json')
    with open(sprites_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    log(
        'sprites.json: %d views, %d gestures, %d mouth sets'
        % (len(manifest['views']), len(manifest['gestures']), len(manifest['mouth']))
    )
    result['sprites'] = sprites_path
    guard()

    # ── 14. Demo Reel ────────────────────────────────────────────────────────
    stage('Demo Reel')
    reel = [talk_mp4]
    for item in rendered:
        rel = clips.get(item['spec']['name'], {}).get('front')
        if rel:
            reel.append(os.path.join(out_dir, rel))
    demo = os.path.join(out_dir, 'demo.mp4')
    _ffmpeg(_st.demo_reel_args(reel, res_wh, demo), log)
    _seal.seal(demo, pipeline='char2d', run_id=os.path.basename(out_dir), log_fn=log)
    dur = _probe_duration(demo)
    log('demo reel: %d clips, %.1f s -> demo.mp4' % (len(reel), dur))
    result['demo'] = demo
    manifest['demo'] = {'file': 'demo.mp4', 'clips': len(reel), 'duration_s': round(dur, 2)}
    with open(sprites_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    return result


def _probe_duration(path):
    try:
        out = subprocess.run(
            [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001 — a probe is not the run
        return 0.0


# ── entry point ──────────────────────────────────────────────────────────────


def start_char2d(directive='', pipeline_options=None, brief=None, **_kw):
    """Start one '2D Character Basics I' run.

    `brief` is the structured character brief; `directive` is the Run button's
    one-line form of the same thing. Either is enough.
    """
    opts = dict(pipeline_options or {})
    try:
        parsed = normalise_brief(brief, directive)
    except ValueError as exc:
        return {'error': str(exc)}

    pid = _mk_job(directive or describe(parsed), opts, parsed)
    out_dir = os.path.join(_OUT_ROOT, pid)
    os.makedirs(out_dir, exist_ok=True)
    stop = _jobs()[pid]['stop_event']

    def _run():
        log = _log_for(pid)
        try:
            result = run_char2d(parsed, out_dir, log, lambda s: _set_stage(pid, s), opts, stop.is_set)
            j = _jobs().get(pid)
            if j is not None:
                j['char2d'] = {'name': parsed.get('name'), 'hand_gate': result.get('hand_gate'), 'out_dir': out_dir}
            # The verdict comes from the HAND GATE, not from "run_char2d did not
            # raise": a run whose hands are broken delivered its files and still
            # failed, and the card must say so.
            _finish(
                pid,
                result.get('hand_gate') != 'failed',
                error=result.get('hand_gate_error'),
                result={
                    'out_dir': out_dir,
                    'sprites': result.get('sprites'),
                    'demo': result.get('demo'),
                    'hand_gate': result.get('hand_gate'),
                    'hand_gate_frames': result.get('hand_gate_frames'),
                    'turnaround': result.get('turnaround'),
                    'talk': result.get('talk'),
                    'clips': result.get('clips'),
                },
            )
        except Halted as exc:
            log('halted: %s' % exc)
            _finish(pid, False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — a failed character
            log('failed: %s' % exc)  # must not take the GUI down
            _finish(pid, False, error='%s\n%s' % (exc, traceback.format_exc()[:900]))

    threading.Thread(target=_run, name='char2d-%s' % pid, daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'char2d', 'out_dir': out_dir, 'brief': parsed}
