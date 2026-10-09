# Photogrammetry capture protocol — one person, one phone, no rig

Companion to `geom/scan_ingest.py`. This document is the CAPTURE half; the module is the
INGEST half. Read this before taking a single photograph, because almost every failure of
a single-camera human scan is baked in at capture time and cannot be repaired afterwards.

---

## 1. What we are actually trying to get, and what we are deliberately throwing away

**We do not want proportions from a scan.**

Proportions we already have, from ANSUR II: 4,082 measured men and 1,986 measured women,
93 dimensions each, public domain (see `data/assets/anthro_reference/PROVENANCE.json`).
A scan gives us proportions from exactly one person, with no percentile attached and no
population behind it.

We also already know, by measurement, what fitting geometry to a single body does to us.
Our current chamfer reference scores `crotch_height_over_stature` at the **2nd percentile**
against ANSUR — cornelis lands at p0.4, female at p1.5, male at p2.7. That is not a scan
artefact we can tune out; it is what happens when a single body's leg-to-torso split is
taken as the truth for a whole cast. One more single body will not fix it. One more single
body treated as dimensional truth would make it worse.

**We want surface detail from a scan.** Specifically the things our cage cannot currently
produce at all, measured on the delivered originals:

| landmark | measured relief on our cage | null floor |
|---|---|---|
| clavicle | absent — no signal | 4.13 mm (p99 of the relief null at S = 1.686 m) |
| iliac crest | absent | " |
| greater trochanter | absent | " |
| PSIS | absent | " |
| cervicale (C7) | absent | " |
| malleolus lateralis | −0.18 mm (flat) | " |
| patella | +8.90 mm, contrast 3.06 (below the 3.66 contrast floor) | " |

Zero of twenty body landmark probes resolve outside the cage's own relief null.

**Why detail is a far safer thing to harvest from n = 1 than proportion is.** A clavicle is
a clavicle. The ridge over the bone, the notch at the sternal end, the way the deltoid
wraps the acromion, the two bumps of the malleoli — these are species-level shapes. They
vary between people in amplitude, not in kind, and an amplitude error of 30% on a 6 mm
ridge is a 2 mm error nobody will ever see. A 30% error on crotch height is a different
human being. So: **the protocol below optimises for high-frequency surface fidelity and
explicitly discards dimensional accuracy.** `geom/scan_ingest.py` enforces that discard in
code — stage (d) low-passes the fitted displacement field and keeps only the residual, so
the scan's proportions are thrown away by construction, not by good intentions.

That is also why the achievable quality bar here is much lower than it sounds. We are not
trying to beat a 100-camera rig at building a digital double. We are trying to get a
believable clavicle.

---

## 2. Why the studios use 100+ synchronised cameras

Two reasons, and only one of them is money.

**2.1 A human cannot hold still long enough for a walkaround.** Quiet standing is not
static. Postural sway in a healthy adult standing at ease moves the centre of pressure by
roughly 5–15 mm in the antero-posterior direction over a few seconds, and the head, being
at the top of an inverted pendulum, moves considerably more than that. Breathing moves the
ribcage and shoulders on a 3–5 second cycle. A walkaround that takes 90 seconds therefore
does not photograph one body; it photographs a slowly deforming body, and the
reconstruction has to average that into one surface. The averaging shows up exactly where
we care: soft, smeared, low-contrast ridges.

A camera array fires every camera within about 1/200 s of every other camera. At that
interval the subject is, for reconstruction purposes, rigid. Every frame is a view of the
*same* geometry. That is the entire point of the array — not resolution, not coverage,
**simultaneity**.

**2.2 Cross-polarised flat lighting.** A specular highlight is not attached to the surface.
It sits where the mirror direction between light and camera happens to land, so it *slides
across the skin as the camera moves*. Feature matching — SIFT here, and everything else in
the same family — assumes that a bright patch on the skin is a fixed thing on the skin.
Speculars break that assumption, and they break it in a specific, poisonous way: they
generate strong, high-contrast, highly repeatable features that match *incorrectly* between
views. Wrong matches with high confidence are worse than no matches. They pull the bundle
adjustment off, and on shiny areas — forehead, nose bridge, collarbone, shins — they
produce a surface that is dented or blistered where the highlight travelled.

The studio fix is a polarising filter on every light, crossed with a polarising filter on
every lens. The specular reflection preserves the light's polarisation and is extinguished
by the crossed lens filter; the diffuse subsurface reflection is depolarised and passes.
What remains is pure albedo — flat, matte, view-independent, and safe to match. This is the
same trick as the flat-lighting rule in our render QC, for the same reason.

We can approximate 2.2 well. We cannot approximate 2.1 at all.

---

## 3. The achievable single-camera version

### 3.1 Frames and path

- **60–100 frames.** Below ~50 the reconstruction of the torso starts failing outright;
  above ~120 the extra frames buy little and CPU-only SIFT matching cost grows as O(n²)
  with exhaustive matching (2,556 pairs at n = 72; 4,950 at n = 100).
- **Three horizontal rings**, not one: roughly chest height, roughly knee height aimed
  slightly up, and roughly head height aimed slightly down. A single waist-height ring
  reconstructs the waist well and the top of the shoulders and the tops of the feet not at
  all — the surfaces near-parallel to every sightline never get a good ray intersection.
  ~24–30 frames per ring.
- **Angular step 5°–6°** between adjacent frames. That is the practical expression of the
  overlap rule below.
- **Constant distance** from the subject, ~2–2.5 m for a full body with a phone's main
  (not ultrawide, not tele) lens. Walk the circle; do not stand still and zoom.
- **Do not change focal length mid-capture.** Zooming makes each frame a different camera.
  COLMAP can be told to solve per-image intrinsics, but with n = 1 subject and no
  calibration target that is a lot of extra unknowns for no benefit. Lock zoom, and if the
  phone lets you, lock focus and exposure too.

### 3.2 Overlap

Every point on the body must be clearly visible in **at least 4, preferably 6+** frames,
and adjacent frames must share **≥ 70%** of their content. The 4-view minimum is not
arbitrary: a 3D point triangulated from 2 views has no redundancy at all and no way to
detect a bad match; from 4+ views a wrong match becomes an outlier the bundle adjustment
can reject. `geom/scan_ingest.py` filters reconstructed points by track length for exactly
this reason and reports the distribution.

### 3.3 Light

- **Flat, indirect, and identical in every frame.** Overcast daylight outdoors, or a large
  room with bounced light and no direct sun patch. Open shade next to a building is good.
- **No on-camera flash, ever.** A flash is a moving light: it travels with the camera, so
  the shading on the body changes in every single frame. That is the *opposite* of what
  reconstruction wants.
- **No hard shadow edges.** A hard shadow boundary is a high-contrast edge that is fixed
  relative to the light, not the body — but since the light and body are both fixed here,
  a hard shadow is survivable in a way a flash is not. It still costs detail inside the
  shadow, where there is no signal to match. Prefer soft.
- **Kill the speculars.** Without cross-polarisation the fallback is to remove the source
  of shine: matte the skin (translucent powder), and capture in diffuse light where there
  is no small bright source to reflect. A linear polariser held over the phone lens
  removes *some* specular from a partly polarised sky or window source; it is a partial
  measure, not the studio trick, because the light itself is unpolarised.
- **Do not let the light change during the capture.** Sun coming out halfway through a
  90-second walkaround is a failed capture. Re-shoot it.

### 3.4 Subject

- Stand as still as possible, weight even on both feet, arms held clear of the torso (~30°
  abduction) so the armpit and the side of the ribcage are actually visible. A relaxed
  arms-down pose hides the exact region we most want.
- Breathe shallowly and evenly. Do not hold your breath — holding it forces a bigger
  compensating breath and a bigger movement.
- Eyes on a fixed point. Head movement is the largest single sway contributor.
- Somebody else takes the photographs. A self-timer walkaround is not a thing.

### 3.5 Background

- **Plain, matte, and non-repeating.** Repeating texture — brick, tiles, slatted fence,
  patterned carpet, a bookshelf of identical spines — is the classic photogrammetry
  poison: it produces confident matches between *different* physical points, and the
  reconstruction folds.
- Some background texture is actively useful, because it is the static part of the scene
  that stabilises the camera poses. A featureless white cyclorama is bad for a walkaround.
  A plain wall with visible surface texture, a room with furniture, or a park is fine.
- Nothing in the background may move. No people walking, no leaves in wind if avoidable.

### 3.6 Clothing and hair — what they do to a scan

This is the part that is usually undersold, so plainly:

- **Hair does not reconstruct.** Fine strands are thinner than the effective resolution,
  they are semi-transparent, and they self-occlude. What comes back is a lumpy, holed blob
  where the hair was. Tie it back, cover it (a plain matte cap), and expect the scalp
  region to be unusable regardless.
- **Loose clothing reconstructs as clothing**, and it also *moves* between frames, which
  costs you the underlying body's shape twice over. Close-fitting matte garments are the
  only usable option; even those add 1–3 mm and smooth out exactly the ridges we came for.
- **Anything shiny fails** — synthetics with a sheen, lycra, patent, jewellery, glasses,
  watch faces. Remove or matte them.
- **Plain black and plain white both fail**, for opposite reasons. Black clips to noise and
  yields no features; white blows out and yields no features. Mid-tone with visible weave
  or print texture is the best case.
- **The regions we most want are the ones clothing covers.** Clavicle, acromion, scapula,
  iliac crest, PSIS, greater trochanter, cervicale. There is no way around this: either
  those regions are exposed at capture time, with all the consent implications in §5, or
  the scan cannot contribute detail there, and the honest thing is to say so and use the
  scan only for the regions it did cover — knee, malleoli, elbow, hand, foot, face. That
  is still worth doing.

### 3.7 Scale — the one thing you must record by hand

**Photogrammetry cannot recover scale.** Structure-from-motion reconstructs the scene up to
an unknown *similarity* transform: a body twice as large photographed from twice as far
produces pixel-identical images. There is no information in the photographs from which the
size can be deduced.

So record it separately, at capture time:

- **Measure and write down the subject's standing stature in metres**, barefoot, heels
  together, at a stated time of day. (Diurnal stature variation in one person is 14.4–19.3
  mm, so the time of day is part of the measurement, not trivia.) **And/or**
- **Put a rigid ruler or a printed scale bar of known length in the scene**, visible in
  several frames, lying flat and not moving.

`geom/scan_ingest.py` **refuses to run without an explicit scale declaration.** It will not
guess, and it will not fall back to "whatever makes it match our cage". A silently
mis-scaled scan corrupts every measurement downstream of it, and mis-scaling is invisible
— the mesh looks perfect.

---

## 4. What this will and will not produce

**Will, on a good capture:**

- A recoverable set of camera poses and a sparse point cloud (thousands of points).
- Recognisable gross body shape.
- Usable mid-frequency surface information on large, matte, well-lit, well-covered,
  non-deforming regions: the front of the shin, the knee, the outside of the thigh, the
  back of the calf, the forearm, the top of the foot, the malleoli.
- Enough for stage (d) of the ingest to extract a high-frequency residual over those
  regions.

**Will not, ever, from this setup:**

- Pore-level or wrinkle-level detail. That needs cross-polarised multi-flash and a lens
  resolving well under a millimetre on the subject.
- Usable hair, eyes, eyelashes, eyebrows, nostrils, ear canals, or the inside of any
  concavity.
- Anything under clothing.
- Reliable geometry on the armpit, perineum, between the fingers, or under the chin —
  concave, self-occluded, poorly lit.
- **Dimensional accuracy.** Even with a perfect scale bar the sway in §2.1 is a
  centimetre-class error on a walkaround, and we discard proportions anyway.
- A watertight mesh straight out of the box. Expect holes at every occluded region; Poisson
  reconstruction will close them with invented surface, and invented surface must not be
  mistaken for measurement. The ingest tags Poisson-filled regions by point support.

**Failure modes, plainly:**

| symptom | cause |
|---|---|
| SfM registers only a fraction of the images, or splits into two disconnected models | too few frames, too large an angular step, or a featureless background |
| the body "folds" — two different parts of the body reconstruct on top of each other | repeating background texture, or a symmetric featureless garment |
| the surface is dented or blistered on the forehead, nose, collarbone, shins | speculars — no cross-polarisation, or a flash was used |
| the whole surface is soft and no ridge resolves | subject sway and breathing over the capture duration; unfixable in post |
| the reconstruction is smooth and clean but every dimension is wrong | scale not recorded; nobody noticed because it looks right |
| large holes at the shoulders and the tops of the feet | single-ring capture, no high or low ring |
| the scan is beautiful and the residual is empty | the detail was there but at a wavelength shorter than the cage can carry — see the Nyquist note in `geom/scan_ingest.py`, and raise the subdivision level rather than the amplitude |

Do not oversell a result from this protocol. A single-camera walkaround is a way to get a
*plausible clavicle ridge*, not a digital double.

---

## 5. Consent and rights — non-negotiable

A scan of a real person **is that person's likeness**. It is not "just geometry", and the
fact that it arrives as a point cloud changes nothing about the rights in it.

Requirements before any photograph is taken:

1. **Explicit, written, informed permission from the subject**, naming: that they are being
   3D-scanned; that the result will be used to build character geometry; that the resulting
   characters will be **published commercially**; and whether the result may be used to
   build a character that is *recognisably them* or only as anonymous surface detail. Those
   are two different permissions and this pipeline uses the second one.
2. **A named subject and a dated signature.** An informal "yeah, go ahead" is not a
   commercial licence.
3. **A stated scope and a stated term.** Perpetual, worldwide, all-media if that is what is
   needed — say so in the document rather than assuming it.
4. **If the subject is a minor**, permission comes from a parent or legal guardian, in
   writing, and the same restriction as above about recognisability applies with less
   latitude, not more.
5. **The permission record goes in `PROVENANCE.json`**, in the scan's output directory,
   in exactly the same shape as every other external asset licence in this repo
   (`data/assets/anthro_reference/PROVENANCE.json`, `data/assets/detectors/PROVENANCE.json`
   are the two reference examples). Fields: what the asset is, who the subject is, the
   licence granted, and **licence evidence** — a pointer to the signed document and the
   exact granting sentence quoted. `geom/scan_ingest.py` refuses to run without a consent
   record and writes it into the output `PROVENANCE.json`.

   **What the gate actually checks** (`_validate_consent`), because until 2026-08-08 it
   checked almost nothing — `str(None)` is the truthy string `'None'`, so a record whose
   every field was `null` was accepted and written into `PROVENANCE.json` as
   `licence: null` beside `is_a_likeness: true`, which reads downstream like a validated
   grant. Now: `subject`, `granted_by`, `date`, `licence`, `licence_evidence` and
   `document` must each be a non-empty **string** of at least 3 characters — not `null`,
   not a number, not a bool; `recognisable_likeness_permitted` must be a real JSON
   `true`/`false`; and `licence_evidence` must carry a **locator or a quotation** (a URL, a
   path to the signed document, or the wording of the grant in quotes), not just a licence
   name. Nine deliberately empty or malformed records are exercised on every self-test run
   and all nine must be refused (`selftest_report.json` -> `consent_gate_check`).

The house rule for external assets applies here without exception: *commercial publication
requires Apache-2.0 / MIT / BSD / CC0 / public-domain, with licence evidence.* A likeness
is not one of those by default. It becomes usable only through a specific written grant,
and that grant is the evidence.

**Do not scan a person who has not signed.** Do not scan from photographs you did not
take. Do not use images scraped from anywhere. There is no version of "we will sort the
paperwork out later" that survives a commercial release.

---

## 6. Checklist

- [ ] Signed consent in hand, scoped for commercial use, recorded for `PROVENANCE.json`
- [ ] Stature measured and written down, with time of day — **and/or** scale bar in frame
- [ ] Flat indirect light, unchanging, no flash
- [ ] Skin mattified; jewellery, glasses, watch removed
- [ ] Hair tied back or capped
- [ ] Close-fitting mid-tone matte clothing, or the region of interest exposed per consent
- [ ] Plain non-repeating background, nothing in it moving
- [ ] Zoom / focus / exposure locked
- [ ] Second person operating the camera
- [ ] Three rings — knee, chest, head height — 24–30 frames each, 5°–6° apart
- [ ] Subject arms ~30° out, weight even, eyes fixed, breathing shallow
- [ ] Total capture under 2 minutes; re-shoot rather than resume
