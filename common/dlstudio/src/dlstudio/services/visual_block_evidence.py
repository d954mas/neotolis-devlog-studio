"""Machine-verifiable evidence for proof-oriented HyperFrames blocks."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


PROOF_TEMPLATES = {"day-card", "before-after", "focus-callout", "cta-endcard"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must contain one JSON object: {path}")
    return value


def _inside(root: Path, raw: object, *, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise RuntimeError(f"{label} requires a relative path.")
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{label} must stay inside the production root.") from exc
    return path


def _production_root(project: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit.resolve()
        if not (root / "data" / "assets" / "registry.json").is_file():
            raise RuntimeError(
                f"production root has no approved asset registry: {root}"
            )
        return root
    for candidate in (project, *project.parents):
        if (candidate / "data" / "assets" / "registry.json").is_file():
            return candidate
    raise RuntimeError(
        "cannot locate production root with data/assets/registry.json; "
        "pass --production-root explicitly."
    )


def _approved_source(root: Path, source: object) -> tuple[object, Path]:
    from .asset_registry import (
        AssetRegistryError,
        load_asset_registry,
        resolve_approved_asset,
    )

    if not isinstance(source, dict):
        raise RuntimeError("visual-block evidence requires a source object.")
    asset_id = source.get("asset_id")
    raw_path = source.get("path")
    expected_hash = source.get("sha256")
    expected_revision = source.get("registry_revision")
    expected_validation = source.get("validation_sha256")
    if not all(isinstance(item, str) and item for item in (asset_id, raw_path, expected_hash)):
        raise RuntimeError(
            "visual-block evidence source requires asset_id, path, sha256, "
            "registry_revision, and validation_sha256."
        )
    if not isinstance(expected_revision, int) or not isinstance(expected_validation, str):
        raise RuntimeError(
            "visual-block evidence source requires asset_id, path, sha256, "
            "registry_revision, and validation_sha256."
        )
    registry = load_asset_registry(root)
    record = next((item for item in registry.assets if item.asset_id == asset_id), None)
    if record is None:
        raise RuntimeError(f"visual-block source is absent from asset registry: {asset_id}")
    try:
        approved_path = resolve_approved_asset(root, asset_id)
    except AssetRegistryError as exc:
        raise RuntimeError(str(exc)) from exc
    if (
        record.artifact_path != str(raw_path).replace("\\", "/")
        or record.artifact_sha256.casefold() != str(expected_hash).casefold()
        or record.revision != expected_revision
        or record.validation_sha256.casefold() != expected_validation.casefold()
        or record.approved_validation_sha256 is None
        or record.approved_validation_sha256.casefold() != expected_validation.casefold()
        or approved_path != _inside(root, raw_path, label="visual-block source")
    ):
        raise RuntimeError(
            "visual-block source does not match the exact approved registry revision."
        )

    catalog_path = root / "data" / "assets" / "catalog.json"
    catalog = _json_object(catalog_path, label="asset catalog")
    entries = catalog.get("assets")
    real_product = isinstance(entries, list) and any(
        isinstance(item, dict)
        and item.get("path") == raw_path
        and str(item.get("sha256", "")).casefold() == str(expected_hash).casefold()
        and item.get("source_role") == "real_product"
        for item in entries
    )
    if not real_product:
        raise RuntimeError(
            "approved visual-block source lacks a matching real_product catalog role."
        )
    return record, approved_path


def _geometry_record(
    root: Path,
    evidence: dict[str, object],
    *,
    asset_id: str,
    artifact_path: str,
) -> dict[str, object]:
    reference = evidence.get("geometry_report")
    if not isinstance(reference, dict):
        raise RuntimeError("visual-block evidence requires a geometry_report reference.")
    report_path = _inside(root, reference.get("path"), label="geometry report")
    expected_hash = reference.get("sha256")
    selector = reference.get("record")
    if (
        not report_path.is_file()
        or not isinstance(expected_hash, str)
        or _sha256(report_path) != expected_hash.casefold()
    ):
        raise RuntimeError("geometry report is missing or its SHA-256 is stale.")
    if not isinstance(selector, dict):
        raise RuntimeError("geometry_report requires a beat_id/segment_index record selector.")
    report = _json_object(report_path, label="geometry report")
    segments = report.get("segments")
    if not isinstance(segments, list):
        raise RuntimeError("geometry report has no segments list.")
    match = next(
        (
            item for item in segments
            if isinstance(item, dict)
            and item.get("beat_id") == selector.get("beat_id")
            and item.get("segment_index") == selector.get("segment_index")
        ),
        None,
    )
    if match is None:
        raise RuntimeError("geometry report record selector did not match a segment.")
    if (
        match.get("asset_id") != asset_id
        or str(match.get("src", "")).replace("\\", "/") != artifact_path
        or match.get("resolved") is not True
    ):
        raise RuntimeError(
            "geometry report record does not prove the approved source transform."
        )
    geometry = match.get("geometry")
    required = (
        "fit",
        "anchor_x",
        "anchor_y",
        "source_width",
        "source_height",
        "scaled_width",
        "scaled_height",
        "output_width",
        "output_height",
    )
    if (
        not isinstance(geometry, dict)
        or any(geometry.get(key) is None for key in required)
        or not all(
            isinstance(geometry.get(key), int) and geometry.get(key) > 0
            for key in (
                "source_width",
                "source_height",
                "scaled_width",
                "scaled_height",
                "output_width",
                "output_height",
            )
        )
    ):
        raise RuntimeError(
            "geometry report record is not a complete A3 resolved transform."
        )
    return match


def _expected_recipe_geometry(record: dict[str, object]) -> tuple[list[int], list[int]]:
    geometry = record["geometry"]
    assert isinstance(geometry, dict)
    source_width = int(geometry["source_width"])
    source_height = int(geometry["source_height"])
    scaled_width = int(geometry["scaled_width"])
    scaled_height = int(geometry["scaled_height"])
    output_width = int(geometry["output_width"])
    output_height = int(geometry["output_height"])
    if geometry["fit"] == "contain":
        if (
            scaled_width != output_width
            or scaled_height != output_height
            or int(geometry.get("pad_x") or 0) != 0
            or int(geometry.get("pad_y") or 0) != 0
        ):
            raise RuntimeError(
                "proof derivation cannot reproduce an A3 contain transform with padding."
            )
        return [0, 0, source_width, source_height], [output_width, output_height]

    crop_x = geometry.get("crop_x")
    crop_y = geometry.get("crop_y")
    crop_width = geometry.get("crop_width")
    crop_height = geometry.get("crop_height")
    if not all(isinstance(item, int) for item in (crop_x, crop_y, crop_width, crop_height)):
        raise RuntimeError("A3 cover transform is missing integer crop geometry.")
    source_crop = [
        round(int(crop_x) * source_width / scaled_width),
        round(int(crop_y) * source_height / scaled_height),
        round(int(crop_width) * source_width / scaled_width),
        round(int(crop_height) * source_height / scaled_height),
    ]
    return source_crop, [output_width, output_height]


def _recompute_derived_hash(source: Path, recipe: dict[str, object]) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to verify visual-block derivations.")
    timestamp = recipe.get("source_time_seconds")
    crop = recipe.get("crop")
    output = recipe.get("output")
    if (
        not isinstance(timestamp, (int, float))
        or float(timestamp) < 0
        or not isinstance(crop, list)
        or len(crop) != 4
        or not all(isinstance(item, int) for item in crop)
        or not isinstance(output, list)
        or len(output) != 2
        or not all(isinstance(item, int) and item > 0 for item in output)
    ):
        raise RuntimeError(
            "derived asset recipe requires source_time_seconds, integer crop "
            "[x,y,w,h], and positive output [w,h]."
        )
    x, y, width, height = crop
    if min(x, y) < 0 or min(width, height) <= 0:
        raise RuntimeError("derived asset crop must have non-negative origin and positive size.")
    out_width, out_height = output
    with tempfile.TemporaryDirectory(prefix="dlstudio-proof-") as tmp:
        rendered = Path(tmp) / "derived.png"
        proc = subprocess.run(
            [
                ffmpeg,
                "-v", "error",
                "-ss", f"{float(timestamp):.6f}",
                "-i", str(source),
                "-frames:v", "1",
                "-vf",
                f"crop={width}:{height}:{x}:{y},"
                f"scale={out_width}:{out_height}:flags=lanczos",
                "-map_metadata", "-1",
                "-c:v", "png",
                "-y", str(rendered),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 or not rendered.is_file():
            tail = "\n".join((proc.stderr or "").splitlines()[-10:])
            raise RuntimeError(f"visual-block derivation could not be reproduced:\n{tail}")
        return _sha256(rendered)


def validate_visual_evidence(
    project: Path,
    *,
    production_root: Path | None,
    template: str | None,
    values: dict[str, object] | None,
    evidence_path: Path | None,
) -> None:
    """Validate approved source, A3 geometry, and reproducible image recipes."""
    if template not in PROOF_TEMPLATES:
        return
    if evidence_path is None:
        raise RuntimeError(
            f"visual-block template {template!r} requires --evidence-file."
        )
    evidence = _json_object(evidence_path, label="visual-block evidence file")
    if evidence.get("schema") != "devlog.visual_block_evidence/v2":
        raise RuntimeError("visual-block evidence has an unsupported schema.")
    if evidence.get("template") != template:
        raise RuntimeError(
            f"visual-block evidence template mismatch: "
            f"{evidence.get('template')!r} != {template!r}"
        )
    root = _production_root(project, production_root)
    record, source_path = _approved_source(root, evidence.get("source"))
    geometry_record = _geometry_record(
        root,
        evidence,
        asset_id=record.asset_id,
        artifact_path=record.artifact_path,
    )

    assert values is not None
    assets = evidence.get("assets")
    if not isinstance(assets, dict):
        raise RuntimeError("visual-block evidence requires an assets object.")
    asset_keys = {
        "day-card": ("background_image",),
        "before-after": ("before_image", "after_image"),
        "focus-callout": ("image",),
        "cta-endcard": ("background_image",),
    }[template]
    timestamps: list[float] = []
    recipes: list[dict[str, object]] = []
    expected_crop, expected_output = _expected_recipe_geometry(geometry_record)
    for key in asset_keys:
        proof = assets.get(key)
        raw = values.get(key)
        if not isinstance(proof, dict) or not isinstance(raw, str):
            raise RuntimeError(f"visual-block evidence is missing asset record: {key}")
        actual = (project / raw).resolve()
        try:
            actual.relative_to(project)
        except ValueError as exc:
            raise RuntimeError(f"visual-block asset must stay inside its project: {key}") from exc
        if proof.get("path") != raw or _sha256(actual) != str(proof.get("sha256", "")).casefold():
            raise RuntimeError(f"visual-block evidence hash is stale for {key}.")
        if (
            proof.get("source_asset_id") != record.asset_id
            or str(proof.get("source_sha256", "")).casefold()
            != record.artifact_sha256.casefold()
        ):
            raise RuntimeError(f"derived asset {key} is not bound to the approved source.")
        recipe = proof.get("recipe")
        if not isinstance(recipe, dict):
            raise RuntimeError(f"derived asset {key} requires a reproducible recipe.")
        if recipe.get("crop") != expected_crop or recipe.get("output") != expected_output:
            raise RuntimeError(
                f"derived asset {key} recipe does not match the A3 geometry transform."
            )
        recomputed = _recompute_derived_hash(source_path, recipe)
        if recomputed != _sha256(actual):
            raise RuntimeError(f"derived asset recipe does not reproduce {key}.")
        timestamps.append(float(recipe["source_time_seconds"]))
        recipes.append(recipe)

    if template == "before-after":
        if len(set(timestamps)) != 2:
            raise RuntimeError(
                "before-after requires two different timestamps from one approved source."
            )
        if recipes[0]["crop"] != recipes[1]["crop"] or recipes[0]["output"] != recipes[1]["output"]:
            raise RuntimeError(
                "before-after timestamps must use identical A3 crop and output geometry."
            )
