<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# The Medusa board's mane is a rendered loop

2026-09-23. The snakes used to be animated in the browser: 39 cut-outs redrawn
every frame as strips sheared by a sine wave (`_mdzDrawSnake` in
`kanban_main.js`). That is a *wobble*, and it was rejected as one. A flat 2D
shear cannot make a coil glide along its own length, cannot move one loop behind
another, and every extra pixel of swing risks exposing the blurred plate
underneath. The ceiling was structural, not a tuning problem.

So the mane is now a video — but **not one frame of the model's output is on the
board**. Wan2.2 supplies the motion; the pixels stay the artist's.

```
    craiyon_142159_….png  (the lossless drawing, 882x986)
              │
              │  render_medusa_loop.py motion      448x496 x 81f, ~6 min GPU
              ▼
    medusa_motion.mp4      — a reference for MOTION ONLY, never shown
              │
              │  warp_medusa_loop.py               ~3 min, CPU
              │    · dense optical flow, chained and composed frame to frame
              │    · smoothed, edge-preserved, clamped, tapered to zero at the lock
              │    · the DRAWING is remapped along that field
              │    · the 8 tongue sprites are stamped on top, flicking
              ▼
    medusa_loop.mp4  ── served at /medusa/loop.mp4 ── the board
```

## Why not simply show the render

It was tried, at 896x992 x 81 frames, 42 minutes of GPU, with her face locked and
only the mane composited. The mane still came back **visibly re-drawn**: strokes
thicker, scales blobbier, contrast up. A diffusion video model does not move a
drawing, it re-imagines one 81 times. Measured on that take:

* bulk motion, at the mane, after smoothing: **0.12 px** — nothing moved;
* what *did* change was every stroke by about a pixel, everywhere at once,
  which is boil, not motion. The difference map lights up her eyelashes and the
  lips as brightly as the coils.

The same graph at 448x496 moves properly (9.9 px of travel). Resolution is the
motion lever on this model, and it is not a knob we can turn up: the drawing has
to end up at 882x986. Hence the split — measure the motion where the model moves
things, apply it where the drawing lives.

## What the warp must get right

* **Taper the FIELD at the lock, do not blend two images.** Cross-fading a
  warped copy against a still one puts a soft double image wherever the warp
  moved something across the boundary — it showed up first as a white cloud
  under her brow, where the face lock cuts through a snake's jaw. A field
  multiplied by `loop_alpha.png` fades to nothing instead: one continuous
  deformation, every line still one line, and where alpha is 0 the displacement
  is 0, so her face is the drawing by arithmetic rather than by compositing.
* **Smooth, then edge-preserve.** The Gaussian pass (sigma 20 px at output
  scale) is what kills the boil — a one-pixel shimmer is spatially incoherent
  flow and a low-pass filter eats it. The bilateral pass after it keeps the jump
  between "this coil moves" and "the paper behind it does not"; a jump in an
  inverse map is a clean edge, a smeared jump rubs out the coil's own outline.
* **Clamp, do not scale.** 13 px is the ceiling. At ~22 px the ink stretches
  into taffy; the clamp holds back the excursions without flattening the sway.
* **The tongues are drawn, not warped.** The layer that moves is the drawing
  with all eight drawn tongues inpainted out of it (the `tpatch_NN.png` rects
  from the bake); the sprites are stamped back on top, sliding out of the mouth
  along the axis baked into `snakes.js` and riding their own head's
  displacement. Warping the drawn tongue instead gives a tongue that sways but
  never flicks.
* **The loop is found, not conditioned.** `end_image` = the start frame does not
  close the loop on this checkpoint (measured: the last frame was the *furthest*
  from the first), `WanVideoLoopArgs` made it worse, and pinning both ends is
  itself a brake on the motion in between — so the motion render does not use
  it. The composer searches for the best matching pair of frames instead. On
  this take the best cut still had a seam 8.4x a frame's own step, so the
  **ping-pong** variant ships: 81 frames out and back, 160 frames, 9.4 s,
  seamless by construction. For a deformation that returns exactly to the
  drawing at the turnaround, the rewind is not visible.

## Numbers for this loop

| | |
|---|---|
| mane travel | 9.94 px mean, 11.72 px peak |
| frames / length | 160 / 9.41 s at 17 fps |
| size | 7.4 MB h264, 882x986 |
| locked deviation from the drawing | **0**, outside the tongue rects |
| inside the tongue rects | 245 — the flick, which is the point |

Re-make it with
`MDZ_FLICKS=2 MDZ_GAIN=1.3 MDZ_SMOOTH=20 MDZ_CLAMP=13 MDZ_BILAT=1.5
/usr/bin/python3 warp_medusa_loop.py medusa_motion.mp4 <out>` — CPU only, no GPU
run needed as long as `medusa_motion.mp4` is kept.

## Rendering a new motion source

`render_medusa_loop.py probe` first — same graph, 33 frames, four minutes. It has
already caught a failure that would have cost 45 minutes (the fp8 T5 encoder,
which that node refuses). Then `motion` for the real one. Other rules that are
not free choices:

* **No Lightning LoRA.** Measured on this box (2026-09-06): the 4-step LoRA held
  the subject but panned the camera instead of moving it, and invented content.
* **shift 5.0, noise_aug 0.0.** Shift is this stack's measured motion lever;
  noise augmentation buys motion by buying invention.
* **`timeout_s` must be passed.** `_comfy_client.submit` defaults to 600 s and
  *interrupts your own prompt* when it expires.
* **Pad, never rescale** if you ever render at the drawing's own size: 882x986
  is not a multiple of 16 and rescaling misregisters everything against the
  masks. (The motion path does not care — flow is resampled either way.)

## Serving it

`kanban_server.py` serves the file from one fixed path, `/medusa/loop.mp4`,
rather than by adding `.mp4` to `_STATIC_OK_EXT`: `HERE` is the crews *source*
tree and the listener is on 0.0.0.0, so that one line would publish every mp4
under it. Adding the route needed a restart of :8899 (the `kanban-server` user
unit — *not* crewai-gui, so no Medusa render or assistant turn is at risk). The
CSS and JS do not need one.

Bump `MDZ_V` in `kanban_main.js` whenever the loop or the masks are re-made: the
static path sends no `Cache-Control` for images and video, so the query string is
the only cache lever. Two backdrops are out of its reach and must be edited by
hand if `medusa_base.jpg` is ever re-baked — `kanban.css` (`.mdz-solo` only) and
`templates/enhanced_dashboard.html` (the framed case).

The canvas is still there and still correct; it takes the board back if the video
404s or the browser cannot decode it.

## Judging it

At board size, not zoomed: the GUI runs at `html{zoom} .67` and the drawing sits
at 882x986, displayed around 1233 px wide. A 2.4x crop exaggerates resampling
nobody can see on the board.

## The page backdrop behind the board (:5000) is a different file

2026-10-02. Two moving things now carry this drawing, and they are **not** the
same asset or the same rule:

| | the mane, on the board | the page backdrop, on :5000 |
|---|---|---|
| file | `medusa_loop.mp4`, 882x986, 9.4 s | `medusa_backdrop.mp4`, 512x512, 30.0 s |
| route | `/medusa/loop.mp4` | `/medusa/backdrop.mp4` |
| pixels | **the artist's**, warped by optical flow | LTX-2.5 generated |
| where | `.mdz-video` inside the :8899 frame | `#zyg-medusa-bg` in `templates/enhanced_dashboard.html` |
| when | only while a workflow is live | whenever the Medusa board is the shown board |

Everything above in this file still holds for the mane: a diffusion model
re-draws the linework, so the board itself keeps showing the drawing. The
backdrop is the one place that rule does not bite, because it is blurred to a
dim wash before anyone sees it — at `blur(58px) saturate(.3) brightness(.34)`
there is no linework left to re-draw, which is also why a square 960 px source
is fine behind a portrait drawing (`object-fit: cover`).

* **It arrives pre-blurred.** `gblur=sigma=28` in ffmpeg, then down to 512 px,
  then crf 20 → 0.5 MB for 30 s. Only `blur(8px)` is left in CSS. A full-screen
  `blur(58px)` on a *video* is re-computed every frame; on the still it was paid
  once. Blurred frames also compress to nearly nothing, which is where the 0.5 MB
  comes from.
* **The still stays underneath and is still the fallback.** The layer only adds
  `.zyg-has-vid` on the video's `canplay` and drops it on `error`, so a 404 or a
  codec the browser will not decode leaves exactly the backdrop that was there
  before. Nothing else had to change for that: `::before` already paints it.
* **`apply()` is the only thing that starts or stops it**, and the `<video>`
  deliberately carries **no `autoplay` attribute** — with one, the element
  resumes itself after `apply()` parks it and the backdrop keeps decoding on
  Metrics, Audit and every other tab. The click handler that retries a refused
  autoplay must also be **deferred** (`setTimeout(apply, 0)`): a click that
  switches tabs has not moved the panel yet while the handler runs, so playing
  there races the pause the panel change is about to do. Both of those were
  measured as "paused: false on another tab", not guessed.
* **Bump `MDZ_BG_V`** in `templates/enhanced_dashboard.html` when the file is
  re-made — the route sends `max-age=86400` and no validator, same as the mane
  loop's `MDZ_V`. Template edits need no restart (`TEMPLATES_AUTO_RELOAD`);
  adding or changing the *route* needs `systemctl --user restart kanban-server`,
  gated on `/inspect/api/architecture/assistant/active` reporting `running: 0`.
* The backdrop follows the board, not the tab: leave Medusa and the board
  auto-follows to whatever pipeline is live, the frame posts `on: false`, and the
  backdrop parks and rewinds. Verified in Chrome at 1600x900.

Source clip and how it was made: `output/ltx25_video/gorgon_board_snakes_loop_30s/`
and the loop notes in the LTX install (`build_loop_api.py`, `make_loop.py`).
