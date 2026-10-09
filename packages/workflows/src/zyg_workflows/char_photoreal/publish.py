#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal.py — a photoreal skin texture for a Character Studio base body.

Verbatim lines 2569-2777 of the original char_photoreal.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import numpy as np

from zyg_workflows.char_photoreal.constants import BODIES, PUB_ROOT, log_to, look_of
from zyg_workflows.char_photoreal.plates import stage_plates, stage_selfcheck, work_dir
from zyg_workflows.char_photoreal.renders import stage_render
from zyg_workflows.char_photoreal.bake import stage_bake

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def stage_publish(body, log, quality=92):
    from PIL import Image

    wd = work_dir(body)
    pd = os.path.join(PUB_ROOT, body)
    os.makedirs(pd, exist_ok=True)
    im = Image.open(os.path.join(wd, 'albedo.png')).convert('RGB')
    im.save(os.path.join(pd, 'albedo.jpg'), quality=quality, subsampling=0)
    man = json.load(open(os.path.join(wd, 'manifest.json')))
    man['albedo'] = 'albedo.jpg'
    look = look_of(body)
    if look == 'ecorche':
        # the grooves between the muscle bellies as relief: a high-pass of the
        # albedo's luminance around mid-grey. The atlas already draws every
        # belly edge as a dark line, so the unsharp residual IS the bump.
        import cv2

        lum = np.asarray(im.convert('L')).astype(np.float32)
        hi = 128.0 + 2.5 * (lum - cv2.GaussianBlur(lum, (0, 0), 6.0))
        Image.fromarray(np.clip(hi, 0, 255).astype(np.uint8)).save(os.path.join(pd, 'bump.jpg'), quality=quality)
        man['bump'] = 'bump.jpg'
        man['look'] = 'ecorche'
    # a contact strip of klein's renders beside the manifest, for the Photoreal
    # panel ("the renders this skin was baked from") — NOT for the Models card:
    # klein photographs the bald base mesh, the card shows the studio's own
    # render with its groom (stage_previews)
    rd = os.path.join(wd, 'renders')
    strip = []
    for vid in ['body_front', 'body_left', 'body_back', 'head_front', 'head_right', 'head_back', 'hand_l', 'eye_l']:
        p = os.path.join(rd, f'{vid}.png')
        if os.path.isfile(p):
            strip.append(Image.open(p).convert('RGB').resize((256, 256), Image.LANCZOS))
    if strip:
        sheet = Image.new('RGB', (256 * len(strip), 256))
        for i, s in enumerate(strip):
            sheet.paste(s, (256 * i, 0))
        sheet.save(os.path.join(pd, 'renders_klein.jpg'), quality=85)
        man['klein_strip'] = 'renders_klein.jpg'
    # card images: keep the studio previews if a previous run wrote them,
    # else fall back to klein's head_front until stage_previews runs
    old = published(body) or {}
    if old.get('previews'):
        for k in ('preview', 'renders_strip', 'previews'):
            if old.get(k):
                man[k] = old[k]
    else:
        hp = os.path.join(rd, 'head_front.png')
        if os.path.isfile(hp):
            Image.open(hp).convert('RGB').resize((512, 512), Image.LANCZOS).save(
                os.path.join(pd, 'preview.jpg'), quality=88
            )
            man['preview'] = 'preview.jpg'
        man['renders_strip'] = man.get('klein_strip', '')
    with open(os.path.join(pd, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=1)
    log(f'[publish] {pd}/albedo.jpg ({os.path.getsize(os.path.join(pd, "albedo.jpg")) // 1024} KB)')
    return man


PREVIEW_PANEL = (480, 640)  # each half of the card's side-by-side strip


def stage_previews(body, log):
    """The Models-card images, shot from the STUDIO (tools_charstudio_screenshot
    .shoot_previews): photoreal skin + char_hair groom + char_eyes eyes, so the
    card shows exactly what stands in the frame.  preview.jpg = head, straight
    on; renders.jpg = full frontal figure (LEFT) beside a three-quarter head.
    Needs the studio server (:8899) and headless Chrome; a failure leaves the
    previous card images in place and is reported, never hidden."""
    from PIL import Image
    from zyg_workflows import tools_charstudio_screenshot as shot

    pd = os.path.join(PUB_ROOT, body)
    mp = os.path.join(pd, 'manifest.json')
    man = published(body)
    if not man:
        raise RuntimeError(f'{body}: nothing published yet — run publish first')
    raw = os.path.join(pd, 'previews')
    log(f'[previews] shooting the studio for {body} ...')
    t0 = time.time()
    r = shot.shoot_previews(raw, body=body)
    if r['errors']:
        log('[previews] page errors: ' + ' | '.join(r['errors'])[:600])
    files = r['files']
    if not (files.get('head_front') and files.get('body_front') and files.get('head_tq')):
        raise RuntimeError(f'previews incomplete: {sorted(files)}')
    if not r['info'].get('hair'):
        raise RuntimeError('the studio stood the model without its groom — refusing a bald card')
    Image.open(files['head_front']).convert('RGB').resize((512, 512), Image.LANCZOS).save(
        os.path.join(pd, 'preview.jpg'), quality=88
    )
    W, H = PREVIEW_PANEL
    sheet = Image.new('RGB', (2 * W, H))
    for i, k in enumerate(['body_front', 'head_tq']):
        sheet.paste(Image.open(files[k]).convert('RGB').resize((W, H), Image.LANCZOS), (i * W, 0))
    sheet.save(os.path.join(pd, 'renders.jpg'), quality=88)
    man['preview'] = 'preview.jpg'
    man['renders_strip'] = 'renders.jpg'
    man['previews'] = {
        'source': 'studio',
        'shots': {k: os.path.relpath(v, pd) for k, v in files.items()},
        'hair_verts': int(r['info'].get('hairVerts') or 0),
        'strip': 'body_front | head_tq',
        'shot': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(mp, 'w', encoding='utf-8') as fh:
        json.dump(man, fh, indent=1)
    log(
        f'[previews] preview.jpg + renders.jpg written ({time.time() - t0:.0f} s, hair verts {man["previews"]["hair_verts"]})'
    )
    return man


def published(body):
    p = os.path.join(PUB_ROOT, body, 'manifest.json')
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


# ── job file for the studio panel ──────────────────────────────────────────
class JobLog:
    def __init__(self, job_dir):
        self.d = job_dir
        self.rec = {'status': 'running', 'stage': '', 'log': [], 'started': time.time(), 'error': '', 'finished': 0.0}
        if job_dir:
            os.makedirs(job_dir, exist_ok=True)
        self.flush()

    def __call__(self, m):
        _zyg_log.info(m)
        self.rec['log'].append(f'{time.strftime("%H:%M:%S")} {m}')
        self.rec['log'] = self.rec['log'][-400:]
        self.flush()

    def stage(self, s):
        self.rec['stage'] = s
        self('== ' + s)

    def check(self):
        if self.d and os.path.exists(os.path.join(self.d, 'ABORT')):
            raise RuntimeError('aborted by the operator')

    def flush(self):
        if not self.d:
            return
        self.rec['heartbeat'] = time.time()
        tmp = os.path.join(self.d, '.job.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(self.rec, fh, indent=1)
        os.replace(tmp, os.path.join(self.d, 'job.json'))

    def done(self, ok, err=''):
        self.rec['status'] = 'done' if ok else 'failed'
        self.rec['error'] = err
        self.rec['finished'] = time.time()
        self.flush()


def run_all(body, log, stage='all', force=False, seed=7):
    stages = ['plates', 'selfcheck', 'render', 'bake', 'publish', 'previews'] if stage == 'all' else [stage]
    if stage == 'all' and look_of(body) == 'ecorche':
        # stage_previews shoots the Character Studio with the char_hair groom
        # on: an écorché wears no hair and is not a Models-card skin
        stages.remove('previews')
    for s in stages:
        if hasattr(log, 'stage'):
            log.stage(s)
        if s == 'plates':
            stage_plates(body, log, force=force)
        elif s == 'selfcheck':
            stage_selfcheck(body, log)
        elif s == 'render':
            stage_render(body, log, seed=seed, force=force, check=getattr(log, 'check', None))
        elif s == 'bake':
            stage_bake(body, log, force=force)
        elif s == 'publish':
            stage_publish(body, log)
        elif s == 'previews':
            stage_previews(body, log)
        else:
            raise ValueError(f'unknown stage {s}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('body', choices=sorted(BODIES))
    ap.add_argument(
        '--stage', default='all', choices=['all', 'plates', 'selfcheck', 'render', 'bake', 'publish', 'previews']
    )
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--job', default='', help='job dir for job.json/ABORT (studio panel)')
    a = ap.parse_args(argv)
    log = JobLog(a.job) if a.job else log_to(None)
    try:
        run_all(a.body, log, stage=a.stage, force=a.force, seed=a.seed)
    except Exception as exc:  # noqa: BLE001
        if a.job:
            log.done(False, f'{type(exc).__name__}: {exc}')
        raise
    if a.job:
        log.done(True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
