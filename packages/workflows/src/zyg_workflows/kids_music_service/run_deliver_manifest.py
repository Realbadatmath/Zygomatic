# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""manifest.json (version 3) for a kids_music_service run, section by section.

Extracted from `run_deliver.stage_deliver`, which was 417 lines. These builders are
pure apart from the `os.path.isfile` probes behind `rel_name` and the clock in
`_manifest_identity`: every other value comes from an argument. They are safe to keep
out of `kids_music_service/__init__.py`'s `_SUBMODULES` write-through tuple because
they read no patchable name off the package — the helpers that do (`chroma_follow`,
`_licence_note`, `_merge_voice_licences`) stayed in `run_deliver.py`.

The key order of each section is the published shape of the file on disk and is
preserved exactly as `stage_deliver` emitted it.
"""

from __future__ import annotations

import os
import time
from zyg_workflows import kids_music_theory as T


def rel_name(p):
    """The basename of `p` when it is a file on disk, else None — the manifest's file rule."""
    return os.path.basename(p) if p and os.path.isfile(p) else None


def build_manifest(
    *,
    ace_info,
    ace_mode,
    ace_mp3,
    ace_takes,
    attempts,
    brief,
    cinematic,
    fallback_safe,
    family,
    follow,
    gates,
    licence,
    lyric_info,
    lyric_src,
    master,
    midi,
    n_takes,
    ok,
    out_dir,
    pick,
    picked_leg,
    picked_take,
    plan,
    produced_status,
    render_engine,
    render_mp3,
    sampler_fallback,
    sampler_res,
    sc,
    singer,
    t0,
    trimmed_s,
    video,
    voice,
    why,
):
    """Assemble manifest.json (version 3) from the finished run.

    Pure apart from the `os.path.isfile` probes behind `rel_name`: every value comes
    from an argument. The key order below is the published shape of the file and the
    sections are emitted in it.
    """
    return {
        **_manifest_identity(brief=brief, cinematic=cinematic, family=family, ok=ok, t0=t0),
        'labels': _manifest_labels(brief=brief, cinematic=cinematic, family=family, plan=plan, singer=singer),
        **_manifest_sound(
            gates=gates,
            plan=plan,
            render_engine=render_engine,
            sampler_fallback=sampler_fallback,
            sampler_res=sampler_res,
            sc=sc,
        ),
        **_manifest_produced(
            ace_info=ace_info,
            ace_mode=ace_mode,
            ace_takes=ace_takes,
            attempts=attempts,
            n_takes=n_takes,
            picked_take=picked_take,
        ),
        'files': _manifest_files(
            ace_mp3=ace_mp3, master=master, midi=midi, out_dir=out_dir, render_mp3=render_mp3, voice=voice
        ),
        # The voice leg: the shipped take's review, what was repaired, how it
        # was mixed. None when no take was reviewed (instrumental, cinematic,
        # best-of-N, review off, or no take passed the singer gate).
        'voice': ({k: v for k, v in voice.items() if not k.startswith('_')} if voice else None),
        # The picture leg. `ok` is derived from an mp4 existing on disk, the same
        # rule the audio legs are held to — a video that failed to assemble says
        # so and gives the reason, rather than naming a file nothing can play.
        'video': video,
        'delivery': _manifest_delivery(
            fallback_safe=fallback_safe,
            follow=follow,
            gates=gates,
            master=master,
            pick=pick,
            picked_leg=picked_leg,
            produced_status=produced_status,
            trimmed_s=trimmed_s,
            why=why,
        ),
        **_manifest_lyrics(brief=brief, licence=licence, lyric_info=lyric_info, lyric_src=lyric_src),
    }


def _manifest_identity(*, brief, cinematic, family, ok, t0):
    """The manifest head: what workflow made it, whether it worked, and where it shelves."""
    return {
        # version 3 (2026-08-29): the manifest carries a picture leg.
        # `kind` names the WORKFLOW, and a cinematic cue is not a children's
        # song: it has its own output root, its own board and no picture leg, so
        # a reader that keys on `kind` must be able to tell them apart.
        'kind': 'melody' if cinematic else 'kidsmusic',
        'version': 3,
        # Derived from whether audio EXISTS, not from whether run() returned
        # normally. A run where both legs failed used to ship
        # delivery:{picked:null, reason:""} with zero gates and a green card.
        'ok': ok,
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'elapsed_s': round(time.time() - t0, 1),
        'title': brief['title'],
        # Where the song belongs in the Melodies library. Written by the run
        # that made it, so a styled song is on its shelf before anybody opens
        # the board — `_km_derive_shelf` only ever guesses for songs that
        # predate this. None on an unstyled brief, exactly as before.
        'family': family,
        'style': brief.get('style'),
        'shelf': brief.get('shelf'),
        # `.get` for style: an unstyled brief never carries the key at all, and
        # `brief[k]` over a fixed tuple would KeyError on every old-shaped run.
        'brief': dict(
            {
                k: brief[k]
                for k in (
                    'theme',
                    'age_band',
                    'mood',
                    'mode',
                    'meter',
                    'form',
                    'tonic',
                    'bpm',
                    'seconds',
                    'sung',
                    'singer',
                )
            },
            style=brief.get('style'),
        ),
    }


def _manifest_labels(*, brief, cinematic, family, plan, singer):
    """The display labels a card reads, looked up in the kids_music_theory tables."""
    # Family-aware: 'storytime' is a key in BOTH tables and means a sung
    # preschool song in one and a 3/4 oboe-and-harp cue in the other, so a
    # bare `T.STYLES[...]` lookup labelled half the cinematic shelf wrongly.
    _style_entry = T.style_lookup(brief.get('style'), family)[1]
    return dict(
        {
            # The cinematic band is 'Instrumental (cinematic)' in AGE_BANDS —
            # the parenthesis is there to explain the entry to a reader of that
            # table, and it is noise on a card that already says Cinematic.
            'age_band': ('Instrumental' if cinematic else T.AGE_BANDS[brief['age_band']]['label']),
            'mood': T.MOODS[brief['mood']]['label'],
            'meter': T.METERS[brief['meter']]['label'],
            'form': T.FORMS[brief['form']]['label'],
            'key': plan['key']['label'],
            'singer': singer['label'] if brief.get('sung') else 'Instrumental',
        },
        **({'style': _style_entry['label']} if _style_entry else {}),
    )


def _manifest_sound(*, gates, plan, render_engine, sampler_fallback, sampler_res, sc):
    """The `render`, `music`, `score` and `gates` sections: what was played and how it scored."""
    return {
        # What the score leg was actually PLAYED on. `files` carries counts, not
        # the sample id lists — those are in song.json under 'render_files',
        # because the board reads this manifest on every poll.
        'render': {
            'engine': render_engine,
            'voices': plan.get('voices') or None,
            # role → voice key, as the sampler actually assigned them. Not the
            # same thing as `voices`: a cinematic plan grows a fourth 'extra'
            # layer from `plan['extra']`, which the brief's voices dict never
            # named, and this is the only record that it was played.
            'layers': sampler_res.get('layers') or {},
            'files': {r: len(v or []) for r, v in (sampler_res.get('files') or {}).items()},
            'out_of_range_notes': sampler_res.get('out_of_range_notes'),
            'fallback_reason': sampler_fallback,
        },
        'music': {
            'bpm': plan['bpm'],
            'bars': plan['bars'],
            'seconds': plan['seconds'],
            'notes': len(plan['melody']),
            'order': plan['order'],
            'range': f'{sc["metrics"].get("range_low")}–{sc["metrics"].get("range_high")}',
            'progressions': sorted({'/'.join(s['progression']) for s in plan['sections']}),
            'lyric_fit': plan.get('lyric_fit', {}),
        },
        'score': {
            'total': sc['total'],
            'ok': sc['ok'],
            'metric_count': sc.get('metric_count'),
            'subscores': sc['subscores'],
            'metrics': sc['metrics'],
            'invariants': sc.get('invariants'),
            'invariants_ok': sc.get('invariants_ok'),
            'construction': sc.get('construction'),
            'fails': sc['fails'],
            'warnings': sc['warnings'],
            'seed': plan['seed'],
            'candidates': plan['search']['candidates_tried'],
            'min_score': plan['search'].get('min_score'),
            'met_min_score': plan['search'].get('met_min_score'),
        },
        'gates': gates,
    }


def _manifest_produced(*, ace_info, ace_mode, ace_takes, attempts, n_takes, picked_take):
    """The `produced` and `ace` sections: what ACE-Step was actually asked to do."""
    return {
        'produced': {
            # What ACTUALLY ran. None of this used to be recorded, so no shipped
            # song could be audited after the fact — and ACE_CHECKPOINT is
            # env-overridable, so a constant would not have been the truth.
            'ace_tags': ace_info.get('ace_tags', ''),
            'caption_negative': ace_info.get('caption_negative', ''),
            'lyrics_head': ace_info.get('lyrics_head', []),
            'checkpoint': ace_info.get('checkpoint', ''),
            'workflow': ace_info.get('workflow', ''),
            'melody_conditioned': ace_info.get('melody_conditioned'),
            'a2a_denoise': ace_info.get('a2a_denoise'),
            'seed': ace_info.get('seed'),
            # 0 = conditioned on the score render as composed; -12 = the take
            # that shipped was a re-seed on the melody an octave down.
            'lead_shift_st': ace_info.get('lead_shift_st', 0),
            'attempts': attempts,
        },
        # The two opt-in levers, and what they actually did. `mode` is the mode
        # ace_render RESOLVED (a cover source that would not stage falls back),
        # not the one that was asked for — both are here so a disagreement is
        # visible. `takes` is empty on the default path, which renders one take.
        'ace': {
            'mode': ace_info.get('mode') or (ace_mode if ace_mode != 'auto' else None),
            'mode_requested': ace_mode,
            'cover_source': ace_info.get('cover_source'),
            'takes_requested': n_takes,
            'takes': ace_takes,
            'picked': picked_take,
            'rank_note': (
                'lowest sung_pitch.rank_score among the takes that passed the singer gate'
                if n_takes > 1
                else 'single take — no ranking'
            ),
        },
    }


def _manifest_files(*, ace_mp3, master, midi, out_dir, render_mp3, voice):
    """The `files` section: every deliverable, by basename, only when it exists on disk."""
    return {
        'master': rel_name(master),
        'produced': rel_name(ace_mp3),
        'render': rel_name(render_mp3),
        'midi': rel_name(midi),
        'roll': rel_name(os.path.join(out_dir, 'roll.svg')),
        'plan': 'song.json',
        'lyrics': rel_name(os.path.join(out_dir, 'lyrics.txt')),
        'video': rel_name(os.path.join(out_dir, 'video.mp4')),
        'poster': rel_name(os.path.join(out_dir, 'poster.jpg')),
        'storyboard': rel_name(os.path.join(out_dir, 'storyboard.json')),
        'stems_vocals': (voice.get('stems') or {}).get('vocals'),
        'stems_backing': (voice.get('stems') or {}).get('backing'),
        'stems_vocals_unconverted': (voice.get('stems') or {}).get('vocals_unconverted'),
        'master_unconverted': rel_name(os.path.join(out_dir, 'master_unconverted.mp3')),
        'voice_report': 'voice_report.json' if os.path.isfile(os.path.join(out_dir, 'voice_report.json')) else None,
    }


def _manifest_delivery(*, fallback_safe, follow, gates, master, pick, picked_leg, produced_status, trimmed_s, why):
    """The `delivery` section: which file shipped, why, and whether it follows the tune."""
    return {
        # The MASTERED file, not the un-mastered one. All six shipped songs
        # read picked: song.mp3 while files.master was master.mp3 — and
        # song.mp3 spans -11.6 to -16.4 LUFS with positive true peak, while
        # master.mp3 spans -13.9 to -14.1 at -0.8 to -2.4 dBTP.
        'picked': rel_name(master) or rel_name(pick),
        'mastered_from': rel_name(pick),
        'picked_leg': picked_leg,
        'reason': why,
        'produced_status': produced_status,
        'fallback_safe': fallback_safe,
        'score_render_role': 'deliverable' if fallback_safe else 'diagnostic',
        'dead_tail_trimmed_s': trimmed_s,
        'loudnorm': ((gates.get('master') or {}).get('checks') or {}).get('loudnorm', {}).get('normalization_type'),
        # MEASURED, not asserted. Without melody conditioning the ACE leg
        # does not follow the composed tune — no note data reaches ACE-Step
        # at all, only tags, lyrics, seed, bpm, duration, time signature and
        # a pitch-class keyscale — and the chroma test against a cross-song
        # null says so every run rather than this being a constant somebody
        # has to remember to change.
        'melody_followed': follow.get('followed'),
        'melody_follow': follow,
        'legs': {
            'render': 'Score render — the composed tune, exactly as scored',
            'produced': ('ACE-Step variation (same key and lyric, different tune)'),
        },
    }


def _manifest_lyrics(*, brief, licence, lyric_info, lyric_src):
    """The lyric provenance tail of the manifest, and the licence record it ends on."""
    return {
        'lyrics_source': lyric_src,
        # WHICH MODEL WROTE IT. 'llm' alone was enough while there was only one model; with
        # Opus 5 on the subscription in front of the local fallback, a song whose lyric came
        # from qwen after a weekly-limit refusal would otherwise be indistinguishable in the
        # record from one Opus wrote. The video leg already records this (video.ideas.llm).
        'lyrics_model': lyric_info.get('model', ''),
        'lyrics_backend': lyric_info.get('backend', ''),
        'lyrics_backend_fallback': bool(lyric_info.get('fallback_backend')),
        'lyrics_fallback_reason': lyric_info.get('reason', ''),
        'lyrics_keys_seen': lyric_info.get('keys_seen', []),
        'lyrics_truncated': brief.get('lyrics_truncated', 0),
        'licence': licence,
    }
