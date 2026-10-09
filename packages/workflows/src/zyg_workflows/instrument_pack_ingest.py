# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""instrument_pack_ingest.py — install sampled musical instruments into the
asset library as a new `instruments` category.

Same shape as pack_ingest.py (2026-08-25) and arch_pack_ingest.py: masters stay
untouched under data/asset_libraries/_originals/<source>/, working copies land
as 48 kHz/16-bit wav via ambience_ingest.register_audio_asset, every record
carries the licence block the publish gate and the AI-training gate read later,
and a re-run is idempotent by MASTER path so it can never double the library.

WHY A NEW CATEGORY AND NOT `foley`
    `foley` exists because a thousand one-shots in `sfx` made bed selection
    impossible. The same argument applies one level down: `foley` is the
    library a scene picks a single PROP beat from — a sword on a shield, a
    door, a body fall — and forty thousand pitched notes there would drown that
    choice completely. Instruments also carry axes nothing else in the library
    has (instrument / pitch / dynamic / articulation / round-robin), which the
    SFX tab groups and facets on.

SOURCES — five, and the licence rule for each was read at FILE level
    freepats       51 sets, CC0 1.0. Verified per pack from the LICENSE.txt or
                   readme.txt/cc0.txt shipped INSIDE each archive, not from the
                   index page. The GPL-3 sets (FSS Steel-String Guitar, the
                   FreePats General MIDI banks) are NOT here: copyleft never
                   reaches an internal tool, but a sample rendered into a
                   published episode is an ASSET, so the strict rule applies.
    vcsl           Versilian Community Sample Library, CC0 1.0 (repo LICENSE +
                   README: "Essentially it's Public Domain- you can do whatever
                   you want with these sounds (even make commercial software),
                   no royalties, no credit, no special terms").
    sfzinstruments 40 CC0-1.0 repos + 1 Unlicense + 9 attribution repos, taken
                   from the GitHub licence field and then CONFIRMED against the
                   LICENSE file in each repo (see verify_licences()).
    philharmonia   13,683 mp3 samples, 20 instruments. NOT a CC licence:
                   "You are free to use these samples as you wish, including
                   releasing them as part of a commercial work. The only
                   restriction is that they must not be sold or made available
                   'as is'". Commercial use granted, redistribution forbidden,
                   SILENT on AI — so mix-only under the silence rule, exactly
                   like the vendor packs in pack_ingest: license_id
                   'royalty-free-verified', no_ai_training=True, transform 'dsp'.
    iowa           University of Iowa Electronic Music Studios MIS — "These
                   recordings have been freely available on this website and
                   may be downloaded and used for any projects, without
                   restrictions." Enabled only when the masters are present.

REJECTED, and why — so none of it is re-argued
    FSS Steel-String Guitar, FreePats GM banks   GPL-3 (asset, not tool)
    FlameStudios.Kay5StringBanjo                 GPL
    Project16Rickenbacker4001                    non-commercial
    jlearman.jRhodes3c / 3d                      samples are CC BY-NC; only the
                                                 control files are CC0
    SamsSonor                                    CC-BY-SA-4.0 — syncing is an
                                                 Adaptation, so SA is banned
                                                 the same way the Wikimedia
                                                 schooner recording was
    SplendidGrandPiano                           README asserts Akai released
                                                 it to the public domain in
                                                 2000; that is a third-party
                                                 assertion with no primary
                                                 evidence, and re-tagged "PD"
                                                 uploads are a known trap. Fails
                                                 closed until evidence exists.
    every repo with no licence file at all       fails closed (Krumhorn,
                                                 OvationGuitar, Clavecin,
                                                 Terkelsen.*, DamiensFunkyGuitar,
                                                 SMDrums, GTownChurch, ...)

    python3 instrument_pack_ingest.py --plan       # counts, writes nothing
    python3 instrument_pack_ingest.py --verify     # re-read every licence file
    python3 instrument_pack_ingest.py --install
    python3 instrument_pack_ingest.py --report
"""

import json
import os
import re
import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

ALIB = os.path.join(_HERE, 'data', 'asset_libraries')
ORIG = os.path.join(ALIB, '_originals')
RUNTIME = os.path.join(_HERE, 'data', 'runtime')
VERIFY_JSON = os.path.join(RUNTIME, 'instrument_pack_licences.json')

CAT = 'instruments'
_AUDIO_EXT = ('.wav', '.flac', '.mp3', '.aif', '.aiff', '.ogg')
# Archive furniture: never a playable sample.
_SKIP_RE = re.compile(
    r'(?i)(^|/)(\.git|__MACOSX|docs?|documentation|images?|'
    r'screenshots?|demos?|examples?)(/|$)'
)
_SKIP_NAME_RE = re.compile(r'(?i)(demo|example|readme|license|licence|preview)')


def _slug(s, n=72):
    s = re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', str(s).lower())).strip('_')
    return s[:n].rstrip('_')


_PITCH_RE = re.compile(r'(?<![A-Za-z])([A-G])([#b]?)(-?[0-9])(?![0-9])')


def _pitch(stem):
    """'EWHarp_Normal_A#3_v2_RR1' -> 'A#3'. None when no note name is present
    (percussion, articulations, unpitched hits)."""
    m = _PITCH_RE.search(stem)
    return f'{m.group(1)}{m.group(2)}{m.group(3)}' if m else None


# ── licence blocks ───────────────────────────────────────────────────────────
_CC0 = {
    'license_id': 'cc0',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'no_ai_training': False,
    'no_redistribute': False,
    'transform': 'model',
}
_PD = dict(_CC0, license_id='public-domain')


def _ccby(version, credit):
    return {
        'license_id': f'cc-by-{version}',
        'commercial_ok': True,
        'attribution_required': True,
        'attribution': credit,
        'no_ai_training': False,
        'no_redistribute': False,
        'transform': 'model',
    }


_PHIL_URL = 'https://philharmonia.co.uk/resources/sound-samples/'
_LIC_PHIL = {
    'source': 'Philharmonia Orchestra (London) — Sound Samples',
    'source_url': _PHIL_URL,
    'license_id': 'royalty-free-verified',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'no_ai_training': True,
    'no_redistribute': True,
    'transform': 'dsp',
    'eula_url': _PHIL_URL,
    'eula_note': (
        'Philharmonia terms: "You are free to use these samples as you wish, '
        'including releasing them as part of a commercial work. The only '
        "restriction is that they must not be sold or made available 'as is' "
        '(i.e. as samples or as a sampler instrument)." SILENT on AI/ML — '
        'mix-only under the silence rule.'
    ),
}
_LIC_IOWA = {
    'source': 'University of Iowa Electronic Music Studios — Musical Instrument Samples',
    'source_url': 'https://theremin.music.uiowa.edu/MIS.html',
    'license_id': 'public-domain',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'no_ai_training': False,
    'no_redistribute': False,
    'transform': 'model',
    'eula_note': (
        'Iowa MIS page: "These recordings have been freely available on this '
        'website and may be downloaded and used for any projects, without '
        'restrictions."'
    ),
}


# ── routers ──────────────────────────────────────────────────────────────────
def _route_freepats(rel):
    """x_<set>/<archive dir>/samples/[<group>/]<stem>.<ext>"""
    parts = rel.split(os.sep)
    if len(parts) < 3 or not parts[0].startswith('x_'):
        return None
    setslug = parts[0][2:]
    try:
        i = [p.lower() for p in parts].index('samples')
    except ValueError:
        return None
    tail = parts[i + 1 :]
    if not tail:
        return None
    group = tail[-2] if len(tail) > 1 else 'samples'
    stem = os.path.splitext(tail[-1])[0]
    return (
        f'fp_{_slug(setslug, 40)}_{_slug(group, 18)}_{_slug(stem, 18)}',
        {'instrument': setslug.replace('_', ' '), 'group': group, 'descriptor': stem, 'pitch': _pitch(stem)},
    )


def _route_vcsl(rel):
    """VCSL-master/<Family>/.../<Instrument>/<stem>.wav"""
    parts = rel.split(os.sep)
    if len(parts) < 4:
        return None
    parts = parts[1:]  # drop the VCSL-master/ prefix
    if parts[0] in ('Assets',):
        return None
    family, instrument = parts[0], parts[-2]
    stem = os.path.splitext(parts[-1])[0]
    # 'EWHarp_Normal_A#3_v2_RR1' — articulation is the 2nd field when present
    bits = stem.split('_')
    artic = bits[1] if len(bits) > 2 else ''
    return (
        f'vcsl_{_slug(instrument, 34)}_{_slug(stem, 30)}',
        {
            'instrument': instrument,
            'family': family,
            'group': instrument,
            'descriptor': stem,
            'pitch': _pitch(stem),
            'articulation': artic,
        },
    )


def _route_vsco2(rel):
    """VSCO-2-CE-master/<Family>/<Instrument>/[<artic>/]<stem>.wav"""
    parts = rel.split(os.sep)
    if len(parts) < 3:
        return None
    parts = parts[1:]
    family, instrument = parts[0], parts[-2]
    stem = os.path.splitext(parts[-1])[0]
    return (
        f'vsco2_{_slug(instrument, 34)}_{_slug(stem, 30)}',
        {'instrument': instrument, 'family': family, 'group': instrument, 'descriptor': stem, 'pitch': _pitch(stem)},
    )


def _route_guitarset(rel):
    """audio_mono-mic/<player>_<style><tempo>-<key>-<progression>_<take>_mic.wav
    — 30 s solo acoustic guitar PERFORMANCES, not one-shots."""
    stem = os.path.splitext(os.path.basename(rel))[0]
    m = re.match(r'(\d+)_([A-Za-z]+)(\d*)-(\w+)-?(\w*)_(\w+)', stem)
    style = m.group(2) if m else ''
    return (
        f'gset_{_slug(stem, 62)}',
        {
            'instrument': 'acoustic guitar',
            'group': f'GuitarSet — {style or "excerpt"}',
            'descriptor': stem,
            'articulation': style,
            'performance': True,
        },
    )


def _route_sfzi(rel):
    """<repo>-<branch>/**/<stem>.<ext> — layout differs per repo, so the
    directory holding the file is the group."""
    parts = rel.split(os.sep)
    if len(parts) < 2:
        return None
    repo = re.sub(r'-(main|master)$', '', parts[0])
    stem = os.path.splitext(parts[-1])[0]
    group = parts[-2] if len(parts) > 2 else 'samples'
    return (
        f'sfzi_{_slug(repo, 34)}_{_slug(stem, 30)}',
        {'instrument': repo, 'group': group, 'descriptor': stem, 'pitch': _pitch(stem)},
    )


_PHIL_LEN = {'very-long', 'long', 'phrase', '1', '05', '025', '15', '2'}


def _route_phil(rel):
    """all-samples/<instrument>/<instr>_<pitch>_<length>_<dynamic>_<artic>.mp3"""
    parts = rel.split(os.sep)
    if len(parts) < 2:
        return None
    instrument = parts[-2]
    stem = os.path.splitext(parts[-1])[0]
    f = stem.split('_')
    pitch = f[1] if len(f) > 1 else ''
    length = f[2] if len(f) > 2 else ''
    dynamic = f[3] if len(f) > 3 else ''
    artic = '_'.join(f[4:]) if len(f) > 4 else 'normal'
    return (
        f'phil_{_slug(instrument, 18)}_{_slug(stem, 52)}',
        {
            'instrument': instrument,
            'group': f'{instrument} — {artic}',
            'descriptor': stem,
            'pitch': _pitch(pitch.replace('s', '#')) or pitch,
            'length': length,
            'dynamic': dynamic,
            'articulation': artic,
        },
    )


def _route_iowa(rel):
    """<instrument>/<Instr>.<dynamic>.<detail>.<channels>.aif"""
    parts = rel.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    instrument = parts[-2] if len(parts) > 1 else stem.split('.')[0]
    f = stem.split('.')
    dynamic = f[1] if len(f) > 1 else ''
    return (
        f'iowa_{_slug(stem, 62)}',
        {
            'instrument': instrument,
            'group': instrument,
            'descriptor': stem,
            'pitch': _pitch(stem),
            'dynamic': dynamic,
            'multi_note': True,
        },
    )


# ── multi-microphone collapse ────────────────────────────────────────────────
# A sampled drum kit ships ONE FILE PER MICROPHONE per hit: DRSKit records every
# stroke on 13 mics, Karoryfer's kits on 4-6. Those are not different sounds,
# they are simultaneous captures of the same sound meant to be SUMMED by a
# sampler engine — a library row reading "snare, close mic, bleed only" is not a
# usable one-shot. So files that are identical once the microphone token is
# removed from their path collapse to one, best perspective first.
#
# The rule is self-limiting BY CONSTRUCTION: two files only ever collapse when
# every other part of their path already matches, so a pack that is not
# mic-split (Philharmonia, VCSL, the guitars) cannot lose a single file. The
# masters stay untouched in _originals/, so another mic is a rule change away.
_MIC_VOCAB = {
    'ohl',
    'ohr',
    'oh',
    'ohs',
    'overhead',
    'overheads',
    'amb',
    'ambl',
    'ambr',
    'ambient',
    'room',
    'rooml',
    'roomr',
    'close',
    'cl',
    'closeroom',
    'top',
    'topone',
    'btm',
    'bottom',
    'bot',
    'sn',
    'snarebtm',
    'snaretop',
    'kdrum',
    'kdruml',
    'kdrumr',
    'kick',
    'kickin',
    'kickout',
    'ride',
    'ridel',
    'rider',
    'hihat',
    'hh',
    'trigger',
    'trig',
    'in',
    'out',
    'ms',
    'mono',
    'mix',
    'stereo',
    'direct',
    'di',
    'mic',
    'mic1',
    'mic2',
    'front',
    'back',
    'under',
    'over',
}
# best perspective first; anything not listed sorts after these, alphabetically
_MIC_RANK = [
    'ohl',
    'oh',
    'ohr',
    'ohs',
    'overhead',
    'overheads',
    'stereo',
    'ms',
    'mix',
    'mono',
    'top',
    'topone',
    'room',
    'rooml',
    'ambl',
    'amb',
    'ambient',
    'close',
    'closeroom',
    'cl',
]
# DrumGizmo convention: '<n>-<Hit name>-<MIC>.flac'. The last dash-token IS the
# microphone whatever it is called, so that position needs no vocabulary.
_DG_RE = re.compile(r'^(\d+)-(.+)-([A-Za-z0-9]+)$')


def _mic_strip(rel):
    """(key, mic) — `key` is the path with its microphone token removed, `mic`
    is that token (None when the file carries no microphone marker)."""
    parts = rel.split(os.sep)
    stem, ext = os.path.splitext(parts[-1])
    m = _DG_RE.match(stem)
    if m:
        return (os.sep.join(parts[:-1] + [f'{m.group(1)}-{m.group(2)}{ext}']), m.group(3).lower())
    # a whole path SEGMENT that is a microphone (Karoryfer: <drum>/<mic>/<rr>/)
    for i, seg in enumerate(parts[:-1]):
        if seg.lower() in _MIC_VOCAB:
            return (os.sep.join(parts[:i] + parts[i + 1 :]), seg.lower())
    # a leading or trailing filename token (swirly '..._rr1_top', NakedDrums
    # '-MS_Black_D2_20_three-P44L')
    bits = stem.split('_')
    if len(bits) > 1 and bits[-1].lower() in _MIC_VOCAB:
        return (os.sep.join(parts[:-1] + ['_'.join(bits[:-1]) + ext]), bits[-1].lower())
    if len(bits) > 1 and bits[0].lstrip('-').lower() in _MIC_VOCAB:
        return (os.sep.join(parts[:-1] + ['_'.join(bits[1:]) + ext]), bits[0].lstrip('-').lower())
    return (rel, None)


def _mic_score(mic):
    try:
        return (0, _MIC_RANK.index(mic))
    except ValueError:
        return (1, mic or '')


def collapse_mics(rows, log_fn=print):
    """Keep one microphone perspective per otherwise-identical file."""
    from collections import Counter, defaultdict

    groups = defaultdict(list)
    for r in rows:
        key, mic = _mic_strip(r['rel'])
        r['mic'] = mic
        groups[(r['src'], key)].append(r)
    keep, dropped = [], Counter()
    for _k, g in groups.items():
        if len(g) == 1:
            keep.append(g[0])
            continue
        g.sort(key=lambda r: _mic_score(r['mic']))
        keep.append(g[0])
        for r in g[1:]:
            dropped[r['src']] += 1
    if dropped:
        before = Counter(r['src'] for r in rows)
        for src, n in sorted(dropped.items()):
            log_fn(
                f'  [mic] {src}: {before[src]} -> {before[src] - n} ({n} duplicate microphone takes of the same hit)'
            )
    keep.sort(key=lambda r: (r['src'], r['rel']))
    return keep


# ── sources ──────────────────────────────────────────────────────────────────
# slug (dir under _originals), licence block, router, human label, licence
# evidence path relative to the source dir ('' = evidence is per-pack, checked
# by verify_licences()).
SOURCES = [
    ('freepats', _CC0, _route_freepats, 'FreePats (CC0)', ''),
    (
        'vcsl',
        dict(
            _CC0,
            source='Versilian Studios LLC — Versilian Community Sample Library',
            source_url='https://github.com/sgossner/VCSL',
        ),
        _route_vcsl,
        'Versilian Community Sample Library',
        'VCSL-master/LICENSE',
    ),
    ('sfzinstruments', _CC0, _route_sfzi, 'sfzinstruments.github.io', ''),
    (
        'vsco2ce',
        dict(
            _CC0,
            source='Versilian Studios LLC — VSCO 2 Community Edition',
            source_url='https://github.com/sgossner/VSCO-2-CE',
        ),
        _route_vsco2,
        'VSCO 2 Community Edition',
        'VSCO-2-CE-master/LICENSE',
    ),
    (
        'guitarset',
        _ccby('4.0', 'GuitarSet (Q. Xi, R. Bittner, J. Pauwels, X. Ye, J. P. Bello, ISMIR 2018) — CC BY 4.0'),
        _route_guitarset,
        'GuitarSet — solo acoustic guitar',
        '',
    ),
    ('philharmonia', _LIC_PHIL, _route_phil, 'Philharmonia Orchestra', ''),
    ('iowa', _LIC_IOWA, _route_iowa, 'University of Iowa MIS', ''),
]

# sfzinstruments repos whose licence is attribution-required rather than CC0.
# Credit strings are what license_gate() collects into the episode credits.
SFZI_ATTRIB = {
    'DrumGizmo.DRSKit': _ccby('4.0', 'DRSKit by the DrumGizmo project (CC BY 4.0)'),
    'DrumGizmo.MuldjordKit': _ccby('4.0', 'MuldjordKit by Jonas Suhr Christensen / DrumGizmo (CC BY 4.0)'),
    'WilkinsonAudio.NakedDrums': _ccby('4.0', 'Naked Drums by Wilkinson Audio (CC BY 4.0)'),
    'BengtNilsson.HeadroomPiano': _ccby('4.0', 'Headroom Piano by Bengt Nilsson (CC BY 4.0)'),
    'MTG.SoloSax': _ccby('4.0', 'Solo Sax by the Music Technology Group, UPF Barcelona (CC BY 4.0)'),
    'Ixox.Flute': _ccby('4.0', 'Ixox Flute by Xavier Hosxe (CC BY 4.0)'),
    'kinwie.dim-cabasa': _ccby('4.0', 'Dim Cabasa by kinwie (CC BY 4.0)'),
    'SalamanderGrandPiano': _ccby('3.0', 'Salamander Grand Piano by Alexander Holm (CC BY 3.0)'),
    'GregSullivan.E-Pianos': _ccby('3.0', 'E-Pianos by Greg Sullivan (CC BY 3.0)'),
}
SFZI_PD = {'jlearman.SteelDrum': dict(_PD, source='Jeff Learman — Steel Drum (Unlicense)')}


# ── enumeration ──────────────────────────────────────────────────────────────
def masters(slug):
    root = os.path.join(ORIG, slug)
    out = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if not _SKIP_RE.search(d)]
        for fn in fs:
            if not fn.lower().endswith(_AUDIO_EXT):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root)
            if _SKIP_RE.search(rel.replace(os.sep, '/')) or _SKIP_NAME_RE.match(fn):
                continue
            out.append((rel, full))
    return sorted(out)


def _sfzi_licence(rel, base):
    """Per-REPO licence for the sfzinstruments source: CC0 unless the repo is
    on one of the two exception lists. Unknown repo -> None (skipped), so a
    repo that lands in the dir without being licence-checked never installs."""
    repo = re.sub(r'-(main|master)$', '', rel.split(os.sep)[0])
    if repo in SFZI_ATTRIB:
        return dict(
            SFZI_ATTRIB[repo], source=f'sfzinstruments — {repo}', source_url=f'https://github.com/sfzinstruments/{repo}'
        )
    if repo in SFZI_PD:
        return dict(SFZI_PD[repo], source_url=f'https://github.com/sfzinstruments/{repo}')
    if repo in SFZI_CC0:
        return dict(
            base, source=f'sfzinstruments — {repo} (CC0)', source_url=f'https://github.com/sfzinstruments/{repo}'
        )
    return None


SFZI_CC0 = {
    'karoryfer.squidpipes',
    'karoryfer.gogodze-phu-vol-ii',
    'karoryfer.gogodze-phu-vol-i',
    'karoryfer.bear-sax',
    'karoryfer.war-tuba',
    'karoryfer.weresax',
    'karoryfer.string-cyborgs',
    'karoryfer.shinyguitar',
    'karoryfer.scarypiano',
    'karoryfer-bigcat.cello',
    'karoryfer.meatbass',
    'karoryfer.pastabass',
    'karoryfer.272-merry-orks',
    'karoryfer.cowsynth',
    'karoryfer.emilyguitar',
    'karoryfer.ergo',
    'karoryfer.fashionbass',
    'karoryfer.growlybass',
    'karoryfer.swagbass',
    'dsmolken.double-bass',
    'karoryfer.caveman-cosmonaut',
    'Karoryfer.TheHatWithThePhat',
    'zamenhof_stickmusterstuch_error',
    'virtuosity_drums',
    'body_percussion',
    'ganjo',
    'Karoryfer.HorsePulse',
    'karoryfer.black-and-green-guitars',
    'hungarian_zither',
    'karoryfer.sneakybass',
    'karoryfer.frankensnare',
    'karoryfer.unruly-drums',
    'karoryfer.big-rusty-drums',
    'karoryfer.swirly-drums',
    'karoryfer.black-and-blue-basses',
    'aliexpress-erhu',
    'cithara-barbarica',
    'karoryfer.big-little-bass',
    'Osiris_Piano',
}


def _freepats_licence(rel, base):
    """FreePats sets are CC0 per the text shipped inside each archive; the
    evidence file is recorded per record so the claim is auditable offline."""
    setdir = rel.split(os.sep)[0]
    ev = _FREEPATS_EVIDENCE.get(setdir)
    if not ev:
        return None
    return dict(
        base,
        source=f'FreePats — {setdir[2:].replace("_", " ")}',
        source_url='https://freepats.zenvoid.org/',
        eula=ev,
        eula_note='CC0 1.0 confirmed in the text shipped inside the archive',
    )


_FREEPATS_EVIDENCE = {}


def _scan_freepats_evidence():
    root = os.path.join(ORIG, 'freepats')
    if not os.path.isdir(root):
        return
    pat = re.compile(r'(?i)(licen[cs]e|readme|cc0)\.(txt|md)$')
    ok = re.compile(r'(?i)(cc0 1\.0|creative commons zero|cc0 public domain)')
    for setdir in sorted(os.listdir(root)):
        d = os.path.join(root, setdir)
        if not (setdir.startswith('x_') and os.path.isdir(d)):
            continue
        for dp, _dd, fs in os.walk(d):
            for fn in fs:
                if not pat.search(fn):
                    continue
                p = os.path.join(dp, fn)
                try:
                    txt = open(p, encoding='utf-8', errors='replace').read()
                except OSError as _exc:
                    _zyg_log.warning('freepats licence file %s unreadable, CC0 evidence may be missed: %s', p, _exc)
                    continue
                if ok.search(txt):
                    _FREEPATS_EVIDENCE[setdir] = os.path.relpath(p, ALIB)
                    break
            if setdir in _FREEPATS_EVIDENCE:
                break


_PER_FILE_LICENCE = {'sfzinstruments': _sfzi_licence, 'freepats': _freepats_licence}


def plan(log_fn=print):
    _scan_freepats_evidence()
    rows = []
    for slug, lic, router, label, _ev in SOURCES:
        ms = masters(slug)
        if not ms:
            log_fn(f'[plan] {slug}: no masters (not downloaded / not extracted)')
            continue
        per = _PER_FILE_LICENCE.get(slug)
        unlicensed = set()
        for rel, full in ms:
            r = router(rel)
            if r is None:
                continue
            filelic = per(rel, lic) if per else lic
            if filelic is None:
                unlicensed.add(rel.split(os.sep)[0])
                continue
            name, extra = r
            rows.append(
                {'src': slug, 'rel': rel, 'full': full, 'name': name, 'extra': extra, 'lic': filelic, 'label': label}
            )
        if unlicensed:
            log_fn(f'[plan] {slug}: SKIPPED {len(unlicensed)} unlicensed pack(s): ' + ', '.join(sorted(unlicensed)[:8]))
    rows = collapse_mics(rows, log_fn=log_fn)
    # disambiguate name collisions before register_audio_asset papers over them
    seen, dup = {}, 0
    for r in rows:
        if r['name'] in seen:
            dup += 1
            base = f'{r["name"]}_{_slug(r["extra"].get("group", "alt"), 16)}'
            if base in seen:
                base = f'{base}_{_slug(os.path.dirname(r["rel"])[-24:], 16)}'
            cand, i = base, 2
            while cand in seen:  # guaranteed unique, never left to the _2 fallback
                cand = f'{base}_{i}'
                i += 1
            r['name'] = cand
        seen[r['name']] = r
    from collections import Counter

    c = Counter(r['src'] for r in rows)
    for k, n in sorted(c.items()):
        log_fn(f'  {n:7d}  {k}')
    log_fn(f'[plan] {len(rows)} samples, {dup} name collisions disambiguated')
    return rows


# ── licence verification ─────────────────────────────────────────────────────
def verify_licences(log_fn=print):
    """Re-read the licence text that actually sits on disk for every source and
    report agreement with what SOURCES claims. Root-level metadata lies (the
    TripoSG lesson), so this reads the shipped files, never the index page."""
    _scan_freepats_evidence()
    out = {'freepats': {}, 'sfzinstruments': {}, 'vcsl': {}, 'philharmonia': {}}
    root = os.path.join(ORIG, 'freepats')
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            if d.startswith('x_') and os.path.isdir(os.path.join(root, d)):
                out['freepats'][d] = _FREEPATS_EVIDENCE.get(d) or 'NO CC0 EVIDENCE'
    root = os.path.join(ORIG, 'sfzinstruments')
    ok = re.compile(
        r'(?i)(cc0|creative commons zero|public domain|attribution 4\.0|'
        r'attribution 3\.0|unlicense)'
    )
    bad = re.compile(r'(?i)(noncommercial|non-commercial|share-?alike|GNU General Public)')
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d)
            if not os.path.isdir(p):
                continue
            repo = re.sub(r'-(main|master)$', '', d)
            txt = ''
            for fn in os.listdir(p):
                if re.search(r'(?i)^(licen[cs]e|copying|unlicense|readme)', fn):
                    try:
                        txt += open(os.path.join(p, fn), encoding='utf-8', errors='replace').read()[:4000]
                    except OSError as _exc:
                        _zyg_log.warning('licence file %s unreadable, attribution scan incomplete: %s', fn, _exc)
            claim = (
                'cc-by'
                if repo in SFZI_ATTRIB
                else 'public-domain'
                if repo in SFZI_PD
                else 'cc0'
                if repo in SFZI_CC0
                else 'UNLISTED'
            )
            hits = sorted(set(m.group(0).lower() for m in ok.finditer(txt)))
            flags = sorted(set(m.group(0).lower() for m in bad.finditer(txt)))
            out['sfzinstruments'][repo] = {'claim': claim, 'found': hits, 'conflict': flags}
    p = os.path.join(ORIG, 'vcsl', 'VCSL-master', 'LICENSE')
    if os.path.isfile(p):
        t = open(p, encoding='utf-8', errors='replace').read()
        out['vcsl'] = {'cc0_in_license_file': bool(re.search(r'(?i)cc0|creative commons zero', t))}
    os.makedirs(RUNTIME, exist_ok=True)
    json.dump(out, open(VERIFY_JSON, 'w'), indent=1)
    nofp = [k for k, v in out['freepats'].items() if v == 'NO CC0 EVIDENCE']
    conflicts = {
        k: v for k, v in out['sfzinstruments'].items() if v['conflict'] or v['claim'] == 'UNLISTED' or not v['found']
    }
    log_fn(f'[verify] freepats: {len(out["freepats"])} packs, {len(nofp)} WITHOUT CC0 evidence {nofp or ""}')
    log_fn(f'[verify] sfzinstruments: {len(out["sfzinstruments"])} repos, {len(conflicts)} needing a look')
    for k, v in sorted(conflicts.items()):
        log_fn(f'    {k}: claim={v["claim"]} found={v["found"]} conflict={v["conflict"]}')
    log_fn(f'[verify] vcsl: {out["vcsl"]}')
    log_fn(f'[verify] -> {VERIFY_JSON}')
    return out


# ── install ──────────────────────────────────────────────────────────────────
def install(rows=None, log_fn=print, limit=None):
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL

    rows = rows if rows is not None else plan(log_fn=lambda m: None)
    have = {}
    for fid, m in AL._load_audio_meta(CAT).items():
        if m.get('master'):
            have[m['master']] = fid
    stats = {'installed': 0, 'skipped': 0, 'failed': 0}
    # ONE sidecar write per BATCH, not per file: the per-file path rewrites the
    # whole licence book every time, so 66k files would rewrite a 90 MB json
    # 66k times. Flushed every BATCH and again in the finally, so a killed run
    # loses at most one batch of licence records — and audit_category() names
    # exactly which files those are.
    BATCH = 500
    sink = {}
    try:
        for i, r in enumerate(rows[:limit]):
            master_rel = os.path.relpath(r['full'], ALIB)
            if master_rel in have:
                stats['skipped'] += 1
                continue
            meta = dict(r['lic'])
            meta.update({k: v for k, v in r['extra'].items() if v not in (None, '')})
            meta.update({'pack': r['src'], 'pack_label': r['label'], 'master': master_rel})
            bits = [f'{r["label"]} — {r["extra"].get("instrument", "")}']
            if r['extra'].get('pitch'):
                bits.append(str(r['extra']['pitch']))
            for k in ('dynamic', 'articulation'):
                if r['extra'].get(k):
                    bits.append(str(r['extra'][k]))
            note = ' / '.join(b for b in bits if b.strip(' —'))
            if meta.get('no_ai_training'):
                note += '. Mix-only: no AI/model input, no redistribution'
            if meta.get('attribution_required'):
                note += f'. Credit required: {meta.get("attribution")}'
            meta['notes'] = note
            rec = ambience_ingest.register_audio_asset(
                CAT, r['full'], meta, name=r['name'], convert=True, log_fn=lambda m: None, meta_sink=sink
            )
            if rec:
                stats['installed'] += 1
                have[master_rel] = rec['id']
            else:
                stats['failed'] += 1
                if stats['failed'] <= 20:
                    log_fn(f'[install] FAILED {r["src"]}/{r["rel"]}')
            if len(sink) >= BATCH:
                ambience_ingest.flush_meta_sink(CAT, sink, log_fn=log_fn)
            if (i + 1) % 2000 == 0:
                log_fn(f'[install] {i + 1}/{len(rows[:limit])} — {stats}')
    finally:
        ambience_ingest.flush_meta_sink(CAT, sink, log_fn=log_fn)
    log_fn(f'[install] {stats}')
    return stats


def report(log_fn=print):
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL
    from collections import Counter

    recs = AL.load_assets(CAT)
    bad = ambience_ingest.audit_category(CAT)
    log_fn(f'{CAT}: {len(recs)} files; licence audit {"CLEAN" if not bad else str(len(bad)) + " UNCLEAN"}')
    for k, n in sorted(Counter(r.get('pack', '(unknown)') for r in recs).items()):
        log_fn(f'   {n:7d}  {k}')
    lic = Counter(r.get('license_id') for r in recs)
    log_fn(f'   licences: {dict(lic)}')
    log_fn(f'   attribution-required: {sum(1 for r in recs if r.get("attribution_required"))}')
    log_fn(f'   mix-only (no model input): {sum(1 for r in recs if r.get("no_ai_training"))}')
    inst = Counter(r.get('instrument') for r in recs)
    log_fn(f'   {len(inst)} distinct instruments; top 15:')
    for k, n in inst.most_common(15):
        log_fn(f'      {n:6d}  {k}')
    if bad:
        for b in bad[:10]:
            log_fn(f'   UNCLEAN {b}')


if __name__ == '__main__':
    a = sys.argv[1:] or ['--plan']
    if '--verify' in a:
        verify_licences()
    rows = plan()
    if '--install' in a:
        install(rows)
    if '--report' in a:
        report()
