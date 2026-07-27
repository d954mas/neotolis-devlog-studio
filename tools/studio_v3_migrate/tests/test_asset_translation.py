from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dlstudio.assets.api import Approval, License, MediaFacts, Provenance
from dlstudio.foundation.api import CasConflict
from dlstudio.persistence import ProductionRepository
from dlstudio.persistence.assets import AssetRepository
from tools.studio_v3_migrate.asset_translation import (
    AssetTranslationError,
    apply_asset_plan,
    load_asset_plan,
    translate_asset_schemas,
    verify_asset_plan,
)
from tools.studio_v3_migrate.cli import _parser, main


def _repositories(production: Path) -> tuple[ProductionRepository, AssetRepository]:
    studio = production / "data" / ".studio"
    repository = ProductionRepository(
        object_root=studio / "objects",
        state_root=studio / "state",
        staging_root=studio / "staging",
        lock_root=studio / "locks",
        production_id=production.name,
    )
    return repository, AssetRepository(repository)


def _write_translatable_registry(
    production: Path,
    asset_ids: tuple[str, ...] = ("clip.main",),
) -> None:
    production.mkdir(parents=True, exist_ok=True)
    (production / "production.toml").write_text(
        'id = "production"\n', encoding="utf-8"
    )
    proof_dir = production / "data" / "assets" / "proof"
    proof_dir.mkdir(parents=True)
    assets = []
    for index, asset_id in enumerate(asset_ids):
        artifact_path = f"data/clip-{index}.bin"
        artifact = production / artifact_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"clip-{index}".encode())
        artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
        provenance = {
            "schema": "devlog.video_provenance",
            "version": 1,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha,
        }
        provenance_path = proof_dir / f"provenance-{index}.json"
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        license_proof = {
            "schema": "dlstudio.license_evidence",
            "version": 1,
            "license_id": "owned",
            "attribution_required": False,
            "attribution": None,
            "redistribution_allowed": True,
        }
        license_path = proof_dir / f"license-{index}.json"
        license_path.write_text(json.dumps(license_proof), encoding="utf-8")
        assets.append(
            {
                "asset_id": asset_id,
                "artifact_path": artifact_path,
                "artifact_sha256": artifact_sha,
                "status": "pending",
                "capture_method": "file",
                "width": 1,
                "height": 1,
                "duration": None,
                "provenance_path": provenance_path.relative_to(
                    production
                ).as_posix(),
                "provenance_sha256": hashlib.sha256(
                    provenance_path.read_bytes()
                ).hexdigest(),
                "license": {
                    "license_id": "owned",
                    "attribution_required": False,
                    "attribution": None,
                    "redistribution_allowed": True,
                    "evidence_path": license_path.relative_to(
                        production
                    ).as_posix(),
                    "evidence_sha256": hashlib.sha256(
                        license_path.read_bytes()
                    ).hexdigest(),
                },
            }
        )
    registry = production / "data" / "assets" / "registry.json"
    registry.write_text(
        json.dumps({"version": 1, "assets": assets}),
        encoding="utf-8",
    )


def _planned_media(plan: dict[str, object]) -> MediaFacts:
    records = plan["records"]
    assert isinstance(records, list)
    target = records[0]["target"]
    return MediaFacts.from_payload(target["media"])


def _translate(
    production: Path,
    *,
    production_id: str | None = None,
) -> dict[str, object]:
    media = MediaFacts(
        kind="image",
        format_name="bin",
        width=1,
        height=1,
    )
    return translate_asset_schemas(
        production,
        production_id=production_id,
        inspect_media=lambda _path: media,
    )


def test_legacy_asset_translation_is_fail_closed_and_deterministic(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "footage" / "clip.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    registry = production / "data" / "assets" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "asset_id": "capture:main",
                        "artifact_path": "data/footage/clip.mp4",
                        "artifact_sha256": hashlib.sha256(b"clip").hexdigest(),
                        "status": "approved",
                        "capture_method": "realtime_window",
                        "state_id": "state",
                        "build_id": "build",
                        "width": 1080,
                        "height": 1920,
                        "duration": 5.0,
                        "fps": 30.0,
                        "head_handle_seconds": 0,
                        "tail_handle_seconds": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first = _translate(production)
    second = _translate(production)
    assert first == second
    record = first["records"][0]
    assert record["asset_id"] == "capture-main"
    assert record["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
    assert "capture_proof_chain_incomplete" in record["blockers"]
    assert "gameplay_handles_below_contract" in record["blockers"]
    assert "license_evidence_incomplete" in record["blockers"]


def test_every_canonical_id_collision_member_is_blocked(tmp_path: Path) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "clip.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    sha = hashlib.sha256(b"clip").hexdigest()
    registry = production / "data" / "assets" / "registry.json"
    registry.parent.mkdir(parents=True)
    base = {
        "artifact_path": "data/clip.bin",
        "artifact_sha256": sha,
        "status": "pending",
        "capture_method": "file",
        "width": 1,
        "duration": None,
        "license": "owned",
    }
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {**base, "asset_id": "same:id"},
                    {**base, "asset_id": "same id"},
                ],
            }
        ),
        encoding="utf-8",
    )
    records = _translate(production)["records"]
    assert len(records) == 2
    assert all(
        record["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
        and "canonical_asset_id_collision" in record["blockers"]
        for record in records
    )


def test_known_hash_bound_file_provenance_and_license_can_translate(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "clip.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    artifact_sha = hashlib.sha256(b"clip").hexdigest()
    proof_dir = production / "data" / "assets" / "proof"
    proof_dir.mkdir(parents=True)

    provenance = {
        "schema": "devlog.video_provenance",
        "version": 1,
        "artifact_path": "data/clip.bin",
        "artifact_sha256": artifact_sha,
    }
    provenance_path = proof_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    license_proof = {
        "schema": "dlstudio.license_evidence",
        "version": 1,
        "license_id": "owned",
        "attribution_required": False,
        "attribution": None,
        "redistribution_allowed": True,
    }
    license_path = proof_dir / "license.json"
    license_path.write_text(json.dumps(license_proof), encoding="utf-8")
    registry = production / "data" / "assets" / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "asset_id": "clip.main",
                        "artifact_path": "data/clip.bin",
                        "artifact_sha256": artifact_sha,
                        "status": "pending",
                        "capture_method": "file",
                        "width": 1,
                        "height": 1,
                        "duration": None,
                        "provenance_path": "data/assets/proof/provenance.json",
                        "provenance_sha256": hashlib.sha256(
                            provenance_path.read_bytes()
                        ).hexdigest(),
                        "license": {
                            "license_id": "owned",
                            "attribution_required": False,
                            "attribution": None,
                            "redistribution_allowed": True,
                            "evidence_path": "data/assets/proof/license.json",
                            "evidence_sha256": hashlib.sha256(
                                license_path.read_bytes()
                            ).hexdigest(),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    record = _translate(production)["records"][0]
    assert record["disposition"] == "TRANSLATE"
    assert record["blockers"] == []
    assert record["target"]["provenance"]["supporting_evidence"]
    assert record["target"]["approval"]["evidence_refs"] == []
    assert record["target"]["license"]["evidence_ref"]
    assert record["target"]["license"]["redistribution_allowed"] is True


@pytest.mark.parametrize("mutation", ["registry_missing", "evidence_mismatch"])
def test_redistribution_rights_must_be_explicit_and_evidence_bound(
    tmp_path: Path,
    mutation: str,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    registry_path = production / "data" / "assets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    license_value = registry["assets"][0]["license"]
    if mutation == "registry_missing":
        license_value.pop("redistribution_allowed")
    else:
        evidence_path = production / license_value["evidence_path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["redistribution_allowed"] = False
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        license_value["evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    record = _translate(production)["records"][0]
    assert record["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
    assert "license_evidence_incomplete" in record["blockers"]
    assert "target" not in record


def test_plan_is_hash_bound_and_load_rejects_tampering(tmp_path: Path) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    first = _translate(production)
    second = _translate(production)
    assert first == second
    assert len(first["plan_id"]) == 64

    plan_path = tmp_path / "asset-plan.json"
    plan_path.write_text(json.dumps(first), encoding="utf-8")
    assert load_asset_plan(plan_path) == first

    tampered = json.loads(plan_path.read_text(encoding="utf-8"))
    tampered["records"][0]["target"]["license"]["license_id"] = "changed"
    plan_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(AssetTranslationError, match="plan_id"):
        load_asset_plan(plan_path)


def test_apply_verify_and_second_apply_are_canonically_idempotent(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan = _translate(production)
    repository, assets = _repositories(production)
    media = _planned_media(plan)

    first = apply_asset_plan(
        production,
        plan,
        repository=assets,
        inspect_media=lambda _path: media,
    )
    assert first["created"] == 1
    assert first["already_present"] == 0
    head = repository.read_head()
    assert head is not None
    assert assets.current("clip.main").ref.as_payload() == (
        plan["records"][0]["target"]["revision"]
    )
    verified = verify_asset_plan(production, plan, repository=assets)
    assert verified["verified"] == 1

    repeated = apply_asset_plan(
        production,
        plan,
        repository=assets,
        inspect_media=lambda _path: media,
    )
    assert repeated["created"] == 0
    assert repeated["already_present"] == 1
    assert repository.read_head() == head


def test_apply_rejects_repository_for_another_production_before_write(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan = _translate(production)
    foreign = tmp_path / "foreign-canonical-store"
    studio = foreign / "data" / ".studio"
    repository = ProductionRepository(
        object_root=studio / "objects",
        state_root=studio / "state",
        staging_root=studio / "staging",
        lock_root=studio / "locks",
        production_id="another-production",
    )
    assets = AssetRepository(repository)

    with pytest.raises(AssetTranslationError, match="repository production id"):
        apply_asset_plan(
            production,
            plan,
            repository=assets,
            inspect_media=lambda _path: _planned_media(plan),
        )
    assert repository.read_head() is None
    assert not repository.object_root.exists()


@pytest.mark.parametrize("mutated", ["source", "evidence"])
def test_apply_preflight_rejects_hash_mutation_before_canonical_write(
    tmp_path: Path,
    mutated: str,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan = _translate(production)
    repository, assets = _repositories(production)
    record = plan["records"][0]
    descriptor = (
        record["source"] if mutated == "source" else record["evidence"][0]
    )
    (production / descriptor["path"]).write_bytes(b"mutated")

    with pytest.raises(AssetTranslationError, match="hash mismatch"):
        apply_asset_plan(
            production,
            plan,
            repository=assets,
            inspect_media=lambda _path: _planned_media(plan),
        )
    assert repository.read_head() is None
    assert not repository.object_root.exists()


def test_apply_preflight_rejects_existing_asset_conflict_before_new_assets(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production, ("a.conflict", "z.new"))
    plan = _translate(production)
    repository, assets = _repositories(production)
    media = _planned_media(plan)
    source = production / plan["records"][0]["source"]["path"]
    conflict = assets.ingest(
        source,
        asset_id="a.conflict",
        media=media,
        provenance=Provenance("provided", "file"),
        approval=Approval("pending"),
        license=License("different", False),
        expected_revision=0,
        inspect_media=lambda _path: media,
    )
    head = repository.read_head()

    with pytest.raises(AssetTranslationError, match="conflict"):
        apply_asset_plan(
            production,
            plan,
            repository=assets,
            inspect_media=lambda _path: media,
        )
    assert repository.read_head() == head
    assert assets.current("a.conflict").ref == conflict.revision.ref
    assert "z.new" not in assets.read_index().entries


def test_retry_resumes_from_canonical_asset_index_without_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production, ("a.first", "b.second"))
    plan = _translate(production)
    repository, assets = _repositories(production)
    media = _planned_media(plan)
    original_ingest = AssetRepository.ingest
    calls = 0

    def fail_second(self: AssetRepository, *args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected interruption")
        return original_ingest(self, *args, **kwargs)

    monkeypatch.setattr(AssetRepository, "ingest", fail_second)
    with pytest.raises(RuntimeError, match="injected interruption"):
        apply_asset_plan(
            production,
            plan,
            repository=assets,
            inspect_media=lambda _path: media,
        )
    assert set(assets.read_index().entries) == {"a.first"}
    assert not (production / "data" / ".studio" / "migration-journal.json").exists()

    monkeypatch.setattr(AssetRepository, "ingest", original_ingest)
    resumed = apply_asset_plan(
        production,
        plan,
        repository=assets,
        inspect_media=lambda _path: media,
    )
    assert resumed["created"] == 1
    assert resumed["already_present"] == 1
    assert set(assets.read_index().entries) == {"a.first", "b.second"}


def test_cli_exposes_one_migrate_assets_mode_surface() -> None:
    parsed = _parser().parse_args(
        [
            "migrate-assets",
            "--production",
            "production",
            "--plan",
            "plan.json",
            "--mode",
            "verify",
        ]
    )
    assert parsed.command == "migrate-assets"
    assert parsed.mode == "verify"
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "translate-assets",
                "--production",
                "production",
                "--report",
                "report.json",
            ]
        )


def test_cli_reports_cas_conflict_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_translate(production)), encoding="utf-8")

    def conflict(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise CasConflict("concurrent canonical writer")

    monkeypatch.setattr(
        "tools.studio_v3_migrate.cli.apply_asset_plan",
        conflict,
    )
    result = main(
        [
            "migrate-assets",
            "--production",
            str(production),
            "--plan",
            str(plan_path),
            "--mode",
            "apply",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "BLOCKED: concurrent canonical writer" in captured.err


def test_manifest_mutation_or_absent_manifest_addition_invalidates_plan(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan = _translate(production)
    registry = production / "data" / "assets" / "registry.json"
    registry.write_text(
        registry.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(AssetTranslationError, match="legacy registry.*hash"):
        apply_asset_plan(production, plan)

    plan = _translate(production)
    catalog = production / "data" / "assets" / "catalog.json"
    catalog.write_text('{"version":1,"assets":[]}', encoding="utf-8")
    with pytest.raises(AssetTranslationError, match="catalog.*appeared"):
        apply_asset_plan(production, plan)


def test_identical_legacy_ids_are_duplicate_blocker_before_head_write(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production, ("same.id", "same.id"))
    plan = _translate(production)
    assert all(
        "canonical_asset_id_collision" in record["blockers"]
        for record in plan["records"]
    )
    repository, assets = _repositories(production)
    with pytest.raises(AssetTranslationError, match="duplicate canonical"):
        apply_asset_plan(production, plan, repository=assets)
    assert repository.read_head() is None


@pytest.mark.parametrize("mutation", ["delete", "replace"])
def test_blocked_artifact_binding_is_rechecked_and_never_fully_verified(
    tmp_path: Path,
    mutation: str,
) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "blocked.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"blocked")
    catalog = production / "data" / "assets" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "path": "data/blocked.bin",
                        "sha256": hashlib.sha256(b"blocked").hexdigest(),
                        "provenance": "unknown",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = _translate(production, production_id="production")
    assert plan["records"][0]["source"]["sha256"] == hashlib.sha256(
        b"blocked"
    ).hexdigest()
    blocked = apply_asset_plan(production, plan)
    assert blocked["status"] == "blocked"
    assert not blocked["fully_verified"]
    if mutation == "delete":
        artifact.unlink()
    else:
        artifact.write_bytes(b"changed")
    with pytest.raises(AssetTranslationError, match="legacy artifact"):
        verify_asset_plan(production, plan)


def test_plan_is_portable_to_clone_with_same_production_identity(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original-location"
    _write_translatable_registry(original)
    plan = _translate(original)
    assert "production_root" not in plan
    clone = tmp_path / "restored-clone"
    shutil.copytree(original, clone)
    media = _planned_media(plan)

    result = apply_asset_plan(
        clone,
        plan,
        inspect_media=lambda _path: media,
    )
    assert result["fully_verified"]
    assert verify_asset_plan(clone, plan)["status"] == "verified"


def test_manifestless_dry_run_requires_explicit_id_before_execution(
    tmp_path: Path,
) -> None:
    production = tmp_path / "original-location"
    _write_translatable_registry(production)
    (production / "production.toml").unlink()

    diagnostic_plan = _translate(production)
    assert diagnostic_plan["production_id"] is None
    with pytest.raises(AssetTranslationError, match="stable explicit production id"):
        apply_asset_plan(
            production,
            diagnostic_plan,
            inspect_media=lambda _path: _planned_media(diagnostic_plan),
        )

    executable_plan = _translate(
        production,
        production_id="stable-production",
    )
    clone = tmp_path / "restored-clone"
    shutil.copytree(production, clone)
    result = apply_asset_plan(
        clone,
        executable_plan,
        inspect_media=lambda _path: _planned_media(executable_plan),
    )
    assert result["fully_verified"]
    assert verify_asset_plan(clone, executable_plan)["status"] == "verified"


def test_conflicting_race_cannot_overwrite_canonical_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = tmp_path / "production"
    _write_translatable_registry(production)
    plan = _translate(production)
    repository, assets = _repositories(production)
    media = _planned_media(plan)
    original_ingest = AssetRepository.ingest
    raced = False

    def race_once(self: AssetRepository, source: Path, **kwargs: object):
        nonlocal raced
        if not raced:
            raced = True
            original_ingest(
                self,
                source,
                asset_id="clip.main",
                media=media,
                provenance=Provenance("provided", "file"),
                approval=Approval("pending"),
                license=License("racing-writer", False),
                expected_revision=0,
                inspect_media=lambda _path: media,
            )
        return original_ingest(self, source, **kwargs)

    monkeypatch.setattr(AssetRepository, "ingest", race_once)
    with pytest.raises(CasConflict):
        apply_asset_plan(
            production,
            plan,
            repository=assets,
            inspect_media=lambda _path: media,
        )
    assert assets.current("clip.main").license.license_id == "racing-writer"
