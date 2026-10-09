# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pack_ingest.py — install the 2026-08-25 sound-pack haul into the asset library.

Seven sources, three destination categories, one licence rule per pack. The
pattern is vocal_fx_ingest.py generalised: masters stay untouched under
data/asset_libraries/_originals/<pack>/, working copies land as 48 kHz/16-bit
wav in the category dir via ambience_ingest.register_audio_asset, and every
record carries the licence block that the publish gate and the AI-training
gate will read later.

ROUTING — why three categories and not one
    vocal_fx  non-verbal HUMAN sound (screams, grunts, sobs, chokes). The
              scene service and build_agony_bed already treat this dir as the
              human-voice one-shot pool.
    foley     everything else that is a ONE-SHOT: weapons on shields and flesh,
              gore, jump-scare stingers, creature voices, raw object recordings,
              designed hits. NEW category (asset_library_service 2026-08-25).
    sfx       BEDS only — the loop-under-dialogue library. Gets the horror
              ambiences, the USC crowds, one river. Nothing under ~8 s goes
              here; a bed picker drowning in one-shots was the whole reason
              foley exists.

QUARANTINE — masters kept, never installed, listed in
data/runtime/pack_ingest_quarantine.json so the decision is reversible:
    child/baby    Screams & Shouts 2 CHILD (160) + BABY (21) — children and
                  infants in pain and dying; licence-clean, editorially not.
    atrocity      Ultimate Horror "Prisoner Screaming, Gas Chamber".
    verbal_en     Xylon's two spoken-English voice lines and its chant.
Everything else installs; spoken words elsewhere are FLAGGED (verbal=True)
by the Whisper scan, exactly as the mouth-noise library does it.

LICENCE — the two-axis record every file gets
    license_id / commercial_ok           -> license_gate  (may it SHIP?)
    no_ai_training                       -> training_gate (may a MODEL eat it?)
    transform: 'dsp' | 'model'           -> the third state neither gate names:
                                            every vendor pack here permits
                                            pitch/EQ/layering in a mix and
                                            forbids model input; CC0 permits both.
Two paper traps found on the way in, recorded so they are never re-argued:
the older 344 EULA shipped inside Screaming and Historical Weapons is SILENT
on AI, but Sonniss's site licence (where they were bought) and 344's current
EULA both forbid it; and the eula.pdf inside the Xylon zip is an OLDER A Sound
Effect EULA without the AI clause, while the live License Agreement it points
to carries one. The live/stricter text governs in both cases.

SCANS
    --whisper   faster-whisper large-v3 (transcriber venv, GPU when free) over
                every vocal candidate; verbal flag per vocal_fx_ingest.classify.
    --slate     0.05 s RMS envelope on every master LONGER than 8 s: a burst
                >20 dB over the file's own median with 40-66 % of its energy in
                200-3000 Hz is a spoken take-number (the ship_creak "Number 11"
                incident). One-shots are bursts by nature, so they are skipped;
                Whisper covers them. Flags, never auto-deletes.

    python3 pack_ingest.py --plan        # counts per destination, nothing written
    python3 pack_ingest.py --slate --whisper
    python3 pack_ingest.py --install
    python3 pack_ingest.py --report
"""

import json
import os
import re
import sys
import time
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

ORIG = os.path.join(_HERE, 'data', 'asset_libraries', '_originals')
RUNTIME = os.path.join(_HERE, 'data', 'runtime')
QUAR_JSON = os.path.join(RUNTIME, 'pack_ingest_quarantine.json')
WHISPER_JSON = os.path.join(RUNTIME, 'pack_ingest_speech_scan.json')
SLATE_JSON = os.path.join(RUNTIME, 'pack_ingest_slate_scan.json')
ASR_PY = paths.ZYG_ASR_PYTHON

ASE_EULA_URL = 'https://www.asoundeffect.com/license-agreement/'
SONNISS_EULA_URL = 'https://sonniss.com/license/'

# ── the packs ────────────────────────────────────────────────────────────────
# Each: masters dir (relative to _originals), the licence block, and a router
# that maps a master's relative path to (category, name, extra_meta) or
# ('quarantine', reason) or None (skip: demo tracks, docs).


def _slug(s, n=72):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', str(s).lower())).strip('_')
    return s[:n].rstrip('_')


def _strip_vendor(stem):
    """'VOXScrm_Male Being Tortured, Perspective 1_344 Audio_Screaming' ->
    ('VOXScrm', 'Male Being Tortured, Perspective 1')"""
    ucs, _, rest = stem.partition('_')
    # 344 puts the take number AFTER the vendor tag ('..._344 Audio_Screaming_01');
    # keep it, or every take of a descriptor collapses onto one name.
    m = re.search(r'_(\d{1,3})$', rest)
    take = m.group(1) if m else ''
    for tail in ('_344 Audio', '_SNDBTS', '_CS_USC'):
        rest = rest.split(tail)[0]
    rest = rest.strip()
    if take and not re.search(r'\d$', rest):
        rest = f'{rest} {take}'
    return ucs, rest


_LIC_344_PAID = {
    'source': '344 Audio Limited (344 SFX)',
    'license_id': 'royalty-free-verified',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'purchased_from': 'Sonniss (1-user licence)',
    'purchase_date': '2026-08-25',
    'no_ai_training': True,
    'no_redistribute': True,
    'transform': 'dsp',
    'eula_url': SONNISS_EULA_URL,
}
_LIC_ASE = {
    'source': 'via A Sound Effect ApS',
    'license_id': 'royalty-free-verified',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'purchased_from': 'A Sound Effect (1-user licence)',
    'purchase_date': '2026-08-25',
    'no_ai_training': True,
    'no_redistribute': True,
    'transform': 'dsp',
    'eula_url': ASE_EULA_URL,
}
_LIC_CC0 = {
    'license_id': 'cc0',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'no_ai_training': False,
    'no_redistribute': False,
    'transform': 'model',
}


def _route_screaming(rel):
    parts = rel.split(os.sep)  # Female/Female General Screams/x.wav
    if len(parts) < 2:
        return None
    sex = 'm' if parts[0].lower().startswith('male') else 'f'
    group = parts[1] if len(parts) > 2 else 'misc'
    ucs, desc = _strip_vendor(os.path.splitext(parts[-1])[0])
    short = re.sub(r'^(male|female|man|woman)\s+', '', desc, flags=re.I)
    return (
        'vocal_fx',
        f'scr_{sex}_{_slug(short)}',
        {'sex': 'male' if sex == 'm' else 'female', 'group': group, 'descriptor': desc, 'ucs_category': ucs},
    )


def _route_ss2(rel):
    parts = rel.split(os.sep)  # VOICES/MALE/xxx.wav
    if len(parts) < 3 or parts[0] != 'VOICES':
        return None
    folder = parts[1]
    if folder in ('CHILD', 'BABY'):
        return ('quarantine', f'child/baby content ({folder.lower()})')
    ucs, desc = _strip_vendor(os.path.splitext(parts[-1])[0])
    sex = 'male' if folder == 'MALE' else 'female'
    short = re.sub(r'^(male|female)\s+', '', desc, flags=re.I)  # sex is already the prefix
    return (
        'vocal_fx',
        f'ss2_{sex[0]}_{_slug(short)}',
        {'sex': sex, 'group': folder.title(), 'descriptor': desc, 'ucs_category': ucs},
    )


def _route_hw1(rel):
    parts = rel.split(os.sep)  # Flesh Impacts/xxx.wav
    if len(parts) < 2:
        return None
    ucs, desc = _strip_vendor(os.path.splitext(parts[-1])[0])
    return ('foley', f'hw1_{_slug(desc)}', {'group': parts[0], 'descriptor': desc, 'ucs_category': ucs})


_UH_HUMAN_SCREAM = re.compile(r'^VOXScrm_(Female Horror Scream|Male Muffled Loud Scream)', re.I)


def _route_uh(rel):
    parts = rel.split(os.sep)  # <Group - Mini>/.../xxx.wav
    if len(parts) < 2:
        return None
    group = parts[0].replace(' - Mini', '')
    stem = os.path.splitext(parts[-1])[0]
    if 'gas chamber' in stem.lower():
        return ('quarantine', 'atrocity reference (gas chamber)')
    ucs, desc = _strip_vendor(stem)
    meta = {'group': group, 'descriptor': desc, 'ucs_category': ucs}
    name = f'uh_{_slug(ucs)}_{_slug(desc, 60)}'
    if group == 'Ambiences':
        meta['bed'] = True
        return ('sfx', name, meta)
    if _UH_HUMAN_SCREAM.match(stem):
        meta['sex'] = 'female' if 'Female' in stem else 'male'
        return ('vocal_fx', name, meta)
    return ('foley', name, meta)


_XYL_VERBAL = ('voice _have a nice day', 'voice _welcome on board', 'nam myoho renge kyo')


def _route_xylon(rel):
    parts = rel.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    if parts[0] == 'Source Recordings':
        if any(stem.lower().startswith(v) for v in _XYL_VERBAL):
            return ('quarantine', 'spoken English / chant (source recording)')
        if stem.lower().startswith('po river'):
            return ('sfx', f'xyl_src_{_slug(stem)}', {'group': 'Source', 'descriptor': stem, 'bed': True})
        return ('foley', f'xyl_src_{_slug(stem)}', {'group': 'Source', 'descriptor': stem})
    if parts[0] == 'Designed Sounds' and len(parts) >= 3:
        sub = parts[1]
        meta = {'group': sub, 'descriptor': stem, 'designed': True}
        return ('foley', f'xyl_{_slug(sub, 16)}_{_slug(stem, 50)}', meta)
    return None


def _route_mrfossy(rel):
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = re.match(r'(\d+)__mrfossy__(.+?)(?:\.wav)?$', stem)
    if not m:
        return None
    fsid, desc = m.group(1), m.group(2).replace('voice_adultmale_', '')
    return (
        'vocal_fx',
        f'mrfossy_{_slug(desc)}',
        {'sex': 'male', 'group': 'Pain grunts', 'descriptor': desc, 'source_url': f'https://freesound.org/s/{fsid}/'},
    )


_USC_MANIFEST = {}


def _usc_manifest():
    if not _USC_MANIFEST:
        p = os.path.join(ORIG, 'usc_sound_effect_archive', 'MANIFEST.json')
        try:
            for f in json.load(open(p))['files']:
                _USC_MANIFEST[os.path.join(f['item'], f['name'])] = f
        except (OSError, ValueError, KeyError) as _exc:
            _zyg_log.warning('USC manifest %s unreadable, its files get no manifest entry: %s', p, _exc)
    return _USC_MANIFEST


_USC_BED_ITEMS = re.compile(r'Crowds|SSE_Library_CROWDS|SSE_Library_AMBIENCE', re.I)


def _route_usc(rel):
    if not rel.lower().endswith('.wav'):
        return None
    item = rel.split(os.sep)[0]
    stem = os.path.splitext(os.path.basename(rel))[0]
    ucs, desc = _strip_vendor(stem) if '_' in stem and stem[:3].isupper() else ('', stem)
    mf = _usc_manifest().get(rel, {})
    meta = {
        'group': item,
        'descriptor': desc or stem,
        'source_url': mf.get('source_url', f'https://archive.org/details/{item}'),
        'ia_comment': mf.get('comment', ''),
        'ia_md5': mf.get('md5', ''),
    }
    name = f'usc_{_slug(stem, 64)}'
    if 'wilhelm' in stem.lower():
        # ownership chain runs through Warner/Republic — the CC0 tag is the
        # uploader's assertion. Mix-only, never a voice reference.
        meta.update(
            {
                'no_ai_training': True,
                'transform': 'dsp',
                'notes_extra': 'Wilhelm take: provenance disputed, treat as mix-only.',
            }
        )
    if _USC_BED_ITEMS.search(item):
        meta['bed'] = True
        return ('sfx', name, meta)
    if 'Foley_Props' in item:
        return ('foley', name, meta)
    return ('vocal_fx', name, meta)


PACKS = [
    # slug, masters subdir, licence block, router, human-readable source
    (
        '344_screaming',
        'Sound Effects',
        dict(
            _LIC_344_PAID,
            source_url='https://sonniss.com/sound-effects/screaming/',
            price_paid='USD 12.00 (60% promo)',
            eula='_originals/344_screaming/Documentation/344-Audio-EULA.pdf',
            eula_note='shipped EULA is the older 344 text (silent on AI); Sonniss site licence + 344 EULA-2025 forbid AI use',
        ),
        _route_screaming,
        '344 Audio — Screaming',
    ),
    (
        'soundbits_screams_shouts_2',
        'Sounds',
        dict(
            _LIC_ASE,
            source='SoundBits (via A Sound Effect)',
            source_url='https://www.asoundeffect.com/sound-library/screams-shouts-2-humans/',
            price_paid='EUR 22.50 (50% promo)',
            eula='(none in archive)',
            eula_note='A Sound Effect License Agreement §3 forbids NN/AI/ML training use',
        ),
        _route_ss2,
        'SoundBits — Screams & Shouts 2: Humans',
    ),
    (
        '344_historical_weapons_1',
        'Sound Effects',
        dict(
            _LIC_344_PAID,
            source_url='https://sonniss.com/sound-effects/historical-weapons-vol-1/',
            price_paid='USD 0.00 (free promo until 2026-09-03)',
            eula='_originals/344_historical_weapons_1/Documentation/344-Audio-EULA.pdf',
            eula_note='shipped EULA is the older 344 text (silent on AI); Sonniss site licence + 344 EULA-2025 forbid AI use',
        ),
        _route_hw1,
        '344 Audio — Historical Weapons Vol. 1',
    ),
    (
        '344_ultimate_horror_mini',
        'Sound Effects',
        dict(
            _LIC_344_PAID,
            source_url='https://sonniss.com/sound-effects/ultimate-horror-mini/',
            price_paid='USD 0.00 (free promo until 2026-09-03)',
            eula='_originals/344_ultimate_horror_mini/Documentation/344-Audio-EULA-2025.pdf',
            eula_note='344 EULA 2025 §3: "Use the Sounds to train AI, machine learning, or neural networks" is prohibited',
        ),
        _route_uh,
        '344 Audio — Ultimate Horror: Mini',
    ),
    (
        'asfx_xylon',
        '',
        dict(
            _LIC_ASE,
            source='A Sound Effect — Xylon (Mohole students, 2021-22)',
            source_url='https://www.asoundeffect.com/gift/',
            purchased_from='A Sound Effect (free gift, 1-user)',
            price_paid='free',
            eula='_originals/asfx_xylon/eula.pdf',
            eula_note='eula.pdf in the archive is an OLDER ASE text without the AI clause; readme defers to the standard ASE EULA, whose live §3 forbids NN/AI/ML use',
        ),
        _route_xylon,
        'A Sound Effect — Xylon',
    ),
    (
        'freesound_mrfossy_30826',
        '',
        dict(
            _LIC_CC0,
            source="Freesound — MrFossy, pack 30826 (uploader's own voice)",
            source_url='https://freesound.org/people/MrFossy/packs/30826/',
            eula='_originals/freesound_mrfossy_30826/_readme_and_license.txt',
            eula_note='CC0 1.0 per pack readme; performer is the uploader, so personality rights sit with the person who waived copyright',
        ),
        _route_mrfossy,
        'Freesound — MrFossy',
    ),
    (
        'usc_sound_effect_archive',
        '',
        dict(
            _LIC_CC0,
            source='USC Sound Effect Archive (Internet Archive, CC0)',
            source_url='https://archive.org/details/usc-sound-effect-archive',
            eula='_originals/usc_sound_effect_archive/LICENCE.md',
            eula_note="licenseurl=CC0 on every item manifest; CC0 does not waive performers' personality rights — anonymous stock performers, low residual risk",
        ),
        _route_usc,
        'USC Sound Effect Archive',
    ),
]


# ── enumeration ──────────────────────────────────────────────────────────────


def masters(slug, sub):
    root = os.path.join(ORIG, slug, sub) if sub else os.path.join(ORIG, slug)
    out = []
    for dp, _d, fs in os.walk(root):
        for fn in fs:
            if fn.lower().endswith('.wav'):
                full = os.path.join(dp, fn)
                out.append((os.path.relpath(full, root), full))
    return sorted(out)


def plan(log_fn=print):
    """Every master -> destination. Returns list of dicts; writes nothing."""
    rows = []
    for slug, sub, lic, router, label in PACKS:
        ms = masters(slug, sub)
        if not ms:
            log_fn(f'[plan] {slug}: NO MASTERS (not extracted?)')
            continue
        for rel, full in ms:
            r = router(rel)
            if r is None:
                rows.append({'pack': slug, 'rel': rel, 'full': full, 'dest': 'skip'})
            elif r[0] == 'quarantine':
                rows.append({'pack': slug, 'rel': rel, 'full': full, 'dest': 'quarantine', 'why': r[1]})
            else:
                cat, name, extra = r
                rows.append(
                    {
                        'pack': slug,
                        'rel': rel,
                        'full': full,
                        'dest': cat,
                        'name': name,
                        'extra': extra,
                        'lic': lic,
                        'label': label,
                    }
                )
    # Byte-identical masters shipped twice (344 Screaming carries five takes in
    # two folders) install once; the copy is marked skip with a pointer.
    import hashlib

    seen_md5, ndup = {}, 0
    for r in rows:
        if r['dest'] not in ('vocal_fx', 'foley', 'sfx'):
            continue
        h = hashlib.md5(open(r['full'], 'rb').read(), usedforsecurity=False).hexdigest()
        r['md5'] = h
        if h in seen_md5:
            r['dest'], r['why'] = 'skip', f'duplicate of {seen_md5[h]["pack"]}/{seen_md5[h]["rel"]}'
            ndup += 1
        else:
            seen_md5[h] = r
    # Remaining same-name pairs are different audio: disambiguate by group,
    # never let register_audio_asset paper over it with a bare _2.
    seen, dup = {}, 0
    for r in rows:
        if r['dest'] in ('vocal_fx', 'foley', 'sfx'):
            k = (r['dest'], r['name'])
            if k in seen:
                dup += 1
                r['name'] = f'{r["name"]}_{_slug(r["extra"].get("group", "alt"), 14)}'
            seen[k] = r
    log_fn(f'[plan] {ndup} byte-identical duplicates skipped')
    from collections import Counter

    c = Counter((r['pack'], r['dest']) for r in rows)
    for (p, d), n in sorted(c.items()):
        log_fn(f'  {n:5d}  {p:30s} -> {d}')
    tot = Counter(r['dest'] for r in rows)
    log_fn(f'[plan] totals: {dict(tot)}  (renamed {dup} name collisions)')
    return rows


# ── scans ────────────────────────────────────────────────────────────────────


def _vocal_candidates(rows):
    """Files worth transcribing: everything bound for vocal_fx, every Ultimate
    Horror voice, every Xylon source whose name hints at a voice, all of USC."""
    out = []
    for r in rows:
        if r['dest'] == 'skip':
            continue
        p = r['pack']
        rel = r['rel'].lower()
        if (
            r['dest'] == 'vocal_fx'
            or r['dest'] == 'quarantine'
            or p == 'usc_sound_effect_archive'
            or (p == '344_ultimate_horror_mini' and 'voices' in rel)
            or (
                p == 'asfx_xylon'
                and re.search(r'voice|vocal|laugh|scream|growl|chant|breath|chew|whistle|interferen|renge', rel)
            )
        ):
            out.append(r['full'])
    return out


def run_whisper(rows, log_fn=print):
    files = _vocal_candidates(rows)
    log_fn(f'[whisper] {len(files)} candidates')
    code = r"""
import json, os, sys
from faster_whisper import WhisperModel
files = json.load(open(sys.argv[1])); out = sys.argv[2]
dev, comp = 'cpu', 'int8'
try:
    import torch
    if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 5000*1024*1024:
        dev, comp = 'cuda', 'int8_float16'
except Exception as _exc:
    print('[whisper] cuda probe failed, staying on cpu:', _exc, flush=True)
print('[whisper] device', dev, flush=True)
m = WhisperModel('large-v3', device=dev, compute_type=comp)
res = {}
try:
    res = json.load(open(out))
except (OSError, ValueError) as _exc:
    print('[whisper] no resumable results file, starting fresh:', _exc, flush=True)
for i, f in enumerate(files):
    if f in res and 'error' not in res[f]:
        continue
    try:
        segs, _i = m.transcribe(f, language='en', vad_filter=False, beam_size=5)
        segs = list(segs)
        res[f] = {'text': ' '.join((s.text or '').strip() for s in segs).strip(),
                  'no_speech_prob': min([s.no_speech_prob for s in segs], default=1.0),
                  'avg_logprob': max([s.avg_logprob for s in segs], default=-99.0)}
    except Exception as e:
        res[f] = {'error': str(e)[:200]}
    if i % 50 == 0:
        print(f'[whisper] {i}/{len(files)}', flush=True)
        json.dump(res, open(out, 'w'), indent=1)
json.dump(res, open(out, 'w'), indent=1)
print('[whisper] done', len(res), flush=True)
"""
    import subprocess

    os.makedirs(RUNTIME, exist_ok=True)
    lst = os.path.join(RUNTIME, 'pack_ingest_whisper_list.json')
    json.dump(files, open(lst, 'w'))
    r = subprocess.run([ASR_PY, '-c', code, lst, WHISPER_JSON], timeout=4 * 3600)
    return r.returncode == 0


def _slate_measure(path):
    """(burst_db_over_median, speech_band_fraction, t_burst_s, dur_s) on a
    0.05 s RMS envelope. None when the file is too short to judge."""
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(path, dtype='float32', always_2d=True)
    x = x.mean(axis=1)
    dur = len(x) / sr
    if dur < 8.0:
        return None
    hop = int(sr * 0.05)
    n = len(x) // hop
    env = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    med = np.median(env)
    i = int(env.argmax())
    burst_db = 20 * np.log10(env[i] / (med + 1e-9))
    # WIDTH of the burst at -12 dB below its peak: a spoken take-number holds
    # mid-band energy for ~0.6-2 s; a sword-on-shield impact decays in <0.3 s.
    # Without this the test flags every clean transient (21 false hits on the
    # first pass, all weapon and metal impacts).
    thr = env[i] * 10 ** (-12 / 20)
    a_, b_ = i, i
    while a_ > 0 and env[a_ - 1] > thr:
        a_ -= 1
    while b_ < n - 1 and env[b_ + 1] > thr:
        b_ += 1
    width = (b_ - a_ + 1) * 0.05
    # speech-band share of the energy in a 0.6 s window around the peak
    a, b = max(0, i * hop - int(0.3 * sr)), min(len(x), i * hop + int(0.3 * sr))
    seg = x[a:b] * np.hanning(b - a)
    spec = np.abs(np.fft.rfft(seg)) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    tot = spec.sum() + 1e-12
    band = spec[(freqs >= 200) & (freqs <= 3000)].sum() / tot
    return float(burst_db), float(band), i * hop / sr, float(dur), float(width)


def run_slate(rows, log_fn=print):
    res = {}
    try:
        res = json.load(open(SLATE_JSON))
    except (OSError, ValueError) as _exc:
        _zyg_log.debug('slate cache %s unreadable, re-measuring: %s', SLATE_JSON, _exc)
    n = flagged = 0
    for r in rows:
        if r['dest'] == 'skip' or r['full'] in res:
            continue
        try:
            m = _slate_measure(r['full'])
        except Exception as e:
            res[r['full']] = {'error': str(e)[:120]}
            continue
        if m is None:
            continue
        burst, band, t, dur, width = m
        suspect = burst > 20.0 and 0.40 <= band <= 0.66 and width >= 0.45
        res[r['full']] = {
            'burst_db': round(burst, 1),
            'speech_band': round(band, 3),
            'burst_width_s': round(width, 2),
            't_s': round(t, 2),
            'dur_s': round(dur, 1),
            'suspect': suspect,
        }
        n += 1
        flagged += suspect
        if n % 100 == 0:
            log_fn(f'[slate] {n} measured, {flagged} suspect')
    os.makedirs(RUNTIME, exist_ok=True)
    json.dump(res, open(SLATE_JSON, 'w'), indent=1)
    log_fn(f'[slate] measured {n} long files, {flagged} suspect -> {SLATE_JSON}')
    return res


# ── install ──────────────────────────────────────────────────────────────────


def install(rows=None, log_fn=print, limit=None):
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL
    from zyg_workflows.vocal_fx_ingest import classify

    rows = rows or plan(log_fn=lambda m: None)
    try:
        wsc = json.load(open(WHISPER_JSON))
    except Exception:
        wsc = {}
        log_fn('[install] WARNING: no whisper scan — verbal flag will be unknown')
    try:
        ssc = json.load(open(SLATE_JSON))
    except Exception:
        ssc = {}
    # idempotency by MASTER path: a re-run must never double the library
    have = {}
    for cat in ('vocal_fx', 'foley', 'sfx'):
        for fid, m in AL._load_audio_meta(cat).items():
            if m.get('master'):
                have[(cat, m['master'])] = fid
    quar = []
    stats = {'installed': 0, 'skipped': 0, 'failed': 0, 'quarantined': 0, 'verbal': 0, 'slate': 0}
    for r in rows[:limit]:
        if r['dest'] == 'skip':
            continue
        master_rel = os.path.relpath(r['full'], os.path.join(_HERE, 'data', 'asset_libraries'))
        if r['dest'] == 'quarantine':
            quar.append({'pack': r['pack'], 'master': master_rel, 'why': r['why']})
            stats['quarantined'] += 1
            continue
        cat = r['dest']
        if (cat, master_rel) in have:
            stats['skipped'] += 1
            continue
        s = wsc.get(r['full']) or {}
        verbal, why = classify(s.get('text'), s.get('no_speech_prob')) if s else (False, 'not scanned')
        sl = ssc.get(r['full']) or {}
        meta = dict(r['lic'])
        meta.update(r['extra'])
        meta.update(
            {
                'pack': r['pack'],
                'pack_label': r['label'],
                'master': master_rel,
                'asr_text': (s.get('text') or '')[:200],
                'asr_no_speech_prob': round(float(s.get('no_speech_prob', 1.0)), 3) if s else None,
                'verbal': verbal,
                'verbal_why': why,
                'slate_suspect': bool(sl.get('suspect')),
                'slate_burst_db': sl.get('burst_db'),
                'slate_t_s': sl.get('t_s'),
            }
        )
        d = r['extra'].get('descriptor', r['name'])
        note = f'{r["label"]} — {d}'
        if r['extra'].get('group'):
            note += f' ({r["extra"]["group"]})'
        if verbal:
            note += f'. CONTAINS SPEECH ({why}) — not for a non-English or period scene'
        if sl.get('suspect'):
            note += f'. SLATE SUSPECT at {sl.get("t_s")}s ({sl.get("burst_db")} dB burst) — listen before use'
        if meta.get('no_ai_training'):
            note += '. Mix-only: no AI/voice-reference use, no redistribution'
        if meta.pop('notes_extra', None):
            note += '. Wilhelm take: provenance disputed, mix-only'
        meta['notes'] = note
        rec = ambience_ingest.register_audio_asset(
            cat, r['full'], meta, name=r['name'], convert=True, log_fn=lambda m: None
        )
        if rec:
            stats['installed'] += 1
            stats['verbal'] += verbal
            stats['slate'] += bool(sl.get('suspect'))
            have[(cat, master_rel)] = rec['id']
        else:
            stats['failed'] += 1
            log_fn(f'[install] FAILED {r["pack"]}/{r["rel"]}')
        if stats['installed'] % 200 == 0 and stats['installed']:
            log_fn(f'[install] {stats}')
    os.makedirs(RUNTIME, exist_ok=True)
    json.dump({'written': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': quar}, open(QUAR_JSON, 'w'), indent=1)
    log_fn(f'[install] done {stats}; quarantine list -> {QUAR_JSON}')
    return stats


def annotate(rows=None, log_fn=print):
    """Merge the (possibly later-finished) Whisper + slate verdicts into records
    that are already installed. Install does not wait for the 85-minute speech
    scan; this pass makes the sidecar catch up. Idempotent."""
    from zyg_workflows import asset_library_service as AL
    from zyg_workflows.vocal_fx_ingest import classify

    rows = rows or plan(log_fn=lambda m: None)
    try:
        wsc = json.load(open(WHISPER_JSON))
    except Exception:
        wsc = {}
    try:
        ssc = json.load(open(SLATE_JSON))
    except Exception:
        ssc = {}
    by_master = {}
    for cat in ('vocal_fx', 'foley', 'sfx'):
        for fid, m in AL._load_audio_meta(cat).items():
            if m.get('master'):
                by_master[(cat, m['master'])] = (fid, m)
    n = changed = verbal = 0
    for r in rows:
        if r['dest'] not in ('vocal_fx', 'foley', 'sfx'):
            continue
        master_rel = os.path.relpath(r['full'], os.path.join(_HERE, 'data', 'asset_libraries'))
        hit = by_master.get((r['dest'], master_rel))
        if not hit:
            continue
        fid, m = hit
        s_ = wsc.get(r['full'])
        if not s_ or 'error' in s_:
            continue
        n += 1
        v, why = classify(s_.get('text'), s_.get('no_speech_prob'))
        sl = ssc.get(r['full']) or {}
        upd = {
            'asr_text': (s_.get('text') or '')[:200],
            'asr_no_speech_prob': round(float(s_.get('no_speech_prob', 1.0)), 3),
            'verbal': v,
            'verbal_why': why,
            'slate_suspect': bool(sl.get('suspect')),
        }
        if all(m.get(k) == val for k, val in upd.items()):
            continue
        note = re.sub(r'\. CONTAINS SPEECH \([^)]*\) — not for a non-English or period scene', '', m.get('notes', ''))
        if v:
            note += f'. CONTAINS SPEECH ({why}) — not for a non-English or period scene'
        upd['notes'] = note
        if AL.set_audio_meta(r['dest'], fid, upd):
            changed += 1
            verbal += v
    log_fn(f'[annotate] {n} scanned records seen, {changed} updated, {verbal} verbal')
    return changed


# ── head slates ──────────────────────────────────────────────────────────────
USC_WORDS_JSON = os.path.join(RUNTIME, 'pack_ingest_usc_words.json')
_SLATE_WORD = re.compile(
    r'\b(number|take|scene|sequence|wild|track|speed|quiet|present|production|\d+[a-z]?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|forty|fifty)\b',
    re.I,
)


def trim_heads(log_fn=print, dry=False):
    """The USC tape transfers open with the recordist's spoken take-number —
    'Number three', 'Wild track for scene 25, take. Speed.' — the ship_creak
    'Number 11' defect. Whisper word timestamps (pack_ingest_usc_words.json)
    locate it; if the words inside the first 6.5 s read as a slate, the working
    copy is re-cut FROM THE MASTER at the slate's end + 0.15 s with a 0.08 s
    fade-in. Masters are never touched; the cut is recorded in the sidecar so
    a re-install reproduces it."""
    import subprocess
    from zyg_workflows import asset_library_service as AL

    words = json.load(open(USC_WORDS_JSON))
    done = []
    for fid, info in words.items():
        head = [w for w in info['words'] if w['s'] < 6.5 and w['p'] >= 0.5]
        phrase = ' '.join(w['w'] for w in head)
        if not head or not _SLATE_WORD.search(phrase):
            continue
        cut = round(max(w['e'] for w in head) + 0.15, 2)
        cat = info['cat']
        master = info['master']
        dest = os.path.join(AL._audio_dir(cat), fid)
        if dry:
            log_fn(f'[trim] would cut {cat}/{fid} at {cut}s  ({phrase!r})')
            continue
        cmd = [
            exe('ffmpeg'),
            '-y',
            '-ss',
            str(cut),
            '-i',
            master,
            '-vn',
            '-af',
            'afade=t=in:st=0:d=0.08',
            '-ar',
            '48000',
            '-c:a',
            'pcm_s16le',
            dest,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            log_fn(f'[trim] FAILED {fid}: {r.stderr[-160:]}')
            continue
        AL.set_audio_meta(
            cat,
            fid,
            {
                'trimmed_head_s': cut,
                'trim_reason': f'spoken slate: {phrase}',
                'notes_trim': f'head slate trimmed at {cut}s ({phrase!r}); master untouched',
            },
        )
        done.append((cat, fid, cut, phrase))
        log_fn(f'[trim] {cat}/{fid} cut at {cut}s  ({phrase!r})')
    log_fn(f'[trim] {len(done)} working copies re-cut from master')
    return done


def report(log_fn=print):
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL
    from collections import Counter

    for cat in ('vocal_fx', 'foley', 'sfx'):
        recs = AL.load_assets(cat)
        bad = ambience_ingest.audit_category(cat)
        by = Counter(r.get('pack', '(pre-existing)') for r in recs)
        log_fn(f'{cat}: {len(recs)} files; licence audit {"CLEAN" if not bad else str(len(bad)) + " UNCLEAN"}')
        for k, n in sorted(by.items()):
            log_fn(f'   {n:5d}  {k}')
        v = [r for r in recs if r.get('verbal')]
        sl = [r for r in recs if r.get('slate_suspect')]
        log_fn(f'   verbal-flagged {len(v)}, slate-suspect {len(sl)}')
        g = ambience_ingest.training_gate(
            [(cat, r['id']) for r in recs if r.get('no_ai_training')][:5], log_fn=lambda m: None
        )
        if [r for r in recs if r.get('no_ai_training')]:
            log_fn(f'   training gate refuses a mix-only sample: {not g["ok"]}')


if __name__ == '__main__':
    a = sys.argv[1:] or ['--plan']
    rows = plan()
    if '--slate' in a:
        run_slate(rows)
    if '--whisper' in a:
        run_whisper(rows)
    if '--install' in a:
        install(rows)
    if '--annotate' in a:
        annotate(rows)
    if '--trim-heads' in a:
        trim_heads()
    if '--report' in a:
        report()
