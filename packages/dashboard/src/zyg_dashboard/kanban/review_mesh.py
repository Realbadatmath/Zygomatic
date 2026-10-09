# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban/review_mesh.py — creature review gate, mesh/prop registries, movement picker, GNM fits, mesh actions, character inspection.

Split verbatim out of ``kanban_server.py`` (lines 83-891) on 2026-10-06; the handler
re-imports every name from here, so ``zyg_dashboard.kanban_server.<name>`` still resolves.
"""

import os
import re
import json
import time
import hashlib
import subprocess
import threading
from urllib.parse import urlsplit as _urlsplit
from zyg_workflows.paths import ZYG_DASHBOARD_URL
from zyg_dashboard.kanban.common import HERE, _CHARS_ROOT, _RUNTIME, _zyg_log

# ── Creature sheet review gate (2026-08-26) ──────────────────────────────────
# The board is served from :8899 but the pipeline API lives on :5000 behind a
# session/token gate, so an Approve button in the page cannot call it directly:
# a cross-origin POST carries no dashboard cookie, and whitelisting a
# state-changing route as public would put "start a GPU training run" on the
# open LAN. This process is same-host, so it forwards the decision itself with
# the shared internal credential — the same hop zero_public_server already makes.
_CREATURE_ROOT = os.path.realpath(
    os.environ.get('ZYG_CREATURE_DATASETS', os.path.expanduser('~/lora-datasets/creatures'))
)
_CREATURE_ID_RE = re.compile(r'^[a-f0-9]{12}$')
# VFX uploads stream to disk, so this cap is about not filling the volume
# by accident rather than about memory.
_VFX_MAX_UPLOAD = int(os.environ.get('ZYG_VFX_MAX_UPLOAD', 8 * 1000**3))
_REC_MAX_UPLOAD = 60 * 1000**2  # ~60 MB — generous for a 10 min mic take
_MAIN_APP = os.environ.get('ZYG_GUI_URL', ZYG_DASHBOARD_URL).rstrip('/')
# ZYG_GUI_URL is operator-set and the forwarders below attach X-Zero-Public-Token to it,
# so the scheme is settled once, here, at import: a file:// or custom-handler URL would
# otherwise be handed the token. The urlopen call sites cite this guard in their noqa.
if _urlsplit(_MAIN_APP).scheme not in ('http', 'https'):
    raise RuntimeError(f'ZYG_GUI_URL must be an http:// or https:// URL, got: {_MAIN_APP}')


def _internal_token() -> str:
    t = os.environ.get('ZERO_PUBLIC_TOKEN', '')
    if t:
        return t
    for envf in (os.path.join(os.path.dirname(os.path.dirname(HERE)), '.env'), os.path.join(HERE, '.env')):
        try:
            with open(envf, encoding='utf-8') as fh:
                for line in fh:
                    if line.startswith('ZERO_PUBLIC_TOKEN='):
                        return line.split('=', 1)[1].strip().strip('"\'')
        except OSError as _exc:
            _zyg_log.debug('%s not readable, looking for the token elsewhere: %s', envf, _exc)
    return ''


_MEDIA_MIME = {
    '.mp4': 'video/mp4',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.vtt': 'text/vtt',
}
_MEDIA_PATH_RE = re.compile(r'^[A-Za-z0-9._/-]{1,400}\.(mp4|png|jpg|jpeg|webp|vtt)$', re.IGNORECASE)

# category key -> (subdir under the char dir, filename filter)
# 2026-08-31: trimmed to the three categories worth reviewing per character —
# the intermediate test-style groups (stitched sheets, OLD training set,
# QC-valve, flywheel expansion, style-preview sweep) added clutter with no
# review value once a character reaches arcane_final. Removed rather than
# hidden so the API stops shipping them entirely.
_CATS = {
    'cells': ('contact_sheet/cells', lambda n: n.startswith('cell_') and 'cand' not in n),
    'tiles': ('contact_sheet/tiles', lambda n: n.startswith('tile') or n.startswith('regen')),
    'arcane_final': ('arcane_instantid', lambda n: True),
}
_CAT_LABELS = {
    'cells': 'Source cells (photoreal)',
    'tiles': 'Cropped tiles',
    'arcane_final': '★ Arcane FINAL (style_arcane + depth-ControlNet)',
}
_CAT_ORDER = ['arcane_final', 'cells', 'tiles']

_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|jpeg|webp)$', re.IGNORECASE)
_IMG_MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}

_LIST_CACHE = {'ts': 0.0, 'data': None}
_NAME_CACHE = {}

# ── Mesh tab (2026-08-05): the mesh-skeleton registry, read-only ─────────────
# Serves geom.mesh_skeletons' registry (the two IMMUTABLE originals + every derived
# character base) and their preview renders. Verification runs on every listing so the
# tab can display, not assume, that the originals are byte-identical to issue.
# 2026-08-05: each entry also carries its geom.anthro gate verdict (rec['anthro']) and
# the path of the full report; _MESH_IMG_RE already admits .json, so the viewer fetches
# anthro_report.json through the same validated path as the previews.
_MESH_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'mesh_skeletons'))
_MESH_CACHE = {'ts': 0.0, 'data': None}
_MESH_IMG_RE = re.compile(r'^[A-Za-z0-9._/-]{1,160}\.(png|json|glb|bin)$')
_MESH_CTYPE = {
    '.png': 'image/png',
    '.json': 'application/json',
    '.glb': 'model/gltf-binary',
    '.bin': 'application/octet-stream',
}


def _mesh_list():
    now = time.time()
    if _MESH_CACHE['data'] is not None and now - _MESH_CACHE['ts'] < 20:
        return _MESH_CACHE['data']
    reg_path = os.path.join(_MESH_ROOT, 'registry.json')
    if not os.path.exists(reg_path):
        return {'originals': {}, 'derived': {}, 'verified': 'no registry yet'}
    try:
        with open(reg_path, encoding='utf-8') as f:
            reg = json.load(f)
    except (OSError, ValueError):
        # registry mid-rewrite by a refresh/derive — serve the last good listing
        if _MESH_CACHE['data'] is not None:
            return _MESH_CACHE['data']
        return {'originals': {}, 'derived': {}, 'verified': 'registry unreadable'}
    # hash-verify the originals for the badge — the check covers the GLB AND every
    # displayed file (previews/mesh3d/params via aux_sha256): display, never assume
    import hashlib

    def _h(p):
        h = hashlib.sha256()
        with open(p, 'rb') as fh:
            for b in iter(lambda: fh.read(1 << 20), b''):
                h.update(b)
        return h.hexdigest()

    status = {}
    for sex, rec in (reg.get('originals') or {}).items():
        d = os.path.join(_MESH_ROOT, rec.get('dir', ''))
        try:
            ok = _h(os.path.join(d, rec.get('glb', ''))) == rec.get('sha256')
            for fn, want in (rec.get('aux_sha256') or {}).items():
                ok = ok and _h(os.path.join(d, fn)) == want
        except OSError:
            ok = False
        status[sex] = 'verified-immutable' if ok else 'HASH MISMATCH'
    reg['verified'] = status
    # The anthropometric verdict travels in the registry entry (rec['anthro']) and the
    # full report is fetched on demand from /mesh/img (which already serves .json). The
    # one thing the registry cannot know is whether that file is still THERE, and a card
    # that offers a panel which then 404s is worse than a card that says 'no report'.
    for sec in ('originals', 'derived'):
        for rec in (reg.get(sec) or {}).values():
            rel = rec.get('anthro_report') or (rec.get('anthro') or {}).get('report')
            rec['anthro_report'] = rel
            rec['anthro_report_present'] = bool(rel and os.path.isfile(os.path.join(_MESH_ROOT, rel)))
    _MESH_CACHE.update(ts=now, data=reg)
    return reg


# ── Prop / creature meshes (2026-08-26) ─────────────────────────────────────
# A SECOND registry, deliberately not folded into mesh_skeletons: that tree is the
# human-body cage line, whose records carry anthropometric gate verdicts and an
# immutable-original contract. A creature has neither, and a card that borrowed those
# fields would be claiming a body gate ran on a Pufferball. Same card shape, own lane,
# own root — and the 3D orbit viewer works unchanged because prop_mesh_library writes
# the same ZM3D mesh3d.bin geom/mesh_skeletons does.
_PROP_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'prop_meshes'))
_PROP_CACHE = {'ts': 0.0, 'data': None}


def _prop_mesh_list():
    """Registered prop/creature meshes, integrity-checked like the skeletons.

    Imported lazily and defensively (same discipline as _ALIB_MOD): a broken or absent
    prop_mesh_library must cost the Mesh tab its props lane, never the whole tab."""
    now = time.time()
    if _PROP_CACHE['data'] is not None and now - _PROP_CACHE['ts'] < 20:
        return _PROP_CACHE['data']
    try:
        from zyg_workflows import prop_mesh_library as _pml

        recs = {r['id']: r for r in _pml.list_assets()}
        status = {aid: ('verified' if v['ok'] else 'HASH MISMATCH') for aid, v in _pml.verify().items()}
    except Exception as exc:  # noqa: BLE001
        out = {'assets': {}, 'verified': {}, 'error': str(exc)}
        _PROP_CACHE.update(ts=now, data=out)
        return out
    for aid, rec in recs.items():
        # The card only needs the summary; 68 file hashes per asset would be most of
        # the payload and nothing reads them client-side.
        rec.pop('sha256', None)
        rec['root'] = 'props'
        rec['integrity'] = status.get(aid, 'unknown')
    out = {'assets': recs, 'verified': status}
    _PROP_CACHE.update(ts=now, data=out)
    return out


# ── Movement Studio (2026-08-31): objects/props inject picker ───────────────
# "Objects" is not a new registry — it is prop_mesh_library reshaped to the
# {id,name,front_image} card shape the character/creature inject pickers
# already use. As of this writing that registry holds exactly one asset (the
# Pufferball); the picker shows whatever is actually registered, not a
# placeholder catalogue.
_MV_OUT_ROOT = os.path.realpath(os.path.join(HERE, 'output', 'movement'))
_MV_JOB_ID_RE = re.compile(r'^[a-f0-9]{12}$')


def _api_movement_objects():
    props = _prop_mesh_list()
    if props.get('error'):
        return {'objects': [], 'error': props['error']}
    out = []
    for aid, rec in (props.get('assets') or {}).items():
        prevs = rec.get('previews') or []
        out.append(
            {
                'id': aid,
                'name': rec.get('name') or aid,
                'kind': rec.get('kind') or 'prop',
                'front_image': ({'p': prevs[0]} if prevs else None),
            }
        )
    out.sort(key=lambda x: x['name'])
    return {'objects': out}


# Library tab (2026-08-31): every movement job, newest first, from its own
# job.json — same "one folder per item, no separate index" shape as
# _api_kidsmusic. Read-only: this never forwards to bp_movement, so a stuck
# GPU job still lets past clips list.
_MV_CACHE = {'ts': 0.0, 'data': None}
_MV_CACHE_TTL = 8.0


def _api_movement_library(force=False):
    now = time.time()
    if not force and _MV_CACHE['data'] and (now - _MV_CACHE['ts']) < _MV_CACHE_TTL:
        return _MV_CACHE['data']
    jobs = []
    try:
        names = os.listdir(_MV_OUT_ROOT)
    except OSError:
        names = []
    for jid in names:
        if not _MV_JOB_ID_RE.match(jid):
            continue
        d = os.path.realpath(os.path.join(_MV_OUT_ROOT, jid))
        if not (d.startswith(_MV_OUT_ROOT + os.sep) and os.path.isdir(d)):
            continue
        try:
            with open(os.path.join(d, 'job.json'), encoding='utf-8') as fh:
                j = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('job %s has no readable job.json, left out of the list: %s', jid, _exc)
            continue
        jobs.append(
            {
                'job_id': jid,
                'status': j.get('status') or 'unknown',
                'subject_type': j.get('subject_type') or '',
                'subject_id': j.get('subject_id') or '',
                'subject_name': j.get('subject_name') or j.get('subject_id') or jid,
                'preset': j.get('preset') or '',
                'mode': j.get('mode') or '',
                'motion_prompt': j.get('motion_prompt') or '',
                'action': j.get('action') or j.get('preset') or '',
                # the WHOLE dial state, so "recall this clip's dials" reproduces the
                # render even after a spec default moves; nondefault is what the card
                # summarises, and is stored rather than recomputed here because this
                # process deliberately does not import movement_studio.
                'params': j.get('params') or {},
                'nondefault': j.get('nondefault') or {},
                'error': j.get('error') or '',
                'has_clip': os.path.isfile(os.path.join(d, 'vace_static.mp4')),
                'started': j.get('started'),
                'updated': j.get('updated') or j.get('ended') or j.get('started'),
            }
        )
    jobs.sort(key=lambda r: r.get('updated') or 0, reverse=True)
    data = {'jobs': jobs, 'count': len(jobs)}
    _MV_CACHE.update({'ts': now, 'data': data})
    return data


# ── GNM head fits (2026-08-21): measurement, NOT a body change ───────────────
# The Phase-1 bridge study fits GNM's identity space to each registered anny head
# and writes results to data/assets/gnm_head/fits/ — a tree the Mesh tab could not
# see, which is why "I changed the meshes" and "the tab looks identical" were BOTH
# true. Nothing here modifies mesh_skeletons; the lane is explicitly labelled so a
# fit render can never be mistaken for a shipped body.
_GNM_ROOT = os.path.realpath(os.path.join(HERE, 'data', 'assets', 'gnm_head'))
_GNM_CACHE = {'ts': 0.0, 'data': None}


def _gnm_fits():
    """Per-body fit metrics + render paths, with the Phase-1 baseline alongside.

    identity_gain_mm is the control arm: fitted face RMS minus the SAME
    similarity scored on GNM's mean head. It is served because the first run of
    this study reported 5-6 mm face RMS as a GO while the identity solve was
    contributing 0.08 mm of it — the number only means something next to its
    control."""
    now = time.time()
    if _GNM_CACHE['data'] is not None and now - _GNM_CACHE['ts'] < 20:
        return _GNM_CACHE['data']

    def _load(sub):
        fp = os.path.join(_GNM_ROOT, sub, 'summary.json')
        try:
            with open(fp, encoding='utf-8') as f:
                return {d['body']: d for d in json.load(f) if 'metrics' in d}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    cur, base = _load('fits'), _load('fits_phase1_baseline')
    rows = []
    for body in sorted(cur) or sorted(base):
        d = cur.get(body) or {}
        m = d.get('metrics') or {}
        renders = []
        for v in range(4):
            rel = f'fits/gnm_fit_{body}_v{v:02d}.png'
            if os.path.isfile(os.path.join(_GNM_ROOT, rel)):
                renders.append(rel)
        rows.append(
            {
                'body': body,
                'metrics': m,
                'renders': renders,
                'date': d.get('date'),
                'baseline': (base.get(body) or {}).get('metrics') or {},
            }
        )
    out = {
        'fits': rows,
        'has_baseline': bool(base),
        'note': 'Phase 1 measurement only - no registered body is modified by this',
    }
    _GNM_CACHE.update(ts=now, data=out)
    return out


# ── Mesh tab ACTIONS (2026-09-02, S05) ──────────────────────────────────────
# The Mesh tab was read-only: two GET routes over a registry that only a CLI
# could change. These three POSTs put derive / reissue / gate behind buttons
# without moving one line of the geometry code — each shells out to the SAME
# command the operator would type, in the SAME interpreter (python3.12, the only
# one that can import Anny; this server runs in the agents venv, which cannot).
#
# Four properties this had to have, because a reissue rewrites a REGISTERED body:
#   1. dry-run first. The GUI's button pair is dry-run then confirm, and the
#      confirm is refused unless a dry run for that body ran in this process.
#   2. one job per body. A lock keyed on the name, not a global one: gating
#      cornelis while abel reissues is fine, two reissues of abel is not.
#   3. names are validated against the REGISTRY, never against a regex alone —
#      an argument that reaches a subprocess must be a value the registry
#      already contains, not merely a string that looks safe.
#   4. the log is a file, streamed to disk as the job runs, so a job that dies
#      leaves its evidence behind.
_MESH_JOBS = os.path.join(_MESH_ROOT, '_jobs')
_MESH_PY = '/usr/bin/python3.12'
_MESH_JOB_ID_RE = re.compile(r'^[a-f0-9]{12}$')
_MESH_HASH_RE = re.compile(
    r'^\s{2,}(?P<name>\S+)\s+(?P<before>[0-9a-f]{8,64})\s*->\s*(?P<after>[0-9a-f]{8,64})'
    r'\s*(?P<verdict>.*)$'
)
_MESH_LOCK = threading.Lock()
_MESH_RUNNING = {}  # name -> job_id, while a job holds it
_MESH_JOBS_MEM = {}  # job_id -> dict
_MESH_DRYRUN_OK = set()  # names whose dry run passed in this process


def _mesh_names():
    """Every name the CLI will accept, off the registry itself."""
    reg = _mesh_list()
    return set(reg.get('originals') or {}) | set(reg.get('derived') or {})


def _mesh_parse_hashes(text):
    """The 'name  BEFORE -> AFTER  verdict' lines mesh_skeletons prints."""
    out = []
    for line in (text or '').splitlines():
        m = _MESH_HASH_RE.match(line.rstrip())
        if m:
            d = m.groupdict()
            d['verdict'] = (d['verdict'] or '').strip()
            out.append(d)
    return out


_MESH_VERDICT_RE = re.compile(
    r'^anthro\s+char=(?P<name>\S+)\s+verdict=(?P<verdict>\w+)\s+'
    r'exit=(?P<exit>-?\d+)'
)


def _mesh_parse_verdict(text):
    """The one summary line geom.anthro prints, as a dict — verdict, the counts
    it reports, and the report path. {} when it printed none (a real crash)."""
    for line in reversed((text or '').splitlines()):
        m = _MESH_VERDICT_RE.match(line.strip())
        if not m:
            continue
        out = {'verdict': m.group('verdict'), 'exit': int(m.group('exit'))}
        for tok in line.split():
            if '=' in tok:
                k, v = tok.split('=', 1)
                if k in (
                    'gates',
                    'pass',
                    'warn',
                    'fail',
                    'error',
                    'missing',
                    'notrun',
                    'blocking',
                    'unrun_blocking',
                    'worst',
                    'json',
                    'alarms',
                    'sha',
                    'sha_stable',
                ):
                    out[k] = v
        # json= is LAST on the line and the report path contains a space
        # (it lives under the legacy tree root), so it is taken as the rest of
        # the line rather than as a whitespace token.
        if 'json=' in line:
            out['json'] = line.split('json=', 1)[1].strip()
        return out
    return {}


def _mesh_job_run(job_id, argv, name):
    """Run one CLI invocation, streaming to the job log. Never raises."""
    job = _MESH_JOBS_MEM[job_id]
    log_path = job['log']
    try:
        with open(log_path, 'a', encoding='utf-8') as fh:
            fh.write('$ %s\n' % ' '.join(argv))
            fh.flush()
            p = subprocess.Popen(argv, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            buf = []
            for line in p.stdout:
                buf.append(line)
                fh.write(line)
                fh.flush()
            rc = p.wait()
        text = ''.join(buf)
        # geom.anthro exits 2 for a FAIL verdict. That is a RESULT, not a broken
        # job, and reporting it as an error would hide the one thing the button
        # exists to show. Only the gate is allowed that reading, and only when
        # it actually printed a verdict line.
        verd = _mesh_parse_verdict(text)
        ok = rc == 0 or (job.get('kind') == 'gate' and rc == 2 and verd.get('verdict'))
        job.update(
            status='done' if ok else 'error',
            rc=rc,
            verdict=verd,
            hashes=_mesh_parse_hashes(text),
            tail=text[-8000:],
            ended=time.time(),
        )
        if rc == 0 and job.get('dry_run'):
            _MESH_DRYRUN_OK.add(name)
        if rc == 0 and job.get('kind') == 'reissue' and not job.get('dry_run'):
            _MESH_CACHE['data'] = None  # the card must stop showing the old hash
            _MESH_DRYRUN_OK.discard(name)
    except Exception as exc:  # noqa: BLE001
        job.update(status='error', rc=-1, error=str(exc), ended=time.time())
    finally:
        with _MESH_LOCK:
            if _MESH_RUNNING.get(name) == job_id:
                _MESH_RUNNING.pop(name, None)


def _mesh_job_start(kind, name, argv, dry_run=False):
    """-> (body, http_code). Refuses a second concurrent job on the same body."""
    os.makedirs(_MESH_JOBS, exist_ok=True)
    with _MESH_LOCK:
        if name in _MESH_RUNNING:
            return {'error': f'{name} already has a job running', 'job_id': _MESH_RUNNING[name]}, 409
        job_id = hashlib.sha256(f'{kind}{name}{time.time()}'.encode()).hexdigest()[:12]
        _MESH_RUNNING[name] = job_id
    job = {
        'job_id': job_id,
        'kind': kind,
        'name': name,
        'dry_run': bool(dry_run),
        'argv': argv,
        'status': 'running',
        'started': time.time(),
        'log': os.path.join(_MESH_JOBS, f'{job_id}.log'),
        'hashes': [],
        'rc': None,
    }
    _MESH_JOBS_MEM[job_id] = job
    threading.Thread(target=_mesh_job_run, args=(job_id, argv, name), name=f'mesh-{kind}-{job_id}', daemon=True).start()
    return {'ok': True, 'job_id': job_id, 'log': job['log']}, 200


def _mesh_list_scoped(scope):
    """Origin+gender-scoped view over _mesh_list()'s cached full registry —
    filtering happens AFTER the cache read (mirrors _api_list_all()/_api_list()
    above) so the two scopes can never contaminate each other through the
    shared 20s cache.

    scope=='medusa' -> only derived characters that are BOTH Medusa-origin
    (is_medusa_char) AND female-based (params.base=='female'); the two
    immutable ORIGINALS (male/female template bodies, not tied to any
    character) are dropped entirely — they're not "characters" at all, so
    "female-only" doesn't strictly apply, but the operator asked not to see
    them mixed in here regardless. Every other scope value -> the full,
    unfiltered registry (existing/default behaviour, unchanged).
    """
    reg = _mesh_list()
    if scope != 'medusa':
        props = _prop_mesh_list()
        out = dict(reg)
        out['props'] = props.get('assets') or {}
        out['props_verified'] = props.get('verified') or {}
        if props.get('error'):
            out['props_error'] = props['error']
        return out
    medusa_ids = _medusa_id_set()
    derived = {}
    for cid, rec in (reg.get('derived') or {}).items():
        cdir = os.path.join(_CHARS_ROOT, cid)
        if not _is_medusa_char(cid, cdir, medusa_ids):
            continue
        if ((rec.get('params') or {}).get('base') or '') != 'female':
            continue
        derived[cid] = rec
    out = dict(reg)
    out['originals'] = {}
    out['derived'] = derived
    out['props'] = {}  # a creature prop is not a Medusa character — never in that scope
    return out


def _safe_char_dir(cid):
    """Return the character's real dir iff cid is safe and the dir is a direct child of the root."""
    if not cid or not _ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(_CHARS_ROOT, cid))
    if d != os.path.join(_CHARS_ROOT, cid):
        return None
    if not (d.startswith(_CHARS_ROOT + os.sep) and os.path.isdir(d)):
        return None
    return d


def _display_name(char_dir, cid):
    n = _NAME_CACHE.get(cid)
    if n is not None:
        return n
    n = cid
    try:
        with open(os.path.join(char_dir, 'character_bible.json'), encoding='utf-8') as f:
            b = json.load(f)
        n = b.get('display_name') or (b.get('identity') or {}).get('name') or cid
    except Exception as _exc:
        _zyg_log.debug('no readable character bible for %s, showing its id: %s', cid, _exc)
    _NAME_CACHE[cid] = n
    return n


_FACET_CACHE = {}  # cid -> (bible_mtime, {'render_style':..,'gender':..})


def _char_facets(char_dir, cid):
    """The two bible fields the Library board files a character by:
    style_profile.render_style and identity.gender. Cached on the bible's own
    mtime rather than forever (unlike _NAME_CACHE) because Character Studio
    writes these fields back — a card must move shelves when its bible does."""
    try:
        bp = os.path.join(char_dir, 'character_bible.json')
        mt = os.path.getmtime(bp)
    except OSError:
        return {'render_style': '', 'gender': ''}
    hit = _FACET_CACHE.get(cid)
    if hit and hit[0] == mt:
        return hit[1]
    facets = {'render_style': '', 'gender': ''}
    try:
        with open(bp, encoding='utf-8') as f:
            b = json.load(f)
        facets['render_style'] = str((b.get('style_profile') or {}).get('render_style') or '')
        facets['gender'] = str((b.get('identity') or {}).get('gender') or '')
    except Exception as _exc:
        _zyg_log.debug('no readable character bible for %s, facets stay empty: %s', cid, _exc)
    _FACET_CACHE[cid] = (mt, facets)
    return facets


def _runtime_status(cid):
    try:
        with open(os.path.join(_RUNTIME, f'contact_sheet_{cid}.json'), encoding='utf-8') as f:
            j = json.load(f)
        return {
            'status': j.get('status'),
            'stage': j.get('stage'),
            'current': j.get('current_stage'),
            'cells_done': j.get('sheet_cells_done'),
            'cells_total': j.get('sheet_cells_total'),
            'error': j.get('error'),
        }
    except Exception:
        return {}


def _manifest_qc(char_dir):
    try:
        with open(os.path.join(char_dir, 'contact_sheet', 'manifest.json'), encoding='utf-8') as f:
            m = json.load(f)
        q = m.get('identity_qc') or {}
        return {
            'counts': q.get('counts'),
            'mean': q.get('mean_score'),
            'excluded': q.get('excluded_from_dataset'),
            'total': q.get('total'),
            'approved': m.get('approved'),
        }
    except Exception:
        return {}


def _list_images(char_dir, cat):
    sub, filt = _CATS[cat]
    d = os.path.join(char_dir, sub)
    out = []
    try:
        for n in os.listdir(d):
            if not n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                continue
            if 'cand' in n:
                continue
            try:
                if not filt(n):
                    continue
                mt = os.path.getmtime(os.path.join(d, n))
            except OSError as _exc:
                _zyg_log.debug('%s not statable, left out of the listing: %s', n, _exc)
                continue
            out.append({'name': n, 'mtime': round(mt, 1)})
    except OSError as _exc:
        _zyg_log.debug('%s not listable, returning what was collected: %s', d, _exc)
    out.sort(key=lambda x: x['name'])
    return out


_MEDUSA_IDS_CACHE = {'ts': 0.0, 'ids': None}


def _medusa_id_set():
    """Char ids that have a Medusa runtime state file
    (data/runtime/medusa_<cid>_state.json). Refreshed on a short TTL — NOT
    memoized at import — so a medusa char created after this server started is
    still detected. Excludes medusa_pending.json (no _state suffix)."""
    now = time.monotonic()
    c = _MEDUSA_IDS_CACHE
    if c['ids'] is not None and (now - c['ts']) < 4.0:
        return c['ids']
    ids = set()
    try:
        for fn in os.listdir(_RUNTIME):
            if fn.startswith('medusa_') and fn.endswith('_state.json'):
                cid = fn[len('medusa_') : -len('_state.json')]
                if cid:
                    ids.add(cid)
    except OSError as _exc:
        _zyg_log.debug('%s not listable, the medusa id set stays empty: %s', _RUNTIME, _exc)
    c['ts'] = now
    c['ids'] = ids
    return ids


def _is_medusa_char(cid, cdir, medusa_ids=None):
    """True iff the character originated from the Medusa workflow. Two independent
    detectors, either sufficient: the durable '.medusa_origin' marker co-located
    with the char data, and the runtime state-file glob (early/timing detector)."""
    try:
        if os.path.exists(os.path.join(cdir, '.medusa_origin')):
            return True
    except OSError as _exc:
        _zyg_log.debug('medusa origin marker not checkable in %s, falling back to the id set: %s', cdir, _exc)
    if medusa_ids is None:
        medusa_ids = _medusa_id_set()
    return cid in medusa_ids


def _api_list_all():
    """Full enumeration (cached 4s). Each entry carries an internal is_medusa flag;
    scope filtering happens AFTER the cache read so the two scopes can never
    contaminate each other through this shared cache."""
    now = time.monotonic()
    if _LIST_CACHE['data'] is not None and (now - _LIST_CACHE['ts']) < 4.0:
        return _LIST_CACHE['data']
    out = []
    try:
        entries = os.listdir(_CHARS_ROOT)
    except OSError:
        entries = []
    medusa_ids = _medusa_id_set()
    for cid in entries:
        if not _ID_RE.match(cid):
            continue
        cdir = os.path.join(_CHARS_ROOT, cid)
        csdir = os.path.join(cdir, 'contact_sheet')
        if not os.path.isdir(csdir):
            continue
        try:
            updated = os.path.getmtime(csdir)
        except OSError:
            updated = 0.0
        st = _runtime_status(cid)
        # Character Studio's inject picker needs a thumbnail per card without an
        # N+1 fetch per character, so a preview image rides along on the list
        # payload — same image, same /inspect/img route the detail view already
        # uses. Prefer the finished portrait (arcane_final) but fall back to
        # cells/tiles since most characters haven't been through that pipeline
        # stage yet and would otherwise show no thumbnail at all.
        front = None
        for cat in _CAT_ORDER:
            imgs = _list_images(cdir, cat)
            if imgs:
                front = {'cat': cat, 'name': imgs[0]['name'], 'mtime': imgs[0]['mtime']}
                break
        pic_count = sum(len(_list_images(cdir, cat)) for cat in _CAT_ORDER)
        facets = _char_facets(cdir, cid)
        out.append(
            {
                'id': cid,
                'name': _display_name(cdir, cid),
                'updated': round(updated, 1),
                'render_style': facets['render_style'],
                'gender': facets['gender'],
                'status': st.get('status'),
                'stage': st.get('stage'),
                'active': st.get('status') == 'running',
                'is_medusa': _is_medusa_char(cid, cdir, medusa_ids),
                'front_image': front,
                'pic_count': pic_count,
            }
        )
    out.sort(key=lambda x: x['updated'], reverse=True)
    _LIST_CACHE['ts'] = now
    _LIST_CACHE['data'] = out
    return out


def _api_list(scope):
    """Origin-scoped list. scope=='medusa' -> ONLY medusa chars; every other value
    (empty/unknown/typo) -> ONLY non-medusa chars. Fail-closed: the default view
    never shows medusa. Filter is re-applied per request over the shared cache."""
    want_medusa = scope == 'medusa'
    return [
        {k: v for k, v in r.items() if k != 'is_medusa'}
        for r in _api_list_all()
        if bool(r.get('is_medusa')) == want_medusa
    ]


def _api_char(cid, scope):
    char_dir = _safe_char_dir(cid)
    if not char_dir:
        return None
    # Fail-closed cross-scope guard: the default (non-medusa) view never serves a
    # medusa char, and the medusa view never serves a non-medusa char.
    if _is_medusa_char(cid, char_dir) != (scope == 'medusa'):
        return None
    st = _runtime_status(cid)
    groups = []
    for cat in _CAT_ORDER:
        imgs = _list_images(char_dir, cat)
        if imgs:
            groups.append({'cat': cat, 'label': _CAT_LABELS[cat], 'images': imgs})
    return {
        'id': cid,
        'name': _display_name(char_dir, cid),
        'status': st.get('status'),
        'stage': st.get('stage'),
        'current': st.get('current'),
        'cells_done': st.get('cells_done'),
        'cells_total': st.get('cells_total'),
        'error': st.get('error'),
        'active': st.get('status') == 'running',
        'qc': _manifest_qc(char_dir),
        'groups': groups,
        'server_time': round(time.time(), 1),
    }


def _api_pictures(scope):
    """Flat, cross-character gallery of every generated image for the given
    origin scope — unlike /inspect/api/char (one character at a time), this
    is 'every picture' in one list, across every character that origin has.
    Reuses _api_list_all()'s cache + _list_images() per category rather than
    re-walking disk; images are served through the existing, already
    scope-guarded /inspect/img (same fail-closed check _api_char uses), so no
    new image-serving path is needed."""
    want_medusa = scope == 'medusa'
    out = []
    for r in _api_list_all():
        if bool(r.get('is_medusa')) != want_medusa:
            continue
        cid = r['id']
        char_dir = _safe_char_dir(cid)
        if not char_dir:
            continue
        for cat in _CAT_ORDER:
            for img in _list_images(char_dir, cat):
                out.append(
                    {
                        'id': cid,
                        'name': r['name'],
                        'cat': cat,
                        'label': _CAT_LABELS[cat],
                        'file': img['name'],
                        'mtime': img['mtime'],
                    }
                )
    out.sort(key=lambda x: x['mtime'], reverse=True)
    return {'pictures': out}
