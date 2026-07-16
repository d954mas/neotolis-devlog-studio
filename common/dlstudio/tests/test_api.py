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
                audio="data/finalize/b01_vo.wav",
                words="data/finalize/b01_words.json",
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
    (data / "font.ttf").write_bytes(b"placeholder-font")

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


def test_takes_upload_rejects_bad_beat_id(light_client):
    client, _, _ = light_client
    # a backslash in the id is rejected by safe_component (routes as one segment)
    r = client.post(
        "/api/takes/bad%5Cid",
        files={"file": ("t.webm", b"x", "audio/webm")},
    )
    assert r.status_code == 400


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
    assert result["audio"] == "data/finalize/b01_vo.wav"
    assert result["words"] == "data/finalize/b01_words.json"
    assert result["measured_lufs"] == -18.5
    assert result["duration"] == 3.2
    # services were called with the resolved absolute recording + finalize paths
    assert calls["process"][0] == (root / "data" / "recordings" / "take.webm").resolve()
    assert calls["process"][1] == root / "data" / "finalize" / "b01_vo.wav"


def test_process_take_rejects_traversal_recording(light_client):
    client, _, _ = light_client
    r = client.post("/api/actions/process-take", json={
        "beat_id": "b01", "recording_path": "../evil.webm",
    })
    assert r.status_code == 400


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


def test_jobs_unknown_id_404(light_client):
    client, _, _ = light_client
    assert client.get("/api/jobs/does-not-exist").status_code == 404


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
