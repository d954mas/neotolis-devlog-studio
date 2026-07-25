"""Crash-recoverable promotion for multi-file production artifacts."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import threading
import uuid
from pathlib import Path


_JOURNAL_PREFIX = ".dlstudio-bundle-"
_LOCK_NAME = ".dlstudio-bundle.lock"
_PROCESS_LOCKS: dict[Path, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


@contextmanager
def _bundle_transaction_lock(directory: Path):
    """Serialize recovery/promotion in one target directory across processes."""

    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(root, threading.RLock())
    with process_lock:
        lock_path = root / _LOCK_NAME
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - Windows is the production platform
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_journal(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _recover_journal(path: Path) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid bundle recovery journal: {path}") from exc
    entries = payload.get("entries")
    if (
        payload.get("schema") != "dlstudio.bundle_transaction"
        or payload.get("version") != 1
        or not isinstance(entries, list)
    ):
        raise RuntimeError(f"invalid bundle recovery entries: {path}")
    root = path.parent.resolve()
    nonce = path.name.removeprefix(_JOURNAL_PREFIX).removesuffix(".json")

    def confined(raw: object, label: str) -> Path:
        candidate = Path(str(raw or ""))
        if not candidate.is_absolute():
            raise RuntimeError(f"bundle {label} path is not absolute: {path}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                f"bundle {label} path escapes recovery root: {path}"
            ) from exc
        return resolved

    committed = payload.get("state") == "committed"
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"invalid bundle recovery entry: {path}")
        staged = confined(entry.get("staged"), "staged")
        target = confined(entry.get("target"), "target")
        backup = confined(entry.get("backup"), "backup")
        expected_backup = target.with_name(f".{target.name}.backup-{nonce}")
        if backup != expected_backup:
            raise RuntimeError(f"bundle backup path is invalid: {path}")
        had_target = entry.get("had_target") is True
        if not committed:
            if backup.is_file():
                target.unlink(missing_ok=True)
                os.replace(backup, target)
            elif not had_target and target.is_file() and not staged.exists():
                target.unlink()
        backup.unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
    path.unlink(missing_ok=True)


def _recover_directory(directory: Path) -> None:
    for journal in sorted(directory.glob(f"{_JOURNAL_PREFIX}*.json")):
        _recover_journal(journal)


def recover_bundle_transactions(root: str | Path) -> None:
    """Restore interrupted transactions without touching a live promotion."""

    base = Path(root).resolve()
    if not base.is_dir():
        return
    directories = {
        journal.parent.resolve()
        for journal in base.rglob(f"{_JOURNAL_PREFIX}*.json")
    }
    for directory in sorted(directories):
        with _bundle_transaction_lock(directory):
            _recover_directory(directory)


def promote_bundle(replacements: list[tuple[Path, Path]]) -> None:
    """Publish staged files with a durable journal and crash recovery."""

    if not replacements:
        return
    staged_paths = [Path(staged).resolve() for staged, _target in replacements]
    target_paths = [Path(target).resolve() for _staged, target in replacements]
    if len(set(target_paths)) != len(target_paths):
        raise ValueError("bundle targets must be unique")
    missing = [path for path in staged_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"bundle staged file is missing: {missing[0]}")
    common = Path(os.path.commonpath([str(path.parent) for path in target_paths]))
    common.mkdir(parents=True, exist_ok=True)

    with _bundle_transaction_lock(common):
        _recover_directory(common)
        nonce = uuid.uuid4().hex
        journal = common / f"{_JOURNAL_PREFIX}{nonce}.json"
        entries = []
        for staged, target in zip(staged_paths, target_paths, strict=True):
            target.parent.mkdir(parents=True, exist_ok=True)
            entries.append({
                "staged": str(staged),
                "target": str(target),
                "backup": str(target.with_name(f".{target.name}.backup-{nonce}")),
                "had_target": target.exists(),
            })
        payload = {
            "schema": "dlstudio.bundle_transaction",
            "version": 1,
            "state": "prepared",
            "promoted": 0,
            "entries": entries,
        }
        _write_journal(journal, payload)
        try:
            for entry in entries:
                target = Path(entry["target"])
                if entry["had_target"]:
                    os.replace(target, Path(entry["backup"]))
            payload["state"] = "backed_up"
            _write_journal(journal, payload)
            for index, entry in enumerate(entries, start=1):
                os.replace(Path(entry["staged"]), Path(entry["target"]))
                payload["promoted"] = index
                _write_journal(journal, payload)
            payload["state"] = "committed"
            _write_journal(journal, payload)
        except BaseException:
            _recover_journal(journal)
            raise
        for entry in entries:
            Path(entry["backup"]).unlink(missing_ok=True)
        journal.unlink(missing_ok=True)


__all__ = ["promote_bundle", "recover_bundle_transactions"]
