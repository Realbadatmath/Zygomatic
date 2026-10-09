# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.tone — TONE blocks."""

from zyg_workflows.sfx_fx.helpers import _db, _pick


# ═══════════════════════════════════════════════════════════════════════════════
#  TONE
# ═══════════════════════════════════════════════════════════════════════════════
def _b_eq3(p, ctx):
    f = []
    for n in ('1', '2', '3'):
        g = float(p['g' + n])
        if abs(g) < 0.05:
            continue
        f.append(f'equalizer=f={float(p["f" + n]):.1f}:t=q:w={float(p["q" + n]):.3f}:g={g:.2f}')
    return f


_EQ18_HZ = [65, 92, 131, 185, 262, 370, 523, 740, 1047, 1480, 2093, 2960, 4186, 5920, 8372, 20000]


def _b_eq18(p, ctx):
    args = []
    for i in range(1, 19):
        g = float(p[f'b{i}'])
        args.append(f'{i}b={_db(g):.4f}')
    if all(abs(float(p[f'b{i}'])) < 0.02 for i in range(1, 19)):
        return []
    return ['superequalizer=' + ':'.join(args)]


def _b_dyneq(p, ctx):
    return [
        f'adynamicequalizer=threshold={float(p["threshold"]):.4f}'
        f':dfrequency={float(p["dfreq"]):.1f}:dqfactor={float(p["dq"]):.3f}'
        f':tfrequency={float(p["tfreq"]):.1f}:tqfactor={float(p["tq"]):.3f}'
        f':attack={float(p["attack"]):.2f}:release={float(p["release"]):.2f}'
        f':ratio={float(p["ratio"]):.3f}:makeup={float(p["makeup"]):.2f}'
        f':range={float(p["range"]):.2f}'
        f':mode={_pick(p, "mode", ["listen", "cut", "boost"])}'
        f':direction={_pick(p, "direction", ["downward", "upward"])}'
        f':dftype={_pick(p, "dftype", ["bandpass", "lowpass", "highpass", "peak"])}'
        f':tftype={_pick(p, "tftype", ["bell", "lowshelf", "highshelf"])}'
    ]


def _b_band(p, ctx):
    kind = _pick(p, 'mode', ['bandpass', 'bandreject'])
    f = f'{kind}=f={float(p["freq"]):.1f}:t=q:w={float(p["q"]):.3f}:m={float(p["mix"]) / 100.0:.4f}'
    if kind == 'bandpass' and p['const_skirt']:
        f += ':csg=1'
    return [f] * max(1, int(p['stages']))


def _b_steepcut(p, ctx):
    """asubcut stops at 200 Hz and asupercut starts at 20 kHz, so neither is a
    musical cut. Cascading 2-pole sections is: order 12 = six of them, 72 dB
    per octave, and every section is exactly on the same corner."""
    n = max(1, int(round(float(p['order']) / 2.0)))
    f = []
    if float(p['low']) > 20.5:
        f += [f'highpass=f={float(p["low"]):.1f}:p=2'] * n
    if float(p['high']) < 19990:
        f += [f'lowpass=f={float(p["high"]):.1f}:p=2'] * n
    return f


def _b_tilt(p, ctx):
    return [
        f'atilt=freq={float(p["freq"]):.1f}:slope={float(p["slope"]):.4f}'
        f':width={float(p["width"]):.1f}:order={int(p["order"])}'
    ]


def _b_crystalizer(p, ctx):
    return [f'crystalizer=i={float(p["intensity"]):.3f}:c={"true" if p["clip"] else "false"}']


def _b_subboost(p, ctx):
    return [
        f'asubboost=dry={float(p["dry"]) / 100.0:.4f}:wet={float(p["wet"]) / 100.0:.4f}'
        f':boost={float(p["boost"]):.3f}:decay={float(p["decay"]) / 100.0:.4f}'
        f':feedback={float(p["feedback"]) / 100.0:.4f}:cutoff={float(p["cutoff"]):.1f}'
        f':slope={max(0.0001, float(p["slope"])):.4f}:delay={float(p["delay"]):.2f}'
    ]


def _b_virtualbass(p, ctx):
    return [f'virtualbass=cutoff={float(p["cutoff"]):.1f}:strength={float(p["strength"]):.3f}']


_EMPH_TYPES = ['col', 'emi', 'bsi', 'riaa', 'cd', '50fm', '75fm', '50kf', '75kf']


def _b_emphasis(p, ctx):
    return [
        f'aemphasis=level_in={_db(p["level_in"]):.4f}:level_out=1'
        f':mode={_pick(p, "mode", ["reproduction", "production"])}'
        f':type={_pick(p, "type", _EMPH_TYPES)}'
    ]


def _b_phaseshift(p, ctx):
    return [f'aphaseshift=shift={float(p["shift"]):.4f}:level={float(p["level"]) / 100.0:.4f}:order={int(p["order"])}']
