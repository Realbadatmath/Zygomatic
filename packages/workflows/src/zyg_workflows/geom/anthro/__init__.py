# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro — measure generated bodies against real anthropometric distributions.

The reference pack under data/assets/anthro_reference/ is built once by build_reference.py
and read at runtime through reference.AnthroReference. Nothing in this package encodes an
aesthetic target: it answers "how unusual is this body, against which population, on which
measurement convention", and leaves any deliberate departure to a separately recorded
stylization delta.

Everything below is exported LAZILY. Importing geom.anthro.measure pulls in anny, torch
and a CUDA context, which is seconds of startup and a GPU allocation; a caller that only
wants a band out of the reference pack, or only wants to render a report someone else
produced, must not pay for that. `from geom.anthro import measure_mesh` still works — the
module is loaded at attribute access, not at package import.
"""

__version__ = '1'

# public name -> module it lives in
_LAZY = {
    # reference pack
    'AnthroReference': 'reference',
    'reference': 'reference',
    'SCHEMA_VERSION': 'reference',
    'WIDTHS': 'reference',
    # landmarks
    'resolve_landmarks': 'landmarks',
    'frame_report': 'landmarks',
    'CAGE_VERTS': 'landmarks',
    'CAGE_FACES': 'landmarks',
    # measurement
    'measure_mesh': 'measure',
    'compare_conventions': 'measure',
    'check_pose_and_frame': 'measure',
    'body_volume': 'measure',
    'slice_loops': 'measure',
    'HULL_CONVENTION': 'measure',
    'POLYLINE_CONVENTION': 'measure',
    'ISO_20685_1_TABLE4_MM': 'measure',
    'ISO_CAVEAT': 'measure',
    # mesh integrity
    'check_integrity': 'integrity',
    'mirror_symmetry': 'integrity',
    'triangulate_quads': 'integrity',
    'monotonic_chain': 'integrity',
    # reporting
    'build': 'report',
    'render_text': 'report',
    'render_summary': 'report',
    'render_percentile_strip': 'report',
    'render_measurements': 'report',
    'render_reference': 'report',
    'render_provenance': 'report',
    'ratio_rows': 'report',
    'write_json': 'report',
    'read_json': 'report',
    'report_path': 'report',
    'stable_sha': 'report',
    'verdict': 'report',
    'exit_code': 'report',
    'contract_fixture': 'report',
    'EXIT_CODES': 'report',
    'PASS': 'report',
    'WARN': 'report',
    'FAIL': 'report',
    'ERROR': 'report',
    # pack builder
    'build_pack': 'build_reference',
}

# gates.py is written in parallel with this file. Its names are listed so that
# `from geom.anthro import gate_character` works the moment it lands, and until then
# raises an AttributeError that NAMES the missing module instead of an opaque one.
_LAZY_OPTIONAL = {
    'gate_character': 'gates',
    'run_gates': 'gates',
    'GATE_REGISTRY': 'gates',
}

__all__ = sorted(list(_LAZY) + list(_LAZY_OPTIONAL))


def __getattr__(name):
    import importlib

    table = _LAZY if name in _LAZY else _LAZY_OPTIONAL
    mod_name = table.get(name)
    if mod_name is None:
        raise AttributeError('module %r has no attribute %r' % (__name__, name))
    try:
        mod = importlib.import_module('%s.%s' % (__name__, mod_name))
    except ImportError as e:
        raise AttributeError('%r lives in geom.anthro.%s, which could not be imported: %s' % (name, mod_name, e)) from e
    if mod_name == 'build_reference' and name == 'build_pack':
        value = mod.build
    else:
        try:
            value = getattr(mod, name)
        except AttributeError as exc:
            raise AttributeError('%r is not (yet) defined in geom.anthro.%s' % (name, mod_name)) from exc
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(list(globals()) + __all__))
