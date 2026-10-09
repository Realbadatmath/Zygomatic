# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Add unique id attributes to every line-like element (line, polyline) in workflow chart SVGs.
IDs appear in gridview when selecting elements, e.g. LINE#workflow_2d-L1
"""

import re
import os
from pathlib import Path

SVG_DIR = Path(__file__).resolve().parent
# Chart prefix mapping: short id for uniqueness when multiple charts in DOM
CHART_PREFIXES = {
    'workflow_2d': 'w2d',
    'workflow_3d': 'w3d',
    'workflow_clipfarm': 'wcf',
    'workflow_distribution': 'wd',
    'workflow_maintenance': 'wm',
    'workflow_2d_state1': 'w2ds1',
    'workflow_3d_state1': 'w3ds1',
    'workflow_3d_state2': 'w3ds2',
    'workflow_3d_state3': 'w3ds3',
    'workflow_distribution_state1': 'wds1',
    'workflow_maintenance_state1': 'wms1',
    'workflow_clipfarm_state1': 'wcfs1',
    'agent_workflow_preset_state1': 'awps1',
    'diagram_boxes_and_arrows': 'dba',
    'diagram_boxes_and_arrows_13_steps': 'dba13',
    'agent_workflow_preset': 'awp',
    'authentication_pyramid_3d': 'ap3d',
    'authentication_pyramid_3d_state1': 'ap3ds1',
}


def get_chart_prefix(filename: str) -> str:
    """Get short prefix from filename (without .svg)."""
    base = filename.replace('.svg', '')
    return CHART_PREFIXES.get(base, base[:8] if len(base) > 8 else base)


def is_line_element(tag: str) -> bool:
    """True if element is a line-like graphic (line, polyline)."""
    return tag.lower() in ('line', 'polyline')


def fix_malformed_ids(content: str) -> str:
    """Fix malformed self-closing tags: "/ id="xxx"> -> "/>."""
    return re.sub(r'"/\s*id="[^"]*">', '"/>', content)


def process_svg(filepath: Path) -> int:
    """Add unique ids to line/polyline elements. Returns count of elements modified."""
    content = filepath.read_text(encoding='utf-8')
    content = fix_malformed_ids(content)
    prefix = get_chart_prefix(filepath.name)
    counter = [0]  # use list to allow modification in nested function

    def replace_line(m: re.Match) -> str:
        full = m.group(0)
        tag = m.group(1).lower()
        if not is_line_element(tag):
            return full
        if ' id=' in full or ' id="' in full or " id='" in full:
            return full  # already has id, skip
        counter[0] += 1
        lid = f'{prefix}-L{counter[0]}'
        new_attr = f' id="{lid}"'
        # Self-closing />: insert before /> to get ... id="lid"/>
        if full.rstrip().endswith('/>'):
            idx = full.rfind('/>')
            return full[:idx] + new_attr + ' ' + full[idx:]
        # Normal >: insert before >
        idx = full.find('>')
        return full[:idx] + new_attr + full[idx:]

    # Match <line ...> and <polyline ...> (both self-closing and with content)
    pattern = re.compile(r'<(line|polyline)(\s[^>]*)?>', re.IGNORECASE)
    new_content = pattern.sub(replace_line, content)
    if counter[0] > 0:
        filepath.write_text(new_content, encoding='utf-8')
    return counter[0]


def main():
    os.chdir(SVG_DIR)
    total = 0
    for f in sorted(SVG_DIR.glob('*.svg')):
        if f.name == 'brushed-metal.svg':
            continue  # texture, not a chart
        n = process_svg(f)
        if n > 0:
            print(f'{f.name}: {n} line ids added')
            total += n
    print(f'Total: {total} line elements assigned unique ids.')


if __name__ == '__main__':
    main()
