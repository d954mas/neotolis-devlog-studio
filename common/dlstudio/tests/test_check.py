"""Check gates: VQ-ASSET, VQ-WORDS, VQ-RES, VQ-OFFSET, and the VQ-SYNC
postcondition verify_output()."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from _builders import mk_design, plate_chunk, probe
from dlstudio.check import run_checks, verify_output
from dlstudio.compile import build_timeline
from dlstudio.ir import (
    AssetProbe,
    BeatPlacement,
    CheckIssue,
    IRBeat,
    IRMix,
    IROverlayItem,
    IRSegment,
    IRSegmentGeometry,
    Timeline,
    WordSpan,
)
from dlstudio.model import Beat, Chunk, Edit, Scene
from dlstudio.model.content import Overlay


# ── helpers to construct IR directly (isolate individual gates) ──────────────

def mk_beat(*, beat_id="b1", duration=4.0, segments=None, overlays=None):
    return IRBeat(
        id=beat_id, duration=duration, audio="vo.wav", words_path="w.json",
        words=[WordSpan(t0=0.0, t1=0.4, text="a")],
        segments=segments or [], overlays=overlays or [],
    )


def mk_timeline(*, beats=None, assets=None, warnings=None, diagnostics=None,
                resolution=(1080, 1920), asset_policy="compatibility"):
    beats = beats or [mk_beat()]
    return Timeline(
        edit_name="e", design=mk_design(resolution=resolution), beats=beats,
        placements=[BeatPlacement(beat_id=b.id, t0=0.0) for b in beats],
        mix=IRMix(), assets=assets or {}, output="out.mp4",
        asset_policy=asset_policy,
        warnings=warnings or [], diagnostics=diagnostics or [],
    )


def seg(
    src,
    kind="image",
    t0=0.0,
    t1=4.0,
    *,
    asset_id=None,
    render_manifest=None,
    editorial_role=None,
    transition_intent=None,
    offset=0.0,
    loop=False,
    expected_state_id=None,
    expected_build_id=None,
    expected_action_id=None,
    fit="cover",
    geometry=None,
):
    return IRSegment(
        kind=kind,
        src=src,
        offset=offset,
        t0=t0,
        t1=t1,
        asset_id=asset_id,
        render_manifest=render_manifest,
        editorial_role=editorial_role,
        transition_intent=transition_intent,
        loop=loop,
        fit=fit,
        geometry=geometry,
        expected_state_id=expected_state_id,
        expected_build_id=expected_build_id,
        expected_action_id=expected_action_id,
    )


def ov(chunk_index, z, t0, t1):
    return IROverlayItem(chunk_index=chunk_index, z=z, t0=t0, t1=t1)


# ── VQ-ASSET ─────────────────────────────────────────────────────────────────

def test_vq_asset_missing_file_errors():
    assets = {"gone.png": probe("gone.png", "image", exists=False)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not rep.ok
    codes = {i.code for i in rep.errors}
    assert "VQ-ASSET" in codes
    assert any(i.where == "gone.png" for i in rep.errors)


def test_vq_asset_all_present_passes():
    assets = {"there.png": probe("there.png", "image", width=1080, height=1920)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not any(i.code == "VQ-ASSET" for i in rep.issues)


def test_vq_asset_id_requires_binding_for_declared_gameplay():
    shot = seg(
        "data/footage/day5.mp4",
        kind="video",
        editorial_role="gameplay",
    )

    rep = run_checks(mk_timeline(
        beats=[mk_beat(segments=[shot])],
        asset_policy="production",
    ))

    assert any(issue.code == "VQ-ASSET-ID" for issue in rep.errors)


def test_draft_allows_unapproved_gameplay_placeholder():
    shot = seg(
        "data/footage/day5.mp4",
        kind="video",
        editorial_role="gameplay",
    )

    rep = run_checks(
        mk_timeline(beats=[mk_beat(segments=[shot])]),
        strict_assets=False,
    )

    assert not any(issue.code == "VQ-ASSET-ID" for issue in rep.errors)


def test_vq_asset_id_passes_exact_approved_binding(tmp_path, monkeypatch):
    artifact = tmp_path / "data" / "footage" / "day5.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"approved-gameplay")
    import hashlib

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata = tmp_path / "data" / "footage" / "day5.mp4.capture.json"
    metadata.write_bytes(b"metadata")
    game_report = tmp_path / "data" / "footage" / "day5.mp4.game.json"
    game_report.write_bytes(b"game-report")
    batch = tmp_path / "data" / "plan" / "capture_batch.json"
    batch.parent.mkdir(parents=True)
    batch.write_bytes(b"batch")
    results = tmp_path / "data" / "plan" / "capture_results.json"
    results.write_bytes(b"results")
    from dlstudio.services.asset_registry import (
        _register_ingested_captures,
        approve_asset,
    )

    registry = _register_ingested_captures(tmp_path, [{
        "request_id": "day5_station",
        "artifact_path": "data/footage/day5.mp4",
        "artifact_sha256": digest,
        "metadata_path": "data/footage/day5.mp4.capture.json",
        "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        "game_report_path": "data/footage/day5.mp4.game.json",
        "game_report_sha256": hashlib.sha256(game_report.read_bytes()).hexdigest(),
        "capture_batch_path": "data/plan/capture_batch.json",
        "capture_batch_sha256": hashlib.sha256(batch.read_bytes()).hexdigest(),
        "capture_results_path": "data/plan/capture_results.json",
        "capture_results_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day5.station.new_visual",
        "build_id": "exe-sha256:" + "a" * 64,
        "action_id": "station_queue_and_tram_pass",
        "seed": 42,
        "parameters": {},
        "initial_semantic_hash": "00000001",
        "action_semantic_hash": "00000002",
        "actual_duration": 11,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "client_area": True,
        "cursor_visible": False,
        "content_seconds": 1,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "frame_audit_passed": True,
            "game_elapsed_seconds": 11,
            "measured_playback_rate": 1.0,
            "presentation": {
                "output_width": 1080,
                "output_height": 1920,
                "fit": "contain",
                "scale": 1.0,
            },
        }])
    current = registry.assets[0]
    approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=digest,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    monkeypatch.chdir(tmp_path)
    shot = seg(
        "data/footage/day5.mp4",
        kind="video",
        asset_id="capture:day5_station",
        editorial_role="gameplay",
        t1=1,
        offset=5,
        expected_state_id="day5.station.new_visual",
        expected_build_id="exe-sha256:" + "a" * 64,
        expected_action_id="station_queue_and_tram_pass",
        fit="contain",
        geometry=IRSegmentGeometry.resolve(
            fit="contain",
            anchor_x=0.5,
            anchor_y=0.5,
            source_width=1080,
            source_height=1920,
            output_width=1080,
            output_height=1920,
        ),
    )

    rep = run_checks(mk_timeline(
        beats=[mk_beat(duration=1, segments=[shot])],
        asset_policy="production",
    ))

    assert not any(
        issue.code in {"VQ-ASSET-ID", "VQ-SOURCE-WINDOW"}
        for issue in rep.issues
    )

    shot.fit = "cover"
    shot.geometry = IRSegmentGeometry.resolve(
        fit="cover",
        anchor_x=0.5,
        anchor_y=0.5,
        source_width=1080,
        source_height=1920,
        output_width=1080,
        output_height=1920,
    )
    rep = run_checks(mk_timeline(
        beats=[mk_beat(duration=1, segments=[shot])],
        asset_policy="production",
    ))
    assert any(
        issue.code == "VQ-ASSET-PRESENTATION"
        for issue in rep.errors
    )

    shot.fit = "contain"
    shot.geometry = IRSegmentGeometry.resolve(
        fit="contain",
        anchor_x=0.5,
        anchor_y=0.5,
        source_width=1080,
        source_height=1920,
        output_width=1080,
        output_height=1920,
    )
    shot.offset = 0
    rep = run_checks(mk_timeline(
        beats=[mk_beat(duration=1, segments=[shot])],
        asset_policy="production",
    ))
    assert any(issue.code == "VQ-SOURCE-WINDOW" for issue in rep.errors)


def test_production_policy_rejects_unclassified_video():
    shot = seg("data/infographics/chart.mp4", kind="video")

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[shot])],
        asset_policy="production",
    ))

    assert any(issue.code == "VQ-ASSET-CLASS" for issue in report.errors)


def test_production_generated_video_requires_hash_bound_render_manifest():
    shot = seg(
        "data/infographics/chart.mp4",
        kind="video",
        editorial_role="presentation",
    )

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[shot])],
        asset_policy="production",
    ))

    assert any(
        issue.code == "VQ-ASSET-ID" and "render_manifest" in issue.message
        for issue in report.errors
    )


def test_production_generated_video_revalidates_render_manifest(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dlstudio.services.hyperframes.validate_hyperframes_render_manifest",
        lambda artifact, manifest, root, **kwargs: calls.append(
            (artifact, manifest, root, kwargs)
        ),
    )
    shot = seg(
        "data/infographics/chart.mp4",
        kind="video",
        render_manifest="data/infographics/chart.mp4.render.json",
        editorial_role="presentation",
    )

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[shot])],
        asset_policy="production",
    ))

    assert not any(issue.code == "VQ-ASSET-ID" for issue in report.errors)
    assert calls and calls[0][:2] == (
        "data/infographics/chart.mp4",
        "data/infographics/chart.mp4.render.json",
    )
    assert calls[0][3] == {"require_final": True}


def test_production_policy_rejects_gameplay_loop_and_missing_expectations():
    shot = seg(
        "data/footage/day5.mp4",
        kind="video",
        asset_id="capture:day5",
        editorial_role="gameplay",
        loop=True,
    )

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[shot])],
        asset_policy="production",
    ))

    codes = {issue.code for issue in report.errors}
    assert "VQ-GAMEPLAY-LOOP" in codes
    assert "VQ-ASSET-EXPECTATION" in codes


def test_production_policy_checks_exact_overlay_public_copy():
    overlay = ov(0, 0, 0.0, 4.0)
    overlay.public_text = ["VERSION 12", "Следующая остановка — Steam"]

    report = run_checks(mk_timeline(
        beats=[mk_beat(overlays=[overlay])],
        asset_policy="production",
    ))

    codes = {issue.code for issue in report.errors}
    assert "VQ-EDITORIAL-LABEL" in codes
    assert "VQ-PUBLIC-CLAIM" in codes


def test_vq_asset_present_but_unreadable_errors():
    assets = {"corrupt.mp4": probe("corrupt.mp4", "video", readable=False)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not rep.ok
    errs = [i for i in rep.errors if i.code == "VQ-ASSET"]
    assert errs and "unreadable" in errs[0].message
    assert errs[0].where == "corrupt.mp4"


def test_vq_asset_readable_true_passes():
    assets = {"ok.mp4": probe("ok.mp4", "video", duration=4.0, readable=True)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not any(i.code == "VQ-ASSET" for i in rep.issues)


def test_vq_asset_readable_undetermined_passes():
    # fonts/other kinds are never ffprobed; readable stays None and must not
    # be treated as broken.
    assets = {"font.ttf": probe("font.ttf", "font", readable=None)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not any(i.code == "VQ-ASSET" for i in rep.issues)


# ── VQ-GEOMETRY ─────────────────────────────────────────────────────────────

def test_vq_geometry_rejects_non_centered_coordinates_for_center_anchor():
    geometry = IRSegmentGeometry(
        fit="cover",
        anchor_x=0.5,
        anchor_y=0.5,
        source_width=200,
        source_height=100,
        scaled_width=200,
        scaled_height=100,
        output_width=100,
        output_height=100,
        crop_x=0,
        crop_y=0,
        crop_width=100,
        crop_height=100,
    )
    shot = seg("wide.mp4")
    shot.geometry = geometry
    timeline = mk_timeline(
        beats=[mk_beat(segments=[shot])],
        assets={"wide.mp4": probe("wide.mp4", "video", width=200, height=100)},
        resolution=(100, 100),
    )

    report = run_checks(timeline)

    assert any(issue.code == "VQ-GEOMETRY" for issue in report.errors)


# ── VQ-BOUNDARY / VQ-RESTART ────────────────────────────────────────────────

def test_gameplay_source_change_requires_transition_intent():
    first = seg("day4.mp4", kind="video", t0=0.0, t1=2.0,
                editorial_role="gameplay")
    second = seg("day5.mp4", kind="video", t0=2.0, t1=4.0,
                 editorial_role="gameplay")

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[first, second])],
    ))

    assert any(issue.code == "VQ-BOUNDARY" for issue in report.errors)


def test_continuous_same_take_requires_monotonic_source_offset():
    first = seg("take.mp4", kind="video", t0=0.0, t1=2.0,
                editorial_role="gameplay")
    second = seg("take.mp4", kind="video", t0=2.0, t1=4.0,
                 editorial_role="gameplay",
                 transition_intent="continuous_same_take")
    second.offset = 0.0

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[first, second])],
    ))

    assert any(issue.code == "VQ-RESTART" for issue in report.errors)


def test_continuous_same_take_accepts_expected_source_offset():
    first = seg("take.mp4", kind="video", t0=0.0, t1=2.0,
                editorial_role="gameplay")
    second = seg("take.mp4", kind="video", t0=2.0, t1=4.0,
                 editorial_role="gameplay",
                 transition_intent="continuous_same_take")
    second.offset = 2.0

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[first, second])],
    ))

    assert not any(
        issue.code in {"VQ-BOUNDARY", "VQ-RESTART"}
        for issue in report.issues
    )


def test_motivated_cut_allows_explicit_source_restart():
    first = seg("take.mp4", kind="video", t0=0.0, t1=2.0,
                editorial_role="gameplay")
    first.offset = 8.0
    second = seg("take.mp4", kind="video", t0=2.0, t1=4.0,
                 editorial_role="gameplay",
                 transition_intent="motivated_cut")
    second.offset = 0.0

    report = run_checks(mk_timeline(
        beats=[mk_beat(segments=[first, second])],
    ))

    assert not any(
        issue.code in {"VQ-BOUNDARY", "VQ-RESTART"}
        for issue in report.issues
    )


# ── VQ-WORDS ─────────────────────────────────────────────────────────────────

def test_vq_words_overlapping_overlays_errors():
    beat = mk_beat(overlays=[ov(0, 0, 0.0, 2.5), ov(1, 1, 2.0, 4.0)])  # 2.5 > 2.0
    rep = run_checks(mk_timeline(beats=[beat]))
    assert not rep.ok
    assert any(i.code == "VQ-WORDS" and "overlapping" in i.message for i in rep.errors)


def test_vq_words_unordered_overlays_errors():
    beat = mk_beat(overlays=[ov(0, 0, 3.0, 4.0), ov(1, 1, 1.0, 2.0)])  # goes backwards
    rep = run_checks(mk_timeline(beats=[beat]))
    assert any(i.code == "VQ-WORDS" and "out of order" in i.message for i in rep.errors)


def test_vq_words_tiled_overlays_pass():
    beat = mk_beat(overlays=[ov(0, 0, 0.0, 2.0), ov(1, 1, 2.0, 4.0)])
    rep = run_checks(mk_timeline(beats=[beat]))
    assert not any(i.code == "VQ-WORDS" for i in rep.issues)


def test_vq_words_out_of_range_index_from_compile_diagnostic(tmp_path):
    # end-to-end: compile appends a structured VQ-WORDS CheckIssue straight to
    # Timeline.diagnostics (plus the human-readable string in .warnings);
    # run_checks merges diagnostics with no parsing involved.
    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [{"word": "a", "start": 0.0, "end": 0.4}]}),
                  encoding="utf-8")
    beat = Beat(audio="vo.wav", words=str(wp), chunks=[plate_chunk(0, 0), plate_chunk(5, 9)])
    edit = Edit(name="e", design=mk_design(), beats={"b1": beat}, order=["b1"], output="o.mp4")
    probes = {
        "vo.wav": probe("vo.wav", "audio", duration=4.0),
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
    }
    tl = build_timeline(edit, probe=False, probes=probes)

    # structured diagnostic present on the IR itself, located to the beat
    diag_words = [d for d in tl.diagnostics if d.code == "VQ-WORDS"]
    assert diag_words and any("out of range" in d.message and d.where == "b1"
                              for d in diag_words)
    assert all(d.severity == "error" for d in diag_words)
    # the human-readable tagged string is still present in .warnings
    assert any(w.startswith("[b1] VQ-WORDS:") and "out of range" in w for w in tl.warnings)

    rep = run_checks(tl)
    assert not rep.ok
    words_errs = [i for i in rep.errors if i.code == "VQ-WORDS"]
    # the out-of-range index (from compile diagnostics) is promoted, located
    # to the beat; other VQ-WORDS errors (e.g. overlap) may also be present.
    assert any("out of range" in i.message and i.where == "b1" for i in words_errs)


# ── VQ-RES ───────────────────────────────────────────────────────────────────

def test_vq_res_dimension_over_4096_errors():
    # the 3840x6826 x264 OOM class
    rep = run_checks(mk_timeline(resolution=(3840, 6826)))
    assert not rep.ok
    assert any(i.code == "VQ-RES" and "exceeds encoder-safe" in i.message
               for i in rep.errors)


def test_vq_res_excessive_upscale_errors():
    assets = {"tiny.png": probe("tiny.png", "image", width=320, height=240)}
    beat = mk_beat(segments=[seg("tiny.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not rep.ok
    res = [i for i in rep.errors if i.code == "VQ-RES"]
    assert res and "upscales" in res[0].message


def test_vq_res_source_at_target_passes():
    assets = {"full.png": probe("full.png", "image", width=1080, height=1920)}
    beat = mk_beat(segments=[seg("full.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


def test_vq_res_within_2_2x_passes():
    # 540x960 -> 1080x1920 is exactly 2.0x, under the 2.2 cap
    assets = {"half.png": probe("half.png", "image", width=540, height=960)}
    beat = mk_beat(segments=[seg("half.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


def test_vq_res_unprobed_segment_skipped():
    beat = mk_beat(segments=[seg("unknown.png")])   # no probe in assets
    rep = run_checks(mk_timeline(beats=[beat], assets={}))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


# ── VQ-OFFSET (warn, not error) ──────────────────────────────────────────────

def test_vq_offset_warning_promoted_but_not_error():
    # diagnostics is what run_checks actually merges (no parsing); warnings
    # carries the matching human-readable string for display only.
    diag = CheckIssue(
        severity="warn", code="VQ-OFFSET",
        message="scene offset 99.00s is at/past source duration 10.00s "
                "for bg.mp4; clamped to 9.00s",
        where="b1",
    )
    tl = mk_timeline(
        diagnostics=[diag],
        warnings=["[b1] VQ-OFFSET: scene offset 99.00s is at/past source "
                  "duration 10.00s for bg.mp4; clamped to 9.00s"],
    )
    rep = run_checks(tl)
    assert rep.ok                                    # warn does not fail the gate
    offs = [i for i in rep.issues if i.code == "VQ-OFFSET"]
    assert offs and offs[0].severity == "warn"
    assert offs[0].where == "b1"


def test_vq_offset_clamp_from_compile_diagnostic(tmp_path):
    # end-to-end: compile's offset-past-EOF clamp lands in tl.diagnostics
    # directly, in addition to the tagged string in tl.warnings.
    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [{"word": "a", "start": 0.0, "end": 0.4}]}),
                  encoding="utf-8")
    beat = Beat(audio="vo.wav", words=str(wp), chunks=[
        Chunk(words=(0, 0), content=Overlay(text="O"),
              scene=Scene(kind="video", src="short.mp4", offset=50.0))])
    edit = Edit(name="e", design=mk_design(), beats={"b1": beat}, order=["b1"], output="o.mp4")
    probes = {
        "vo.wav": probe("vo.wav", "audio", duration=4.0),
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
        "short.mp4": probe("short.mp4", "video", duration=6.0, width=1080, height=1920),
    }
    tl = build_timeline(edit, probe=False, probes=probes)

    diag_offset = [d for d in tl.diagnostics if d.code == "VQ-OFFSET"]
    assert diag_offset
    assert diag_offset[0].severity == "warn"
    assert diag_offset[0].where == "b1"
    assert "short.mp4" in diag_offset[0].message

    rep = run_checks(tl)
    assert rep.ok       # warn only
    offs = [i for i in rep.issues if i.code == "VQ-OFFSET"]
    assert offs and offs[0].where == "b1"


def test_clean_timeline_passes_all_gates():
    assets = {"bg.png": probe("bg.png", "image", width=1080, height=1920),
              "vo.wav": probe("vo.wav", "audio", duration=4.0)}
    beat = mk_beat(segments=[seg("bg.png")],
                   overlays=[ov(0, 0, 0.0, 2.0), ov(1, 1, 2.0, 4.0)])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets))
    assert rep.ok and rep.issues == []


# ── VQ-SYNC / verify_output ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if shutil.which("ffmpeg") is None:      # pragma: no cover
        pytest.skip("ffmpeg not on PATH")
    d = tmp_path_factory.mktemp("media")
    mp4 = d / "clip.mp4"                     # 2s video + 2s audio (a real beat shape)
    video_only = d / "video_only.mp4"        # 2s video, no audio track
    torn = d / "torn.mp4"                    # 1s VIDEO inside a 3s container (0.5)
    wav = d / "silent.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=320x240:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)],
        check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=320x240:r=30",
         "-pix_fmt", "yuv420p", str(video_only)],
        check=True, capture_output=True)
    # The exact PLAN_STUDIO_V2 counterexample: video=1s, audio=3s,
    # container=3s. A container-only check calls this fine at expected=3s.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=1:s=320x240:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(torn)],
        check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
         "-t", "2", str(wav)],
        check=True, capture_output=True)
    return {"mp4": str(mp4), "video_only": str(video_only), "torn": str(torn),
            "wav": str(wav), "dir": str(d)}


def test_verify_output_passes_within_tolerance(media):
    verify_output(media["mp4"], 2.0, tolerance=0.25)     # ~2.0s, no raise


def test_verify_output_duration_mismatch_raises(media):
    with pytest.raises(RuntimeError, match="duration mismatch") as e:
        verify_output(media["mp4"], 10.0)
    # both durations reported (the fact the v1 bug hid)
    assert "2.0" in str(e.value) and "10.0" in str(e.value)


def test_verify_output_missing_file_raises():
    with pytest.raises(RuntimeError, match="does not exist"):
        verify_output("/no/such/file.mp4", 2.0)


def test_verify_output_no_video_stream_raises(media):
    with pytest.raises(RuntimeError, match="no video stream"):
        verify_output(media["wav"], 2.0)


def test_verify_output_stream_duration_mismatch_raises(media):
    """0.5 regression — the mandated counterexample: video=1s, audio=3s,
    container=3s, expected=3s MUST fail. The container duration is the max
    of the streams, so only a per-stream check can see the truncated video."""
    with pytest.raises(RuntimeError, match="video STREAM duration mismatch"):
        verify_output(media["torn"], 3.0, tolerance=0.35)


def test_verify_output_missing_audio_stream_raises(media):
    """0.5: every render output carries VO audio; its absence is an error by
    default (a beat that lost its audio track used to pass verify)."""
    with pytest.raises(RuntimeError, match="no audio stream"):
        verify_output(media["video_only"], 2.0)


def test_verify_output_require_audio_false_allows_video_only(media):
    verify_output(media["video_only"], 2.0, require_audio=False)  # no raise
