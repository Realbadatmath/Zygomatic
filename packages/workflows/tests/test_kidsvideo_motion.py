# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Children's Music picture leg — every picture becomes an LTX-2.5 clip (2026-10-02).

CPU-only: no ComfyUI is contacted. ffmpeg is used for the clip-cutting test.
"""

import json
import os
import shutil
import subprocess
import pytest

from tests import _tree
from zyg_workflows import kids_video_service as KV
from zyg_workflows import ltx_hidream_service as LH
from zyg_workflows import pipeline_kidsmusic as PK

FFMPEG = shutil.which('ffmpeg')


def test_stage_list_has_animate_between_measure_and_assemble():
    i = PK.STAGES.index('Measure Frames')
    assert PK.STAGES[i + 1] == 'Animate'
    assert PK.STAGES[i + 2] == 'Assemble Video'


def test_board_card_exists_for_animate():
    """The board that drives this stage is the dashboard's, so its sources are read from
    the production tree; without that tree there is nothing here to check against."""
    js = open(_tree.crews('kanban_assets', 'kanban_main.js'), encoding='utf-8').read()
    assert "prompt: 'Animate'" in js
    html = open(_tree.crews('kanban.html'), encoding='utf-8').read()
    assert 'kanban_main.js?v=44' not in html


def test_default_family_is_hidream_unless_overridden():
    assert KV.MODEL_FAMILY in ('hidream', 'klein')
    if not os.environ.get('ZYG_KIDSVIDEO_FAMILY'):
        assert KV.MODEL_FAMILY == 'hidream'


def test_motion_prompt_keeps_first_frame_and_forbids_text():
    brief = {'theme': 'a friendly green tractor', 'mood': 'happy'}
    slot = {'i': 3, 'idea': 'the tractor drives past a red barn', 'motif': 'journey'}
    p = KV.motion_prompt(brief, slot)
    assert p.startswith('Use the provided start image as the first frame.')
    assert 'left to right' in p
    assert 'No text' in p
    assert 'nothing is added or removed' in p
    count = {'i': 4, 'idea': 'three red balloons', 'motif': 'count_up', 'draw': {'kind': 'count', 'n': 3}}
    assert 'bob gently' in KV.motion_prompt(brief, count)


def test_motion_clip_for_prefers_recorded_file_then_default(tmp_path):
    out = tmp_path
    (out / 'frames').mkdir()
    default = out / 'frames' / 'v007.mp4'
    default.write_bytes(b'x')
    assert KV.motion_clip_for({'i': 7}, str(out)) == str(default)
    assert KV.motion_clip_for({'i': 8}, str(out)) is None
    rec = out / 'frames' / 'custom.mp4'
    rec.write_bytes(b'y')
    assert KV.motion_clip_for({'i': 7, 'motion': {'file': 'frames/custom.mp4'}}, str(out)) == str(rec)
    # an empty recorded file is not a clip
    rec.write_bytes(b'')
    assert KV.motion_clip_for({'i': 7, 'motion': {'file': 'frames/custom.mp4'}}, str(out)) == str(default)


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg missing')
def test_clip_to_slot_cuts_and_pads(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_KIDSVIDEO_CPU_ENCODE', '1')
    src = tmp_path / 'src.mp4'
    subprocess.run(
        [
            FFMPEG,
            '-y',
            '-f',
            'lavfi',
            '-i',
            'testsrc=size=640x360:rate=24',
            '-t',
            '1.0',
            '-pix_fmt',
            'yuv420p',
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / 'slot.mp4'
    assert KV._clip_to_slot(str(src), str(out), 2.5, w=320, h=180, fps=24)
    probe = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-show_entries',
            'stream=width,height',
            '-show_entries',
            'format=duration',
            '-of',
            'json',
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    d = json.loads(probe.stdout)
    assert d['streams'][0]['width'] == 320 and d['streams'][0]['height'] == 180
    assert abs(float(d['format']['duration']) - 2.5) < 0.15  # padded from 1.0 s to the slot


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg missing')
def test_render_motion_uses_clip_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_KIDSVIDEO_CPU_ENCODE', '1')
    from PIL import Image

    still = tmp_path / 'f000.png'
    Image.new('RGB', (320, 180), (120, 200, 90)).save(still)
    src = tmp_path / 'v000.mp4'
    subprocess.run(
        [
            FFMPEG,
            '-y',
            '-f',
            'lavfi',
            '-i',
            'testsrc=size=320x180:rate=24',
            '-t',
            '1.0',
            '-pix_fmt',
            'yuv420p',
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    slot = {'i': 0, 'dur': 0.8, 'start': 0.0}
    out = tmp_path / 'c000.mp4'
    assert KV._render_motion(str(still), str(out), slot, [], w=320, h=180, fps=24, clip_path=str(src)) == 'ltx'
    out2 = tmp_path / 'c001.mp4'
    assert KV._render_motion(str(still), str(out2), slot, [], w=320, h=180, fps=24) == 'kenburns'


def test_registry_clears_hidream_and_ltx_weights():
    from zyg_workflows import licence_provenance as lp

    for name, kind in [
        ('hidream_o1_image_dev_fp8_scaled.safetensors', 'checkpoint'),
        (LH.LTX_UNET, 'checkpoint'),
        ('ltx-2.5-video-vae-bf16.safetensors', 'vae'),
        ('gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors', 'text_encoder'),
    ]:
        art = lp.classify_weight(name, kind=kind)
        assert art['status'] == 'cleared', (name, art)


def test_ltx_graph_sets_every_kids_input():
    g = LH.ltx_graph(
        'abc_f003.png', 'the duck waddles', seconds=3, seed=123, aspect='16:9 (Widescreen)', prefix='video/kids_t'
    )
    loads = [e for e in g.values() if e['class_type'] == 'LoadImage']
    assert loads and loads[0]['inputs']['image'] == 'abc_f003.png'
    prompts = [e for e in g.values() if e['class_type'] == 'PrimitiveStringMultiline']
    assert prompts and prompts[0]['inputs']['value'] == 'the duck waddles'
    assert g['sg362']['inputs']['value'] == 3
    seeds = [e['inputs']['noise_seed'] for e in g.values() if e['class_type'] == 'RandomNoise']
    assert seeds and all(sd == 123 for sd in seeds)
    saves = [e for e in g.values() if e['class_type'] == 'SaveVideo']
    assert saves[0]['inputs']['filename_prefix'] == 'video/kids_t'
    assert saves[0]['inputs']['format'] == 'auto'


def test_hidream_graph_aligns_to_32_and_uses_template_settings():
    g = LH.hidream_graph('a red tractor', width=1536, height=870, seed=5, negative='photo')
    lat = g['156']['inputs']
    assert lat['width'] == 1536 and lat['height'] == 864
    assert g['108']['inputs']['cfg'] == 1.0 and g['108']['inputs']['noise_seed'] == 5
    assert g['112']['inputs']['steps'] == LH.HIDREAM_STEPS
    assert g['124']['inputs']['noise_scale'] == LH.HIDREAM_NOISE_SCALE
    assert g['188']['inputs']['text'] == 'photo'


def test_clip_seconds_covers_slot_plus_transition():
    assert LH.clip_seconds(2.45) == 3  # 2.45 + 0.3 → 2.75 → 3
    assert LH.clip_seconds(2.9) == 4  # 2.9 + 0.3 → 3.2 → 4
    assert LH.clip_seconds(1.2) == 2
    assert LH.clip_seconds(0.4) == 2  # never below the 2 s floor


def test_no_paid_sdk_in_new_module():
    src = open(_tree.pkg('ltx_hidream_service.py'), encoding='utf-8').read()
    for bad in ('anthropic', 'openai', 'litellm', 'ollama'):
        assert bad not in src.lower().replace('no ollama', ''), bad
