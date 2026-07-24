from __future__ import annotations

import json

from PIL import Image


def test_review_pack_is_exact_hash_bound_and_compact(tmp_path, monkeypatch):
    from dlstudio.services import review_pack

    video = tmp_path / "data/finalize/video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact video bytes")
    plan = tmp_path / "data/plan"
    plan.mkdir(parents=True)
    (plan / "shot_manifest.json").write_text(json.dumps({"shots": [
        {"id": "s01", "purpose": "hook", "src": "data/infographics/master.mp4", "t0": 0, "t1": 2},
        {"id": "s02", "purpose": "payoff", "src": "b.mp4", "t0": 2, "t1": 5},
    ]}), encoding="utf-8")
    (plan / "story_contract.json").write_text(json.dumps({
        "standalone_story": {"premise": "p", "causal_turn": "t", "payoff": "x"}
    }), encoding="utf-8")
    hyper = tmp_path / "data/hyperframes/master"
    hyper.mkdir(parents=True)
    (hyper / "index.html").write_text(
        "<html><body><h1>Visible hook</h1><script>hidden</script></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(review_pack, "_probe_video", lambda path: {
        "duration": 5.0, "width": 1080, "height": 1920, "fps": 30.0,
    })

    def fake_extract(video, timestamp, out, width, height):
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (width, height), "#334455").save(out)

    monkeypatch.setattr(review_pack, "_extract_thumbnail", fake_extract)

    out, sheet = review_pack.build_review_pack(tmp_path, video, max_frames=6)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["artifact"]["path"] == str(video.resolve())
    assert len(payload["artifact"]["sha256"]) == 64
    assert len(payload["compact_review"]["frames"]) <= 6
    assert payload["viewer_text"][0]["text"] == "Visible hook"
    assert sheet.is_file()
    assert sheet.stat().st_size < 500_000


def test_review_pack_adds_short_clips_for_freeze_candidates(tmp_path, monkeypatch):
    from dlstudio.services import review_pack

    video = tmp_path / "data/finalize/video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"exact video bytes")
    review = tmp_path / "data/review"
    review.mkdir(parents=True)
    (review / "preflight.json").write_text(json.dumps({
        "issues": [{
            "severity": "error",
            "code": "VQ-FREEZE",
            "where": "freeze@7.567s",
            "message": (
                "whole-frame freeze candidate 0.433s at "
                "[7.567,8.000] in gameplay"
            ),
        }, {
            "severity": "error",
            "code": "VQ-CADENCE",
            "where": "gameplay",
            "message": (
                "gameplay [10.000,12.800) has stepped capture cadence: "
                "adjacent duplicates 47.0% (39/83); "
                "alternating plateaus 45.8% (38/83)"
            ),
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(review_pack, "_probe_video", lambda path: {
        "duration": 12.8, "width": 1080, "height": 1920, "fps": 30.0,
    })

    def fake_extract_thumbnail(video, timestamp, out, width, height):
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (width, height), "#334455").save(out)

    def fake_extract_clip(video, start, duration, out, width):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"candidate clip")

    monkeypatch.setattr(review_pack, "_extract_thumbnail", fake_extract_thumbnail)
    monkeypatch.setattr(review_pack, "_extract_freeze_clip", fake_extract_clip)

    out, _sheet = review_pack.build_review_pack(tmp_path, video, max_frames=4)

    payload = json.loads(out.read_text(encoding="utf-8"))
    candidates = payload["compact_review"]["freeze_candidates"]
    assert candidates == [{
        "id": "freeze_01",
        "time": 7.567,
        "duration": 0.433,
        "severity": "error",
        "clip": "data/review/freeze_candidates/freeze_01.mp4",
    }]
    assert (tmp_path / candidates[0]["clip"]).read_bytes() == b"candidate clip"
    cadence = payload["compact_review"]["cadence_candidates"]
    assert cadence == [{
        "id": "cadence_01",
        "time": 10.0,
        "duration": 2.8,
        "severity": "error",
        "clip": "data/review/cadence_candidates/cadence_01.mp4",
    }]
    assert (tmp_path / cadence[0]["clip"]).read_bytes() == b"candidate clip"
