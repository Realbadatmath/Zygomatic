#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Source CC0 / CC-BY eagle + red-tailed hawk calls from Freesound into the SFX library.

The SFX libraries hold no real eagle. The classic film "eagle cry" is in fact a
red-tailed hawk: a descending scream that falls from ~3.5 kHz to ~2 kHz over
roughly a second. This script searches Freesound for that sound, keeps ONLY
licences we may ship commercially (CC0 first tier, CC-BY 4.0/3.0 second tier
with attribution), downloads the HQ MP3 previews (no OAuth needed), converts
them to 48 kHz mono 24-bit wav in data/asset_libraries/sfx/, measures each one
(duration, peak, spectral centroid, glide, spoken-slate suspicion), writes
eagle_shortlist.json and registers every file's provenance with
asset_library_service.set_audio_meta.

Usage:  python source_eagle_call.py [--limit 10] [--dry-run]
Key:    FREESOUND_API_KEY, else first line of ~/.config/zygomatic/freesound.key
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse

import numpy as np

from zyg_workflows.bin import exe
from zyg_workflows import http_json

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.join(HERE, 'data', 'asset_libraries', 'sfx')
ORIG_DIR = os.path.join(HERE, 'data', 'asset_libraries', '_originals', 'freesound_eagle')
SHORTLIST = os.path.join(SFX_DIR, 'eagle_shortlist.json')
KEY_FILE = os.path.expanduser('~/.config/zygomatic/freesound.key')
ADDED_DATE = '2026-09-14'

QUERIES = [
    'red-tailed hawk scream',
    'red tailed hawk',
    'hawk screech',
    'eagle call',
    'eagle scream',
    'bald eagle',
    'golden eagle call',
]

FIELDS = 'id,name,license,duration,previews,username,url,tags,avg_rating,num_downloads'

# Exact licence URLs the Freesound API returns. Anything not in here (NC, ND,
# sampling+) is dropped — we may not ship it.
LICENCE_TIERS = {
    'http://creativecommons.org/publicdomain/zero/1.0/': ('cc0', 1),
    'https://creativecommons.org/publicdomain/zero/1.0/': ('cc0', 1),
    'http://creativecommons.org/licenses/by/4.0/': ('cc-by-4.0', 2),
    'https://creativecommons.org/licenses/by/4.0/': ('cc-by-4.0', 2),
    'http://creativecommons.org/licenses/by/3.0/': ('cc-by-3.0', 2),
    'https://creativecommons.org/licenses/by/3.0/': ('cc-by-3.0', 2),
}

SR = 48000
NFFT = 2048
HOP = 512

# The queries pull in sound-alikes that are not birds: a horror scream, an
# "eagle-like" synth, a Space 1999 spaceship called Eagle, a banshee. They are
# licence-clean but they are not what the library is missing, and once written
# as eagle_NN.wav they are in the SFX rail for good. Require a real bird-of-prey
# word, and reject the fiction/synthesis markers.
RAPTOR_WORDS = (
    'eagle',
    'hawk',
    'falcon',
    'raptor',
    'buzzard',
    'kite',
    'osprey',
    'birdofprey',
    'bird-of-prey',
    'birdsofprey',
    'kestrel',
)
NOT_A_BIRD = (
    'demonic',
    'banshee',
    'monster',
    'creature',
    'fantasy',
    'griffin',
    'gryffin',
    'sci-fi',
    'scifi',
    'fiction',
    'electronic',
    'robotics',
    'digital',
    'comlock',
    'intercom',
    'horror',
    'halloween',
    'synth',
)


def is_bird_of_prey(sound):
    """True when the name+tags name a real raptor and carry no fiction marker."""
    hay = (str(sound.get('name') or '') + ' ' + ' '.join(sound.get('tags') or [])).lower()
    if any(w in hay for w in NOT_A_BIRD):
        return False
    return any(w in hay for w in RAPTOR_WORDS)


def api_key():
    k = os.environ.get('FREESOUND_API_KEY', '').strip()
    if k:
        return k
    try:
        with open(KEY_FILE, 'r', encoding='utf-8') as f:
            return f.readline().strip()
    except OSError:
        return ''


def slug(text, maxlen=32):
    s = re.sub(r'[^a-z0-9]+', '_', str(text or '').lower()).strip('_')
    return s[:maxlen].rstrip('_') or 'sound'


def search(query, key):
    params = urllib.parse.urlencode(
        {
            'query': query,
            'fields': FIELDS,
            'filter': 'duration:[0.5 TO 12]',
            'sort': 'rating_desc',
            'page_size': 15,
            'token': key,
        }
    )
    url = f'https://freesound.org/apiv2/search/text/?{params}'
    body = http_json.request_json(url, headers={'User-Agent': 'Zygomatic/1.0'}, timeout=30)
    return body.get('results', [])


def collect(key):
    """All licence-clean, de-duplicated candidates across every query."""
    seen, out, dropped, offtopic = {}, [], {}, []
    for q in QUERIES:
        try:
            results = search(q, key)
        except Exception as e:  # noqa: BLE001
            _zyg_log.info(f'  ! search "{q}" failed: {e}')
            continue
        kept = 0
        for r in results:
            lic = (r.get('license') or '').strip()
            tier = LICENCE_TIERS.get(lic)
            if not tier:
                dropped[lic] = dropped.get(lic, 0) + 1
                continue
            sid = r.get('id')
            if sid in seen:
                continue
            seen[sid] = True
            if not is_bird_of_prey(r):
                offtopic.append(f'{sid} {r.get("name", "")[:38]}')
                continue
            r['_license_id'], r['_tier'] = tier
            r['_query'] = q
            out.append(r)
            kept += 1
        _zyg_log.info(f'  {q:28s} {len(results):3d} results, {kept:2d} new licence-clean')
    if dropped:
        _zyg_log.info(
            '  dropped licences: '
            + ', '.join(f'{v}x {k.rsplit("/licenses/", 1)[-1].rstrip("/")}' for k, v in sorted(dropped.items()))
        )
    for o in offtopic:
        _zyg_log.info(f'  dropped (not a bird of prey): {o}')
    return out


def download(sound, dest):
    url = (sound.get('previews') or {}).get('preview-hq-mp3')
    if not url:
        return False
    if os.path.exists(dest) and os.path.getsize(dest) > 3000:
        return True
    r = subprocess.run(
        [exe('curl'), '-sL', '--max-time', '60', '-A', 'Zygomatic/1.0', '-o', dest, url],
        capture_output=True,
        timeout=90,
    )
    return r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 3000


def to_wav(src, dest):
    r = subprocess.run(
        [exe('ffmpeg'), '-y', '-v', 'error', '-i', src, '-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s24le', dest],
        capture_output=True,
        timeout=120,
    )
    if r.returncode != 0:
        _zyg_log.info(f'  ! ffmpeg: {r.stderr.decode("utf-8", "replace").strip()[:200]}')
        return False
    return os.path.exists(dest) and os.path.getsize(dest) > 1000


def decode(path):
    """Mono float32 samples at SR."""
    r = subprocess.run(
        [exe('ffmpeg'), '-v', 'error', '-i', path, '-f', 'f32le', '-ar', str(SR), '-ac', '1', '-'],
        capture_output=True,
        timeout=120,
    )
    if r.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(r.stdout, dtype=np.float32)


def stft(x):
    """(mag[frames, bins], freqs, frame_times) — Hann, NFFT/HOP."""
    if x.size < NFFT:
        x = np.pad(x, (0, NFFT - x.size))
    n = 1 + (x.size - NFFT) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    win = np.hanning(NFFT).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    freqs = np.fft.rfftfreq(NFFT, 1.0 / SR)
    times = np.arange(n) * HOP / SR
    return mag, freqs, times


def has_glide(mag, freqs, times):
    """A descending scream: the dominant partial starts in 2.5-5 kHz and falls
    by >= 0.8 kHz within 1.5 s. Quiet frames are ignored (their argmax is noise)."""
    band = (freqs >= 500) & (freqs <= 9000)
    sub, fsub = mag[:, band], freqs[band]
    if sub.size == 0:
        return False
    energy = sub.sum(axis=1)
    if not energy.any():
        return False
    loud = energy > energy.max() * 0.15
    dom = fsub[np.argmax(sub, axis=1)]
    starts = np.where(loud & (dom >= 2500) & (dom <= 5000))[0]
    for i in starts:
        ahead = (times > times[i]) & (times <= times[i] + 1.5) & loud
        if ahead.any() and dom[ahead].min() <= dom[i] - 800:
            return True
    return False


def slate_suspect(x, mag, freqs, times):
    """Field recordings often open with a spoken slate ("red-tailed hawk, take
    two"). Flag a burst > 20 dB above the file's median RMS in the first 2 s
    that puts 40-66 % of its energy in the 200-3000 Hz speech band."""
    frames = mag.shape[0]
    n = 1 + max(0, (x.size - NFFT)) // HOP
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(min(n, frames))[:, None]
    if idx.size == 0:
        return False
    rms = np.sqrt((x[idx].astype(np.float64) ** 2).mean(axis=1)) + 1e-12
    med = float(np.median(rms))
    speech = (freqs >= 200) & (freqs <= 3000)
    power = mag.astype(np.float64) ** 2
    total = power.sum(axis=1) + 1e-12
    ratio = power[:, speech].sum(axis=1) / total
    for i in range(min(len(rms), len(ratio))):
        if times[i] > 2.0:
            break
        if 20.0 * math.log10(rms[i] / med) > 20.0 and 0.40 <= ratio[i] <= 0.66:
            return True
    return False


def measure(path):
    x = decode(path)
    if x.size == 0:
        return None
    peak = float(np.abs(x).max())
    mag, freqs, times = stft(x)
    power = mag.astype(np.float64) ** 2
    tot = power.sum()
    centroid = float((power.sum(axis=0) * freqs).sum() / tot) if tot > 0 else 0.0
    return {
        'duration_s': round(x.size / SR, 3),
        'peak_db': round(20.0 * math.log10(peak), 2) if peak > 0 else -120.0,
        'centroid_hz': round(centroid, 1),
        'glide': bool(has_glide(mag, freqs, times)),
        'slate_suspect': bool(slate_suspect(x, mag, freqs, times)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10, help='max previews to download')
    ap.add_argument('--dry-run', action='store_true', help='search + rank only')
    args = ap.parse_args()

    key = api_key()
    if not key:
        print(f'FREESOUND_API_KEY unset and no key at {KEY_FILE}', file=sys.stderr)
        return 2

    os.makedirs(SFX_DIR, exist_ok=True)
    os.makedirs(ORIG_DIR, exist_ok=True)

    print('searching Freesound…')
    cands = collect(key)
    if not cands:
        print('no licence-clean candidates', file=sys.stderr)
        return 1
    # Pre-download order: CC0 before CC-BY, then community rating, then reach.
    cands.sort(key=lambda r: (r['_tier'], -float(r.get('avg_rating') or 0), -int(r.get('num_downloads') or 0)))
    print(f'{len(cands)} licence-clean candidates; downloading up to {args.limit}')
    if args.dry_run:
        for r in cands[: args.limit]:
            print(f'  [{r["_license_id"]:10s}] {r["id"]:8d} {r.get("name", "")[:50]}')
        return 0

    rows, nn = [], 0
    for r in cands:
        if nn >= args.limit:
            break
        sid, name = r['id'], r.get('name') or ''
        sl = slug(os.path.splitext(name)[0])
        mp3 = os.path.join(ORIG_DIR, f'{sid}_{sl}.mp3')
        if not download(r, mp3):
            print(f'  ! download failed {sid} {name[:40]}')
            continue
        nn += 1
        wav_name = f'eagle_{nn:02d}_{sl}.wav'
        wav = os.path.join(SFX_DIR, wav_name)
        if not to_wav(mp3, wav):
            print(f'  ! convert failed {sid} {name[:40]}')
            nn -= 1
            continue
        m = measure(wav)
        if m is None:
            print(f'  ! measure failed {wav_name}')
            continue
        rows.append(
            {
                'file': wav_name,
                'freesound_id': sid,
                'name': name,
                'username': r.get('username') or '',
                'license_url': (r.get('license') or '').strip(),
                'tier': r['_tier'],
                'license_id': r['_license_id'],
                'url': r.get('url') or f'https://freesound.org/s/{sid}/',
                'avg_rating': round(float(r.get('avg_rating') or 0), 3),
                'query': r['_query'],
                **m,
            }
        )
        print(f'  + {wav_name}  {m["duration_s"]}s  glide={m["glide"]}  slate={m["slate_suspect"]}')

    if not rows:
        print('nothing downloaded', file=sys.stderr)
        return 1

    # Final rank: CC0 first, then a real descending scream, then rating.
    rows.sort(key=lambda d: (d['tier'], not d['glide'], -d['avg_rating']))

    with open(SHORTLIST, 'w', encoding='utf-8') as f:
        json.dump([{k: v for k, v in d.items() if k != 'license_id'} for d in rows], f, indent=2)
    print(f'\nwrote {SHORTLIST} ({len(rows)} entries)')

    from zyg_workflows import asset_library_service as A

    for d in rows:
        ok = A.set_audio_meta(
            'sfx',
            d['file'],
            {
                'source': 'Freesound',
                'source_url': d['url'],
                'license_id': d['license_id'],
                'commercial_ok': True,
                'attribution_required': d['tier'] == 2,
                'attribution': f'{d["username"]} via freesound.org',
                'no_ai_training': False,
                'no_redistribute': False,
                'transform': 'model',
                'descriptor': d['name'],
                'pack_label': 'Freesound — birds of prey (CC0/BY)',
                'group': 'Birds of prey',
                'added_date': ADDED_DATE,
                'freesound_id': d['freesound_id'],
                'preview_only': True,
                'eula_note': (
                    '128 kbps MP3 preview (the original WAV needs OAuth2); '
                    'licence read per file from the API license field'
                ),
            },
        )
        if not ok:
            print(f'  ! set_audio_meta refused {d["file"]}', file=sys.stderr)

    print(f'\n{"file":42s} {"lic":8s} {"dur":>6s} {"peak":>7s} {"centroid":>9s} {"glide":>5s} {"slate":>5s}  who')
    for d in rows:
        print(
            f'{d["file"]:42s} {d["license_id"]:8s} {d["duration_s"]:6.2f} '
            f'{d["peak_db"]:7.2f} {d["centroid_hz"]:9.1f} {str(d["glide"]):>5s} '
            f'{str(d["slate_suspect"]):>5s}  {d["username"]}'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
