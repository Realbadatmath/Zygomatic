# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""capabilities_hub.py — the Metrics > Capabilities collector and store (:5000/metrics,
subtab Capabilities). 2026-09-27.

What this tab answers: for every step in our workflows, WHICH model or tool can do WHAT,
according to a test we actually ran. One sheet per workflow step; in a sheet the ROWS are
the models/tools that exist in that step and the COLUMNS are the things that were tested.

The store is the interface — the board computes nothing
----------------------------------------------------------------------------------------
One JSON file per step in ``data/runtime/capabilities/<step_id>.json``, written by
``record_sheet({...})`` (or ``python3 capabilities_hub.py record --file x.json``). A step
with no file shows as an empty rail entry saying so; it is never invented.

A cell is never a bare "yes". Every cell carries its own state AND where that state came
from, so the sheet can be read as evidence rather than as an opinion:

    state   yes | no | partial | untested | na       (untested is the honest default)
    grade   measured | receipt | vendor | assumed    (how we know — see GRADES)
    value   the number the test produced (optional), formatted with the column's unit
    note    one line, what the test actually showed
    src     id of an entry in the sheet's ``sources``

Each ROW also carries a computed ``rating`` — the score printed beside the model's name,
read back off that row's own answered cells (see RATING_BANDS / _row_rating). It is never
recorded and never stored: a rating that could be written down could disagree with the
evidence under it. A row with nothing answered carries no rating at all, not a zero.

``grade`` is the honesty lever ([[feedback_measure_before_claim]]): `measured` means a
bench in THIS repo produced the number, `receipt` means a production run recorded it,
`vendor` means a model card claims it and we have not checked, `assumed` means someone
reasoned it. A cell with state `yes` and grade `vendor` is a claim, not a capability, and
the board colours it differently. Nothing here upgrades a grade on its own.

Sheet schema (record_sheet):

    {
      'step': 'vlm_judges',                     # must be a STEPS id
      'question': 'Which judge sees which defect, and how often?',
      'verdict': 'No local VLM sees an extra digit reliably.',   # optional, one line
      'status': 'tested',                       # tested|partial|untested (computed if absent)
      'tested_at': '2026-09-27T12:00:00+02:00', # when the test ran
      'columns': [{'id': 'recall', 'label': 'Defect recall', 'hint': '…',
                   'unit': 'ratio', 'higher_better': True, 'group': 'Overall'}],
      'rows': [{'id': 'qwen3vl_8b', 'label': 'Qwen3-VL 8B FP8', 'role': 'resident judge',
                'licence': 'Apache-2.0', 'where': 'vlm_inspector.py',
                'cells': {'recall': {'state': 'no', 'value': 0.24, 'grade': 'measured',
                                     'note': 'says fine to almost everything', 'src': 'bench'}}}],
      'sheets': [ … extra matrices, same columns/rows shape … ],   # optional
      'notes': ['…'], 'limitations': ['…'],
      'sources': [{'id': 'bench', 'label': 'defect_bench', 'path': '/abs/…'}],
      'inspect': {                              # the Inspect page — inputs AND outputs
        'summary': '…',
        'inputs':  [{'kind': 'image'|'text'|'file', …}],
        'trials':  [{'id','input','expected','results':[{'row','answer','ok','detail'}]}],
        'assets':  [{'id','label','path','kind':'image'}],
      },
    }

The Inspect document is NOT shipped in the board payload — the board is data sheets only
(the operator asked for exactly that). It is fetched per step:

    GET /api/metrics/hub/capabilities                 → rail + sheets
    GET /api/metrics/hub/capabilities?inspect=<step>  → that step's Inspect document
    GET /api/metrics/hub/capabilities?asset=<id>      → one registered picture, base64

``asset`` only resolves ids the sheets themselves registered, so the endpoint cannot be
walked into an arbitrary-file reader.

Hot-reloaded by metrics_hub.section('capabilities') when this file's mtime changes — the
same rule as analytics_hub/test_data_hub, so collector edits need no GUI restart.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging as _zyg_logging
import os
import re
import sys
import time
from datetime import datetime

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = os.path.dirname(os.path.abspath(__file__))
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

try:
    from zyg_dashboard import metrics_hub as mh

    RUNTIME = mh.RUNTIME
    TZ = mh.TZ
except Exception:  # standalone (CLI without the hub)
    from datetime import timezone

    mh = None
    RUNTIME = os.environ.get('ZYG_METRICS_RUNTIME_DIR') or os.path.join(CREWS, 'data', 'runtime')
    TZ = timezone.utc


STORE = os.environ.get('ZYG_CAPABILITIES_DIR') or os.path.join(RUNTIME, 'capabilities')

# ── the workflow, step by step ───────────────────────────────────────────────
# The left rail. `group` is the rail heading; order here is the order shown. A step is
# listed whether or not it has been tested — an untested step is the whole point of the
# tab, so it must be visible, not absent.
GROUPS = [
    {'id': 'text', 'label': 'Story & text'},
    {'id': 'voice', 'label': 'Voice & speech'},
    {'id': 'music', 'label': 'Music'},
    {'id': 'sfx', 'label': 'SFX & audio post'},
    {'id': 'image', 'label': 'Still image'},
    {'id': 'video', 'label': 'Video'},
    {'id': 'motion', 'label': 'Motion & body'},
    {'id': 'three_d', 'label': '3D, scene & architecture'},
    {'id': 'judges', 'label': 'Judges, gates & QC'},
]

STEPS = [
    # ── story & text ──
    {
        'id': 'llm_script',
        'group': 'text',
        'label': 'Script & story writing',
        'hint': 'scene text, dialogue, narration copy',
    },
    {
        'id': 'llm_prompt',
        'group': 'text',
        'label': 'Prompt building & expansion',
        'hint': 'turning a brief into a render prompt',
    },
    {
        'id': 'llm_agents',
        'group': 'text',
        'label': 'Agent & coding models',
        'hint': 'the models that run the studios and write code',
    },
    {
        'id': 'llm_research',
        'group': 'text',
        'label': 'Research & fact lookup',
        'hint': 'period research, sourcing, documentary facts',
    },
    {'id': 'subtitles', 'group': 'text', 'label': 'Subtitles & captions', 'hint': 'timing, line breaks, numerals'},
    # ── voice & speech ──
    {'id': 'tts', 'group': 'voice', 'label': 'Voices (text to speech)', 'hint': 'the engines that speak a line'},
    {
        'id': 'voice_clone',
        'group': 'voice',
        'label': 'Voice cloning & donors',
        'hint': 'building a character voice from a reference',
    },
    {
        'id': 'voice_direction',
        'group': 'voice',
        'label': 'Take direction & prosody',
        'hint': 'emotion, pace, age, wear on a take',
    },
    {
        'id': 'voice_conversion',
        'group': 'voice',
        'label': 'Singing voice conversion',
        'hint': 'putting a trained singer on a sung stem',
    },
    {'id': 'stt', 'group': 'voice', 'label': 'Speech to text', 'hint': 'transcription, alignment, ASR check'},
    {
        'id': 'diarization',
        'group': 'voice',
        'label': 'Diarization & speaker ID',
        'hint': 'who spoke when, and is it the same person',
    },
    # ── music ──
    {'id': 'music_gen', 'group': 'music', 'label': 'Music generation', 'hint': 'song and cue generation from a prompt'},
    {
        'id': 'melody',
        'group': 'music',
        'label': 'Melody, theory & arrangement',
        'hint': 'notes, key, register, instrument choice',
    },
    {'id': 'stem_split', 'group': 'music', 'label': 'Stem separation', 'hint': 'pulling vocal/backing apart'},
    # ── sfx & audio post ──
    {'id': 'sfx_gen', 'group': 'sfx', 'label': 'SFX generation', 'hint': 'making a sound that does not exist yet'},
    {
        'id': 'sfx_library',
        'group': 'sfx',
        'label': 'SFX library & retrieval',
        'hint': 'finding the right recorded sound',
    },
    {
        'id': 'sfx_process',
        'group': 'sfx',
        'label': 'SFX processing & effects rack',
        'hint': 'shaping a sound once we have it',
    },
    {
        'id': 'audio_mix',
        'group': 'sfx',
        'label': 'Mix, loudness & mastering',
        'hint': 'levels, limiter, loudnorm, delivery',
    },
    # ── still image ──
    {'id': 't2i', 'group': 'image', 'label': 'Text to image', 'hint': 'a still from a prompt alone'},
    {
        'id': 'i2i',
        'group': 'image',
        'label': 'Image to image & restyle',
        'hint': 'restyling or editing an existing still',
    },
    {
        'id': 'inpaint',
        'group': 'image',
        'label': 'Inpaint & repair',
        'hint': 'fixing hands, objects, seams inside a frame',
    },
    {
        'id': 'identity',
        'group': 'image',
        'label': 'Identity lock (adapters)',
        'hint': 'keeping the same face across stills',
    },
    {'id': 'controlnet', 'group': 'image', 'label': 'Structural control', 'hint': 'depth, pose and edge conditioning'},
    {'id': 'lora_train', 'group': 'image', 'label': 'LoRA training', 'hint': 'teaching a character or a style'},
    {'id': 'upscale', 'group': 'image', 'label': 'Upscale & restoration', 'hint': 'more pixels without new invention'},
    # ── video ──
    {'id': 'i2v', 'group': 'video', 'label': 'Image to video', 'hint': 'moving a still we already approved'},
    {'id': 't2v', 'group': 'video', 'label': 'Text to video', 'hint': 'a clip from a prompt alone'},
    {
        'id': 'v2v',
        'group': 'video',
        'label': 'Video to video & animate',
        'hint': 'driving a character with a reference performance',
    },
    {
        'id': 'lipsync',
        'group': 'video',
        'label': 'Lipsync & audio-driven face',
        'hint': 'a mouth that matches the line',
    },
    {'id': 'interp', 'group': 'video', 'label': 'Interpolation & retime', 'hint': 'frame rate, slow motion, smoothing'},
    {'id': 'vfx', 'group': 'video', 'label': 'VFX & compositing', 'hint': 'elements, mattes, grade, overlays'},
    {
        'id': 'video_assembly',
        'group': 'video',
        'label': 'Assembly, encode & delivery',
        'hint': 'cutting, muxing and shipping the file',
    },
    # ── motion & body ──
    {
        'id': 'movement',
        'group': 'motion',
        'label': 'Movement & whole-body action',
        'hint': 'walking, turning, carrying, working',
    },
    {'id': 'poses', 'group': 'motion', 'label': 'Poses & stance', 'hint': 'a single held body position'},
    {'id': 'gestures', 'group': 'motion', 'label': 'Gestures & hands', 'hint': 'what the arms and hands do'},
    {'id': 'facial', 'group': 'motion', 'label': 'Facial movement', 'hint': 'brows, lids, lips, gaze, expression'},
    {
        'id': 'muscle',
        'group': 'motion',
        'label': 'Muscle, flex & soft tissue',
        'hint': 'flexing, weight, deformation under load',
    },
    {
        'id': 'body_fit',
        'group': 'motion',
        'label': 'Body fitting & pose tracking',
        'hint': 'recovering a 3D body from pixels',
    },
    {
        'id': 'rigging',
        'group': 'motion',
        'label': 'Rigging & retarget',
        'hint': 'skeletons, weights, moving motion between bodies',
    },
    # ── 3d, scene & architecture ──
    {
        'id': 'mesh_gen',
        'group': 'three_d',
        'label': 'Mesh generation',
        'hint': 'making geometry from an image or prompt',
    },
    {'id': 'mesh_qc', 'group': 'three_d', 'label': 'Mesh QC & anatomy', 'hint': 'is the geometry actually correct'},
    {'id': 'grooms', 'group': 'three_d', 'label': 'Hair, grooms & eyes', 'hint': 'strand hair, eye shaders, skin'},
    {'id': 'arch', 'group': 'three_d', 'label': 'Architecture generation', 'hint': 'buildings, plans, landscape'},
    {
        'id': 'render3d',
        'group': 'three_d',
        'label': '3D render & look-dev',
        'hint': 'getting a picture out of the geometry',
    },
    # ── judges, gates & qc ──
    {
        'id': 'vlm_judges',
        'group': 'judges',
        'label': 'VLM judges (image & video defects)',
        'hint': 'the models we ask "is this picture wrong?"',
    },
    {
        'id': 'pixel_gates',
        'group': 'judges',
        'label': 'Pixel gates',
        'hint': 'arithmetic checks that do not use a model',
    },
    {
        'id': 'detectors',
        'group': 'judges',
        'label': 'Detector models',
        'hint': 'find the thing, then judge it separately',
    },
    {
        'id': 'identity_gates',
        'group': 'judges',
        'label': 'Identity & continuity gates',
        'hint': 'is it still the same character',
    },
    {
        'id': 'text_judges',
        'group': 'judges',
        'label': 'Text, era & typography judges',
        'hint': 'anachronism, lettering, spelling in frame',
    },
    {
        'id': 'audio_judges',
        'group': 'judges',
        'label': 'Audio judges & QC',
        'hint': 'is the sound wrong, and how would we know',
    },
]
STEP_BY_ID = {s['id']: s for s in STEPS}
STEP_IDS = [s['id'] for s in STEPS]

# ── vocabulary ───────────────────────────────────────────────────────────────
STATES = {
    'yes': {'label': 'Can do', 'tone': 'good', 'icon': '✓'},
    'partial': {'label': 'Partly / conditional', 'tone': 'warning', 'icon': '~'},
    'no': {'label': 'Cannot do', 'tone': 'critical', 'icon': '✕'},
    'untested': {'label': 'Not tested', 'tone': 'neutral', 'icon': '·'},
    'na': {'label': 'Not applicable', 'tone': 'muted', 'icon': '–'},
}
# How we know. The board prints the grade next to the cell; only `measured` and `receipt`
# count towards a step's "tested" coverage.
GRADES = {
    'measured': {'label': 'Measured here', 'rank': 3, 'hint': 'a bench in this repo produced this number'},
    'receipt': {'label': 'Production receipt', 'rank': 2, 'hint': 'a real run recorded it, not a bench'},
    'vendor': {'label': 'Vendor claim', 'rank': 1, 'hint': 'the model card says so; we have not checked'},
    'assumed': {'label': 'Assumed', 'rank': 0, 'hint': 'reasoned from how it is wired, never measured'},
}
HARD_GRADES = ('measured', 'receipt')
STATUSES = {
    'tested': {
        'label': 'Benched',
        'tone': 'good',
        'hint': 'a real bench was run for this step — see the coverage figure for how '
        'much of the questionnaire it answered',
    },
    'partial': {'label': 'Some answers', 'tone': 'warning', 'hint': 'a few questions carry evidence, most do not'},
    'untested': {
        'label': 'No answers yet',
        'tone': 'neutral',
        'hint': 'the tools are listed; nothing has been measured',
    },
    'broken': {'label': 'Unreadable sheet', 'tone': 'critical', 'hint': ''},
}
UNITS = (
    'number',
    'int',
    'pct',
    'ratio',
    'x',
    'ms',
    's',
    'min',
    'h',
    'mb',
    'gb',
    'tokens',
    'usd',
    'eur',
    'fps',
    'px',
    'score',
    'count',
    'cents',
    'text',
)

# ── the rating ───────────────────────────────────────────────────────────────
# One number per ROW, printed next to the model/tool's name: of the questions this sheet
# actually answered for that tool, how many came back the way the question wants. It is a
# reading of the cells already on the sheet, never a separate opinion — nothing records a
# rating, so a rating cannot disagree with the evidence under it.
#
#   yes → 1, partial → ½, no → 0, and `higher_better: False` FLIPS that reading:
#   "Attribution required: yes" is a mark against a tool, not for it.
#
# Untested and not-applicable cells leave both sides of the fraction, so a rating can
# never be earned by a gap. The answered/asked count travels with the score, because 100
# off two questions is not 100 off fifty — and a row under THIN_RATING of its sheet is
# flagged provisional so the board can say so rather than imply otherwise.
RATING_POINTS = {'yes': 1.0, 'partial': 0.5, 'no': 0.0}
RATING_BANDS = [
    (
        'strong',
        {'label': 'Strong', 'tone': 'good', 'min': 80, 'hint': 'nearly everything asked of it came back the right way'},
    ),
    ('capable', {'label': 'Capable', 'tone': 'good', 'min': 60, 'hint': 'does the job, with gaps we know about'}),
    ('mixed', {'label': 'Mixed', 'tone': 'warning', 'min': 40, 'hint': 'about as much against it as for it'}),
    ('weak', {'label': 'Weak', 'tone': 'warning', 'min': 20, 'hint': 'fails most of what was asked'}),
    ('poor', {'label': 'Poor', 'tone': 'critical', 'min': 0, 'hint': 'answered the wrong way almost everywhere'}),
]
RATINGS = dict(RATING_BANDS)
THIN_RATING = 0.25  # under a quarter of the sheet answered → the score is provisional


def rating_band(score):
    """The band a 0-100 score falls in. Bands are ordered high to low."""
    for key, band in RATING_BANDS:
        if score >= band['min']:
            return key
    return RATING_BANDS[-1][0]


def _row_rating(cells, cols, na):
    """The row's rating, or None when no question in this sheet has an answer for it yet —
    an untested row has no score, it does not have a zero."""
    got, n, measured, worst = 0.0, 0, 0, None
    for c in cols:
        cell = cells.get(c['id'])
        if not cell or cell['state'] not in RATING_POINTS:
            continue  # untested / not applicable: counts on neither side
        point = RATING_POINTS[cell['state']]
        if c.get('higher_better') is False:
            point = 1.0 - point
        got += point
        n += 1
        if cell['grade'] in HARD_GRADES:
            measured += 1
        rank = GRADES.get(cell['grade'] or 'assumed', {}).get('rank', 0)
        worst = rank if worst is None else min(worst, rank)
    if not n:
        return None
    asked = max(len(cols) - na, n)
    score = round(100.0 * got / n, 1)
    grade = next((k for k, g in GRADES.items() if g['rank'] == worst), 'assumed')
    return {
        'score': score,
        'band': rating_band(score),
        'answered': n,
        'asked': asked,
        'measured': measured,
        'grade': grade,
        'thin': n < THIN_RATING * asked,
    }


# ── helpers ──────────────────────────────────────────────────────────────────
def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), TZ).isoformat(timespec='seconds')
    except Exception:
        return None


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _slug(s, maxlen=60):
    s = re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()).strip('-')
    return (s[:maxlen].rstrip('-')) or 'x'


def _asset_id(path):
    return hashlib.sha1(os.path.realpath(path).encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


def _ensure_store():
    os.makedirs(STORE, exist_ok=True)
    return STORE


def sheet_path(step_id):
    return os.path.join(STORE, f'{_slug(step_id)}.json')


# ── writing ──────────────────────────────────────────────────────────────────
def record_sheet(rec, replace=True):
    """Write one step's capability sheet. Returns the path written."""
    step = rec.get('step')
    if step not in STEP_BY_ID:
        raise ValueError(f'unknown step {step!r} — add it to capabilities_hub.STEPS first')
    _ensure_store()
    path = sheet_path(step)
    if os.path.exists(path) and not replace:
        raise FileExistsError(path)
    rec = dict(rec)
    rec.setdefault('recorded_at', _iso(time.time()))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return path


# ── reading & validation ─────────────────────────────────────────────────────
def _norm_cell(raw, col_id, errors):
    """A cell is always a dict in the payload, even when the record wrote a bare string."""
    if raw is None:
        return {'state': 'untested', 'grade': None, 'value': None, 'note': '', 'src': None}
    if isinstance(raw, str):
        raw = {'state': raw}
    if not isinstance(raw, dict):
        errors.append(f'cell {col_id}: not an object')
        return {'state': 'untested', 'grade': None, 'value': None, 'note': '', 'src': None}
    state = str(raw.get('state') or 'untested')
    if state not in STATES:
        errors.append(f'cell {col_id}: unknown state {state!r}')
        state = 'untested'
    grade = raw.get('grade')
    if grade is not None and grade not in GRADES:
        errors.append(f'cell {col_id}: unknown grade {grade!r}')
        grade = None
    # An asserted capability with no grade is not evidence — say so rather than imply one.
    if state in ('yes', 'no', 'partial') and grade is None:
        grade = 'assumed'
        errors.append(f'cell {col_id}: state {state!r} carries no grade, read as "assumed"')
    return {
        'state': state,
        'grade': grade,
        'value': _num(raw.get('value')),
        'text': raw.get('text') or None,
        'note': raw.get('note') or '',
        'src': raw.get('src') or None,
    }


def _norm_matrix(m, errors, idx=0):
    """Normalise one matrix for the wire.

    A sheet asks hundreds of questions of a handful of tools and almost every answer is
    "not tested", so an unanswered cell is OMITTED rather than shipped as a full object —
    the frontend reads a missing cell as untested. On the seeded store that is ~300 cells
    on the wire instead of tens of thousands. Empty column fields are dropped for the same
    reason; the frontend already defaults them.
    """
    cols, seen = [], set()
    for c in m.get('columns') or []:
        cid = str(c.get('id') or _slug(c.get('label')))
        if cid in seen:
            errors.append(f'duplicate column id {cid!r}')
            continue
        seen.add(cid)
        unit = c.get('unit') or None
        if unit and unit not in UNITS:
            errors.append(f'column {cid}: unknown unit {unit!r} (printed as text)')
        col = {'id': cid, 'label': c.get('label') or cid}
        if c.get('hint'):
            col['hint'] = c['hint']
        if unit:
            col['unit'] = unit
        if c.get('group'):
            col['group'] = c['group']
        if c.get('higher_better') is not None:
            col['higher_better'] = c['higher_better']
        cols.append(col)
    rows = []
    for r in m.get('rows') or []:
        rid = str(r.get('id') or _slug(r.get('label')))
        raw = r.get('cells') or {}
        cells, na = {}, 0
        for c in cols:
            if c['id'] not in raw:
                continue
            cell = _norm_cell(raw[c['id']], c['id'], errors)
            if (
                cell['state'] == 'untested'
                and cell['grade'] is None
                and cell['value'] is None
                and not cell['text']
                and not cell['note']
            ):
                continue  # a default cell is the absence of a cell
            if cell['state'] == 'na':
                na += 1
            cells[c['id']] = cell
        row = {'id': rid, 'label': r.get('label') or rid, 'cells': cells, 'na': na}
        rating = _row_rating(cells, cols, na)
        if rating:  # an unanswered row ships no rating, not a zero
            row['rating'] = rating
        for k in ('role', 'licence', 'where', 'note'):
            if r.get(k):
                row[k] = r[k]
        if r.get('retired'):
            row['retired'] = True
        rows.append(row)
    out = {'id': m.get('id') or (f'm{idx}' if idx else 'main'), 'columns': cols, 'rows': rows}
    for k in ('title', 'hint', 'note'):
        if m.get(k):
            out[k] = m[k]
    return out


def _coverage(matrices):
    """How much of this step is actually known: answered cells / every question asked of
    every tool. The denominator is the whole grid (minus the cells marked not-applicable),
    not the cells that happen to carry an answer — otherwise a sheet with one answer in it
    would read 100 %."""
    hard = total = 0
    for m in matrices:
        total += len(m['columns']) * len(m['rows'])
        for r in m['rows']:
            total -= r.get('na', 0)
            for c in r['cells'].values():
                if c['state'] != 'untested' and c['grade'] in HARD_GRADES:
                    hard += 1
    return {'measured_cells': hard, 'cells': total, 'pct': round(100.0 * hard / total, 1) if total else 0.0}


def default_test(step_id):
    """The DEFAULT TEST behind a sheet (capability_tests/<step>.py via capabilities_tests.summary):
    what a new model in this step is run through, validated against the questionnaire so every
    column has one disposition. Kept small for the payload; never raises — a step without a
    test module reports present=False, a broken one reports its errors."""
    try:
        from zyg_dashboard import capabilities_tests as ct
        from zyg_workflows.devreload import maybe_reload

        maybe_reload(ct)  # same hot-reload spirit as the section itself (ZYG_DEV_RELOAD=1)
        v = ct.summary(step_id)
    except Exception as exc:
        return {'present': False, 'ok': False, 'errors': [f'{type(exc).__name__}: {exc}']}
    if not v.get('present'):
        return {'present': False}
    return {
        k: v.get(k)
        for k in (
            'present',
            'ok',
            'version',
            'hash',
            'title',
            'columns',
            'probes',
            'operator_checks',
            'dispositions',
            'rows',
            'blocked',
            'errors',
            'warnings',
            'module',
            'include_shared',
            'budget',
            'check_kinds_added',
            'transports_added',
        )
    }


def load_sheet(step_id):
    """Read one sheet from the store; None when the step has no sheet yet."""
    path = sheet_path(step_id)
    if not os.path.exists(path):
        return None
    errors = []
    try:
        with open(path, encoding='utf-8') as f:
            rec = json.load(f)
    except Exception as exc:  # a broken file is shown, never dropped
        return {
            'step': step_id,
            'status': 'broken',
            'errors': [f'{type(exc).__name__}: {exc}'],
            'matrices': [],
            'file': path,
            'coverage': {'measured_cells': 0, 'cells': 0, 'pct': 0.0},
            'sources': [],
            'notes': [],
            'limitations': [],
            'rows_n': 0,
            'has_inspect': False,
        }
    mats = [_norm_matrix(rec, errors)]
    for i, extra in enumerate(rec.get('sheets') or [], start=1):
        mats.append(_norm_matrix(extra, errors, idx=i))
    cov = _coverage(mats)
    test = default_test(step_id)
    if test.get('present') and rec.get('test_hash') and rec.get('test_hash') != test.get('hash'):
        errors.append(
            f'cells were measured by test {rec["test_hash"]}; the default test is now '
            f'{test.get("hash")} — a new model cannot be compared with these rows until they are re-run'
        )
    status = rec.get('status')
    if status not in STATUSES:
        status = 'tested' if cov['pct'] >= 60 else ('partial' if cov['measured_cells'] else 'untested')
    return {
        'step': step_id,
        'title': rec.get('title') or STEP_BY_ID[step_id]['label'],
        'question': rec.get('question') or '',
        'verdict': rec.get('verdict') or '',
        'status': status,
        'tested_at': rec.get('tested_at'),
        'recorded_at': rec.get('recorded_at'),
        'matrices': mats,
        'coverage': cov,
        'rows_n': len(mats[0]['rows']) if mats else 0,
        'notes': list(rec.get('notes') or []),
        'limitations': list(rec.get('limitations') or []),
        'sources': list(rec.get('sources') or []),
        'errors': errors,
        'next_tests': list(rec.get('next_tests') or []),
        'has_inspect': bool(rec.get('inspect')),
        'file': path,
        'test_hash': rec.get('test_hash'),
        'default_test': test,
    }


def _raw_sheet(step_id):
    path = sheet_path(step_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ── assets (the Inspect page's pictures) ─────────────────────────────────────
def asset_index():
    """{asset_id: abs path} over every asset any sheet registered. The only paths the
    asset endpoint will serve — a client id that is not in here resolves to nothing."""
    idx = {}
    for sid in STEP_IDS:
        rec = _raw_sheet(sid)
        if not rec:
            continue
        for a in (rec.get('inspect') or {}).get('assets') or []:
            p = a.get('path')
            if p:
                idx[a.get('id') or _asset_id(p)] = os.path.realpath(p)
    return idx


_MIME = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac',
    '.svg': 'image/svg+xml',
}
ASSET_MAX_BYTES = 12 * 1024 * 1024


def asset(asset_id):
    """One registered file as a data URI, or an error dict. Served through the section
    endpoint so the tab needs no new Flask route (a new route costs a GUI restart)."""
    path = asset_index().get(str(asset_id or ''))
    if not path:
        return {'ok': False, 'error': 'unknown asset id'}
    if not os.path.exists(path):
        return {'ok': False, 'error': 'the file this sheet points at is gone', 'path': path}
    size = os.path.getsize(path)
    if size > ASSET_MAX_BYTES:
        return {
            'ok': False,
            'error': f'file is {size / 1e6:.1f} MB, over the {ASSET_MAX_BYTES / 1e6:.0f} MB cap',
            'path': path,
        }
    mime = _MIME.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')
    with open(path, 'rb') as f:
        blob = f.read()
    return {
        'ok': True,
        'id': asset_id,
        'mime': mime,
        'bytes': size,
        'path': path,
        'data_uri': f'data:{mime};base64,' + base64.b64encode(blob).decode('ascii'),
    }


# ── the Inspect document ─────────────────────────────────────────────────────
def inspect(step_id):
    """Everything that went INTO and came OUT of the step's test. Kept out of the board
    payload on purpose: the board shows data sheets, this is the evidence behind them."""
    if step_id not in STEP_BY_ID:
        return {'ok': False, 'error': f'unknown step {step_id!r}'}
    rec = _raw_sheet(step_id)
    meta = STEP_BY_ID[step_id]
    if not rec:
        return {
            'ok': True,
            'step': step_id,
            'label': meta['label'],
            'empty': True,
            'reason': 'No capability sheet has been recorded for this step yet.',
            'inspect': None,
        }
    ins = rec.get('inspect') or {}
    assets = []
    for a in ins.get('assets') or []:
        p = a.get('path') or ''
        rp = os.path.realpath(p) if p else ''
        assets.append(
            {
                'id': a.get('id') or (_asset_id(p) if p else ''),
                'label': a.get('label') or os.path.basename(p),
                'kind': a.get('kind') or 'image',
                'path': p,
                'note': a.get('note') or '',
                'exists': bool(rp and os.path.exists(rp)),
                'bytes': os.path.getsize(rp) if rp and os.path.exists(rp) else None,
            }
        )
    return {
        'ok': True,
        'step': step_id,
        'label': meta['label'],
        'title': rec.get('title') or meta['label'],
        'question': rec.get('question') or '',
        'verdict': rec.get('verdict') or '',
        'tested_at': rec.get('tested_at'),
        'empty': not ins,
        'reason': ''
        if ins
        else 'This sheet has no Inspect evidence attached — it was '
        'filled from the stack inventory, not from a test run.',
        'summary': ins.get('summary') or '',
        'method': list(ins.get('method') or []),
        'command': ins.get('command') or '',
        'environment': ins.get('environment') or {},
        'inputs': list(ins.get('inputs') or []),
        'trials': list(ins.get('trials') or []),
        'outputs': list(ins.get('outputs') or []),
        'assets': assets,
        'raw': ins.get('raw'),
        'sources': list(rec.get('sources') or []),
        'notes': list(rec.get('notes') or []),
        'limitations': list(rec.get('limitations') or []),
    }


# ── the board payload ────────────────────────────────────────────────────────
def _data_version():
    """Changes when any sheet changes — the frontend keeps its DOM while it is equal."""
    h = hashlib.sha1(usedforsecurity=False)
    h.update(b'capabilities-v1|')
    for sid in STEP_IDS:
        p = sheet_path(sid)
        try:
            st = os.stat(p)
            h.update(f'{sid}:{int(st.st_mtime)}:{st.st_size}|'.encode())
        except OSError:
            h.update(f'{sid}:-|'.encode())
    return h.hexdigest()[:12]


def section_capabilities(days=30, now=None, fresh=False):
    """Metrics > Capabilities. `days` is ignored — a capability sheet is the current truth
    about a tool, not a time series; the range picker does not change what a sheet says."""
    t0 = time.time()
    # `?inspect=` / `?asset=` ride the section endpoint so no new Flask route is needed.
    try:
        from flask import has_request_context, request

        if has_request_context():
            a = request.args.get('asset')
            if a:
                return {'mode': 'asset', 'asset': asset(a), 'data_version': _data_version()}
            i = request.args.get('inspect')
            if i:
                return {'mode': 'inspect', 'inspect': inspect(i), 'data_version': _data_version()}
            one = request.args.get('sheet')
            if one:
                # One step's sheet. The board renders a single step at a time and the full
                # set is ~1 MB now that a step asks hundreds of questions, so the poll
                # carries the rail and the sheet is fetched per step and cached by the
                # frontend against data_version.
                return {'mode': 'sheet', 'step': one, 'sheet': load_sheet(one), 'data_version': _data_version()}
    except Exception as _exc:
        _zyg_log.warning('capability poll fast path failed, falling back to the full rail: %s', _exc)

    rail = []
    for s in STEPS:
        sh = load_sheet(s['id'])
        rail.append(
            {
                'id': s['id'],
                'group': s['group'],
                'label': s['label'],
                'hint': s['hint'],
                'status': sh['status'] if sh else 'untested',
                'tools': sh['rows_n'] if sh else 0,
                'coverage': sh['coverage'] if sh else {'measured_cells': 0, 'cells': 0, 'pct': 0.0},
                'tested_at': sh.get('tested_at') if sh else None,
                'has_sheet': bool(sh),
                'has_inspect': bool(sh and sh['has_inspect']),
                'has_test': bool(sh and (sh.get('default_test') or {}).get('present')),
                'test_ok': bool(sh and (sh.get('default_test') or {}).get('ok')),
            }
        )
    tested = sum(1 for r in rail if r['status'] == 'tested')
    partial = sum(1 for r in rail if r['status'] == 'partial')
    return {
        'mode': 'board',
        'groups': GROUPS,
        'rail': rail,
        'states': STATES,
        'grades': GRADES,
        'statuses': STATUSES,
        'hard_grades': list(HARD_GRADES),
        'ratings': RATINGS,
        'rating_points': RATING_POINTS,
        'thin_rating': THIN_RATING,
        'totals': {
            'steps': len(rail),
            'tested': tested,
            'partial': partial,
            'untested': len(rail) - tested - partial,
            'tools': sum(r['tools'] for r in rail),
            'measured_cells': sum(r['coverage']['measured_cells'] for r in rail),
            'cells': sum(r['coverage']['cells'] for r in rail),
        },
        'store': STORE,
        'data_version': _data_version(),
        'compute_ms': round((time.time() - t0) * 1000),
        'method': [
            'Rows are the models and tools wired into that step of the workflow; columns are '
            'what a test asked of them.',
            'Every cell carries how we know it: measured here, production receipt, vendor claim '
            'or assumed. Only the first two count as tested.',
            'A step with no test shows every cell as "not tested" — that is the gap to go and '
            'close, not a missing feature of this tab.',
            "The rating beside a row reads that row's own answered cells — yes 1, partly \u00bd, "
            'no 0, flipped where the question is one a tool wants to answer "no" to. It is out '
            'of the questions answered, which is printed under it.',
        ],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    args = sys.argv[1:]
    verb = args[0] if args else 'section'
    if verb == 'list':
        for s in STEPS:
            sh = load_sheet(s['id'])
            print(
                f'{s["id"]:<18} {s["group"]:<9} {(sh["status"] if sh else "no sheet"):<10} '
                f'{(str(sh["coverage"]["pct"]) + "%" if sh else "—"):>7}  {s["label"]}'
            )
    elif verb == 'show':
        print(json.dumps(load_sheet(args[1]), indent=1, default=str))
    elif verb == 'inspect':
        print(json.dumps(inspect(args[1]), indent=1, default=str))
    elif verb == 'record':
        src = args[args.index('--file') + 1] if '--file' in args else None
        rec = json.load(open(src, encoding='utf-8')) if src else json.load(sys.stdin)
        print(record_sheet(rec))
    elif verb == 'assets':
        for k, v in asset_index().items():
            print(k, v, 'OK' if os.path.exists(v) else 'MISSING')
    else:
        print(json.dumps(section_capabilities(), indent=1, default=str))
