"""Edit-level assembly — Phase 1: concat + duration postcondition.

Phase 1 concatenates the per-beat MP4s (all produced by `render_beat`, so
they share codec params: same libx264/nvenc profile, yuv420p, 48kHz aac) with
the concat demuxer under stream copy — no re-encode, exact-copy quality, fast.

Beat `transition_out` crossfades are DEFERRED to Phase 2: a real crossfade
needs re-encoding both beats and offsetting the second (xfade + the mix
graph), which is exactly the Phase-2 assemble pass. In Phase 1 any requested
transition_out degrades to a documented hard cut.

The full mix graph (music beds across beat boundaries, sidechain ducking keyed
by the VO stems `render_beat` drops next to each MP4, SFX at word anchors,
-14 LUFS loudnorm) is Phase 2 — see the TODO seam at the bottom.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from dlstudio.ir import Timeline

if TYPE_CHECKING:                      # avoid a package<->submodule import cycle
    from dlstudio.render import RenderOpts

DEFAULT_VERIFY_TOL = 0.5               # concat accumulates per-beat rounding


def _probe_duration(src: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", src],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _verify_duration(path: Path, expected: float,
                     tol: float = DEFAULT_VERIFY_TOL) -> None:
    actual = _probe_duration(str(path))
    if abs(actual - expected) > tol:
        raise RuntimeError(
            f"VQ-SYNC duration mismatch for {path}: probed {actual:.3f}s vs "
            f"expected {expected:.3f}s (tol {tol}s)"
        )


def _postcondition(path: Path, expected: float) -> None:
    try:
        from dlstudio.check import verify_output
        verify_output(str(path), expected)
    except NotImplementedError:
        _verify_duration(path, expected)


def assemble(timeline: Timeline, beat_files: dict[str, "Path"],
             opts: "RenderOpts") -> Path:
    """Concat rendered beats into `timeline.output` (stream copy). Beats are
    ordered by `timeline.beats` (concat order). Verifies total duration vs
    `timeline.duration` before returning."""
    out_path = Path(timeline.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ordered = [beat_files[b.id] for b in timeline.beats]
    if not ordered:
        raise RuntimeError("assemble: timeline has no beats")

    # Phase 1: hard cuts only. Note any requested crossfades as deferred.
    wanted = [b.id for b in timeline.beats if b.transition_out
              and b.transition_out.kind != "cut"]
    if wanted:
        print(f"[assemble] Phase 1: hard-cutting {len(wanted)} beat "
              f"transition(s) {wanted}; real crossfades land in Phase 2.")

    # concat demuxer list file. Forward slashes + single quotes + -safe 0 keep
    # Windows paths happy.
    list_file = out_path.parent / f".{out_path.stem}_concat.txt"
    lines = []
    for p in ordered:
        ap = str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{ap}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy",
           "-movflags", "+faststart", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        list_file.unlink()
    except OSError:
        pass
    if r.returncode != 0:
        dbg = out_path.parent / f"{out_path.stem}_ffmpeg_error.txt"
        dbg.write_text("CMD:\n" + " ".join(cmd) + "\n\nSTDERR:\n" + r.stderr,
                       encoding="utf-8")
        raise RuntimeError(f"ffmpeg concat failed (rc={r.returncode}). Debug: {dbg}")

    _postcondition(out_path, timeline.duration)

    # ── Phase 2 TODO seam: full mix graph ──────────────────────────────────
    # Replace the stream-copy concat above with a re-encoding assemble pass:
    #   1. video: xfade beats per transition_out (offset = cumulative beat
    #      durations minus accumulated crossfade), else concat filter.
    #   2. audio: layer IRMix.music spans across beat boundaries (amix), apply
    #      sidechaincompress ducking keyed by the per-beat *_vo_stem.wav files
    #      that render_beat writes, place IRSfx at their resolved times,
    #      then loudnorm to timeline.mix.target_lufs / true_peak_db.
    # Keep the duration postcondition; add the VQ-AUDIO LUFS postcondition.
    return out_path
