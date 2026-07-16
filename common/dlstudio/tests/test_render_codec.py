"""Codec-preset matrix (port of legacy compose_ffmpeg._codec_args)."""
from __future__ import annotations

import pytest

from dlstudio.render.beat import codec_args


def _join(args):
    return " ".join(args)


@pytest.mark.parametrize("quality,expect_preset,expect_crf,expect_ab", [
    ("draft", "ultrafast", "28", "160k"),
    ("preview", "veryfast", "22", "192k"),
    ("standard", "medium", "18", "192k"),
    ("upload", "medium", "18", "256k"),
    ("master", "slow", "16", "320k"),
])
def test_cpu_presets(quality, expect_preset, expect_crf, expect_ab):
    args, ab = codec_args(quality, gpu=False)
    j = _join(args)
    assert "libx264" in j
    assert f"-preset {expect_preset}" in j
    assert f"-crf {expect_crf}" in j
    assert "-pix_fmt yuv420p" in j
    assert "-rc" not in args               # CPU path has no NVENC rate control
    assert ab == expect_ab


@pytest.mark.parametrize("quality,expect_preset,expect_cq,expect_ab", [
    ("draft", "p1", "28", "160k"),
    ("preview", "p3", "24", "192k"),
    ("standard", "p4", "20", "192k"),
    ("upload", "p4", "20", "256k"),
    ("master", "p5", "16", "320k"),
])
def test_gpu_presets(quality, expect_preset, expect_cq, expect_ab):
    args, ab = codec_args(quality, gpu=True)
    j = _join(args)
    assert "h264_nvenc" in j
    assert f"-preset {expect_preset}" in j
    assert "-rc vbr" in j
    assert f"-cq {expect_cq}" in j
    assert "-crf" not in args
    assert "-pix_fmt yuv420p" in j
    assert ab == expect_ab


def test_unknown_quality_defaults_to_standard():
    args, ab = codec_args("", gpu=False)
    assert "-preset medium" in _join(args)
    assert ab == "192k"
