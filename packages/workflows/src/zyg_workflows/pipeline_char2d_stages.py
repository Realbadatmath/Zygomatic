# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages behind `pipeline_char2d.run_char2d`, one function per step.

`run_char2d` was a 419-line list of fourteen numbered stages. The stages that
carried real work moved here; the runner keeps the order, the card updates, the
`guard()` stop checks and the two `_seal.seal` calls (which is what
`scripts/check_seal_hooks.py` pins to `run_char2d` itself).

IMPORT DIRECTION IS ONE-WAY. This module imports the runner's helpers and
constants at module level; `run_char2d` imports this module *lazily*, inside
the function. Reversing either half closes the cycle.

`collect_anchors`, `gate_verdict`, `gesture_manifest_entry`, `build_manifest`
and `demo_reel_args` are pure — values in, a dict/list/str out, no disk, no
subprocess — which is what makes them unit-testable
(`tests/test_pipeline_char2d_helpers.py`).
"""

from __future__ import annotations

import glob
import json
import os

from zyg_workflows import char2d_mouth as M
from zyg_workflows.pipeline_char2d import (
    DEFAULT_WAV,
    FPS,
    GATE_VIEWS,
    GESTURE_DIR,
    GESTURE_RES,
    GESTURE_VIEWS,
    HARD_HAND_TAGS,
    LICENCES,
    VIEW_RES,
    VIEWS,
    _blender,
    _HERE,
    _on_white,
    _pipe_frames,
)


# ── 2-4. one Blender: body → cel shader → six views ──────────────────────────


def build_views(out_dir, brief_path, log, stage, should_abort):
    """Build the body, cel-shade it and render the six views in one Blender.

    The card advances on the subprocess's own progress prints — 'CLASSIFY …'
    ends the body build, 'CAMERA …' starts the render — so the three stage
    names are real boundaries in one process rather than three sleeps.

    Returns (views_json, blend, views_doc, views, res_wh). Raises RuntimeError
    when Blender exits non-zero or wrote neither of the two files it must.
    """
    seen = {'classify': False, 'camera': False}

    def _progress(line):
        if line.startswith(('RIG ', 'LANDMARKS ', 'CLASSIFY ', 'CAMERA ', 'MOUTH ', 'VIEW ', 'SAVED ', 'DONE ')):
            log(line[:180])
        if line.startswith('CLASSIFY ') and not seen['classify']:
            seen['classify'] = True
            stage('Cel Shader + Ink Lines')
        elif line.startswith('CAMERA ') and not seen['camera']:
            seen['camera'] = True
            stage('Six-View Render')

    rc = _blender(
        [
            '-b',
            '--python',
            'blender_scripts/char2d_build.py',
            '--',
            '--brief',
            brief_path,
            '--out',
            out_dir,
            '--views',
            ','.join(VIEWS),
            '--res',
            VIEW_RES,
        ],
        log,
        on_line=_progress,
        should_abort=should_abort,
    )
    if not seen['camera']:
        stage('Six-View Render')
    if rc != 0:
        raise RuntimeError('char2d_build.py exited %d' % rc)
    views_json = os.path.join(out_dir, 'views.json')
    blend = os.path.join(out_dir, 'character.blend')
    for path in (views_json, blend):
        if not os.path.isfile(path):
            raise RuntimeError('char2d_build.py wrote no %s' % os.path.basename(path))
    with open(views_json, 'r', encoding='utf-8') as fh:
        views_doc = json.load(fh)
    views = views_doc['views']
    res_wh = tuple(views_doc.get('res') or (1024, 1536))
    log(
        'views: %d rendered at %dx%d, height %.3f m'
        % (len(views), res_wh[0], res_wh[1], views_doc.get('height_m', 0.0))
    )
    return views_json, blend, views_doc, views, res_wh


# ── 6. Mouth Anchors ─────────────────────────────────────────────────────────


def collect_anchors(views):
    """The mouth/chin/head-top anchor row per view, keyed by view name.

    Pure: the measured pixels come straight off the views.json entries, and the
    view kind and foreshortened mouth width come from `char2d_mouth`'s geometry.
    """
    anchors = {}
    for name, entry in views.items():
        anchors[name] = {
            'yaw': entry['yaw'],
            'file': entry['file'],
            'kind': M.view_kind(entry['yaw']),
            'mouth_px': entry['mouth_px'],
            'mouth_w_px': entry['mouth_w_px'],
            'effective_mouth_w_px': round(M.effective_mouth_w(entry), 2),
            'chin_px': entry['chin_px'],
            'head_top_px': entry['head_top_px'],
        }
    return anchors


def anchors_line(anchors):
    """The one-line log summary of an anchor table."""
    return 'anchors: ' + ', '.join(
        '%s %s/%.1fpx' % (n, a['kind'], a['effective_mouth_w_px']) for n, a in anchors.items()
    )


# ── 8. Lip-Sync Timing (Rhubarb) ─────────────────────────────────────────────


def resolve_wav(options):
    """The lip-sync WAV for this run: the `wav` option, else the house default.

    A relative path is taken against the package directory. Raises RuntimeError
    when the file is not there — a talking clip with no audio is not a clip.
    """
    wav = str(options.get('wav') or DEFAULT_WAV)
    if not os.path.isabs(wav):
        wav = os.path.join(_HERE, wav)
    if not os.path.isfile(wav):
        raise RuntimeError('lip-sync WAV not found: %s' % wav)
    return wav


def timing_line(timing):
    """The one-line log summary of a Rhubarb timing document."""
    return 'timing: %.2f s, %d frames, %d changes (%.2f/s), min run %d' % (
        timing['duration_s'],
        timing['n_frames'],
        timing['changes'],
        timing['changes_per_s'],
        timing['min_run_frames'],
    )


# ── 10. Gesture Keyframes ────────────────────────────────────────────────────


def render_gesture_keyframes(blend, out_dir, log, should_abort, guard):
    """Pose and render every gesture from the five gesture views.

    One Blender per gesture, reusing the saved character.blend; the idle pose is
    left out because it is the rest state, not a gesture. Returns
    (gestures_dir, rendered) where each row is {'spec', 'render'}.
    """
    gesture_paths = [
        p
        for p in sorted(glob.glob(os.path.join(GESTURE_DIR, '*.json')))
        if not os.path.basename(p).startswith('00_idle')
    ]
    if not gesture_paths:
        raise RuntimeError('no gestures in %s' % GESTURE_DIR)
    gestures_dir = os.path.join(out_dir, 'gestures')
    os.makedirs(gestures_dir, exist_ok=True)
    rendered = []
    for path in gesture_paths:
        guard()
        with open(path, 'r', encoding='utf-8') as fh:
            spec = json.load(fh)
        rc = _blender(
            [
                '-b',
                blend,
                '--python',
                'blender_scripts/char2d_render_pose.py',
                '--',
                '--gesture',
                path,
                '--out',
                gestures_dir,
                '--views',
                ','.join(GESTURE_VIEWS),
                '--res',
                GESTURE_RES,
            ],
            log,
            on_line=lambda ln: log(ln[:180]) if ln.startswith('DONE ') else None,
            should_abort=should_abort,
        )
        if rc != 0:
            raise RuntimeError('char2d_render_pose.py exited %d for %s' % (rc, spec['name']))
        render_json = os.path.join(gestures_dir, spec['name'], 'render.json')
        if not os.path.isfile(render_json):
            raise RuntimeError('no render.json for %s' % spec['name'])
        with open(render_json, 'r', encoding='utf-8') as fh:
            rendered.append({'spec': spec, 'render': json.load(fh)})
    log(
        'gesture keyframes: %d gestures, %d stills'
        % (len(rendered), sum(len(g['render']['keys']) * len(GESTURE_VIEWS) for g in rendered))
    )
    return gestures_dir, rendered


# ── 11. Hand Anatomy Gate ────────────────────────────────────────────────────


def run_hand_gate(rendered, gestures_dir, out_dir):
    """MediaPipe hand QC over every rendered key, from the palm-side views only.

    Returns the gate dict (views, frames, flagged, hard, unknown, n_frames, ok);
    writes nothing. `expected_hands` is deliberately NOT set: how many hands a
    3/4 view should show is a judgement this runner cannot make, and guessing it
    turns a missed detection into 'hand-count-mismatch' at severity hard — a
    failed run on the strength of a guess.
    """
    from zyg_workflows import anatomy_qc

    gate = {'views': list(GATE_VIEWS), 'frames': [], 'flagged': [], 'hard': [], 'unknown': 0}
    for item in rendered:
        name = item['spec']['name']
        for key in item['render']['keys']:
            for view in GATE_VIEWS:
                fname = key['files'].get(view)
                if not fname:
                    continue
                img = os.path.join(gestures_dir, name, fname)
                out = anatomy_qc.qc_hands_frame(img)
                row = {
                    'gesture': name,
                    'key': key['n'],
                    'key_name': key['name'],
                    'view': view,
                    'file': os.path.relpath(img, out_dir),
                    'ok': out.get('ok'),
                    'detected': out.get('detected'),
                    'issues': [{'tag': i['tag'], 'severity': i['severity']} for i in (out.get('issues') or [])],
                }
                gate['frames'].append(row)
                if out.get('ok') is None:
                    gate['unknown'] += 1
                elif out.get('ok') is False:
                    gate['flagged'].append(row)
                for issue in out.get('issues') or []:
                    if issue.get('tag') in HARD_HAND_TAGS and issue.get('severity') == 'hard':
                        gate['hard'].append(dict(row, tag=issue['tag']))
    gate['n_frames'] = len(gate['frames'])
    gate['ok'] = not gate['flagged'] and not gate['hard']
    return gate


def _frame_lines(rows):
    """'<gesture> k<n> <view>: <tag,tag>' for each flagged or hard frame."""
    return [
        '%s k%d %s: %s' % (r['gesture'], r['key'], r['view'], ','.join(i['tag'] for i in r['issues'])) for r in rows
    ]


def gate_verdict(gate):
    """Classify a hand gate result. Returns (result_updates, log_lines). Pure.

    A hard tag is a broken hand, so the job ends red — but the remaining three
    stages run first, so the sprites, the clips and the reel exist to be LOOKED
    at. A gate that deletes the evidence of what it rejected cannot be argued
    with. Anything else the gate reports (chirality ambiguity on a 3/4 view, a
    non-monotonic joint, an implausible bone ratio) ships DEGRADED, flagged.
    """
    if gate['hard']:
        tags = sorted({r['tag'] for r in gate['hard']})
        updates = {
            'hand_gate': 'failed',
            'hand_gate_error': 'hand anatomy gate: %d frame(s) carry a hard tag (%s) — %s'
            % (
                len(gate['hard']),
                ', '.join(tags),
                '; '.join('%s k%d %s' % (r['gesture'], r['key'], r['view']) for r in gate['hard']),
            ),
            'hand_gate_frames': _frame_lines(gate['hard']),
        }
        line = (
            'hand gate: FAILED — %d of %d frames carry %s; the sprites are '
            'still written so the defect can be seen' % (len(gate['hard']), gate['n_frames'], ', '.join(tags))
        )
        return updates, [line]
    if gate['flagged']:
        tags = sorted({i['tag'] for r in gate['flagged'] for i in r['issues']})
        updates = {'hand_gate': 'flagged', 'hand_gate_frames': _frame_lines(gate['flagged'])}
        line = 'hand gate: FLAGGED — %d of %d frames (%s); sprites ship degraded' % (
            len(gate['flagged']),
            gate['n_frames'],
            ', '.join(tags),
        )
        return updates, [line]
    return (
        {'hand_gate': 'clean'},
        ['hand gate: clean over %d frames (%d unverifiable)' % (gate['n_frames'], gate['unknown'])],
    )


# ── 12. Gesture Clips ────────────────────────────────────────────────────────


def encode_gesture_clips(rendered, gestures_dir, out_dir, log, guard):
    """One mp4 per gesture per view, each key held for its own frame count.

    The plates are composited on white once per gesture and reused across the
    five views. Returns (clips, gres): the gesture → view → relative mp4 map and
    the resolution the keys were rendered at.
    """
    gres = tuple(rendered[0]['render'].get('res') or (768, 1152))
    clips = {}
    for item in rendered:
        guard()
        name = item['spec']['name']
        gdir = os.path.join(gestures_dir, name)
        clips[name] = {}
        plates = {}
        for key in item['render']['keys']:
            for view, fname in key['files'].items():
                plates[(key['n'], view)] = _on_white(os.path.join(gdir, fname)).tobytes()
        for view in GESTURE_VIEWS:
            frames = []
            for key in item['render']['keys']:
                buf = plates.get((key['n'], view))
                if buf is None:
                    continue
                frames.extend([buf] * max(1, int(key.get('hold_frames') or 1)))
            if not frames:
                continue
            mp4 = os.path.join(gdir, '%s.mp4' % view)
            _pipe_frames(frames, gres, mp4)
            clips[name][view] = os.path.relpath(mp4, out_dir)
        log(
            'clips: %s -> %d view(s), %d frames'
            % (name, len(clips[name]), sum(max(1, int(k.get('hold_frames') or 1)) for k in item['render']['keys']))
        )
    return clips, gres


# ── 13. Sprite Manifest ──────────────────────────────────────────────────────


def gesture_manifest_entry(spec, render, clips, gestures_dir, out_dir):
    """The sprites.json row for one gesture: its labels, its clips, its keys. Pure."""
    return {
        'label': spec.get('label'),
        'meaning': spec.get('meaning'),
        'hands': spec.get('hands'),
        'reads_well': spec.get('reads_well'),
        'clips': clips.get(spec['name'], {}),
        'keys': [
            {
                'name': k['name'],
                'hold_frames': k.get('hold_frames'),
                'files': {
                    v: os.path.relpath(os.path.join(gestures_dir, spec['name'], f), out_dir)
                    for v, f in k['files'].items()
                },
            }
            for k in render['keys']
        ],
    }


def build_manifest(
    *,
    brief,
    views_doc,
    res_wh,
    views,
    anchors,
    turnaround,
    mouth_files,
    wav,
    timing,
    timing_path,
    talk_mp4,
    hand_gate,
    anatomy_path,
    gate,
    rendered,
    clips,
    gestures_dir,
    out_dir,
):
    """The delivered sprites.json document. Pure: builds the dict, writes nothing.

    Every path in it is relative to *out_dir* except the lip-sync WAV, which is
    an input and may live anywhere.
    """
    manifest = {
        'brief': dict(brief),
        'height_m': views_doc.get('height_m'),
        'res': list(res_wh),
        'fps': FPS,
        'views': {n: {'file': e['file'], 'yaw': e['yaw'], 'mouth': anchors[n]} for n, e in views.items()},
        'turnaround': os.path.relpath(turnaround, out_dir),
        'mouth': mouth_files,
        'gestures': {},
        'talk': {
            'wav': wav,
            'timing': os.path.relpath(timing_path, out_dir),
            'clip': os.path.relpath(talk_mp4, out_dir),
            'changes_per_s': timing['changes_per_s'],
        },
        'hand_gate': {
            'verdict': hand_gate,
            'file': os.path.relpath(anatomy_path, out_dir),
            'frames': gate['n_frames'],
            'flagged': len(gate['flagged']),
        },
        'licences': dict(LICENCES),
    }
    for item in rendered:
        spec, render = item['spec'], item['render']
        manifest['gestures'][spec['name']] = gesture_manifest_entry(spec, render, clips, gestures_dir, out_dir)
    return manifest


# ── 14. Demo Reel ────────────────────────────────────────────────────────────


def demo_reel_args(reel, res_wh, demo):
    """ffmpeg args that concat *reel* into *demo*. Pure.

    Every input is scaled to *res_wh*, forced to FPS and resampled to 44.1 kHz
    stereo before the concat — that normalisation is what lets one filter graph
    take the talking clip and the ten gesture clips together instead of eleven
    special cases.
    """
    args = []
    for path in reel:
        args += ['-i', path]
    chains = []
    for i in range(len(reel)):
        chains.append(
            '[%d:v]scale=%d:%d,setsar=1,fps=%d[v%d];'
            '[%d:a]aresample=44100,aformat=channel_layouts=stereo[a%d];' % (i, res_wh[0], res_wh[1], FPS, i, i, i)
        )
    chains.append(''.join('[v%d][a%d]' % (i, i) for i in range(len(reel))))
    chains.append('concat=n=%d:v=1:a=1[v][a]' % len(reel))
    return args + [
        '-filter_complex',
        ''.join(chains),
        '-map',
        '[v]',
        '-map',
        '[a]',
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '20',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        '128k',
        demo,
    ]
