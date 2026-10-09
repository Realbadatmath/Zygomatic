# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.second_ledger — The Second Ledger cold-open intro scene spec (lines 3851-4406).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

# ── The Second Ledger — cold-open intro scene ───────────────────────────────
# Guidelines from the st_second_ledger template: Amsterdam & the Atlantic
# 1672-1676; Abel keeps the ledgers + a journal; Cornelis "must be loved";
# episode beat 1 is a title card; "The Outbound" is the current arc.

ABEL = 'c3345deb5bde'
CORNELIS = '0015c8a3f2e3'

# 2026-08-11 revision (operator notes on the first cut):
#   • Cornelis is OUT — the cold open is Abel alone. His line, the door-creak
#     cue that motivated his entrance, and the two-shot all go with him.
#   • The bed sat ~11 LU under the voice and read as weather; it is now ~21 LU
#     under (bed_lufs -42) so the water is felt rather than heard.
#   • Abel is re-pitched with the formants SHIFTED, not preserved
#     — the render measured 153 Hz / 15.1 cm VTL, i.e. sitting on voice_qc's
#     adult-female calibration point, which is why it did not read as a boy.
#   • The last line now opens a scored beat: suspense fades in under it, the
#     camera pulls out for 6.5 s, then the cue crossfades into a calmer theme
#     across the DAY 1 card.
#
# 2026-08-11 second revision (operator notes on the scored cut — "the music is
# perfect", everything below is around it):
#   • Ambience down 4 dB AND retired: it now fades to silence just before the
#     first cue enters, so the water never shares the underscore's slot.
#   • The harbour no longer pans — it closes on one canal house, and the screen
#     fades before the move arrives (tail_zoom_overshoot_s).
#   • The score outlives the picture by 1 s of black (audio_tail_s).
#   • Abel −3.5 st (was −2.0).
SECOND_LEDGER_INTRO = {
    'slug': 'second_ledger_intro',
    'width': 1344,
    'height': 768,
    'voices': {
        # pitch_semitones re-tunes the frozen seed's RENDER, not the seed: the
        # seed stays canonical for the episode pipeline and every other scene.
        #
        # −1.5 st (2026-08-11; was −3.5, operator: "sounds robotic … make sure
        # it sounds like a teenager"). BOTH complaints had one cause. The old
        # _pitch_shift ran librubberband, which doubles the render's shimmer —
        # the buzzy artefact heard as "robotic" — and gets worse the further it
        # shifts. A thin, buzzy voice does not read as a real boy, so each round
        # of "not right yet" was answered with MORE shift, which added more
        # artefact and walked the pitch down into adult-male territory. Fixing
        # the shifter (see _pitch_shift: resample+atempo, no phase vocoder)
        # removes the artefact, and with it gone the voice no longer needs to be
        # dragged down to sound male. Measured on the same cached raw clone:
        #     shipped  −3.5 rubberband  126.4 Hz / 16.76 cm  → voice_qc adult male
        #     now      −1.5 resample    141.5 Hz / 15.91 cm  → voice_qc teen_male
        # 15.91 cm also clears the 15.5 cm adult-FEMALE tract ceiling, which is
        # the discriminator that matters at this pitch: teen_male and adult
        # female overlap on F0, and only the tract separates them.
        'abel': {'ref': 'abel_seed', 'seed': 1672, 'pitch_semitones': -1.5, 'formant': 'shifted'},
    },
    # Canonical outfit per character — Qwen-edit enforced on every continuity
    # shot (matches the canon_service pixel canon, i.e. what the LoRAs trained on).
    'wardrobe_locks': {
        ABEL: {
            'subject': 'the boy',
            'outfit': ('a plain sober dark-brown wool doublet with a small flat white linen collar, no lace, no ruff'),
            'negative': (
                'purple clothing, striped doublet, ruff collar, ruffled '
                'collar, lace collar, vest, waistcoat, loose white shirt'
            ),
            'seed': 42,
        },
    },
    # Shared props/set — identical across every continuity shot. The negative
    # repels each observed drift mode (the lantern, the invented purple ruff).
    'continuity': {
        'props': (
            'a single burning candle in a simple brass candlestick on the '
            'dark wooden table, a large open leather-bound journal with '
            'cream pages, dark oak plank walls'
        ),
        'negative': (
            'lantern, oil lamp, hanging lamp, glass lamp, purple '
            'clothing, striped doublet, ruff collar, large ruffled '
            'collar, lace collar'
        ),
    },
    'shots': [
        # ONE still carries the whole cabin: a wide of Abel alone at the table.
        # The dialogue is framed tight on him by zooming INTO it (kb_zoom), and
        # the pull-out below simply keeps that same move running out to 1.0. No
        # cut, no second render, and therefore nothing that can drift — the same
        # reasoning that made the first cut's close-up a crop of the wide.
        {
            'id': 'cabin_abel',
            'kind': 'solo',
            'char_ids': [ABEL],
            'seed': 1672,
            'continuity': True,
            'last_dialogue_shot': True,
            'scene_desc': (
                'sitting alone at a small dark wooden table writing in a '
                'large open leather-bound journal with a goose-feather '
                'quill, in a dim cramped 17th-century Dutch ship cabin at '
                'night, warm candlelight, dark oak plank walls, sea chest '
                'and coiled rope behind him, wide shot showing the whole '
                'cabin around him, cinematic photograph, sharp focus'
            ),
            'negative': ('daylight, sunny, window light, second person, two people, crowd, close-up'),
            # Leads with what the hands are DOING, because the fixer keeps only the
            # first comma-clause — an identity-first prompt got the quill erased.
            'hand_prompt': (
                'a boys hand gripping a goose-feather quill pen writing '
                'in an open journal, painterly stylised illustration, '
                'warm candlelight'
            ),
            # Zoom span for the DIALOGUE portion (a slow push in); the pull-out
            # picks up exactly where this ends, so the two read as one take.
            # `flame` lights the candle the pull-out reveals. `flicker` alone is a
            # brightness wobble on the WHOLE frame — the room answering a fire that
            # is itself painted-on and dead still, which is the wrong way round.
            # This puts the movement on the fire.
            #
            # The anchor is the WICK, measured off the plate rather than eyeballed:
            # the painted flame's bright pixels run x 243-257, y 441-508 of the
            # 1344x768 delivery, so the wick sits at (250, 508) -> (0.186, 0.661)
            # and the body is 67 px tall (h_frac 0.087) and ~7 px half-wide
            # (w_frac 0.0052). Those numbers ARE the painted flame; the add-layer
            # has to sit on it, not beside it.
            #
            # Sizes scale with z, so through the pull-out the light pool spills in
            # over the left edge at ~28.6 s, the flame itself crosses at ~30.5 s
            # and lands at its plate position at 33.1 s — the light arrives before
            # its source does, which is what makes the reveal read as a reveal.
            #
            # amount 0.42 (not the room's 0.035) because this is the SOURCE: at
            # 0.035 the fire is the steadiest thing in a frame that is already
            # wobbling. Same seed as `flicker` on purpose — the flame and the room
            # it lights must agree about which way the light just went.
            #
            # The flame MOVES, it does not only pulse: `bend_frac`/`height_amount`
            # warp the plate itself (see `_flame_apply`), so what bends is the
            # painted fire in the plate's own style rather than a drawn flame laid
            # over it. Measured on the delivered frames at z == 1, over 2 s:
            #     tip travel   plate 0.0 px  ->  8.1 px   (body is 14 px wide)
            #     height       plate 0   px  ->   10 px   (71-81 px tall)
            # A brightness-only version of this shipped first and was rejected on
            # exactly that: a lamp on a dimmer, not a fire.
            'fx': {
                'kb_zoom': (1.72, 1.88),
                'focus_xy': (0.63, 0.46),
                'flicker': 0.035,
                'particles': 'dust',
                'particle_gain': 0.35,
                'warm': 0.8,
                # RE-MEASURED 2026-08-30. The candle was repainted at 4x through
                # a crop-scoped Qwen edit because the delivered flame was a soft
                # white sliver with a saturated blue mid-section — an upscale of
                # a plate that never had the detail. The new one is a warm
                # teardrop with a bright core and a small blue base, and it sits
                # 30 px HIGHER on the hires plate than the old one. The warp is
                # anchored to the wick and sized in frame fractions, so shipping
                # the old numbers over the new candle would bend empty air just
                # under it. Measured off the repainted plate at x8: wick at
                # (505, 985) of 2688x1536, tip at y 856, widest half-width 13.5.
                'flame': {
                    'anchor': (0.1879, 0.6413),
                    'w_frac': 0.0050,
                    'h_frac': 0.0840,
                    'halo_r_frac': 0.115,
                    'core': 1.0,
                    'halo': 0.55,
                    'bloom': 0.55,
                    # 0.42, not the brightness-only cut's 0.55: once the
                    # swing drives real GEOMETRY the old depth stretched
                    # the flame into a 26%-taller spike every second.
                    # Brightness tolerates what shape does not.
                    'amount': 0.42,
                    'breath': 0.18,
                    'height_amount': 0.30,
                    # tip travel, ~10 px at z = 1 (8.1 px measured on
                    # the frames) against a 14 px-wide painted flame, so
                    # the lean is unmistakable without the fire leaving
                    # its wick. warp_span bounds the warp tile at 2.2
                    # flame-heights — by there both displacements have
                    # already decayed to nothing on their own.
                    'bend_frac': 0.0075,
                    'warp_span': 2.2,
                    'seed': 7,
                },
            },
        },
        # hand_fix False: there are no hands in a harbour, and the fixer's
        # gate would otherwise open the plate for a pass it cannot help.
        {
            'id': 'day1_harbor',
            'kind': 'scenery',
            'seed': 1672,
            'arcane': True,
            'hand_fix': False,
            'scene_desc': (
                'Amsterdam harbor at dawn in 1672, a tall-masted Dutch '
                'merchant sailing ship moored at the quay being loaded with '
                'crates and barrels, warm golden morning light over calm '
                'water, Dutch Golden Age, canal houses along the waterfront'
            ),
            # The plate is CARRIED, not generated from scene_desc above: it is the
            # delivered harbour re-lit by a Qwen whole-image edit — sun moved to the
            # upper-left corner, sky cleared to blue with a few clouds, chimneys on
            # the roof ridges, the left bank dropped into shadow because a sun up
            # there cannot light canal-facing fronts that point away from it. The
            # composition, the ship and the rigging are the original's.
            #
            # THE CLOSING MOVE IS NOW IN TWO PARTS, and the first part is a HOLD.
            # The bird has to be the only thing travelling while it is on screen —
            # `at` fractions are re-derived by the driver from the take lengths, so
            # the hold always ends exactly when the bird leaves frame.
            'fx': {
                'kb_keys': [
                    {'at': 0.00, 'z': 1.00, 'focus': (0.93, 0.30)},
                    {'at': 0.41, 'z': 1.00, 'focus': (0.93, 0.30)},
                    {'at': 1.00, 'z': 3.00, 'focus': (0.93, 0.30)},
                ],
                'focus_xy': (0.93, 0.30),
                # 0.15, not the old cut's 0.5: that plate was a golden dawn and
                # wanted warming. This one is a blue morning, and 0.5 puts it
                # back to sunset.
                'warm': 0.15,
                'vignette': 0.2,
                # ── the canal ───────────────────────────────────────────────
                # Re-measured on THIS plate: the waterline down the left bank,
                # round the ship's bow, along its waterline, then hard down the
                # quay's corner at x = 893. Excludes the hull, both quays and
                # every crate.
                #
                # amp 0.015, up from v17's 0.006, and the reason is the whole
                # point of this shot's new timing. v17's water was real and
                # INVISIBLE: measured on the delivered file with the pull-in
                # running, the waves moved 0.16/255 of a per-frame change of
                # 28.8 — 0.6%, i.e. the camera moved the picture ~180x more
                # than the water did, and every check that passed had been run
                # with the camera frozen. A frozen-camera check proves the
                # effect EXISTS; it cannot prove it is visible. Now the camera
                # actually stops for the bird, so the canal is the only thing
                # in frame that moves, and the amplitude is sized for a plate
                # whose water is a smooth mirror rather than the old one's
                # heavily painted ripple.
                'water': {
                    # RE-MEASURED 2026-08-30 on the rebuilt plate. The left
                    # bank is a new quay so its waterline moved, and the right
                    # edge now runs out to 0.753 instead of 0.664 because the
                    # crate stack that used to stand IN the canal there is gone
                    # and that area is water — which also means the seam where
                    # it was patched sits inside the mask and ripples with the
                    # rest of the canal rather than sitting still under it.
                    'poly': [
                        (0.0000, 0.7370),
                        (0.0818, 0.7240),
                        (0.1711, 0.7057),
                        (0.2530, 0.6901),
                        (0.3348, 0.6732),
                        (0.4055, 0.6615),
                        (0.4539, 0.6536),
                        (0.4799, 0.6589),
                        (0.4911, 0.6849),
                        (0.5015, 0.7109),
                        (0.5149, 0.7305),
                        (0.5372, 0.7383),
                        (0.5952, 0.7448),
                        (0.6548, 0.7513),
                        (0.7143, 0.7578),
                        (0.7530, 0.7656),
                        (0.7530, 1.0000),
                        (0.0000, 1.0000),
                    ],
                    'horizon': 0.648,
                    'vp_x': 0.470,
                    'amp_frac': 0.024,
                    'lateral': 0.35,
                    'profile': 1.5,
                    'min_px': 9.0,
                    'feather': 0.010,
                    'trains': [
                        (0.50, 1.35, 0.45, 0.0, 0.00),
                        (0.31, 0.66, 0.76, 17.0, 1.93),
                        (0.19, 0.33, 1.18, -26.0, 0.61),
                    ],
                    # The photometric half, added after the delivered v17 read
                    # as a dead canal despite measurably moving: crests tilt
                    # toward the sky and brighten, troughs tilt toward the dark
                    # quay and darken, exactly as the flame's bidirectional
                    # multiplier works. Geometry alone gives the eye nothing on
                    # a smooth low-contrast surface.
                    'shade': {'amount': 0.30},
                    'glint': {'gain': 0.60, 'width': 0.34, 'lum0': 0.55, 'lum_w': 0.26, 'rgb': (255, 226, 176)},
                },
                # ── two chimneys alight ─────────────────────────────────────
                # Anchors are the POT MOUTHS, measured off the plate at x10:
                # the left stack's right pot spans x 99-110 with its rim at
                # y 186, so the source is (104.5, 187) -> (0.0778, 0.2435); the
                # right bank's stack has its rim at (1024, 218) -> (0.762,
                # 0.2839). Anchoring on the stack instead of the pot is what
                # makes smoke appear to leak out of a roof beside a chimney,
                # which is the failure this measurement exists to avoid.
                # The first puff is r0 wide and centred ON the rim, so it
                # overlaps the pot's mouth rather than starting in clear air
                # above it.
                # Colour is not decoration here, it is which side of the sun
                # the plume is on. The LEFT stack stands between the lens and
                # a sun in the upper-left corner, so its smoke is BACKLIT and
                # reads darker than the sky behind it; shipped pale, against
                # that sky's glare, it measured invisible. The RIGHT stack is
                # lit from the left against clear blue, so its smoke is pale.
                # Same effect, opposite colours, because they are lit from
                # opposite sides.
                'smoke': [
                    {
                        'anchor': (0.0778, 0.2435),
                        'rise_frac': 0.20,
                        'drift_frac': 0.070,
                        'r0_frac': 0.0060,
                        'r1_frac': 0.021,
                        'puffs': 34,
                        'period_s': 11.0,
                        'opacity': 0.45,
                        'mouth_frac': 0.13,
                        'stratify': True,
                        'colour': (140, 132, 120),
                        'blur_frac': 0.0028,
                        'seed': 11,
                    },
                    {
                        'anchor': (0.7872, 0.2852),
                        'rise_frac': 0.13,
                        'drift_frac': 0.045,
                        # 34 puffs, not 26: phases are random, so a sparse
                        # column leaves instants with no puff near u = 0 and
                        # the plume measurably detaches from its own pot.
                        'r0_frac': 0.0055,
                        'r1_frac': 0.016,
                        'puffs': 34,
                        'period_s': 13.0,
                        'opacity': 0.34,
                        'mouth_frac': 0.18,
                        'stratify': True,
                        'colour': (236, 232, 224),
                        'blur_frac': 0.0024,
                        'seed': 23,
                    },
                ],
                # ── the canary ──────────────────────────────────────────────
                # In from the right two seconds after the harbour arrives, down
                # into the harbour over the water, out past the camera on the
                # left. `t0_rel` is measured from the SHOT's arrival, not the
                # top of the scene, so it survives any line above it
                # re-rendering at a different length.
                #
                # It grows to 1.35x on the way out because it is passing the
                # lens, and the path's last waypoints are off-plate on purpose:
                # a bird that reaches the frame edge and stops has landed on
                # the glass.
                # The flight is a DEPTH move, not a pass across the frame:
                # in from the right close to the lens, out toward the moored
                # ship and away from us, then round and off to the left. That
                # is carried by `scale`, which falls to 0.52 at the ship — the
                # bird is 97 px of wingspan when it enters and 34 px at the
                # ship. The path rises toward the horizon (0.643) as it
                # recedes, because something above eye level that goes away
                # from you drops TOWARD the horizon, not off the top of frame.
                'bird': {
                    't0_rel': 2.0,
                    'dur_s': 5.0,
                    'path': [
                        (1.12, 0.395),
                        (0.95, 0.425),
                        (0.81, 0.455),
                        (0.69, 0.482),
                        (0.585, 0.500),
                        (0.475, 0.498),
                        (0.355, 0.482),
                        (0.215, 0.462),
                        (-0.08, 0.438),
                    ],
                    'size_frac': 0.024,
                    'scale': [(0.0, 1.50), (0.30, 0.95), (0.55, 0.52), (0.78, 0.52), (1.0, 0.62)],
                    'bound_period_s': 0.82,
                    'flap_frac': 0.62,
                    'beats': 5.0,
                    'bound_frac': 0.95,
                    'dive_gain': 0.45,
                    'pitch_gain': 0.30,
                    'supersample': 3,
                    'blur_frac': 0.0005,
                    'ink_px': 2.5,
                    'ink_rgb': (44, 32, 20),
                    'shade': 0.34,
                    # colours come from _CANARY: a real canary is a
                    # streaky finch, not a yellow blob, and the map is
                    # kept even where the ground colour is bred lemon.
                },
            },
        },
    ],
    # The pull-out beat: the last line lands, then the camera keeps opening up
    # on the same still for 6.5 s before the fade to black. Zoom starts exactly
    # where the dialogue framing ended (2.00) so the move is continuous.
    'pullout': {'shot_id': 'cabin_abel', 'hold_s': 6.5, 'zoom': (1.88, 1.00), 'focus_xy': (0.63, 0.46)},
    # Anatomy repair settings — see stage 1b2 for why each is not the default.
    'hand_fix': {'denoise': 0.60, 'attempts': 3, 'crop_ctx': 2.6, 'max_color_delta': 75, 'force': True},
    'dialogue': [
        {
            'speaker': 'abel',
            'text': ('Five hundred and ninety three days. That is how long we have been at sea.'),
            'pause_after_s': 1.0,
        },
        {
            'speaker': 'abel',
            'text': ('I am tasked with upkeep of the ledgers, and with writing a journal of our voyage.'),
            'pause_after_s': 1.0,
        },
        {
            'speaker': 'abel',
            'text': (
                'The men are tired and malnourished. Our ship is broken. Yet home is far away, like a distant memory.'
            ),
            'pause_after_s': 0.9,
        },
        {'speaker': 'abel', 'text': 'It is likely we will not return.', 'pause_after_s': 0.6},
    ],
    # The word lands over the DAY 1 card, one second after it appears — spoken
    # into the black, before the harbour is revealed, so it reads as the thought
    # he is carrying into the voyage rather than a caption on the house. It is
    # NOT part of the running order (it sits ~8 s after the last line), so it is
    # authored as an anchored line: START on card_start + 1.0. Aligned to the
    # START here, not the end, because the beat being hit is "one second into
    # the card" — where the word BEGINS is the thing that matters, and the card
    # (3.2 s, 0.8 s fade-in) has room for it to finish.
    # seed 99, not the scene's 1672: a one-word prompt is where this TTS is
    # least reliable, and the take has to be picked rather than assumed. Of the
    # seeds rendered, 1672 put a spurious word in front of it ("Q. Home." /
    # "Here. Home."), 7 gave "You know, home.", 1673 produced a single clean-
    # looking take that says "Kewaum". 99 renders "Home." once, correctly.
    # The seed only re-rolls the SAMPLER; identity still comes from the frozen
    # abel_seed clone, so this is a different take of the same voice.
    'anchored_lines': [
        {'speaker': 'abel', 'text': 'Home.', 'seed': 99, 'at': {'mark': 'card_start', 'offset': 1.0}, 'align': 'start'},
    ],
    # Barely-there maritime ambience.
    'bed': [('waves_hull_01.wav', 0.0), ('ship_creak_02.wav', -7.0)],
    # The water comes up out of silence rather than being present from frame
    # one. 2.0, not the 3.0 first tried: at 3.0 the ramp landed on Abel's first
    # word, so the bed was still arriving as he spoke. The scene originally had
    # the water at FULL level for a full second before the first line (bed from
    # frame one, head_silence_s 1.0), and that settled beat is what makes the
    # place read before the voice takes over — operator asked for it back. So
    # the ramp is sized to finish 1.0 s ahead of head_silence_s (3.0), not to
    # fill it. Move head_silence_s and this has to move with it.
    'bed_fade_in_s': 2.0,
    'stem_lufs': -16.0,
    # −42 (was −38, operator: "the water is still too loud"). That is 26 LU under
    # the voice stem BEFORE the sidechain duck takes another ~7 dB out of it
    # under speech. The delivered distance is NOT the authored one — the master
    # gain-up moves it — so re-measure windowed RMS against a speech window
    # rather than trusting the number: [[project-scene-audio-levels]].
    'bed_lufs': -42.0,
    # The bed hands the scene over to the score and never returns. 6.5 s ramp
    # (was 3.0), reaching silence 0.6 s AFTER the first cue enters (was 0.4 s
    # before) — operator: "fade out over more seconds … stop 1 second later …
    # start fading 2-3 seconds earlier so it's a nice smooth fade out". So the
    # ramp now runs 18.8→25.3 s where it used to run 21.3→24.3 s.
    # `lead_s` is NEGATIVE on purpose: the handover is now a short overlap
    # rather than a gap, i.e. the water is still receding under the first bars
    # of the score instead of clearing the slot before it. The two no longer
    # compete for the "just under the voice" slot because by the time the cue
    # is established the bed is already ~20 dB down the ramp.
    # NOTE the ramp STARTS under line 2, where the bed is ducked and inaudible
    # anyway — so what is actually heard is the bed arriving already well down
    # in the gap after that line, which is the smoothness being asked for.
    'bed_fade_out': {'fade_s': 6.5, 'lead_s': -0.6},
    # Two ACE-Step cues (MIT weights → clean for a monetised channel). Cue times
    # are anchored to events/marks, so they follow the dialogue if a line is
    # re-rendered at a different length.
    'music': [
        {
            'name': 'suspense',
            'generate': {
                'prompt': (
                    'dark ambient orchestral suspense, sustained low '
                    'strings, slow swelling cello drone, distant '
                    'timpani heartbeat, sparse, ominous, no melody, '
                    'cinematic underscore, instrumental'
                ),
                'seconds': 60,
                'seed': 1672,
            },
            # in under the last line, out just before DAY 1
            't_in': {'event': 3, 'at': 'start', 'offset': -0.3},
            'src_start_s': 14.0,  # skip the track's silent opening build
            'fade_in_s': 3.0,
            't_out': {'mark': 'card_start', 'offset': -0.2},
            'fade_out_s': 2.2,
            'lufs': -37.0,
        },  # lands ~13 dB under dialogue in the master
        {
            'name': 'nuanced',
            'generate': {
                'prompt': (
                    'reflective cinematic underscore, warm solo cello '
                    'over soft strings, gentle harp, hopeful but '
                    'melancholic, slow, spacious, baroque chamber '
                    'colour, instrumental'
                ),
                'seconds': 60,
                'seed': 1673,
            },
            # crossfades under the suspense tail and carries the card + the harbour
            't_in': {'mark': 'card_start', 'offset': -1.8},
            'src_start_s': 18.0,
            'fade_in_s': 2.6,
            # Outlives the picture: the fade lands on 'audio_end', which is
            # audio_tail_s past the black frame. fade_out_s == end_fade_s +
            # audio_tail_s, so the music starts fading exactly as the screen does
            # and finishes one second into the dark.
            't_out': {'mark': 'audio_end'},
            'fade_out_s': 2.5,
            # −35.2, not the −37.0 its twin still uses. Extending this cue by the
            # audio tail made it a 14.5 s excerpt instead of 13.5 s, and
            # _music_segment normalises the EXCERPT — the extra second is louder
            # than the cue's average, so hitting −37 scaled everything before it
            # down. Measured 1.77 dB quieter against a fixed speech window than the
            # cut this level was approved on; this puts it back.
            'lufs': -35.2,
        },
    ],
    # 3.0 (was 1.0): Abel starts speaking two seconds later, so the opening
    # picture fade and the ambience ramp both complete into silence before the
    # first line rather than under it. Every music cue and the anchored "Home."
    # hang off marks/events, so they all shift with it — nothing to re-time.
    'head_silence_s': 3.0,
    # Open from black over 1 s. The bed ramp is longer (2 s) on purpose: sound
    # keeps arriving after the picture has, so the scene does not "start" twice.
    'fade_in_s': 1.0,
    'fade_to_black_s': 1.2,
    'title_card': {'text': 'DAY 1', 'dur_s': 3.2, 'fade_in_s': 0.8},
    'tail_shot_id': 'day1_harbor',
    'tail_fade_in_s': 1.5,
    'tail_hold_s': 5.5,
    'end_fade_s': 1.5,
    # The closing zoom is authored to run 2.0 s LONGER than the picture lasts, so
    # the screen fades while the camera is still closing on the house — it ends
    # approaching, never arriving. Reaches z≈2.17 of the authored 3.0 at black.
    'tail_zoom_overshoot_s': 2.0,
    # One second of black after the fade, for the score to resolve into.
    'audio_tail_s': 1.0,
    # Guard fade only — the musical shape is the cue's own fade_out_s above.
    # Measured at 1.0 s (i.e. spanning the whole tail): it multiplied the cue's
    # fade over exactly the second that is supposed to be audible and cost 8 dB
    # at the tail's midpoint, so the score was effectively gone a third of the
    # way into the dark. 0.3 s only catches the landing.
    'master_fade_s': 0.3,
}
