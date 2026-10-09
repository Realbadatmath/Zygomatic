<!--
SPDX-FileCopyrightText: 2026 Zygomatic

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# geom.anthro

Measures generated parametric human meshes against real anthropometric distributions and
gates them.

There is no measurable "perfect" proportion, and this package does not look for one. It
answers a different, answerable question: **how unusual is this body, against which
population, on which measurement convention** — and it makes any deliberate departure
visible as a number (the *stylization delta*) instead of letting it drift in unrecorded.

```
python -m geom.anthro check <character|all>          run the gates, print the report, write JSON
python -m geom.anthro measure <character>            the measurement table with its conventions
python -m geom.anthro reference <ratio> [--sex S]    one band, with its provenance
python -m geom.anthro build-pack                     re-run the reference builder
python -m geom.anthro selftest [--character NAME]    exercise the whole stack
python -m geom.anthro list                           characters this CLI can see
```

Exit codes: **0** pass, **1** pass-with-warnings, **2** fail, **3** internal error.
`1` is deliberately distinct from `0`: a body that clears every band while sitting at p93
on nine ratios is a recorded stylization decision, and a build system has to be able to
tell that apart from "nothing to see here".

A **usage** error (bad flag, unknown character, unknown ancestry) is exit **3**, never 2 —
2 means the *body* failed its gates, and a typo must not be reported as that.

Shared flags — accepted **either side** of the subcommand: `--ancestry`, `--width`
(`p1p99 p5p95 p25p75 sd1 sd2 sd3`), `--columns`, `--out`.

`--ancestry` is validated once, up front, against the pack. An unknown group and a group
that exists but sits below the `n >= 100` floor both fail loudly with the real `n`:

```
$ python -m geom.anthro check female --ancestry asian
ancestry 'asian' exists in ANSUR II for female but only n=71, below the n>=100 floor,
so no band was built. Do not substitute pooled silently — decide explicitly.        (exit 3)
```

---

## 1. Modules

| module | owns |
|---|---|
| `build_reference.py` | builds the reference pack from the primary microdata |
| `reference.py` | runtime reader for the pack (`AnthroReference`, `reference()`) |
| `landmarks.py` | resolves landmarks on the anny cage from MakeHuman morph supports |
| `measure.py` | every measurement the cage can honestly produce, with its convention |
| `integrity.py` | mesh integrity: watertight, manifold, winding, self-intersection, mirror |
| `gates.py` | the gate registry and its thresholds |
| `report.py` | rendering: text report, JSON artifact, log line, percentile strip |
| `__main__.py` | the CLI |

`geom/anthro/__init__.py` exports lazily. Importing `measure` pulls in anny, torch and a
CUDA context; a caller that only wants a band out of the pack must not pay for that.
`from geom.anthro import measure_mesh` still works — the module loads at attribute access.

---

## 2. The reference pack

Built once into `data/assets/anthro_reference/`, read at runtime through
`reference.AnthroReference`. `schema_version = 1`.

```
data/assets/anthro_reference/
  reference.json      the distributions, the ratio specs, the policy blocks
  mahalanobis.npz     per-subject ratio vectors + the stored joint model
  PROVENANCE.json     per-source citation, licence, retrieval date, known gaps
  source/             the primary microdata the build consumed
```

### 2.1 `reference.json`

| key | contents |
|---|---|
| `schema_version` | `1`. `reference.py` refuses any other value rather than guessing. |
| `ratios` | 49 ratio specs: `kind`, `numerator`, `denominator`, `scale`, `iso_class`, `units`, `definition`. The `definition` string carries the landmark **and** the definition trap where one exists. |
| `dimensions` | 40 raw dimensions behind those ratios. |
| `stats[sex][group][ratio]` | `mean`, `sd`, `cv`, `min`, `max`, `n`, `p1/p5/p25/p50/p75/p95/p99`, and `q` — a 101-point percentile grid. Percentiles are interpolated inside `q`, so they are *empirical*, not gaussian. |
| `predictability[dimension]` | `r`, `rmse_mm`, `policy` (`tight`/`wide`), `iso_class`. `r` is the **worse** of the two sexes and `rmse_mm` the larger, so the policy is never softer than the data supports for either. |
| `predictability_policy` | the cut (`tight iff r >= 0.80 AND residual rmse <= 30 mm`), its provenance, and its consequence. |
| `mahalanobis` | `order` (the 10-component frame vector), per-sex `mean`, empirical `d2` thresholds, `chi2_reference`, `cov_condition_number`, `independent_bands_check`. |
| `cdc_lms` | CDC 2000 stature-for-age and BMI-for-age LMS, ages 24–240 months. |
| `coverage` | `ansur_age_years [17, 58]`, `ansur_population "US Army 2010-2012"`, `cdc_age_months [24, 240]`. |
| `conventions` | girth convention, definition traps, symmetry's two distinct checks, and `not_shipped_because_contested`. |
| `gaps` | what the pack does **not** cover, in its own words. Read this before gating anything. |
| `dropped_groups` / `min_group_n` | ancestry groups below the `n >= 100` floor, with their real `n`. |
| `iso_20685_1_table4_mm` | the ISO table, mirrored so `measure.py` and the gates cannot drift apart. |

### 2.2 Populations actually shipped

ANSUR II 2012 working database, public release. US Army personnel stratified to the Total
Army DMDC census of 2011‑09‑30, measured 2010‑10 … 2012‑04, ages 17–58. **Not a civilian
population.** Public domain (US Government work, 17 USC 105).

* male: `pooled` (n=4082), `white`, `black`, `hispanic`, `asian`
* female: `pooled` (n=1986), `white`, `black`, `hispanic`

Dropped below the `n >= 100` floor, and named rather than silently pooled: male
`native_american` (n=29), `pacific_islander` (n=34), `other` (n=3); female `asian` (n=71),
`native_american` (n=20), `pacific_islander` (n=25).

**The female `asian` band does not exist while the male one does.** An ancestry-aware gate
must handle that asymmetry explicitly. `reference.band()` raises with the real `n` rather
than falling back to pooled, because a typo'd ancestry quietly becoming pooled is exactly
the bias the pack exists to prevent.

### 2.3 Why the joint gate is primary

Ten independent p5–p95 bands each *claim* to admit 90%. Measured on the real male sample,
**all ten together admit 0.4716** — against 0.3487 if they were independent, and against
the 0.9 each one nominally claims. Independent per-ratio bands are therefore both too
strict in aggregate *and* blind to combinations that never co-occur.

The primary plausibility check is Mahalanobis D² on the 10-component frame vector
(cervicale, acromial, iliocristale, crotch, tibiale, sitting height, biacromial,
bicristal, acromion-radiale, radiale-stylion — all over stature). Its thresholds are the
**empirical** percentiles of D² in the real sample, not χ². On this data χ²(df=10, .95) =
18.307 actually passes 0.9358 of real people, not 0.95 — the χ² number is stored for
comparison only.

The vector **excludes girths on purpose**: adult ageing is a girth delta on an unchanged
skeleton, so a girth-carrying frame model would reject a correctly-aged character.

`mahalanobis()` accepts any subset of the ten and builds the exact marginal for that
subset (sub-mean and **sub-covariance**, not dropped columns of the inverse).

---

## 3. Measurement conventions

Every stored measurement carries **landmark + convention + population + date**. A consumer
that cannot state all four for its own number cannot legitimately compare it to these
bands. Definition traps cause more error in practice than any tolerance does.

### 3.1 Girths — plane slice + convex hull

ANSUR II circumferences are taut-tape measurements on live subjects. We reproduce that as
a horizontal **plane slice** at the landmark height, then the **convex hull perimeter** of
the intersection contour — the method used by SHAPY, A2B and CALVIS and implied by
**ISO 18825-2**. Limb girths are taken **perpendicular to the limb axis** (ISO 18825-2);
every limb site *also* reports the horizontal value, because ANSUR tapes thigh and calf
horizontally and the two are not the same number.

`hull >= true contour >= inscribed polyline`.

MakeHuman/anny's own `Ruler.getMeasure` sums straight chords along a vertex ring — an
inscribed polyline. `measure.py` measured the gap on this cage directly: the polyline is
longer than the taut-tape hull at 124 of 125 site-character combinations, by 5.0–226.4 mm
(mean 65.8), because the ring undulates 8.2–40.2 mm out of plane and the chord sum charges
for the undulation. **Polyline girths must never be compared to the pack's circumference
bands.** `compare_conventions()` quantifies all three per site.

### 3.2 Definition traps encoded in the pack

* **waist** — ANSUR II = omphalion (navel). WHO = midpoint between lowest rib and iliac
  crest. NIH/NHANES = iliac crest. The WHO and NIH sites differ by up to **10.1 cm** in
  women. A "waist" number without its site is not a measurement.
* **leg length** — at least four incompatible definitions: crotch height, trochanterion
  height, iliocristale height, subischial (stature − sitting height).
* **shoulder width** — biacromial breadth (skeletal), bideltoid breadth (soft tissue) and
  shoulder circumference are three different quantities sharing one colloquial name.
* **head dimensions** — ANSUR measures over hair; this cage is bald.

### 3.3 ISO 20685-1:2018 Table 4

| class | mm | class | mm |
|---|---|---|---|
| height | 4 | circumference, large | 9 |
| segment length | 5 | circumference, small | 4 |
| breadth | 4 | head (without hair) | 1 |
| depth | 5 | head (with hair) | 2 |
| hand | 1 | foot | 2 |

**These bound a MEAN difference across a validation sample, not a per-mesh error.** Using
them per-mesh is **HOUSE policy and is labelled as such** everywhere it appears; it is not
ISO conformance. And a per-mesh 4 mm "anthropometric accuracy" claim would be meaningless
anyway: diurnal stature variation in a real person is **14.4–19.3 mm**. "Within ±2 mm of a
**declared build target**" is a different statement, is reproducible, and is valid.

### 3.4 Heights tight, breadths wide

Stature predicts landmark heights almost deterministically and breadths barely at all:

Read out of the shipped pack (worse sex, larger RMSE):

| dimension | r | residual RMSE | policy |
|---|---|---|---|
| cervicale height | 0.9841 | 11.23 mm | tight |
| acromial height | 0.9669 | 16.16 mm | tight |
| crotch height | 0.8491 | 23.87 mm | tight |
| biacromial breadth | 0.5317 | 16.23 mm | wide |
| bideltoid breadth | 0.3129 | 30.87 mm | wide |
| waist circumference (omphalion) | 0.2079 | 109.25 mm | wide |

A `tight` dimension may be gated around its stature-predicted value with half-width
`2*rmse`. A `wide` dimension must be gated against the **population band for its group**
and **never against a stature-derived point**. Query it with
`reference().predictability(dimension)`.

### 3.5 Symmetry — two checks, never merged

* **morph-space symmetry**: a mesh built from a symmetric morph space should be
  *near*-zero asymmetric, so any material deviation is a broken morph — but the gate is
  **not** at floating-point tolerance and must not be. The shipped tolerance is
  `integrity.SYM_MORPH_TOL_MM = 0.15 mm`, and it is set by the vendor data, not by
  float64: **anny's own local-morph target tables are not bit-mirror-symmetric**.
  Measured over six bodies with the sculpt layer off — stock male/female 0.0167 mm,
  female original 0.0014, abel 0.0229, cornelis 0.0600, male original **0.0632 mm** — the
  floor is 0.0632 mm and it rises with the number of fitted `measure-*` locals applied.
  0.15 mm clears that floor with ~2.4× headroom while still catching the asymmetric
  sculpt that motivated the gate (2.93–3.76 mm) by ~25×. Gating at float ε would fail
  **4 of 4** issued bodies for a defect none of them has.
* **realism-injected asymmetry**: a separate, deliberate 0–10 mm band (population mean
  5.2 mm).

Conflating them turns "your morph pipeline is broken" into "this body looks natural".

> **Corrected 2026-08-05.** This section previously said "expected asymmetry is *exactly*
> zero … gate at floating-point tolerance", which was the pre-fix intent from when the
> tolerance was 0.05 mm and the `abs_definition` sculpt was still asymmetric. A reader
> following it would have filed the male original's 0.0632 mm as a broken morph needing
> investigation, when 0.0632 mm **is** the vendor-data floor the tolerance was widened to
> accommodate. The single authority for the number is `integrity.SYM_MORPH_TOL_MM`.

---

## 4. The report

`report.py` reads the gate output **as data** and renders it three ways.

### 4.1 The gate-report contract

`report.py` reads the gate output as **data** and requires none of it. Accepted shapes:

```python
{'tiers': {tier: [gate, …]}}   {'tiers': [{'tier':…, 'gates':[…]}]}   {'gates': [gate, …]}
{'results': […]}               [gate, …]                              a lone gate dict
gate = {'id', 'tier', 'severity', 'status', 'observed', 'band', 'source', 'explanation'}
```

Field aliases are accepted so the renderer and the engine can be written in parallel:
`explanation` ← `explain`/`why`/`message`/`note`/`detail`;
`source` ← `threshold_source` (preferred — it cites the *number*) then `source` (which
describes the *run*); provenance class ← `threshold_provenance`/`provenance_class`/
`provenance`, or the leading word of the source string.

`band` may be `(lo,hi)`, `[lo,hi]`, `{'lo','hi'}`, `{'min','max'}`, one-sided, or prose.
`observed` may be a number, `{'value','units'}`, a diagnostic dict (rendered `{n fields}`
— a JSON fragment chopped mid-key looks like a value and is not one), or prose. `status`
accepts the spellings below plus `True`/`False`.

A field that is **present and `None`** renders `none declared`; a field that is **absent**
renders `unknown`. Those are different facts and only the second is a gap.

`contract_fixture()` returns a gate report in this shape including the awkward rows
(absent status, unrecognised severity, malformed entry, one-sided band, CONTESTED gate,
gate with no provenance). It is a **shape test, not a measurement**: it carries
`synthetic: true` and every rendering of it prints a banner saying so. It is what the CLI
falls back to *only* when `gates.py` does not exist; if `gates.py` exists but cannot be
called that is exit 3, never a fixture.

### 4.2 HOUSE arithmetic (this renderer's only policy)

Statuses collapse into six buckets — `PASS`, `warn`, `fail`, `skip` (not run), `report`
(informational), `unknown`:

* **A missing field is never a pass.** An *absent* status → `unknown`, which counts
  towards the warning total.
* **An explicitly declared non-verdict is not an omission.** `unmeasurable`,
  `not_applicable`, `not_implementable`, `refused` → `skip`. The gate author said no
  judgement was possible and said why; that is information, and it does not raise a
  warning by itself.
* **…unless it was a blocking gate.** A `skip` at `block` severity is **escalated** to a
  warning — a blocking check that did not run has not passed. The escalation is printed.
* **An unrecognised severity is fatal, not minor.** A failure is downgraded to a warning
  only on a recognised low severity (`minor, advisory, info, informational, note,
  cosmetic, low, warn, warning, report`); high is (`critical, blocker, fatal, major, high,
  severe, error, block, blocking`). Every downgrade is printed on its own line.
* Any failing gate at high or unrecognised severity → `FAIL`. Otherwise any warning,
  unknown status, or policy alarm → `PASS-WITH-WARNINGS`. Otherwise `PASS`.

### 4.3 Policy alarms — defects in the registry, not in the body

Raised, printed loudly, and carried into the JSON:

| alarm | meaning |
|---|---|
| `contested_threshold_shipped` | a gate declares CONTESTED provenance. It must not ship. |
| `undeclared_provenance` | a gate ships a **threshold** with no declared claim class. A report-only gate declaring neither threshold nor band is exempt — there is no number to attribute — and those are named in the footer instead. |
| `unrecognised_severity` | severity not in the vocabulary; treated as HIGH. |
| `malformed_gate` | an entry that could not be read as a mapping; counted `unknown`. |
| `age_outside_reference_population` | the subject's age is outside ANSUR's 17–58. |
| `verdict_disagreement` | the engine's own verdict and this renderer's recomputation of it from the rows disagree. Cheapest available check that the two have not drifted. |

### 4.4 The percentile strip

Every measured ratio, **passing or not**, with its value, its empirical percentile, its
band, and the signed distance to the nearer band edge in the ratio's own units *and* in
millimetres of this subject's own stature.

```
crotch_height_over_stature      0.4407  p 0.4 #.[-------------:--------------]..   -0.0184   -33.1 pooled
```

`[` `]` band edges · `:` median · `#` this body · `{` `}` this body **on** a band edge
(one cell is ~3 percentile points, so the marker would otherwise erase the edge) ·
`<` `>` outside the sampled range entirely · `p0!`/`p100!` the same fact in the number
column.

Flags: `conv` = this mesh measurement is not on the survey's convention, so its percentile
compares two different definitions and is indicative only (the reason is printed in full
underneath). `pooled` = no ancestry declared.

The strip exists because printing only the failures **hides the shape of the body**. Nine
ratios all sitting at p93 is a house style, and it is invisible in a pass/fail list.

### 4.5 The JSON artifact

Written atomically (tmp + `fsync` + `os.replace` + directory `fsync`) to
`data/assets/anthro_reports/<character>.json`. Keys sorted. All clock-dependent fields are
isolated in `volatile`, and `stable_sha256` is taken over the document **without**
`volatile` and without itself — so two runs of the same mesh against the same pack produce
the same digest and a report diffs for real change rather than for the time of day.

### 4.6 The log line

```
anthro char=abel verdict=FAIL exit=2 gates=11 pass=4 warn=3 fail=2 unknown=2 skip=0
ratios=34 banded=34 outside=10 sex=male ancestry=undeclared width=p5p95
stature_m=1.5200 worst=… alarms=… SYNTHETIC=1 sha=fb017cdccac8
```

One line, `key=value`, no separators a log parser has to escape.

---

## 5. The gate registry

Owned by `gates.py` (`GATES`, schema `geom.anthro.gates/1`). **36 gates** over four tiers,
each carrying a DECLARED `severity` ∈ `block | warn | report` and a
`threshold_provenance` ∈ `MEASURED | HOUSE`. `validate_registry()` refuses to run a
registry containing an untagged or CONTESTED threshold, so `CONTESTED` cannot reach a
report through the normal path — `report.py` alarms on it anyway, because a renderer
that trusts its input is not a check.

> **Everything from here to the end of §5 is GENERATED, not written.** Regenerate it
> after any registry change instead of editing it — a census maintained by hand goes
> stale silently, and this one had (it said 34 gates and "block 23" while the registry
> held 36 and only 19 of them could actually block):
>
> ```
> python3 -m geom.anthro.gates --severity-table          # the same data as text
> python3 -c "import geom.anthro.gates as g; g.severity_table()"   # as a dict
> ```

Census, read from `gates.severity_table()` on 2026-08-05:

* **36 gates** — tier 1 = 16, tier 2 = 10, tier 3 = 5, tier 4 = 5
* **declared** severity: block 24, warn 8, report 4
* **effective** severity after calibration: block 19, warn 13, report 4 — **5 gates are downgraded**, i.e. the
  registry asks them to block and the measurement takes that away.
* threshold provenance: HOUSE 21, MEASURED 12, no-threshold 3

**Declared is not effective.** Severity is calibrated, not asserted: a gate may carry severity 'block' only if, run as configured, it would reject at most 1.0% of the real ANSUR II reference sample (plus 1/n, the granularity of an empirical percentile on that sample). Otherwise it is downgraded to 'warn'. Structural gates — cage integrity, landmark ordering, morph bounds, the build-target stature check, provenance, and bands the CALLER declared — are not statistical statements about a population and keep their declared severity.
The `rejects` column is that measurement. `*n/a*` means the gate is structural — cage
integrity, landmark ordering, morph bounds, a caller-declared band — so there is no
population rejection rate to compute and it keeps its declared severity.

| gate | tier | declared | effective | threshold provenance | rejects |
|---|---|---|---|---|---|
| `t1_topology_identity` | 1 | block | block | MEASURED | *n/a* |
| `t1_watertight` | 1 | block | block | HOUSE | *n/a* |
| `t1_edge_manifold` | 1 | block | block | HOUSE | *n/a* |
| `t1_vertex_manifold` | 1 | block | block | HOUSE | *n/a* |
| `t1_winding_consistent` | 1 | block | block | HOUSE | *n/a* |
| `t1_outward_normals` | 1 | block | block | HOUSE | *n/a* |
| `t1_degenerate_geometry` | 1 | block | block | HOUSE | *n/a* |
| `t1_self_intersection` | 1 | block | block | HOUSE | *n/a* |
| `t1_self_intersection_locality` | 1 | report | report | *(no threshold)* | *n/a* |
| `t1_shell_containment` | 1 | block | block | HOUSE | *n/a* |
| `t1_euler_genus` | 1 | report | report | *(no threshold)* | *n/a* |
| `t1_build_target_stature` | 1 | block | block | HOUSE | *n/a* |
| `t1_morph_bounds` | 1 | block | block | HOUSE | *n/a* |
| `t1_landmark_ordering_hard` | 1 | block | block | MEASURED | 0.000% |
| `t1_landmark_ordering_soft` | 1 | warn | warn | MEASURED | 45.835% |
| `t1_girth_chain` | 1 | block | block | MEASURED | 0.000% |
| `t2_mahalanobis` | 2 | block | **warn** ⤓ | MEASURED | 1.176% |
| `t2_heights_tight` | 2 | block | **warn** ⤓ | HOUSE | 23.003% |
| `t2_breadths_wide` | 2 | block | **warn** ⤓ | MEASURED | 8.547% |
| `t2_girths_wide` | 2 | block | **warn** ⤓ | MEASURED | 12.821% |
| `t2_ancestry_leg` | 2 | warn | warn | MEASURED | 3.419% |
| `t2_ancestry_cormic` | 2 | warn | warn | MEASURED | 3.419% |
| `t2_child_growth` | 2 | block | block | HOUSE | 0.270% |
| `t2_child_proportions` | 2 | warn | warn | HOUSE | *n/a* |
| `t2_adult_age_channel` | 2 | warn | warn | MEASURED | 9.402% |
| `t2_vhi_bmi` | 2 | block | block | HOUSE | *n/a* |
| `t3_depths_wide` | 3 | block | **warn** ⤓ | MEASURED | 5.983% |
| `t3_morph_symmetry` | 3 | block | block | HOUSE | *n/a* |
| `t3_realism_asymmetry` | 3 | warn | warn | HOUSE | *n/a* |
| `t3_spine_curvature` | 3 | report | report | *(no threshold)* | *n/a* |
| `t3_cast_diversity` | 3 | warn | warn | MEASURED | 1.000% |
| `t4_measurement_provenance` | 4 | block | block | HOUSE | *n/a* |
| `t4_threshold_provenance` | 4 | block | block | HOUSE | *n/a* |
| `t4_stylization_axis` | 4 | warn | warn | HOUSE | *n/a* |
| `t4_canon_and_percentiles` | 4 | report | report | HOUSE | *n/a* |
| `t4_tolerance_sanity` | 4 | block | block | HOUSE | *n/a* |

⤓ = the declared severity was **taken away by measurement**:

* `t2_mahalanobis` — rejects 1.18% of the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y), 1.2x the 1.0% ceiling (bar as applied, including the 1/n granularity of the governing cell: 1.024%). A gate stricter than the population is a gate that rejects people who exist.
* `t2_heights_tight` — rejects 23.00% of the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y), 23.0x the 1.0% ceiling (bar as applied, including the 1/n granularity of the governing cell: 1.024%). A gate stricter than the population is a gate that rejects people who exist.
* `t2_breadths_wide` — rejects 8.55% of the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y), 8.5x the 1.0% ceiling (bar as applied, including the 1/n granularity of the governing cell: 1.855%). A gate stricter than the population is a gate that rejects people who exist.
* `t2_girths_wide` — rejects 12.82% of the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y), 12.8x the 1.0% ceiling (bar as applied, including the 1/n granularity of the governing cell: 1.855%). A gate stricter than the population is a gate that rejects people who exist.
* `t3_depths_wide` — rejects 5.98% of the real ANSUR II sample (US Army, male n=4082, female n=1986, 17-58 y), 6.0x the 1.0% ceiling (bar as applied, including the 1/n granularity of the governing cell: 1.855%). A gate stricter than the population is a gate that rejects people who exist.

The per-gate threshold *values* and their citations live in `gates.py` and are printed
in full by `check`'s PROVENANCE footer for whichever gates actually ran. This table is
a census, not a substitute for reading them.

---

## 6. The three claim classes

Every threshold anywhere in this package carries exactly one.

| class | means | must carry |
|---|---|---|
| **MEASURED** | read off a named dataset | source, population, n, date |
| **HOUSE** | our own policy | a rationale, and never presented as a measurement |
| **CONTESTED** | the literature does not support it | **do not ship these at all** |

CONTESTED is in the vocabulary *so that a contested number can be named and alarmed on* —
never as a licence to use one. A gate declaring it triggers
`contested_threshold_shipped`.

`measure.py` adds two record-level classes for values that are not thresholds:
`UNMEASURABLE` (this cage or this pose cannot produce it) and `REFUSED` (measurable in
principle, not on this mesh — always with a reason). Neither is ever silently omitted.

---

## 7. Numbers we deliberately did NOT encode

Every item below was checked and rejected. They are listed here so nobody re-adds them.

* **Golden ratio (1.618) in body proportion.** Read out of the shipped pack:
  `1 / mean(omphalion-height / stature)` = **1.6627** male pooled, **1.6619** female
  pooled (ANSUR II, n=4082 / 1986). The empirical attractor is nearer **5/3 = 1.6667**
  than φ = 1.6180, and the gap to φ is ~4.5 mm/m either way. Not a target.
* **Waist–hip ratio 0.7 as an ideal.** Read out of the shipped pack: the **minimum** WHR
  across all **1986** ANSUR II women is **0.7006**, p1 = **0.7232**, mean = **0.8418**.
  0.70 therefore describes *no woman in the sample at all*. The pack ships the WHR
  *distribution*; it does not ship the ideal.
* **"Adonis index" 1.618 shoulder-to-waist.** No primary source. The commonly cited 2023
  IJSM study **does not exist**. `shoulder_waist_circumference` is reported as a measured
  distribution position only.
* **Symmetry as beauty.** Effect is near zero after publication-bias correction. The two
  symmetry checks we *do* run are geometric integrity checks (§3.5), not aesthetics.
* **Drillis & Contini segment constants.** Small convenience sample, superseded by the
  microdata in this pack.
* **The nth-percentile person.** Does not exist. A p95-stature man averages about **p62**
  waist and **p53** head breadth. Never assemble a body by stacking one percentile.
* **A single-population leg gate.** Ancestry is the largest proportion effect found:
  crotch-height/stature in males runs **.4951** Black (n=642) / **.4794** White (n=2817) /
  **.4787** Hispanic (n=440) / **.4711** Asian (n=117). That .0240 spread is **44.3 mm of
  leg on a 1.85 m man** — 11× the ISO height tolerance. A pooled band used as a universal
  gate encodes a bias, not a tolerance, and the report says so on every pooled row.
  These are **per-subject** ratio means, read straight out of
  `reference.json → stats.male.<group>.crotch_height_over_stature.mean`, which is the
  statistic every band, percentile and gate in this package is built on. *(Corrected
  2026-08-05: the four figures printed here to 4 dp used to be .4952/.4796/.4788/.4712,
  which are the **ratio of the two column means** — a different estimator that appears
  nowhere in the pipeline. §10 makes exactly this distinction for
  `shoulder_hip_skeletal` and gets it right, so quote the pack, never a recomputation.)*
* **A per-mesh ISO 20685-1 accuracy claim.** See §3.3.
* **Shoulder:hip as a child/adult discriminator.** Not encoded, and the briefing's numbers
  for it did **not** reproduce here — see §10.
* **Scaling an adult mesh down to make a child.** Wrong in three known ways at once — see
  §8.

---

## 8. Known gaps — read before gating

* **Children and adolescents.** ANSUR II is 17–58. **No ratio band in this pack applies to
  a child.** A 12-year-old's cormic index (~.507) is *lower* than an adult's (~.523), so
  legs are proportionally **longer**; head length is ~**96%** of adult at ~**85%** of
  adult stature; growth is distal-to-proximal so hands and feet are proportionally
  **large**. All three read as failures against an adult band and all three are correct
  anatomy. CDC LMS stature-for-age and BMI-for-age (24–240 months) *do* apply — but they
  constrain **size, not proportion**. The report raises
  `age_outside_reference_population` and repeats the caveat above the strip.
* **Adult ageing** is not modelled as a trajectory. Its shape is a **girth delta on a
  near-unchanged skeleton**. The numbers are **MEASURED from the microdata this pack
  ships** (`build_reference._ageing_deltas`, least squares over the full 17–58 sample,
  25→43 y): waist **+8.77 cm** and BMI **+2.27** for men (n=4082), **+6.59 cm** and
  **+1.92** for women (n=1986), while crotch/stature and the cormic index move by at most
  **0.68%** of their value at 25, all downward. Binned means (24–26 vs 42–44 y) give
  +8.03 cm / +2.10 male and +5.81 cm / +1.69 female. ANSUR II is **cross-sectional and
  militarily selected**, so this is the difference between two age groups in one selected
  population, not one person's life course, and it is smaller than the civilian figure.
  Gate ageing on girths, never on frame ratios. Live values:
  `reference().provenance('gaps')` → `adult ageing` → `.measured`.

  > **Corrected 2026-08-05.** This bullet, `build_reference.py`, and `reference.json`
  > itself all previously asserted "waist **+12.5 cm** and BMI **+3.2** while
  > crotch/stature and cormic drift **under 0.6%**" as fact, with no provenance key —
  > the one policy block in the pack that carried none. It was an unattributed civilian
  > briefing figure: **42% high** on waist and **41% high** on BMI against this pack's own
  > CSVs, and the female crotch/stature drift is −0.68%, outside the "<0.6%" it claimed.
  > The pack now derives all of it in code at build time and cannot drift again.
* **Non-US, non-military populations.** DODRace groups are administrative categories, not
  biological ones.
* **Female `asian`** has no band (n=71 < 100) while male `asian` does.
* **A-pose bideltoid.** The A-pose abducts the humerus ~40°, carrying the deltoid
  laterally. That measurement is correct for *this pose* and is not the standing survey
  dimension; it is flagged `conv` and reported against the band anyway, so the size of the
  pose effect is visible rather than hidden.
* **Derived mass and BMI** carry a whole-body density **assumption** (985 kg/m³ HOUSE;
  anny's own vendor code uses 980 "for simplicity"). The cage has no lungs, gut gas or
  fat/lean split, so nothing in the geometry can determine it. A 5% density error is a 5%
  mass error. Tagged `HOUSE`, never `MEASURED`.

---

## 9. Stylization is a named parameter, not a drift

anny/MakeHuman already ships a `BodyProportions` macro — 108 targets split
`idealproportions` / `uncommonproportions`. The stylization axis is therefore **a named
parameter**, and it must be **recorded per character**, not arrived at by accident. The
report's `STYLIZATION DELTA` block states it as a number: the median percentile across all
banded ratios, how many sit at or above p50, how many are beyond p5/p95, and the ratios
furthest outside their bands with the delta in millimetres.

A median percentile far from 50 is a whole-body style, not a per-ratio error. It is the
number to **record**, not the number to gate away.

---

## 10. One claim that did not reproduce

Recorded here rather than quietly dropped.

**`shoulder_hip_skeletal` — the pack's `definition` string contradicts the pack's own
statistics.** The definition reads *"biacromial/bicristal, both skeletal. Does NOT separate
a 12-year-old boy from an adult man (both ~1.43)"*. The qualitative conclusion is fine and
is the one we act on; the number **1.43 is not what this dataset says**:

| source | biacromial/bicristal, adult male |
|---|---|
| `reference.json` `stats.male.pooled` | **1.5133** |
| recomputed from `ansur_m.csv` (n=4082), mean of per-subject ratios | **1.5133** |
| ratio of the two column means (415.7 mm / 275.4 mm) | 1.5092 |

So the shipped *statistic* is correct and independently reproducible; only the prose
number in the definition string is wrong. The briefing's paired figures (1.4285 for a
12-year-old boy, 1.4325 for an adult man) presumably use a different *biiliac* landmark or
a different population, and **neither can be re-derived from this pack** — it carries no
child breadth microdata at all.

Consequence, and it is deliberately conservative: **we encode no shoulder:hip maturity
discriminator in either direction.** We do not gate on it as a child/adult cue, and we do
not claim the ~1.43 equality. The measured adult figure above is all this repository can
stand behind. The `definition` string is owned by `build_reference.py`; this note is not a
licence for another module to "correct" a number it did not measure.
