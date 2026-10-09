# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Per-kind prompt questions, the kind each step is asked as, and the bank assignment."""

from __future__ import annotations

from zyg_workflows.capabilities_questions.banks import BANKS, _banks
from zyg_workflows.capabilities_questions.core import q
from zyg_workflows.capabilities_questions.prompt_damage import PROMPT_DAMAGE


# Per-kind additions. The same worry, in the form it actually takes for that tool.
PROMPT_EXTRA = {
    'text': [
        q('pd_system_wins', 'A system prompt outranks the user text', '', '', True, 'Prompt: damage'),
        q('pd_role_needed', 'Needs a role preamble to behave', '', '', False, 'Prompt: clarity needed'),
        q(
            'pd_dilution',
            'A long prompt does not dilute the ask',
            'the instruction must survive the material it is buried in',
            '',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_format_decay',
            'Format contract survives a long prompt',
            'JSON obedience falls off as the prompt grows',
            '',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_injection',
            'Resists prompt injection',
            'instructions inside the material we paste in are data, not orders',
            '',
            True,
            'Prompt: damage',
        ),
        q('pd_tone_word', 'One tone word does not rewrite everything', '', '', True, 'Prompt: damage'),
        q(
            'pd_refuse_wording',
            'Wording alone does not trigger a refusal',
            'a period scene is not a safety event',
            '',
            True,
            'Prompt: damage',
        ),
        q(
            'pd_reasoning_budget',
            'Thinking budget that pays off',
            'where more reasoning stops improving the text',
            'tokens',
            True,
            'Prompt: limits',
        ),
    ],
    'image': [
        q(
            'pd_clip77',
            'Reads past the 77-token encoder window',
            'chunked or long-clip, not truncated',
            '',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_pos_neg_split',
            'The fix belongs in the negative prompt',
            'the house rule — a positive fix recolours the costume',
            '',
            True,
            'Prompt: steering',
        ),
        q('pd_style_vs_content', 'Style terms do not move the content', '', '', True, 'Prompt: damage'),
        q(
            'pd_count_words',
            'A counted noun renders that count',
            '"three barrels" is a prompt instruction, not a hint',
            '',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_verbatim',
            'An instruction passed verbatim is honoured',
            'rewording the instruction changes the render',
            '',
            True,
            'Prompt: steering',
        ),
    ],
    'video': [
        q('pd_clip77', 'Reads past the 77-token encoder window', '', '', True, 'Prompt: limits'),
        q(
            'pd_motion_words',
            'Motion verbs actually drive motion',
            'or the clip just breathes',
            '',
            True,
            'Prompt: steering',
        ),
        q(
            'pd_action_count',
            'Sequential actions in one prompt',
            'she turns, then lifts — how many beats survive',
            'count',
            True,
            'Prompt: limits',
        ),
        q('pd_camera_words', 'Camera language is obeyed', '', '', True, 'Prompt: steering'),
        q(
            'pd_prompt_vs_plate',
            'Prompt still matters beside the plate',
            'when a reference image is supplied, does the text do anything',
            '',
            True,
            'Prompt: steering',
        ),
    ],
    'audio': [
        q(
            'pd_text_vs_style',
            'Style prompt and content agree',
            'they must not fight: lyric versus genre, line versus direction',
            '',
            True,
            'Prompt: damage',
        ),
        q(
            'pd_tag_vocab',
            'Works outside a fixed tag vocabulary',
            'if only listed tags work, that list is the capability',
            '',
            True,
            'Prompt: clarity needed',
        ),
        q(
            'pd_spelling_sound',
            'Spelling does not distort pronunciation',
            'or the prompt needs phonetic respelling',
            '',
            True,
            'Prompt: damage',
        ),
        q(
            'pd_direction_words',
            'Direction words change the take',
            'tired, urgent, whispered — audible, not decorative',
            '',
            True,
            'Prompt: steering',
        ),
        q(
            'pd_punct_timing',
            'Punctuation drives timing predictably',
            'a comma is a pause, and always the same pause',
            '',
            True,
            'Prompt: damage',
        ),
    ],
    'judge': [
        q(
            'pd_question_wording',
            'The verdict survives a reworded question',
            'two phrasings of one defect must agree',
            '',
            True,
            'Prompt: damage',
        ),
        q(
            'pd_leading',
            'Resists a leading question',
            'asking "is the hand broken?" should not produce yes',
            '',
            True,
            'Prompt: damage',
        ),
        q('pd_yes_bias', 'No default-yes bias', '', '', True, 'Prompt: damage'),
        q(
            'pd_rubric_needed',
            'Needs the threshold spelled out',
            '"bad" has to be defined in the prompt',
            '',
            False,
            'Prompt: clarity needed',
        ),
        q(
            'pd_batched_questions',
            'Questions per prompt before it drifts',
            'one prompt asking twenty things answers the first five',
            'count',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_abstain',
            'Can answer "cannot tell"',
            'a forced verdict is a coin toss with a reason attached',
            '',
            True,
            'Prompt: clarity needed',
        ),
    ],
    'geometry': [
        q(
            'pd_dimension_words',
            'Named dimensions are honoured',
            'a 3 m wall comes out 3 m',
            '',
            True,
            'Prompt: steering',
        ),
        q(
            'pd_part_names',
            'Part vocabulary is understood',
            'the names for the pieces of the thing being built',
            '',
            True,
            'Prompt: clarity needed',
        ),
        q(
            'pd_count_words',
            'A counted feature renders that count',
            'five windows means five',
            '',
            True,
            'Prompt: limits',
        ),
        q(
            'pd_spatial_words',
            'Placement language is obeyed',
            'left of, behind, on top of',
            '',
            True,
            'Prompt: steering',
        ),
    ],
}

# Which kind each prompt-driven step is asked as. A step absent here is not driven by a
# prompt at all (pixel_gates is arithmetic, stem_split takes a file, video_assembly takes a
# cut list) and is deliberately NOT asked these questions — an untested column on a tool
# that has no prompt would be a lie by omission's opposite.
PROMPT_KIND = {
    'llm_script': 'text',
    'llm_prompt': 'text',
    'llm_agents': 'text',
    'llm_research': 'text',
    'subtitles': 'text',
    't2i': 'image',
    'i2i': 'image',
    'inpaint': 'image',
    'identity': 'image',
    'controlnet': 'image',
    'lora_train': 'image',
    'upscale': 'image',
    'i2v': 'video',
    't2v': 'video',
    'v2v': 'video',
    'vfx': 'video',
    'lipsync': 'video',
    'tts': 'audio',
    'voice_clone': 'audio',
    'voice_direction': 'audio',
    'voice_conversion': 'audio',
    'music_gen': 'audio',
    'melody': 'audio',
    'sfx_gen': 'audio',
    'sfx_library': 'audio',
    'sfx_process': 'audio',
    'audio_mix': 'audio',
    'stt': 'audio',
    'vlm_judges': 'judge',
    'detectors': 'judge',
    'text_judges': 'judge',
    'audio_judges': 'judge',
    'identity_gates': 'judge',
    'diarization': 'judge',
    'mesh_gen': 'geometry',
    'mesh_qc': 'geometry',
    'arch': 'geometry',
    'render3d': 'geometry',
    'grooms': 'geometry',
    'movement': 'video',
    'poses': 'video',
    'gestures': 'video',
    'facial': 'video',
    'muscle': 'video',
    'body_fit': 'judge',
    'rigging': 'geometry',
}


# The four bands, in the order the sheet reads them.
PROMPT_GROUPS = ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering']


def prompt_bank(kind):
    """The prompt-damage questions for one kind of prompt-driven tool.

    The per-kind extras are MERGED INTO their band rather than appended after it: the
    header draws a group band from each consecutive run of one group name, so a stray
    'Prompt: damage' question sitting after the steering block would draw a second damage
    band four columns wide and read as a different section.
    """
    core = PROMPT_DAMAGE + PROMPT_EXTRA.get(kind, [])
    out = []
    for g in PROMPT_GROUPS:
        out.extend(c for c in core if c['group'] == g)
    out.extend(c for c in core if c['group'] not in PROMPT_GROUPS)
    return out


for _s, _k in PROMPT_KIND.items():
    BANKS[_s] = _banks(BANKS.get(_s, []), prompt_bank(_k))
