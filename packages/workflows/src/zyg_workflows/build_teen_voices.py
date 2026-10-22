# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_teen_voices.py — freeze a bench of candidate teenage-male voices.

WHAT THIS MAKES
---------------
Ten seeds under data/assets/voice_seeds/teens/, each one a source voice reshaped
with the Voices tab's own seed_k / seed_m and frozen, plus a manifest and a
per-seed provenance sidecar. voice_studio._load_teen_voices() registers them, so
they arrive in the tab as VOICES with their knobs at defaults — the shaping is
already in the wav, exactly the way abel_narrator_seed.wav carries its k=1.00 /
m=1.45. Auditioning a candidate is then a click, not two numbers to retype, and
tuning one further starts from where it was left.

WHY NOT FROM THE ADULT-MALE POOL
--------------------------------
Because it does not work, and the measurements that say so are worth keeping.
Both knobs trade pitch against body, at different ratios (which is the only
reason the pair spans the plane at all). Measured here on the cold-open line:

    seed_k  1.00 -> 1.08     F0 156.4 -> 161.1 Hz    VTL 16.79 -> 15.63 cm
    seed_m  1.00 -> 0.90     F0 161.1 -> 149.2 Hz    VTL 15.63 -> 16.66 cm
    seed_m  1.10 -> 1.36     F0 175.5 -> 203.6 Hz    VTL 14.12 -> 12.93 cm

So m BELOW 1.0 lowers pitch and GROWS the tract (+1.35 cm on the seed at 0.90 —
rubberband's formant preservation over-corrects downward on this ffmpeg build,
where the module's earlier note recorded it merely holding). m ABOVE 1.0 drags
the formants up with the pitch and collapses the tract: the third row is an
eight-year-old, not a teenager.

A boy mid-voice-change is NOT a shrunken man. His pitch is already at adult
female (150-180 Hz); his tract is between the two adult sizes (~15-16 cm against
14.44 female / 17.30 male measured on this box). Reaching that from a 90 Hz /
17.3 cm adult male would need pitch up AND body down by a lot, i.e. large m,
which destroys the tract. All eight Maya1 male seeds sit at 88-107 Hz and none
can reach the band at a defensible tract. The route is the other way: start from
a LIGHT voice, use k to set the body, and put the pitch back with m<1.

TARGETS
-------
Anchored on the male voice-change literature — Cooksey's speaking-F0 stages
(unchanged 264 Hz, midvoice I 233, midvoice II 214, midvoice IIA 183, newvoice
146, emerging adult ~123) — pulled to what this rig can deliver with a tract that
does not read female. The top of the practical window is ~176 Hz: above that the
tract cannot be held over 15 cm, which is why there is no 214 Hz candidate here.
Every figure below is a RENDER measurement on the cold-open line, never a seed
measurement — the engine re-synthesises and the two disagree (Abel: seed
14.64 cm, render 15.94).

LICENCE / CONSENT
-----------------
Two families, kept visibly apart because they carry different exposure:
  maya1  — wholly synthetic (Apache-2.0 generator), no human recorded, no
           personality rights in play at all.
  kyutai — CC0 AND donated by volunteers who knew they were giving a voice to a
           speech model. A real human's timbre, heavily reshaped; keep it out of
           anything that would put words in an identifiable person's mouth.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from zyg_workflows import voice_studio as vs  # noqa: E402

DEST = os.path.join(_HERE, 'data', 'assets', 'voice_seeds', 'teens')
MANIFEST = os.path.join(DEST, 'manifest.json')

# The audition line every figure in here was measured on. Anything measured on a
# different line is not comparable: VTL comes from formant dispersion, so a
# vowel-heavy line reads a LONGER tract (the same three voices measured 1.9-2.8 cm
# larger on the long-vowel line than on this one).
LINE = vs.DEFAULT_LINES[0]['text']

# id, source voice, display, role/anchor, k, m, family — filled from the tuning
# run (tune_teens.py), which drove the live studio and measured every render.
DESIGN: list = []

_MAYA_NOTE = (
    'Wholly synthetic: the source was designed by Maya1 (Apache-2.0) '
    'from a written description, so no human was recorded and there is '
    'no consent or personality-rights exposure. Reshaped from a light '
    'source rather than built up from an adult male — see '
    'build_teen_voices.py for why that direction is the only one that '
    'works.'
)
_KYUTAI_NOTE = (
    'Source is a CC0 Kyutai voice donation — licence-clean AND '
    'consent-clean (the donor knew they were giving a voice to a '
    'speech model), which a permissive licence alone does not give. '
    'It is a REAL human timbre, heavily reshaped: keep it out of '
    "anything that would put words in an identifiable person's "
    'mouth.'
)


def freeze(src_vid: str, k: float, m: float, out_wav: str) -> str:
    """Apply the studio's own seed transform and write the frozen seed."""
    v = vs.voice(src_vid)
    if not v:
        raise SystemExit(f'unknown source voice {src_vid!r}')
    p = vs.defaults()
    p['seed_k'], p['seed_m'] = float(k), float(m)
    chain = vs.seed_chain(p)
    if vs._apply(v['seed'], out_wav, chain, vs._SEED_SR) is None:
        raise SystemExit(f'ffmpeg failed shaping {src_vid} k={k} m={m}')
    return out_wav


if __name__ == '__main__':  # the CLI lives in build_teen_voices_cli
    from zyg_workflows.build_teen_voices_cli import cli_main as _cli_main

    raise SystemExit(_cli_main())
