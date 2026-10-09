# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `LoraTrainerService._run_training`.

`_run_training` was 389 lines in one frame and needed a GPU, a SimpleTuner
checkout and a subprocess to reach any of it, so its two pure string readers —
the tqdm progress parser and the log-tail error picker — had never been
exercised at all. These tests are the first time they are.

Nothing here touches the GPU, the network or a service.
"""

import os

from zyg_workflows.lora_trainer_service import service_training as st


def test_a_training_bar_line_reports_its_step_and_total():
    """`parse_progress` reads the `| n/N [` group of a real `Steps:` line."""
    line = 'Epoch 3/6, Steps:  49%|████      | 981/2000 [55:01<56:40,  3.34s/it]'

    assert st.parse_progress(line) == (981, 2000)


def test_a_loading_bar_is_never_read_as_training_progress():
    """Only `Steps:`/`Epoch` bars count — this is the bug the guard exists for."""
    assert st.parse_progress('Loading weights: 100%|██████| 19/19 [00:04<00:00]') is None
    assert st.parse_progress('Generating bucket cache:  74%|███   | 740/1000 [00:02<00:01]') is None
    # no bar group at all
    assert st.parse_progress('Steps: starting up') is None
    # not a tqdm line in the first place
    assert st.parse_progress('') is None


def test_an_impossible_step_count_is_rejected():
    """`n > N` or `N == 0` is not progress; it is a misread bar."""
    assert st.parse_progress('Steps: 100%|█| 2001/2000 [00:01<00:00]') is None
    assert st.parse_progress('Steps:   0%|  | 0/0 [00:00<?, ?it/s]') is None
    # the boundary the guard does allow
    assert st.parse_progress('Steps: 100%|█| 2000/2000 [00:01<00:00]') == (2000, 2000)


def test_a_saved_checkpoint_line_yields_its_safetensors_path():
    """`saved_checkpoint_path` needs both the word *saved* and a .safetensors path."""
    line = 'INFO: Model weights saved to /srv/lora/char/checkpoint-500/pytorch_lora_weights.safetensors'

    assert st.saved_checkpoint_path(line) == '/srv/lora/char/checkpoint-500/pytorch_lora_weights.safetensors'
    # the word without a path, and a path without the word, are both nothing
    assert st.saved_checkpoint_path('INFO: checkpoint saved') is None
    assert st.saved_checkpoint_path('INFO: loading /srv/lora/a.safetensors') is None


def test_the_error_picker_prefers_the_newest_error_line():
    """`pick_real_error` walks the tail backwards and takes the first error it names."""
    tail = [
        'INFO: starting',
        'ERROR: first failure, older',
        'Traceback (most recent call last):',
        'INFO: cleaning up',
    ]

    assert st.pick_real_error(tail) == 'Traceback (most recent call last):'


def test_argparse_usage_lines_are_never_the_error_message():
    """A run that died on a bad flag printed thirty `[--flag]` lines after the cause."""
    tail = [
        'train.py: error: unrecognized arguments: --nope',
        '[--pretrained_model_name_or_path PRETRAINED]',
        '[--output_dir OUTPUT_DIR]',
    ]

    assert st.pick_real_error(tail) == 'train.py: error: unrecognized arguments: --nope'


def test_the_newest_line_with_content_is_the_fallback():
    """With no error line at all, the picker still answers something useful."""
    assert st.pick_real_error(['INFO: one', 'INFO: two', '   ', '']) == 'INFO: two'
    assert st.pick_real_error([]) == ''
    assert st.pick_real_error(['', '  \n']) == ''


def test_colour_codes_are_stripped_from_the_message():
    """`clean_error_line` removes the ANSI escapes SimpleTuner colours its log with."""
    assert st.clean_error_line('  \x1b[31mERROR: CUDA out of memory\x1b[0m \n') == 'ERROR: CUDA out of memory'
    assert st.pick_real_error(['\x1b[1;31merror: boom\x1b[0m']) == 'error: boom'


def test_each_family_has_its_own_vram_floor():
    """`vram_min_gb` answers the per-family default when the override is unset."""
    previous = os.environ.pop('ZYG_LORA_VRAM_MIN_GB', None)
    try:
        assert st.vram_min_gb('qwen') == 36.0
        assert st.vram_min_gb('klein') == 24.0
        assert st.vram_min_gb('sdxl') == 18.0
        # every other family, FLUX included, is the 30 GB default
        assert st.vram_min_gb('flux') == 30.0
        assert st.vram_min_gb('') == 30.0
    finally:
        if previous is not None:
            os.environ['ZYG_LORA_VRAM_MIN_GB'] = previous


def test_the_environment_override_beats_every_family_default():
    """`ZYG_LORA_VRAM_MIN_GB` is read for all families, as a float."""
    previous = os.environ.get('ZYG_LORA_VRAM_MIN_GB')
    os.environ['ZYG_LORA_VRAM_MIN_GB'] = '7.5'
    try:
        assert st.vram_min_gb('qwen') == 7.5
        assert st.vram_min_gb('flux') == 7.5
    finally:
        if previous is None:
            del os.environ['ZYG_LORA_VRAM_MIN_GB']
        else:
            os.environ['ZYG_LORA_VRAM_MIN_GB'] = previous


def test_the_training_environment_carries_config_path_and_the_vram_settings():
    """SimpleTuner finds its config.json only through CONFIG_PATH, so it must be set."""
    env = st.training_env('/srv/lora/cfg/char')

    assert env['CONFIG_PATH'] == '/srv/lora/cfg/char'
    assert env['PYTHONUNBUFFERED'] == '1'
    assert env['TOKENIZERS_PARALLELISM'] == 'false'
    assert env['PYTORCH_CUDA_ALLOC_CONF'] == 'expandable_segments:True'
    assert env['ST_ENABLE_GRADIENT_OFFLOAD'] == '1'
    # a copy of this process's environment, not a replacement for it
    assert env['PATH'] == os.environ['PATH']
    assert 'CONFIG_PATH' not in os.environ or os.environ['CONFIG_PATH'] != '/srv/lora/cfg/char'


def test_the_log_rotation_moves_the_previous_run_aside(tmp_path):
    """`rotate_training_log` leaves `<log>.prev` holding the run before this one."""
    log = tmp_path / 'training-flux.log'
    log.write_text('the previous run\n')

    st.rotate_training_log(str(log))

    assert not log.exists()
    assert (tmp_path / 'training-flux.log.prev').read_text() == 'the previous run\n'


def test_rotating_a_log_that_was_never_written_does_nothing(tmp_path):
    """A first run has no log to archive, and that is not an error."""
    log = tmp_path / 'training-sdxl.log'

    st.rotate_training_log(str(log))

    assert not log.exists()
    assert not (tmp_path / 'training-sdxl.log.prev').exists()


def test_a_run_that_must_stop_is_a_base_model_that_is_not_ready():
    """`BaseModel.ready` False is how `prepare_base_model` says "the caller returns"."""
    assert st.BaseModel().ready is True
    assert st.BaseModel(ready=False).ready is False
    # FLUX trains straight from _TRAIN_MODEL_PATH and sets none of the three
    default = st.BaseModel()
    assert (default.sdxl, default.qwen, default.klein) == (None, None, None)
