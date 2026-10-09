# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.state — audio path safety, audition clips and studio_state().

Moved verbatim from voice_studio.py lines 2908-3026 (2026-10-06 split).
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import re

from zyg_workflows.voice_studio.constants import (
    PRESET_ROOT,
    RENDER_ROOT,
    _CHATTERBOX_PY,
    _CHATTERBOX_WORKER,
    _INDEXTTS_PY,
    _INDEXTTS_WORKER,
    _SEED_DIR,
)
from zyg_workflows.voice_studio.policy import (
    voice,
)
from zyg_workflows.voice_studio.synthesis import (
    _gpu_usable,
)
from zyg_workflows.voice_studio.presets import (
    list_presets,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.voice_studio')


# ────────────────────────────────────────────────────────── audio path safety
# Three read-only roots, addressed as '<key>/<relpath>'. Anything else 404s.
AUDIO_ROOTS = {'run': RENDER_ROOT, 'pre': PRESET_ROOT, 'seed': _SEED_DIR}
# .mp3 rides alongside .wav because a bench row may carry an 'in context'
# clip -- a sung take inside its arrangement -- and re-encoding 26 MB of
# those to wav to satisfy a file extension would be the wrong trade. What
# keeps this safe is unchanged: the three named roots, the realpath prefix
# check and the '..' rejection below, none of which care about extension.
_AUDIO_REL_RE = re.compile(r'^(run|pre|seed)/[A-Za-z0-9._/-]{1,200}\.(wav|mp3)$')


def resolve_audio(rel: str) -> 'str|None':
    if not rel or not _AUDIO_REL_RE.match(rel) or '..' in rel:
        return None
    key, _, tail = rel.partition('/')
    root = os.path.realpath(AUDIO_ROOTS[key])
    full = os.path.realpath(os.path.join(root, tail))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    return full


def audio_rel(path: str) -> str:
    """`seed/<relpath>` for a file under the seed root, or '' if it is not there.

    studio_state built this inline for the seed and the identity reference; the
    library board needs the same string for the same files, and two copies of a
    path rule is how the two views end up disagreeing about which wav a voice
    auditions.
    """
    try:
        if not path or not os.path.isfile(path):
            return ''
        root = os.path.realpath(_SEED_DIR)
        full = os.path.realpath(path)
        if not full.startswith(root + os.sep):
            return ''
        return 'seed/' + os.path.relpath(full, root)
    except OSError:
        return ''


def audition_clips(v: dict) -> list:
    """Every clip a voice can be AUDITIONED from, without synthesising anything.

    The library board could only ever play a BAKED take -- a TTS render of a
    fixed line -- so the ten sung rows added 2026-09-06, which have no baked
    take and never will, had cards with no way to hear them at all. 293 of 303
    voices are baked, so this is a small gap in count and a total one for any
    voice the engine cannot render; and a baked take is in any case not the same
    artefact as the seed wav that DEFINES the voice, which sat on disk all along
    already served by /voice/audio. The seed comes first; a bench row may add
    its own extras (`extra_audio`), which is how a sung bench offers 'in the
    song' beside the isolated stem.

    Returns [{'label', 'rel'}] -- never raises, and silently drops a clip whose
    file has gone, because a missing extra must not cost the card its seed.
    """
    out = []
    rel = audio_rel((v or {}).get('seed', ''))
    if rel:
        out.append({'label': (v or {}).get('seed_label') or 'seed', 'rel': rel})
    for ex in (v or {}).get('extra_audio') or []:
        r = audio_rel(str((ex or {}).get('path') or ''))
        if r:
            out.append({'label': str((ex or {}).get('label') or 'clip'), 'rel': r})
    return out


def studio_state(vid: str) -> dict:
    """Everything the tab needs for one voice in a single call."""
    v = voice(vid)
    if not v:
        return {}
    meta = {}
    try:
        with open(v['meta_json'], encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError, KeyError) as _exc:
        _zyg_log.debug('voice meta for %s unreadable, the tab gets no metadata: %s', vid, _exc)
    st = list_presets(vid)
    seed_ok = os.path.isfile(v['seed'])
    return {
        'voice': {
            k: v[k]
            for k in (
                'id',
                'name',
                'role',
                'age_class',
                'default_text',
                'note',
                'test_lines',
                'vtl_caution_cm',
                'vtl_caution_note',
            )
        },
        'seed_present': seed_ok,
        # relpath, NOT basename: the pool seeds live in a subdirectory, and
        # basename would address seed/<name>.wav — a path that does not exist, so
        # the "hear the seed" button 404s on sixteen of the seventeen voices.
        # resolve_audio already walls this off to _SEED_DIR.
        'seed_audio': f'seed/{os.path.relpath(v["seed"], _SEED_DIR)}' if seed_ok else '',
        'identity_audio': (
            f'seed/{os.path.relpath(v["identity_ref"], _SEED_DIR)}'
            if v.get('identity_ref') and os.path.isfile(v['identity_ref'])
            else ''
        ),
        'seed_meta': meta,
        'presets': st['presets'],
        'active': st['active'],
        'engines': {
            'chatterbox': os.path.isfile(_CHATTERBOX_PY) and os.path.isfile(_CHATTERBOX_WORKER),
            'indextts2': os.path.isfile(_INDEXTTS_PY) and os.path.isfile(_INDEXTTS_WORKER),
        },
        'gpu': _gpu_usable(),
    }
