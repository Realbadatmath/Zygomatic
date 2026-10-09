# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio — the Sheet/Checks/Voice actions, server side (2026-09-18).

Four ops behind /inspect/api/studio/char_checks/, one per dock tool that was
drawn with an `act:` key and no handler:

  angles       Which of the sheet's angles this character actually has on disk.
               The canonical list is NOT re-derived here: contact_sheet/
               manifest.json carries `cell_angles` (the 48 prose labels this
               run was generated from) and `cell_paths` (where each cell was
               written). Those are what the run really used, so a character
               sheeted under an older or a custom angle set is reported
               against ITS OWN list, not against today's default. Only when
               the manifest is missing or angle-less does it fall back to
               contact_sheet_pipeline.contact_sheet_angle_labels(angle_set).

  handqc       hand_qc_service.detect_hand_boxes on one image, then the VLM
               crop judge (_judge_crop) on each box.
               MEASURED, and the reason this op exists at all: the judge scores
               melted hands as fine when it is shown a full frame, so it is
               only ever shown CROPS here. When the judge cannot be reached the
               boxes come back with verdict 'judge unavailable' and the
               transport error — never an empty verdict that reads as a pass.

  anachronism  era_gate (NOT picture_fx — picture_fx only mentions the gate in
               a help string) run against the character's wardrobe period.
               The kinds are derived OFFLINE from the character's own wardrobe
               and presentation prose (era_gate.derive_checks_offline), which
               is deterministic and needs no LLM; the universal tells are added
               on top; era_gate.judge_frame does the looking.
               'contemporary', '2000s' and 'science fiction' are NOT gated and
               say so explicitly — a period gate that "passes" a period it has
               no questions for is a silent pass.

  audition     One line in this character's voice. voice_studio.start_render is
               called in-process, which is exactly what POST /voice/api/render
               does (same module object, same _JOBS dict), so the page polls
               the ordinary GET /voice/api/job?id=… and plays /voice/audio?p=…
               MEASURED: voice_profile.character_voice in the bibles on disk
               holds AZURE names ('en-US-BrianNeural') or free prose, not Voice
               Studio ids — 108 of them are empty. So the resolver checks the
               id against the studio's own list and refuses with the id it was
               given rather than auditioning some other character's voice.

Everything is fenced on _char_dir(): the id has to match the library's id shape
and the resolved directory has to be a direct child of the dataset root. Image
arguments are resolved INSIDE that directory and nowhere else.
"""

import json
import os
import re
from zyg_workflows import paths

_ROOT = os.path.realpath(str(paths.ZYG_LORA_DATASETS / 'storyteller_chars'))
_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
_CELL_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}\.(png|jpg|jpeg|webp)$', re.I)

# How many hand crops are judged and returned. A contact-sheet cell has at most
# two hands in it; the cap is what stops a full-body frame with a crowd behind
# the subject from turning one press into twenty VLM calls.
_MAX_HANDS = 4

# wardrobe.period (character_studio.FIELDS['wardrobe.period'].choices) -> the
# era-lock dict era_gate reads. `end` is the last year that belongs to the
# period; era_gate.period_bucket buckets it and picks the vocabulary.
# None means the period HAS no "after" — nothing can be anachronistic in it.
_PERIOD_ERA = {
    'contemporary': None,
    '2000s': None,
    'science fiction': None,
    '1980s': {'period_end': 1989, 'period_label': 'the 1980s'},
    '1950s': {'period_end': 1959, 'period_label': 'the 1950s'},
    '1920s': {'period_end': 1929, 'period_label': 'the 1920s'},
    'victorian': {'period_end': 1901, 'period_label': 'the Victorian era'},
    'regency': {'period_end': 1820, 'period_label': 'the Regency'},
    '18th century': {'period_end': 1799, 'period_label': 'the 18th century'},
    '17th century': {'period_end': 1699, 'period_label': 'the 17th century'},
    'renaissance': {'period_end': 1600, 'period_label': 'the Renaissance'},
    'medieval': {'period_end': 1500, 'period_label': 'the Middle Ages'},
    'ancient': {'period_end': 400, 'period_label': 'antiquity'},
    'timeless fantasy': {'period_end': 1500, 'period_label': 'a pre-industrial fantasy world'},
}

# The bible prose the offline kind-derivation is run over. Wardrobe first: the
# gate is asked about the COSTUME, and a character's default scene description
# would otherwise drown it in scenery keywords.
_PROSE_PATHS = (
    'wardrobe.outfit_variants',
    'wardrobe.layers',
    'wardrobe.fabric',
    'wardrobe.footwear',
    'wardrobe.headwear',
    'wardrobe.outerwear',
    'wardrobe.condition',
    'default_presentation.default_clothing',
    'default_presentation.accessories',
    'accessories.jewellery',
    'accessories.weapons',
    'accessories.eyewear',
    'accessories.bags',
)


def _char_dir(cid):
    """The character's real directory, or None. A direct child of the root and
    nothing else — the same fence kanban_server._safe_char_dir applies."""
    cid = str(cid or '').strip()
    if not _ID_RE.match(cid):
        return None
    d = os.path.realpath(os.path.join(_ROOT, cid))
    if d != os.path.join(_ROOT, cid) or not os.path.isdir(d):
        return None
    return d


def _mods():
    from zyg_workflows import character_bible_service
    from zyg_workflows import character_studio

    return character_bible_service, character_studio


def _manifest(cdir):
    try:
        with open(os.path.join(cdir, 'contact_sheet', 'manifest.json'), encoding='utf-8') as fh:
            m = json.load(fh)
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _stat(p):
    try:
        st = os.stat(p)
        return round(st.st_size), round(st.st_mtime, 1)
    except OSError:
        return 0, 0.0


# ── angles ───────────────────────────────────────────────────────────────────
def _angles(payload, method):  # noqa: ARG001
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}

    man = _manifest(cdir)
    angle_set = str(man.get('angle_set') or '').strip()
    labels = man.get('cell_angles')
    source = 'manifest.cell_angles'
    if not isinstance(labels, list) or not labels:
        try:
            from zyg_workflows import contact_sheet_pipeline as CSP

            labels = CSP.contact_sheet_angle_labels(angle_set or None)
            source = f'contact_sheet_pipeline (angle_set={angle_set or "default"})'
        except Exception as e:  # noqa: BLE001 — shown in the panel
            return {'error': f'no angle list for this character: {type(e).__name__}: {e}'[:200], 'code': 500}

    # cell_paths is where the RUN wrote each cell. It is authoritative when it
    # is there (a re-stitch after QC can renumber); the cells/cell_NN.png
    # layout is the fallback and is also what /inspect/img serves by name.
    paths = man.get('cell_paths')
    cells_dir = os.path.join(cdir, 'contact_sheet', 'cells')
    rows, missing = [], []
    for i, name in enumerate(labels):
        fp = ''
        if isinstance(paths, list) and i < len(paths) and isinstance(paths[i], str):
            fp = paths[i]
        if not fp:
            fp = os.path.join(cells_dir, f'cell_{i:02d}.png')
        nbytes, mtime = _stat(fp)
        present = nbytes > 0
        rows.append(
            {
                'idx': i,
                'name': str(name),
                'present': present,
                'file': fp,
                # what the page hands to imgUrl(id, cat, name, mtime)
                'cat': 'cells' if os.path.dirname(fp) == cells_dir else '',
                'img': os.path.basename(fp),
                'bytes': nbytes,
                'mtime': mtime,
            }
        )
        if not present:
            missing.append(i)

    return {
        'ok': True,
        'id': cid,
        'angle_set': angle_set or 'unknown',
        'source': source,
        'total': len(rows),
        'present': len(rows) - len(missing),
        'angles': rows,
        'missing': missing,
        'sheet_approved': man.get('approved'),
        'manifest': bool(man),
    }


# ── the image an image check runs on ─────────────────────────────────────────
def _pick_image(cdir, pkg, want):
    """(path, how) for a check, or (None, why). `want` is an optional cell file
    name — resolved inside this character's cells directory and nowhere else."""
    want = str(want or '').strip()
    if want:
        if not _CELL_RE.match(want):
            return None, 'that is not a cell file name'
        fp = os.path.realpath(os.path.join(cdir, 'contact_sheet', 'cells', want))
        base = os.path.join(cdir, 'contact_sheet', 'cells')
        if not fp.startswith(base + os.sep) or not os.path.isfile(fp):
            return None, f'no cell {want} on disk for this character'
        return fp, f'cell {want}'

    cond = (pkg or {}).get('conditioning') or {}
    mr = cond.get('master_reference_image')
    if isinstance(mr, str) and mr and os.path.isfile(mr):
        return mr, 'conditioning.master_reference_image'
    # The bible names no master reference (or names one that is gone). The
    # anchor face is what identity QC scores every cell against, so it is the
    # next most canonical picture of this character.
    anchor = os.path.join(cdir, 'contact_sheet', 'contact_sheet_anchor_face.png')
    if os.path.isfile(anchor):
        return anchor, 'contact_sheet/contact_sheet_anchor_face.png (no master reference in the bible)'
    cell0 = os.path.join(cdir, 'contact_sheet', 'cells', 'cell_00.png')
    if os.path.isfile(cell0):
        return cell0, 'contact_sheet/cells/cell_00.png (no master reference, no anchor face)'
    return None, 'this character has no master reference, no anchor face and no cells'


# ── hand QC ──────────────────────────────────────────────────────────────────
def _handqc(payload, method):  # noqa: ARG001
    cbs, _cs = _mods()
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    pkg = cbs.load(cid) or {}
    img, how = _pick_image(cdir, pkg, payload.get('image'))
    if not img:
        return {'error': how, 'code': 404}

    try:
        from zyg_workflows import hand_qc_service as HQ
    except Exception as e:  # noqa: BLE001
        return {'error': f'hand_qc_service will not import: {type(e).__name__}: {e}'[:200], 'code': 503}

    try:
        boxes = HQ.detect_hand_boxes(img)
    except Exception as e:  # noqa: BLE001 — detect_hand_boxes
        # fails CLOSED by contract; a detector that cannot run must never be
        # reported as "no hands found".
        return {'error': f'hand detection unavailable — {type(e).__name__}: {e}'[:300], 'code': 503}

    boxes = sorted(boxes, key=lambda b: -float(b.get('conf') or 0))[:_MAX_HANDS]
    hands, judged, defective, visible = [], 0, 0, 0
    judge_error = ''
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = (float(v) for v in b['box'])
        rec = {
            'i': i,
            'box': [round(x1), round(y1), round(x2), round(y2)],
            'conf': round(float(b.get('conf') or 0), 3),
            'crop_b64': '',
            'verdict': None,
            'why': '',
        }
        try:
            rec['crop_b64'] = HQ._crop_b64(img, (x1, y1, x2, y2))
        except Exception as e:  # noqa: BLE001
            rec['why'] = f'crop failed: {type(e).__name__}: {e}'[:160]
            hands.append(rec)
            continue
        # ALWAYS the crop, never the frame: measured, the judge passes melted
        # hands when it is shown the whole picture.
        try:
            v = HQ._judge_crop(rec['crop_b64'])
            rec['verdict'] = v
            judged += 1
            if v.get('hand_visible'):
                visible += 1
            if v.get('defective'):
                defective += 1
        except Exception as e:  # noqa: BLE001
            rec['why'] = 'judge unavailable'
            judge_error = f'{type(e).__name__}: {e}'[:300]
        hands.append(rec)

    backend = ''
    try:
        backend = HQ._select_backend()
    except Exception:  # noqa: BLE001
        backend = 'unknown'

    return {
        'ok': True,
        'id': cid,
        'image': img,
        'how': how,
        'backend': backend,
        'vlm_model': getattr(HQ, '_VLM_MODEL', ''),
        'hands': hands,
        'found': len(boxes),
        'judged': judged,
        'visible': visible,
        'defective': defective,
        'judge_error': judge_error,
        # `visible` is reported separately on purpose. The detector and the
        # judge disagree often: a 0.97-confidence box the judge answers
        # hand_visible=false with is a crop the judge did NOT inspect, and
        # folding it into "0 defective" would read as a hand it cleared.
        'verdict': (
            'no hands detected'
            if not boxes
            else 'judge unavailable'
            if judged == 0
            else f'{defective} defective of {visible} the judge could see ({len(boxes)} box(es) detected)'
        ),
    }


# ── anachronism ──────────────────────────────────────────────────────────────
def _prose(cs, pkg):
    bits = []
    for path in _PROSE_PATHS:
        v = cs._get(pkg, path)
        if isinstance(v, str) and v.strip():
            bits.append(v.strip())
    return ', '.join(bits)


def _anachronism(payload, method):  # noqa: ARG001
    cbs, cs = _mods()
    cid = str(payload.get('id') or '').strip()
    cdir = _char_dir(cid)
    if not cdir:
        return {'error': 'unknown character', 'code': 404}
    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json', 'code': 404}

    # the bible's period, unless the panel asked for another one
    period = str(payload.get('period') or '').strip().lower()
    from_bible = not period
    if not period:
        period = str(cs._get(pkg, 'wardrobe.period') or '').strip().lower()
    if not period:
        period = str((cs.FIELDS.get('wardrobe.period') or {}).get('default') or 'contemporary')
    if period not in _PERIOD_ERA:
        return {'error': f'{period!r} is not one of the wardrobe.period choices'}

    era = _PERIOD_ERA[period]
    if era is None:
        return {
            'ok': True,
            'id': cid,
            'period': period,
            'from_bible': from_bible,
            'gated': False,
            'kinds': [],
            'flags': [],
            'answers': {},
            'reason': f'{period} has no "after" — there is no object that could be '
            f'out of period, so the gate has no question to ask. This is '
            f'not a pass: nothing was looked at. Pick a period above to run it.',
        }

    img, how = _pick_image(cdir, pkg, payload.get('image'))
    if not img:
        return {'error': how, 'code': 404}

    try:
        from zyg_workflows import era_gate as EG
    except Exception as e:  # noqa: BLE001
        return {'error': f'era_gate will not import: {type(e).__name__}: {e}'[:200], 'code': 503}

    prose = _prose(cs, pkg)
    checks = EG.derive_checks_offline(prose, era)
    # No gore item (this is a portrait check, not a scene one) and no subject
    # item (there is no prompt to say what the shot is of).
    items = EG.build_items({'checks': checks}, era, include_gore=False, include_subject=False, include_universal=True)

    log_lines = []
    res = EG.judge_frame(img, items, era, prefer='local', local_ok=True, log=lambda m: log_lines.append(str(m)[:200]))
    if res.get('skipped'):
        return {'error': f'the gate did not run: {res.get("reason") or "unknown"}', 'code': 503, 'log': log_lines[-12:]}

    kinds = [
        {'id': c['id'], 'kind': c.get('kind', ''), 'question': c['question'], 'fix': c.get('fix', '')} for c in checks
    ]
    # MEASURED 2026-09-18: era_gate's keyword rules are written for SCENE
    # prompts ('tunics', 'cloaks', 'dressed'), and a bible's wardrobe prose
    # often names garments they do not list ('blouse', 'slacks'). No kinds
    # then means no object-specific question was asked — the panel has to say
    # that, or seven universal passes read as a full clearance.
    kinds_note = (
        ''
        if kinds
        else "No object-specific question: nothing in this bible's wardrobe prose "
        "matched era_gate's object keywords, so only the universal period "
        'tells below were asked.'
    )
    named = [
        {
            'id': it['id'],
            'question': it['question'],
            'source': it.get('source', ''),
            'answer': res['answers'].get(it['id'], 'unknown'),
            'expected': it.get('expected', 'no'),
            'ok': res['answers'].get(it['id'], 'unknown') == it.get('expected', 'no'),
        }
        for it in items
    ]

    return {
        'ok': True,
        'id': cid,
        'period': period,
        'from_bible': from_bible,
        'gated': True,
        'era': era,
        'bucket': EG.period_bucket(era),
        'image': img,
        'how': how,
        'prose': prose[:400],
        'judge': res.get('judge', ''),
        'seconds': res.get('seconds', 0),
        'kinds': kinds,
        'kinds_note': kinds_note,
        'checks': named,
        'flags': res.get('flags', []),
        'unknown': res.get('unknown', []),
        'answers': res.get('answers', {}),
        'passed': not res.get('flags'),
        'log': log_lines[-12:],
    }


# ── audition ─────────────────────────────────────────────────────────────────
def _voice_studio():
    from zyg_workflows import voice_studio

    return voice_studio


def _audition(payload, method):  # noqa: ARG001
    cbs, _cs = _mods()
    cid = str(payload.get('id') or '').strip()
    if not _char_dir(cid):
        return {'error': 'unknown character', 'code': 404}
    pkg = cbs.load(cid)
    if pkg is None:
        return {'error': 'this character has no character_bible.json', 'code': 404}

    try:
        vs = _voice_studio()
    except Exception as e:  # noqa: BLE001
        return {'error': f'voice studio unavailable: {type(e).__name__}: {e}'[:200], 'code': 503}

    vp = pkg.get('voice_profile') or {}
    claimed = str(vp.get('character_voice') or '').strip()
    vid = str(payload.get('voice') or '').strip() or claimed
    if not vid:
        return {
            'error': 'this character has no voice_profile.character_voice and no '
            'voice was picked. Use "Pick a voice" first.',
            'code': 404,
            'claimed': claimed,
        }
    if not vs.voice(vid):
        return {
            'error': f'{vid!r} is not a Voice Studio voice. The bibles on disk carry '
            f'Azure voice names and free prose in voice_profile.character_voice, '
            f'which the local cloning engines cannot speak — pick a studio '
            f'voice for this character.',
            'code': 404,
            'claimed': claimed,
            'tried': vid,
        }

    name = str(pkg.get('display_name') or cid).strip() or cid
    text = str(payload.get('text') or '').strip() or f'{name} here. This is how I sound today.'
    try:
        job = vs.start_render(vid, text, payload.get('params') or {})
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:250], 'code': 500}

    return {
        'ok': True,
        'id': cid,
        'voice': vid,
        'claimed': claimed,
        'from_bible': vid == claimed,
        'name': name,
        'text': text,
        'job': job,
        'poll': '/voice/api/job',
        'audio': '/voice/audio',
    }


ROUTES = {
    'angles': _angles,
    'handqc': _handqc,
    'anachronism': _anachronism,
    'audition': _audition,
}
