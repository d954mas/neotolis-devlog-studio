from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.studio_v3_verify.gates import (
    GateStatus,
    check_architecture,
    check_banned_surfaces,
    check_generated_client,
    check_performance_contract,
    validate_canonical_vectors,
)
from tools.studio_v3_verify.runner import git_safe_environment, resolve_profile


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _architecture_config() -> dict[str, object]:
    return {
        "v3_modules": ["foundation", "assets", "timeline", "rendering", "application"],
        "allowed_dependencies": {
            "foundation": [],
            "assets": ["foundation"],
            "timeline": ["foundation", "assets"],
            "rendering": ["foundation", "assets", "timeline"],
            "application": ["foundation", "assets", "timeline", "rendering"],
        },
        "public_module": "api",
    }


def test_architecture_rejects_forbidden_dependency(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(source / "foundation" / "ids.py", "from dlstudio.application.api import Command\n")

    result = check_architecture(source, _architecture_config())

    assert result.status is GateStatus.FAIL
    assert any("foundation -> application" in detail for detail in result.details)


def test_architecture_rejects_cross_module_deep_import(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(source / "timeline" / "compiler.py", "from dlstudio.assets.models import AssetRevision\n")

    result = check_architecture(source, _architecture_config())

    assert result.status is GateStatus.FAIL
    assert any("must use dlstudio.assets.api" in detail for detail in result.details)


def test_architecture_accepts_public_api_import(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(source / "timeline" / "compiler.py", "from dlstudio.assets.api import AssetRevision\n")

    result = check_architecture(source, _architecture_config())

    assert result.status is GateStatus.PASS


def test_architecture_generates_quality_rule_index(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(
        source / "timeline" / "api.py",
        'RULES = ("VQ-SYNC", "VQ-ASSET", "not-a-rule")\n',
    )

    result = check_architecture(source, _architecture_config())

    assert result.status is GateStatus.PASS
    assert result.metrics["rules"] == 2
    assert result.metrics["rule_index"] == "VQ-ASSET,VQ-SYNC"


def test_architecture_resolves_relative_cross_module_import_from_package_init(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dlstudio"
    _write(source / "timeline" / "__init__.py", "from ..assets.models import AssetRevision\n")

    result = check_architecture(source, _architecture_config())

    assert result.status is GateStatus.FAIL
    assert any("must use dlstudio.assets.api" in detail for detail in result.details)


def test_architecture_rejects_dependency_cycle(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    config = _architecture_config()
    config["allowed_dependencies"] = {
        **config["allowed_dependencies"],
        "assets": ["foundation", "timeline"],
    }
    _write(source / "timeline" / "api.py", "from dlstudio.assets.api import AssetRevision\n")
    _write(source / "assets" / "api.py", "from dlstudio.timeline.api import TimelineIR\n")

    result = check_architecture(source, config)

    assert result.status is GateStatus.FAIL
    assert any("dependency cycle" in detail for detail in result.details)


def test_banned_surface_scan_catches_runtime_migration_and_cwd(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(
        source / "timeline" / "compiler.py",
        "from pathlib import Path\n"
        "from tools.studio_v3_migrate import migrate\n"
        "ROOT = Path.cwd()\n",
    )
    config = {
        "always_forbidden_import_prefixes": ["tools.studio_v3_migrate"],
        "always_forbidden_calls": ["Path.cwd", "os.chdir"],
        "always_forbidden_symbols": ["GLOBAL_CHUNK_RESOLVER"],
        "always_forbidden_literals": [{"name": "asset_policy", "value": "compatibility"}],
        "cutover_absent_paths": [],
        "cutover_forbidden_regex": [],
    }

    result = check_banned_surfaces(source, tmp_path, config, cutover=False)

    assert result.status is GateStatus.FAIL
    assert any("tools.studio_v3_migrate" in detail for detail in result.details)
    assert any("Path.cwd" in detail for detail in result.details)


def test_cutover_scan_requires_legacy_paths_to_be_absent(tmp_path: Path) -> None:
    source = tmp_path / "dlstudio"
    _write(source / "foundation" / "api.py", "")
    _write(tmp_path / "common" / "devlog" / "__init__.py", "")
    config = {
        "always_forbidden_import_prefixes": [],
        "always_forbidden_calls": [],
        "always_forbidden_symbols": [],
        "always_forbidden_literals": [],
        "cutover_absent_paths": ["common/devlog"],
        "cutover_forbidden_regex": [],
    }

    result = check_banned_surfaces(source, tmp_path, config, cutover=True)

    assert result.status is GateStatus.FAIL
    assert any("legacy path still exists" in detail for detail in result.details)


def test_canonical_vector_hook_rejects_hash_mismatch(tmp_path: Path) -> None:
    vector = tmp_path / "bad.vector.json"
    vector.write_text(
        json.dumps(
            {
                "id": "bad",
                "schema_version": 1,
                "expected_canonical_utf8": "{\"a\":1}",
                "expected_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    result = validate_canonical_vectors(tmp_path)

    assert result.status is GateStatus.FAIL
    assert any("hash mismatch" in detail for detail in result.details)


def test_repository_canonical_vectors_are_valid() -> None:
    vectors = Path(__file__).with_name("vectors")

    result = validate_canonical_vectors(vectors)

    assert result.status is GateStatus.PASS
    assert result.metrics["vectors"] >= 1


def test_performance_contract_requires_all_behavior_hooks() -> None:
    config_path = Path(__file__).parents[4] / "tools" / "studio_v3_verify" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    test_root = Path(__file__).parents[1]
    result = check_performance_contract(
        config["performance_hooks"], test_root
    )

    assert result.status is GateStatus.PASS
    assert result.metrics["hooks"] == 4
    assert result.metrics["tests"] == 4


def test_generated_client_is_deferred_before_cutover_without_script(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _write(webui / "package.json", json.dumps({"scripts": {}}))

    result = check_generated_client(tmp_path, webui, strict=False, run=lambda *_args, **_kwargs: 0)

    assert result.status is GateStatus.SKIP


def test_generated_client_is_blocking_at_cutover_without_script(tmp_path: Path) -> None:
    webui = tmp_path / "webui"
    _write(webui / "package.json", json.dumps({"scripts": {}}))

    result = check_generated_client(tmp_path, webui, strict=True, run=lambda *_args, **_kwargs: 0)

    assert result.status is GateStatus.FAIL
    assert any("generate:client" in detail for detail in result.details)


def test_generated_client_detects_changes_to_already_dirty_outputs(
    tmp_path: Path,
) -> None:
    webui = tmp_path / "webui"
    _write(
        webui / "package.json",
        json.dumps({"scripts": {"generate:client": "generate"}}),
    )
    schema = webui / "src" / "api" / "openapi.v3.json"
    types = webui / "src" / "api" / "v3.gen.ts"
    _write(schema, "dirty schema")
    _write(types, "dirty types")

    def regenerate(*_args, **_kwargs) -> int:
        _write(schema, "canonical schema")
        _write(types, "canonical types")
        return 0

    result = check_generated_client(
        tmp_path,
        webui,
        strict=True,
        run=regenerate,
    )

    assert result.status is GateStatus.FAIL
    assert any("changed generated bytes" in detail for detail in result.details)


def test_auto_profile_is_phase0_while_any_legacy_path_exists(tmp_path: Path) -> None:
    _write(tmp_path / "common" / "devlog" / "__init__.py", "")

    profile = resolve_profile(
        "auto",
        tmp_path,
        {"cutover_absent_paths": ["common/devlog", "common/dlstudio/src/dlstudio/model"]},
    )

    assert profile == "phase0"


def test_auto_profile_is_cutover_after_all_legacy_paths_are_absent(tmp_path: Path) -> None:
    profile = resolve_profile(
        "auto",
        tmp_path,
        {"cutover_absent_paths": ["common/devlog", "common/dlstudio/src/dlstudio/model"]},
    )

    assert profile == "cutover"


def test_git_safe_environment_does_not_require_global_git_config(tmp_path: Path) -> None:
    env = git_safe_environment(tmp_path, {"KEEP": "yes"})

    assert env["KEEP"] == "yes"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_0"] == tmp_path.resolve().as_posix()


def test_python_ci_lock_contains_only_exact_pins() -> None:
    repo_root = Path(__file__).parents[4]
    lock = repo_root / "tools" / "studio_v3_verify" / "python-ci.lock"
    requirement_lines = [
        line.strip()
        for line in lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert requirement_lines
    assert all("==" in line.split(";", 1)[0] for line in requirement_lines)
    assert not any(
        operator in line.split(";", 1)[0]
        for line in requirement_lines
        for operator in (">=", "<=", "~=", "!=", ">", "<")
    )


def test_ci_matrix_locks_windows_linux_python_and_node() -> None:
    repo_root = Path(__file__).parents[4]
    workflow = (repo_root / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    assert "ubuntu-24.04" in workflow
    assert "windows-2022" in workflow
    assert 'python-version: "3.12.4"' in workflow
    assert 'node-version: "22.14.0"' in workflow
    assert "python-ci.lock" in workflow
    assert "npm ci" in workflow
