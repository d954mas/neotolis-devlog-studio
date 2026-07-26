from __future__ import annotations

import shutil
import subprocess
import json

import numpy as np
import pytest


def _frame(value: int, *, stripe: int | None = None) -> np.ndarray:
    image = np.full((24, 32), value, dtype=np.uint8)
    if stripe is not None:
        image[:, stripe : stripe + 3] = min(255, value + 70)
    return image


def test_cut_times_are_derived_from_ordered_shot_starts():
    from dlstudio.services.render_preflight import cut_times_from_shots

    shots = [
        {"id": "s01", "t0": 0.0, "t1": 1.0},
        {"id": "s02", "t0": 1.0, "t1": 2.5},
        {"id": "s03", "t0": 2.5, "t1": 4.0},
    ]

    assert cut_times_from_shots(shots) == (1.0, 2.5)


def test_boundary_gate_finds_one_frame_black_flash_and_blocks_final():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    samples = [
        FrameSample(index=i, time=i / 20, luma=_frame(180, stripe=i % 8))
        for i in range(21)
    ]
    samples[11] = FrameSample(index=11, time=0.55, luma=_frame(0))

    draft = analyze_frame_samples(samples, cut_times=[0.5], final=False)
    final = analyze_frame_samples(samples, cut_times=[0.5], final=True)

    assert [(issue.code, issue.severity) for issue in draft.issues] == [
        ("VQ-BOUNDARY", "warn")
    ]
    assert [(issue.code, issue.severity) for issue in final.issues] == [
        ("VQ-BOUNDARY", "error")
    ]
    assert "0.550s" in final.issues[0].message
    assert final.model_dump(mode="json")["issues"][0]["where"] == "cut@0.500s"


def test_boundary_gate_finds_stale_frame_after_cut():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    old = _frame(70, stripe=3)
    new = _frame(160, stripe=18)
    samples = []
    for i in range(21):
        time = i / 20
        image = old if time < 0.5 else new
        samples.append(FrameSample(index=i, time=time, luma=image.copy()))
    samples[12] = FrameSample(index=12, time=0.6, luma=old.copy())

    report = analyze_frame_samples(samples, cut_times=[0.5], final=False)

    assert [issue.code for issue in report.issues] == ["VQ-BOUNDARY"]
    assert "stale/foreign" in report.issues[0].message


def test_motion_gate_reports_adjacent_duplicates_and_stepped_motion():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    samples = []
    for i in range(24):
        step = i // 2
        samples.append(
            FrameSample(index=i, time=i / 24, luma=_frame(80, stripe=step % 20))
        )

    draft = analyze_frame_samples(
        samples, cut_times=[], motion_ranges=[(0.0, 1.0, "zoom")], final=False
    )
    final = analyze_frame_samples(
        samples, cut_times=[], motion_ranges=[(0.0, 1.0, "zoom")], final=True
    )

    assert [(issue.code, issue.severity) for issue in draft.issues] == [
        ("VQ-MOTION-SMOOTH", "warn")
    ]
    assert [(issue.code, issue.severity) for issue in final.issues] == [
        ("VQ-MOTION-SMOOTH", "error")
    ]
    assert "duplicate" in final.issues[0].message
    assert "stepped-motion" in final.issues[0].message


def test_smooth_motion_has_no_render_findings():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    base = np.tile(np.arange(32, dtype=np.uint8), (24, 1)) * 5
    samples = [
        FrameSample(
            index=i,
            time=i / 24,
            luma=np.roll(base, i, axis=1),
        )
        for i in range(24)
    ]

    report = analyze_frame_samples(
        samples, cut_times=[], motion_ranges=[(0.0, 1.0, "pan")], final=True
    )

    assert report.issues == []


def test_half_second_whole_frame_freeze_blocks_final_gameplay():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    samples = []
    for index in range(45):
        if index < 12:
            stripe = index
        elif index <= 27:
            stripe = 12
        else:
            stripe = index - 15
        samples.append(
            FrameSample(
                index=index,
                time=index / 30,
                luma=_frame(80, stripe=stripe % 29),
            )
        )

    report = analyze_frame_samples(
        samples,
        cut_times=[],
        freeze_ranges=[(0.0, 1.5, "gameplay")],
        final=True,
    )

    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("VQ-FREEZE", "error")
    ]
    assert "0.500s" in report.issues[0].message
    assert "[0.400,0.900]" in report.issues[0].message
    assert report.issues[0].where == "freeze@0.400s"


def test_short_frame_pause_is_not_a_freeze_candidate():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    samples = []
    for index in range(30):
        stripe = 8 if 8 <= index <= 13 else index
        samples.append(
            FrameSample(
                index=index,
                time=index / 30,
                luma=_frame(80, stripe=stripe % 29),
            )
        )

    report = analyze_frame_samples(
        samples,
        cut_times=[],
        freeze_ranges=[(0.0, 1.0, "gameplay")],
        final=True,
    )

    assert report.issues == []


def test_duplicated_every_other_frame_reports_stepped_capture_cadence():
    from dlstudio.services.render_preflight import FrameSample, analyze_frame_samples

    samples = [
        FrameSample(
            index=index,
            time=index / 30,
            luma=_frame(80, stripe=(index // 2) % 29),
        )
        for index in range(60)
    ]

    report = analyze_frame_samples(
        samples,
        cut_times=[],
        freeze_ranges=[(0.0, 2.0, "gameplay")],
        final=True,
    )

    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("VQ-CADENCE", "error")
    ]
    assert "adjacent duplicates 50.8%" in report.issues[0].message
    assert "alternating plateaus 47.5%" in report.issues[0].message


def test_deliberate_hold_is_excluded_from_freeze_ranges():
    from dlstudio.services.render_preflight import freeze_ranges_from_shots

    shots = [
        {
            "id": "gameplay",
            "t0": 0.0,
            "t1": 2.0,
            "src": "game.mp4",
            "motion": "native",
            "intent": "normal",
        },
        {
            "id": "ending",
            "t0": 2.0,
            "t1": 4.0,
            "src": "end.png",
            "motion": "static",
            "intent": "deliberate_hold",
        },
    ]

    assert freeze_ranges_from_shots(shots) == ((0.0, 2.0, "gameplay"),)


def test_deliberate_low_fps_demo_is_excluded_from_freeze_ranges():
    from dlstudio.services.render_preflight import freeze_ranges_from_shots

    shots = [
        {
            "id": "broken_capture_demo",
            "t0": 0.0,
            "t1": 3.0,
            "src": "before_gameplay.mp4",
            "motion": "native",
            "intent": "deliberate_low_fps_demo",
        },
        {
            "id": "smooth_proof",
            "t0": 3.0,
            "t1": 6.0,
            "src": "after_gameplay.mp4",
            "motion": "native",
            "intent": "payoff",
        },
    ]

    assert freeze_ranges_from_shots(shots) == ((3.0, 6.0, "smooth_proof"),)


def test_manifest_motion_gate_only_enforces_declared_continuous_effects():
    from dlstudio.services.render_preflight import motion_ranges_from_shots

    shots = [
        {"id": "gameplay", "t0": 0, "t1": 2, "src": "game.mp4", "motion": "native"},
        {"id": "text", "t0": 2, "t1": 4, "src": "card.mp4", "motion": "kinetic_text"},
        {"id": "hold", "t0": 4, "t1": 6, "src": "still.png", "motion": "subtle"},
        {"id": "zoom", "t0": 6, "t1": 8, "src": "still.png", "motion": "smooth_zoom"},
        {"id": "pan", "t0": 8, "t1": 10, "src": "still.png", "ken_burns": True},
    ]

    assert motion_ranges_from_shots(shots) == (
        (6.0, 8.0, "zoom"),
        (8.0, 10.0, "pan"),
    )


def test_missing_ffmpeg_is_a_graceful_warning(tmp_path, monkeypatch):
    from dlstudio.services import render_preflight

    artifact = tmp_path / "draft.mp4"
    artifact.write_bytes(b"not decoded because the tool is unavailable")
    monkeypatch.setattr(render_preflight.shutil, "which", lambda name: None)

    report = render_preflight.analyze_rendered_video(
        artifact, cut_times=[0.5], final=True
    )

    assert [(issue.code, issue.severity) for issue in report.issues] == [
        ("VQ-RENDER-TOOLS", "warn")
    ]


def test_shot_manifest_path_is_an_explicit_boundary_source(tmp_path, monkeypatch):
    from dlstudio.services import render_preflight

    artifact = tmp_path / "draft.mp4"
    artifact.write_bytes(b"fixture")
    manifest = tmp_path / "shot_manifest.json"
    manifest.write_text(json.dumps({"shots": [
        {"id": "s01", "t0": 0.0, "t1": 0.5, "motion": "static"},
        {"id": "s02", "t0": 0.5, "t1": 1.0, "motion": "static"},
    ]}), encoding="utf-8")
    samples = tuple(
        render_preflight.FrameSample(i, i / 10, _frame(160, stripe=i % 8))
        for i in range(11)
    )
    monkeypatch.setattr(render_preflight, "decode_rendered_frames", lambda path: samples)

    report = render_preflight.analyze_rendered_video(
        artifact, shot_manifest=manifest, final=False
    )

    assert not any("not evaluated" in issue.message for issue in report.issues)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)
def test_real_mp4_is_decoded_without_frame_resampling(tmp_path):
    from dlstudio.services.render_preflight import decode_rendered_frames

    artifact = tmp_path / "exact.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=10:duration=1", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(artifact),
        ],
        check=True,
    )

    samples = decode_rendered_frames(artifact)

    assert len(samples) == 10
    assert [sample.index for sample in samples] == list(range(10))
    assert samples[0].time == pytest.approx(0.0)
    assert samples[-1].time == pytest.approx(0.9)
    assert samples[0].luma.shape == (96, 96)
