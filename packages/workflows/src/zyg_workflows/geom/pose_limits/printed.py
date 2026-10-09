# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE PRINTED NUMBERS — every threshold, and the page it was read on.

Moved verbatim out of the old single-file pose_limits.py (lines 358-745).
"""

from zyg_workflows.geom.pose_limits.base import SCRATCH, fractions, os


# ---------------------------------------------------------------------------------
# THE PRINTED NUMBERS. Every one of these is a degree count read off a page, and the page
# is named. Widening any of them requires contradicting the page, not a run of our meshes.
# ---------------------------------------------------------------------------------
AFS = 'Anatomy For Sculptors, Understanding the Human Figure'
HEADNECK = 'Form of the Head and Neck'

WRIST_EXTENSION_NATURAL_DEG = 45.0
WRIST_EXTENSION_FORCED_DEG = 90.0
WRIST_FLEXION_NATURAL_DEG = 50.0
WRIST_FLEXION_FORCED_DEG = 90.0
WRIST_ULNAR_MAX_DEG = 40.0
WRIST_RADIAL_MAX_DEG = 20.0
WRIST_SOURCE = (
    '%s p.181-182: wrist extension 0-45 deg natural and 45-90 deg forced; '
    'flexion 0-50 natural and 50-90 forced; ulnar deviation up to 40 deg; '
    'radial deviation up to 20 deg and flagged as the unnatural direction.' % AFS
)

# HeadNeck p.161 prints the per-joint band for C3-C7. THE RIG DOES NOT HAVE C3-C7: its
# cervical chain is neck01, neck02, neck03 and head, i.e. FOUR rotational joints against
# the five vertebral levels the page counts. The per-joint band is therefore applied to
# the four joints the rig actually has, and the arithmetic that makes that defensible is
# stated rather than hidden: 4 joints x 15-20 deg = 60-80 deg, which brackets the same
# page's printed total of 85 deg. Both numbers are reported so the mismatch is visible.
CERVICAL_EXTENSION_TOTAL_MAX_DEG = 85.0
CERVICAL_PER_JOINT_DEG = (15.0, 20.0)
CERVICAL_SOURCE = (
    '%s p.161: total cervical extension does not exceed ~85 deg, '
    'distributed over C3-C7 at roughly 15-20 deg per joint.' % HEADNECK
)
CERVICAL_RIG_JOINTS = ('neck01', 'neck02', 'neck03', 'head')
CERVICAL_MAPPING_NOTE = (
    'The rig has FOUR cervical rotational joints (neck01, neck02, neck03 and the head bone '
    'on neck03), not the five vertebral levels the page counts. The per-joint band is '
    "applied to those four; 4 x 15-20 deg = 60-80 deg against the same page's printed "
    'total of 85 deg. The top joint (head on neck03) is taken to be the occiput-C2 complex '
    "because the head bone's head sits at the skull base — MEASURED at z=0.7108 m on the "
    "neutral against neck03 at 0.6814 and the head bone's tail (crown) at 0.8646. That "
    'lumps the atlanto-occipital and atlanto-axial joints into one, which the rig cannot '
    'separate; the >=50% share is therefore tested against the pair, exactly as the page '
    'states it.'
)

OCCIPUT_C2_MIN_SHARE = 0.50
OCCIPUT_SOURCE = (
    '%s p.171: at least half of head pitch and half of head yaw happen at '
    'the occiput-C2 joint complex, not spread evenly down the neck.' % HEADNECK
)

SCAPULA_STATIC_BELOW_DEG = 90.0
SCAPULA_SOURCE = (
    '%s p.90: the scapula stays essentially static below 90 deg of humeral '
    'abduction and only then begins to rotate; its borders become surface-'
    'readable above that angle.' % AFS
)

PRONATION_HUMERUS_ROTATION_MAX_DEG = 0.0
PRONATION_SOURCE = (
    '%s p.149: pronation is a forearm event and produces no rotation of '
    'the humerus; %s p.150: the twist accumulates along the forearm with '
    'its maximum at the wrist.' % (AFS, AFS)
)

ELBOW_OWNER_SOURCE = (
    '%s p.156: the olecranon belongs to the ULNA and therefore travels '
    'with the forearm through flexion, not with the upper arm.' % AFS
)

# The HUMERAL negative control for t5_elbow_owner. The medial and lateral epicondyles are
# prominences of the DISTAL HUMERUS: whatever else is true of a rig, a discriminator with
# any resolving power at the elbow must answer "upper arm" for them. If it answers
# "forearm" for a humeral landmark as well as for the olecranon, it is answering the same
# thing on both sides of the joint and its PASS on the olecranon carries no information.
# See t5_elbow_owner.__doc__ for the measurement that made this control necessary (D7).
ELBOW_HUMERAL_CONTROL_PATCHES = ('epicondyle_lat', 'epicondyle_med')

PATELLAR_LIGAMENT_MAX_DRIFT = 0.02
PATELLAR_SOURCE = (
    '%s p.208: the patellar ligament holds the patella at a fixed distance '
    'from the tibial tuberosity through the whole knee range.' % AFS
)

TRANSVERSE_TILT_STDEV_MIN_DEG = 2.0
STIFFNESS_SOURCE = (
    '%s p.175 names three pose errors (elbows locked at exactly 90 or 180 '
    'degrees, fully extended finger chains in a relaxed hand, left and '
    'right forearms parallel); %s p.19 gives a five-configuration pose '
    'taxonomy; %s p.16 asks for a transverse-tilt standard deviation above '
    '2 degrees with shoulder and hip tilts of opposite sign.' % (AFS, AFS, AFS)
)

# AFS p.16's sentence has TWO conjuncts and this is the second one. It prints no tolerance
# on the sign opposition — it states it as a property of the pose — so the operationalised
# rule is the absence of a tolerance and not a chosen one: every pose that carries a
# measurable tilt at both girdles must show opposite signs. TILT_SIGN_ZERO_FLOOR_DEG is a
# NUMERICAL zero (a tilt below it has no determined sign), not an allowance; the sensitivity
# of the answer to that choice is reported at the HOUSE floors below rather than assumed
# away. Enforcing this conjunct is what makes abel and cornelis fail (R1): measured
# 2026-08-06, 22 of 44 and 23 of 43 fitted poses tilt shoulders and hips the SAME way.
#
# THIS CONSTANT IS THE THING THAT DECIDES. opposition_verdict() reads it and nothing else
# decides the conjunct; move it and the verdict moves with it. It was decorative until
# 2026-08-06 — the gate enforced `n_same_sign == 0` and this number was printed on the band
# and read by nothing (NEW-1) — so it is now guarded twice: against the page by
# TILT_OPPOSITION_CANON_FRACTION, and against the code by opposition_rule_drift().
TILT_OPPOSITION_REQUIRED_FRACTION = 1.0
TILT_SIGN_ZERO_FLOOR_DEG = 1e-6
TILT_SIGN_SENSITIVITY_FLOORS_DEG = (1.0, 2.0)

# THE MIRROR OF THE PAGE, and the reason it is a second literal. AFS p.16 states the sign
# opposition as a property of the pose and prints no allowance, so the only fraction the
# page supports is "all of them": 1.0. This constant is that PAGE value; the one above is
# what the module ENFORCES; opposition_rule_drift() compares them on every run and the gate
# returns ERROR when they part company. It is the same guard the first conjunct of the same
# sentence already has one tier up (geom/anthro/gates.py PL_STIFFNESS_FLOOR_DEG mirrors
# TRANSVERSE_TILT_STDEV_MIN_DEG and errors on divergence); until 2026-08-06 the conjunct
# that actually decides abel and cornelis had no such guard at all (NEW-1).
TILT_OPPOSITION_CANON_FRACTION = 1.0
# How many counts the boundary sweep in opposition_rule_drift() probes in addition to the
# live denominator. Small, exact, and it runs even on a body with no pose library.
TILT_OPPOSITION_PROBE_DENOMINATORS = (1, 2, 3, 4, 8, 44)


def _required_opposition():
    """TILT_OPPOSITION_REQUIRED_FRACTION as an exact Fraction, or None if it is not one.

    None is not a licence to fall back on a hardcoded rule: opposition_verdict() returns a
    NON-VERDICT and opposition_rule_drift() turns that into an ERROR that names the reason.
    A constant that cannot be read is a band that cannot be enforced, and the gate says so
    rather than deciding the conjunct some other way.
    """
    try:
        return fractions.Fraction(TILT_OPPOSITION_REQUIRED_FRACTION)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def opposition_verdict(n_opposed, n_evaluated):
    """THE enforced test for AFS p.16's SECOND conjunct. The only place it is decided.

    Until 2026-08-06 this read `opposition_ok = bool(n_same_sign == 0)` and
    TILT_OPPOSITION_REQUIRED_FRACTION was a LABEL printed on the band and read by nothing
    (NEW-1). Measured proof of the divergence, on abel's own 44 fitted poses: setting the
    constant to 0.0 made the report declare "no opposition required" while the gate went
    on FAILING at a measured opposition of 0.5000, and all 14 demo_broken controls passed.
    The direction was enforced-STRICTER-than-declared, so nothing was flattered by it —
    which is exactly why it was dangerous: nothing would have alarmed when the relation
    reversed.

    Reads the constant. Returns None when no pose determined a sign, which is a non-verdict
    and never a pass. The comparison is EXACT — Fraction, not float division — so no pose
    set is decided by a rounding step at the boundary (n_opposed/n_evaluated for large n).
    """
    req = _required_opposition()
    if not n_evaluated or req is None:
        return None
    return bool(fractions.Fraction(int(n_opposed), int(n_evaluated)) >= req)


def max_same_sign_allowed(n_evaluated):
    """How many SAME-SIGN poses of `n_evaluated` the DECLARED constant tolerates.

    Derived from the constant by integer arithmetic that shares no expression with
    opposition_verdict(), so the two are independent statements of the same rule and
    opposition_rule_drift() can compare them. It is also what the printed sentence quotes,
    so the prose cannot go on saying "the printed rule allows none" after the constant has
    been moved.
    """
    req = _required_opposition()
    if not n_evaluated or req is None:
        return None
    n = int(n_evaluated)
    # smallest k with k/n >= req, by ceiling division on integers
    k_min = -((-req.numerator * n) // req.denominator)
    return n - max(0, min(n, k_min))


def opposition_rule_drift(n_opposed=None, n_evaluated=None, enforced=None):
    """Is the ENFORCED sign-opposition test still doing what the DECLARED constant says?

    Returns None when everything agrees, otherwise a dict naming the divergence. The gate
    turns a non-None return into status ERROR: a gate whose declared band is not the band
    it enforced has not measured anything a reader can use, and saying so is rule 4.

    Four checks, each an independent statement of the rule:

      range     the constant is a fraction in [0, 1]. Outside that no pose set can move
                the verdict in one of the two directions, which is a dead gate.
      mirror    TILT_OPPOSITION_REQUIRED_FRACTION vs TILT_OPPOSITION_CANON_FRACTION, the
                value AFS p.16 supports. Same shape as gates.PL_STIFFNESS_FLOOR_DEG.
      live      the verdict THIS RUN actually carries, against the constant applied to
                THIS RUN's counts by integer cross-multiplication. This one holds however
                the verdict was produced — inline the old `n_same_sign == 0` back into the
                gate and this fires on abel the moment the constant is not 1.0.
      boundary  sweep k = 0..n through opposition_verdict() and find where it flips; the
                flip must sit exactly where the constant puts it, and the answer must be
                monotone non-decreasing in k (more opposed poses may never score worse).
    """
    bad = []
    req_f = TILT_OPPOSITION_REQUIRED_FRACTION
    req = _required_opposition()
    if req is None:
        # same record shape as every other return: the gate's ERROR text reads
        # ['divergences'] and a differently-shaped refusal would crash instead of refusing.
        return {
            'divergences': [
                {
                    'check': 'range',
                    'required_fraction': req_f,
                    'why': 'TILT_OPPOSITION_REQUIRED_FRACTION is not a number, so the '
                    'declared band has no meaning and nothing can be enforced '
                    'against it',
                }
            ],
            'required_fraction': req_f,
            'canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
            'rule': 'the declared band must be a number before it can be the enforced rule',
        }
    if not (0 <= req <= 1):
        bad.append(
            {
                'check': 'range',
                'required_fraction': req_f,
                'why': 'a required opposition fraction outside [0, 1] cannot be met '
                'or cannot be missed; the gate would be decided in advance',
            }
        )
    if req_f != TILT_OPPOSITION_CANON_FRACTION:
        bad.append(
            {
                'check': 'mirror',
                'required_fraction': req_f,
                'canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
                'why': 'this gate ships AFS p.16 at provenance CANON. The page prints '
                'no allowance on the sign opposition, so the only fraction it '
                'supports is %r. Enforcing %r is a HOUSE choice wearing a CANON '
                'label — change the provenance or change the number.' % (TILT_OPPOSITION_CANON_FRACTION, req_f),
            }
        )
    if n_evaluated:
        n, k = int(n_evaluated), int(n_opposed or 0)
        expect = bool(k * req.denominator >= req.numerator * n)
        if enforced is not None and bool(enforced) != expect:
            bad.append(
                {
                    'check': 'live',
                    'n_opposed': k,
                    'n_evaluated': n,
                    'required_fraction': req_f,
                    'enforced_verdict': bool(enforced),
                    'declared_verdict': expect,
                    'why': 'the verdict this run carries is not the verdict the '
                    "declared fraction produces on this run's own counts. "
                    'The report would print a band that was not enforced.',
                }
            )
    for n in sorted(set(TILT_OPPOSITION_PROBE_DENOMINATORS) | ({int(n_evaluated)} if n_evaluated else set())):
        if n <= 0:
            continue
        seq = [opposition_verdict(k, n) for k in range(n + 1)]
        if any(seq[i] and not seq[i + 1] for i in range(n)):
            bad.append(
                {
                    'check': 'boundary_monotonic',
                    'n_evaluated': n,
                    'verdict_by_n_opposed': seq,
                    'why': 'the enforced test got HARSHER as more poses opposed',
                }
            )
            continue
        flip = next((k for k in range(n + 1) if seq[k]), None)
        # where the CONSTANT puts the boundary. req > 1 is unmeetable, so no k flips it.
        want = None if req > 1 else n - (max_same_sign_allowed(n) or 0)
        if flip != want:
            bad.append(
                {
                    'check': 'boundary',
                    'n_evaluated': n,
                    'required_fraction': req_f,
                    'enforced_flips_at_n_opposed': flip,
                    'declared_flips_at_n_opposed': want,
                    'why': 'the enforced test changes its answer somewhere other than '
                    'where the declared fraction puts the boundary, so the '
                    'constant is not the thing deciding this gate',
                }
            )
    if not bad:
        return None
    return {
        'divergences': bad,
        'required_fraction': req_f,
        'canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
        'rule': 'the DECLARED band and the ENFORCED test must be the same rule. '
        "geom/pose_limits.py:opposition_verdict is the only place AFS p.16's "
        'second conjunct is decided, and it must read '
        'TILT_OPPOSITION_REQUIRED_FRACTION.',
    }


# HOUSE windows. None of these can produce a blocking verdict; each is reported at three
# widths so its sensitivity is visible instead of implied. The VERDICT on each of AFS
# p.175's three named pose errors is taken at the NARROWEST width — the strictest reading
# of "locked at exactly 90 or 180" and of "parallel", i.e. the fewest poses this gate is
# willing to call an instance of the named error.
STIFF_ELBOW_WINDOWS_DEG = (3.0, 5.0, 8.0)
STIFF_PARALLEL_WINDOWS_DEG = (5.0, 10.0, 15.0)
ERECT_TRUNK_WINDOWS_DEG = (10.0, 15.0, 20.0)
ERECT_KNEE_WINDOW_DEG = 15.0
TWIST_STATION_COUNTS = (6, 10)


def ansur_rom_columns():
    """Evidence for canon_may_block(): does the MEASURED reference contain any range-of-
    motion column at all?

    ANSUR II is a linear-anthropometry survey. If it ever gained a goniometry column this
    would find it and the CANON thresholds in this file would lose the right to block,
    automatically. Returns None when the microdata is not on disk — an absent file is not
    evidence of absence and must not be reported as if it were.
    """
    import csv

    path = os.path.join(SCRATCH, 'ansur_m.csv')
    if not os.path.exists(path):
        return None
    with open(path, newline='', encoding='latin-1') as fh:
        cols = next(csv.reader(fh))
    # substrings that would appear in the name of any goniometric column
    kw = (
        'angle',
        'rom',
        'goniom',
        'flexion',
        'extension',
        'rotation',
        'deviation',
        'abduction',
        'adduction',
        'pronation',
        'supination',
    )
    hits = sorted({c for c in cols for k in kw if k in c.lower()})
    # 'abdominalextensiondepthsitting' and 'forearmcircumferenceflexed' are LINEAR columns
    # whose names contain those substrings; a real ROM column would be an angle in degrees.
    linear = sorted(
        c for c in hits if any(s in c.lower() for s in ('depth', 'circumference', 'length', 'breadth', 'height'))
    )
    return {
        'n_columns': len(cols),
        'substring_hits': hits,
        'hits_that_are_linear_measures': linear,
        'rom_columns': sorted(set(hits) - set(linear)),
    }


def canon_may_block():
    """A CANON threshold may block only where no MEASURED source exists for the quantity.

    Rule 5 of the operating brief, enforced rather than asserted. For joint ROM the
    measured reference is silent, and this checks that rather than trusting it.
    """
    ev = ansur_rom_columns()
    if ev is None:
        return {
            'may_block': True,
            'why': 'ANSUR II microdata not on disk this run; no '
            'MEASURED range-of-motion source is known to '
            'exist in any reference pack we ship',
            'evidence': None,
        }
    ok = not ev['rom_columns']
    return {
        'may_block': bool(ok),
        'why': (
            'ANSUR II carries %d columns and NONE of them is a range-of-motion '
            'measurement (the %d substring hits are all linear measures such as '
            '%s), so no MEASURED source exists for joint ROM and CANON is the '
            'strongest evidence available'
            % (ev['n_columns'], len(ev['substring_hits']), ', '.join(ev['hits_that_are_linear_measures'][:3]))
            if ok
            else 'ANSUR II now carries range-of-motion columns (%s); a MEASURED source '
            'exists and CANON must not block this quantity' % ', '.join(ev['rom_columns'])
        ),
        'evidence': ev,
    }
