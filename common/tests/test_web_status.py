import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette
from devlog.web.serve import _ThreadedServer, _status_to_dict, build_handler_class


def _edit_with_missing_assets(tmp_path: Path) -> Edit:
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display=str(tmp_path / "display.ttf"), text=str(tmp_path / "text.ttf"))
    (tmp_path / "display.ttf").write_bytes(b"font")
    (tmp_path / "text.ttf").write_bytes(b"font")
    design = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    edit = Edit(
        name="youtube",
        design=design,
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                title="A",
                audio="data/finalize/missing.wav",
                words="data/finalize/missing.json",
                chunks=[Chunk(words=(0, 1), kind="plate", text="A")],
            )
        },
    )
    return edit


def test_status_to_dict_reports_errors_and_beats(tmp_path: Path):
    edit = _edit_with_missing_assets(tmp_path)
    status = _status_to_dict(edit, tmp_path)
    assert status["errors"] >= 1
    assert status["beats"][0]["beat_id"] == "a"


def test_check_action_returns_status_json(tmp_path: Path):
    edit = _edit_with_missing_assets(tmp_path)
    handler = build_handler_class(edit, tmp_path)

    with _ThreadedServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/actions/check"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                status = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert status["errors"] >= 1
    assert status["beats"][0]["beat_id"] == "a"


def test_render_action_requires_edit_path(tmp_path: Path):
    edit = _edit_with_missing_assets(tmp_path)
    handler = build_handler_class(edit, tmp_path)

    with _ThreadedServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/actions/render/a"
            req = urllib.request.Request(url, method="POST")
            try:
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                code = exc.code
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert code == 400
    assert "edit module path" in payload["error"]


def test_audio_action_requires_edit_path(tmp_path: Path):
    edit = _edit_with_missing_assets(tmp_path)
    rec_dir = tmp_path / "data" / "recordings"
    rec_dir.mkdir(parents=True)
    (rec_dir / "take.webm").write_bytes(b"fake")
    handler = build_handler_class(edit, tmp_path)

    with _ThreadedServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/actions/audio/a/take.webm"
            req = urllib.request.Request(url, method="POST")
            try:
                urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                payload = json.loads(exc.read().decode("utf-8"))
                code = exc.code
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert code == 400
    assert "edit module path" in payload["error"]
