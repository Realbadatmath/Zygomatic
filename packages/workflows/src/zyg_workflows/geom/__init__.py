# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom — geometry-backed asset pipeline: manifest, ingest, and the readable-geometry gate.

Pure python throughout. Anything that needs bpy lives in ../prop_mesh/ and is run as
`blender -b -P`, never imported.
"""
