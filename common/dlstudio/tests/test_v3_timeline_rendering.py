from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from _builders import find_system_font
from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    AssetRevisionRef,
    BlobRef,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.authoring.api import (
    Animation,
    AudioClip,
    Edit,
    MediaGeometry,
    MediaLayer,
    SolidLayer,
    TextLayer,
    VideoFade,
)
from dlstudio.authoring.compiler import compile_edit
from dlstudio.authoring.loader import load_edit
from dlstudio.foundation.api import canonical_bytes
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderOptions,
    render,
)
from dlstudio.rendering import api as rendering_api
from dlstudio.timeline.api import TimelineIR, VisualInstruction, check_timeline


class EmptyResolver:
    def path_for(self, _ref):
        raise AssertionError("solid-only fixture has no objects")

    def verify(self, _ref):
        raise AssertionError("solid-only fixture has no objects")


class FileResolver:
    def __init__(self, objects: Path) -> None:
        self.objects = objects

    def path_for(self, ref: BlobRef) -> Path:
        return self.objects / ref.sha256

    def verify_metadata(self, ref: BlobRef) -> None:
        path = self.path_for(ref)
        assert path.is_file()
        assert path.stat().st_size == ref.size

    def verify(self, ref: BlobRef) -> None:
        self.verify_metadata(ref)
        digest = hashlib.sha256()
        with self.path_for(ref).open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
        assert digest.hexdigest() == ref.sha256


def _asset(
    asset_id: str,
    source: Path,
    media: MediaFacts,
) -> AssetRevision:
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return AssetRevision(
        asset_id=asset_id,
        blob=BlobRef(digest, len(raw)),
        media=media,
        provenance=Provenance("provided", "test_fixture"),
        approval=Approval("validated", (digest,)),
        license=License("test-only", False, redistribution_allowed=False),
    )


def _install_object(source: Path, revision: AssetRevision, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, root / revision.blob.sha256)


def _edit(production_id: str = "fixture.vertical") -> Edit:
    return Edit(
        production_id=production_id,
        width=320,
        height=180,
        fps_num=30,
        fps_den=1,
        duration_ns=1_000_000_000,
        background="0x101820",
        visuals=(
            SolidLayer(
                start_ns=0,
                duration_ns=1_000_000_000,
                z=0,
                x=20,
                y=20,
                width=280,
                height=140,
                color="0xff5a36",
            ),
        ),
        standalone_story="A colored card appears and deliberately resolves.",
        kind="reel",
    )


def test_compile_produces_standalone_canonical_timeline() -> None:
    timeline = compile_edit(_edit())
    raw = timeline.canonical_bytes()
    assert TimelineIR.from_canonical_bytes(raw) == timeline
    assert timeline.timeline_id == (
        "fc66d169804cce3d28eb1d9d64a9cb16fc7060dbed4872f60be218342ed3a6ea"
    )
    assert not check_timeline(timeline).blocking
    assert b"resolver" not in raw
    assert b"fixture.vertical" in raw


def test_parallel_edits_share_no_mutable_timeline_state() -> None:
    first = compile_edit(_edit("fixture.one"))
    second = compile_edit(_edit("fixture.two"))
    assert first.timeline_id != second.timeline_id
    assert first.production_id == "fixture.one"
    assert second.production_id == "fixture.two"


def test_unreachable_asset_does_not_change_timeline_or_cache_identity(
    tmp_path: Path,
) -> None:
    unused = tmp_path / "unused.bin"
    unused.write_bytes(b"unused")
    revision = _asset(
        "unused.data", unused, MediaFacts(kind="data", format_name="bin")
    )
    base = _edit()
    with_unused = Edit(
        production_id=base.production_id,
        width=base.width,
        height=base.height,
        fps_num=base.fps_num,
        fps_den=base.fps_den,
        duration_ns=base.duration_ns,
        background=base.background,
        assets=(revision,),
        visuals=base.visuals,
        standalone_story=base.standalone_story,
        kind=base.kind,
    )
    assert compile_edit(with_unused).timeline_id == compile_edit(base).timeline_id


def test_canonical_timeline_rejects_surplus_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "unused.bin"
    source.write_bytes(b"unused")
    revision = _asset(
        "unused.data", source, MediaFacts(kind="data", format_name="bin")
    )
    with pytest.raises(ValueError, match="unreachable snapshots"):
        TimelineIR(
            **{
                **{
                    field: getattr(compile_edit(_edit()), field)
                    for field in (
                        "production_id",
                        "width",
                        "height",
                        "fps_num",
                        "fps_den",
                        "duration_ns",
                        "background",
                        "visuals",
                        "audio",
                        "metadata",
                    )
                },
                "assets": (
                    *compile_edit(_edit()).assets,
                    rendering_api.AssetSnapshot.from_revision(revision),
                ),
            }
        )


def test_canonical_ir_cannot_rebind_revision_ref_to_other_blob(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"trusted")
    revision = _asset(
        "fixture.media",
        source,
        MediaFacts(
            kind="image",
            format_name="raw",
            width=1,
            height=1,
        ),
    )
    edit = Edit(
        production_id="fixture.binding",
        width=1,
        height=1,
        fps_num=1,
        fps_den=1,
        duration_ns=1_000_000_000,
        background="black",
        assets=(revision,),
        visuals=(
            MediaLayer("fixture.media", 0, 1_000_000_000, 0, 0, 0, 1, 1),
        ),
        standalone_story="The exact trusted byte identity remains bound.",
    )
    wrapped = json.loads(compile_edit(edit).canonical_bytes())
    wrapped["payload"]["assets"][0]["revision"]["blob"] = {
        "sha256": "0" * 64,
        "size": 7,
    }
    tampered = canonical_bytes(
        wrapped["payload"],
        domain=TimelineIR.DOMAIN,
        version=TimelineIR.VERSION,
    )
    with pytest.raises(Exception, match="invalid TimelineIR"):
        TimelineIR.from_canonical_bytes(tampered)


@pytest.mark.performance_smoke
def test_cache_hit_skips_ffmpeg_and_returns_verified_bytes(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(crf=28, preset="ultrafast")
    cache = tmp_path / "cache"
    first = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    assert not first.cache_hit
    second = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "second.mp4",
        cache_root=cache,
    )
    assert second.cache_hit
    assert second.command == ()
    assert first.artifact == second.artifact
    assert hashlib.sha256((tmp_path / "second.mp4").read_bytes()).hexdigest() == (
        second.artifact.sha256
    )
    assert not (tmp_path / ".cache.auth-key").exists()


def test_cache_hit_rejects_changed_executor(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    cache = tmp_path / "cache"
    render(
        timeline,
        fingerprint,
        RenderOptions(preset="ultrafast"),
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    forged = replace(fingerprint, ffmpeg="definitely-no-such-ffmpeg")
    with pytest.raises(FileNotFoundError, match="unavailable"):
        render(
            timeline,
            forged,
            RenderOptions(preset="ultrafast"),
            EmptyResolver(),
            output=tmp_path / "second.mp4",
            cache_root=cache,
        )


def test_poisoned_cache_is_rebuilt_not_trusted(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(crf=28, preset="ultrafast")
    cache = tmp_path / "cache"
    first = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    cached = cache / "objects" / f"{first.artifact.sha256}.mp4"
    with cached.open("r+b") as handle:
        handle.seek(max(0, first.artifact.size // 2))
        handle.write(b"POISON")
    second = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "second.mp4",
        cache_root=cache,
    )
    assert not second.cache_hit
    assert second.artifact == first.artifact


def test_same_size_poison_with_restored_mtime_is_rebuilt(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(crf=28, preset="ultrafast")
    cache = tmp_path / "cache"
    first = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    cached = cache / "objects" / f"{first.artifact.sha256}.mp4"
    original = cached.stat()
    with cached.open("r+b") as handle:
        handle.seek(first.artifact.size // 2)
        original_byte = handle.read(1)
        handle.seek(first.artifact.size // 2)
        handle.write(bytes([original_byte[0] ^ 0xFF]))
    os.utime(cached, ns=(original.st_atime_ns, original.st_mtime_ns))
    second = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "second.mp4",
        cache_root=cache,
    )
    assert not second.cache_hit
    assert second.artifact == first.artifact


def test_manifest_cannot_redirect_to_mutated_object_under_original_hash(
    tmp_path: Path,
) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(preset="ultrafast")
    cache = tmp_path / "cache"
    first = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    cached = cache / "objects" / f"{first.artifact.sha256}.mp4"
    with cached.open("r+b") as handle:
        handle.seek(first.artifact.size // 2)
        byte = handle.read(1)
        handle.seek(first.artifact.size // 2)
        handle.write(bytes([byte[0] ^ 0xFF]))
    manifest_path = cache / "manifests" / f"{first.cache_key}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["size"] = cached.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    second = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "second.mp4",
        cache_root=cache,
    )
    assert not second.cache_hit
    assert second.artifact == first.artifact


def test_manifest_for_another_cache_key_is_rebuilt(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(preset="ultrafast")
    cache = tmp_path / "cache"
    first = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "first.mp4",
        cache_root=cache,
    )
    manifest_path = cache / "manifests" / f"{first.cache_key}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cache_key"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    second = render(
        timeline,
        fingerprint,
        options,
        EmptyResolver(),
        output=tmp_path / "second.mp4",
        cache_root=cache,
    )
    assert not second.cache_hit
    assert second.artifact == first.artifact


def test_same_key_concurrent_render_has_one_writer(tmp_path: Path) -> None:
    timeline = compile_edit(_edit())
    fingerprint = ExecutionFingerprint.detect()
    options = RenderOptions(crf=28, preset="ultrafast")
    cache = tmp_path / "cache"

    def run(position: int):
        return render(
            timeline,
            fingerprint,
            options,
            EmptyResolver(),
            output=tmp_path / f"{position}.mp4",
            cache_root=cache,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(item.cache_hit for item in results) == [False, True]
    assert results[0].artifact == results[1].artifact


def test_full_track_boundary_fade_is_interval_scoped(tmp_path: Path) -> None:
    timeline = compile_edit(
        replace(
            _edit("fixture.video-fades"),
            video_fades=(
                VideoFade("out", 400_000_000, 100_000_000),
                VideoFade("in", 500_000_000, 100_000_000),
            ),
        )
    )
    output = tmp_path / "video-fades.mp4"
    render(
        timeline,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        EmptyResolver(),
        output=output,
    )
    before = _pixel(output, 0.2)
    fade_out = [_pixel(output, at) for at in (0.41, 0.44, 0.47)]
    boundary = _pixel(output, 0.5)
    fade_in = [_pixel(output, at) for at in (0.53, 0.56, 0.59)]
    after = _pixel(output, 0.8)
    assert max(before) > 100
    assert [
        sum(pixel) for pixel in fade_out
    ] == sorted((sum(pixel) for pixel in fade_out), reverse=True)
    assert max(boundary) < 20
    assert [
        sum(pixel) for pixel in fade_in
    ] == sorted(sum(pixel) for pixel in fade_in)
    assert max(after) > 100


def test_text_font_is_path_bound_not_ffmpeg_media_input(tmp_path: Path) -> None:
    font_name = find_system_font()
    if font_name is None:
        pytest.skip("no real system font available")
    font = Path(font_name)
    revision = _asset(
        "fixture.font", font, MediaFacts(kind="font", format_name="ttf")
    )
    objects = tmp_path / "objects"
    _install_object(font, revision, objects)
    timeline = compile_edit(
        Edit(
            production_id="fixture.text",
            width=320,
            height=180,
            fps_num=30,
            fps_den=1,
            duration_ns=500_000_000,
            background="black",
            assets=(revision,),
            visuals=(
                TextLayer(
                    "Studio v3",
                    "fixture.font",
                    0,
                    500_000_000,
                    0,
                    20,
                    50,
                    280,
                    80,
                    36,
                ),
            ),
            standalone_story="Exact-font text appears and resolves.",
        )
    )
    result = render(
        timeline,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        FileResolver(objects),
        output=tmp_path / "text.mp4",
    )
    font_path = str(objects / revision.blob.sha256)
    graph = result.command[result.command.index("-filter_complex") + 1]
    assert "fontfile=" in graph
    assert revision.blob.sha256 in graph
    assert result.command.count(font_path) == 0
    assert result.path.stat().st_size > 1000


def test_text_box_geometry_changes_filtergraph(tmp_path: Path) -> None:
    font_name = find_system_font()
    if font_name is None:
        pytest.skip("no real system font available")
    font = Path(font_name)
    revision = _asset(
        "fixture.font", font, MediaFacts(kind="font", format_name="ttf")
    )
    objects = tmp_path / "objects"
    _install_object(font, revision, objects)

    def graph(width: int, height: int) -> str:
        timeline = compile_edit(
            Edit(
                production_id=f"fixture.text-box-{width}",
                width=320,
                height=180,
                fps_num=30,
                fps_den=1,
                duration_ns=500_000_000,
                background="black",
                assets=(revision,),
                visuals=(
                    TextLayer(
                        "bounded",
                        "fixture.font",
                        0,
                        500_000_000,
                        0,
                        20,
                        50,
                        width,
                        height,
                        24,
                    ),
                ),
                standalone_story="Text remains inside an exact raster box.",
            )
        )
        command = rendering_api._build_command(
            timeline,
            ExecutionFingerprint.detect(),
            RenderOptions(preset="ultrafast"),
            FileResolver(objects),
            tmp_path / f"{width}.mp4",
        )
        return command[command.index("-filter_complex") + 1]

    assert graph(280, 80) != graph(240, 60)


def test_resolved_media_geometry_is_replayed_exactly(tmp_path: Path) -> None:
    source = tmp_path / "frame.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=100x50",
            "-frames:v",
            "1",
            "-y",
            str(source),
        ],
        check=True,
    )
    revision = _asset(
        "fixture.frame",
        source,
        MediaFacts(kind="image", format_name="png", width=100, height=50),
    )
    objects = tmp_path / "objects"
    _install_object(source, revision, objects)
    timeline = compile_edit(
        Edit(
            production_id="fixture.exact-geometry",
            width=64,
            height=64,
            fps_num=30,
            fps_den=1,
            duration_ns=500_000_000,
            background="black",
            assets=(revision,),
            visuals=(
                MediaLayer(
                    "fixture.frame",
                    0,
                    500_000_000,
                    0,
                    0,
                    0,
                    64,
                    64,
                    geometry=MediaGeometry(100, 50, 128, 64, crop_x=32, crop_y=0),
                    transition_intent="motivated_cut",
                ),
            ),
            standalone_story="The resolved crop is replayed exactly.",
        )
    )
    command = rendering_api._build_command(
        timeline,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        FileResolver(objects),
        tmp_path / "geometry.mp4",
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "scale=128:64,crop=64:64:32:0" in graph
    assert timeline.visuals[0].transition_intent == "motivated_cut"


def test_base_track_uses_native_xfade_not_alpha_overlay(tmp_path: Path) -> None:
    revisions: list[AssetRevision] = []
    objects = tmp_path / "objects"
    for position, color in enumerate(("red", "blue")):
        source = tmp_path / f"{color}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=64x64",
                "-frames:v",
                "1",
                "-y",
                str(source),
            ],
            check=True,
        )
        revision = _asset(
            f"fixture.{color}",
            source,
            MediaFacts(kind="image", format_name="png", width=64, height=64),
        )
        _install_object(source, revision, objects)
        revisions.append(revision)
    timeline = compile_edit(
        Edit(
            production_id="fixture.native-xfade",
            width=64,
            height=64,
            fps_num=30,
            fps_den=1,
            duration_ns=2_000_000_000,
            background="black",
            assets=tuple(revisions),
            visuals=(
                MediaLayer(
                    revisions[0].asset_id,
                    0,
                    1_200_000_000,
                    0,
                    0,
                    0,
                    64,
                    64,
                    fit="stretch",
                ),
                MediaLayer(
                    revisions[1].asset_id,
                    1_000_000_000,
                    1_000_000_000,
                    0,
                    0,
                    0,
                    64,
                    64,
                    fit="stretch",
                    transition="fade",
                    transition_ns=200_000_000,
                ),
            ),
            standalone_story="A true crossfade joins two exact raster sources.",
        )
    )
    command = rendering_api._build_command(
        timeline,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        FileResolver(objects),
        tmp_path / "xfade.mp4",
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.2:offset=1" in graph
    assert "fade=t=in:st=1" not in graph


def test_duck_amount_changes_sidechain_render_graph(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "48000",
            "-y",
            str(wav),
        ],
        check=True,
    )
    revision = _asset(
        "fixture.tone",
        wav,
        MediaFacts(
            kind="audio",
            format_name="wav",
            duration_ns=1_000_000_000,
            sample_rate=48_000,
            channels=1,
            codec="pcm_s16le",
        ),
    )
    objects = tmp_path / "objects"
    _install_object(wav, revision, objects)

    def graph(amount: int) -> str:
        timeline = compile_edit(
            Edit(
                production_id=f"fixture.duck-{abs(amount)}",
                width=64,
                height=64,
                fps_num=30,
                fps_den=1,
                duration_ns=1_000_000_000,
                background="black",
                assets=(revision,),
                audio=(
                    AudioClip("fixture.tone", 0, 1_000_000_000, role="voice"),
                    AudioClip(
                        "fixture.tone",
                        0,
                        1_000_000_000,
                        role="music",
                        duck=True,
                    ),
                ),
                duck_amount_db_milli=amount,
                standalone_story="Voice deterministically ducks the music bed.",
            )
        )
        command = rendering_api._build_command(
            timeline,
            ExecutionFingerprint.detect(),
            RenderOptions(preset="ultrafast"),
            FileResolver(objects),
            tmp_path / f"{amount}.mp4",
        )
        return command[command.index("-filter_complex") + 1]

    shallow = graph(-6_000)
    deep = graph(-12_000)
    assert shallow != deep
    assert "ratio=4.000" in shallow
    assert "ratio=7.000" in deep


def test_invalid_geometry_and_non_base_special_transition_are_rejected() -> None:
    with pytest.raises(ValueError, match="text instructions support only cut/fade"):
        VisualInstruction(
            kind="text",
            start_ns=0,
            duration_ns=1,
            z=1,
            x=0,
            y=0,
            width=10,
            height=10,
            text="invalid",
            font_asset=AssetRevisionRef("fixture.font", "0" * 64),
            font_size=10,
            color="white",
            transition="slide_left",  # type: ignore[arg-type]
            transition_ns=1,
        )

    source = AssetRevision(
        asset_id="fixture.geometry",
        blob=BlobRef("1" * 64, 1),
        media=MediaFacts(kind="image", format_name="png", width=10, height=10),
        provenance=Provenance("provided", "test_fixture"),
        approval=Approval("validated", ("1" * 64,)),
        license=License("test-only", False, redistribution_allowed=False),
    )
    with pytest.raises(ValueError, match="resolved crop is outside scaled media"):
        compile_edit(
            Edit(
                production_id="fixture.invalid-geometry",
                width=10,
                height=10,
                fps_num=30,
                fps_den=1,
                duration_ns=1,
                background="black",
                assets=(source,),
                visuals=(
                    MediaLayer(
                        source.asset_id,
                        0,
                        1,
                        0,
                        0,
                        0,
                        10,
                        10,
                        geometry=MediaGeometry(
                            10,
                            10,
                            5,
                            5,
                            crop_x=4,
                            crop_y=4,
                        ),
                    ),
                ),
                standalone_story="Impossible geometry cannot enter canonical IR.",
            )
        )


def test_serialized_animations_execute_without_authoring_runtime(
    tmp_path: Path,
) -> None:
    source = tmp_path / "overlay.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red@0.8:s=64x64,format=rgba",
            "-frames:v",
            "1",
            "-y",
            str(source),
        ],
        check=True,
    )
    revision = _asset(
        "fixture.animated-overlay",
        source,
        MediaFacts(kind="image", format_name="png", width=64, height=64),
    )
    objects = tmp_path / "objects"
    _install_object(source, revision, objects)
    animations = (
        Animation("scale", 500, 1100, "out", 0, 300_000_000),
        Animation("x", 0, 1000, "linear", 0, 300_000_000),
        Animation("y", 0, 1000, "in", 0, 300_000_000),
        Animation("opacity", 0, 1000, "linear", 0, 300_000_000),
        Animation("rotate", 0, 1000, "in_out", 0, 300_000_000),
    )
    timeline = compile_edit(
        Edit(
            production_id="fixture.serialized-animation",
            width=64,
            height=64,
            fps_num=30,
            fps_den=1,
            duration_ns=500_000_000,
            background="black",
            assets=(revision,),
            visuals=(
                MediaLayer(
                    revision.asset_id,
                    0,
                    500_000_000,
                    1,
                    0,
                    0,
                    64,
                    64,
                    fit="stretch",
                    animations=animations,
                ),
            ),
            standalone_story="Serialized animation replays without a DSL resolver.",
        )
    )
    replayed = TimelineIR.from_canonical_bytes(timeline.canonical_bytes())
    assert replayed == timeline
    output = tmp_path / "animated.mp4"
    result = render(
        replayed,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        FileResolver(objects),
        output=output,
        cache_root=tmp_path / "cache",
    )
    assert result.artifact.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    graph = result.command[result.command.index("-filter_complex") + 1]
    assert "eval=frame" in graph
    assert "geq=" in graph
    assert "rotate=a=" in graph
    assert "overlay=x='(" in graph


def test_text_authoring_does_not_claim_unsupported_animation_contract() -> None:
    assert "animations" not in TextLayer.__dataclass_fields__


def test_legacy_sfx_port_covers_every_beat_and_clips_timeline_end() -> None:
    from tools.studio_v3_port_legacy import _sfx_specs

    first = SimpleNamespace(src="first.wav", t=0.25, gain_db=-2.0)
    last = SimpleNamespace(src="last.wav", t=0.75, gain_db=-3.0)
    timeline = SimpleNamespace(
        beats=(
            SimpleNamespace(id="first", sfx=(first,)),
            SimpleNamespace(id="last", sfx=(last,)),
        )
    )

    specs = _sfx_specs(
        timeline,
        {"first": 0.0, "last": 1.0},
        2_000_000_000,
        lambda _src, _kind: {"duration_ns": 500_000_000},
    )

    assert specs == [
        (first, 250_000_000, 500_000_000),
        (last, 1_750_000_000, 250_000_000),
    ]


def test_transition_anti_cut_gate_rejects_renderer_mutation() -> None:
    from tools.studio_v3_render_representatives import (
        _anti_cut_group,
        _guard_integrity,
    )

    group = {
        "kind": "xfade:fade",
        "start_ns": 1,
        "end_ns": 5,
        "frame_indices": [1, 2, 3, 4],
        "before_frame_index": 0,
        "after_frame_index": 5,
    }
    references = {
        index: bytes([value] * 16)
        for index, value in enumerate((0, 50, 100, 150, 200, 250))
    }
    hard_cut = {
        index: bytes([(0 if index <= 2 else 250)] * 16)
        for index in range(6)
    }
    late_hard_cut = {
        index: bytes([(0 if index < 5 else 250)] * 16)
        for index in range(6)
    }

    assert _anti_cut_group(group, references, references)["pass"] is True
    assert _anti_cut_group(group, references, hard_cut)["pass"] is False
    assert _anti_cut_group(group, references, late_hard_cut)["pass"] is False
    corrupted_guards = [
        {
            "mae_gray": 255.0,
            "dhash_hamming": 2000,
            "global_ssim": 0.0,
        }
        for _index in range(10)
    ]
    assert _guard_integrity(corrupted_guards)["pass"] is False


def _pixel(path: Path, at: float) -> tuple[int, int, int]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1,format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return tuple(completed.stdout[:3])  # type: ignore[return-value]


def test_delayed_media_starts_at_source_zero(tmp_path: Path) -> None:
    source = tmp_path / "red-blue.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=64x64:r=30:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=64x64:r=30:d=0.5",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=True,
    )
    revision = _asset(
        "fixture.video",
        source,
        MediaFacts(
            kind="video",
            format_name="mp4",
            duration_ns=1_000_000_000,
            width=64,
            height=64,
            fps_num=30,
            fps_den=1,
            codec="h264",
        ),
    )
    objects = tmp_path / "objects"
    _install_object(source, revision, objects)
    timeline = compile_edit(
        Edit(
            production_id="fixture.delayed",
            width=64,
            height=64,
            fps_num=30,
            fps_den=1,
            duration_ns=2_000_000_000,
            background="black",
            assets=(revision,),
            visuals=(
                MediaLayer(
                    "fixture.video",
                    1_000_000_000,
                    1_000_000_000,
                    0,
                    0,
                    0,
                    64,
                    64,
                    fit="stretch",
                ),
            ),
            standalone_story="Delayed red-to-blue media begins at source zero.",
        )
    )
    output = tmp_path / "delayed.mp4"
    render(
        timeline,
        ExecutionFingerprint.detect(),
        RenderOptions(preset="ultrafast"),
        FileResolver(objects),
        output=output,
    )
    early = _pixel(output, 1.1)
    late = _pixel(output, 1.7)
    assert early[0] > early[2] * 2
    assert late[2] > late[0] * 2


def test_fresh_process_renders_ir_without_authoring_import(
    tmp_path: Path,
) -> None:
    timeline = compile_edit(_edit())
    ir = tmp_path / "timeline.ir.json"
    ir.write_bytes(timeline.canonical_bytes())
    objects = tmp_path / "objects"
    objects.mkdir()
    output = tmp_path / "fresh.mp4"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "dlstudio.rendering.worker",
            "--ir",
            str(ir),
            "--objects",
            str(objects),
            "--output",
            str(output),
            "--cache",
            str(tmp_path / "cache"),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.stat().st_size > 1000
    worker_source = (
        Path(__file__).parents[1]
        / "src"
        / "dlstudio"
        / "rendering"
        / "worker.py"
    ).read_text(encoding="utf-8")
    assert "dlstudio.authoring" not in worker_source
    assert "GLOBAL_CHUNK_RESOLVER" not in worker_source


def test_representative_vertical_longform_and_voice_ports_compile() -> None:
    repo = Path(__file__).parents[3]
    ports = (
        repo
        / "not_a_trolley_problem"
        / "reels"
        / "2026_07_18_reel_02"
        / "v3_port.py",
        repo
        / "not_a_trolley_problem"
        / "devlogs"
        / "2026_07_22_devlog_01"
        / "v3_port.py",
        repo
        / "not_a_trolley_problem"
        / "devlogs"
        / "2026_07_17_devlog_01"
        / "v3_port.py",
    )
    timelines = [compile_edit(load_edit(path)) for path in ports]
    assert [item.metadata["kind"] for item in timelines] == [
        "reel",
        "devlog",
        "capture_vo",
    ]
    assert all(
        TimelineIR.from_canonical_bytes(item.canonical_bytes()) == item
        for item in timelines
    )
