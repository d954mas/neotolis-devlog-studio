"""Production-scoped data contract for Studio's single Autopilot checkpoint.

The checkpoint is deliberately deterministic: it joins the shot ledger,
asset catalog and preflight report, and exposes only two mutations.  Package
approval can flip existing ``approved`` booleans when no blockers remain;
content-changing actions are persisted as requests and never edit the shot
or VO automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_ACTIONS = {"replace_shot", "request_capture", "change_text"}
_APPROVAL = Path("data/plan/autopilot_approval.json")
_REQUESTS = Path("data/plan/autopilot_requests.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def preflight_manifest_sha256(path: Path) -> str:
    """Hash preflight-relevant manifest content, excluding approval flags."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    for shot in _shots(normalized):
        shot.pop("approved", None)
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compiled_timeline_sha256(timeline: Any) -> str:
    if not hasattr(timeline, "model_dump"):
        raise ValueError("compiled timeline does not expose a deterministic model")
    encoded = json.dumps(
        timeline.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_compiled_ir_sha256(base: Path) -> str:
    from dlstudio.compile import build_timeline
    from dlstudio.production import load_production_edit_module

    module, _manifest, _module_name = load_production_edit_module(
        base,
        force_reload=True,
    )
    edit = getattr(module, "EDIT", None)
    if edit is None:
        raise ValueError(f"production edit does not expose EDIT: {base / 'edit'}")
    return compiled_timeline_sha256(build_timeline(edit))


@contextmanager
def _checkpoint_transaction_lock(base: Path):
    """Share the production writer lock with ``autopilot-run``."""

    path = base / "data" / "review" / ".autopilot-run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(
                "autopilot production state is being changed by another process"
            ) from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _editorial_hashes(
    base: Path,
    preflight: Any,
) -> tuple[dict[str, str], list[str]]:
    """Hash edit code, design inputs, and exact author-review artifacts."""

    candidates: set[Path] = set()
    for relative in (
        "production.toml",
        "data/plan/story_contract.json",
        "data/plan/script_approval.json",
        "data/review/storyboard_boundaries.json",
        "data/review/review_pack.json",
        "data/review/review_pack_sheet.jpg",
    ):
        path = base / relative
        if path.is_file():
            candidates.add(path)
    for directory in (base / "edit", base / "data" / "fonts"):
        if directory.is_dir():
            candidates.update(path for path in directory.rglob("*") if path.is_file())

    errors: list[str] = []
    inputs = preflight.get("inputs", {}) if isinstance(preflight, dict) else {}
    artifact_value = inputs.get("render_artifact") if isinstance(inputs, dict) else None
    if artifact_value:
        artifact = Path(str(artifact_value))
        artifact = artifact.resolve() if artifact.is_absolute() else (base / artifact).resolve()
        if artifact.is_symlink() or not artifact.is_file():
            errors.append("reviewed render artifact is missing")
        else:
            expected = str(inputs.get("render_artifact_sha256") or "").casefold()
            actual = _sha256(artifact)
            if not expected or actual != expected:
                errors.append("reviewed render artifact SHA-256 is stale")
            candidates.add(artifact)

    hashes: dict[str, str] = {}
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        resolved = path.resolve()
        try:
            key = resolved.relative_to(base).as_posix()
        except ValueError:
            key = str(resolved)
        hashes[key] = _sha256(resolved)
    return hashes, errors


def _shots(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("shots", []) if isinstance(payload, dict) else payload
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _issues(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("issues", []) if isinstance(payload, dict) else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _wall_time(preflight: Any) -> dict[str, Any]:
    source = preflight.get("wall_time", {}) if isinstance(preflight, dict) else {}
    if not isinstance(source, dict):
        source = {}
    budget = max(0.0, _number(source.get("budget_minutes"), 60.0))
    elapsed = max(0.0, _number(source.get("elapsed_minutes"), 0.0))
    return {
        "budget_minutes": budget,
        "elapsed_minutes": elapsed,
        "remaining_minutes": max(0.0, budget - elapsed),
        "stage": str(source.get("stage") or "checkpoint"),
    }


def _duration(shot: dict[str, Any]) -> float:
    if shot.get("duration_seconds") is not None:
        return max(0.0, _number(shot.get("duration_seconds")))
    return max(0.0, _number(shot.get("t1")) - _number(shot.get("t0")))


def _open_requests(base: Path) -> list[dict[str, Any]]:
    payload = _read_json(base / _REQUESTS, {})
    requests = payload.get("requests", []) if isinstance(payload, dict) else []
    if not isinstance(requests, list):
        return []
    closed = {"resolved", "rejected", "cancelled", "completed"}
    return [
        item
        for item in requests
        if isinstance(item, dict)
        and str(item.get("status", "requested")).casefold() not in closed
    ]


def _source_hashes(
    base: Path,
    manifest: Any,
    catalog: Any,
) -> tuple[dict[str, str], list[str]]:
    items = catalog.get("assets", []) if isinstance(catalog, dict) else []
    assets = {
        str(item.get("path", "")).replace("\\", "/"): item
        for item in items
        if isinstance(item, dict) and item.get("path")
    }
    hashes: dict[str, str] = {}
    errors: list[str] = []
    for src in sorted({
        str(shot.get("src") or "").replace("\\", "/")
        for shot in _shots(manifest)
        if shot.get("src")
    }):
        entry = assets.get(src)
        if entry is None:
            errors.append(f"approved source is absent from catalog: {src}")
            continue
        value = Path(src)
        path = value.resolve() if value.is_absolute() else (base / value).resolve()
        if path.is_symlink() or not path.is_file():
            errors.append(f"approved source is missing or not a regular file: {src}")
            continue
        actual = _sha256(path)
        catalog_hash = str(entry.get("sha256") or "").casefold()
        if catalog_hash and catalog_hash != actual:
            errors.append(f"asset catalog SHA-256 is stale for source: {src}")
            continue
        hashes[src] = actual
    return hashes, errors


def _approval_status(
    base: Path,
    manifest_path: Path,
    catalog_path: Path,
    manifest: Any,
    catalog: Any,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    approval = _read_json(base / _APPROVAL, None)
    if not isinstance(approval, dict):
        return False, ["hash-bound author approval is missing"], None
    errors: list[str] = []
    if not manifest_path.is_file() or approval.get("manifest_sha256") != _sha256(manifest_path):
        errors.append("shot manifest changed after author approval")
    if not catalog_path.is_file() or approval.get("catalog_sha256") != _sha256(catalog_path):
        errors.append("asset catalog changed after author approval")
    preflight_path = base / "data" / "review" / "preflight.json"
    if (
        not preflight_path.is_file()
        or approval.get("preflight_sha256") != _sha256(preflight_path)
    ):
        errors.append("preflight changed after author approval")
    current_sources, source_errors = _source_hashes(base, manifest, catalog)
    errors.extend(source_errors)
    if approval.get("source_sha256") != current_sources:
        errors.append("reviewed source bytes changed after author approval")
    preflight = _read_json(preflight_path, {})
    current_editorial, editorial_errors = _editorial_hashes(base, preflight)
    errors.extend(editorial_errors)
    if approval.get("editorial_sha256") != current_editorial:
        errors.append("edit, design, or reviewed artifact changed after author approval")
    if not str(approval.get("approved_by") or "").strip():
        errors.append("author approval has no approver identity")
    return not errors, errors, approval


def _checkpoint_digest(
    base: Path,
    manifest_path: Path,
    catalog_path: Path,
    preflight_path: Path,
    manifest: Any,
    catalog: Any,
) -> str:
    source_hashes, source_errors = _source_hashes(base, manifest, catalog)
    preflight = _read_json(preflight_path, {})
    editorial_hashes, editorial_errors = _editorial_hashes(base, preflight)
    payload = {
        "manifest_sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
        "catalog_sha256": _sha256(catalog_path) if catalog_path.is_file() else None,
        "preflight_sha256": _sha256(preflight_path) if preflight_path.is_file() else None,
        "source_sha256": source_hashes,
        "source_errors": source_errors,
        "editorial_sha256": editorial_hashes,
        "editorial_errors": editorial_errors,
        "open_requests": _open_requests(base),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_checkpoint(root: str | Path) -> dict[str, Any]:
    """Join all production-scoped checkpoint inputs into one stable response."""
    base = Path(root).resolve()
    manifest_path = base / "data" / "plan" / "shot_manifest.json"
    catalog_path = base / "data" / "assets" / "catalog.json"
    preflight_path = base / "data" / "review" / "preflight.json"
    missing = [
        path.relative_to(base).as_posix()
        for path in (manifest_path, catalog_path, preflight_path)
        if not path.is_file()
    ]
    manifest = _read_json(manifest_path, {})
    catalog = _read_json(catalog_path, {})
    preflight = _read_json(preflight_path, {})
    open_requests = _open_requests(base)

    catalog_items = catalog.get("assets", []) if isinstance(catalog, dict) else []
    assets = {
        str(item.get("path", "")).replace("\\", "/"): item
        for item in catalog_items
        if isinstance(item, dict) and item.get("path")
    }
    issues = _issues(preflight)
    blockers = [item for item in issues if str(item.get("severity", "")).casefold() == "error"]
    notices = [item for item in issues if str(item.get("severity", "")).casefold() != "error"]
    for path in missing:
        blockers.append({
            "severity": "error",
            "code": "AUTOPILOT-MISSING",
            "message": f"required checkpoint input is missing: {path}",
            "where": path,
        })
    for request in open_requests:
        blockers.append({
            "severity": "error",
            "code": "AUTOPILOT-REQUEST",
            "message": (
                f"pending author request {request.get('id', '<unknown>')}: "
                f"{request.get('action', 'change')}"
            ),
            "where": "data/plan/autopilot_requests.json",
        })
    preflight_inputs = preflight.get("inputs", {}) if isinstance(preflight, dict) else {}
    if not isinstance(preflight_inputs, dict):
        preflight_inputs = {}
    if (base / "edit" / "__init__.py").is_file():
        expected_ir = str(preflight_inputs.get("compiled_ir_sha256") or "")
        try:
            current_ir = _current_compiled_ir_sha256(base)
        except Exception as exc:
            blockers.append({
                "severity": "error",
                "code": "AUTOPILOT-STALE-PREFLIGHT",
                "message": f"cannot compile current edit for checkpoint: {exc}",
                "where": "edit/__init__.py",
            })
        else:
            if not expected_ir or expected_ir != current_ir:
                blockers.append({
                    "severity": "error",
                    "code": "AUTOPILOT-STALE-PREFLIGHT",
                    "message": "preflight compiled IR digest does not match current edit",
                    "where": preflight_path.relative_to(base).as_posix(),
                })
    for label, path, field in (
        ("shot manifest", manifest_path, "shot_manifest_sha256"),
        ("asset catalog", catalog_path, "asset_catalog_sha256"),
    ):
        if not path.is_file():
            continue
        expected = preflight_inputs.get(field)
        actual = (
            preflight_manifest_sha256(path)
            if field == "shot_manifest_sha256"
            else _sha256(path)
        )
        if expected != actual:
            blockers.append({
                "severity": "error",
                "code": "AUTOPILOT-STALE-PREFLIGHT",
                "message": f"preflight is stale for current {label}",
                "where": preflight_path.relative_to(base).as_posix(),
            })

    rows: list[dict[str, Any]] = []
    for index, shot in enumerate(_shots(manifest)):
        shot_id = str(shot.get("id") or f"shot-{index + 1}")
        src = str(shot.get("src") or "").replace("\\", "/")
        asset = assets.get(src, {})
        matching = [
            issue for issue in issues
            if str(issue.get("where") or "") in {shot_id, src}
        ]
        flags = {
            str(flag)
            for values in (shot.get("quality_flags", []), asset.get("quality_flags", []))
            if isinstance(values, list)
            for flag in values
            if str(flag)
        }
        flags.update(str(issue.get("code")) for issue in matching if issue.get("code"))
        proposed = str(shot.get("proposed_fix") or "")
        if not proposed:
            proposed = next(
                (str(issue.get("proposed_fix") or issue.get("message") or "") for issue in matching),
                "",
            )
        rows.append({
            "id": shot_id,
            "vo_thesis": str(
                shot.get("vo_thesis")
                or shot.get("thesis")
                or shot.get("vo_text")
                or shot.get("purpose")
                or ""
            ),
            "shot": {
                "src": src,
                "provenance": str(asset.get("provenance") or shot.get("provenance") or "unknown"),
                "source_role": str(asset.get("source_role") or shot.get("source_role") or "other"),
            },
            "duration_seconds": round(_duration(shot), 3),
            "quality_flags": sorted(flags),
            "proposed_fix": proposed,
            "approved": shot.get("approved") is True,
        })

    approval_valid, approval_errors, approval = _approval_status(
        base, manifest_path, catalog_path, manifest, catalog
    )
    approved_flags = bool(rows) and all(row["approved"] for row in rows)
    checkpoint_digest = _checkpoint_digest(
        base, manifest_path, catalog_path, preflight_path, manifest, catalog
    )
    return {
        "wall_time": _wall_time(preflight),
        "blockers": blockers,
        "notices": notices,
        "missing_inputs": missing,
        "rows": rows,
        "approved_all": approved_flags and approval_valid,
        "can_approve_all": bool(rows) and not blockers,
        "can_resume": approved_flags and approval_valid and not blockers,
        "approval_valid": approval_valid,
        "approval_errors": approval_errors,
        "approval": approval,
        "open_requests": open_requests,
        "checkpoint_digest": checkpoint_digest,
    }


def _audit(root: Path, event: dict[str, Any]) -> None:
    path = root / "data" / "review" / "autopilot_checkpoint_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def approve_all(
    root: str | Path,
    *,
    approved_by: str,
    expected_checkpoint_digest: str,
) -> dict[str, Any]:
    """Approve every existing shot without changing any other manifest field."""
    base = Path(root).resolve()
    actor = approved_by.strip()
    if not actor:
        raise ValueError("approved_by must be non-empty")
    with _LOCK, _checkpoint_transaction_lock(base):
        snapshot = load_checkpoint(base)
        if (
            not expected_checkpoint_digest
            or snapshot["checkpoint_digest"] != expected_checkpoint_digest.casefold()
        ):
            raise ValueError(
                "checkpoint changed after it was displayed; reload before approval"
            )
        if snapshot["blockers"]:
            raise ValueError("checkpoint has blockers; resolve them before approval")
        path = base / "data" / "plan" / "shot_manifest.json"
        manifest = _read_json(path, None)
        shots = _shots(manifest)
        if manifest is None or not shots:
            raise ValueError("shot manifest has no shots to approve")
        catalog_path = base / "data" / "assets" / "catalog.json"
        preflight_path = base / "data" / "review" / "preflight.json"
        observed_hashes = {
            path: _sha256(path)
            for path in (path, catalog_path, preflight_path)
        }
        catalog = _read_json(catalog_path, {})
        source_hashes, source_errors = _source_hashes(base, manifest, catalog)
        if source_errors:
            raise ValueError("; ".join(source_errors))
        preflight = _read_json(preflight_path, {})
        editorial_hashes, editorial_errors = _editorial_hashes(base, preflight)
        if editorial_errors:
            raise ValueError("; ".join(editorial_errors))
        if _checkpoint_digest(
            base, path, catalog_path, preflight_path, manifest, catalog
        ) != expected_checkpoint_digest.casefold():
            raise ValueError(
                "checkpoint changed during approval; reload before approval"
            )
        changed = 0
        for shot in shots:
            if shot.get("approved") is not True:
                shot["approved"] = True
                changed += 1
        if any(_sha256(item) != digest for item, digest in observed_hashes.items()):
            raise ValueError(
                "checkpoint inputs changed during approval; reload before approval"
            )
        _atomic_json(path, manifest)
        approved_at = _now()
        approval = {
            "version": 1,
            "approved_at": approved_at,
            "approved_by": actor,
            "manifest_sha256": _sha256(path),
            "catalog_sha256": _sha256(catalog_path),
            "preflight_sha256": _sha256(preflight_path),
            "source_sha256": source_hashes,
            "editorial_sha256": editorial_hashes,
        }
        _atomic_json(base / _APPROVAL, approval)
        event = {
            "timestamp": approved_at,
            "action": "approve_all",
            "approved_by": actor,
            "approved_count": len(shots),
            "changed_count": changed,
        }
        _audit(base, event)
        return {**event, "checkpoint": load_checkpoint(base)}


def require_current_approval(root: str | Path) -> dict[str, Any]:
    """Return a resumable checkpoint or reject stale/missing author approval."""
    snapshot = load_checkpoint(root)
    if snapshot["can_resume"]:
        return snapshot
    reasons = [
        str(item.get("message") or item.get("code") or "checkpoint blocker")
        for item in snapshot["blockers"]
        if isinstance(item, dict)
    ]
    reasons.extend(str(item) for item in snapshot["approval_errors"])
    if not all(row.get("approved") is True for row in snapshot["rows"]):
        reasons.append("not every storyboard row is approved")
    raise ValueError("; ".join(dict.fromkeys(reasons)) or "author approval is not current")


def request_change(
    root: str | Path,
    *,
    action: str,
    shot_id: str,
    reason: str,
    requested_by: str,
) -> dict[str, Any]:
    """Persist a dangerous content change as a structured request only."""
    base = Path(root).resolve()
    if action not in _ACTIONS:
        raise ValueError(f"unsupported checkpoint action: {action}")
    sid = shot_id.strip()
    why = reason.strip()
    actor = requested_by.strip()
    if not sid or not why or not actor:
        raise ValueError("shot_id, reason and requested_by must be non-empty")
    with _LOCK:
        known = {row["id"] for row in load_checkpoint(base)["rows"]}
        if sid not in known:
            raise ValueError(f"unknown shot id: {sid}")
        path = base / _REQUESTS
        payload = _read_json(path, {"version": 1, "requests": []})
        if not isinstance(payload, dict) or not isinstance(payload.get("requests"), list):
            payload = {"version": 1, "requests": []}
        request = {
            "id": uuid.uuid4().hex,
            "timestamp": _now(),
            "action": action,
            "shot_id": sid,
            "reason": why,
            "requested_by": actor,
            "status": "requested",
        }
        payload["requests"].append(request)
        _atomic_json(path, payload)
        _audit(base, request)
        return {"status": "requested", "request": request}
