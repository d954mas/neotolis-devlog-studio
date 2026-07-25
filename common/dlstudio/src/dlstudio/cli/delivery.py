"""`dl2 deliver` — validate and assemble one production delivery bundle."""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def _source_path(root: Path, data_dir: Path, value: str | None, default: Path) -> Path:
    from dlstudio.cli import CliError

    raw = Path(value) if value is not None else default
    resolved = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    try:
        resolved.relative_to(data_dir.resolve())
    except ValueError as exc:
        raise CliError(f"delivery source must stay inside production data/: {resolved}") from exc
    return resolved


def cmd_deliver(args: argparse.Namespace) -> int:
    """Build the exact manifest-scoped bundle and record a delivery event."""
    from dlstudio.cli import CliError
    from dlstudio.cli.autopilot import _load_target
    from dlstudio.production import ProductionError, load_production_manifest
    from dlstudio.services.delivery import DeliveryError, build_delivery_bundle
    from dlstudio.services.publish_evidence import (
        PublishEvidenceError,
        validate_delivery_sources,
    )
    from dlstudio.services.telemetry import TelemetryError, record_telemetry_event
    from dlstudio.cli.telemetry import current_run_id

    started = time.perf_counter_ns()
    try:
        _edit, root, _canonical = _load_target(args.edit)
        manifest = load_production_manifest(root)
        video = _source_path(
            root, manifest.data_dir, args.video, Path("data/publish/video.mp4")
        )
        metadata = _source_path(
            root, manifest.data_dir, args.metadata, Path("data/publish/metadata.md")
        )
        image_name = "thumbnail.png" if manifest.kind == "devlog" else "cover.png"
        image = _source_path(
            root,
            manifest.data_dir,
            args.image,
            Path("data/publish") / image_name,
        )
        sources = validate_delivery_sources(
            manifest,
            video_path=video,
            metadata_path=metadata,
            image_path=image,
        )
        result = build_delivery_bundle(
            manifest,
            video_path=sources.video_path,
            metadata_path=sources.metadata_path,
            image_path=sources.image_path,
            overwrite=args.overwrite,
        )
        wall_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
        record_telemetry_event(
            manifest,
            stage="delivery",
            agent_role="packager",
            wall_ms=wall_ms,
            human_wait_ms=0,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            artifact_paths=(
                result.video_path,
                result.metadata_path,
                result.image_path,
                result.manifest_path,
            ),
            run_id=current_run_id(),
        )
    except (
        ProductionError,
        DeliveryError,
        PublishEvidenceError,
        TelemetryError,
    ) as exc:
        raise CliError(str(exc)) from exc

    print(f"[dl2] delivery -> {result.delivery_dir}")
    print(f"[dl2]   video: {result.video_path.name}")
    print(f"[dl2]   metadata: {result.metadata_path.name}")
    print(f"[dl2]   image: {result.image_path.name}")
    print(
        f"[dl2]   copied: {len(result.copied)}, "
        f"unchanged: {len(result.skipped)}"
    )
    return 0


def cmd_publish_evidence(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.cli.autopilot import _load_target
    from dlstudio.production import ProductionError, load_production_manifest
    from dlstudio.services.publish_evidence import (
        PublishEvidenceError,
        refresh_publish_evidence,
    )
    from dlstudio.cli.telemetry import record_automatic_stage

    started = time.perf_counter_ns()
    try:
        _edit, root, _canonical = _load_target(args.edit)
        manifest = load_production_manifest(root)
        result = refresh_publish_evidence(manifest, publish_path=args.publish_json)
    except (ProductionError, PublishEvidenceError) as exc:
        raise CliError(str(exc)) from exc
    print(f"[dl2] publish evidence -> {result.evidence_path}")
    print(f"[dl2] publish video -> {result.publish_video_path}")
    print(f"[dl2] exact video SHA-256: {result.video_sha256}")
    print(f"[dl2] exact review: {result.review_verdict}")
    record_automatic_stage(
        root, stage="publish_evidence", agent_role="packager",
        started_ns=started,
        artifact_paths=(result.publish_path, result.evidence_path, result.publish_video_path),
    )
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    deliver = sub.add_parser(
        "deliver",
        help="validate and assemble a production-scoped publish bundle",
    )
    deliver.add_argument(
        "edit", help="production path or product_id:production_id reference"
    )
    deliver.add_argument(
        "--video",
        help="source under production data/ (default: data/publish/video.mp4)",
    )
    deliver.add_argument(
        "--metadata",
        help="source under production data/ (default: data/publish/metadata.md)",
    )
    deliver.add_argument(
        "--image",
        help=(
            "source under production data/ (default: data/publish/thumbnail.png "
            "for devlogs, cover.png for reels)"
        ),
    )
    deliver.add_argument(
        "--overwrite",
        action="store_true",
        help="replace different destination bytes (same-hash files remain skips)",
    )
    deliver.set_defaults(func=cmd_deliver)

    evidence = sub.add_parser(
        "publish-evidence",
        help="bind publish.json to exact preflight, review, video, image, and metadata facts",
    )
    evidence.add_argument(
        "edit", help="production path or product_id:production_id reference"
    )
    evidence.add_argument(
        "--publish-json", help="publish package JSON (default: data/publish/publish.json)"
    )
    evidence.set_defaults(func=cmd_publish_evidence)


__all__ = ["add_subparser", "cmd_deliver", "cmd_publish_evidence"]
