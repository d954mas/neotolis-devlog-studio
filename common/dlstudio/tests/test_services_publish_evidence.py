from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from dlstudio.production import ProductManifest, ProductionManifest


def _manifest(tmp_path: Path) -> ProductionManifest:
    product_root = tmp_path / "game"
    root = product_root / "reels" / "2026_07_18_reel_01"
    product = ProductManifest(
        root=product_root, id="game", title="Game", version=1,
        game_root=product_root, sources={}, devlogs_dir=product_root / "devlogs",
        reels_dir=product_root / "reels", shared_dir=product_root / "shared",
        delivery_dir=product_root / "delivery",
    )
    return ProductionManifest(
        root=root, id="2026_07_18_reel_01", kind="reel", date="2026-07-18",
        orientation="vertical", version=1, edit_dir=root / "edit",
        data_dir=root / "data", delivery_dir=product.delivery_dir / "reels" / root.name,
        product=product,
    )


def _write_ready_publish_inputs(
    manifest: ProductionManifest,
    *,
    attribution: dict | None = None,
) -> tuple[Path, str]:
    video = manifest.data_dir / "finalize" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact-video")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    publish = manifest.publish_dir
    publish.mkdir(parents=True)
    Image.new("RGB", (1080, 1920), "red").save(publish / "cover.png")
    (publish / "metadata.md").write_text(
        "# Title\nGame\n# Description\nStory\n# Tags\ngame dev\n# Hashtags\n#gamedev\n",
        encoding="utf-8",
    )
    payload = {
        "version": 1,
        "product_id": "game",
        "production_id": manifest.id,
        "video": {"path": "data/finalize/video.mp4"},
        "cover": {"path": "data/publish/cover.png"},
        "upload_checklist": {"passed": []},
    }
    if attribution is not None:
        payload["attribution"] = attribution
    (publish / "publish.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest.review_dir.mkdir(parents=True)
    (manifest.review_dir / "preflight.json").write_text(json.dumps({
        "ok": True,
        "errors": 0,
        "warnings": 0,
        "inputs": {
            "render_artifact": str(video),
            "render_artifact_sha256": digest,
        },
    }), encoding="utf-8")
    (manifest.review_dir / "feedback.json").write_text(json.dumps({
        "full": {"video": {
            "artifact_path": str(video),
            "artifact_sha256": digest,
            "verdict": "ship",
        }}
    }), encoding="utf-8")
    return video, digest


def test_refresh_publish_evidence_binds_preflight_and_review_to_exact_hash(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    video = manifest.data_dir / "finalize" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact-video")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    publish = manifest.publish_dir
    publish.mkdir(parents=True)
    Image.new("RGB", (1080, 1920), "red").save(publish / "cover.png")
    (publish / "metadata.md").write_text(
        "# Title\nGame\n# Description\nStory\n# Tags\ngame dev\n# Hashtags\n#gamedev\n",
        encoding="utf-8",
    )
    (publish / "publish.json").write_text(json.dumps({
        "version": 1, "product_id": "game", "production_id": manifest.id,
        "video": {"path": "data/finalize/video.mp4", "sha256": "stale"},
        "cover": {"path": "data/publish/cover.png", "sha256": "stale"},
        "upload_checklist": {"passed": []},
    }), encoding="utf-8")
    manifest.review_dir.mkdir(parents=True)
    (manifest.review_dir / "preflight.json").write_text(json.dumps({
        "ok": True, "errors": 0, "warnings": 2,
        "inputs": {
            "render_artifact": str(video),
            "render_artifact_sha256": digest,
        },
    }), encoding="utf-8")
    (manifest.review_dir / "feedback.json").write_text(json.dumps({
        "full": {"video": {"artifact_path": str(video), "artifact_sha256": digest,
        "verdict": "ship", "timestamp": "2026-07-18T00:00:00Z"}}
    }), encoding="utf-8")

    from dlstudio.services import publish_evidence
    monkeypatch.setattr(publish_evidence, "_probe_video", lambda _path: (17.5, 1080, 1920))
    result = publish_evidence.refresh_publish_evidence(manifest)

    payload = json.loads(result.publish_path.read_text(encoding="utf-8"))
    assert payload["video"]["sha256"] == digest
    assert payload["video"]["resolution"] == {"width": 1080, "height": 1920}
    gates = {item["gate"]: item["evidence"] for item in payload["upload_checklist"]["passed"]}
    assert digest in gates["exact_final_blind_review"]
    assert "warnings=2" in gates["preflight_mechanical"]
    assert result.evidence_path.is_file()
    publish_video = manifest.publish_dir / "video.mp4"
    assert publish_video.read_bytes() == video.read_bytes()
    assert payload["publish_video"] == {
        "path": "data/publish/video.mp4",
        "sha256": digest,
        "size": len(b"exact-video"),
    }
    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["metadata"]["sha256"] == hashlib.sha256(
        (publish / "metadata.md").read_bytes()
    ).hexdigest()


def test_refresh_publish_evidence_rejects_video_mutated_after_preflight(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    video = manifest.data_dir / "finalize" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"before-preflight")
    stale_digest = hashlib.sha256(video.read_bytes()).hexdigest()
    video.write_bytes(b"after-preflight")
    current_digest = hashlib.sha256(video.read_bytes()).hexdigest()
    publish = manifest.publish_dir
    publish.mkdir(parents=True)
    Image.new("RGB", (1080, 1920), "red").save(publish / "cover.png")
    (publish / "metadata.md").write_text(
        "# Title\nGame\n# Description\nStory\n# Hashtags\n#gamedev\n",
        encoding="utf-8",
    )
    (publish / "publish.json").write_text(json.dumps({
        "version": 1,
        "product_id": "game",
        "production_id": manifest.id,
        "video": {"path": "data/finalize/video.mp4"},
        "cover": {"path": "data/publish/cover.png"},
    }), encoding="utf-8")
    manifest.review_dir.mkdir(parents=True)
    (manifest.review_dir / "preflight.json").write_text(json.dumps({
        "ok": True,
        "errors": 0,
        "warnings": 0,
        "inputs": {
            "render_artifact": str(video),
            "render_artifact_sha256": stale_digest,
        },
    }), encoding="utf-8")
    (manifest.review_dir / "feedback.json").write_text(json.dumps({
        "full": {"video": {
            "artifact_path": str(video),
            "artifact_sha256": current_digest,
            "verdict": "ship",
        }}
    }), encoding="utf-8")
    from dlstudio.services import publish_evidence
    monkeypatch.setattr(
        publish_evidence,
        "_probe_video",
        lambda _path: (10.0, 1080, 1920),
    )

    with pytest.raises(
        publish_evidence.PublishEvidenceError,
        match="preflight SHA-256",
    ):
        publish_evidence.refresh_publish_evidence(manifest)


def test_refresh_publish_evidence_requires_copy_ready_credit_for_used_cc_by_asset(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    _write_ready_publish_inputs(
        manifest,
        attribution={"required": False, "text": None},
    )
    footage = manifest.data_dir / "footage" / "licensed.mp4"
    footage.parent.mkdir(parents=True)
    footage.write_bytes(b"licensed")
    plan = manifest.data_dir / "plan"
    plan.mkdir(parents=True)
    (plan / "shot_manifest.json").write_text(json.dumps({
        "shots": [{"id": "s01", "src": "data/footage/licensed.mp4"}],
    }), encoding="utf-8")
    provenance = manifest.data_dir / "assets" / "provenance" / "licensed.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(json.dumps({
        "schema": "devlog.video_provenance",
        "version": 1,
        "artifact_path": "data/footage/licensed.mp4",
        "artifact_sha256": hashlib.sha256(footage.read_bytes()).hexdigest(),
        "editorial_role": "reference",
        "license": "CC-BY 4.0",
        "credit": "Example Creator",
    }), encoding="utf-8")
    (manifest.data_dir / "assets" / "registry.json").write_text(json.dumps({
        "version": 1,
        "assets": [{
                "asset_id": "stock:licensed",
                "artifact_path": "data/footage/licensed.mp4",
                "artifact_sha256": hashlib.sha256(footage.read_bytes()).hexdigest(),
            "provenance_path": "data/assets/provenance/licensed.json",
            "provenance_sha256": hashlib.sha256(
                provenance.read_bytes()
            ).hexdigest(),
        }],
    }), encoding="utf-8")

    from dlstudio.services import publish_evidence
    monkeypatch.setattr(
        publish_evidence, "_probe_video", lambda _path: (17.5, 1080, 1920)
    )
    with pytest.raises(
        publish_evidence.PublishEvidenceError,
        match="attribution.required=true",
    ):
        publish_evidence.refresh_publish_evidence(manifest)

    publish_path = manifest.publish_dir / "publish.json"
    payload = json.loads(publish_path.read_text(encoding="utf-8"))
    payload["attribution"] = {
        "required": True,
        "text": "Music: Example Creator — CC-BY 4.0",
    }
    publish_path.write_text(json.dumps(payload), encoding="utf-8")
    metadata = manifest.publish_dir / "metadata.md"
    metadata_text = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        metadata_text.replace(
            "# Tags",
            payload["attribution"]["text"] + "\n# Tags",
        ),
        encoding="utf-8",
    )

    result = publish_evidence.refresh_publish_evidence(manifest)

    refreshed = json.loads(result.publish_path.read_text(encoding="utf-8"))
    gates = {item["gate"] for item in refreshed["upload_checklist"]["passed"]}
    assert "attribution_ready" in gates


def test_refresh_publish_evidence_detects_music_referenced_by_production_edit(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    _write_ready_publish_inputs(
        manifest,
        attribution={"required": False, "text": None},
    )
    manifest.edit_dir.mkdir(parents=True)
    (manifest.edit_dir / "__init__.py").write_text("# test edit\n", encoding="utf-8")
    music = manifest.data_dir / "music" / "licensed.ogg"
    music.parent.mkdir(parents=True)
    music.write_bytes(b"licensed-music")
    provenance = manifest.data_dir / "assets" / "provenance" / "music.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text(json.dumps({
        "schema": "devlog.video_provenance",
        "version": 1,
        "artifact_path": "data/music/licensed.ogg",
        "artifact_sha256": hashlib.sha256(music.read_bytes()).hexdigest(),
        "editorial_role": "music",
        "license": "CC-BY 4.0",
        "credit": "Music Creator",
    }), encoding="utf-8")
    (manifest.data_dir / "assets" / "registry.json").write_text(json.dumps({
        "version": 1,
        "assets": [{
            "asset_id": "music:licensed",
            "artifact_path": "data/music/licensed.ogg",
            "artifact_sha256": hashlib.sha256(music.read_bytes()).hexdigest(),
            "provenance_path": "data/assets/provenance/music.json",
            "provenance_sha256": hashlib.sha256(
                provenance.read_bytes()
            ).hexdigest(),
        }],
    }), encoding="utf-8")

    import dlstudio.compile as compile_mod
    import dlstudio.production as production_mod
    from dlstudio.services import publish_evidence

    monkeypatch.setattr(
        production_mod,
        "load_production_edit_module",
        lambda *_args, **_kwargs: (
            SimpleNamespace(EDIT=object()),
            manifest,
            "test.edit",
        ),
    )
    monkeypatch.setattr(
        compile_mod,
        "_referenced_paths",
        lambda _edit: {"data/music/licensed.ogg": "audio"},
    )
    monkeypatch.setattr(
        publish_evidence, "_probe_video", lambda _path: (17.5, 1080, 1920)
    )

    with pytest.raises(
        publish_evidence.PublishEvidenceError,
        match="attribution.required=true",
    ):
        publish_evidence.refresh_publish_evidence(manifest)


def test_refresh_publish_evidence_rejects_unregistered_external_music(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    _write_ready_publish_inputs(manifest)
    manifest.edit_dir.mkdir(parents=True)
    (manifest.edit_dir / "__init__.py").write_text("# test edit\n", encoding="utf-8")
    music = manifest.data_dir / "music" / "unknown.ogg"
    music.parent.mkdir(parents=True)
    music.write_bytes(b"unknown-license")

    import dlstudio.compile as compile_mod
    import dlstudio.production as production_mod
    from dlstudio.services import publish_evidence

    monkeypatch.setattr(
        production_mod,
        "load_production_edit_module",
        lambda *_args, **_kwargs: (
            SimpleNamespace(EDIT=object()),
            manifest,
            "test.edit",
        ),
    )
    monkeypatch.setattr(
        compile_mod,
        "_referenced_paths",
        lambda _edit: {"data/music/unknown.ogg": "audio"},
    )
    monkeypatch.setattr(
        publish_evidence, "_probe_video", lambda _path: (17.5, 1080, 1920)
    )

    with pytest.raises(
        publish_evidence.PublishEvidenceError,
        match="not registered with hash-bound provenance",
    ):
        publish_evidence.refresh_publish_evidence(manifest)


def test_refresh_publish_evidence_rejects_registered_music_without_provenance(
    tmp_path, monkeypatch
):
    manifest = _manifest(tmp_path)
    _write_ready_publish_inputs(manifest)
    manifest.edit_dir.mkdir(parents=True)
    (manifest.edit_dir / "__init__.py").write_text("# test edit\n", encoding="utf-8")
    music = manifest.data_dir / "music" / "legacy.ogg"
    music.parent.mkdir(parents=True)
    music.write_bytes(b"legacy-music")
    registry = manifest.data_dir / "assets" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "version": 1,
        "assets": [{
            "asset_id": "music:legacy",
            "artifact_path": "data/music/legacy.ogg",
            "artifact_sha256": hashlib.sha256(music.read_bytes()).hexdigest(),
        }],
    }), encoding="utf-8")

    import dlstudio.compile as compile_mod
    import dlstudio.production as production_mod
    from dlstudio.services import publish_evidence

    monkeypatch.setattr(
        production_mod,
        "load_production_edit_module",
        lambda *_args, **_kwargs: (
            SimpleNamespace(EDIT=object()),
            manifest,
            "test.edit",
        ),
    )
    monkeypatch.setattr(
        compile_mod,
        "_referenced_paths",
        lambda _edit: {"data/music/legacy.ogg": "audio"},
    )
    monkeypatch.setattr(
        publish_evidence, "_probe_video", lambda _path: (17.5, 1080, 1920)
    )

    with pytest.raises(
        publish_evidence.PublishEvidenceError,
        match="has no provenance record",
    ):
        publish_evidence.refresh_publish_evidence(manifest)
