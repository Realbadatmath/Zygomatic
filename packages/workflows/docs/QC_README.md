# QC gates — how they work now

Built 2026-08-04. Before this date every gate in this repo was advisory:
`pipeline_debug` read a `qc_gates.json` that did not exist, defaulted to
`shadow`, wrote the mode into the verdict, and **nothing consumed it**
(`grep gate_mode` → zero call sites). `scene20_v28`, the best render on disk,
finished with `verdict.ok=false`, 29 failed checks and 10 defect tags, and
shipped.

---

## The one command

```bash
.venv-test/bin/python -m pytest tests/ -q          # the golden suite, ~1s, no GPU
```

`.venv-test/` is a throwaway venv containing only pytest. It is deliberately
isolated from every production env — this repo has real dependency landmines
(`pip install facenet-pytorch` would downgrade torch 2.10 → 2.2.2 plus 12 nvidia
wheels).

## Day-to-day

```bash
python3 scripts/qc_gate_admin.py list          # every gate and its ladder mode
python3 scripts/qc_gate_admin.py coverage      # which defect classes have NO gate
python3 scripts/qc_gate_admin.py show region_flow
python3 scripts/qc_gate_admin.py promote region_churn   # refuses unless golden passes
python3 scripts/qc_gate_admin.py demote region_flow     # always allowed, no proof needed
python3 scripts/golden_baseline.py             # what would change across all 39 runs
python3 scripts/flag_audit.py                  # ZYG_ flag inventory
```

## The ladder

| mode | behaviour |
|---|---|
| `shadow` | measure + record. Never surfaces as a blocker. |
| `warn` | measure + record + mark the run loudly. Does not stop it. |
| `block` | measure + record + **raise `QCBlocked`**. Stops the pipeline. |

Config: `data/runtime/qc_gates.json`. Contracts: `qc_contract.py`.

**Kill switch:** `ZYG_QC_ENFORCE=0` turns every `block` into a `warn`, from the
environment, without editing anything. That is the switch to pull at 3 a.m.

**An unregistered gate is always `shadow`**, regardless of the global default. A
gate with no contract in `GATE_CONTRACTS` has not earned authority. That is what
makes "new gates enter at shadow" automatic instead of a convention someone has
to remember.

## Three verdicts, not two

`PASS` / `FAIL` / **`UNKNOWN`**. A gate that could not look must not report green.

This was live, in two opposite directions at once: `pipeline_debug.py:520`
recorded a crashed tracker as `{'ok': True, 'note': 'skipped: ...'}` — green — and
`finish()` counted `{'ok': None}` as a *failure*. Both halves of a missing concept.
Elsewhere, "an ink PASS means no-coverage (measured 0/7 recall), not clean."

`qc_contract.classify()` also catches `ok=True` carrying a skip note, so historical
records route correctly too.

## Coverage is part of the verdict

Every run report now ends with a coverage matrix: for each defect class, did any
gate that detects it actually decide?

- **covered** — a gate ran and returned PASS or FAIL
- **unknown** — a gate ran and could not decide
- **uncovered** — nothing that detects this class ran at all

**UNCOVERED is not a pass.** `eyelid-aperture` sat uncovered for six renders while
every gate measured face `flow_median` — which is *anti-correlated* with eyelid
aperture. The operator's plain-English complaint ("his eyes were almost closed the
entire 20 seconds") was right and the whole instrument panel was measuring the
wrong quantity. The matrix makes that visible in advance instead of after.

Classes **no gate anywhere** detects — where your eyes are still the only
instrument:

- `texture-collapse` — waxy skin cost ~4.5h GPU and a LoRA trained on 48 anime
  images before a 12-render A/B found the real lever
- `style-collapse` — the 2026-07-15 anime-collapse incident, 30/49 faces undetectable
- `audio-loss` — CLAP gates exist in the audio path but emit no `pipeline_debug`
  checks, so they are invisible to this ladder

Shrinking that list is the roadmap.

## Why so few gates block

Arming `region_flow` naively blocked **12 of 39** historical runs. After
calibration it blocks **2**, and both are true positives. What the golden set
caught before anything shipped:

1. **`region_flow:keep:*`** — a keep/pin region is **static by design**. Measuring
   it for aliveness failed in 10 of 14 recorded runs *including known-good ones*.
   Permanently `shadow`.
2. **`region_flow` is two gates wearing one name** — a *frozen* half (flow below
   floor) and a *churn* half (edge structure re-drawn). Different defect classes,
   different remedies, very different maturity. The frozen half separates 4.5×
   across its threshold (v8a `abel_hand` 0.080 → v8b 0.364, gate 0.12) and
   **blocks**. The churn half fired at 0.553 against a 0.55 floor on v29 — a 0.5%
   margin — and 0.684 on v22, both good runs, so it only **warns**. Split via
   `fail_kind`, with note-text fallback so the 56 reports already on disk route
   correctly.
3. **`prop_ncc` held at `warn`** — the fixed 0.70 floor fails the *final seam of
   every 20s clip* because prop fidelity decays with elapsed generated time
   (wall-stable ~5s, 4–6× worse by ~s12). That is a measured property of the model,
   not a defect the run introduced. Blocking on it would stop v28.

A gate that blocks most of the corpus is miscalibrated, not strict.
`test_block_rate_stays_sane` fails above 25%.

## The golden set

`tests/golden/labels.json` — hand-labelled ground truth: defects this pipeline
actually shipped, with the numbers that proved them.

**This is where your eyes get deposited into the system permanently.** Every time
you spot something on screen the gates missed, add a case. From then on it is
checked in milliseconds on every gate change, forever, instead of being
re-discovered by you on the next render.

`tests/golden/baseline.json` — auto-generated characterisation snapshot of all 39
recorded runs. It does not claim the verdicts are *right*, it claims they are
*known*. Any threshold change that silently flips a verdict on a run nobody was
watching fails the suite with the run named. Regenerate deliberately:

```bash
python3 scripts/golden_baseline.py --write
```

## Promotion

`qc_gate_admin.py promote` applies the new mode, runs the golden suite, and
**reverts on failure**. A gate cannot reach `block` without proving on every
historical run that it fails the bad ones and spares the good ones.

Demotion never requires proof — making a gate quieter cannot ship a defect it was
already catching, and an operator must always be able to stop the bleeding.

## The licence gate (2026-08-09)

`licence_provenance.py` — is every weight in this graph cleared for **commercial**
publication? Added when the channel became monetised.

This is the only class in the taxonomy where the operator eye is not a weaker
instrument but **no instrument**: a FLUX.1-dev frame and an Apache-2.0 frame are
visually identical, so no amount of looking finds this defect at any resolution.

```bash
python3 licence_provenance.py state             # pause switch + territory + registry
python3 licence_provenance.py check <graph.json>
python3 licence_provenance.py weight <name> lora
```

Registry: `data/runtime/model_licences.json`. An entry exists **only** when its
licence was read at the primary source, and every entry cites that source. A
weight that is absent classifies as `UNKNOWN`, which is not a pass — guessing
"probably fine" into that file converts an unread licence into a green gate.

**A LoRA is charged with its BASE model's licence**, because a LoRA is a
derivative of what it was fine-tuned from. Two measured false positives shaped
how lineage resolves, both found by running the gate over the real corpus:

1. **char_id is not a lineage key.** One character owns several LoRAs on
   *different* bases — a FLUX image LoRA and a Wan video LoRA
   (`wan_chars/wan_char_<id>`, musubi-tuner `--task i2v-14B`). Resolving by char
   id charged Wan weights with FLUX's licence: **FAIL on 40 of 41 captured
   graphs.** Fixed with registry `lora_lineage` conventions, checked before the
   char-id scan.
2. **The bare staged name has two writers.** `arcane_restyle.py:112` stages the
   **SDXL** LoRA as `zygchar_<id>.safetensors` while
   `comfy_generation_service.py:1385` stages family-suffixed
   `zygchar_<cid>_<mf>.safetensors`. A blanket `zygchar_* → flux` rule charges
   SDXL weights non-commercially. Bare names fall through to the char-id scan and
   are charged **the worst** of that character's legs — honest ambiguity beats a
   coin-flip in either direction.

Registering `zygchar_<cid>_<mf>` at every staging site (i.e. giving
`arcane_restyle` the family suffix) would remove that ambiguity for good.

**Three entry points, three moments.**

| call | when | what it can know |
|---|---|---|
| `family_decision(fam)` | operator approval, pre-render | only the base family the run will derive from — a contact-sheet run *trains* the adapter it will use |
| `attest_licences(graph)` | submit, pre-render | every weight the graph references |
| `publish_decision(weights)` | delivery | the weights a finished asset actually used |

`family_decision` is wired into `bp_zero_public_store.api_zpub_pending_decide`:
approving a run whose base family is not cleared returns **409** instead of
burning a GPU slot that would stop at the render gate anyway. It fails **open** —
a broken licence module must never freeze the approval queue.

**The pause switch is separate from the ladder.** The ladder judges finished work;
`ZYG_FLUX_RENDERS` stops work starting. It defaults to `paused` (2026-08-09
operator decision) and is enforced at three sites — LoRA training on a FLUX base,
FLUX fill/HandFixer (degrades to the existing cv2 repair), and FLUX still
generation. Each uses that caller's existing refusal protocol rather than raising.
A typo'd value reads as paused. To resume:

```bash
export ZYG_FLUX_RENDERS=allowed
```

## The restoration gate (2026-08-09)

`restoration_qc.py` — did the upscaler **invent** detail that was not in the
source? Built before the SeedVR2 (Apache-2.0) finishing stage lands, so the
replacement arrives against a calibrated instrument instead of an opinion.

The upscaler was an unmeasured stage: `texture-collapse` is the opposite failure
(detail *lost*), and nothing looked at the image the viewer actually sees.

**The control arm is exact, not empirical.** A LANCZOS upscale invents nothing by
construction — fixed kernel, no learned prior. So the gate reports
`residual(model) − residual(lanczos)` on the same source, where `residual` is the
mean absolute difference after box-downsampling the upscale back to source size.

Measured 2026-08-09 over the FINAL_pipeline RealESRGAN_x2 run:

| case | delta |
|---|---|
| LANCZOS scored against itself (zero point) | **0.00000000** exactly |
| NEAREST-NEIGHBOUR 2x (invents nothing) | −0.0040 .. −0.0047 |
| **incumbent RealESRGAN_x2, 65 frames** | 0.011826 .. 0.012607 |
| ESRGAN + injected σ=0.05 invention | 0.02228 .. 0.02264 |

Floor is the incumbent's worst frame × 1.5 = **0.018911**, which gives it a
concrete meaning: *invents more than the finishing stage we already ship and
accept*. Result: **65/65 incumbent PASS, 15/15 injected-invention FAIL.**

**Tile separation is logged and never weighed.** The first cut refused to decide
below a guessed 1.20 ratio — which returned UNKNOWN on the whole incumbent corpus
(measured 1.10–1.32). The direction was also backwards: injecting invention drove
separation *down* (1.23→1.06). And even corrected it is unusable, because the two
populations overlap (incumbent min 1.10 vs invention max 1.11). No threshold on
that ratio separates them, so it makes no claim.

**Blind to identity.** A restorer can invent a *consistent* face and score well
here. In the contact-sheet path that is already covered: the anchor is extracted
from the **native** sheet while tiles are cropped from the **upscaled** one, so
ArcFace drift is measured across the upscaler. The video path has no equivalent
post-upscale identity gate — that hole is real and still open.

```bash
python3 restoration_qc.py pair <src.png> <upscaled.png>
python3 restoration_qc.py calibrate <src_dir> <up_dir>   # propose a floor
python3 restoration_qc.py folder <src_dir> <up_dir> 20
```

Calibration needs numpy/PIL, so run it with the production interpreter
(`"/home/zygomatic/Zygomatic Full/agents/.venv/bin/python"`); imports are lazy so
the decision logic still tests in `.venv-test`.

## Related

- `run_ledger.py --trends` — cross-run pass-rate drift, two-proportion z-test.
  Now on a nightly timer (`zyg-qc-trends.timer`). One run's gates are boring;
  fourteen days of them are how the ghost-face pattern (17/49 bad cells, every
  per-run gate passing) becomes visible at all.
- `lora_attest.py` — hashes every model file in the **captured** comfy graph
  against `model_pins.json`. This is the gate the wrong-character bug needed:
  identity QC scores a render against *its own anchor*, so a wrong-but-consistent
  asset is green. That blindness hid 65/67 wrong characters.
- `self_improve.py` — now reads `qc_spec.json` **exported from production** by
  `DebugRun.finish()`, rather than a driver constant (`scene20_v8.py::V8_QC`)
  that does not exist.
