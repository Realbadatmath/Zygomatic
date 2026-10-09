# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.placing — the placement itself: the plan transform, `_place`, the
attribution record and the credits/design check. Moved verbatim out of
floor_plans.py (2026-10-06)."""

from __future__ import annotations

from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
)

from zyg_workflows.arch_assistant_ext.floor_plans import placing_steps as _steps
from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    ATTR_KEY,
    SCALE_MAX,
    SCALE_MIN,
    _T,
    _fit_scale,
    attribution_of,
)


# ── placing ──────────────────────────────────────────────────────────────────
def _plan_transform(plan: dict, rect: tuple, mirror, rot, want_scale='fit') -> tuple:
    """(_T placed on `rect` as align="centre" would, error). The one place the
    mirror -> rotate -> scale -> centre transform is decided, so core_from_plan
    draws the core exactly where place_plan will later put the plan's own."""
    x0, z0, x1, z1 = (min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3]))
    W, D = x1 - x0, z1 - z0
    pw, pd = _num(plan.get('w'), 0.0), _num(plan.get('d'), 0.0)
    if pw <= 0 or pd <= 0:
        return None, f'refused: {plan.get("id")} has no size on record'
    rot = int(_num(rot, 0)) % 360
    if rot % 90:
        return None, f'refused: rotate_deg must be 0, 90, 180 or 270 (got {rot})'
    rw, rd = (pd, pw) if rot in (90, 270) else (pw, pd)
    if want_scale in (None, '', 'fit'):
        s = _fit_scale(W, D, rw, rd)
        if not (SCALE_MIN - 1e-9 <= s <= SCALE_MAX + 1e-9):
            return None, (
                f'refused: {plan.get("id")} is {pw:g} x {pd:g} m, the bay is {W:g} x {D:g} m — '
                f'scale {s:.2f} is past ±12 %: search_plans(width={W:g}, depth={D:g}) lists '
                f'plans that fit'
            )
    else:
        s = _num(want_scale, 1.0)
        if s <= 0:
            return None, 'refused: scale must be "fit" or a positive number'
    T = _T(pw, pd, bool(mirror), rot, s)
    SW, SD = T.size
    T.ox, T.oz = x0 + (W - SW) / 2, z0 + (D - SD) / 2
    return T, ''


def _place(d: Drawing, plan: dict, rect: tuple, storey: int, opts: dict) -> dict:
    """Draw `plan` into the world rectangle `rect`. The plain function task 4's
    tiler calls; t_place_plan is the tool wrapper around it.

    opts: y, grp, group, mirror, rotate_deg, scale, align, entrance_side, snap,
          doors, windows, zones, fixtures, shell, wall_mat
    Returns {'ids', 'counts', 'notes', 'scale', 'rot', 'dropped', 'error'}.

    The stages are in placing_steps; this is the order they run in and the record
    they add up to.
    """
    out = {'ids': [], 'counts': {}, 'notes': [], 'scale': 1.0, 'rot': 0, 'dropped': 0, 'error': ''}
    bounds = (min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3]))
    mirror = bool(opts.get('mirror'))

    # rotation ---------------------------------------------------------------
    rot, err = _steps.resolve_rotation(plan, opts, mirror)
    if err:
        out['error'] = err
        return out

    # scale, then centre the plan on the bay ---------------------------------
    T, err = _plan_transform(plan, rect, mirror, rot, opts.get('scale', 'fit'))
    if err:
        out['error'] = err
        return out
    out['scale'], out['rot'] = round(T.s, 4), rot

    # alignment, the core keep-out, the walls' group and material ------------
    ctx, err = _steps.build_context(d, plan, rect, bounds, storey, opts, T)
    if err:
        out['error'] = err
        return out

    _steps.draw_walls(ctx)
    _steps.draw_zones(ctx)
    _steps.draw_doors(ctx)
    _steps.draw_windows(ctx)
    _steps.draw_fixtures(ctx)
    _steps.closing_notes(ctx)

    out.update(
        {
            'ids': ctx.ids,
            'counts': ctx.counts,
            'notes': ctx.notes,
            'dropped': ctx.dropped,
            'rect': bounds,
            'grp': ctx.grp,
            'y': ctx.y,
        }
    )
    return out


# the name floor_plans re-exports; the function moved with its only caller
_side_of = _steps.side_of


def record_attribution(d: Drawing, pack_name: str, plan_id: str) -> str:
    """One entry per pack in d.ext['attributions']; plan ids appended."""
    text = attribution_of(pack_name)
    store = d.ext.get(ATTR_KEY)
    if not isinstance(store, list):
        store = []
    for e in store:
        if isinstance(e, dict) and e.get('pack') == pack_name:
            plans = e.setdefault('plans', [])
            if plan_id not in plans:
                plans.append(plan_id)
            e['text'] = text
            d.ext[ATTR_KEY] = store
            return text
    store.append({'pack': pack_name, 'text': text, 'plans': [plan_id]})
    d.ext[ATTR_KEY] = store
    return text


def credits_text(d: Drawing) -> str:
    """The attribution lines this drawing owes, one per line."""
    store = d.ext.get(ATTR_KEY)
    if not isinstance(store, list) or not store:
        return ''
    return '\n'.join(str(e.get('text') or '') for e in store if isinstance(e, dict) and e.get('text'))


def t_attributions(d: Drawing, a):
    store = d.ext.get(ATTR_KEY)
    lines = [e for e in (store or []) if isinstance(e, dict) and e.get('text')] if isinstance(store, list) else []
    if not lines:
        return (
            'this drawing owes no credits — nothing from the plan library is in it yet. '
            "place_plan or tile_units records the pack's attribution the moment one is used."
        )
    out = []
    for e in lines:
        plans = [str(p) for p in (e.get('plans') or []) if p]
        used = ''
        if plans:
            used = (
                f' — {len(plans)} plan'
                + ('' if len(plans) == 1 else 's')
                + ' used: '
                + ', '.join(plans[:6])
                + (', …' if len(plans) > 6 else '')
            )
        out.append(str(e['text']) + used)
    n = len(out)
    return (
        f'{n} credit line{"" if n == 1 else "s"} this drawing owes, word for word:\n'
        + '\n'.join(out)
        + '\nThey must appear in the credits of anything published from it; every export writes '
        'them to a .credits.txt beside the file.'
    )


def check_attributions(d: Drawing) -> list:
    """A licence obligation is a fact about the output, not a fault in the design,
    so this is always 'info' and never blocks done — it only makes sure the
    credit line cannot be forgotten between placing a plan and publishing."""
    lines = [ln for ln in credits_text(d).split('\n') if ln.strip()]
    if not lines:
        return []
    return [
        {
            'sev': 'info',
            'code': 'credits',
            'text': 'credits required: '
            + '; '.join(lines)
            + ' — attributions() prints them, and every export writes them beside the file',
        }
    ]


DESIGN_CHECKS = [check_attributions]
