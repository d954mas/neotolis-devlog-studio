from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.authoring.api import AudioClip, Edit, SolidLayer, _compile_resolved
from dlstudio.foundation.api import BlobRef
from dlstudio.rendering.api import (
    ArtifactReport,
    ExecutionFingerprint,
    VoiceSignalEvidence,
    analyze_voice_signal,
    paired_ffprobe,
    verify_rendered_artifact,
)


def _timeline():
    return _compile_resolved(
        Edit(
            production_id="fixture.artifact-report",
            width=64,
            height=96,
            fps_num=30,
            fps_den=1,
            duration_ns=1_000_000_000,
            background="black",
            visuals=(
                SolidLayer(0, 1_000_000_000, 0, 0, 0, 64, 96, "black"),
            ),
            standalone_story="A final artifact report fixture.",
        )
    )


def _artifact(path: Path) -> BlobRef:
    raw = path.read_bytes()
    return BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))


def _render_fixture(path: Path, audio_source: str | None) -> BlobRef:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x96:r=30:d=1",
    ]
    if audio_source is not None:
        command.extend(("-f", "lavfi", "-i", audio_source, "-shortest"))
    command.extend(("-c:v", "libx264", "-pix_fmt", "yuv420p"))
    if audio_source is not None:
        command.extend(("-c:a", "aac"))
    command.extend(("-y", str(path)))
    subprocess.run(command, check=True)
    return _artifact(path)


def _voice_evidence(
    artifact: BlobRef,
    peak: int | None,
    active: int,
    correlation: int | None = -3_000,
) -> VoiceSignalEvidence:
    return VoiceSignalEvidence(artifact, peak, active, correlation)


def test_voice_required_report_blocks_digitally_silent_audio(
    tmp_path: Path,
) -> None:
    final = tmp_path / "silent.mp4"
    artifact = _render_fixture(final, "anullsrc=r=48000:cl=mono:d=1")

    report = verify_rendered_artifact(
        artifact,
        final,
        _timeline(),
        require_voice=True,
        voice_signal=_voice_evidence(artifact, None, 0, None),
    )

    assert report.blocking
    assert "audio.voice.silent" in {
        finding.rule for finding in report.findings
    }
    assert report.active_audio_ratio_milli == 0


def test_voice_required_report_accepts_audible_audio(tmp_path: Path) -> None:
    final = tmp_path / "audible.mp4"
    artifact = _render_fixture(
        final,
        "sine=frequency=440:sample_rate=48000:duration=1",
    )

    report = verify_rendered_artifact(
        artifact,
        final,
        _timeline(),
        require_voice=True,
        voice_signal=_voice_evidence(artifact, -10_000, 1000),
    )

    assert not report.blocking
    assert report.audio_codec == "aac"
    assert report.integrated_lufs_milli is not None
    assert report.true_peak_db_milli is not None
    assert report.active_audio_ratio_milli is not None
    assert report.active_audio_ratio_milli > 0
    assert ArtifactReport.from_canonical_bytes(report.canonical_bytes()) == report


def test_audible_music_cannot_mask_a_silent_voice_role(tmp_path: Path) -> None:
    silent = tmp_path / "silent.wav"
    music = tmp_path / "music.wav"
    for target, source in (
        (silent, "anullsrc=r=48000:cl=mono:d=1"),
        (music, "sine=frequency=440:sample_rate=48000:duration=1"),
    ):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, "-y", str(target)],
            check=True,
        )

    def revision(asset_id: str, source: Path) -> AssetRevision:
        return AssetRevision(
            asset_id,
            _artifact(source),
            MediaFacts(
                kind="audio",
                format_name="wav",
                duration_ns=1_000_000_000,
                sample_rate=48_000,
                channels=1,
                codec="pcm_s16le",
            ),
            Provenance("provided", "test_fixture"),
            Approval("pending"),
            License("test-only", False),
        )

    voice_revision = revision("voice.silent", silent)
    music_revision = revision("music.audible", music)
    timeline = _compile_resolved(
        Edit(
            production_id="fixture.voice-isolation",
            width=64,
            height=96,
            fps_num=30,
            fps_den=1,
            duration_ns=1_000_000_000,
            background="black",
            visuals=(SolidLayer(0, 1_000_000_000, 0, 0, 0, 64, 96, "black"),),
            audio=(
                AudioClip("voice.silent", 0, 1_000_000_000, role="voice"),
                AudioClip("music.audible", 0, 1_000_000_000, role="music"),
            ),
            voice_script="Narration must be audible independently of music.",
            standalone_story="Audible music cannot stand in for narration.",
        ),
        (voice_revision, music_revision),
    )

    class Resolver:
        def verify(self, ref: BlobRef) -> None:
            assert ref in {voice_revision.blob, music_revision.blob}

        def path_for(self, ref: BlobRef) -> Path:
            return silent if ref == voice_revision.blob else music

    final = tmp_path / "music-mix.mp4"
    artifact = _render_fixture(
        final,
        "sine=frequency=440:sample_rate=48000:duration=1",
    )
    voice_signal = analyze_voice_signal(
        artifact,
        final,
        timeline,
        Resolver(),
        ffmpeg="ffmpeg",
    )
    report = verify_rendered_artifact(
        artifact,
        final,
        timeline,
        require_voice=True,
        voice_signal=voice_signal,
    )

    assert report.active_audio_ratio_milli and report.active_audio_ratio_milli > 0
    assert report.voice_active_audio_ratio_milli == 0
    assert {finding.rule for finding in report.findings} >= {"audio.voice.silent"}


def test_audible_source_missing_from_exact_final_is_blocking(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=997:sample_rate=48000:duration=1",
            "-y", str(voice),
        ],
        check=True,
    )
    revision = AssetRevision(
        "voice.audible",
        _artifact(voice),
        MediaFacts(
            kind="audio",
            format_name="wav",
            duration_ns=1_000_000_000,
            sample_rate=48_000,
            channels=1,
            codec="pcm_s16le",
        ),
        Provenance("provided", "test_fixture"),
        Approval("pending"),
        License("test-only", False),
    )
    timeline = _compile_resolved(
        Edit(
            production_id="fixture.voice-dropped",
            width=64,
            height=96,
            fps_num=30,
            fps_den=1,
            duration_ns=1_000_000_000,
            background="black",
            visuals=(SolidLayer(0, 1_000_000_000, 0, 0, 0, 64, 96, "black"),),
            audio=(AudioClip("voice.audible", 0, 1_000_000_000, role="voice"),),
            voice_script="This audible take must exist in the exact final.",
            standalone_story="A renderer must not drop the voice branch.",
        ),
        (revision,),
    )

    class Resolver:
        def verify(self, ref: BlobRef) -> None:
            assert ref == revision.blob

        def path_for(self, ref: BlobRef) -> Path:
            assert ref == revision.blob
            return voice

    final = tmp_path / "music-only.mp4"
    artifact = _render_fixture(
        final,
        "sine=frequency=233:sample_rate=48000:duration=1",
    )
    evidence = analyze_voice_signal(
        artifact, final, timeline, Resolver(), ffmpeg="ffmpeg"
    )
    report = verify_rendered_artifact(
        artifact,
        final,
        timeline,
        require_voice=True,
        voice_signal=evidence,
    )

    assert evidence.true_peak_db_milli is not None
    assert evidence.active_audio_ratio_milli > 0
    assert (
        evidence.correlation_db_milli is None
        or evidence.correlation_db_milli <= -30_000
    )
    assert "audio.voice.silent" in {finding.rule for finding in report.findings}

    included = tmp_path / "voice-included.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=64x96:r=30:d=1", "-i", str(voice),
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-y", str(included),
        ],
        check=True,
    )
    included_artifact = _artifact(included)
    included_evidence = analyze_voice_signal(
        included_artifact, included, timeline, Resolver(), ffmpeg="ffmpeg"
    )
    included_report = verify_rendered_artifact(
        included_artifact,
        included,
        timeline,
        require_voice=True,
        voice_signal=included_evidence,
    )

    assert included_evidence.correlation_db_milli is not None
    assert included_evidence.correlation_db_milli > -30_000
    assert not included_report.blocking


def test_intentionally_silent_artifact_remains_valid(tmp_path: Path) -> None:
    final = tmp_path / "no-audio.mp4"
    artifact = _render_fixture(final, None)

    report = verify_rendered_artifact(
        artifact,
        final,
        _timeline(),
        require_voice=False,
    )

    assert not report.blocking
    assert report.audio_codec is None
    assert report.integrated_lufs_milli is None
    assert report.active_audio_ratio_milli is None


def test_artifact_report_rejects_a_different_exact_blob(tmp_path: Path) -> None:
    final = tmp_path / "audible.mp4"
    _render_fixture(
        final,
        "sine=frequency=440:sample_rate=48000:duration=1",
    )

    with pytest.raises(ValueError, match="exact artifact"):
        verify_rendered_artifact(
            BlobRef("0" * 64, final.stat().st_size),
            final,
            _timeline(),
            require_voice=True,
            voice_signal=_voice_evidence(
                BlobRef("0" * 64, final.stat().st_size), -10_000, 1000
            ),
        )


def test_verifier_uses_explicit_paired_toolchain_when_path_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = tmp_path / "audible.mp4"
    artifact = _render_fixture(
        final,
        "sine=frequency=440:sample_rate=48000:duration=1",
    )
    execution = ExecutionFingerprint.detect()
    probe = paired_ffprobe(execution.ffmpeg)
    monkeypatch.setenv("PATH", "")

    report = verify_rendered_artifact(
        artifact,
        final,
        _timeline(),
        require_voice=True,
        voice_signal=_voice_evidence(artifact, -10_000, 1000),
        ffmpeg=execution.ffmpeg,
        ffprobe=probe,
    )

    assert not report.blocking
    assert report.ffprobe_binary_sha256 == _artifact(Path(probe)).sha256
