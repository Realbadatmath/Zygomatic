# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""(1) per-beat prompt clipping and (2) the beat / context-window map (original lines 110-319).

Split out of wan_vace_service.py; the code below is unchanged.
"""

from zyg_workflows.wan_vace_service.base import _env_int, _log_noop

# ---------------------------------------------------------------------------
# (1) PER-BEAT PROMPT CLIPPING (2026-07-31)
#
# WHY: this file used to clip the WHOLE positive prompt with pos[:4000] and the whole
# negative with neg[:900]. Both numbers were invented and both are BINDING:
#   * the v9 positive measured 3997/4000 chars — three characters from the wall. Python
#     slices from the END, so the truncation eats the tail of the LAST beat, which is
#     exactly where the style clause lives (a measured contributor to style fade).
#   * the PROBE graph clipped at pos[:900], so every probe validated a MUTILATED prompt —
#     a gate that renders a different prompt from the run it gates is not a gate.
# The real constraint is not a global character budget at all: WanVideoTextEncode splits the
# positive on '|' (ComfyUI-WanVideoWrapper/nodes.py:342) and encodes EACH sub-prompt through
# umt5 separately, where the limit is 512 TOKENS PER SUB-PROMPT (~1500 chars at worst-case
# density). So the correct clip is per-beat, and a global clip is both too generous (it lets
# one beat blow past 512 tokens and get silently truncated inside the encoder) and too mean
# (it destroys the last beat when the aggregate happens to be long).
# The negative is NOT split by the wrapper (only the positive is), so it gets one flat clip —
# raised from 900 to the same 1500, measured at 853 chars = ~283 tokens, well inside 512.
# Every clip that actually fires now logs a WARNING naming the beat index and its length.
# ---------------------------------------------------------------------------

_BEAT_SEP = ' | '


def beat_char_limit():
    """Per-sub-prompt character budget. 1500 ~= 512 umt5 tokens at worst-case density."""
    return max(64, _env_int('ZYG_WAN_BEAT_CHARS', 1500))


def _clip_one(text, limit):
    """Hard clip to `limit`, then back off to the last ',' or ' ' within the final 40 chars
    so the cut does not land mid-word (a half-word is a garbage umt5 token). Returns the
    clipped string; callers compare lengths to decide whether to warn."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (',', ' '):
        i = cut.rfind(sep)
        if i >= limit - 40:
            cut = cut[:i]
            break
    return cut.rstrip().rstrip(',')


def clip_prompt_beats(prompt, limit=None, tag='positive', log_fn=None):
    """Clip EACH ' | ' sub-prompt to `limit` chars independently and rejoin with ' | '.

    Replaces the aggregate pos[:4000] / pos[:900] slices (see the header above). A prompt
    with no '|' is simply one beat and is clipped the same way — the 512-token encoder limit
    applies to it identically. NEVER truncates silently: any beat that is actually clipped
    logs a WARNING naming its index and both lengths."""
    log = log_fn or _log_noop
    if not prompt:
        return prompt
    lim = int(limit or beat_char_limit())
    beats = [b.strip() for b in str(prompt).split('|')]
    out = []
    fired = []
    for i, b in enumerate(beats):
        c = _clip_one(b, lim)
        if len(c) != len(b):
            fired.append((i, len(b), len(c)))
        out.append(c)
    if fired:
        for i, was, now in fired:
            log(
                f'[prompt-clip] WARNING: {tag} beat {i}/{len(beats) - 1} CLIPPED '
                f'{was} -> {now} chars (limit {lim}) — this beat exceeded the ~512 umt5 '
                'token budget; shorten it in the script or raise ZYG_WAN_BEAT_CHARS'
            )
    log(
        f'[prompt-clip] {tag}: {len(beats)} beat(s), lengths '
        f'{[len(b) for b in out]} (limit {lim}, {len(fired)} clipped)'
    )
    return _BEAT_SEP.join(out)


def clip_negative(neg, limit=None, log_fn=None):
    """Flat clip for the negative — the wrapper does NOT split negatives on '|'
    (only positive_prompt is split, nodes.py:342), so beats are meaningless here."""
    log = log_fn or _log_noop
    if not neg:
        return neg
    lim = int(limit or beat_char_limit())
    if len(neg) <= lim:
        return neg
    out = _clip_one(neg, lim)
    log(f'[prompt-clip] WARNING: negative CLIPPED {len(neg)} -> {len(out)} chars (limit {lim})')
    return out


# ---------------------------------------------------------------------------
# (2) BEAT / CONTEXT-WINDOW MAP (2026-07-31)
#
# WHY: scheduled ' | ' prompts are NOT distributed evenly over the clip. The wrapper picks
# one sub-prompt per context window with
#       prompt_index = min(int(max(c) / section_size), num_prompts - 1)   [nodes_sampler.py:1881]
#       section_size = latent_video_length / num_prompts                  [nodes_sampler.py:625]
# where max(c) is the LAST LATENT of the window — not its centre, not its first latent. Because
# window 0 already ends at latent 20 out of 87, any schedule with >= 5 beats makes
# int(20/section_size) >= 1, so BEAT 0 IS NEVER SELECTED BY ANY WINDOW. We shipped 5-beat
# schedules for weeks; the opening beat of every one of them was dead text that cost encode
# time and steered nothing.
#
# This function reproduces that arithmetic exactly so the schedule can be checked on the CPU
# in microseconds instead of discovered 90 minutes into a render.
# ---------------------------------------------------------------------------


def beat_window_map(num_frames, context_frames, context_overlap, num_beats, has_ref=True, context_stride=4, fps=17.0):
    """Which scheduled beat each context window will actually render.

    Mirrors ComfyUI-WanVideoWrapper exactly:
      latents        = (num_frames-1)//4 + 1, +1 when any VACE embed carries ref_images
                       (has_ref adds one latent frame to the noise tensor, nodes_sampler.py:338)
      ctx latents    = (context_frames-1)//4 + 1          [nodes_sampler.py:616]
      overlap latents= context_overlap // 4               [nodes_sampler.py:618]
      stride         = ctx - overlap                      [context.py:92, uniform_standard]
      windows        = [j, j+ctx-1] for j in range(0, latents, stride); the final window,
                       which would roll past the end, is SHIFTED BACK to end at latents-1
                       (context.py shift_window_to_end) rather than wrapping
      section_size   = latents / num_beats
      prompt_index   = min(int(last_latent / section_size), num_beats-1)

    Exact for the shipped config (context_stride//4 <= 1, i.e. context_stride < 8). Larger
    strides make uniform_standard emit additional coarser passes; that is flagged, not modelled.

    window_times is a REPORTING aid using the 4-frames-per-latent convention
    (latent L spans source frames 4L-3 .. 4L, clamped to the clip). It reproduces the
    published v9 window spans to one decimal. `mapping` is the authoritative artifact.

    Returns a dict: latents, windows, section_size, mapping, dead_beats, window_times,
    plus stride/ctx_latents/overlap_latents/context_windows_active/notes."""
    nf = int(num_frames)
    nb = max(1, int(num_beats))
    latents = (nf - 1) // 4 + 1 + (1 if has_ref else 0)
    ctx = (int(context_frames) - 1) // 4 + 1
    ov = int(context_overlap) // 4
    stride = max(1, ctx - ov)
    notes = []
    if int(context_stride) // 4 > 1:
        notes.append(
            f'context_stride={context_stride} -> latent stride '
            f'{int(context_stride) // 4} > 1: uniform_standard adds coarser passes '
            'this map does not model'
        )
    active = ctx < latents
    if not active:
        # wrapper disables context windows entirely when context_frames > num_frames
        windows = [(0, latents - 1)]
        notes.append(
            'context window shorter than the clip is impossible here — the wrapper '
            'runs a single full-length pass and scheduled prompts are not selected '
            'per-window'
        )
    else:
        windows = []
        for j in range(0, latents, stride):
            w = (j, j + ctx - 1) if (j + ctx) <= latents else (latents - ctx, latents - 1)
            if w not in windows:
                windows.append(w)
    section_size = latents / float(nb)
    mapping = [min(int(last / section_size), nb - 1) for (_first, last) in windows]
    dead = [b for b in range(nb) if b not in mapping]
    f = float(fps) or 17.0
    # 3dp, not 2: callers print these at 1dp and double rounding moves boundaries
    # (15.3529 -> 15.35 -> 15.3, but the honest 1dp value is 15.4)
    times = [(round(max(0, 4 * a - 3) / f, 3), round(min(4 * b + 1, nf) / f, 3)) for (a, b) in windows]
    return {
        'latents': latents,
        'ctx_latents': ctx,
        'overlap_latents': ov,
        'stride': stride,
        'windows': windows,
        'section_size': section_size,
        'mapping': mapping,
        'dead_beats': dead,
        'window_times': times,
        'context_windows_active': active,
        'notes': notes,
    }


def assert_no_dead_beats(
    num_frames, context_frames, context_overlap, num_beats, has_ref=True, context_stride=4, fps=17.0, log_fn=None
):
    """Raise ValueError naming every beat no context window will ever select.

    Returns the beat_window_map dict when the schedule is clean, so callers can log it."""
    log = log_fn or _log_noop
    m = beat_window_map(
        num_frames, context_frames, context_overlap, num_beats, has_ref=has_ref, context_stride=context_stride, fps=fps
    )
    for n in m['notes']:
        log(f'[beat-map] NOTE: {n}')
    log(
        f'[beat-map] {m["latents"]} latents, {len(m["windows"])} window(s) '
        f'{m["windows"]}, section_size {m["section_size"]:.2f}, mapping {m["mapping"]}'
    )
    if m['dead_beats']:
        spans = ', '.join(f'w{i}[{a}-{b}] -> beat {p}' for i, ((a, b), p) in enumerate(zip(m['windows'], m['mapping'])))
        raise ValueError(
            f'DEAD BEATS {m["dead_beats"]} — no context window selects them, so that text is '
            f'never rendered. {num_beats} beats over {m["latents"]} latents gives '
            f'section_size {m["section_size"]:.2f}; window 0 already ends at latent '
            f'{m["windows"][0][1]}. Windows: {spans}. Use <= 4 beats for this shot geometry '
            '(4 beats -> [0,1,2,2,3,3], no dead), or merge the dead beat into its neighbour.'
        )
    return m
