# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_harvest_kyutai.py — import the Kyutai CC0 voice donations as seeds.

WHAT THIS TAKES, AND WHAT IT DELIBERATELY LEAVES
------------------------------------------------
kyutai/tts-voices holds two things that look alike and are not. The `.wav` files
are plain audio and clone through any zero-shot engine, which is all this codebase
ever needs from a voice. The `.safetensors` siblings are voice EMBEDDINGS for
Kyutai's own TTS, pinned to its checkpoint (1e68beda@240), and they are useless
here — Kyutai withheld the encoder that makes them, so that model can only ever
speak in voices they shipped and could never say Abel. We take the wavs (110 MB
raw + 146 MB enhanced) and skip the embeddings (117 MB).

WHY THIS COLLECTION AND NOT A BIGGER ONE
----------------------------------------
Licence is the easy half: voice-donations is CC0, which clears the assets rule
that CC BY 4.0 banks (VCTK, LibriTTS-R) do not, and that the CC-BY-NC ones
(Expresso, EARS, VoxPopuli) fail outright on a monetised channel. The half that
usually gets skipped is CONSENT: these were donated to the Unmute Voice Donation
Project (June 2025 – February 2026, 228 of 374 submissions passed verification)
BY people who knew they were donating a voice to a speech model. A CC0 licence on
a corpus recorded for speech recognition would clear the same legal bar and would
not clear that one.

RAW vs _enhanced
----------------
Both are fetched. Enhanced is denoised, and denoising moves formants — which is
exactly the measurement this codebase uses to decide who is speaking. Neither is
declared the winner here: the raw file is registered as the seed because it is
the unmodified donation, the enhanced one is kept alongside so the operator can
A/B them on the meters. Judge it per voice, not once for the collection.

CLASSIFICATION IS FROM MEASUREMENT, NOT FROM PROSE
--------------------------------------------------
The donations arrive as opaque hex ids (0a67.wav) with NO gender, age or accent
metadata anywhere in the repo, which is why 228 CC0 voices are not the same thing
as 228 usable voices. Every wav is measured through the same Praat path the
Voices tab uses, and the name, sex and age band are derived from what came back.
This is also the lesson the Maya1 pool taught the hard way on 2026-08-11: eight
seeds whose written descriptions promised a tenor-to-bass range all measured
within two semitones of each other, and one described as "late teens" rendered
as a full adult male. Descriptions do not survive measurement, so nothing here
is allowed to depend on one.

NOTE the measurement is of the SOURCE wav, not of a render. voice_studio's own
comments record that the two differ (13.87 cm seed vs 11.99 cm render on Abel),
because the engine re-synthesises rather than replays. Source metrics are the
right signal for BROWSING — is this a deep male or a bright female — and the
wrong one for gating a take. The tab still measures every render.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(_HERE, 'data', 'assets', 'voice_seeds', 'kyutai')
MANIFEST = os.path.join(DEST, 'manifest.json')

REPO = 'kyutai/tts-voices'
#: Hub revision the donations are fetched at. 'main' is NOT a pin — the dataset card carries no
#: commit this repository can cite; set $ZYG_KYUTAI_REVISION to a sha for a reproducible fetch.
REVISION = os.environ.get('ZYG_KYUTAI_REVISION', 'main')
SUBDIR = 'voice-donations'
LICENCE = 'cc0-1.0'
PROVENANCE = (
    'Unmute Voice Donation Project (Kyutai), June 2025 – February 2026: '
    '228 of 374 submissions passed verification. Released CC0. Donors '
    'submitted knowingly for use in a speech model.'
)


# ─────────────────────────────────────────────────────────────────── download
def download(dest: str = DEST) -> int:
    """Fetch every donation wav. Returns the count on disk afterwards.

    allow_patterns carries the whole point of this function: the default snapshot
    would also drag down 117 MB of Kyutai-only embeddings that nothing in this
    codebase can read.
    """
    from huggingface_hub import snapshot_download

    os.makedirs(dest, exist_ok=True)
    snapshot_download(
        repo_id=REPO,
        repo_type='model',
        revision=REVISION,
        local_dir=dest,
        allow_patterns=[f'{SUBDIR}/*.wav'],
    )
    return len(_raw_wavs(dest))


def _raw_wavs(dest: str) -> list:
    """The donations proper — the enhanced copies are variants of these, not
    separate speakers, and counting them would double the collection."""
    d = os.path.join(dest, SUBDIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names if n.endswith('.wav') and not n.endswith('_enhanced.wav')]


# ──────────────────────────────────────────────────────────────── measurement
def measure_all(wavs: list, chunk: int = 40, log=print) -> dict:
    """path -> metrics, via the voice_analysis venv. Batched: the analysis script
    takes many wavs per invocation, and 228 separate interpreter starts cost more
    than the measuring does."""
    from zyg_workflows import voice_qc

    if not voice_qc.enabled():
        raise RuntimeError(
            'voice QC disabled or analysis venv missing — classification is the whole job, so this cannot degrade'
        )
    out = {}
    for i in range(0, len(wavs), chunk):
        batch = wavs[i : i + chunk]
        try:
            r = subprocess.run(
                [voice_qc._ANALYSIS_PY, voice_qc._ANALYSIS_SCRIPT] + batch, capture_output=True, text=True, timeout=900
            )
            rows = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            log(f'  batch {i // chunk + 1}: FAILED ({e!r}) — falling back one by one')
            rows = [(voice_qc.measure(w) or [{}])[0] for w in batch]
        for row in rows:
            if isinstance(row, dict) and row.get('path'):
                out[row['path']] = row
        log(f'  measured {min(i + chunk, len(wavs))}/{len(wavs)}')
    return out


# Buckets are for SCANNING a list of 228, not for gating anything. Cut points sit
# near the published norms (adult male ~116 Hz, adult female ~205 Hz) and near
# where the Maya1 pool actually landed on this box, so a bucket means roughly the
# same thing across both collections.
_MALE_BUCKETS = ((95.0, 'deep'), (115.0, 'mid'), (1e9, 'light'))
_FEMALE_BUCKETS = ((175.0, 'low'), (200.0, 'mid'), (1e9, 'bright'))


# Plausibility rails. Adult vocal tracts run about 13–20 cm and speaking F0 about
# 75–300 Hz; outside those, Praat has not measured a voice, it has fitted noise.
# Donations that trip these are KEPT and flagged, never dropped — the ids are
# donor-chosen and 'WhisperInEar' is exactly what it says, a whisper, which has no
# fundamental to track and is still a perfectly good intimate reference. Throwing
# away a good voice because one metric cannot describe it is the wrong trade.
_VTL_SANE = (12.5, 19.5)
_F0_SANE = (70.0, 300.0)


def classify(m: dict) -> dict:
    """Sex, bucket and age band from F0 + VTL. {} when nothing is measurable."""
    f0, vtl = m.get('f0_median_hz'), m.get('vtl_cm')
    # NaN survives JSON as a float that fails equality with itself.
    if f0 is None or vtl is None or f0 != f0 or vtl != vtl:
        return {}
    verdict = str(m.get('verdict') or '')
    # Whether the sex was READ off voice_qc's verdict or GUESSED afterwards is
    # itself worth recording. Measured on this box: kd_selfie's source sits at
    # 155.1 Hz over a 15.4 cm tract — 'ambiguous', a hair under the 15.5 cut, so
    # the fallback called it female; the render came back at 123.0 Hz, which is
    # nobody's adult female. A guess presented like a reading is the failure mode
    # here, not the guess itself, so the label carries its own provenance.
    sex_certain = verdict == 'adult male' or verdict.startswith('adult female')
    if verdict == 'adult male':
        sex = 'm'
    elif verdict.startswith('adult female'):
        sex = 'f'
    elif f0 < 140.0:
        # Deciding this on VTL alone was a bug worth naming: donation 'stein'
        # measures 88.9 Hz over a 14.72 cm tract, and the tract-only rule called
        # it female. No adult female speaks at 89 Hz, so when the pitch is that
        # decisive it outranks a formant fit that is evidently off — which is the
        # opposite of the usual rule here, and correct for the opposite reason:
        # the normal danger is a fake F0 over a real tract, not this.
        sex = 'm'
    elif f0 >= 190.0:
        sex = 'f'
    else:
        # Genuinely in the overlap. VTL decides, as the cue this codebase trusts
        # when pitch and size disagree.
        sex = 'm' if vtl >= 15.5 else 'f'
    # Confidence is about whether the NUMBERS can be believed, not about the
    # audio. Anything the operator should not sort by silently.
    unsane = not _VTL_SANE[0] <= vtl <= _VTL_SANE[1] or not _F0_SANE[0] <= f0 <= _F0_SANE[1]
    disagree = (f0 < 140.0 and vtl < 15.0) or (f0 > 190.0 and vtl > 16.0)
    low = unsane or disagree
    buckets = _MALE_BUCKETS if sex == 'm' else _FEMALE_BUCKETS
    bucket = next(label for cut, label in buckets if f0 < cut)
    # Band = what voice_qc will grade a render of this seed against. Anything
    # reading child/adolescent gets the loose 'adolescent' band rather than an
    # adult one that would fail it on arrival.
    if f0 >= 200 and vtl <= 14.5:
        band = 'adolescent'
    else:
        band = 'adult_male' if sex == 'm' else 'adult_female'
    return {
        'sex': sex,
        'bucket': bucket,
        'band': band,
        'verdict': verdict,
        'confidence': 'low' if low else 'ok',
        'sex_certain': sex_certain,
        'f0_hz': round(float(f0), 1),
        'vtl_cm': round(float(vtl), 2),
        'duration_s': m.get('duration_s'),
        'voiced_frames': m.get('voiced_frames'),
    }


# A donation with almost no voiced audio cannot be measured OR cloned well, and
# admitting it would put a voice in the sidebar that fails the moment it is
# opened. Praat needs voiced frames; so does a cloner.
_MIN_VOICED_FRAMES = 60
_MIN_DURATION_S = 3.0


def _safe_id(donation_id: str, taken: set) -> str:
    """'Andrea_(Spanish)' -> 'kd_andrea_spanish'.

    The upstream ids are NOT all hex. Donors named their own uploads, so the
    collection contains 'WhisperInEar', "Muhtasim's_Voice" and 'Andrea_(Spanish)'
    alongside '0a67'. A voice id becomes a URL parameter and a preset DIRECTORY
    name, so voice_studio refuses anything outside [a-z0-9_-] — which silently
    dropped exactly three donations, two of them the Spanish-accented pair, i.e.
    the accent range this bank is being imported for. Slugify here rather than
    loosening the rule there: the id has to stay boring, and the original is kept
    as donation_id for display.
    """
    slug = re.sub(r'[^a-z0-9]+', '_', donation_id.lower()).strip('_')[:48]
    base = f'kd_{slug or "voice"}'
    out, n = base, 2
    while out in taken:  # 'Andrea (Spanish)' and 'Andrea_Spanish' collide
        out = f'{base}_{n}'
        n += 1
    taken.add(out)
    return out


def build(dest: str = DEST, log=print) -> dict:
    """Measure everything on disk and write manifest.json. Returns a summary."""
    wavs = _raw_wavs(dest)
    if not wavs:
        raise RuntimeError(f'no wavs under {dest} — run download() first')
    log(f'measuring {len(wavs)} donations…')
    metrics = measure_all(wavs, log=log)
    voices, skipped, taken, renamed = [], [], set(), []
    for w in wavs:
        vid_hex = os.path.basename(w)[:-4]
        m = metrics.get(w) or metrics.get(os.path.abspath(w)) or {}
        c = classify(m)
        dur = float(m.get('duration_s') or 0.0)
        if not c:
            skipped.append((vid_hex, 'unmeasurable'))
            continue
        if dur < _MIN_DURATION_S:
            skipped.append((vid_hex, f'{dur:.1f}s too short'))
            continue
        if int(m.get('voiced_frames') or 0) < _MIN_VOICED_FRAMES:
            skipped.append((vid_hex, 'too few voiced frames'))
            continue
        enh = w[:-4] + '_enhanced.wav'
        sexword = 'Male' if c['sex'] == 'm' else 'Female'
        vid = _safe_id(vid_hex, taken)
        if vid != f'kd_{vid_hex.lower()}':
            renamed.append((vid_hex, vid))
        voices.append(
            {
                # 'kd' = kyutai donation. Prefixed because the id becomes a preset
                # DIRECTORY name, and a bare hex string collides far too easily with
                # anything else that ever gets imported.
                'name': vid,
                'donation_id': vid_hex,
                'gender': c['sex'],
                'bucket': c['bucket'],
                'band': c['band'],
                'display': f'{c["bucket"].title()} {sexword.lower()} · {vid_hex}',
                # The flag goes in the ROLE, where the rail already prints it. A
                # low-confidence voice that looks identical to a measured one in the
                # list is worse than no measurement at all.
                # 'src' is not decoration: these are SOURCE-wav numbers and the render
                # will differ. Measured spread on four donations spanning the range:
                # −4.5, +5.6, +9.1 Hz — small and not systematic, so source is a sound
                # way to BROWSE. The fourth was the whisper, off by −178 Hz, which is
                # what the unreliable flag is for.
                'role': (
                    f'{sexword}{"?" if not c["sex_certain"] else ""} · '
                    f'{c["bucket"]} · src {c["f0_hz"]:g} Hz · {c["vtl_cm"]:g} cm'
                    + (' · ⚠ metrics unreliable' if c['confidence'] == 'low' else '')
                    + (' · sex inferred' if not c['sex_certain'] else '')
                ),
                'confidence': c['confidence'],
                'sex_certain': c['sex_certain'],
                'wav': w,
                'enhanced_wav': enh if os.path.isfile(enh) else '',
                'duration_s': round(dur, 2),
                'f0_hz': c['f0_hz'],
                'vtl_cm': c['vtl_cm'],
                'verdict': c['verdict'],
            }
        )
    voices.sort(key=lambda v: (v['gender'], v['f0_hz']))
    man = {
        'source': f'{REPO}/{SUBDIR}',
        'license': LICENCE,
        'provenance': PROVENANCE,
        'purpose': 'reference voices cloned by IndexTTS-2 / Chatterbox',
        'measured': 'source wav via voice_analysis (Praat), NOT a render',
        'skipped': [{'id': i, 'why': w} for i, w in skipped],
        'renamed': [{'from': a, 'to': b} for a, b in renamed],
        'voices': voices,
    }
    tmp = MANIFEST + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=2)
    os.replace(tmp, MANIFEST)
    with open(os.path.join(dest, 'PROVENANCE.txt'), 'w', encoding='utf-8') as f:
        f.write(
            f'{REPO}/{SUBDIR}\nLicence: {LICENCE}\n\n{PROVENANCE}\n\n'
            'The .safetensors voice embeddings in the upstream repo are NOT '
            'fetched: they are Kyutai-model-specific and unreadable here.\n'
        )
    return {
        'kept': len(voices),
        'skipped': skipped,
        'renamed': renamed,
        'male': sum(1 for v in voices if v['gender'] == 'm'),
        'female': sum(1 for v in voices if v['gender'] == 'f'),
        'low_conf': sum(1 for v in voices if v.get('confidence') == 'low'),
        'sex_guessed': sum(1 for v in voices if not v.get('sex_certain')),
    }


if __name__ == '__main__':  # pragma: no cover — operator tool
    import argparse

    ap = argparse.ArgumentParser(description='Harvest the Kyutai CC0 voice donations')
    ap.add_argument('--skip-download', action='store_true')
    a = ap.parse_args()
    if not a.skip_download:
        print(f'downloading {REPO}/{SUBDIR} wavs (skipping .safetensors)…')
        print(f'  {download()} donations on disk')
    s = build()
    print(
        f'\nkept {s["kept"]} ({s["male"]} male / {s["female"]} female; '
        f"{s['low_conf']} flagged 'metrics unreliable', "
        f'{s["sex_guessed"]} with sex inferred rather than read)'
    )
    if s['skipped']:
        print(f'skipped {len(s["skipped"])}:')
        for i, w in s['skipped'][:20]:
            print(f'  {i}  {w}')
    print(f'\nmanifest: {MANIFEST}')
    sys.exit(0)
