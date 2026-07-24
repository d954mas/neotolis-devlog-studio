"""Production-scoped data contract for Studio's single Autopilot checkpoint.

The checkpoint is deliberately deterministic: it joins the shot ledger,
asset catalog and preflight report, and exposes only two mutations.  Package
approval can flip existing ``approved`` booleans when no blockers remain;
content-changing actions are persisted as requests and never edit the shot
or VO automatically.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_ACTIONS = {"replace_shot", "request_capture", "change_text"}


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

    return {
        "wall_time": _wall_time(preflight),
        "blockers": blockers,
        "notices": notices,
        "missing_inputs": missing,
        "rows": rows,
        "approved_all": bool(rows) and all(row["approved"] for row in rows),
        "can_approve_all": bool(rows) and not blockers,
    }


def _audit(root: Path, event: dict[str, Any]) -> None:
    path = root / "data" / "review" / "autopilot_checkpoint_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def approve_all(root: str | Path, *, approved_by: str) -> dict[str, Any]:
    """Approve every existing shot without changing any other manifest field."""
    base = Path(root).resolve()
    actor = approved_by.strip()
    if not actor:
        raise ValueError("approved_by must be non-empty")
    with _LOCK:
        snapshot = load_checkpoint(base)
        if snapshot["blockers"]:
            raise ValueError("checkpoint has blockers; resolve them before approval")
        path = base / "data" / "plan" / "shot_manifest.json"
        manifest = _read_json(path, None)
        shots = _shots(manifest)
        if manifest is None or not shots:
            raise ValueError("shot manifest has no shots to approve")
        changed = 0
        for shot in shots:
            if shot.get("approved") is not True:
                shot["approved"] = True
                changed += 1
        _atomic_json(path, manifest)
        event = {
            "timestamp": _now(),
            "action": "approve_all",
            "approved_by": actor,
            "approved_count": len(shots),
            "changed_count": changed,
        }
        _audit(base, event)
        return {**event, "checkpoint": load_checkpoint(base)}


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
        path = base / "data" / "plan" / "autopilot_requests.json"
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
