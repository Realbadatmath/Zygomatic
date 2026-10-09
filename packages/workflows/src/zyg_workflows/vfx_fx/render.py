# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Output formats and the render jobs (vfx_fx.py lines 3373-3625)."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid

from zyg_workflows.vfx_fx.constants import (
    _zyg_log,
    JOBLOG,
    FFMPEG,
    DERIVED_PACK,
)
from zyg_workflows.vfx_fx.registry import (
    _n,
)
from zyg_workflows.vfx_fx.chain import (
    OP_BY_ID,
    normalise_stack,
    compile_chain,
    probe,
    source_ctx,
    build_graph,
)

# ── output formats ──────────────────────────────────────────────────────────
# h264 is on the list because most elements do not need a matte and it is a
# tenth the size.  It is also the one that will quietly throw an element's alpha
# away, so it is labelled with that rather than left to be discovered in a shot.
FORMATS = {
    'webm_alpha': {
        'lb': 'WebM VP9 + alpha',
        'ext': '.webm',
        'alpha': True,
        'note': 'The only browser-playable format with a matte. Slow to encode.',
        'args': ['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-b:v', '0', '-row-mt', '1', '-auto-alt-ref', '0'],
    },
    'prores4444': {
        'lb': 'ProRes 4444 + alpha',
        'ext': '.mov',
        'alpha': True,
        'note': 'The master. Big, fast to encode, opens in everything.',
        'args': ['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0'],
    },
    'h264': {
        'lb': 'h264 (no alpha)',
        'ext': '.mp4',
        'alpha': False,
        'note': 'NO ALPHA CHANNEL EXISTS in h264 — a matte is discarded, '
        'not flattened. Only for an element that fills the frame.',
        'args': ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'slow', '-movflags', '+faststart'],
    },
    'png': {
        'lb': 'PNG + alpha',
        'ext': '.png',
        'alpha': True,
        'still': True,
        'note': 'A single frame, lossless, with its matte.',
        'args': ['-c:v', 'png', '-frames:v', '1'],
    },
}

JOBS = {}
_JOBS_LOCK = threading.Lock()


def _slug(t):
    return re.sub(r'[^a-z0-9]+', '_', str(t).lower()).strip('_')[:48] or 'element'


def _quality_args(fmt, q):
    if fmt in ('webm_alpha', 'h264'):
        return ['-crf', str(int(q))]
    if fmt == 'prores4444':
        # prores_ks quality is 0 (best) to 32; the UI's 0-51 CRF scale is mapped
        # rather than shown twice, so one slider means one thing everywhere.
        return ['-qscale:v', str(max(0, min(32, int(round(q * 32 / 51)))))]
    return []


def start_render(cat, fn, stack, opts=None):
    """Bake the stack into a NEW row in the same library. Returns {ok, id}.

    The source is never written to.  An edit that overwrote its own master
    would be one bad stack away from losing an element nobody can download
    again -- half this library came off archive.org items and a MediaFire link
    that has to be resolved by hand."""
    opts = opts or {}
    fp, ctx = source_ctx(cat, fn)
    st, dropped = normalise_stack(stack, ctx['kind'])
    if not [o for o in st if o.get('on', True)]:
        return {'ok': False, 'error': 'the stack is empty — nothing to bake'}

    fmt = str(opts.get('format') or ('png' if ctx['kind'] == 'image' else 'webm_alpha'))
    if fmt not in FORMATS:
        return {'ok': False, 'error': f'unknown output format {fmt}'}
    F = FORMATS[fmt]
    if ctx['kind'] == 'image' and not F.get('still'):
        return {'ok': False, 'error': f'{F["lb"]} is a video format; this source is a still'}

    from zyg_workflows import vfx_ingest as vi

    name = str(opts.get('name') or '').strip()
    base = _slug(name or (os.path.splitext(fn)[0] + '_fx'))
    out_fn = f'fx_{base}_{uuid.uuid4().hex[:6]}{F["ext"]}'
    out_fp = os.path.join(vi._libdir(cat), out_fn)

    tail = ''
    if opts.get('out_w') and opts.get('out_h'):
        tail = (
            f'scale={int(opts["out_w"])}:{int(opts["out_h"])}:'
            f'force_original_aspect_ratio=decrease:flags=lanczos,format=rgba,'
            f'pad={int(opts["out_w"])}:{int(opts["out_h"])}:(ow-iw)/2:(oh-ih)/2:color=black@0'
        )
    graph, out_label = build_graph(st, ctx, maxw=0)
    if tail:
        graph, out_label = compile_chain(st, ctx, tail=tail)

    cmd = [
        FFMPEG,
        '-hide_banner',
        '-nostdin',
        '-y',
        '-i',
        fp,
        '-filter_complex',
        graph,
        '-map',
        f'[{out_label}]',
        '-an',
    ]
    if opts.get('fps') and ctx['kind'] == 'video':
        cmd += ['-r', _n(float(opts['fps']))]
    cmd += list(F['args']) + _quality_args(fmt, float(opts.get('crf', 23)))
    cmd += ['-progress', 'pipe:1', '-nostats', out_fp]

    jid = uuid.uuid4().hex[:12]
    job = {
        'id': jid,
        'state': 'running',
        'cat': cat,
        'src': fn,
        'out': out_fn,
        'fmt': fmt,
        'started': time.time(),
        'pct': 0.0,
        'frame': 0,
        'dropped': dropped,
        'graph': graph,
        'err': '',
        'total_frames': ctx['nframes'] or int(round(ctx['dur'] * ctx['fps'])) or 1,
        'ops': [o['op'] for o in st if o.get('on', True)],
    }
    with _JOBS_LOCK:
        JOBS[jid] = job
    threading.Thread(target=_render_worker, args=(job, cmd, out_fp, cat, fn, st, ctx, fmt), daemon=True).start()
    return {'ok': True, 'id': jid, 'out': out_fn}


def _render_worker(job, cmd, out_fp, cat, src_fn, st, ctx, fmt):
    try:
        os.makedirs(JOBLOG, exist_ok=True)
        logp = os.path.join(JOBLOG, job['id'] + '.log')
        with open(logp, 'w', encoding='utf-8') as lg:
            lg.write(' '.join(cmd) + '\n\n')
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=lg, text=True)
            for line in proc.stdout:
                if line.startswith('frame='):
                    try:
                        job['frame'] = int(line.split('=', 1)[1])
                        job['pct'] = min(99.0, 100.0 * job['frame'] / max(1, job['total_frames']))
                    except ValueError as _exc:
                        _zyg_log.debug('unparsable ffmpeg progress line ignored: %s', _exc)
            rc = proc.wait()
        if rc != 0 or not os.path.isfile(out_fp) or os.path.getsize(out_fp) < 64:
            tailtxt = ''
            try:
                with open(logp, encoding='utf-8') as lg:
                    tailtxt = ''.join(lg.readlines()[-6:]).strip()
            except OSError as _exc:
                _zyg_log.warning('ffmpeg log tail unreadable, reporting the exit code only: %s', _exc)
            job.update(state='error', err=tailtxt or f'ffmpeg exited {rc}')
            if os.path.isfile(out_fp):
                os.remove(out_fp)
            return
        _register(job, out_fp, cat, src_fn, st, ctx, fmt)
        job.update(state='done', pct=100.0, bytes=os.path.getsize(out_fp), ended=time.time())
    except Exception as ex:  # noqa: BLE001
        job.update(state='error', err=f'{type(ex).__name__}: {ex}')


def _register(job, out_fp, cat, src_fn, st, ctx, fmt):
    """Write the derived file's sidecar row.

    LICENCE IS INHERITED, NOT RE-ASSERTED.  A grade does not make a
    non-commercial source commercial, and the derived row carries the source's
    licence, its transform state and its no-ai-training flag verbatim, plus
    `derived_from` naming the file it came out of -- so a licence read on the
    derivative lands on the same answer as a read on the master, and can see
    which master to check ([[feedback_licence_policy]])."""
    from zyg_workflows import vfx_ingest as vi

    meta = vi.load_sidecar()
    src = meta.get(f'{cat}/{src_fn}') or {}
    info = probe(out_fp) or {}
    poster = ''
    if fmt != 'png':
        poster = os.path.splitext(os.path.basename(out_fp))[0] + '.jpg'
        try:
            subprocess.run(
                [
                    FFMPEG,
                    '-hide_banner',
                    '-v',
                    'error',
                    '-y',
                    '-i',
                    out_fp,
                    '-frames:v',
                    '1',
                    '-vf',
                    'scale=480:-1',
                    os.path.join(os.path.dirname(out_fp), poster),
                ],
                capture_output=True,
                timeout=120,
            )
        except Exception:  # noqa: BLE001
            poster = ''
    rec = {
        'cat': cat,
        'file': os.path.basename(out_fp),
        'kind': 'image' if fmt == 'png' else 'video',
        'name': (src.get('name') or src_fn)
        + ' — '
        + ' + '.join(OP_BY_ID[o]['lb'] for o in job['ops'][:3])
        + ('…' if len(job['ops']) > 3 else ''),
        'pack_label': DERIVED_PACK,
        'group': src.get('group') or 'Other',
        'bytes': os.path.getsize(out_fp),
        'w': info.get('w') or 0,
        'h': info.get('h') or 0,
        'fps': info.get('fps') or 0,
        'dur': info.get('dur') or 0,
        'poster': poster,
        # inherited verbatim -- see the docstring
        'licence': src.get('licence', ''),
        'license_id': src.get('license_id', ''),
        'transform': src.get('transform', ''),
        'no_ai_training': src.get('no_ai_training', False),
        'eula_note': src.get('eula_note', ''),
        'source': src.get('source', ''),
        'master': src.get('master', ''),
        # the recipe, so a derived row can always say what was done to it
        'derived_from': f'{cat}/{src_fn}',
        'derived_at': int(time.time()),
        'derived_format': fmt,
        'recipe': [{'op': o['op'], 'p': o['p']} for o in st if o.get('on', True)],
        'recipe_graph': job['graph'],
    }
    vi.save_sidecar({f'{cat}/{rec["file"]}': rec})


def job_status(jid):
    j = JOBS.get(str(jid or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    return {'ok': True, **{k: v for k, v in j.items() if k != 'graph'}}


def recent_jobs(n=20):
    return sorted(
        ({k: v for k, v in j.items() if k != 'graph'} for j in JOBS.values()),
        key=lambda j: j.get('started', 0),
        reverse=True,
    )[:n]
