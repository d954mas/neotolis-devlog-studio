"""Tests for the Studio v2 FastAPI backend (dlstudio.api).

Two project flavours:
- a *compiled* project (real sine wav + words.json + gradient png, the
  test_e2e fixture pattern) for /api/project, /api/ir, /api/check, which go
  through build_timeline + real ffprobe -> guarded by an ffmpeg skip.
- a *light* project (beats referencing paths that never get probed) for
  feedback merge, takes upload, file-traversal rejection, and the job
  lifecycle, where compile/render are monkeypatched or unused -> no ffmpeg.

create_app(dotted) imports the edit module and os.chdir()s into its project
root; the autouse `_restore_cwd` fixture in conftest puts cwd back.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")  # python-multipart, needed for UploadFile

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from dlstudio.api import create_app  # noqa: E402

_HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_needs_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")

_WORDS = {
    "text": "hello brave new world again now",
    "words": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "brave", "start": 0.5, "end": 0.9},
        {"word": "new", "start": 1.0, "end": 1.3},
        {"word": "world", "start": 2.0, "end": 2.4},
        {"word": "again", "start": 2.5, "end": 2.9},
        {"word": "now", "start": 3.0, "end": 3.4},
    ],
}


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _write_pkg(tmp_path: Path, pkg: str, edit_body: str) -> tuple[str, Path]:
    """Write tmp_path/<pkg>/edits/myedit/__init__.py exposing EDIT, plus a
    devlog.toml workspace marker at tmp_path. Returns (dotted, project_root)."""
    root = tmp_path / pkg
    (root / "edits" / "myedit").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "edits" / "__init__.py").write_text("", encoding="utf-8")
    (root / "edits" / "myedit" / "__init__.py").write_text(edit_body, encoding="utf-8")
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    return f"{pkg}.edits.myedit", root


_COMPILED_EDIT_BODY = textwrap.dedent(
    """
    from dlstudio.model import (
        Beat, Chunk, Design, Edit, Fonts, Overlay, Palette, Plate, Scene, TextStyle,
    )

    EDIT = Edit(
        name="apitest",
        design=Design(
            resolution=(320, 180), fps=30,
            palette=Palette(tokens={"bg": "#101018", "text": "#ffffff", "accent": "#ff2b4e"}),
            fonts=Fonts(main="data/font.ttf"),
            styles={"plate.default": TextStyle(size=220), "overlay.default": TextStyle(size=120)},
        ),
        beats={
            "b01": Beat(
                audio="data/vo.wav", words="data/words.json",
                title="Intro", vo="hello brave new world", stage="calm and clear",
                face="none",
                scene=Scene(kind="image", src="data/scene.png"),
                chunks=[
                    Chunk(words=(0, 2), content=Plate(text="HELLO")),
                    Chunk(words=(3, 5), content=Overlay(text="WORLD", subtitle="again now")),
                ],
            ),
        },
        order=["b01"],
        output="data/apitest_final.mp4",
    )
    """
)

_LIGHT_EDIT_BODY = textwrap.dedent(
    """
    from dlstudio.model import Beat, Chunk, Design, Edit, Fonts, Palette, Plate

    EDIT = Edit(
        name="light",
        design=Design(
            resolution=(1920, 1080),
            palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
            fonts=Fonts(main="main.ttf"),
        ),
        beats={
            "b01": Beat(
                # Deliberately NOT the <id>_vo.wav / <id>_words.json convention:
                # process-take must write to whatever path the beat declares,
                # or a real edit never sees the processed take (H1).
                audio="data/finalize/b01_audio_tight_pause.wav",
                words="data/finalize/b01_words_tight.json",
                vo="hi there world",
                chunks=[Chunk(words=(0, 1), content=Plate(text="X"))],
            ),
        },
        order=["b01"],
        output="data/finalize/out.mp4",
    )
    """
)


@pytest.fixture()
def compiled_client(tmp_path, monkeypatch):
    """A real compiled project + TestClient (needs ffmpeg)."""
    pkg = _unique("apiproj")
    dotted, root = _write_pkg(tmp_path, pkg, _COMPILED_EDIT_BODY)
    data = root / "data"
    data.mkdir()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3.4",
         "-ar", "48000", "-ac", "1", str(data / "vo.wav")],
        check=True, capture_output=True,
    )
    (data / "words.json").write_text(json.dumps(_WORDS), encoding="utf-8")
    img = Image.new("RGB", (640, 360), (40, 80, 160))
    img.save(data / "scene.png")
    # 0.11 validates font loadability at check time — placeholder bytes would
    # (correctly) raise VQ-ASSET, so stage a real system font.
    from _builders import find_system_font

    system_font = find_system_font()
    if system_font is None:
        pytest.skip("no known system font found (0.11 validates loadability)")
    shutil.copyfile(system_font, data / "font.ttf")

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(dotted)) as client:
        yield client, root, dotted


@pytest.fixture()
def light_client(tmp_path, monkeypatch):
    """A light project (no ffmpeg) + TestClient."""
    pkg = _unique("lightproj")
    dotted, root = _write_pkg(tmp_path, pkg, _LIGHT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(dotted)) as client:
        yield client, root, dotted


def _await_job(client: TestClient, job_id: str, *, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data = {"status": "running"}
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        data = r.json()
        if data["status"] != "running":
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {data}")


# ─── /api/project, /api/ir, /api/check (compiled) ────────────────────────────

@_needs_ffmpeg
def test_project_endpoint(compiled_client):
    client, root, _ = compiled_client
    r = client.get("/api/project")
    assert r.status_code == 200
    data = r.json()
    assert data["edit_name"] == "apitest"
    assert data["output"] == "data/apitest_final.mp4"
    assert data["design"]["resolution"] == [320, 180]
    assert data["design"]["fps"] == 30
    assert len(data["beats"]) == 1
    b = data["beats"][0]
    assert b["id"] == "b01"
    assert b["title"] == "Intro"
    assert b["vo"] == "hello brave new world"
    assert b["stage"] == "calm and clear"
    assert b["face"] == "none"
    assert b["n_chunks"] == 2
    assert b["audio"] == "data/vo.wav"
    assert b["words"] == "data/words.json"
    assert b["rendered"] is False
    assert b["duration"] == pytest.approx(3.4, abs=0.1)


@_needs_ffmpeg
def test_project_rendered_flag_true_when_mp4_present(compiled_client):
    client, root, _ = compiled_client
    fin = root / "data" / "finalize"
    fin.mkdir(parents=True, exist_ok=True)
    (fin / "b01.mp4").write_bytes(b"fake-mp4")
    data = client.get("/api/project").json()
    assert data["beats"][0]["rendered"] is True


@_needs_ffmpeg
def test_ir_endpoint(compiled_client):
    client, _, _ = compiled_client
    r = client.get("/api/ir")
    assert r.status_code == 200
    ir = r.json()
    assert ir["edit_name"] == "apitest"
    assert [b["id"] for b in ir["beats"]] == ["b01"]
    assert ir["beats"][0]["duration"] == pytest.approx(3.4, abs=0.1)
    assert "placements" in ir and "mix" in ir and "assets" in ir


@_needs_ffmpeg
def test_check_endpoint(compiled_client):
    client, _, _ = compiled_client
    r = client.get("/api/check")
    assert r.status_code == 200
    report = r.json()
    assert isinstance(report["issues"], list)
    # every referenced asset exists -> no missing/unreadable asset errors
    assert not [i for i in report["issues"]
                if i["code"] == "VQ-ASSET" and i["severity"] == "error"]


# ─── root / placeholder ──────────────────────────────────────────────────────

def test_root_serves_placeholder_when_no_static(light_client):
    client, _, _ = light_client
    r = client.get("/")
    assert r.status_code == 200
    assert "Studio v2" in r.text


def test_research_page_serves_the_same_ui_shell(light_client):
    client, _, _ = light_client
    r = client.get("/research/")
    assert r.status_code == 200
    assert '<base href="/"' in r.text or "Studio v2" in r.text


# ─── feedback: read empty, write, deep-merge ─────────────────────────────────

def test_feedback_empty_when_missing(light_client):
    client, _, _ = light_client
    r = client.get("/api/feedback")
    assert r.status_code == 200
    assert r.json() == {}


def test_feedback_deep_merge(light_client):
    client, root, _ = light_client
    r1 = client.post("/api/feedback", json={"b01": {"note": "tighten intro"}})
    assert r1.status_code == 200
    assert r1.json() == {"b01": {"note": "tighten intro"}}

    r2 = client.post("/api/feedback", json={"b01": {"rating": 5}, "b02": {"note": "ok"}})
    assert r2.status_code == 200
    merged = r2.json()
    assert merged == {
        "b01": {"note": "tighten intro", "rating": 5},
        "b02": {"note": "ok"},
    }
    # persisted + re-read identically
    assert client.get("/api/feedback").json() == merged
    on_disk = json.loads((root / "data" / "review" / "feedback.json").read_text(encoding="utf-8"))
    assert on_disk == merged


def test_feedback_rejects_non_object(light_client):
    client, _, _ = light_client
    r = client.post("/api/feedback", json=[1, 2, 3])
    assert r.status_code == 400


def test_feedback_rejects_oversize_body(light_client, monkeypatch):
    client, _, _ = light_client
    monkeypatch.setattr("dlstudio.api.app._MAX_FEEDBACK_BYTES", 10)
    r = client.post("/api/feedback", json={"b01": {"note": "x" * 100}})
    assert r.status_code == 413


def _nest(depth: int) -> dict:
    root: dict = {}
    cur = root
    for _ in range(depth):
        cur["k"] = {}
        cur = cur["k"]
    cur["v"] = 1
    return root


def test_feedback_rejects_too_deep(light_client):
    client, _, _ = light_client
    deep = _nest(40)
    # store starts empty, so the first merge never recurses -> accepted
    assert client.post("/api/feedback", json=deep).status_code == 200
    # now the store is equally deep; merging the same shape recurses past the
    # cap and is rejected (guards against unbounded recursion / stack blowup)
    assert client.post("/api/feedback", json=deep).status_code == 400


# ─── single Autopilot checkpoint ───

def _write_checkpoint_inputs(root: Path) -> Path:
    plan = root / "data" / "plan"
    assets = root / "data" / "assets"
    review = root / "data" / "review"
    plan.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    manifest = plan / "shot_manifest.json"
    manifest.write_text(json.dumps({"shots": [{
        "id": "b01_s01", "vo_thesis": "real game proof",
        "src": "data/footage/game.mp4", "t0": 0, "t1": 3,
        "approved": False,
    }]}), encoding="utf-8")
    (assets / "catalog.json").write_text(json.dumps({"assets": [{
        "path": "data/footage/game.mp4", "provenance": "game_capture",
        "source_role": "real_product", "quality_flags": [],
    }]}), encoding="utf-8")
    (review / "preflight.json").write_text(json.dumps({
        "wall_time": {"budget_minutes": 60, "elapsed_minutes": 12},
        "issues": [],
    }), encoding="utf-8")
    return manifest


def test_autopilot_checkpoint_get_and_approve_are_production_scoped(light_client):
    client, root, _ = light_client
    manifest = _write_checkpoint_inputs(root)

    snapshot = client.get("/api/autopilot/checkpoint")
    assert snapshot.status_code == 200
    assert snapshot.json()["rows"][0]["shot"]["provenance"] == "game_capture"

    approved = client.post(
        "/api/autopilot/checkpoint/approve", json={"approved_by": "author"}
    )
    assert approved.status_code == 200
    assert approved.json()["checkpoint"]["approved_all"] is True
    assert json.loads(manifest.read_text(encoding="utf-8"))["shots"][0]["approved"] is True


def test_autopilot_content_action_records_request_without_mutating_manifest(light_client):
    client, root, _ = light_client
    manifest = _write_checkpoint_inputs(root)
    before = manifest.read_bytes()

    response = client.post("/api/autopilot/checkpoint/request", json={
        "action": "replace_shot", "shot_id": "b01_s01",
        "reason": "Use the newer portrait capture", "requested_by": "author",
    })

    assert response.status_code == 200
    assert response.json()["status"] == "requested"
    assert manifest.read_bytes() == before
    request_file = root / "data" / "plan" / "autopilot_requests.json"
    assert json.loads(request_file.read_text(encoding="utf-8"))["requests"][0]["action"] == "replace_shot"


# ─── takes upload ────────────────────────────────────────────────────────────

def test_takes_upload_saves_file(light_client):
    client, root, _ = light_client
    r = client.post(
        "/api/takes/b01",
        files={"file": ("take.webm", b"AUDIO-BYTES", "audio/webm")},
    )
    assert r.status_code == 200
    rel = r.json()["path"]
    assert rel.startswith("data/recordings/b01_")
    assert rel.endswith(".webm")
    saved = root / rel
    assert saved.is_file()
    assert saved.read_bytes() == b"AUDIO-BYTES"


def test_takes_upload_persists_validated_recording_markers(light_client):
    client, root, _ = light_client
    metadata = {
        "schema": "devlog.voice_take",
        "version": 1,
        "countdown_seconds": 3,
        "room_tone_seconds": 2,
        "speech_start_seconds": 5,
        "stop_requested_seconds": 12.5,
        "post_roll_end_seconds": 13.5,
        "post_roll_target_seconds": 1,
        "post_roll_completed": True,
        "completed_lead_in": True,
    }
    r = client.post(
        "/api/takes/b01",
        files={"file": ("take.webm", b"AUDIO-BYTES", "audio/webm")},
        data={"metadata": json.dumps(metadata)},
    )
    assert r.status_code == 200
    metadata_path = root / r.json()["metadata_path"]
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata


def test_takes_upload_does_not_publish_raw_without_sidecar_bundle(
    light_client,
    monkeypatch,
):
    client, root, _ = light_client
    metadata = {
        "schema": "devlog.voice_take",
        "version": 1,
        "countdown_seconds": 3,
        "room_tone_seconds": 2,
        "speech_start_seconds": 5,
        "stop_requested_seconds": 12.5,
        "post_roll_end_seconds": 13.5,
        "post_roll_target_seconds": 1,
        "post_roll_completed": True,
        "completed_lead_in": True,
    }
    monkeypatch.setattr(
        "dlstudio.services.bundle.promote_bundle",
        lambda _replacements: (_ for _ in ()).throw(
            RuntimeError("promotion failed")
        ),
    )

    with pytest.raises(RuntimeError, match="promotion failed"):
        client.post(
            "/api/takes/b01",
            files={"file": ("take.webm", b"AUDIO-BYTES", "audio/webm")},
            data={"metadata": json.dumps(metadata)},
        )

    recordings = root / "data" / "recordings"
    assert not list(recordings.glob("b01_*"))
    assert not list(recordings.glob(".*.upload"))


def test_takes_upload_rejects_unordered_recording_markers(light_client):
    client, _, _ = light_client
    metadata = {
        "schema": "devlog.voice_take",
        "version": 1,
        "countdown_seconds": 3,
        "room_tone_seconds": 2,
        "speech_start_seconds": 5,
        "stop_requested_seconds": 12,
        "post_roll_end_seconds": 11,
        "post_roll_target_seconds": 1,
        "post_roll_completed": False,
        "completed_lead_in": True,
    }
    r = client.post(
        "/api/takes/b01",
        files={"file": ("take.webm", b"AUDIO-BYTES", "audio/webm")},
        data={"metadata": json.dumps(metadata)},
    )
    assert r.status_code == 400


def test_takes_upload_rejects_bad_beat_id(light_client):
    client, _, _ = light_client
    # a backslash in the id is rejected by safe_component (routes as one segment)
    r = client.post(
        "/api/takes/bad%5Cid",
        files={"file": ("t.webm", b"x", "audio/webm")},
    )
    assert r.status_code == 400


def test_takes_upload_rejects_empty(light_client):
    client, root, _ = light_client
    r = client.post(
        "/api/takes/b01",
        files={"file": ("empty.webm", b"", "audio/webm")},
    )
    assert r.status_code == 400
    # no partial file left behind
    rec = root / "data" / "recordings"
    assert not (rec.exists() and list(rec.glob("b01_*")))


def test_takes_upload_rejects_oversize(light_client, monkeypatch):
    client, root, _ = light_client
    # shrink the cap so a tiny body trips it (streamed cap, not Content-Length)
    monkeypatch.setattr("dlstudio.api.app._MAX_UPLOAD_BYTES", 4)
    r = client.post(
        "/api/takes/b01",
        files={"file": ("big.webm", b"way-more-than-four-bytes", "audio/webm")},
    )
    assert r.status_code == 413
    rec = root / "data" / "recordings"
    assert not (rec.exists() and list(rec.glob("b01_*")))


# ─── /api/file traversal rejection ───────────────────────────────────────────

def test_file_serves_under_root(light_client):
    client, root, _ = light_client
    target = root / "data" / "recordings" / "x.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"hello-file")
    r = client.get("/api/file", params={"path": "data/recordings/x.txt"})
    assert r.status_code == 200
    assert r.content == b"hello-file"


def test_file_rejects_parent_traversal(light_client, tmp_path):
    client, root, _ = light_client
    (tmp_path / "outside.txt").write_bytes(b"secret")  # sibling of root
    r = client.get("/api/file", params={"path": "../outside.txt"})
    assert r.status_code == 404


def test_file_rejects_absolute_path(light_client, tmp_path):
    client, _, _ = light_client
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    r = client.get("/api/file", params={"path": str(outside)})
    assert r.status_code == 404


def test_file_rejects_encoded_traversal(light_client, tmp_path):
    client, _, _ = light_client
    (tmp_path / "outside.txt").write_bytes(b"secret")
    # %2e%2e%2f == "../" — Starlette decodes it before our handler sees it
    r = client.get("/api/file?path=%2e%2e%2foutside.txt")
    assert r.status_code == 404


def test_file_missing_is_404(light_client):
    client, _, _ = light_client
    r = client.get("/api/file", params={"path": "data/nope.bin"})
    assert r.status_code == 404


def test_file_rejects_non_data_subtree(light_client):
    client, root, _ = light_client
    # a real source file under the project root but OUTSIDE data/ — safe_join
    # allows it (it is under root), but /api/file now serves only data/ (H4).
    src = root / "edits" / "myedit" / "__init__.py"
    assert src.is_file()
    r = client.get("/api/file", params={"path": "edits/myedit/__init__.py"})
    assert r.status_code == 404


def test_cors_restricted_to_dev_origins(light_client):
    client, _, _ = light_client
    # an allowlisted dev origin gets echoed back...
    good = client.get("/api/feedback", headers={"Origin": "http://localhost:5173"})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    # ...an arbitrary origin does not (no wildcard "*").
    evil = client.get("/api/feedback", headers={"Origin": "http://evil.example"})
    assert evil.headers.get("access-control-allow-origin") is None


# ─── job lifecycle: process-take ─────────────────────────────────────────────

class _FakeProcessResult:
    def __init__(self, out: Path):
        self.out = out
        self.input_i = -18.5
        self.input_tp = -2.0
        self.input_lra = 5.0
        self.input_thresh = -30.0
        self.duration = 3.2


def test_process_take_job_lifecycle(light_client, monkeypatch):
    client, root, _ = light_client
    (root / "data" / "recordings").mkdir(parents=True, exist_ok=True)
    (root / "data" / "recordings" / "take.webm").write_bytes(b"raw")

    calls = {}

    def fake_process_take(recording, out_wav, **kw):
        calls["process"] = (Path(recording), Path(out_wav))
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"vo")
        return _FakeProcessResult(Path(out_wav))

    def fake_transcribe(wav, out_json, **kw):
        calls["transcribe"] = (Path(wav), Path(out_json), kw)
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text("{}", encoding="utf-8")
        return Path(out_json)

    monkeypatch.setattr("dlstudio.services.process_take", fake_process_take)
    monkeypatch.setattr("dlstudio.services.transcribe", fake_transcribe)

    r = client.post("/api/actions/process-take", json={
        "beat_id": "b01", "recording_path": "data/recordings/take.webm",
    })
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    done = _await_job(client, job_id)
    assert done["status"] == "done"
    result = done["result"]
    # H1: the processed wav/words land at the beat's OWN declared paths, not a
    # hardcoded <id>_vo.wav — so a real edit's render/UI actually see the take.
    assert result["audio"] == "data/finalize/b01_audio_tight_pause.wav"
    assert result["words"] == "data/finalize/b01_words_tight.json"
    assert result["measured_lufs"] == -18.5
    assert result["duration"] == 3.2
    audio_out = root / "data" / "finalize" / "b01_audio_tight_pause.wav"
    words_out = root / "data" / "finalize" / "b01_words_tight.json"
    # 0.7 atomic promotion: services are called with same-dir TEMP paths (the
    # declared extension preserved for format inference), and the results are
    # os.replace()-promoted to the declared paths only after both succeed.
    assert calls["process"][0] == (root / "data" / "recordings" / "take.webm").resolve()
    assert calls["process"][1].parent == audio_out.parent
    assert calls["process"][1] != audio_out and calls["process"][1].suffix == ".wav"
    assert calls["transcribe"][0] == calls["process"][1]     # transcribed the temp wav
    assert calls["transcribe"][1].parent == words_out.parent
    assert calls["transcribe"][1] != words_out and calls["transcribe"][1].suffix == ".json"
    # the declared paths hold the promoted content; no temp litter remains
    assert audio_out.read_bytes() == b"vo"
    assert words_out.read_text(encoding="utf-8") == "{}"
    assert not list(audio_out.parent.glob("*.tmp-*"))


def test_process_take_rejects_traversal_recording(light_client):
    client, _, _ = light_client
    r = client.post("/api/actions/process-take", json={
        "beat_id": "b01", "recording_path": "../evil.webm",
    })
    assert r.status_code == 400


def test_process_take_unknown_beat_404(light_client):
    client, _, _ = light_client
    # membership is validated before the recording is touched (mirrors
    # render-beat); an unknown beat is a 404 (L5).
    r = client.post("/api/actions/process-take", json={
        "beat_id": "nope", "recording_path": "data/recordings/take.webm",
    })
    assert r.status_code == 404


def test_process_take_job_reports_error(light_client, monkeypatch):
    client, root, _ = light_client
    (root / "data" / "recordings").mkdir(parents=True, exist_ok=True)
    (root / "data" / "recordings" / "take.webm").write_bytes(b"raw")

    def boom(recording, out_wav, **kw):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr("dlstudio.services.process_take", boom)
    r = client.post("/api/actions/process-take", json={
        "beat_id": "b01", "recording_path": "data/recordings/take.webm",
    })
    job_id = r.json()["job_id"]
    done = _await_job(client, job_id)
    assert done["status"] == "error"
    assert "ffmpeg exploded" in done["error"]


def test_process_take_quality_rejection_persists_rejected_verdict(
    light_client,
    monkeypatch,
):
    client, root, _ = light_client
    recording = root / "data" / "recordings" / "take.webm"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"raw")

    from dlstudio import services

    verdict = {
        "schema": "dlstudio.voice-take-verdict",
        "version": 1,
        "verdict": "block",
        "recommended_action": "re_record",
    }

    def reject(recording, out_wav, **kw):
        raise services.VoiceTakeQualityError("click detected", verdict)

    monkeypatch.setattr("dlstudio.services.process_take", reject)
    response = client.post("/api/actions/process-take", json={
        "beat_id": "b01",
        "recording_path": "data/recordings/take.webm",
    })
    done = _await_job(client, response.json()["job_id"])

    assert done["status"] == "error"
    assert "click detected" in done["error"]
    rejected = root / "data" / "review" / "voice_takes" / "take.rejected.json"
    assert json.loads(rejected.read_text(encoding="utf-8"))["verdict"] == "block"


def test_process_take_failure_leaves_previous_take_intact(light_client, monkeypatch):
    """0.7 regression: WAV/words used to be written STRAIGHT to the beat's
    declared paths — a transcribe failure left a new wav with the OLD words
    (or a half-written wav). With temp+promote, any failure leaves the
    previous take byte-identical and no temp litter behind."""
    client, root, _ = light_client
    (root / "data" / "recordings").mkdir(parents=True, exist_ok=True)
    (root / "data" / "recordings" / "take.webm").write_bytes(b"raw")

    audio_out = root / "data" / "finalize" / "b01_audio_tight_pause.wav"
    words_out = root / "data" / "finalize" / "b01_words_tight.json"
    verdict_out = root / "data" / "review" / "voice_takes" / "take.json"
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    verdict_out.parent.mkdir(parents=True, exist_ok=True)
    audio_out.write_bytes(b"previous-take-wav")
    words_out.write_text('{"words": "previous"}', encoding="utf-8")
    verdict_out.write_text('{"verdict": "previous"}', encoding="utf-8")

    def fake_process_take(recording, out_wav, **kw):
        Path(out_wav).write_bytes(b"new-take-wav")     # stage 1 succeeds...
        return _FakeProcessResult(Path(out_wav))

    def failing_transcribe(wav, out_json, **kw):
        raise RuntimeError("whisper exploded")          # ...stage 2 fails

    monkeypatch.setattr("dlstudio.services.process_take", fake_process_take)
    monkeypatch.setattr("dlstudio.services.transcribe", failing_transcribe)

    r = client.post("/api/actions/process-take", json={
        "beat_id": "b01", "recording_path": "data/recordings/take.webm",
    })
    done = _await_job(client, r.json()["job_id"])
    assert done["status"] == "error"
    assert "whisper exploded" in done["error"]
    # the previous take survived untouched — nothing was promoted
    assert audio_out.read_bytes() == b"previous-take-wav"
    assert words_out.read_text(encoding="utf-8") == '{"words": "previous"}'
    assert verdict_out.read_text(encoding="utf-8") == '{"verdict": "previous"}'
    assert not list(audio_out.parent.glob("*.tmp-*"))


def test_parallel_process_take_jobs_same_beat_serialize(light_client, monkeypatch):
    """0.7: two Process jobs of ONE beat must never run concurrently (they
    write the same declared wav/words paths)."""
    client, root, _ = light_client
    (root / "data" / "recordings").mkdir(parents=True, exist_ok=True)
    (root / "data" / "recordings" / "take.webm").write_bytes(b"raw")

    state = {"active": 0, "max_active": 0}
    guard = threading.Lock()

    def slow_process_take(recording, out_wav, **kw):
        with guard:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.15)
        Path(out_wav).write_bytes(b"vo")
        with guard:
            state["active"] -= 1
        return _FakeProcessResult(Path(out_wav))

    def fake_transcribe(wav, out_json, **kw):
        Path(out_json).write_text("{}", encoding="utf-8")
        return Path(out_json)

    monkeypatch.setattr("dlstudio.services.process_take", slow_process_take)
    monkeypatch.setattr("dlstudio.services.transcribe", fake_transcribe)

    job_ids = []
    for _ in range(2):
        r = client.post("/api/actions/process-take", json={
            "beat_id": "b01", "recording_path": "data/recordings/take.webm",
        })
        job_ids.append(r.json()["job_id"])

    for jid in job_ids:
        done = _await_job(client, jid)
        assert done["status"] == "done", done
    assert state["max_active"] == 1, "two takes of one beat overlapped"


def test_jobs_unknown_id_404(light_client):
    client, _, _ = light_client
    assert client.get("/api/jobs/does-not-exist").status_code == 404


# ─── 2.6: stale-feedback protection — server-side artifact pinning ───────────

def test_feedback_verdict_gets_artifact_sha256_and_timestamp(light_client):
    import hashlib

    client, root, _ = light_client
    mp4 = root / "data" / "finalize" / "b01.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"reviewed-render-bytes")
    expected = hashlib.sha256(b"reviewed-render-bytes").hexdigest()

    r = client.post("/api/feedback", json={
        "b01": {"video": {
            "verdict": "needs-fixes",
            "artifact_path": "data/finalize/b01.mp4",
        }},
    })
    assert r.status_code == 200
    section = r.json()["b01"]["video"]
    assert section["artifact_sha256"] == expected
    assert section["timestamp"]
    # persisted, not just echoed
    stored = json.loads((root / "data" / "review" / "feedback.json")
                        .read_text(encoding="utf-8"))
    assert stored["b01"]["video"]["artifact_sha256"] == expected


def test_feedback_reviewer_provided_sha_not_overwritten(light_client):
    client, root, _ = light_client
    mp4 = root / "data" / "finalize" / "b01.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"whatever")

    r = client.post("/api/feedback", json={
        "b01": {"video": {
            "verdict": "ok",
            "artifact_path": "data/finalize/b01.mp4",
            "artifact_sha256": "reviewer-computed-value",
        }},
    })
    assert r.json()["b01"]["video"]["artifact_sha256"] == "reviewer-computed-value"


def test_feedback_missing_or_escaping_artifact_gets_no_sha(light_client):
    client, _, _ = light_client
    r = client.post("/api/feedback", json={
        "b01": {"video": {"verdict": "x", "artifact_path": "data/finalize/gone.mp4"},
                "vo": {"verdict": "y", "artifact_path": "../../etc/passwd"}},
    })
    assert r.status_code == 200
    body = r.json()["b01"]
    assert "artifact_sha256" not in body["video"]   # file doesn't exist
    assert "artifact_sha256" not in body["vo"]      # escapes the root
    # timestamps still stamped so staleness age is visible either way
    assert body["video"]["timestamp"]


# ─── safe_join vs Windows extended-length resolution (0.7/0.9 flake) ─────────

def test_safe_join_tolerates_extended_length_resolution(tmp_path, monkeypatch):
    """Under concurrent dir churn (two Studio jobs racing in data/finalize),
    Windows Path.resolve() transiently returns the `\\\\?\\`-prefixed
    extended form for one path and the plain form for another; relative_to
    then fails and safe_join rejected the beat's OWN declared paths. Pin
    that the containment check canonicalizes the prefix."""
    from dlstudio.api.paths import safe_join

    real_resolve = Path.resolve

    def extended_for_wav(self, strict=False):
        r = real_resolve(self, strict)
        if self.name.endswith(".wav") and not str(r).startswith("\\\\?\\"):
            return Path("\\\\?\\" + str(r))
        return r

    monkeypatch.setattr(Path, "resolve", extended_for_wav)
    got = safe_join(tmp_path, "data/finalize/b01_audio.wav")
    assert got is not None
    assert not str(got).startswith("\\\\?\\")


def test_safe_join_still_rejects_traversal(tmp_path):
    from dlstudio.api.paths import safe_join

    assert safe_join(tmp_path, "../evil.wav") is None
    assert safe_join(tmp_path, "C:/evil.wav") is None
    assert safe_join(tmp_path, "data/../../evil.wav") is None


def test_jobmanager_caps_finished_jobs():
    from dlstudio.api.jobs import JobManager

    jm = JobManager(max_workers=2, max_jobs=2)
    try:
        ids = [jm.submit(lambda: 42) for _ in range(4)]
        deadline = time.time() + 5.0
        while time.time() < deadline:
            snaps = [jm.get(i) for i in ids]
            if all(s is None or s["status"] != "running" for s in snaps):
                break
            time.sleep(0.01)
        # a further submit evicts finished jobs beyond the cap
        jm.submit(lambda: 42)
        assert len(jm._jobs) <= jm._max_jobs + 1
        # at least one of the original four was evicted
        assert sum(1 for i in ids if jm.get(i) is not None) < 4
    finally:
        jm.shutdown()


def test_jobmanager_evicts_by_ttl():
    from dlstudio.api.jobs import JobManager

    jm = JobManager(max_workers=1, ttl_seconds=0.0)
    try:
        first = jm.submit(lambda: 1)
        deadline = time.time() + 5.0
        while time.time() < deadline and (jm.get(first) or {}).get("status") == "running":
            time.sleep(0.01)
        time.sleep(0.01)  # ensure now - finished_at > 0
        jm.submit(lambda: 1)  # triggers TTL eviction of the finished first job
        assert jm.get(first) is None
    finally:
        jm.shutdown()


# ─── hot-reload: beats.py edits appear without a restart (H2) ─────────────────

def test_project_hot_reloads_edit_module(light_client):
    client, root, _ = light_client
    assert [b["id"] for b in client.get("/api/project").json()["beats"]] == ["b01"]

    two_beats = textwrap.dedent(
        """
        from dlstudio.model import Beat, Chunk, Design, Edit, Fonts, Palette, Plate

        EDIT = Edit(
            name="light",
            design=Design(
                resolution=(1920, 1080),
                palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
                fonts=Fonts(main="main.ttf"),
            ),
            beats={
                "b01": Beat(
                    audio="data/finalize/b01_audio_tight_pause.wav",
                    words="data/finalize/b01_words_tight.json",
                    vo="hi there world",
                    chunks=[Chunk(words=(0, 1), content=Plate(text="X"))],
                ),
                "b02": Beat(
                    audio="data/finalize/b02_audio.wav",
                    words="data/finalize/b02_words.json",
                    vo="second beat",
                    chunks=[Chunk(words=(0, 1), content=Plate(text="Y"))],
                ),
            },
            order=["b01", "b02"],
            output="data/finalize/out.mp4",
        )
        """
    )
    (root / "edits" / "myedit" / "__init__.py").write_text(two_beats, encoding="utf-8")

    data = client.get("/api/project").json()
    assert [b["id"] for b in data["beats"]] == ["b01", "b02"]


def test_script_approval_is_hash_bound_and_invalidates_after_vo_edit(light_client):
    client, root, _ = light_client
    initial = client.get("/api/project").json()
    assert initial["script_approved"] is False
    assert len(initial["script_sha256"]) == 64

    approved = client.post("/api/script/approve", json={"approved_by": "author"})
    assert approved.status_code == 200
    assert approved.json()["script_approved"] is True
    assert client.get("/api/project").json()["script_approved"] is True
    assert (root / "data" / "plan" / "script_approval.json").is_file()

    init_path = root / "edits" / "myedit" / "__init__.py"
    source = init_path.read_text(encoding="utf-8")
    init_path.write_text(source.replace("hi there world", "hi changed world"), encoding="utf-8")

    changed = client.get("/api/project").json()
    assert changed["script_approved"] is False
    assert changed["script_sha256"] != initial["script_sha256"]


def test_stale_script_approval_blocks_take_upload(light_client):
    client, root, _ = light_client
    assert client.post(
        "/api/script/approve",
        json={"approved_by": "author"},
    ).status_code == 200
    init_path = root / "edits" / "myedit" / "__init__.py"
    init_path.write_text(
        init_path.read_text(encoding="utf-8").replace(
            "hi there world",
            "hot edited script",
        ),
        encoding="utf-8",
    )

    response = client.post(
        "/api/takes/b01",
        files={"file": ("take.webm", b"AUDIO-BYTES", "audio/webm")},
    )

    assert response.status_code == 409
    assert "approval is stale" in response.json()["detail"]
    recordings = root / "data" / "recordings"
    assert not (recordings.exists() and list(recordings.glob("b01_*")))


def test_stale_script_approval_blocks_take_processing(light_client):
    client, root, _ = light_client
    assert client.post(
        "/api/script/approve",
        json={"approved_by": "author"},
    ).status_code == 200
    recording = root / "data" / "recordings" / "take.webm"
    recording.parent.mkdir(parents=True, exist_ok=True)
    recording.write_bytes(b"raw")
    init_path = root / "edits" / "myedit" / "__init__.py"
    init_path.write_text(
        init_path.read_text(encoding="utf-8").replace(
            "hi there world",
            "hot edited script",
        ),
        encoding="utf-8",
    )

    response = client.post("/api/actions/process-take", json={
        "beat_id": "b01",
        "recording_path": "data/recordings/take.webm",
    })

    assert response.status_code == 409
    assert "approval is stale" in response.json()["detail"]


def test_project_hot_reloads_filesystem_production(tmp_path, monkeypatch):
    product = tmp_path / "not_a_trolley_problem"
    production = product / "reels" / "2026_07_18_reel_01"
    devlog = product / "devlogs" / "2026_07_17_devlog_01"
    edit_dir = production / "edit"
    edit_dir.mkdir(parents=True)
    (devlog / "edit").mkdir(parents=True)
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    (product / "product.toml").write_text(
        "\n".join(
            [
                'id = "not_a_trolley_problem"',
                'title = "Not a Trolley Problem"',
                'game_root = "C:/projects/game-67-idle"',
                "[sources]",
                'diary = "https://neotolis-diary.dev"',
            ]
        ),
        encoding="utf-8",
    )
    (production / "production.toml").write_text(
        "\n".join(
            [
                'id = "2026_07_18_reel_01"',
                'kind = "reel"',
                'date = "2026-07-18"',
                'orientation = "vertical"',
                'edit_path = "edit"',
                'data_root = "data"',
                'delivery_root = "../../delivery/reels/2026_07_18_reel_01"',
            ]
        ),
        encoding="utf-8",
    )
    (devlog / "production.toml").write_text(
        "\n".join(
            [
                'id = "2026_07_17_devlog_01"',
                'kind = "devlog"',
                'date = "2026-07-17"',
                'orientation = "landscape"',
                'edit_path = "edit"',
                'data_root = "data"',
                'delivery_root = "../../delivery/devlogs/2026_07_17_devlog_01"',
            ]
        ),
        encoding="utf-8",
    )
    source_v1 = textwrap.dedent(
        """
        from dlstudio.model import Design, Edit, Fonts, Palette
        EDIT = Edit(
            name="filesystem-v1",
            design=Design(
                resolution=(1080, 1920),
                palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
                fonts=Fonts(main="data/fonts/main.ttf"),
            ),
            beats={}, order=[], output="data/finalize/final.mp4",
        )
        """
    )
    init_path = edit_dir / "__init__.py"
    init_path.write_text(source_v1, encoding="utf-8")
    (devlog / "edit" / "__init__.py").write_text(
        source_v1.replace("filesystem-v1", "devlog-v1"), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with TestClient(create_app(str(production))) as client:
        project_data = client.get("/api/project").json()
        assert project_data["edit_name"] == "filesystem-v1"
        assert project_data["product"] == {
            "id": "not_a_trolley_problem",
            "title": "Not a Trolley Problem",
            "current_production_id": "2026_07_18_reel_01",
            "productions": [
                {
                    "id": "2026_07_17_devlog_01",
                    "kind": "devlog",
                    "date": "2026-07-17",
                    "orientation": "landscape",
                    "studio_ref": "not_a_trolley_problem:2026_07_17_devlog_01",
                    "current": False,
                },
                {
                    "id": "2026_07_18_reel_01",
                    "kind": "reel",
                    "date": "2026-07-18",
                    "orientation": "vertical",
                    "studio_ref": "not_a_trolley_problem:2026_07_18_reel_01",
                    "current": True,
                },
            ],
        }
        init_path.write_text(source_v1.replace("filesystem-v1", "filesystem-v2"), encoding="utf-8")
        assert client.get("/api/project").json()["edit_name"] == "filesystem-v2"


# ─── job lifecycle: render-beat ──────────────────────────────────────────────

def test_render_beat_job_lifecycle(light_client, monkeypatch, tmp_path):
    client, root, _ = light_client

    from conftest import make_ir_beat, make_timeline

    timeline = make_timeline([make_ir_beat("b01", duration=4.0)])

    def fake_build_timeline(edit, **kw):
        return timeline

    def fake_render_beat(beat, design, _timeline, opts):
        out = Path(opts.workdir) / f"{beat.id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"rendered-mp4")
        return out

    monkeypatch.setattr("dlstudio.compile.build_timeline", fake_build_timeline)
    monkeypatch.setattr("dlstudio.render.render_beat", fake_render_beat)

    r = client.post("/api/actions/render-beat", json={"beat_id": "b01"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    done = _await_job(client, job_id)
    assert done["status"] == "done", done
    assert done["result"]["output"] == "data/finalize/b01.mp4"
    assert (root / "data" / "finalize" / "b01.mp4").is_file()


def test_render_beat_unknown_beat_404(light_client):
    client, _, _ = light_client
    r = client.post("/api/actions/render-beat", json={"beat_id": "nope"})
    assert r.status_code == 404


def test_parallel_render_jobs_same_beat_serialize_and_cache_stays_valid(
    light_client, monkeypatch, tmp_path,
):
    """0.9 regression: the jobs executor is a ThreadPool in ONE process with
    no dedup — two render jobs of the same beat used to share the workdir MP4
    and the pid-keyed cache tmp path, publishing a torn MP4 into the cache as
    a lasting hit. Per-beat serialization means the second job waits, then
    simply materializes the first job's cache entry: exactly ONE render."""
    client, root, _ = light_client
    from dlstudio import cache as dl_cache

    monkeypatch.setattr(dl_cache, "CACHE_DIR", tmp_path / "cache2")

    from conftest import make_ir_beat, make_timeline

    timeline = make_timeline([make_ir_beat("b01", duration=4.0)])
    monkeypatch.setattr("dlstudio.compile.build_timeline", lambda edit, **kw: timeline)

    render_count = {"n": 0}

    def slow_render_beat(beat, design, _timeline, opts):
        render_count["n"] += 1
        time.sleep(0.15)
        out = Path(opts.workdir) / f"{beat.id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"rendered-mp4-payload")
        dl_cache.vo_stem_sibling(out).write_bytes(b"rendered-stem")
        return out

    monkeypatch.setattr("dlstudio.render.render_beat", slow_render_beat)

    job_ids = []
    for _ in range(2):
        r = client.post("/api/actions/render-beat", json={"beat_id": "b01"})
        job_ids.append(r.json()["job_id"])

    for jid in job_ids:
        done = _await_job(client, jid)
        assert done["status"] == "done", done
    assert render_count["n"] == 1, "same-beat render jobs were not deduplicated"
    # the published cache entry is a complete, untorn pair
    entries = list((tmp_path / "cache2").glob("*.mp4"))
    assert len(entries) == 1
    assert entries[0].read_bytes() == b"rendered-mp4-payload"
    assert entries[0].with_suffix(".wav").read_bytes() == b"rendered-stem"
    assert not list((tmp_path / "cache2").glob("*.tmp-*"))


def test_render_beat_job_blocks_on_check_errors(light_client, monkeypatch):
    """0.4: the Studio API render path runs the same pre-render gate as the
    CLI — a timeline with a mechanical ERROR must fail the job before
    render_beat is ever invoked."""
    client, _, _ = light_client

    from conftest import make_ir_beat, make_timeline
    from dlstudio.ir import AssetProbe

    tl = make_timeline([make_ir_beat("b01", duration=4.0)])
    tl = tl.model_copy(update={"assets": {
        "data/gone.png": AssetProbe(path="data/gone.png", kind="image", exists=False),
    }})
    monkeypatch.setattr("dlstudio.compile.build_timeline", lambda edit, **kw: tl)

    def must_not_render(*a, **k):
        raise AssertionError("render must not start when checks error")

    monkeypatch.setattr("dlstudio.render.render_beat", must_not_render)

    r = client.post("/api/actions/render-beat", json={"beat_id": "b01"})
    assert r.status_code == 200
    job = _await_job(client, r.json()["job_id"])
    assert job["status"] == "error", job
    assert "pre-render checks failed" in job["error"]
