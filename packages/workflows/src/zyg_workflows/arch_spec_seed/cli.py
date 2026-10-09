# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.cli — main() — validate every seed sheet and write it out.

Moved verbatim out of the 1,179-line arch_spec_seed.py; original lines 1140-1179.
"""

from __future__ import annotations

from zyg_workflows.arch_spec_seed.constants import HERE, json, os, sys

from zyg_workflows.arch_spec_seed.seeds import SEEDS


def main(argv):
    force = '--force' in argv
    sys.path.insert(0, os.path.join(HERE, 'arch_assistant_ext'))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        'object_specs', os.path.join(HERE, 'arch_assistant_ext', 'object_specs.py')
    )
    OS_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(OS_)
    os.makedirs(OS_.SPEC_DIR, exist_ok=True)
    wrote, skipped, bad = 0, 0, 0
    for s in SEEDS:
        s = dict(s)
        s.setdefault('written', '2026-09-08')
        errs = OS_.validate_spec(s)
        if errs:
            print(f'  BAD  {s.get("key")}: {"; ".join(errs)}')
            bad += 1
            continue
        path = os.path.join(OS_.SPEC_DIR, s['key'] + '.json')
        if os.path.exists(path) and not force:
            try:
                with open(path, encoding='utf-8') as fh:
                    old = json.load(fh)
            except Exception:  # noqa: BLE001
                old = {}
            if old.get('source') == 'researched':
                print(f'  keep {s["key"]} (researched, seed not applied)')
                skipped += 1
                continue
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(s, fh, ensure_ascii=False, indent=1, sort_keys=True)
        wrote += 1
    print(f'\n{wrote} written, {skipped} kept, {bad} rejected -> {OS_.SPEC_DIR}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
