# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.provenance_seal`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.provenance_seal` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.provenance_seal import seal, verify


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='provenance_seal', description='C2PA content credentials.')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p_verify = sub.add_parser('verify', help='read the credential in a file')
    p_verify.add_argument('path')
    p_sign = sub.add_parser('sign', help='seal a file in place')
    p_sign.add_argument('path')
    p_sign.add_argument('--pipeline', required=True)
    p_sign.add_argument('--run-id', default='')
    args = parser.parse_args(argv)

    if args.cmd == 'verify':
        res = verify(args.path)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res['sealed'] else 1
    res = seal(args.path, pipeline=args.pipeline, run_id=args.run_id, log_fn=lambda m: print(m, file=sys.stderr))
    print(json.dumps(res, indent=2, default=str))
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
