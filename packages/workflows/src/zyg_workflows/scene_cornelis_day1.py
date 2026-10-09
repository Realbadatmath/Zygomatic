# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Second Ledger — Cornelis, Day 1.

The second scene in the series, and the first told by the father: the scenes
Abel is not in and does not know about. Same workflow as the Abel cold open
(`storyteller_scene_service.build_scene`), same cabin — but not the same sea:
since 2026-08-25 this scene opens on screams and a candle, with no water at all.

Shape (2026-08-25 opening):
    black; screams rise out of the dark over 3 s and hold for 3 → the candle
    on his table is the only thing in the frame until, at 3 s, its light
    spreads across the cabin over 5 s and finds Cornelis at the table with his
    pipe → the screams recede to a murmur and, on that murmur, he speaks →
    DAY 1 → the series chart fades in, the camera pushes into the West African
    coast, and the Day 1 course draws itself down the coast as a rope while he
    names it. No sea: the waves and gulls that used to open the scene are gone.

THIS FILE IS THE CUT, not a scratch driver. The Abel cut's driver lived only in
a session scratchpad under /tmp and was lost when it was cleared, which cost the
ability to rebuild the shipping version — see [[project-storyteller-scene-service]].

    python3 scene_cornelis_day1.py [out_dir]
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zyg_workflows import maritime_map_service as mms  # noqa: E402
from zyg_workflows import storyteller_scene_service as sss  # noqa: E402

CORNELIS = sss.CORNELIS

# His frozen voice seed. Absolute, because _resolve_voice_ref only searches the
# shared pool directory by bare name and this one is cast-specific.
_CORNELIS_SEED = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'data', 'assets', 'voice_seeds', 'cast', 'cornelis_elder_gravel.wav'
)

# ── the chart move, authored in longitude/latitude ──────────────────────────
# The camera is aimed at COORDINATES, not at eyeballed fractions of a plate.
# That is the dividend of drawing the map instead of generating it: "hold Texel
# and Loango in frame together" is a solvable statement, and it stays solved if
# the chart is ever redrawn at another size.
_CHART = mms.get_chart(log_fn=lambda m: None)


_PATH, _MARKS = mms.route_path(mms.WEST_AFRICA_RUN, _CHART)


def _norm(lon, lat):
    return _CHART.lonlat_to_norm(lon, lat)


# ── the camera follows the rope ─────────────────────────────────────────────
# The first cut of this move held one fixed "corridor" framing that was supposed
# to contain the whole voyage at once. It cannot: Texel to Loango is 1008 px of
# a 3072 px plate, so holding both caps the push at z≈2.6 — and at that width the
# rope is a thread across a mostly empty ocean, with the drawn half sliding off
# the top of frame as the head runs south. Measured on the test frames: at the
# midpoint of the draw the entire revealed rope was out of shot.
#
# So the framing TRACKS the head instead. The reveal is a known function of time
# (a smoothstep over the draw window), so where the head will be at any instant
# is computable rather than guessable, and the keys below are derived from the
# path rather than typed. The coast then gets its moment port by port, which is
# also the better shot.
_TAIL_S = 16.5  # tail_fade_in_s + tail_hold_s
_DRAW0, _DRAW1 = 7.4, 13.6  # the rope's window, in tail seconds


def _head_norm(u: float, z: float, lead: float = 0.055):
    """Where to point the camera when the rope is `u` of the way along.

    The head sits ABOVE centre by a fraction of the current window height, so
    the frame shows the water the course is about to run into rather than the
    coast it has just left — a reveal framed on what it has already revealed
    reads as lagging.
    """
    i = int(round(max(0.0, min(1.0, u)) * (len(_PATH) - 1)))
    x, y = _PATH[i]
    return (x / _CHART.width, (y + lead * (_CHART.height / z)) / _CHART.height)


def _at_frac(t_s: float) -> float:
    return t_s / _TAIL_S


def _reveal_at(t_s: float) -> float:
    """The same eased reveal the service will run, so the camera and the rope
    cannot disagree about where the head is."""
    x = (t_s - _DRAW0) / (_DRAW1 - _DRAW0)
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _chart_keys():
    keys = [
        # establish the world — it has to read as a world map before it reads
        # as a route
        {'at': 0.000, 'z': 1.04, 'focus': (0.500, 0.430)},
        {'at': 0.182, 'z': 1.16, 'focus': (0.496, 0.415)},
    ]
    # the push into the coast, arriving just before the line starts
    z_in = 2.30
    keys.append({'at': _at_frac(6.6), 'z': z_in, 'focus': _head_norm(0.0, z_in)})
    # then travel with the head while it draws, easing tighter as it goes
    for t_s, z in ((_DRAW0, 2.34), (9.0, 2.46), (10.6, 2.62), (12.2, 2.82), (_DRAW1, 3.05)):
        keys.append({'at': _at_frac(t_s), 'z': z, 'focus': _head_norm(_reveal_at(t_s), z)})
    # and settle on the Gold Coast ladder, where the names are
    keys.append({'at': 1.000, 'z': 3.55, 'focus': _norm(-0.5, -0.5)})
    return keys


# ── the handover: the screams go out and the score comes in TOGETHER ────────
# 2026-08-22, operator: "when the ambient sound drops, make sure the music fades
# in at the same time". Then it was the sea handing over to the strings; the sea
# is gone (2026-08-25) and the thing receding is now the scream bed that opens
# the scene, but the shape is the same one the operator approved — the ramps
# CROSS in one 4 s window, ending 2 s into "No man avoids the cost of living",
# and nothing sits in between.
#
# Both times come from these three names so they cannot drift apart. The scream
# cue's `t_out` is where its fade REACHES silence and its fade_out_s runs back
# from there, whereas the score's `t_in` is where its own fade BEGINS — hence
# the two anchors, offset by exactly _HANDOVER_S. Anchored to the line rather
# than to a typed second because these takes have re-rendered longer twice
# already, and because head_silence_s just moved.
_HANDOVER_S = 4.0
_HANDOVER_END = {'event': 1, 'at': 'start', 'offset': 2.0}
_HANDOVER_START = {'event': 1, 'at': 'start', 'offset': _HANDOVER_END['offset'] - _HANDOVER_S}

CORNELIS_DAY1 = {
    'slug': 'cornelis_day1',
    'width': 1344,
    'height': 768,
    'voices': {
        # 2026-08-21 round 1 PICK: benches/cornelis cg08, "Elder Gravel — heavy
        # body, pitch dropped further" (k=0.925 resample, m=0.950 rubberband),
        # frozen into data/assets/voice_seeds/cast/cornelis_elder_gravel.wav.
        # Absolute, because _resolve_voice_ref only searches the shared pool
        # directory by bare name and this one is cast-specific. It points at the
        # CAST copy, never at the benches/ wav — that directory is rebuilt.
        #
        # THIS REVERSES THE SAME MORNING'S DIRECTION, and the reversal is the
        # point. cornelis_broken was built hours earlier for "make cornelis voice
        # sound more broken, more rough": a real weathered CC0 donor
        # (kd_jeff_andrew) at k=0.895, measuring render wear 9.93 against
        # m03_elder_gravel's 2.95, which is 3.4x the roughness. It was then
        # rejected by ear — along with both attempts at giving it a sigh — and
        # the operator's call was to clean the voice up instead.
        #
        # So the two seeds are opposite ends of one axis, and the numbers say so:
        #     cornelis_broken        render wear 9.85-10.01   HNR ~3.4 dB
        #     cornelis_elder_gravel  render wear 2.94         HNR  9.14 dB
        # The lesson worth keeping is that wear is not a quality score. A voice
        # can measure convincingly weathered and still not be the character —
        # at HNR ~3 dB it was rough enough that voice_qc's own tract measurement
        # stopped working on it (see cornelis_broken.json's caution). Round 1
        # was won by a CLEAN synthetic, not by the roughest candidate on the
        # bench.
        #
        # Elder Gravel is Maya1-designed (Apache-2.0) from a written description:
        # no human recorded, so no consent or personality-rights exposure, and
        # nothing to keep out of a character's mouth. Round 2 (benches/cornelis_r2,
        # eg01-eg10) explores around this pick.
        'cornelis': {'ref': _CORNELIS_SEED, 'seed': 1672},
    },
    # Canon outfit, Qwen-edit enforced on the continuity shot. Prompts steer;
    # only this guarantees he is wearing the same coat in every episode.
    'wardrobe_locks': {
        CORNELIS: {
            'subject': 'the older bearded man',
            'outfit': (
                'a brown wool coat with gold embroidery over a crimson '
                'sash across the chest, and a black wide-brimmed hat'
            ),
            'negative': (
                'red pirate coat, tricorn hat, bareheaded, plain coat, naval uniform, epaulettes, modern clothing'
            ),
            'seed': 42,
        },
    },
    # The same cabin Abel writes his ledger in — the candle in the brass stick
    # and the dark oak planks are the set, and they are shared across the series
    # so the two scenes read as one ship.
    'continuity': {
        'props': (
            'a single burning candle in a simple brass candlestick on the '
            'dark wooden table, dark oak plank walls, a sea chest and '
            'coiled rope behind him'
        ),
        'negative': ('lantern, oil lamp, hanging lamp, glass lamp, modern furniture, bright room'),
    },
    'shots': [
        {
            'id': 'cabin_cornelis',
            'kind': 'solo',
            'char_ids': [CORNELIS],
            # 8814, benched against 1672 and 3311. It is the one that separates the
            # hands the way the scene asks — right hand raised holding something,
            # left flat on the table — and puts the candle in its brass stick and
            # the coiled rope on the bulkhead without being told twice.
            'seed': 8814,
            'continuity': True,
            'last_dialogue_shot': True,
            # Pipe FIRST, then the hands, then the room. The first attempt led
            # with "sitting alone at a small dark wooden table" and got exactly
            # that and nothing else: no pipe at all (a sliver of stick in his
            # fingers), both hands together in the middle of the table, and a
            # gilded blue-and-gold damask chamber instead of a ship. SDXL spends
            # its attention at the head of the clause, so the prop that the scene
            # is ABOUT has to be the first thing said.
            'scene_desc': (
                'smoking a long white clay churchwarden pipe, the pipe '
                'stem held up to his mouth in his raised right hand, '
                'his left hand resting flat on the bare wooden table in '
                'front of him, sitting alone at a small dark wooden '
                'table below deck in a cramped dim 17th-century Dutch '
                'merchant ship cabin at night, low dark oak plank walls '
                'and heavy timber deck beams close overhead, warm '
                'candlelight, a grave unsmiling expression, looking off '
                'to one side in thought, medium wide shot showing the '
                'small cabin around him, cinematic photograph, sharp '
                'focus'
            ),
            'negative': (
                'daylight, sunny, window light, second person, two people, '
                'crowd, smiling, laughing, cigarette, cigar, close-up, '
                'ornate palace interior, gilded panelling, damask '
                'wallpaper, gold filigree, throne room, blue and gold '
                'brocade, stone hall, chandelier, large bright room, '
                'both hands together, empty hands, writing, quill'
            ),
            # The pipe itself is not reachable from the prompt — see the prop_edit
            # note in the service. The sampler puts a sliver of stick in his hand on
            # every seed; this turns it into the pipe, in place, after the wardrobe
            # is locked and before the hand is repaired.
            'prop_edit': {
                # SCOPED TO THE HAND. Whole-frame edits were benched three prompt
                # families deep and never once produced a pipe: Qwen downsamples to
                # ~1 MP, so a 180 px hand arrives as a smudge, and the passes either
                # recoloured the source silhouette (a straight stick → a white rod,
                # a wand, a lit taper) or converted some other object of about the
                # right shape — one turned the CANDLE into a goblet and left the
                # hand alone. Cropping to the hand and upscaling ×2.6 first fixes
                # both: the pipe is synthesised at real detail, and nothing outside
                # the box exists to be repurposed.
                'box': (0.14, 0.55, 0.48, 1.00),
                'instruction': (
                    'the man is holding a white clay tobacco pipe: a '
                    'long slender white stem running through his '
                    'fingers with a small round bowl at its raised '
                    'end'
                ),
                # 'smoke' is in the NEGATIVE on purpose. Asking for "thin smoke
                # rising from the bowl" painted a smoke wisp INTO the plate, and a
                # painted wisp is frozen — it cannot drift, thin or curl, so it
                # sits dead next to the fx.smoke plume that does. There must be
                # exactly one smoke in this shot and it has to be the moving one.
                'negative': (
                    'smoke, smoke wisp, vapour, steam, cigarette, cigar, '
                    'quill, pen, stick, wand, baton, candle, mug, cup, '
                    'two pipes, extra fingers, deformed hand, '
                    'changed clothing'
                ),
                'seed': 42,
                'feather': 26,
            },
            # Action first: apply_hand_fixer_pass keeps only the first comma-clause,
            # so an identity-first prompt tells the fill nothing about the pipe and
            # the pipe is what gets erased.
            'hand_prompt': (
                'a mans hand gripping a long white clay pipe raised '
                'near his face, painterly stylised illustration, warm '
                'candlelight'
            ),
            # A gentle push, not the tight one the Abel cut uses. The pipe bowl
            # ends up at y 0.89 of the plate; at Abel's 1.72-1.88 the window bottom
            # is 0.77 and the whole prop — the thing the scene is about — is out of
            # frame. 1.18 keeps the bowl, its smoke and his face in one window.
            'fx': {
                'kb_zoom': (1.02, 1.18),
                'focus_xy': (0.47, 0.52),
                'flicker': 0.035,
                'particles': 'dust',
                'particle_gain': 0.30,
                'warm': 0.8,
                # Anchor is the PIPE BOWL on the hi-res base, in normalised base
                # coordinates. It is set from the rendered still — see
                # `place_smoke_anchor()` below — because there is no way to know
                # where the sampler put his hand before it has put it there.
                # Measured off the bowl rim in the rendered still (487, 683 of
                # 1344×768). Normalised, so it survives the ESRGAN hi-res base.
                # Anchor measured off the bowl OPENING in the rendered still
                # (532, 684 of 1344×768) — re-measured after the prop edit was
                # re-run without painted smoke, which moved the bowl ~27 px.
                # A prop edit is generative: re-run it and re-measure, never
                # carry the old anchor across. Normalised, so it survives the
                # ESRGAN hi-res base.
                # Opacity 0.78, not the 0.55 that shipped alongside the painted
                # wisp: with the plate's own smoke gone this layer carries the
                # whole effect on its own and had to come up. Swept against the
                # still — 0.95 with tight puffs reads as a steam cloud over his
                # chest, 0.55 as room haze; 0.78 with r1 0.022 and blur 0.005 is
                # a plume that curls and still leaves his face clear. The rest was swept against that still: the first
                # pass tied blur to the puff radius, so a plume that climbed far
                # enough had to be so soft it read as room haze sitting in front
                # of him rather than smoke leaving a bowl. blur_frac is now its
                # own knob and is small.
                'smoke': {
                    'anchor': (0.396, 0.889),
                    'rise_frac': 0.32,
                    'drift_frac': 0.10,
                    'puffs': 70,
                    'r0_frac': 0.0045,
                    'r1_frac': 0.022,
                    'blur_frac': 0.005,
                    'opacity': 0.78,
                    'period_s': 7.5,
                    'seed': 11,
                    'colour': (231, 226, 217),
                },
            },
        },
        # The series chart. Not generated — drawn, so that every episode can pull
        # the identical plate and a course can be laid on real coordinates.
        {
            'id': 'day1_chart',
            'kind': 'map',
            'fx': {
                'warm': 0.25,
                'vignette': 0.24,
                'grain': 3.0,
                # Establish the world, THEN push into the coast, then ease off
                # while the rope draws and drift south with it. A two-value zoom
                # span can only travel at one rate for the whole window, which
                # would either never arrive or arrive before the line starts.
                'kb_keys': _chart_keys(),
            },
            # The Day 1 course. Times hang off the line that describes it, so if the
            # take re-renders longer the rope simply draws for longer with it.
            'route': {
                'legs': 'WEST_AFRICA_RUN',
                'draw': {
                    'from': {'mark': 'tail_start', 'offset': _DRAW0},
                    'to': {'mark': 'tail_start', 'offset': _DRAW1},
                },
                # Thin, as asked. 9 base px on a 5376-wide plate is ~4 px on screen
                # at the framing the rope draws in — a line's weight, a rope's
                # construction.
                'width': 9.0,
                'lay_px': 16.0,
                'label_size': 46,
                'port_fade_s': 0.7,
            },
        },
    ],
    'pullout': {'shot_id': 'cabin_cornelis', 'hold_s': 3.5, 'zoom': (1.18, 1.00), 'focus_xy': (0.47, 0.52)},
    'hand_fix': {'denoise': 0.60, 'attempts': 3, 'crop_ctx': 2.6, 'max_color_delta': 75, 'force': True},
    'dialogue': [
        # SLOWER, on the operator's note — and slowed by RE-SAMPLING the take,
        # not by stretching one. cfg_weight is a Chatterbox sampler knob: lower
        # values make the model GENERATE a more deliberate read. Stretching was
        # already tried and rejected on the Abel cut, because a sentence has
        # rhythm to distort and a stretched one reads as dragged.
        #
        # IT IS NOT MONOTONIC, so both lines were benched rather than assumed —
        # each cfg_weight is effectively a different take, and the two sentences
        # disagree about which is slowest (words/sec on the speech islands):
        #     cfg          0.40   0.35   0.30   0.25   0.20
        #     "price"      3.10   2.50   2.52   2.73   2.61
        #     "cost"       2.63   2.69   2.63   2.41   2.01
        # So they get different values: 0.35 is the floor for the first, 0.20 for
        # the second. Anyone re-tuning these must re-measure — reading a trend
        # off one line and applying it to the other would make one of them
        # FASTER.
        {
            'speaker': 'cornelis',
            'text': 'We all pay the price one day.',
            'cfg_weight': 0.35,  # 3.10 -> 2.50 wps, ~19 % slower
            'pause_after_s': 0.7,
        },
        {
            'speaker': 'cornelis',
            'text': 'No man avoids the cost of living.',
            'cfg_weight': 0.20,  # 2.63 -> 2.01 wps, ~24 % slower
            'pause_after_s': 0.5,
        },
        # A HELD, SCORED PAUSE. This beat was opened for the scream cue when it
        # played here in the clear (2026-08-21), and it STAYS at 5.8 s now that
        # the screams have moved to the head of the scene (2026-08-25, "make the
        # rest of the scene continue as it currently does"): the strings entered
        # under it in the approved cut and still do, so it is a pause under the
        # score, not a hole. The arithmetic that sets the gap:
        #     pause_after_s 0.5  +  beat 5.8  =  6.3 s after the line ends
        # A `beat` advances the clock WITHOUT appending to the timeline, so every
        # {'event': N} in this spec keeps its index — unlike removing a line,
        # which renumbers them (that is how the score once ended up hanging off
        # the chart line instead of the last cabin line).
        {'beat': 5.8},
        # THE EXHALE — REMOVED 2026-08-21 (operator: "both are really bad").
        # Two roads were tried and neither is shippable:
        #  · SYNTHESISED. Chatterbox has no breath token, so the beat had to be
        #    coaxed from a padded vowel ('A' + 'h'*20). Repeated 'h' is a dose
        #    lever that SATURATES AND REVERSES — 12 h → 1.78 s, 20 h → 1.98 s,
        #    30 h → 1.62 s and it starts saying "Um, okay", 44 h → 1.10 s "Oh".
        #    '*sighs*' renders the WORD "size" on every seed. And the take that
        #    shipped measured F0 171 Hz against his 84-88: an octave above his
        #    own voice, which nobody had measured until the swap forced it.
        #  · RECORDED (344 Audio, vocal_fx library). Pitch is fixable —
        #    pitch_semitones -7.18 put the stock sigh from 119.9 Hz onto his
        #    79.4 — and so is level (it arrived +5.7 dB ABOVE his lines). What
        #    is NOT fixable here is TEXTURE: the take measures HNR 21.9 against
        #    his lines' 3.4, so a clean, healthy breath sits between two broken
        #    sentences. Nothing in this pipeline ADDS roughness to a clean
        #    recording. The roughness-matched alternative (m_groans_pained_groan,
        #    wear 1.47) trades the falling exhale shape for it and reads as pain
        #    rather than resignation. Both were rendered and both were rejected.
        # THE REAL BLOCKER IS UPSTREAM: no borrowed breath can match this voice
        # while the voice itself is unsettled. The beat comes back only once
        # Cornelis's own seed is chosen — see data/assets/voice_seeds/cast/.
        # The line below now follows line 1 directly.
        {'speaker': 'cornelis', 'text': 'Yet the cost is more than I can bear.', 'pause_after_s': 0.4},
    ],
    # Spoken over the chart, once the push into the coast has arrived. Anchored
    # rather than in the running order because it sits ~10 s after the last
    # cabin line, and because the beat being hit is "the map has settled", not
    # "the previous line finished".
    'anchored_lines': [
        {
            'speaker': 'cornelis',
            'text': ('We traveled with our goods from afar, sailing through the ports of west Africa.'),
            'at': {'mark': 'tail_start', 'offset': 7.2},
            'align': 'start',
            # A sentence pauses at its own comma, so the island splitter cuts it in
            # two and the default 'loudest' would ship half of it with nothing
            # detecting the loss. `span` keeps first-island-start → last-island-end.
            'take': 'span',
        },
    ],
    # NO AMBIENCE (2026-08-25, operator: "no more ambient ocean sounds"). The
    # waves, gulls and creak that used to open the scene are gone. An EMPTY list,
    # not a missing key: the service falls back to its default waves+creak bed
    # when the key is absent, and that default is exactly the sound being
    # removed. bed_fade_in_s / bed_fade_out / bed_lufs went with it.
    'bed': [],
    'stem_lufs': -23.0,
    'master_lufs': -14.0,
    'music': [
        # THE SCREAMS OPEN THE SCENE (2026-08-25). They come up out of the dark
        # over 3 s, hold for 3, recede over 2 s to a murmur that is still there
        # when he speaks, and go out completely across the same window the score
        # comes in on. The cue starts at frame 0, so its cue-relative shape IS
        # the timeline:
        #     0.0 → 3.0    fade in
        #     3.0 → 6.0    held at full
        #     6.0 → 8.0    settle −12 dB — the picture is fully lit at 8.0 too
        #     8.0 → ~10.2  held soft; he starts on it at 8.2 (head_silence_s)
        #     ~10.2 → ~14.2 fade to silence as the strings rise (_HANDOVER_*:
        #                   the window ends 2 s into event 1, the second line)
        # The asset is `crowd_agony_16s.wav`, NOT the 9 s `crowd_agony.wav` the
        # 08-21 cut used: that one carries ~7.3 s of crowd and then slicing-room
        # silence, and a 14 s cue would have looped 1.5 s of that silence into a
        # second copy's loud head — the crowd vanishing and restarting exactly
        # where he starts to speak. The long bed is the same recordings laid
        # down as staggered, re-pitched waves (build_agony_bed.py --seconds 16),
        # CLAP-verified on registration. Licence: 344 Audio DERIVED — mix-only,
        # never a model input, never redistributed (see its library sidecar).
        # Previously this crowd played in the clear after event 1 (the second
        # cabin line) and the operator rejected it there ("absurdly off"); as a
        # bed under a black frame it is asked for by name, and its level — not
        # a filter — is what keeps it in the background
        # (see [[project-agony-bed-clap]]).
        {
            'name': 'crowd_agony',
            'file': 'crowd_agony_16s.wav',
            't_in': 0.0,
            # 1.2, SWEPT TWICE — and the first sweep picked wrong. The built bed
            # breathes: each wave carries a half-second lull ~2.5 s after it
            # enters, and at 0.0 one of them sat at 8.0-8.5 s, i.e. the murmur
            # dropped ~13 dB in the very half second he starts on. A 0.5 s-window
            # sweep then chose 0.3 for its flat hold — but at 100 ms resolution 0.3
            # still put a ~0.3 s, ~20 dB hole at 7.8-8.2 s, the settle's landing,
            # so the screams stopped and restarted under his first breath (caught
            # in review, on the delivered master). Re-swept 0.7-1.5 at 100 ms: the
            # hole leaves the landing from 0.8 on, and 1.2 is best on every axis —
            # landing min −62 dBFS (0.3: −84), plateau sd 0.9 dB (the most even of
            # the sweep), one sub-−72 dBFS window in the 2.2 s hold (0.3: three).
            # The lesson: measure the landing at the resolution of a syllable, not
            # of a bar — a crowd of discrete groans at −12 dB has gaps a 0.5 s
            # window averages away.
            'src_start_s': 1.2,
            'fade_in_s': 3.0,
            'settle': {'hold_s': 3.0, 'over_s': 2.0, 'db': -12.0},
            't_out': _HANDOVER_END,
            # MUST equal _HANDOVER_S: the screams go out over four, the score comes
            # in over the same four.
            'fade_out_s': _HANDOVER_S,
            # −46, MEASURED, not −39 as first authored. The number is applied to
            # the ~14 s excerpt BEFORE the shape, so it describes the 3 s plateau;
            # and the master chain does not lift everything equally — its limiter
            # passes eat the voice's crest and let quiet material through, so the
            # plateau took +22.1 dB where the voice took +10.5 (measured mix →
            # master on the −39 build). At −39 the screams landed −18.0 dBFS RMS,
            # 5.7 dB under his line — a foreground, not a background. −46 puts the
            # plateau ~12 dB under the voice and the −12 dB murmur ~24 dB under,
            # i.e. 7 dB softer than the gulls this opening used to have. Re-measure
            # the plateau / murmur / voice windows before touching it
            # (scene_state['music'][0]['settle'] gives the windows).
            'lufs': -46.0,
        },
        {
            'name': 'ledger_weight',
            'generate': {
                'prompt': (
                    'slow solemn cinematic underscore, low sustained '
                    'strings, single mournful cello line, sparse '
                    'harp, baroque chamber colour, heavy, resigned, '
                    'instrumental'
                ),
                'seconds': 90,
                'seed': 1672,
            },
            # THE CROSSFADE (2026-08-22). The score starts rising on the frame the
            # scream bed starts its final recession, and reaches full just as the
            # screams reach silence — one 4 s handover rather than two separate
            # moves. (Until 08-22 this was {'event': 2, 'at': 'end', 'offset':
            # -2.0}: 2 s before the end of "Yet the cost is more than I can bear",
            # which measured 22.22 s against the then-sea's ramp at 9.48→13.48 s.)
            # It enters 2 s before event 1 — "No man avoids the cost of living",
            # the SECOND cabin line (indices here are 0-based, as every {'event': N}
            # in this file is) — under the first two cabin lines, and the
            # {'beat': 5.8} that used to be a deliberate hole is scored.
            #
            # (Event indices address the BUILT timeline. A `beat` does not append to
            # it, so inserting one is index-safe; REMOVING a line is not — this was
            # {'event': 3} until the sigh came out of index 2.)
            't_in': _HANDOVER_START,
            # Head-room check: this excerpt is now 42.8 s from 16.0 s in, so the
            # generated track has to be at least 58.9 s long — it is 90.
            'src_start_s': 16.0,
            # MUST equal _HANDOVER_S: the screams go out over four, the score comes
            # in over the same four. Change one and change the other, or the ramps
            # stop landing together.
            'fade_in_s': _HANDOVER_S,
            't_out': {'mark': 'audio_end'},
            # A guard, not the shape: the master's own 2.0 s fade is the ending, and
            # two linear ramps over the same second multiply into something far
            # steeper than either.
            'fade_out_s': 0.3,
            # −37.0, NOT the −36.0 of the approved cut, and this is a compensation
            # rather than a taste change. `_music_segment` normalises the EXCERPT,
            # so moving t_in earlier lengthened the slice 30.10 s → 42.84 s and the
            # extra 12.7 s of source is quieter than the average — at an unchanged
            # −36 the music the operator already signed off measured +1.01 dB
            # louder over its own window (26.2→51.3 s). −37.0 puts it back within
            # 0.01 dB. Any further edit to t_in or t_out is a LEVEL change: re-run
            # the same window measurement before assuming the balance survived.
            'lufs': -37.0,
        },
    ],
    # THE CANDLE REVEAL (2026-08-25) replaces the 2 s black + 3 s fade that
    # opened the 08-21 cut. The frame is dark; the candle on his table — the one
    # in the brass stick at frame right, i.e. the plate's own candle, not a
    # drawn one — is the only thing in it, arriving out of black over the first
    # second. At 3 s its light starts to spread and over 5 s it lights the whole
    # cabin, reaching him before it reaches the far bulkhead (inverse-square
    # from the flame: see storyteller_scene_service._reveal_light). Fully lit at
    # 8.0 s, which is also where the screams land on their murmur.
    #
    # `anchor` is the FLAME's centre in normalised base coordinates, measured on
    # the rendered still like the smoke anchor. NOT the centre of the bright
    # blob: the >250-luma blob at frame right spans y 233-320 of 1344×768, but
    # only its top third is flame — a warm (R−B ≈ 15-77), 3-13 px wide core on
    # rows 228-262 — and the rest is the neutral-white wax body (R−B ≈ 3-30,
    # 29-32 px wide, rows 264-320). The first cut anchored the light at the
    # blob's centre, 29 px down inside the wax (found in review); the source is
    # the flame, centre (1081, 246). It is cut through the same camera as the
    # picture, so the light stays on the flame while the push-in moves the
    # frame under it. flame_r_frac 0.035 is 47 px of full light around the
    # flame — the flame and the top of the candle — with the (R/d)² halo at
    # 0.4 by the foot of the wax and dying on the brass below it, so the
    # candle reads as a candle lit by its own flame rather than a glowing bar.
    # ease 2.0: the lit radius grows as u², so the spread is SLOW off the mark
    # and the 5 s are used evenly — the table first, his face around 5.9 s,
    # the pipe bowl at 6.7, the far-left bulkhead last at 8.0. With the
    # smoothstep first tried he was fully lit by 4.5 s and the remaining 3.5 s
    # only finished a corner nobody looks at (measured on the frames).
    'reveal': {
        'shot_id': 'cabin_cornelis',
        'anchor': (0.804, 0.320),
        'flame_r_frac': 0.035,
        'flame_in_s': 1.0,
        'delay_s': 3.0,
        'dur_s': 5.0,
        'ease': 2.0,
        'flicker': 0.035,
    },
    # 8.2, not 7.5: he starts the moment the screams have settled on their
    # murmur (8.0) and the picture is fully lit (8.0) — a beat after both, so
    # the two arrivals are heard and seen before the voice takes the scene.
    # Everything downstream hangs off marks/events and moves with it.
    'head_silence_s': 8.2,
    'fade_to_black_s': 1.5,
    'title_card': {'text': 'DAY 1', 'dur_s': 3.2, 'fade_in_s': 0.8},
    'tail_shot_id': 'day1_chart',
    'tail_fade_in_s': 3.0,
    'tail_hold_s': 13.5,
    'end_fade_s': 3.0,
    'audio_tail_s': 0.0,
    'master_fade_s': 2.0,
    'subtitles': True,
}


def place_smoke_anchor(x: float, y: float, spec: dict = None) -> dict:
    """Point the plume at the pipe bowl, in normalised base coordinates."""
    spec = spec if spec is not None else CORNELIS_DAY1
    sh = sss.shot_by_id_spec(spec, 'cabin_cornelis')
    sh['fx']['smoke']['anchor'] = (float(x), float(y))
    return spec


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else None
    r = sss.build_scene(copy.deepcopy(CORNELIS_DAY1), out_dir=out)
    sys.exit(0 if r else 1)
