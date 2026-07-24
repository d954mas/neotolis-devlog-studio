from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

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
        "inputs": {"render_artifact": str(video)},
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
