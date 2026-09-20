"""Legacy toggle/filter compatibility; active renderer exclusion is tested in test_short_loop."""
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock
import numpy as np
import pytest
from PIL import Image
from app.config.settings import Settings
from app.video.visualizer import prepare_visualizer, add_visualizer
from app.utils.ffmpeg import find_ffmpeg

ROOT=Path(__file__).resolve().parents[1]


def settings(**overrides):
    return Settings(_env_file=None,VISUALIZER_ENABLED=True,
        VISUALIZER_MUSIC_DISK_PATH=str(ROOT/'asset/music-disk.gif'),
        VISUALIZER_SOUNDWAVE_PATH=str(ROOT/'asset/soundwave.gif'),**overrides)


def test_disabled_visualizer_never_reads_assets(tmp_path):
    disabled=settings().model_copy(update={'visualizer_enabled':False,'visualizer_music_disk_path':'missing.gif'})
    assert prepare_visualizer(disabled,tmp_path) is None
    assert not list(tmp_path.iterdir())
    cmd=[];filters=['[0:v]copy[base]']
    assert add_visualizer(cmd,filters,'base',None,2,0)=='base'
    assert cmd==[] and filters==['[0:v]copy[base]']


def test_filter_zero_is_original_and_presets_valid():
    from app.video.branding import effect_filter
    for mode in ('none','vintage','old_film','warm_film','faded_film','noir','sepia','film_grain','cool_cinematic'):
        settings(VISUAL_EFFECT=mode)
        assert effect_filter(mode,0)==''
        if mode!='none':assert effect_filter(mode,.06)
