# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Put the singer's trained voice on a finished kids-music song (backfill).

Usage: python tools/vc_render_song.py <job_id>

New songs are converted inside kids_music_service.run(); this applies the SAME
step (kids_music_service.convert_voice, voice_conversion.ship_check) to a song
made before 2026-09-15. It converts the kept vocal stem (the unconverted one if
the song was converted before), re-mixes at the song's recorded balance, masters
through master_audio, re-muxes the video, and keeps master_unconverted.mp3 and
stems/vocals_unconverted.flac for A/B. A conversion that fails the per-song
check is recorded and NOT shipped — exactly as in a run.
"""

import json
import logging as _zyg_logging
import os
import shutil
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)
from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main(job):
    jd = os.path.join(CREWS, 'output/kidsmusic', job)
    man_path = os.path.join(jd, 'manifest.json')
    man = json.load(open(man_path))
    plan = json.load(open(os.path.join(jd, 'song.json')))
    voice = man.get('voice') or {}
    if (man.get('delivery') or {}).get('picked_leg') != 'produced':
        raise SystemExit('the shipped song is the score render — no voice to convert')
    stems = {k: os.path.join(jd, p) for k, p in K.STEM_FILES.items()}
    if not (os.path.isfile(stems['vocals']) and os.path.isfile(stems['backing'])):
        raise SystemExit('no stems on this song — it predates the voice leg')
    if not os.path.isfile(stems['vocals_unconverted']):
        shutil.copyfile(stems['vocals'], stems['vocals_unconverted'])
    if not os.path.isfile(os.path.join(jd, 'master_unconverted.mp3')):
        shutil.copyfile(os.path.join(jd, 'master.mp3'), os.path.join(jd, 'master_unconverted.mp3'))
    singer = T.SINGERS[plan['brief'].get('singer') or T.DEFAULT_SINGER]
    if not singer.get('vc_model'):
        raise SystemExit(f'singer {plan["brief"].get("singer")} has no trained voice (vc_model)')
    voice['_stems'] = {'vocals': stems['vocals_unconverted'], 'rest': stems['backing']}
    voice['reviewed'] = bool(voice.get('reviewed', True))
    take = os.path.join(jd, voice.get('take_file') or 'song.mp3')
    feed = K.convert_voice(voice, plan, singer, take, jd, log_fn=log)
    voice.pop('_stems', None)
    if feed:
        master, gate, _ = K.master_audio(feed, jd, plan, log_fn=log, dst_name='_vc_master.mp3')
        os.remove(feed)
        if not master:
            raise SystemExit('mastering failed')
        os.replace(master, os.path.join(jd, 'master.mp3'))
        remuxed = K.remux_video(jd, os.path.join(jd, 'master.mp3'), log_fn=log)
        man.setdefault('gates', {})['master'] = gate
        man.setdefault('files', {}).update(
            {
                'master_unconverted': 'master_unconverted.mp3',
                'stems_vocals_unconverted': K.STEM_FILES['vocals_unconverted'],
            }
        )
        log(
            f'master {gate.get("checks", {}).get("lufs")} LUFS key {gate.get("checks", {}).get("key_match")}; '
            f'video re-muxed: {remuxed}'
        )
    man['voice'] = voice
    with open(man_path + '.tmp', 'w') as fh:
        json.dump(man, fh, indent=1)
    os.replace(man_path + '.tmp', man_path)
    K._update_voice_report(jd, voice)
    shutil.rmtree(os.path.join(jd, '_vc'), ignore_errors=True)
    log(
        'done — '
        + ('converted voice shipped' if feed else 'NOT shipped: ' + '; '.join(voice['conversion'].get('reasons') or []))
    )


if __name__ == '__main__':
    main(sys.argv[1])
