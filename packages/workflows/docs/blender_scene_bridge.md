# The Blender scene bridge

One `shot.json` in, one `final.mp4` out: the character acting in the Blender city,
with the VFX volumes rendered in Cycles and laid over the video engine's picture.

```bash
"…/agents/.venv/bin/python" scene_shot_run.py \
    data/architecture/shots/<id>/shot.json \
    [--engine vace|animate] [--draft-only] [--skip-video] [--force STAGE,…]
```

Seven stages, each idempotent, each skipped when its outputs are newer than its
inputs, each writing a line into `<shot_dir>/receipt.json`:

| # | stage | tool | output |
|---|---|---|---|
| 1 | validate | `scene_shot.load/validate/resolve_positions` | `shot.resolved.json` |
| 2 | build | `blender_scripts/scene_build.py` | `scene.blend` |
| 3 | draft | `scene_render.py --mode draft` | `draft/draft.mp4` |
| 4 | plates | `scene_plates_export.py` + `scene_plates.build` | `plates_raw/`, `plates/` |
| 5 | video | VACE or Wan-Animate | `video/<engine>_take<N>/` |
| 6 | vfx | `scene_render.py --mode full --effects-only 1` | `full/effects_alpha.mov` |
| 7 | composite | ffmpeg | `final.mp4`, `final_strip.png` |

`--draft-only` stops after 3. `--skip-video` runs everything but 5 and 7.
`--force plates,vfx` reruns named stages regardless of mtimes; the cascade only ever
runs forward, never back.

## The six operator questions

### 1. Where is the city?

`shot.drawing` — an absolute path to an Architecture Studio project JSON. Stage 2 hands
it to `arch_blender_build.build()`, the very builder the studio renders with, so the
geometry in the shot is the geometry in the studio, not a copy of it. The fixture
drawing is `data/architecture/projects/first-building-attempt.json` (44 KB, 223 records).

### 2. Where is the camera?

`shot.camera.keys = [{f, p, t, fov}]`, studio frame (Y-up), interpolated by
`scene_shot.camera_at` and baked one key per frame onto `shot_cam`. `fov` is VERTICAL
with a 36 mm sensor fit. The baked track is re-exported per frame into
`plates_raw/camera.json` (`near`, `far`, `matrix_world`, `lens_mm`), which is what
`vfx_place.camera_from_scene_shot` reads when you place an element on the finished clip.

### 3. Where are the VFX?

`shot.effects = [{id, pack, size_m, start_frame, rel|p}]`. `pack` is a bare filename that
must exist in `scene_shot.VDB_DIR`; a VFX-library `vfx_volumes` row's `f` field is
already exactly that, so no translation. `rel: {to: <actor id>, dx, dy, dz}` is resolved
against the actor's position by `resolve_positions`, which returns a deep copy of the
SHOT with each `rel` replaced by an absolute `p`. Measured extents land in
`effects_bounds.json`; per-frame projected pixel boxes land in `<mode>/placement.json`.

### 4. Where is the actor?

`shot.actors = [{id, char_id, proxy, height_m, motion, start_frame, path:[{f,p,ry}]}]`.
A proxy mesh is placed as a COLLECTION INSTANCE and animated along `path`. Stage 4 turns
that into the plate channels below. **Stage 5 renders actor index 0 only** — the plate
set already carries every actor's matte and skeleton, so the loop is a change to that
one stage, but today the rest of the cast is in the picture as proxies.

### 5. What does the video engine do with it?

It resamples the actor region of the Blender beauty plate and holds everything else.
Both engines take the same plate set; neither has ever seen the VFX volumes.

### 6. What does it look like cut together?

Stage 7: the engine clip scaled to the shot resolution, retimed to `shot.fps`, with
`effects_alpha.mov` overlaid (`overlay=format=auto` — a real 12-bit alpha), encoded
libx264 crf 18 yuv420p. `final_strip.png` stacks frames 1 / mid / last as
draft | ctrl | engine | final, which is the one image that shows all four layers agreeing.

## Contracts

**`shot.json`** — `zyg.scene_shot/1`: `id, drawing, fps, frames, resolution:[w,h], camera,
sun:{hour}, actors[], effects[], render:{draft:{width,height,engine}, full:{samples,denoise}},
video:{engine,prompt,steps,seed}`. `scene_shot.validate` ignores unknown keys but does
enforce the effect packs. Editing it bumps its mtime and so rebuilds everything.

**`plates_raw/`** (written by the exporter, read only by `scene_plates`) —
`beauty_%05d.png` 8-bit RGB · `depth_%05d.png` 16-bit BW, **near = WHITE, far = BLACK**,
linear in camera Z, sky = 0 · `matte_<actor>_%05d.png` 8-bit 0/255 · `joints.json`
(33 `geom.keypoints.POSE_NAMES` per actor per frame) · `camera.json` · `actors.json`.
EEVEE Next has no `IndexOB` pass, so the mattes are a depth diff: render Z with the actor
and without, and threshold the difference. Occlusion-correct by construction.

**`plates/plateset.json`** — `zyg.plateset/1`, six channels in one directory:
`bg_` (beauty with the proxy painted out), `ctrl_`, `depth_`, `face_`, `m_` (dilated actor
matte), `pose_` (the rig's own skeleton — no pose detector anywhere in this pipeline),
plus `still.png`. The actor region is flattened to grey 127 and the skeleton drawn over
the WHOLE frame, not clipped to the proxy silhouette.

## The two engines, and what they cost

| | VACE | Wan-Animate |
|---|---|---|
| entry | `movement_studio.render_kwargs` → `wan_vace_service.generate_vace_static_clip` | `wan_animate_service.animate_from_plateset` |
| peak VRAM | 22.8 GB | 28.9 GB |
| wall (49 f, 832×480, 20 steps) | ~460 s | ~193 s |
| output fps | **17** | 24 (inherits the plate set) |
| face | resampled | **static** — the canon crop is repeated, `face_source: canon_static` |

Both need `num_frames` = 4n+1 or the encoder truncates; the runner forces it.
LoRA names need the subfolder: `wan_chars/wan_char_<id>_t2v.safetensors`.

**Limits to plan shots around.**
- **Identity decays over a long shot.** Keep shots ≤ 4 s (≈ 97 frames). Longer means
  context windows, and the character drifts between them.
- **Identity is unmeasurable when the actor is small.** On `fixture_house` the actor
  matte is 107 px tall falling to 82, i.e. a head of 11–14 px against MTCNN's 20 px
  minimum, so facenet returns `no_face` on every frame and the receipt says so rather
  than inventing a cosine. That wants a closer camera or a bigger render, not a retake.
- **The VFX are not lit by the engine output, and do not light it.** They are a separate
  Cycles pass laid on top. A volume that should spill onto the actor will not.
- **The face is held on Wan-Animate.** Do not write dialogue against that engine.

## Draft first, full later

Stage 3 is the check point: Workbench at `render.draft` size, every volume replaced by a
labelled wire box. Tenths of a second per frame, and it answers "is the fire where I said
it was" without a path tracer. `--draft-only` is that loop. Only when the boxes are right
is it worth spending stage 6, which is Cycles at `render.full.samples` with the buildings
as holdouts.

## Locks, and why

- **Every** headless Blender launch holds `flock /tmp/claude-1000/arch_ext_blender.lock`.
  Two at once SIGBUS the Bonsai add-on. `scene_shot_run.blender_run` does this for you.
- Stages 5 and 6 additionally hold `geom.pose_track.gpu_lock` (`/home/zygomatic/.zyg_gpu.lock`),
  which blocks in `flock(2)` rather than polling so it queues fairly with every other job.
- Stages 2, 3 and 4 are EEVEE/Workbench rasterising on the display GPU; they take the
  Blender lock only, as tasks 2/3/9 did.

## What the receipt records

`<shot_dir>/receipt.json` (`zyg.scene_shot_run/1`): per-stage `ran`/`reason`/`wall_s`,
the engine and its clip, `ffprobe` of the clip and of `final.mp4`, file sizes, the
plateset / camera / `effects_bounds` facts, the `identity` block (measured or honestly
`unmeasurable`), and a `licence` block from `licence_provenance.publish_decision` on the
LoRA weights actually used. The licence verdict is **recorded, not enforced** — this
assembler makes a working file; the publish boundary is zpub's to hold.

Stage 7 also writes `final.settings.json` (and `clip.settings.json`) with
`{"scene_shot": <shot_dir>}`, which is how the Video Studio placement rack finds this
shot's camera track instead of an fov dialled in after the fact.
