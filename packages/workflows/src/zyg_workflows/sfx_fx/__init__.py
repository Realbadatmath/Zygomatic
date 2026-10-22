# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sfx_fx.py — the SFX Studio's effect roster (2026-09-02).

sfx_merger.py shipped with ONE effect type ('tweak', a fixed rack of ffmpeg
filters) plus whatever plugin_host.py could load as VST3. That covered level,
pitch, trim, four tone knobs and a hint of room — enough to place a layer in a
merge, nowhere near enough to *redesign* a sound.

This module is the rest of it: every effect an sfx studio is expected to have,
each one a real DSP block with its own knob rack, declared in the same shape
sfx_merger.RACKS uses so the tab draws them with the knob code it already has
and the mixer's slot picker lists them without knowing they exist.

Two kinds of block:

  filter fx   build(p, ctx) -> [ffmpeg -af filter strings]
              These BATCH: a run of consecutive filter fx (and 'tweak' slots)
              collapses into one ffmpeg pass, so a ten-effect chain is still
              one process.

  render fx   render(p, src, dst) -> None
              Its own pass, for anything a single -af chain cannot express: a
              measure-then-apply two-pass (Normalize, Loudness), a chunked
              varispeed ramp (Doppler), a two-input graph (Convolution,
              Ping-pong). Same contract plugin_host.render() already had, so
              sfx_merger stages them the same way.

Licence: ffmpeg is an external TOOL — see feedback_licence_policy, copyleft in
a tool never reaches the asset. The convolution IRs are SYNTHESISED here from
noise and a decay curve, so no impulse-response pack's licence is involved
either.
"""

import hashlib
import math
import os
import subprocess
import tempfile
from zyg_workflows.bin import exe
import logging as _zyg_logging

# The sections of the original sfx_fx.py, imported in their original order so
# that module-level side effects still run exactly as they did.
from zyg_workflows.sfx_fx import helpers
from zyg_workflows.sfx_fx import dynamics
from zyg_workflows.sfx_fx import tone
from zyg_workflows.sfx_fx import time_pitch
from zyg_workflows.sfx_fx import space
from zyg_workflows.sfx_fx import modulation
from zyg_workflows.sfx_fx import restoration
from zyg_workflows.sfx_fx import utility
from zyg_workflows.sfx_fx import roster_a
from zyg_workflows.sfx_fx import roster_b
from zyg_workflows.sfx_fx import roster_c
from zyg_workflows.sfx_fx import roster


from zyg_workflows.sfx_fx.helpers import _SR
from zyg_workflows.sfx_fx.helpers import _FF_TIMEOUT
from zyg_workflows.sfx_fx.helpers import _k
from zyg_workflows.sfx_fx.helpers import _t
from zyg_workflows.sfx_fx.helpers import _s
from zyg_workflows.sfx_fx.helpers import _pick
from zyg_workflows.sfx_fx.helpers import _db
from zyg_workflows.sfx_fx.helpers import _q
from zyg_workflows.sfx_fx.helpers import _run
from zyg_workflows.sfx_fx.helpers import _ff

from zyg_workflows.sfx_fx.dynamics import _NORM_MODES
from zyg_workflows.sfx_fx.dynamics import _b_compressor
from zyg_workflows.sfx_fx.dynamics import _b_limiter
from zyg_workflows.sfx_fx.dynamics import _b_gate
from zyg_workflows.sfx_fx.dynamics import _b_expander
from zyg_workflows.sfx_fx.dynamics import _b_punch
from zyg_workflows.sfx_fx.dynamics import _b_deesser
from zyg_workflows.sfx_fx.dynamics import _b_autolevel
from zyg_workflows.sfx_fx.dynamics import _b_speechnorm
from zyg_workflows.sfx_fx.dynamics import _SOFTCLIP
from zyg_workflows.sfx_fx.dynamics import _b_softclip
from zyg_workflows.sfx_fx.dynamics import _b_psyclip
from zyg_workflows.sfx_fx.dynamics import _b_bitcrush
from zyg_workflows.sfx_fx.dynamics import _b_exciter
from zyg_workflows.sfx_fx.dynamics import _b_contrast
from zyg_workflows.sfx_fx.dynamics import _b_dcshift
from zyg_workflows.sfx_fx.dynamics import _measure
from zyg_workflows.sfx_fx.dynamics import _r_normalize
from zyg_workflows.sfx_fx.dynamics import _r_loudness

from zyg_workflows.sfx_fx.tone import _b_eq3
from zyg_workflows.sfx_fx.tone import _EQ18_HZ
from zyg_workflows.sfx_fx.tone import _b_eq18
from zyg_workflows.sfx_fx.tone import _b_dyneq
from zyg_workflows.sfx_fx.tone import _b_band
from zyg_workflows.sfx_fx.tone import _b_steepcut
from zyg_workflows.sfx_fx.tone import _b_tilt
from zyg_workflows.sfx_fx.tone import _b_crystalizer
from zyg_workflows.sfx_fx.tone import _b_subboost
from zyg_workflows.sfx_fx.tone import _b_virtualbass
from zyg_workflows.sfx_fx.tone import _EMPH_TYPES
from zyg_workflows.sfx_fx.tone import _b_emphasis
from zyg_workflows.sfx_fx.tone import _b_phaseshift

from zyg_workflows.sfx_fx.time_pitch import _b_pitchpro
from zyg_workflows.sfx_fx.time_pitch import _d_pitchpro
from zyg_workflows.sfx_fx.time_pitch import _b_stutter
from zyg_workflows.sfx_fx.time_pitch import _d_stutter
from zyg_workflows.sfx_fx.time_pitch import _b_silence
from zyg_workflows.sfx_fx.time_pitch import _d_silence
from zyg_workflows.sfx_fx.time_pitch import _b_trimsil
from zyg_workflows.sfx_fx.time_pitch import _FADE_CURVES
from zyg_workflows.sfx_fx.time_pitch import _b_fadepro
from zyg_workflows.sfx_fx.time_pitch import _DITHERS
from zyg_workflows.sfx_fx.time_pitch import _b_lofi
from zyg_workflows.sfx_fx.time_pitch import _probe_dur
from zyg_workflows.sfx_fx.time_pitch import _r_doppler

from zyg_workflows.sfx_fx.space import _b_reverb
from zyg_workflows.sfx_fx.space import _b_delay
from zyg_workflows.sfx_fx.space import _r_pingpong
from zyg_workflows.sfx_fx.space import _IR_CHARS
from zyg_workflows.sfx_fx.space import _ir_path
from zyg_workflows.sfx_fx.space import _r_convolve
from zyg_workflows.sfx_fx.space import _b_width
from zyg_workflows.sfx_fx.space import _ST_MODES
from zyg_workflows.sfx_fx.space import _b_stereotools
from zyg_workflows.sfx_fx.space import _b_haas
from zyg_workflows.sfx_fx.space import _b_crossfeed
from zyg_workflows.sfx_fx.space import _b_decorrelate
from zyg_workflows.sfx_fx.space import _b_compdelay
from zyg_workflows.sfx_fx.space import _b_autopan

from zyg_workflows.sfx_fx.modulation import _b_chorus
from zyg_workflows.sfx_fx.modulation import _b_flanger
from zyg_workflows.sfx_fx.modulation import _b_phaser
from zyg_workflows.sfx_fx.modulation import _b_tremolo
from zyg_workflows.sfx_fx.modulation import _b_vibrato
from zyg_workflows.sfx_fx.modulation import _b_ringmod
from zyg_workflows.sfx_fx.modulation import _b_dynsmooth
from zyg_workflows.sfx_fx.modulation import _b_spectral

from zyg_workflows.sfx_fx.restoration import _b_denoise
from zyg_workflows.sfx_fx.restoration import _WAVELETS
from zyg_workflows.sfx_fx.restoration import _b_denoise_wav
from zyg_workflows.sfx_fx.restoration import _b_denoise_nlm
from zyg_workflows.sfx_fx.restoration import _b_declick
from zyg_workflows.sfx_fx.restoration import _b_declip
from zyg_workflows.sfx_fx.restoration import _b_hum
from zyg_workflows.sfx_fx.restoration import _b_dialogue
from zyg_workflows.sfx_fx.restoration import _b_denorm

from zyg_workflows.sfx_fx.utility import _CH_OPS
from zyg_workflows.sfx_fx.utility import _CH_PAN
from zyg_workflows.sfx_fx.utility import _b_channel
from zyg_workflows.sfx_fx.utility import _b_gainstage

from zyg_workflows.sfx_fx.roster_a import _fx

from zyg_workflows.sfx_fx.roster import FX
from zyg_workflows.sfx_fx.roster import _BY_ID
from zyg_workflows.sfx_fx.roster import EFFECT_TYPES
from zyg_workflows.sfx_fx.roster import FILTER_IDS
from zyg_workflows.sfx_fx.roster import RENDER_IDS
from zyg_workflows.sfx_fx.roster import is_fx
from zyg_workflows.sfx_fx.roster import filters
from zyg_workflows.sfx_fx.roster import render
from zyg_workflows.sfx_fx.roster import dur_after

_zyg_log = _zyg_logging.getLogger(__name__)

#: The package IS the namespace sfx_fx.py had: every name above is re-exported.
__all__ = [
    'hashlib',
    'math',
    'os',
    'subprocess',
    'tempfile',
    'exe',
    '_zyg_logging',
    'helpers',
    'dynamics',
    'tone',
    'time_pitch',
    'space',
    'modulation',
    'restoration',
    'utility',
    'roster_a',
    'roster_b',
    'roster_c',
    'roster',
    '_SR',
    '_FF_TIMEOUT',
    '_k',
    '_t',
    '_s',
    '_pick',
    '_db',
    '_q',
    '_run',
    '_ff',
    '_NORM_MODES',
    '_b_compressor',
    '_b_limiter',
    '_b_gate',
    '_b_expander',
    '_b_punch',
    '_b_deesser',
    '_b_autolevel',
    '_b_speechnorm',
    '_SOFTCLIP',
    '_b_softclip',
    '_b_psyclip',
    '_b_bitcrush',
    '_b_exciter',
    '_b_contrast',
    '_b_dcshift',
    '_measure',
    '_r_normalize',
    '_r_loudness',
    '_b_eq3',
    '_EQ18_HZ',
    '_b_eq18',
    '_b_dyneq',
    '_b_band',
    '_b_steepcut',
    '_b_tilt',
    '_b_crystalizer',
    '_b_subboost',
    '_b_virtualbass',
    '_EMPH_TYPES',
    '_b_emphasis',
    '_b_phaseshift',
    '_b_pitchpro',
    '_d_pitchpro',
    '_b_stutter',
    '_d_stutter',
    '_b_silence',
    '_d_silence',
    '_b_trimsil',
    '_FADE_CURVES',
    '_b_fadepro',
    '_DITHERS',
    '_b_lofi',
    '_probe_dur',
    '_r_doppler',
    '_b_reverb',
    '_b_delay',
    '_r_pingpong',
    '_IR_CHARS',
    '_ir_path',
    '_r_convolve',
    '_b_width',
    '_ST_MODES',
    '_b_stereotools',
    '_b_haas',
    '_b_crossfeed',
    '_b_decorrelate',
    '_b_compdelay',
    '_b_autopan',
    '_b_chorus',
    '_b_flanger',
    '_b_phaser',
    '_b_tremolo',
    '_b_vibrato',
    '_b_ringmod',
    '_b_dynsmooth',
    '_b_spectral',
    '_b_denoise',
    '_WAVELETS',
    '_b_denoise_wav',
    '_b_denoise_nlm',
    '_b_declick',
    '_b_declip',
    '_b_hum',
    '_b_dialogue',
    '_b_denorm',
    '_CH_OPS',
    '_CH_PAN',
    '_b_channel',
    '_b_gainstage',
    '_fx',
    'FX',
    '_BY_ID',
    'EFFECT_TYPES',
    'FILTER_IDS',
    'RENDER_IDS',
    'is_fx',
    'filters',
    'render',
    'dur_after',
]
