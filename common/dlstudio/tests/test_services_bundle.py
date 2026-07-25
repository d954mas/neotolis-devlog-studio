from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest


def test_promote_bundle_publishes_all_files_and_removes_journal(tmp_path):
    from dlstudio.services.bundle import promote_bundle

    first = tmp_path / "data" / "audio.wav"
    second = tmp_path / "data" / "words.json"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"old-audio")
    second.write_bytes(b"old-words")
    staged_first = first.with_name(".audio.staged.wav")
    staged_second = second.with_name(".words.staged.json")
    staged_first.write_bytes(b"new-audio")
    staged_second.write_bytes(b"new-words")

    promote_bundle([(staged_first, first), (staged_second, second)])

    assert first.read_bytes() == b"new-audio"
    assert second.read_bytes() == b"new-words"
    assert not list(tmp_path.rglob(".dlstudio-bundle-*.json"))


def test_recovery_rolls_back_a_process_crash_mid_promotion(tmp_path):
    from dlstudio.services.bundle import recover_bundle_transactions

    root = tmp_path / "data"
    root.mkdir()
    first = root / "audio.wav"
    second = root / "words.json"
    first.write_bytes(b"new-audio")
    staged_second = root / ".words.staged.json"
    staged_second.write_bytes(b"new-words")
    first_backup = root / ".audio.wav.backup-crash"
    second_backup = root / ".words.json.backup-crash"
    first_backup.write_bytes(b"old-audio")
    second_backup.write_bytes(b"old-words")
    journal = root / ".dlstudio-bundle-crash.json"
    journal.write_text(json.dumps({
        "schema": "dlstudio.bundle_transaction",
        "version": 1,
        "state": "backed_up",
        "promoted": 1,
        "entries": [
            {
                "staged": str(root / ".audio.staged.wav"),
                "target": str(first),
                "backup": str(first_backup),
                "had_target": True,
            },
            {
                "staged": str(staged_second),
                "target": str(second),
                "backup": str(second_backup),
                "had_target": True,
            },
        ],
    }), encoding="utf-8")

    recover_bundle_transactions(tmp_path)

    assert first.read_bytes() == b"old-audio"
    assert second.read_bytes() == b"old-words"
    assert not journal.exists()
    assert not staged_second.exists()


def test_parallel_promotions_do_not_recover_each_others_live_journal(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services import bundle

    root = tmp_path / "data"
    root.mkdir()
    staged_a = root / ".a.staged"
    staged_b = root / ".b.staged"
    target_a = root / "a.wav"
    target_b = root / "b.wav"
    staged_a.write_bytes(b"a")
    staged_b.write_bytes(b"b")
    first_prepared = threading.Event()
    release_first = threading.Event()
    original_write = bundle._write_journal

    def slow_first_transaction(path, payload):
        original_write(path, payload)
        entries = payload.get("entries") or []
        if (
            payload.get("state") == "prepared"
            and entries
            and entries[0].get("target") == str(target_a.resolve())
            and not first_prepared.is_set()
        ):
            first_prepared.set()
            assert release_first.wait(timeout=5)

    monkeypatch.setattr(bundle, "_write_journal", slow_first_transaction)
    errors: list[BaseException] = []

    def promote(staged, target):
        try:
            bundle.promote_bundle([(staged, target)])
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=promote, args=(staged_a, target_a))
    second = threading.Thread(target=promote, args=(staged_b, target_b))
    first.start()
    assert first_prepared.wait(timeout=5)
    second.start()
    time.sleep(0.05)
    assert not target_b.exists()
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert target_a.read_bytes() == b"a"
    assert target_b.read_bytes() == b"b"
    assert not list(root.glob(".dlstudio-bundle-*.json"))


def test_recovery_rejects_journal_paths_outside_recovery_root(tmp_path):
    from dlstudio.services.bundle import recover_bundle_transactions

    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("must survive", encoding="utf-8")
    journal = root / ".dlstudio-bundle-escape.json"
    journal.write_text(json.dumps({
        "schema": "dlstudio.bundle_transaction",
        "version": 1,
        "state": "backed_up",
        "promoted": 0,
        "entries": [{
            "staged": str(outside),
            "target": str(root / "safe.txt"),
            "backup": str(root / ".safe.txt.backup-escape"),
            "had_target": False,
        }],
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="escapes recovery root"):
        recover_bundle_transactions(root)

    assert outside.read_text(encoding="utf-8") == "must survive"


def test_bundle_reader_waits_until_multi_file_promotion_is_complete(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services import bundle

    data = tmp_path / "data"
    audio = data / "audio" / "take.wav"
    words = data / "audio" / "take_words.json"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"old-audio")
    words.write_bytes(b"old-words")
    staged_audio = data / "audio" / ".take.wav.staged"
    staged_words = data / "audio" / ".take_words.json.staged"
    staged_audio.write_bytes(b"new-audio")
    staged_words.write_bytes(b"new-words")

    first_promoted = threading.Event()
    release_writer = threading.Event()
    real_replace = bundle.os.replace

    def pausing_replace(source, target):
        real_replace(source, target)
        if Path(source) == staged_audio:
            first_promoted.set()
            assert release_writer.wait(timeout=5)

    monkeypatch.setattr(bundle.os, "replace", pausing_replace)
    writer = threading.Thread(
        target=bundle.promote_bundle,
        args=([(staged_audio, audio), (staged_words, words)],),
    )
    writer.start()
    assert first_promoted.wait(timeout=5)

    observed: list[tuple[bytes, bytes]] = []
    reader_entered = threading.Event()

    def read_bundle():
        with bundle.bundle_read_lock([audio, words]):
            reader_entered.set()
            observed.append((audio.read_bytes(), words.read_bytes()))

    reader = threading.Thread(target=read_bundle)
    reader.start()
    time.sleep(0.05)
    assert not reader_entered.is_set()
    release_writer.set()
    writer.join(timeout=5)
    reader.join(timeout=5)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert observed == [(b"new-audio", b"new-words")]
