# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_cast_voices.py — freeze audition benches of candidate CHARACTER voices.

Built 2026-08-21, operator: "make 10 variations of the cornelis main voice the
elder gravel" and "also make 10 variations for the kyutai roscoe voice", after
both sigh attempts were rejected and the call was made to settle the VOICE first.

WHAT THIS MAKES
---------------
Two benches of ten under data/assets/voice_seeds/benches/<bench>/, each candidate
a source voice reshaped with the Voices tab's own seed_k / seed_m and frozen, plus
a manifest and a per-candidate sidecar. voice_studio._load_bench_voices() picks
them up, so they arrive in the tab as VOICES with their knobs at defaults — the
shaping is already in the wav. Auditioning is a click, and tuning one further
starts from where it was left. Same shape as build_teen_voices.py, which is why
the loader was made generic rather than copied.

THE TWO KNOBS, AND WHY THE GRID LOOKS LIKE THIS
-----------------------------------------------
    seed_k  a RESAMPLE — moves pitch and vocal tract together. k<1 lowers F0 and
            GROWS the tract: a bigger, older body. It is also the knob that
            CARRIES roughness through, because a resample preserves every phase
            relationship in the glottal noise.
    seed_m  rubberband with formants preserved — moves pitch and leaves the body.
            It SMOOTHS: it is a phase-vocoder resynthesis, and it erases exactly
            the irregularity that reads as a worn voice.

So the spine of each bench is a k ladder (identical body-size steps, roughness
intact), and only three rows use m — to decouple pitch from body where the ladder
alone cannot reach: a large frame that is not a rumble (k down, m up), and a
tighter drier elder (k up, m down).

MEASURED BASELINES (voice_texture.py, this box)
-----------------------------------------------
    m03_elder_gravel   F0 98.1 Hz   wear  1.11   HNR 10.10   Maya1 synthetic
    Roscoe (kd_roscoe) F0 90.5 Hz   wear  5.68   HNR  5.05   CC0 human donor
    cornelis_broken    F0 79.2 Hz   wear  6.64   HNR  4.92   shipping today
    Jeff_Andrew        F0 88.7 Hz   wear  6.09   HNR  4.89   its donor

The two benches are deliberately NOT the same voice twice. Elder Gravel is clean
(wear 1.11) and Roscoe is weathered (5.68); no reshape can turn one into the
other, because EQ and resampling cannot manufacture jitter. That is the actual
choice on offer here — designed-clean against human-worn — and it is why both
were asked for. k=0.895 appears in both ladders on purpose: it is the reshape the
currently-shipping Cornelis uses, so each bench contains one direct comparison.

LICENCE / CONSENT — THE TWO FAMILIES DIFFER
-------------------------------------------
    maya1   Elder Gravel is wholly synthetic (Apache-2.0 generator) from a
            written description. No human was recorded; no consent or
            personality-rights exposure. Its unreshaped row is shippable.
    kyutai  Roscoe is CC0 AND consent-clean (donated to Kyutai's Unmute Voice
            Donation Project by someone who knew they were giving a voice to a
            speech model). It is still a REAL person's timbre. House practice —
            see cornelis_broken.json — is that a donor-derived seed is always
            RESHAPED before a character speaks with it, so an identifiable
            person is never put in a character's mouth. kr01 is therefore
            flagged reference_only: it is the anchor the ladder is judged
            against, and it must not ship.

    python3 build_cast_voices.py              # build both benches + render
    python3 build_cast_voices.py --no-render  # seeds and manifest only
    python3 build_cast_voices.py cornelis     # one bench
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from zyg_workflows import voice_studio as vs  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

BENCH_ROOT = os.path.join(_HERE, 'data', 'assets', 'voice_seeds', 'benches')

# The audition line. DEFAULT_LINES[0] is the Second Ledger cold open — canon, the
# register Cornelis actually speaks in, and the line every other figure in this
# codebase is measured on. Anything measured on a different line is not
# comparable: VTL comes from formant dispersion, so a vowel-heavy line reads a
# longer tract.
LINE = vs.DEFAULT_LINES[0]['text']

_MAYA_NOTE = (
    'Wholly synthetic: designed by Maya1 (Apache-2.0) from a written '
    'description, so no human was recorded and there is no consent or '
    'personality-rights exposure.'
)
_KYUTAI_NOTE = (
    'Source is a CC0 Kyutai voice donation — licence-clean AND '
    'consent-clean (the donor knew they were giving a voice to a '
    'speech model). It is a REAL human timbre: house practice is to '
    'reshape it before a character speaks with it.'
)

_UBI_DESIGNS = os.path.join(BENCH_ROOT, 'ubi', 'designs')
UBI_ROWS = [
    # id, k, m, display, why, source
    (
        'ub01',
        1.200,
        1.000,
        'Ubi — young light, shrunk (pure k)',
        'f06 young light resampled up 20 %: pitch and tract move together, nothing resynthesised. The clean anchor of the pool route.',
        'f06_young_light',
    ),
    (
        'ub02',
        1.250,
        1.200,
        'Ubi — young light, smaller and higher',
        'A step smaller from k, pitch lifted a little further with m. Should read as a small creature, not a girl.',
        'f06_young_light',
    ),
    (
        'ub03',
        1.300,
        1.400,
        'Ubi — young light, tiny and squeaky',
        'The far end of the f06 route: tract collapsed by m, body shrunk by k. Listen for the cloner re-pitching instead of following.',
        'f06_young_light',
    ),
    (
        'ub04',
        1.250,
        1.000,
        'Ubi — bright clear, shrunk (pure k)',
        'f02 bright soprano resampled up 25 %. Brighter consonants than f06; the articulate option.',
        'f02_bright_clear',
    ),
    (
        'ub05',
        1.300,
        1.250,
        'Ubi — bright clear, tiny',
        'f02 pushed to creature size with both knobs. The chirpiest pool row.',
        'f02_bright_clear',
    ),
    (
        'ub06',
        1.350,
        1.600,
        'Ubi — boyish, child transform taken further',
        'm06 young earnest through the Abel child recipe (k 1.167 / m 1.678) with more k: a BOY creature rather than a girl creature.',
        'm06_young_earnest',
    ),
    (
        'ub07',
        1.100,
        1.000,
        'Ubi — design 1 (squeaky mascot), a shade smaller',
        'Maya1 asked for a squeaky cartoon mascot outright; k 1.10 so it is not shippable as a bare adult if the design came back adult.',
        os.path.join(_UBI_DESIGNS, 'ubi_d1.wav'),
    ),
    (
        'ub08',
        1.200,
        1.200,
        'Ubi — design 2 (fluffy sidekick), small',
        'Maya1 fluffy-sidekick design shrunk to creature size.',
        os.path.join(_UBI_DESIGNS, 'ubi_d2.wav'),
    ),
    (
        'ub09',
        1.150,
        1.100,
        'Ubi — design 3 (elfin), small',
        'Maya1 elfin giggly design, lightly shrunk.',
        os.path.join(_UBI_DESIGNS, 'ubi_d3.wav'),
    ),
    (
        'ub10',
        1.250,
        1.300,
        'Ubi — design 4 (cheeky boy), tiny',
        'Maya1 cheeky nasal boy design pushed to creature size. The most processed design row.',
        os.path.join(_UBI_DESIGNS, 'ubi_d4.wav'),
    ),
]

# id, k, m, display, what the row is FOR.
BENCHES = {
    'cornelis': {
        'source': 'm03_elder_gravel',
        'family': 'maya1',
        'label': 'Cornelis — Elder Gravel ladder',
        'note': _MAYA_NOTE,
        'rows': [
            (
                'cg01',
                1.000,
                1.000,
                'Elder Gravel — as designed',
                'The untouched source. The anchor every other row is judged against.',
            ),
            (
                'cg02',
                0.960,
                1.000,
                'Elder Gravel — a shade heavier',
                'Smallest step that is audible at all; use it to calibrate your ear to the ladder.',
            ),
            (
                'cg03',
                0.925,
                1.000,
                'Elder Gravel — heavier',
                'Noticeably older and larger without leaving his register.',
            ),
            (
                'cg04',
                0.895,
                1.000,
                'Elder Gravel — at the shipping reshape',
                'k=0.895 is exactly what the current Cornelis uses on its donor. Direct comparison row.',
            ),
            (
                'cg05',
                0.865,
                1.000,
                'Elder Gravel — deep',
                'Where the ladder starts sounding like a big man rather than an old one.',
            ),
            (
                'cg06',
                0.835,
                1.000,
                'Elder Gravel — deeper',
                'Chest and slow. Watch for the resample starting to smear consonants.',
            ),
            (
                'cg07',
                0.800,
                1.000,
                'Elder Gravel — deepest',
                'The end of the useful ladder; included so the limit is heard, not guessed.',
            ),
            (
                'cg08',
                0.925,
                0.950,
                'Elder Gravel — heavy body, pitch dropped further',
                'k sets a larger frame, m takes the pitch down again without shrinking it.',
            ),
            (
                'cg09',
                0.865,
                1.050,
                'Elder Gravel — large frame, pitch back up',
                'A big man who is not a rumble: body from k, pitch recovered with m.',
            ),
            (
                'cg10',
                1.040,
                0.930,
                'Elder Gravel — tighter and drier',
                'The other direction: a smaller tract from k, pitch pulled down by m.',
            ),
        ],
    },
    # ── ROUND 2 ──────────────────────────────────────────────────────────
    # Operator picked cg08 out of round 1: "Elder Gravel, heavy body, pitch
    # dropped further" (k=0.925, m=0.950). Round 1 was a WIDE ladder whose job
    # was to find the region; this is a FINE grid whose job is to find the point,
    # so the steps are ~0.02 instead of ~0.035 and they move in both knobs.
    #
    # Seven rows are a 3x3 around the pick (k 0.905/0.925/0.945 x m 0.930/0.950/
    # 0.970) plus one step further in the direction the operator moved. The other
    # two rows test a DIFFERENT ROUTE TO THE SAME PLACE, which is the part worth
    # explaining: cg08 arrives at render F0 87.9 Hz using m to pull the pitch
    # down after k set the body, and m is a phase-vocoder resynthesis that SMOOTHS
    # — it spends roughness to buy pitch. Pure k lands on the same pitch without
    # that cost (round 1 measured k=0.865 -> 89.6 Hz and k=0.835 -> 85.8 Hz, so
    # k~0.850 brackets 87.9). eg09 is that pure-k route and eg10 is halfway
    # between the two. If eg09 sounds better than eg01 at the same pitch, the m in
    # the pick was costing texture for nothing; if it sounds worse, the smoothing
    # is part of what was liked. Either answer is worth one row.
    #
    # Everything stays above k=0.84: round 1 measured the ladder saturating there
    # and INVERTING below it, on both benches independently.
    'cornelis_r2': {
        'source': 'm03_elder_gravel',
        'family': 'maya1',
        'label': 'Cornelis round 2 — around the cg08 pick',
        'note': _MAYA_NOTE,
        'rows': [
            (
                'eg01',
                0.925,
                0.950,
                'R2 — the pick, unchanged',
                'cg08 exactly. The anchor; every other row is a step away from it.',
            ),
            (
                'eg02',
                0.905,
                0.950,
                'R2 — heavier body',
                'Same pitch treatment, larger frame. Is the body the thing you liked?',
            ),
            (
                'eg03',
                0.945,
                0.950,
                'R2 — lighter body',
                'The other side of the body step, in case the pick is already too large.',
            ),
            (
                'eg04',
                0.925,
                0.930,
                'R2 — pitch dropped further',
                'Straight more-of-what-you-picked: same frame, lower still.',
            ),
            (
                'eg05',
                0.925,
                0.970,
                'R2 — pitch eased back',
                'Same frame, less pitch drop — the row that says whether m went too far.',
            ),
            (
                'eg06',
                0.905,
                0.930,
                'R2 — heavier and lower',
                'Both knobs one step further in. The corner of the grid you moved toward.',
            ),
            (
                'eg07',
                0.945,
                0.970,
                'R2 — lighter and higher',
                'The opposite corner. Included so the grid has a floor as well as a ceiling.',
            ),
            (
                'eg08',
                0.885,
                0.940,
                'R2 — a step beyond the pick',
                'Past the grid in the direction you moved, to check the region does not keep improving.',
            ),
            (
                'eg09',
                0.850,
                1.000,
                'R2 — same pitch, PURE k (no smoothing)',
                'Lands near 87.9 Hz on k alone. No phase vocoder, so the source texture is kept intact — the direct test of what the m in cg08 costs.',
            ),
            (
                'eg10',
                0.870,
                0.975,
                'R2 — halfway to the pure-k route',
                'Between eg01 and eg09: most of the pitch from k, a little from m.',
            ),
        ],
    },
    # ── UBI, the Pufferball (portfolio video spokes-creature, 2026-10-03) ─────
    # Operator: "generate 10 voices for ubi so i can choose one". Ubi is a
    # fist-sized ball of fluff, so the target is SMALLER than a child: tract
    # well under the 12.3 cm Abel's child seed measured, pitch 250-450 Hz. Two
    # routes, because neither alone was trusted:
    #   designs  Maya1 asked for a creature outright (ubi_d1-d4 under
    #            benches/ubi/designs/, descriptions in the .txt beside each).
    #            Maya1 cannot design a child (2026-08-06, all 11 Abel candidates
    #            came back adult), so each design is ALSO pushed up with k.
    #   pool     the lightest pool voices (f06 young light, f02 bright clear,
    #            m06 young earnest) shrunk with k > 1 and lifted with m > 1 —
    #            the Abel child transform (k 1.167 / m 1.678) taken further.
    #            m > 1 collapses the tract (teen bench finding) and for a tiny
    #            creature that is the point, not a defect.
    # Rows are measured on Ubi's OWN line, not the ledger cold open: a vowel-
    # heavy register reads a different tract, and he will never speak canon.
    'ubi': {
        'source': 'f06_young_light',
        'family': 'maya1',
        'gender': 'f',
        'age_class': 'creature',
        'label': 'Ubi — the Pufferball, creature ladder',
        'note': _MAYA_NOTE,
        # IndexTTS-2, not Chatterbox: the Chatterbox venv was deleted in the
        # 2026-10-02 disk sweep and IndexTTS-2 has been the house primary since
        # 2026-08-06 anyway. It preserves tract size exactly (Abel: 12.26 ->
        # 12.26 cm), which is what a creature seed needs.
        'engine': 'indextts2',
        'measured_on': 'Ubi line S01 (portfolio), indextts2 defaults, seed 1672',
        'lines': [
            {
                'id': 'ubi_open',
                'label': 'Ubi — let me explain',
                'text': (
                    'Hey! Let me, let me! I want to explain! Of course, this is '
                    'peanuts, I can do it. Hi! My name is Ubi.'
                ),
            },
            {
                'id': 'ubi_agenda',
                'label': 'Ubi — the agenda',
                'text': (
                    'Today we are going to explain AI assistants, workflows, the '
                    'approval queue, the content creation hub, the session tree, '
                    'and the multiple studios that are listed on screen right now.'
                ),
            },
            {
                'id': 'ubi_close',
                'label': 'Ubi — the close',
                'text': (
                    'Those were our closing statements, and this was our portfolio. '
                    'His name is Levi Harley, and in all humbleness, we thank you '
                    'for your time.'
                ),
            },
        ],
        'rows': UBI_ROWS,
    },
    'roscoe': {
        'source': 'kd_roscoe',
        'family': 'kyutai',
        'label': 'Roscoe — CC0 donor ladder',
        'note': _KYUTAI_NOTE,
        'rows': [
            (
                'kr01',
                1.000,
                1.000,
                'Roscoe — unreshaped donor',
                'REFERENCE ONLY. The donor as recorded, so the ladder has an anchor. Not for shipping.',
            ),
            (
                'kr02',
                0.965,
                1.000,
                'Roscoe — a shade heavier',
                'The lightest reshape that is both audible and house-practice compliant.',
            ),
            ('kr03', 0.930, 1.000, 'Roscoe — heavier', 'Older and larger; the donor roughness rides through intact.'),
            (
                'kr04',
                0.895,
                1.000,
                'Roscoe — at the shipping reshape',
                'Same k the current Cornelis uses, on a different donor. Direct comparison row.',
            ),
            ('kr05', 0.865, 1.000, 'Roscoe — deep', 'Roughest useful region: weathered and large at once.'),
            ('kr06', 0.835, 1.000, 'Roscoe — deeper', 'Chest-heavy. Listen for the roughness turning into buzz.'),
            ('kr07', 0.805, 1.000, 'Roscoe — deepest', 'End of the ladder, included so the limit is heard.'),
            (
                'kr08',
                0.930,
                0.950,
                'Roscoe — heavy body, pitch dropped further',
                'm smooths, so this is the row where roughness starts being spent for pitch.',
            ),
            (
                'kr09',
                0.865,
                1.050,
                'Roscoe — large frame, pitch back up',
                'Big body, pitch recovered — the least rumbly way to get size from this donor.',
            ),
            (
                'kr10',
                1.040,
                0.930,
                'Roscoe — tighter and drier',
                'Smaller tract, pitch pulled down by m. The most processed row in the bench.',
            ),
        ],
    },
}


def _source(src: str) -> dict:
    """A registered pool/bench voice id, or a bare wav path (a bench-local design
    that is not in the pool — the Ubi creature designs live beside their bench)."""
    v = vs.voice(src)
    if v:
        return v
    if os.path.isfile(src) and src.lower().endswith('.wav'):
        return {
            'id': os.path.splitext(os.path.basename(src))[0],
            'name': os.path.splitext(os.path.basename(src))[0],
            'seed': src,
        }
    return {}


def freeze(src_vid: str, k: float, m: float, out_wav: str) -> str:
    """Apply the studio's own seed transform and write the frozen seed."""
    v = _source(src_vid)
    if not v:
        raise SystemExit(f'unknown source voice {src_vid!r}')
    p = vs.defaults()
    p['seed_k'], p['seed_m'] = float(k), float(m)
    chain = vs.seed_chain(p)
    if vs._apply(v['seed'], out_wav, chain, vs._SEED_SR) is None:
        raise SystemExit(f'ffmpeg failed shaping {src_vid} k={k} m={m}')
    return out_wav


def _texture(wav: str) -> dict:
    """voice_texture's four Praat measures + `wear` for one file, or {}.

    measure() takes a LIST and returns one row per path; wear is derived, not
    returned, so it is computed here. Never raises: a missing Praat venv must
    leave the bench buildable with the age figures alone.
    """
    if not os.path.isfile(wav):
        return {}
    try:
        from zyg_workflows import voice_texture

        rows = voice_texture.measure([wav])
        row = rows[0] if rows else {}
        if not row.get('ok'):
            return {}
        out = {k: round(float(row[k]), 3) for k in ('hnr', 'jitter', 'shimmer', 'cpps') if row.get(k) is not None}
        if len(out) == 4:
            out['wear'] = round(float(voice_texture.wear(row)), 2)
        for k in ('f0', 'floor_db', 'voiced_frames'):
            if row.get(k) is not None:
                out[k] = row[k]
        return out
    except Exception as exc:
        _zyg_log.info(f'  [texture] {os.path.basename(wav)}: {exc}')
        return {}


def build(bench: str, render: bool = True) -> list:
    spec = BENCHES[bench]
    dest = os.path.join(BENCH_ROOT, bench)
    os.makedirs(dest, exist_ok=True)
    src = _source(spec['source'])
    if not src:
        raise SystemExit(f'source voice {spec["source"]!r} is not registered')
    line = (spec.get('lines') or [{'text': LINE}])[0]['text']
    rows = []
    for row_spec in spec['rows']:
        vid, k, m, display, why = row_spec[:5]
        row_src_id = row_spec[5] if len(row_spec) > 5 else spec['source']
        src = _source(row_src_id)
        if not src:
            raise SystemExit(f'source voice {row_src_id!r} is not registered')
        out_wav = os.path.join(dest, vid + '.wav')
        freeze(row_src_id, k, m, out_wav)
        seed_q = vs.measure(out_wav)
        seed_t = _texture(out_wav)

        # RENDER, then measure the render. The seed and the render disagree —
        # the engine re-synthesises — and only the render is what a listener
        # hears, so the manifest ranks on render figures.
        render_wav = os.path.join(dest, vid + '_audition.wav')
        r_q, r_t = {}, {}
        if render and not os.path.isfile(render_wav):
            p = vs.defaults()
            p['eng_seed'] = 1672
            p['engine'] = spec.get('engine', p['engine'])
            if vs.synth(line, out_wav, render_wav, p, print) is None:
                _zyg_log.info(f'  {vid}: RENDER FAILED')
        if os.path.isfile(render_wav):
            r_q, r_t = vs.measure(render_wav), _texture(render_wav)

        row = {
            'name': vid,
            'display': display,
            'role': why,
            'wav': out_wav,
            'audition_wav': render_wav if os.path.isfile(render_wav) else '',
            'gender': spec.get('gender', 'm'),
            'age_class': spec.get('age_class', 'adult_male'),
            'bench': bench,
            'family': spec['family'],
            'source_voice': row_src_id,
            'source_display': src.get('name', ''),
            'source_wav': src.get('seed', ''),
            'seed_k': round(float(k), 3),
            'seed_m': round(float(m), 3),
            'seed_f0_hz': seed_q.get('f0_hz'),
            'seed_vtl_cm': seed_q.get('vtl_cm'),
            'seed_wear': seed_t.get('wear'),
            'render_f0_hz': r_q.get('f0_hz'),
            'render_vtl_cm': r_q.get('vtl_cm'),
            'render_wear': r_t.get('wear'),
            'render_hnr_db': r_t.get('hnr'),
            'render_jitter_pct': r_t.get('jitter'),
            'measured_on': (
                spec.get('measured_on') or 'DEFAULT_LINES[0] (Second Ledger cold open), chatterbox defaults, seed 1672'
            ),
            # Only the unreshaped human donor is barred; the synthetic source is
            # shippable as designed.
            # The measurement render doubles as an instant audition clip in the
            # tab (the loader's generic `extras`), so a candidate is hearable
            # even before the take cache is baked.
            'extras': (
                [
                    {
                        'label': 'audition — '
                        + (spec.get('lines') or [{'label': 'cold open'}])[0].get('label', 'line'),
                        'path': render_wav,
                    }
                ]
                if os.path.isfile(render_wav)
                else []
            ),
            'reference_only': bool(spec['family'] == 'kyutai' and abs(k - 1.0) < 1e-6 and abs(m - 1.0) < 1e-6),
            'note': spec['note'],
        }
        rows.append(row)
        with open(os.path.splitext(out_wav)[0] + '.json', 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'candidate': display,
                    'why_this_row': why,
                    'bench': bench,
                    'built': '2026-08-21 by build_cast_voices.py',
                    'source_voice': row_src_id,
                    'source_wav': src.get('seed', ''),
                    'source_family': spec['family'],
                    'transform': {
                        'k': row['seed_k'],
                        'm': row['seed_m'],
                        'ffmpeg': (
                            f'asetrate/atempo k={row["seed_k"]:.3f}'
                            + (
                                f' + rubberband pitch={row["seed_m"]:.3f} formant=preserved'
                                if abs(m - 1.0) > 1e-6
                                else ''
                            )
                        ),
                        'note': (
                            'k is a RESAMPLE: it moves pitch and tract together '
                            'and carries glottal roughness through untouched. '
                            'm is a phase-vocoder resynthesis: it moves pitch '
                            'only and SMOOTHS, so it spends roughness to buy '
                            'pitch. On a worn voice, prefer k.'
                        ),
                    },
                    'seed_measured': {
                        'f0_median_hz': seed_q.get('f0_hz'),
                        'vtl_cm': seed_q.get('vtl_cm'),
                        'texture': seed_t,
                    },
                    'render_measured': {
                        'f0_median_hz': r_q.get('f0_hz'),
                        'vtl_cm': r_q.get('vtl_cm'),
                        'texture': r_t,
                        'line': 'Second Ledger cold open',
                        'engine': 'chatterbox, defaults, eng_seed 1672',
                    },
                    'reference_only': row['reference_only'],
                    'wholly_synthetic': spec['family'] == 'maya1',
                    'note': spec['note'],
                    'caution': (
                        'voice_qc VTL is not trustworthy on heavily worn '
                        'voices — formant dispersion needs stable formants, '
                        'and at HNR ~3 dB / jitter ~7 % there are none. Rank '
                        'on wear and F0, not on tract.'
                    ),
                },
                f,
                indent=1,
                ensure_ascii=False,
            )
        _zyg_log.info(
            f'{vid}  k={k:.3f} m={m:.3f}  seed {seed_q.get("f0_hz")} Hz '
            f'/ wear {seed_t.get("wear")}  ->  render {r_q.get("f0_hz")} Hz '
            f'/ wear {r_t.get("wear")} / HNR {r_t.get("hnr")}'
        )

    # THE LADDER SATURATES, AND THEN IT INVERTS. Both benches showed it
    # independently and at the same place: the k rungs track down to ~0.835 and
    # the bottom rung does not follow — cg07 (k=0.800) rendered 92.7 Hz after
    # cg06 had reached 85.8, and kr07 (k=0.805) rendered 119.3 Hz after kr06's
    # 84.9. A resample that deep leaves the seed too smeared for the cloner to
    # track, and the engine re-pitches instead of following. Flag any rung whose
    # render moves the WRONG WAY against the previous one, so an operator hearing
    # an oddly high take knows it is the rig's limit and not a taste question.
    ladder = [r for r in rows if abs(r['seed_m'] - 1.0) < 1e-6]
    ladder.sort(key=lambda r: -r['seed_k'])
    for prev, cur in zip(ladder, ladder[1:]):
        a, b = prev.get('render_f0_hz'), cur.get('render_f0_hz')
        if a is None or b is None:
            continue
        if b > a + 1.0:  # k went DOWN, pitch should not go UP
            cur['ladder_warning'] = (
                f'BROKEN RUNG — k {cur["seed_k"]:.3f} rendered {b:.1f} Hz, '
                f'ABOVE the {a:.1f} Hz of the shallower k {prev["seed_k"]:.3f}. '
                f'The resample is too deep for the cloner to track and the '
                f'engine re-pitched. Treat as the floor of the ladder, not as a '
                f'candidate.'
            )
            _zyg_log.info(f'  ! {cur["name"]}: {cur["ladder_warning"]}')

    # MERGE, never replace — rebuilding one candidate must not unregister the
    # rest (the teen builder learned this the expensive way: the wavs stay on
    # disk, so nothing looks broken until an operator goes to play a voice that
    # was already picked and finds it gone).
    manifest = os.path.join(dest, 'manifest.json')
    prior = []
    try:
        with open(manifest, encoding='utf-8') as f:
            prior = (json.load(f) or {}).get('voices') or []
    except (OSError, ValueError):
        prior = []
    fresh = {r['name'] for r in rows}
    kept = [r for r in prior if r.get('name') not in fresh and os.path.isfile(r.get('wav', ''))]
    rows = sorted(kept + rows, key=lambda r: r['name'])
    with open(manifest, 'w', encoding='utf-8') as f:
        json.dump(
            {
                'purpose': f'candidate voices for audition in the Voices tab — {spec["label"]}',
                'bench': bench,
                'built': '2026-08-21',
                'source_voice': spec['source'],
                'measured_on': spec.get('measured_on') or 'DEFAULT_LINES[0], chatterbox at defaults, eng_seed 1672',
                'test_lines': spec.get('lines'),
                'how_to_read': (
                    'The spine is a seed_k ladder — identical body-size '
                    'steps with the source roughness intact. Rows using '
                    'seed_m decouple pitch from body and cost roughness '
                    'to do it. Rank on render wear and render F0; VTL is '
                    'unreliable on worn voices.'
                ),
                'voices': rows,
            },
            f,
            indent=1,
            ensure_ascii=False,
        )
    _zyg_log.info(f'\nmanifest: {manifest}  ({len(rows)} voices)')
    return rows


def bake(bench: str) -> int:
    """Fill the Voices tab's OWN take cache for this bench, so clicking a
    candidate plays instantly instead of queueing an ~11 s render.

    The audition wavs `build()` writes are for MEASUREMENT — they live beside
    the seeds and the tab has never heard of them. What the player reads is the
    finished-take cache, keyed on (voice, text, every parameter). So the bake
    goes through voice_studio's own `_bake_batch`, at `defaults()`, which is
    exactly what vsPickVoice loads when a voice is clicked; anything else would
    be a cache that lies precisely where it is hardest to notice.

    Batched per voice on purpose: a fresh Chatterbox process spends most of its
    life importing torch and loading weights, so one invocation per VOICE rather
    than per TAKE is ~2x. Already-cached lines are skipped, so this is
    idempotent and a re-run after adding a candidate costs only that candidate.
    """
    # RE-REGISTER FIRST. voice_studio builds VOICES once, at import — so in a
    # run that BUILDS a bench and then bakes it, the manifest was written after
    # the registry was already populated and every candidate looks unknown. The
    # first cornelis_r2 run hit exactly this: it wrote 10 seeds, then reported
    # "0 new takes across 10 voices" and exited 0. A bake that silently does
    # nothing is worse than one that fails, because the bench looks delivered.
    vs.VOICES.update(vs._load_bench_voices())

    rows = BENCHES[bench]['rows']
    p = vs.defaults()
    p['eng_seed'] = 1672
    p['engine'] = BENCHES[bench].get('engine', p['engine'])
    total = made = 0
    failed: list = []
    for vid, *_rest in rows:
        v = vs.voice(vid)
        if not v:
            _zyg_log.info(f'  {vid}: not registered — build the bench first')
            continue
        lines = vs.bake_lines(vid)
        todo = [ln for ln in lines if not vs.take_has(vid, ln['text'], p)]
        total += len(lines)
        if not todo:
            _zyg_log.info(f'  {vid}: all {len(lines)} lines already cached')
            continue
        ok = vs._bake_batch(vid, v, todo, p)
        made += ok
        # _bake_batch swallows its own exceptions into the bake log (one bad
        # voice must not end a multi-hour library bake), so from here a total
        # failure and a success look identical apart from this count. Say it
        # plainly — the first cornelis_r2 bake lost four voices to VRAM still
        # held by a scene render that had just finished, and "baked 0/5" scrolled
        # past as if it were fine.
        note = ''
        if ok < len(todo):
            note = f'  <-- {len(todo) - ok} FAILED (engine or VRAM; re-run to retry)'
            failed.append(vid)
        _zyg_log.info(f'  {vid}: baked {ok}/{len(todo)} ({len(lines) - len(todo)} already cached){note}')
    if total == 0:
        raise SystemExit(
            f'bake: NOTHING to do for {bench!r} — none of its {len(rows)} '
            f'candidates are registered. The seeds and manifest may exist while '
            f'the registry does not know them; this must never pass silently.'
        )
    # Re-check from the CACHE rather than trusting the counters: that is the
    # thing the tab actually reads, and it is what "is this bench playable"
    # means.
    missing = [
        (vid, ln['id'])
        for vid, *_r in rows
        if vs.voice(vid)
        for ln in vs.bake_lines(vid)
        if not vs.take_has(vid, ln['text'], p)
    ]
    _zyg_log.info(f'bake: {made} new takes, {total} lines across {len(rows)} voices')
    if missing:
        _zyg_log.info(
            f'bake: {len(missing)} take(s) STILL MISSING across '
            f'{len(set(v for v, _ in missing))} voice(s) — those candidates will '
            f'not play instantly. Re-run to retry (cached takes are skipped). '
            f'{missing[:6]}{"..." if len(missing) > 6 else ""}'
        )
    else:
        _zyg_log.info(f'bake: all {total} takes present — every candidate plays on click')
    return made


if __name__ == '__main__':  # the CLI lives in build_cast_voices_cli
    from zyg_workflows.build_cast_voices_cli import main as _cli_main

    raise SystemExit(_cli_main())
