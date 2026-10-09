# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""cli — cli section of remedy_kb (verbatim split).

Moved unchanged from remedy_kb.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import _infer_role, json, normalize_signature, sys
from .evaluator import evaluate
from .kb import _subst, apply, load_kb, match, posterior_confidence
from .learning import format_ranked


def _main(argv):
    if '--list' in argv:
        kb = load_kb()
        print(
            json.dumps(
                {
                    'ok': kb['ok'],
                    'sources': kb.get('sources'),
                    'remedies': [
                        {
                            k: r.get(k)
                            for k in (
                                'id',
                                'severity',
                                'status',
                                'confidence',
                                'authored_confidence',
                                'attempts',
                                'successes',
                                'source',
                            )
                        }
                        for r in kb['remedies']
                    ],
                },
                indent=1,
            )
        )
        return 0
    if '--match' in argv:
        p = argv[argv.index('--match') + 1]
        with open(p, encoding='utf-8') as f:
            sig = json.load(f)
        print(format_ranked(match(sig, log_fn=print)))
        return 0
    if '--selftest' in argv:
        return 0 if _selftest() else 1
    print(__doc__.strip().splitlines()[0])
    print('usage: python3 remedy_kb.py --list | --match <signature.json> | --selftest')
    return 1


def _selftest():
    """Unit tests for the predicate evaluator and the learning loop. Lives in the
    module (not a separate file) so it ships with the code it guards and can be run
    on any box with `python3 remedy_kb.py --selftest`."""
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f'{name}: got {got!r}, want {want!r}')

    sig = {
        'regions': {
            'a_hand': {'flow_mean': 0.08, 'min_flow': 0.12, 'box': [0.58, 0.60, 0.83, 0.90], 'role': 'character_hand'}
        },
        'props': {'book': {'min_ncc': 0.99, 'ncc_min': 0.70, 'raw_min_ncc': 0.936, 'pinned': True}},
        'keep_boxes': {'book': [0.495, 0.70, 0.825, 0.92]},
        'chain': ['render', 'pasteback_static'],
        'params': {'pasteback': 'static'},
        'nested': {'a.b': {'c': 7}},
    }
    E = lambda p, s=sig: evaluate(p, s)[0]  # noqa: E731

    # literals / logic
    check('lit true', E(True), True)
    check('all empty', E({'all': []}), True)
    check('any empty', E({'any': []}), False)
    check('and', E({'all': [True, True]}), True)
    check('and false', E({'all': [True, False]}), False)
    check('or', E({'any': [False, True]}), True)
    check('not', E({'not': False}), True)

    # comparisons + dotted lookup
    check('lt', E({'lt': ['regions.a_hand.flow_mean', 'regions.a_hand.min_flow']}), True)
    check('gte', E({'gte': ['props.book.raw_min_ncc', 0.90]}), True)
    check('lt missing', E({'lt': ['regions.nope.flow_mean', 0.12]}), False)
    check('gt missing', E({'gt': ['regions.nope.flow_mean', 0.12]}), False)
    check('dotted key', E({'eq': ['nested.a.b.c', 7]}), True)
    check('bool not number', E({'gte': [{'lit': True}, 0.5]}), False)
    check('str number', E({'gt': [{'lit': '0.9'}, 0.5]}), True)

    # eq/ne fail closed
    check('eq missing', E({'eq': ['nope.x', 'nope.y']}), False)
    check('ne missing', E({'ne': ['nope.x', 'nope.y']}), False)
    check('ne real', E({'ne': [{'lit': 1}, {'lit': 2}]}), True)

    # membership / presence
    check('in list', E({'in': [{'lit': 'pasteback_static'}, 'chain']}), True)
    check('in list no', E({'in': [{'lit': 'ink'}, 'chain']}), False)
    check('in map keys', E({'in': [{'lit': 'book'}, 'keep_boxes']}), True)
    check('present', E({'present': 'params.pasteback'}), True)
    check('absent', E({'absent': 'params.page_quad'}), True)
    check('absent no', E({'absent': 'params.pasteback'}), False)

    # quantifiers
    check('exists', E({'exists': {'in': 'regions', 'as': 'r', 'where': {'lt': ['$r.flow_mean', '$r.min_flow']}}}), True)
    check(
        'exists key', E({'exists': {'in': 'regions', 'as': 'r', 'where': {'eq': ['$r._key', {'lit': 'a_hand'}]}}}), True
    )
    check(
        'exists filter empty',
        E(
            {
                'exists': {
                    'in': 'regions',
                    'as': 'r',
                    'filter': {'eq': ['$r.role', {'lit': 'background'}]},
                    'where': True,
                }
            }
        ),
        False,
    )
    check(
        'forall vacuous guard',
        E(
            {
                'forall': {
                    'in': 'regions',
                    'as': 'r',
                    'filter': {'eq': ['$r.role', {'lit': 'background'}]},
                    'where': True,
                    'min_count': 1,
                }
            }
        ),
        False,
    )
    check(
        'forall true',
        E({'forall': {'in': 'regions', 'as': 'r', 'where': {'lt': ['$r.flow_mean', '$r.min_flow']}}}),
        True,
    )
    check('forall min_count', E({'forall': {'in': 'regions', 'as': 'r', 'where': True, 'min_count': 2}}), False)
    check('exists missing coll', E({'exists': {'in': 'nope', 'as': 'r', 'where': True}}), False)
    check(
        'nested quant',
        E(
            {
                'exists': {
                    'in': 'props',
                    'as': 'p',
                    'where': {'exists': {'in': 'keep_boxes', 'as': 'k', 'where': {'eq': ['$k._key', '$p._key']}}},
                }
            }
        ),
        True,
    )

    # geometry
    check('overlap', E({'boxes_overlap': {'a': 'regions.a_hand.box', 'b': 'keep_boxes.book', 'min_frac': 0.10}}), True)
    check(
        'overlap strict',
        E({'boxes_overlap': {'a': 'regions.a_hand.box', 'b': 'keep_boxes.book', 'min_frac': 0.99}}),
        False,
    )
    check('overlap disjoint', E({'boxes_overlap': {'a': {'lit': [0.0, 0.0, 0.1, 0.1]}, 'b': 'keep_boxes.book'}}), False)
    check('overlap not a box', E({'boxes_overlap': {'a': {'lit': [1, 2]}, 'b': 'keep_boxes.book'}}), False)

    # MALFORMED preconditions -> no match, never raise
    for bad in (
        None,
        'a string',
        123,
        [],
        {},
        {'lt': 'nope'},
        {'lt': [1]},
        {'all': 'nope'},
        {'not': {'lt': [1]}},
        {'bogus_op': [1, 2]},
        {'exists': {'in': 'regions'}},
        {'exists': 'nope'},
        {'forall': {'in': 'regions', 'as': 'r'}},
        {'boxes_overlap': 'nope'},
        {'in': [1, 2, 3]},
        {'eq': [1, 2], 'ne': [1, 2]},  # two operators
        {'path': 'x'},
    ):
        try:
            v, t = evaluate(bad, sig)
        except Exception as e:
            fails.append(f'malformed {bad!r} RAISED {e}')
            continue
        if v is not False:
            fails.append(f'malformed {bad!r} matched (should not)')
        if not isinstance(t, dict) or 'ok' not in t:
            fails.append(f'malformed {bad!r} produced no trace')

    # a MALFORMED clause must never fire, and must never INVERT into a match.
    # (Found by this selftest: {'not': {'lt': [1]}} used to evaluate True, because the
    # inner malformed node was False and 'not' happily inverted it. One corrupt KB
    # entry would then have matched every run.)
    check('bad under not', E({'not': {'lt': [1]}}), False)
    check('bad under not not', E({'not': {'not': {'bogus_op': 1}}}), False)
    check('bad in all', E({'all': [True, {'bogus_op': 1}]}), False)
    check('bad in any', E({'any': [True, {'bogus_op': 1}]}), False)
    check('bad nested deep', E({'all': [{'any': [{'not': {'zzz': 1}}]}]}), False)
    check('bad in where', E({'exists': {'in': 'regions', 'as': 'r', 'where': {'bogus_op': 1}}}), False)
    check('bad in filter', E({'exists': {'in': 'regions', 'as': 'r', 'filter': {'bogus_op': 1}, 'where': True}}), False)
    check(
        'good all still fires',
        E({'all': [{'in': [{'lit': 'pasteback_static'}, 'chain']}, {'lt': ['regions.a_hand.flow_mean', 0.12]}]}),
        True,
    )

    # not-a-dict signature, and deep recursion
    check('empty sig', evaluate({'lt': ['a.b', 1]}, {})[0], False)
    check('none sig', evaluate({'lt': ['a.b', 1]}, None)[0], False)
    deep = True
    for _ in range(60):
        deep = {'not': deep}
    try:
        check('depth guard', evaluate(deep, sig)[0] in (True, False), True)
    except Exception as e:
        fails.append(f'depth recursion RAISED {e}')

    # cyclic signature must not hang the deep-copy in normalize_signature
    cyc = {'regions': {}}
    cyc['self'] = cyc
    try:
        normalize_signature(cyc)
    except Exception as e:
        fails.append(f'cyclic signature RAISED {e}')

    # confidence update rule
    check('posterior prior only', posterior_confidence(0.92, 2.0, 0, 0), 0.92)
    check('posterior 1 success', posterior_confidence(0.92, 2.0, 1, 1), 0.9467)
    check('posterior 1 failure', posterior_confidence(0.92, 2.0, 1, 0), 0.6133)
    check('posterior clamp hi', posterior_confidence(1.0, 2.0, 50, 50), 0.99)
    check('posterior clamp lo', posterior_confidence(0.0, 2.0, 50, 0), 0.01)
    check('posterior junk', posterior_confidence('x', None, 'y', None), 0.5)
    check('posterior s>a', posterior_confidence(0.5, 2.0, 1, 99), 0.6667)

    # apply() purity + dotted set/remove
    base = {
        'pasteback': 'static',
        'keep_boxes': {'book': [0, 0, 1, 1], 'candle': [0, 0, 1, 1]},
        'probe': {'context_windows': False},
    }
    frozen = json.dumps(base, sort_keys=True)
    r1 = apply(
        {
            'resolved_action': {
                'set': {'pasteback': 'none', 'probe.context_windows': 'inherit'},
                'remove': ['keep_boxes.book'],
            }
        },
        base,
    )
    check('apply set', r1['pasteback'], 'none')
    check('apply dotted set', r1['probe']['context_windows'], 'inherit')
    check('apply remove', 'book' in r1['keep_boxes'], False)
    check('apply keeps sibling', 'candle' in r1['keep_boxes'], True)
    check('apply PURE', json.dumps(base, sort_keys=True), frozen)
    check('apply remove absent', 'x' in apply({'resolved_action': {'remove': ['nope.gone']}}, base), False)
    check('apply junk remedy', apply(None, base) == base, True)

    # placeholder substitution
    bnd = {'p': ('book', {'box': [0.495, 0.7, 0.825, 0.92], 'min_ncc': 0.61})}
    check('subst whole -> raw', _subst('{$p.box}', {}, bnd), [0.495, 0.7, 0.825, 0.92])
    check('subst key', _subst('{$p._key}', {}, bnd), 'book')
    check('subst inline', _subst('drop keep_boxes.{$p._key} now', {}, bnd), 'drop keep_boxes.book now')
    check('subst unresolved kept', _subst('{$zz.q}', {}, bnd), '{$zz.q}')

    # role inference
    check('role hand', _infer_role('a_hand'), 'character_hand')
    check('role hands', _infer_role('c_hands'), 'character_hand')
    check('role head', _infer_role('a_head'), 'character_head')
    check('role prop', _infer_role('pipe'), 'prop')

    if fails:
        print('SELFTEST FAILURES:')
        for f in fails:
            print('  -', f)
        return False
    print('remedy_kb selftest: ALL PASS')
    return True


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
