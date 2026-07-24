"""Deterministic CLI boundaries for the agent-driven production flow.

The commands in this module collect and validate facts.  They deliberately do
not contain an AI runtime and storyboard delegates rendering to the existing
``preview`` path, so it cannot silently rewrite an edit's meaning.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CATALOG = Path("data/assets/catalog.json")
_SHOT_MANIFEST = Path("data/plan/shot_manifest.json")
_PREFLIGHT = Path("data/review/preflight.json")
_STORYBOARD_BOUNDARIES = Path("data/review/storyboard_boundaries.json")
_RUN_STATE = Path("data/review/autopilot_run.json")
_RUN_ID_ENV = "DLSTUDIO_RUN_ID"


def _load_target(edit_ref: str) -> tuple[Any, Path, str]:
    """Load an edit and retain a cwd-independent reference for reloading.

    ``load_edit`` changes cwd to the project/production root.  A relative
    filesystem reference would otherwise stop resolving when storyboard hands
    it to the existing preview command for a second load.
    """
    from dlstudio.cli import (
        _find_workspace_root,
        _load_v2_config,
        _resolve_edit_arg,
        load_edit,
    )
    from dlstudio.production import is_filesystem_edit_ref

    workspace_root = _find_workspace_root()
    resolved = _resolve_edit_arg(edit_ref, _load_v2_config(workspace_root))
    canonical = resolved
    value = Path(resolved)
    product_ref = ":" in resolved and not value.drive
    if is_filesystem_edit_ref(resolved) and not product_ref:
        canonical = str(value.resolve())
    edit, production_root = load_edit(canonical)
    return edit, production_root.resolve(), canonical


def _read_shots(path: Path) -> list[dict[str, Any]]:
    from dlstudio.cli import CliError

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(f"shot manifest is required: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON in shot manifest {path}: {exc}") from exc

    shots = payload.get("shots") if isinstance(payload, dict) else payload
    if not isinstance(shots, list) or not all(isinstance(item, dict) for item in shots):
        raise CliError(
            f"shot manifest {path} must be a JSON array or an object with a shots array"
        )
    return shots


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
    return f"run_{stamp}_{secrets.token_hex(3)}"


def _load_run_state(path: Path) -> dict[str, Any]:
    from dlstudio.cli import CliError

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError(f"autopilot run state is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid autopilot run state {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("run_id"), str):
        raise CliError(f"invalid autopilot run state: {path}")
    return payload


def _save_run_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _write_json(path, state)


def _run_stage(
    state: dict[str, Any],
    state_path: Path,
    name: str,
    action,
    stage_args: argparse.Namespace,
) -> int:
    started = time.perf_counter_ns()
    try:
        rc = int(action(stage_args) or 0)
    except Exception as exc:
        state["stages"].append({
            "name": name,
            "status": "failed",
            "wall_ms": max(0, (time.perf_counter_ns() - started) // 1_000_000),
            "error": str(exc),
        })
        state["status"] = "blocked"
        state["next_action"] = f"fix {name}, then resume the same run"
        _save_run_state(state_path, state)
        raise
    state["stages"].append({
        "name": name,
        "status": "passed" if rc == 0 else "failed",
        "wall_ms": max(0, (time.perf_counter_ns() - started) // 1_000_000),
    })
    if rc:
        state["status"] = "blocked"
        state["next_action"] = f"fix {name}, then resume the same run"
    _save_run_state(state_path, state)
    return rc


def _creator_profile_path(root: Path) -> Path | None:
    """Find the product-level compact creator profile for a production."""
    for candidate_root in (root, *root.parents):
        if (candidate_root / "product.toml").is_file():
            candidate = candidate_root / "shared" / "preferences.toml"
            return candidate if candidate.is_file() else None
    return None


def _script_vo_issues(edit: Any, root: Path) -> tuple[list[Any], dict[str, str | None]]:
    """Run deterministic script lineage, transcript and first-3s VO gates."""
    from dlstudio.ir import CheckIssue
    from dlstudio.services.script_preflight import (
        canonical_script_text,
        check_wav_first_3s,
        lint_script,
        load_creator_profile,
        scan_transcript_proper_names,
        verify_script_approval,
    )

    issues: list[CheckIssue] = []
    order = getattr(edit, "order", None)
    beats = getattr(edit, "beats", None)
    approval_path = root / "data" / "plan" / "script_approval.json"
    profile_path = _creator_profile_path(root)
    inputs = {
        "script_approval": (
            Path("data/plan/script_approval.json").as_posix()
            if approval_path.is_file()
            else None
        ),
        "creator_profile": str(profile_path.relative_to(root).as_posix())
        if profile_path is not None and profile_path.is_relative_to(root)
        else (str(profile_path) if profile_path is not None else None),
    }
    if not isinstance(order, list) or not isinstance(beats, dict):
        return issues, inputs

    scripted = [beat_id for beat_id in order if (getattr(beats.get(beat_id), "vo", None) or "").strip()]
    if not scripted:
        return issues, inputs

    script = canonical_script_text(edit)
    if not approval_path.is_file():
        issues.append(CheckIssue(
            severity="error",
            code="VQ-SCRIPT-APPROVAL",
            message="recorded script has no hash-bound approval snapshot",
            where="data/plan/script_approval.json",
        ))
    else:
        try:
            verified = verify_script_approval(
                script, approval_path, script_id=str(getattr(edit, "name", ""))
            )
            if verified.issue is not None:
                issues.append(CheckIssue(
                    severity="error",
                    code=verified.issue.code,
                    message=verified.issue.message,
                    where="data/plan/script_approval.json",
                ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(CheckIssue(
                severity="error",
                code="VQ-SCRIPT-APPROVAL",
                message=f"invalid script approval snapshot: {exc}",
                where="data/plan/script_approval.json",
            ))

    profile = None
    if profile_path is not None:
        try:
            profile = load_creator_profile(profile_path)
        except (OSError, ValueError) as exc:
            issues.append(CheckIssue(
                severity="error", code="VQ-SCRIPT-PROFILE",
                message=f"invalid creator profile: {exc}", where=str(profile_path),
            ))

    for beat_id in scripted:
        beat = beats[beat_id]
        vo = beat.vo or ""
        if profile is not None:
            lint = lint_script(vo, profile)
            for item in lint.issues:
                issues.append(CheckIssue(
                    severity="warn" if item.severity == "warning" else "error",
                    code=item.code,
                    message=item.message,
                    where=beat_id,
                ))

        audio_path = (root / beat.audio).resolve()
        if audio_path.is_file() and audio_path.suffix.casefold() == ".wav":
            try:
                audio = check_wav_first_3s(audio_path)
                for item in audio.issues:
                    issues.append(CheckIssue(
                        severity="warn" if item.severity == "warning" else "error",
                        code=item.code,
                        message=item.message,
                        where=beat_id,
                    ))
            except (OSError, ValueError) as exc:
                issues.append(CheckIssue(
                    severity="error", code="VQ-AUDIO-START",
                    message=f"cannot inspect VO start: {exc}", where=beat_id,
                ))

        if profile is not None:
            expected_names = tuple(
                name for name in profile.proper_names if name.casefold() in vo.casefold()
            )
            words_path = (root / beat.words).resolve()
            if expected_names and words_path.is_file():
                try:
                    scan = scan_transcript_proper_names(words_path, expected_names)
                    for item in scan.issues:
                        issues.append(CheckIssue(
                            severity="error", code=item.code,
                            message=item.message, where=beat_id,
                        ))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    issues.append(CheckIssue(
                        severity="error", code="VQ-TRANSCRIPT-PROPER",
                        message=f"cannot scan transcript tokens: {exc}", where=beat_id,
                    ))
    return issues, inputs


def cmd_inventory(args: argparse.Namespace) -> int:
    from dlstudio.services.autopilot import build_asset_catalog
    from dlstudio.cli.telemetry import record_automatic_stage

    started = time.perf_counter_ns()
    _edit, root, _canonical = _load_target(args.edit)
    out = root / _CATALOG
    catalog = build_asset_catalog(root, out_path=out)
    record_automatic_stage(
        root, stage="inventory", agent_role="planner", started_ns=started,
        artifact_paths=(out,),
    )
    print(f"[dl2] inventory: {len(catalog.assets)} assets -> {out}")
    return 0


def cmd_asset_approve(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.services.asset_registry import AssetRegistryError, approve_asset

    _edit, root, _canonical = _load_target(args.edit)
    try:
        registry = approve_asset(
            root,
            args.asset_id,
            expected_sha256=args.sha,
            approved_by=args.approved_by,
        )
    except AssetRegistryError as exc:
        raise CliError(str(exc)) from exc
    asset = next(item for item in registry.assets if item.asset_id == args.asset_id)
    print(
        f"[dl2] asset approved: {asset.asset_id} "
        f"revision={asset.revision} sha256={asset.artifact_sha256}"
    )
    return 0


def cmd_capture_batch(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.services.capture_batch import (
        CaptureBatchError,
        ingest_capture_results,
        prepare_capture_batch,
    )
    from dlstudio.cli.telemetry import record_automatic_stage

    started = time.perf_counter_ns()
    _edit, root, _canonical = _load_target(args.edit)
    try:
        if args.prepare:
            requests = Path(args.requests) if args.requests else root / "data" / "plan" / "capture_requests.json"
            out = Path(args.out) if args.out else root / "data" / "plan" / "capture_batch.json"
            batch = prepare_capture_batch(root, requests, out_path=out)
            print(
                f"[dl2] capture-batch: {len(batch.requests)} requests -> {out}"
            )
            print("[dl2] hand this one manifest to the external capture agent")
            record_automatic_stage(
                root, stage="capture_request", agent_role="planner",
                started_ns=started, artifact_paths=(out,),
            )
            return 0
        receipt = ingest_capture_results(root, args.ingest, batch_path=args.batch)
    except CaptureBatchError as exc:
        raise CliError(str(exc)) from exc
    print(
        f"[dl2] capture-ingest: {len(receipt.ingested)} ingested, "
        f"{len(receipt.failed)} failed -> {receipt.catalog_path}"
    )
    print(f"[dl2] receipt: {receipt.receipt_path}")
    record_automatic_stage(
        root, stage="capture_ingest", agent_role="capture_agent",
        started_ns=started,
        artifact_paths=(receipt.catalog_path, receipt.receipt_path),
    )
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from dlstudio import check as dl_check
    from dlstudio import compile as dl_compile
    from dlstudio.cli import CliError
    from dlstudio.ir import CheckIssue, CheckReport
    from dlstudio.services.autopilot import AssetCatalog, validate_shot_manifest
    from dlstudio.services.editorial_preflight import run_editorial_preflight
    from dlstudio.services.render_preflight import analyze_rendered_video
    from dlstudio.services.visual_preflight import run_visual_preflight
    from dlstudio.cli.telemetry import record_automatic_stage

    started = time.perf_counter_ns()
    edit, root, _canonical = _load_target(args.edit)
    timeline = dl_compile.build_timeline(edit)
    mechanical = dl_check.run_checks(timeline)
    issues = list(mechanical.issues)
    script_issues, script_inputs = _script_vo_issues(edit, root)
    issues.extend(script_issues)

    manifest_path = root / _SHOT_MANIFEST
    catalog_path = root / _CATALOG
    manifest_input: str | None = (
        _SHOT_MANIFEST.as_posix() if manifest_path.is_file() else None
    )
    catalog_input: str | None = (
        _CATALOG.as_posix() if catalog_path.is_file() else None
    )
    shots: list[dict[str, Any]] | None = None
    catalog: AssetCatalog | None = None

    if manifest_path.is_file():
        shots = _read_shots(manifest_path)
        if not catalog_path.is_file():
            issues.append(
                CheckIssue(
                    severity="error",
                    code="VQ-SOURCE",
                    message=(
                        "shot manifest exists but asset catalog is missing; "
                        "run dl2 inventory"
                    ),
                    where=_CATALOG.as_posix(),
                )
            )
        else:
            try:
                catalog = AssetCatalog.model_validate_json(
                    catalog_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError, ValueError) as exc:
                raise CliError(f"invalid asset catalog {catalog_path}: {exc}") from exc
            width, height = timeline.design.resolution
            orientation = "landscape" if width >= height else "vertical"
            shot_report = validate_shot_manifest(
                shots,
                catalog,
                orientation=orientation,
                final=args.final,
            )
            issues.extend(shot_report.issues)

    visual_report = run_visual_preflight(
        edit,
        timeline,
        root,
        shots=shots,
        catalog=catalog,
        final=args.final,
    )
    issues.extend(visual_report.issues)
    width, height = timeline.design.resolution
    editorial_report = run_editorial_preflight(
        root,
        require_story_contract=height > width and manifest_path.is_file(),
    )
    issues.extend(editorial_report.issues)

    artifact_value = args.artifact or getattr(edit, "output", None)
    artifact_path: Path | None = None
    if artifact_value:
        candidate = Path(artifact_value)
        artifact_path = candidate if candidate.is_absolute() else root / candidate
        artifact_path = artifact_path.resolve()
        if artifact_path.is_file():
            render_report = analyze_rendered_video(
                artifact_path,
                shots=shots,
                final=args.final,
            )
            issues.extend(render_report.issues)
        elif args.artifact or args.final:
            issues.append(CheckIssue(
                severity="error" if args.final else "warn",
                code="VQ-RENDER-ARTIFACT",
                message="render artifact does not exist",
                where=str(artifact_path),
            ))

    report = CheckReport(issues=issues)
    warnings = [issue for issue in report.issues if issue.severity == "warn"]
    payload = {
        "version": 1,
        "ok": report.ok,
        "errors": len(report.errors),
        "warnings": len(warnings),
        "issues": [issue.model_dump(mode="json") for issue in report.issues],
        "autofix_suggestions": [],
        "inputs": {
            "shot_manifest": manifest_input,
            "asset_catalog": catalog_input,
            "render_artifact": str(artifact_path) if artifact_path is not None else None,
            **script_inputs,
        },
    }
    out = root / _PREFLIGHT
    _write_json(out, payload)
    for issue in report.issues:
        print(f"[{issue.severity.upper()}] {issue.code} {issue.where}: {issue.message}")
    print(
        f"[dl2] preflight: {len(report.errors)} errors, {len(warnings)} warnings -> {out}"
    )
    record_automatic_stage(
        root, stage="preflight", agent_role="quality_gate", started_ns=started,
        artifact_paths=(out,),
    )
    return 1 if report.errors else 0


def cmd_storyboard(args: argparse.Namespace) -> int:
    from dlstudio.cli import preview
    from dlstudio.cli.telemetry import record_automatic_stage

    started = time.perf_counter_ns()
    edit, root, canonical = _load_target(args.edit)
    manifest_path = root / _SHOT_MANIFEST
    if not manifest_path.is_file():
        from dlstudio.cli import CliError

        raise CliError(f"shot manifest is required: {manifest_path}")
    shots = _read_shots(manifest_path)

    preview_args = argparse.Namespace(
        edit=canonical,
        width="540p",
        quality="draft",
        jobs=args.jobs,
        keyframes=args.keyframes,
    )
    rc = preview.cmd_preview(preview_args)
    if rc:
        return rc

    payload = {
        "version": 1,
        "preview": Path(edit.output).as_posix(),
        "contact_sheet": Path("data/review/contact_sheet.jpg").as_posix(),
        "boundaries": shots,
    }
    out = root / _STORYBOARD_BOUNDARIES
    _write_json(out, payload)
    artifacts = [out, root / "data" / "review" / "contact_sheet.jpg"]
    preview_path = (root / edit.output).resolve()
    if preview_path.is_file():
        artifacts.append(preview_path)
    record_automatic_stage(
        root, stage="storyboard", agent_role="planner", started_ns=started,
        artifact_paths=tuple(artifacts),
    )
    print(f"[dl2] storyboard: boundaries -> {out}")
    return 0


def cmd_review_pack(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.cli.telemetry import record_automatic_stage
    from dlstudio.services.review_pack import ReviewPackError, build_review_pack

    started = time.perf_counter_ns()
    edit, root, _canonical = _load_target(args.edit)
    raw = Path(args.artifact) if args.artifact else Path(edit.output)
    artifact = raw if raw.is_absolute() else root / raw
    try:
        out, sheet = build_review_pack(
            root, artifact, max_frames=args.frames, thumb_width=args.thumb_width
        )
    except ReviewPackError as exc:
        raise CliError(str(exc)) from exc
    record_automatic_stage(
        root, stage="review_pack", agent_role="quality_gate", started_ns=started,
        artifact_paths=(out, sheet),
    )
    print(f"[dl2] review-pack: {out}")
    print(f"[dl2] review-pack sheet: {sheet}")
    return 0


def cmd_autopilot_run(args: argparse.Namespace) -> int:
    """Run deterministic production stages without agent polling.

    The command stops only at the author storyboard checkpoint and at the
    exact-review boundary.  Re-running with ``--resume`` advances the same
    run id instead of rediscovering commands and rebuilding prior stages.
    """
    from dlstudio.cli import CliError, cmd_final
    from dlstudio.cli.delivery import cmd_deliver, cmd_publish_evidence

    _edit, root, canonical = _load_target(args.edit)
    state_path = root / _RUN_STATE
    if args.resume:
        state = _load_run_state(state_path)
    else:
        if state_path.is_file() and not args.restart:
            previous = _load_run_state(state_path)
            if previous.get("status") != "completed":
                raise CliError(
                    f"autopilot run {previous['run_id']} is {previous.get('status')}; "
                    "use --resume or --restart"
                )
        state = {
            "version": 1,
            "run_id": _new_run_id(),
            "production": canonical,
            "status": "running",
            "phase": "prepare",
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "human_active_ms": 0,
            "stages": [],
            "next_action": None,
        }
        _save_run_state(state_path, state)

    run_id = str(state["run_id"])
    previous_run_id = os.environ.get(_RUN_ID_ENV)
    original_cwd = Path.cwd()
    os.environ[_RUN_ID_ENV] = run_id
    try:
        status = str(state.get("status", "running"))
        if status == "completed":
            print(f"[dl2] autopilot-run {run_id}: already completed")
            return 0

        phase = str(state.get("phase", "prepare"))
        if not args.resume or (status == "blocked" and phase == "prepare"):
            state["status"] = "running"
            state["phase"] = "prepare"
            for name, action, stage_args in (
                ("inventory", cmd_inventory, argparse.Namespace(edit=canonical)),
                (
                    "preflight",
                    cmd_preflight,
                    argparse.Namespace(edit=canonical, final=False, artifact=None),
                ),
                (
                    "storyboard",
                    cmd_storyboard,
                    argparse.Namespace(
                        edit=canonical, jobs=args.jobs, keyframes=args.keyframes
                    ),
                ),
                (
                    "storyboard_review_pack",
                    cmd_review_pack,
                    argparse.Namespace(
                        edit=canonical, artifact=None, frames=args.review_frames,
                        thumb_width=320,
                    ),
                ),
            ):
                rc = _run_stage(state, state_path, name, action, stage_args)
                if rc:
                    return rc
            state["status"] = "awaiting_checkpoint"
            state["phase"] = "author_checkpoint"
            state["next_action"] = (
                f"approve the storyboard, then run: dl2 autopilot-run "
                f"{canonical} --resume"
            )
            _save_run_state(state_path, state)
            print(f"[dl2] autopilot-run {run_id}: awaiting author checkpoint")
            return 0

        if status == "awaiting_checkpoint" or (
            status == "blocked" and phase == "finalize"
        ):
            human_active_ms = max(0, int(round(args.human_minutes * 60_000)))
            state["human_active_ms"] = int(state.get("human_active_ms", 0)) + human_active_ms
            if human_active_ms:
                from dlstudio.cli.telemetry import record_human_checkpoint
                record_human_checkpoint(
                    root, run_id=run_id, human_active_ms=human_active_ms,
                    artifact_paths=(state_path,),
                )
            state["status"] = "running"
            state["phase"] = "finalize"
            for name, action, stage_args in (
                (
                    "preflight_resume",
                    cmd_preflight,
                    argparse.Namespace(edit=canonical, final=False, artifact=None),
                ),
                (
                    "final_render",
                    cmd_final,
                    argparse.Namespace(
                        edit=canonical, width=None, quality=None, gpu=False,
                        no_cache=False, stale=True, jobs=args.jobs,
                    ),
                ),
                (
                    "final_preflight",
                    cmd_preflight,
                    argparse.Namespace(edit=canonical, final=True, artifact=None),
                ),
                (
                    "final_review_pack",
                    cmd_review_pack,
                    argparse.Namespace(
                        edit=canonical, artifact=None, frames=args.review_frames,
                        thumb_width=320,
                    ),
                ),
            ):
                rc = _run_stage(state, state_path, name, action, stage_args)
                if rc:
                    return rc
            state["status"] = "awaiting_exact_review"
            state["phase"] = "exact_review"
            state["next_action"] = (
                "run one exact-hash blind review, then resume the same command"
            )
            _save_run_state(state_path, state)
            print(f"[dl2] autopilot-run {run_id}: awaiting exact review")
            return 0

        if status == "awaiting_exact_review" or (
            status == "blocked" and phase == "delivery"
        ):
            state["phase"] = "delivery"
            for name, action, stage_args in (
                (
                    "publish_evidence",
                    cmd_publish_evidence,
                    argparse.Namespace(edit=canonical, publish_json=None),
                ),
                (
                    "delivery",
                    cmd_deliver,
                    argparse.Namespace(
                        edit=canonical, video=None, metadata=None, image=None,
                        overwrite=False,
                    ),
                ),
            ):
                rc = _run_stage(state, state_path, name, action, stage_args)
                if rc:
                    return rc
            state["status"] = "completed"
            state["phase"] = "completed"
            state["next_action"] = None
            state["completed_at"] = _utc_now()
            _save_run_state(state_path, state)
            print(f"[dl2] autopilot-run {run_id}: completed")
            return 0

        raise CliError(f"unknown autopilot run status: {status!r}")
    finally:
        os.chdir(original_cwd)
        if previous_run_id is None:
            os.environ.pop(_RUN_ID_ENV, None)
        else:
            os.environ[_RUN_ID_ENV] = previous_run_id


def add_subparsers(sub: argparse._SubParsersAction) -> None:
    run = sub.add_parser(
        "autopilot-run",
        help="run the production state machine with one author checkpoint",
    )
    run.add_argument("edit", help="production path or product:id")
    run_mode = run.add_mutually_exclusive_group()
    run_mode.add_argument("--resume", action="store_true")
    run_mode.add_argument("--restart", action="store_true")
    run.add_argument("--human-minutes", type=float, default=0.0)
    run.add_argument("-j", "--jobs", type=int, default=4)
    run.add_argument("--keyframes", type=int, default=8)
    run.add_argument("--review-frames", type=int, default=16)
    run.set_defaults(func=cmd_autopilot_run)

    review_pack = sub.add_parser(
        "review-pack",
        help="build a compact exact-artifact review JSON and thumbnail sheet",
    )
    review_pack.add_argument("edit", help="production path or product:id")
    review_pack.add_argument("--artifact")
    review_pack.add_argument("--frames", type=int, default=16)
    review_pack.add_argument("--thumb-width", type=int, default=320)
    review_pack.set_defaults(func=cmd_review_pack)

    inventory = sub.add_parser(
        "inventory",
        help="build the production asset catalog",
    )
    inventory.add_argument("edit", help="dotted edit, production path, or product:id")
    inventory.set_defaults(func=cmd_inventory)

    approve = sub.add_parser(
        "asset-approve",
        help="approve one exact validated asset revision",
    )
    approve.add_argument("edit", help="dotted edit, production path, or product:id")
    approve.add_argument("asset_id", help="stable registry asset id")
    approve.add_argument("--sha", required=True, help="exact current artifact SHA-256")
    approve.add_argument("--approved-by", default="author")
    approve.set_defaults(func=cmd_asset_approve)

    capture = sub.add_parser(
        "capture-batch",
        help="prepare one external capture-agent batch or ingest its results",
    )
    capture.add_argument("edit", help="dotted edit, production path, or product:id")
    action = capture.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--prepare", action="store_true", help="normalize all capture requests"
    )
    action.add_argument(
        "--ingest", metavar="RESULTS_JSON", help="verify and catalog captured results"
    )
    capture.add_argument(
        "--requests", help="request JSON (default: data/plan/capture_requests.json)"
    )
    capture.add_argument(
        "--out", help="batch JSON (default: data/plan/capture_batch.json)"
    )
    capture.add_argument(
        "--batch", help="batch JSON used for ingest (default: data/plan/capture_batch.json)"
    )
    capture.set_defaults(func=cmd_capture_batch)

    preflight = sub.add_parser(
        "preflight",
        help="compile and combine IR checks with optional shot/source checks",
    )
    preflight.add_argument("edit", help="dotted edit, production path, or product:id")
    preflight.add_argument(
        "--final",
        action="store_true",
        help="apply final-severity gates and require the exact render artifact",
    )
    preflight.add_argument(
        "--artifact",
        help="exact rendered MP4 to inspect (default: EDIT.output when it exists)",
    )
    preflight.set_defaults(func=cmd_preflight)

    storyboard = sub.add_parser(
        "storyboard",
        help="render the existing 540p preview and write shot-boundary facts",
    )
    storyboard.add_argument("edit", help="dotted edit, production path, or product:id")
    storyboard.add_argument(
        "-j", "--jobs", type=int, default=1, help="parallel preview worker processes"
    )
    storyboard.add_argument(
        "--keyframes", type=int, default=8, help="number of preview keyframes"
    )
    storyboard.set_defaults(func=cmd_storyboard)
