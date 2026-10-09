# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vocal_fx_ingest.py — install the 344 Audio "Human Mouth Noises" library (2026-08-21).

The pipeline's first PAID audio licence, and the first non-verbal human performance
library it has ever had. Until now a character's sigh had to be SYNTHESISED: the
Cornelis cut renders 'A' + 'h'*20 and stretches it, because Chatterbox has no breath
token (see scene_cornelis_day1). 315 recorded mouth noises replace that whole class of
hack.

    masters   data/asset_libraries/_originals/344_human_mouth_noises/   96/192 kHz 24-bit
    working   data/asset_libraries/vocal_fx/                            48 kHz 16-bit
    licence   .../_originals/344_human_mouth_noises/LICENCE.md

WHY A SEPARATE CATEGORY. `sfx` is the ambience-bed library — seven files a scene loops
under dialogue. Pouring 315 one-shots into it would make choosing a bed impossible, and
the two are used differently: a bed runs the length of a scene, a vocal fx lands on a
single beat. The scene service resolves a bare `sfx:` filename across BOTH dirs
(_AUDIO_DIRS), so a spec never names the category.

WHY THE LICENCE NEEDED NEW MACHINERY. Every previous library file was CC0, where the
only question is "may this be published". This EULA grants commercial use but forbids
using the sounds "to train AI, machine learning, or neural networks" — and this pipeline
feeds audio to models as INPUT (a Chatterbox voice-clone reference is exactly that). So
every record lands with no_ai_training=True and ambience_ingest.training_gate() refuses
it wherever audio becomes model input. Mix-only. See LICENCE.md.

THE SPEECH SCAN, AND WHAT IT OVERTURNED
A modern British actor saying an English sentence cannot go in a 1672 Dutch cabin, and
sixteen filenames in this library ARE English sentences — "Begone from my sight",
"You Utter Disgrace!", "We are at an impasse". The obvious reading is that those files
contain those words. They do not. Whisper large-v3 (no VAD, so nothing gets trimmed)
transcribes them "Oof", "Oh", "Ugh": 344 Audio named the files by the SENTIMENT the
non-verbal sound carries, not by a transcript. Measured, not assumed — the assumption
was wrong and would have discarded the most useful emotional material in the library.

Reading the scan needs one non-obvious rule: WHISPER'S TEXT IS ONLY CREDIBLE WHEN
no_speech_prob IS LOW. Above ~0.7 it emits YouTube caption boilerplate — 60+ files here
transcribe as "Thanks for watching!" and one as "Subtitles by the Amara.org community".
Those are hallucinations on silence-shaped input, not speech. Real interjections sit at
0.04-0.5 and come back as "Ugh", "Ew", "Mwah". So `verbal` is only set when confidence
is HIGH (no_speech_prob < 0.55) AND the text carries a word that is neither an
interjection nor onomatopoeia. The per-file evidence is kept in the sidecar
(asr_text / asr_no_speech_prob) so this never has to be re-litigated by ear.

    python3 vocal_fx_ingest.py --scan            # (re)run the ASR pass
    python3 vocal_fx_ingest.py --install         # convert + register all 315
    python3 vocal_fx_ingest.py --report          # what is installed, and its licence
"""

import json
import os
import re
import sys
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

CAT = 'vocal_fx'
MASTERS = os.path.join(_HERE, 'data', 'asset_libraries', '_originals', '344_human_mouth_noises')
SFX_ROOT = os.path.join(MASTERS, 'Sound Effects')
SCAN_JSON = os.path.join(_HERE, 'data', 'runtime', 'vocal_fx_speech_scan.json')
ASR_PY = str(paths.ZYG_HOME / 'Zygomatic' / 'transcriber' / '.venv' / 'bin' / 'python')

LICENCE = {
    'source': '344 Audio Limited — Human Mouth Noises',
    'source_url': 'https://sonniss.com/sound-effects/human-mouth-noises',
    'license_id': 'royalty-free-verified',
    'commercial_ok': True,
    'attribution_required': False,
    'attribution': '',
    'purchased_from': 'Sonniss (1-user licence)',
    'purchase_date': '2026-08-21',
    # The two clauses that are STRICTER than CC0 — see LICENCE.md and
    # ambience_ingest.training_gate.
    'no_ai_training': True,
    'no_redistribute': True,
    'eula': '_originals/344_human_mouth_noises/Documentation/344-Audio-EULA-2025.pdf',
}

# Text that is a vocal gesture rather than a word. Whisper spells these freely
# ('ooooh', 'uuuuugh', 'hehehe'), so the run-collapsing below matters as much as
# the list: 'mmmmmmmm' must reduce to 'mm' before it is looked up.
_INTERJ = frozenset(
    """
 a ah aah ahh ahem ahhh argh aw aww ay bah beep bleh blech blergh brr cough
 duh eh er erm eugh ew eww gah grr ha hah haha hehe heh hm hmm hmph ho hoo
 huh hup la mm mmm mwah nah no oh oi ooh oof ough ow pff pfft phew psst ro
 shh sigh sniff tch tchuh tsk tut ugh uh uhh um umm wha whew whoa woah woo
 woof wow yay yeah yep yikes
 m grr gr hup pah bleugh blegh mwa
 huah hugh heugh urgh agh ugh nuh wah wa yah ya ra raagh rawr hyah nyeah
 bwah buh ruh ru ju u r ngh nngh ouch ow ouf argh aargh hey god ay aye oi oy
 hoo hooo yow yeow eek eep gah gaah grah hrgh hnng nng ah aah aaah
 roar boom moo rah blah hoop dun hiya doh tcha hurrah ooh eurgh
""".split()
)
# 2026-08-25: the Screams & Shouts 2 pack (1,055 wordless shouts) exposed 151
# gestures Whisper spells freely — 'HUAH!', 'NNNNNGH!', 'WAAAAAH', 'rawr' —
# none of them a word in any language. 'god' is the same word in Dutch and
# English and shouted in pain is a gesture, not dialogue.

# Whisper's well-known caption hallucinations. It emits these on silence-shaped
# or non-speech input, and they are not evidence of anything — 60+ files in this
# library transcribe as "Thanks for watching!". Most are already excluded by the
# confidence threshold; these two families leak under it, so they are named.
_HALLUCINATION = (
    'thanks for watching',
    'thank you for watching',
    'subtitles by',
    'amara.org',
    'subscribe',
    "we'll see you next time",
    'see you next time',
    'transcription by',
    'castingwords',
    'the end',
    'bye.',
)


def _collapse(w):
    """'uuuuuuugh' -> 'ugh', 'hehehehe' -> 'hehe'. Repeated letters are how a
    transcriber spells a SUSTAINED gesture; they are not new words."""
    w = re.sub(r'(.)\1{1,}', r'\1', w)  # runs of one letter -> one
    w = re.sub(r'^(he|ha|ho|mwa|do|ro|na|la)(\1)+$', r'\1\1', w)  # hehehe -> hehe
    return w


# 2026-08-25: a token Whisper invents for a roar ('raaagh', 'kusaaa', 'deugh',
# 'nullllll') is not a word in any language, and no interjection list can be
# long enough. So a token only counts as a WORD when the system dictionary
# knows it (after run-collapsing). Without a dictionary the gate is open, as
# before. Onomatopoeia the dictionary DOES know ('roar', 'boom', 'moo') sit in
# _INTERJ.
_DICT = None
for _dp in ('/usr/share/dict/words', '/usr/share/dict/american-english'):
    try:
        _DICT = frozenset(w.strip().lower() for w in open(_dp, encoding='utf-8', errors='ignore') if w.strip())
        break
    except OSError as _exc:
        _zyg_log.debug('word list %s unavailable, trying the next one: %s', _dp, _exc)
        continue


def _is_word(w):
    if _DICT is None:
        return True
    c = _collapse(w)
    return w in _DICT or c in _DICT or c.rstrip("'s") in _DICT


def classify(text, no_speech_prob):
    """(verbal: bool, why: str). See the module docstring — text is only trusted
    when the model is CONFIDENT there is speech; otherwise it is caption
    boilerplate hallucinated onto a non-speech recording."""
    t = (text or '').strip()
    if not t:
        return False, 'no text'
    if no_speech_prob is None or no_speech_prob >= 0.55:
        return False, f'not credible (no_speech_prob {no_speech_prob:.2f})'
    low = t.lower()
    if any(h in low for h in _HALLUCINATION):
        return False, 'caption hallucination'
    if sum(1 for c in t if ord(c) > 0x2000) >= 2:
        # runs of CJK/Cyrillic on an English-forced decode: the model has
        # nothing to decode and is wandering, not hearing words
        return False, 'non-latin hallucination'
    words = re.findall(r"[a-z']+", low)
    real = [w for w in words if w not in _INTERJ and _collapse(w) not in _INTERJ and _is_word(w)]
    if not real:
        return False, 'interjection only'
    return True, 'words: ' + ' '.join(real[:6])


# ── naming ───────────────────────────────────────────────────────────────────
# Delivered names are 'HMNMisc_Sigh_344 Audio_Human Mouth Noises.wav': a UCS
# category prefix, the descriptor, then vendor boilerplate. The descriptor is
# the only part worth keeping in a filename, prefixed with sex and folder so the
# flat library dir still sorts into something a person can read.


def _slug(s):
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', s.lower())).strip('_')


def parse_master(rel):
    """'Male Mouth Noises/Yawns/HMNBrth_Worn Out Yawn_344 Audio_....wav'
    -> {'sex','group','descriptor','ucs','name'}"""
    parts = rel.split(os.sep)
    sex = 'm' if parts[0].lower().startswith('male') else 'f'
    group = parts[1] if len(parts) > 2 else 'misc'
    stem = os.path.splitext(parts[-1])[0]
    ucs, _, rest = stem.partition('_')
    descriptor = rest.split('_344 Audio')[0].strip() or stem
    return {
        'sex': sex,
        'group': group,
        'descriptor': descriptor,
        'ucs': ucs,
        'name': f'{sex}_{_slug(group)}_{_slug(descriptor)}',
    }


def masters():
    out = []
    for dirpath, _dirs, files in os.walk(SFX_ROOT):
        for fn in files:
            if fn.lower().endswith('.wav'):
                full = os.path.join(dirpath, fn)
                out.append((os.path.relpath(full, SFX_ROOT), full))
    return sorted(out)


# ── the ASR pass ─────────────────────────────────────────────────────────────


def run_scan(log_fn=print):
    """Transcribe every master into SCAN_JSON. Runs under the transcriber venv,
    which is where faster-whisper lives (this service runs on /usr/bin/python3).
    vad_filter is OFF on purpose: the Silero VAD would trim the non-speech
    vocalisation that is the very thing being classified."""
    import subprocess

    code = r"""
import json, os, sys
from faster_whisper import WhisperModel
root, out = sys.argv[1], sys.argv[2]
dev, comp = 'cpu', 'int8'
try:
    import torch
    if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 5000*1024*1024:
        dev, comp = 'cuda', 'int8_float16'
except Exception as _exc:
    print(f'[scan] cuda probe failed, transcribing on cpu/int8: {_exc!r}', file=sys.stderr, flush=True)
m = WhisperModel('large-v3', device=dev, compute_type=comp)
res = {}
files = []
for dp, _d, fs in os.walk(root):
    files += [os.path.join(dp, f) for f in fs if f.lower().endswith('.wav')]
for i, f in enumerate(sorted(files)):
    rel = os.path.relpath(f, root)
    try:
        segs, _i = m.transcribe(f, language='en', vad_filter=False, beam_size=5)
        segs = list(segs)
        res[rel] = {'text': ' '.join((s.text or '').strip() for s in segs).strip(),
                    'no_speech_prob': min([s.no_speech_prob for s in segs], default=1.0),
                    'avg_logprob': max([s.avg_logprob for s in segs], default=-99.0)}
    except Exception as e:
        res[rel] = {'error': str(e)[:200]}
    if i % 25 == 0:
        print(f'[scan] {i}/{len(files)}', flush=True)
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(res, open(out, 'w'), indent=1)
"""
    if not os.path.isfile(ASR_PY):
        log_fn(f'[vocal-fx] no ASR interpreter at {ASR_PY}')
        return None
    r = subprocess.run([ASR_PY, '-c', code, SFX_ROOT, SCAN_JSON], timeout=7200)
    if r.returncode != 0:
        log_fn('[vocal-fx] scan failed')
        return None
    log_fn(f'[vocal-fx] scan written to {SCAN_JSON}')
    return SCAN_JSON


def load_scan():
    try:
        with open(SCAN_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ── install ──────────────────────────────────────────────────────────────────


def install(log_fn=print, limit=None):
    """Convert + register every master into the vocal_fx library.

    Idempotent by NAME: a master whose target filename is already registered is
    skipped rather than ingested again — register_audio_asset would otherwise
    uniquify to `_2` and quietly double the library on a re-run.
    """
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL

    scan = load_scan()
    if not scan:
        log_fn(
            '[vocal-fx] WARNING: no speech scan — install anyway, but the '
            'verbal flag will be unknown. Run --scan first.'
        )
    have = {r['id'] for r in AL.load_assets(CAT)}
    n_ok = n_skip = n_fail = n_verbal = 0
    for rel, full in masters()[:limit]:
        info = parse_master(rel)
        fn = info['name'] + '.wav'
        if fn in have:
            n_skip += 1
            continue
        s = scan.get(rel) or {}
        verbal, why = classify(s.get('text'), s.get('no_speech_prob'))
        if verbal:
            n_verbal += 1
        meta = dict(LICENCE)
        meta.update(
            {
                'sex': 'male' if info['sex'] == 'm' else 'female',
                'group': info['group'],
                'descriptor': info['descriptor'],
                'ucs_category': info['ucs'],
                'master': os.path.join('_originals', '344_human_mouth_noises', 'Sound Effects', rel),
                # The evidence, kept so the "does it contain words" question is
                # answered from a measurement rather than re-argued by ear.
                'asr_text': (s.get('text') or '')[:200],
                'asr_no_speech_prob': round(float(s.get('no_speech_prob', 1.0)), 3),
                'verbal': verbal,
                'verbal_why': why,
                'notes': (
                    f'344 Audio Human Mouth Noises — {info["descriptor"]} '
                    f'({info["group"]}, {"male" if info["sex"] == "m" else "female"}). '
                    f'Non-verbal: {why}.'
                    if not verbal
                    else f'344 Audio Human Mouth Noises — {info["descriptor"]}. '
                    f'CONTAINS SPEECH ({why}) — do not use in a non-English '
                    f'or period scene.'
                ),
            }
        )
        rec = ambience_ingest.register_audio_asset(
            CAT, full, meta, name=info['name'], convert=True, log_fn=lambda m: None
        )
        if rec:
            n_ok += 1
        else:
            n_fail += 1
            log_fn(f'[vocal-fx] FAILED {rel}')
    log_fn(
        f'[vocal-fx] installed {n_ok}, skipped {n_skip} (already present), '
        f'failed {n_fail}; {n_verbal} flagged as containing speech'
    )
    return {'installed': n_ok, 'skipped': n_skip, 'failed': n_fail, 'verbal': n_verbal}


def report(log_fn=print):
    from zyg_workflows import ambience_ingest
    from zyg_workflows import asset_library_service as AL

    recs = AL.load_assets(CAT)
    log_fn(f'{len(recs)} files in {CAT}')
    bad = ambience_ingest.audit_category(CAT)
    log_fn(f'licence audit: {len(bad)} unclean' if bad else 'licence audit: CLEAN')
    verbal = [r for r in recs if r.get('verbal')]
    log_fn(f'flagged as containing speech: {len(verbal)}')
    for r in verbal:
        log_fn(f'  {r["id"]}  {r.get("verbal_why")}')
    by = {}
    for r in recs:
        by.setdefault(f'{r.get("sex", "?")} / {r.get("group", "?")}', []).append(r)
    for k in sorted(by):
        log_fn(f'  {len(by[k]):3d}  {k}')
    g = ambience_ingest.training_gate([(CAT, r['id']) for r in recs[:5]], log_fn=lambda m: None)
    log_fn(f'training gate refuses vocal_fx: {not g["ok"]}  ({len(g["violations"])}/5 sampled refused)')
    return recs


if __name__ == '__main__':
    a = sys.argv[1:] or ['--report']
    if '--scan' in a:
        run_scan()
    if '--install' in a:
        install()
    if '--report' in a:
        report()
