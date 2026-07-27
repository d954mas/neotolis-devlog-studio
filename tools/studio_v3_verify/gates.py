from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class GateResult:
    name: str
    status: GateStatus
    details: tuple[str, ...] = ()
    metrics: Mapping[str, int | float | str] = field(default_factory=dict)


def _python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and not path.name.endswith(".pyi")
    )


def _module_name(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    return ".".join(("dlstudio", *relative.parts))


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = module_name.split(".")[:-1]
    if not package:
        return None
    trim = node.level - 1
    if trim > len(package):
        return None
    base = package[: len(package) - trim] if trim else package
    suffix = node.module.split(".") if node.module else []
    return ".".join((*base, *suffix))


def _dlstudio_target(import_name: str | None) -> tuple[str, tuple[str, ...]] | None:
    if not import_name:
        return None
    parts = import_name.split(".")
    if len(parts) < 2 or parts[0] != "dlstudio":
        return None
    return parts[1], tuple(parts[2:])


def _cycle(graph: Mapping[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in active_set:
            index = active.index(node)
            return [*active[index:], node]
        if node in visited:
            return None
        active.append(node)
        active_set.add(node)
        for target in sorted(graph.get(node, ())):
            found = visit(target)
            if found:
                return found
        active.pop()
        active_set.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        found = visit(node)
        if found:
            return found
    return None


def check_architecture(source_root: Path, config: Mapping[str, object]) -> GateResult:
    modules = set(str(value) for value in config["v3_modules"])
    allowed_raw = config["allowed_dependencies"]
    assert isinstance(allowed_raw, Mapping)
    allowed = {
        str(owner): set(str(target) for target in targets)
        for owner, targets in allowed_raw.items()
    }
    public_module = str(config.get("public_module", "api"))
    graph: dict[str, set[str]] = {module: set() for module in modules}
    details: list[str] = []
    parsed_files = 0

    for path in _python_files(source_root):
        relative = path.relative_to(source_root)
        owner = relative.parts[0]
        if owner not in modules:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            details.append(f"{relative.as_posix()}: cannot parse: {exc}")
            continue
        parsed_files += 1
        module_name = _module_name(source_root, path)
        imported: list[tuple[str, tuple[str, ...], int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _dlstudio_target(alias.name)
                    if target:
                        imported.append((*target, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = _dlstudio_target(_resolve_import(module_name, node))
                if target:
                    imported.append((*target, node.lineno))

        for target, remainder, line in imported:
            if target == owner or target not in modules:
                continue
            graph[owner].add(target)
            if target not in allowed.get(owner, set()):
                details.append(
                    f"{relative.as_posix()}:{line}: forbidden dependency {owner} -> {target}"
                )
            if not remainder or remainder[0] != public_module:
                details.append(
                    f"{relative.as_posix()}:{line}: cross-module import must use "
                    f"dlstudio.{target}.{public_module}"
                )

    found_cycle = _cycle(graph)
    if found_cycle:
        details.append(f"dependency cycle: {' -> '.join(found_cycle)}")
    return GateResult(
        name="architecture/import-boundaries",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(details),
        metrics={"files": parsed_files, "edges": sum(map(len, graph.values()))},
    )


def _qualified_call(node: ast.Call) -> str | None:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
        return ".".join(reversed(parts))
    return None


def _assigned_names(node: ast.AST) -> Iterable[tuple[str, ast.AST]]:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if node.value is not None:
            yield node.target.id, node.value
    elif isinstance(node, ast.keyword) and node.arg:
        yield node.arg, node.value


def check_banned_surfaces(
    source_root: Path,
    repo_root: Path,
    config: Mapping[str, object],
    *,
    cutover: bool,
) -> GateResult:
    import_prefixes = tuple(str(value) for value in config["always_forbidden_import_prefixes"])
    forbidden_calls = set(str(value) for value in config["always_forbidden_calls"])
    forbidden_symbols = set(str(value) for value in config["always_forbidden_symbols"])
    literal_rules = {
        (str(item["name"]), str(item["value"]))
        for item in config["always_forbidden_literals"]
    }
    details: list[str] = []
    parsed_files = 0

    configured_modules = set(str(value) for value in config.get("v3_modules", ()))
    for path in _python_files(source_root):
        relative = path.relative_to(repo_root).as_posix()
        owner = path.relative_to(source_root).parts[0]
        if configured_modules and owner not in configured_modules:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            details.append(f"{relative}: cannot parse: {exc}")
            continue
        parsed_files += 1
        for node in ast.walk(tree):
            import_names: list[str] = []
            if isinstance(node, ast.Import):
                import_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                import_names.append(node.module)
            for import_name in import_names:
                if any(
                    import_name == prefix or import_name.startswith(prefix + ".")
                    for prefix in import_prefixes
                ):
                    details.append(
                        f"{relative}:{node.lineno}: forbidden runtime import {import_name}"
                    )
            if isinstance(node, ast.Call):
                qualified = _qualified_call(node)
                if qualified in forbidden_calls:
                    details.append(f"{relative}:{node.lineno}: forbidden call {qualified}")
            if isinstance(node, ast.Name) and node.id in forbidden_symbols:
                details.append(f"{relative}:{node.lineno}: forbidden symbol {node.id}")
            for name, value in _assigned_names(node):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if (name, value.value) in literal_rules:
                        details.append(
                            f"{relative}:{getattr(node, 'lineno', 0)}: forbidden "
                            f"{name}={value.value!r}"
                        )

    if cutover:
        for relative_path in config["cutover_absent_paths"]:
            target = repo_root / str(relative_path)
            if target.exists():
                details.append(f"legacy path still exists: {relative_path}")
        patterns = [re.compile(str(pattern)) for pattern in config["cutover_forbidden_regex"]]
        for path in _python_files(source_root):
            relative = path.relative_to(repo_root).as_posix()
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                if pattern.search(text):
                    details.append(
                        f"{relative}: cutover-banned surface matches /{pattern.pattern}/"
                    )

    return GateResult(
        name="banned-runtime-surfaces",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(sorted(set(details))),
        metrics={"files": parsed_files, "cutover": str(cutover).lower()},
    )


def validate_canonical_vectors(vector_root: Path) -> GateResult:
    details: list[str] = []
    files = sorted(vector_root.glob("*.vector.json")) if vector_root.is_dir() else []
    if not files:
        return GateResult(
            name="canonical-vectors",
            status=GateStatus.FAIL,
            details=(f"no *.vector.json files found under {vector_root}",),
            metrics={"vectors": 0},
        )
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            vector_id = value["id"]
            schema_version = value["schema_version"]
            canonical = value["expected_canonical_utf8"]
            expected_hash = value["expected_sha256"]
            if not isinstance(vector_id, str) or not vector_id:
                raise ValueError("id must be a non-empty string")
            if not isinstance(schema_version, int) or schema_version < 1:
                raise ValueError("schema_version must be a positive integer")
            if not isinstance(canonical, str):
                raise ValueError("expected_canonical_utf8 must be a string")
            canonical_bytes = canonical.encode("utf-8")
            if b"\r" in canonical_bytes:
                raise ValueError("canonical bytes contain CR")
            actual_hash = hashlib.sha256(canonical_bytes).hexdigest()
            if actual_hash != expected_hash:
                details.append(
                    f"{path.name}: hash mismatch: expected {expected_hash}, got {actual_hash}"
                )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
            details.append(f"{path.name}: invalid canonical vector: {exc}")
    return GateResult(
        name="canonical-vectors",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(details),
        metrics={"vectors": len(files)},
    )


_REQUIRED_PERFORMANCE_HOOKS = {
    "status_no_compile_scan_subprocess",
    "cache_hit_no_ffmpeg_full_read",
    "cli_api_no_heavy_provider_import",
    "review_pack_bounded",
}


def check_performance_contract(hooks: object, test_root: Path) -> GateResult:
    details: list[str] = []
    if not isinstance(hooks, list):
        return GateResult(
            name="performance-contract",
            status=GateStatus.FAIL,
            details=("performance_hooks must be a list",),
        )
    ids: set[str] = set()
    for index, hook in enumerate(hooks):
        if not isinstance(hook, Mapping):
            details.append(f"performance_hooks[{index}] must be an object")
            continue
        hook_id = hook.get("id")
        selector = hook.get("test_selector")
        owner = hook.get("owner")
        if not isinstance(hook_id, str) or not hook_id:
            details.append(f"performance_hooks[{index}] has no id")
            continue
        ids.add(hook_id)
        if not isinstance(selector, str) or not selector:
            details.append(f"{hook_id}: no test_selector")
        if not isinstance(owner, str) or not owner:
            details.append(f"{hook_id}: no owner")
    missing = sorted(_REQUIRED_PERFORMANCE_HOOKS - ids)
    if missing:
        details.append(f"missing required performance hooks: {', '.join(missing)}")
    implemented: set[str] = set()
    for path in sorted(test_root.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            details.append(f"cannot inspect performance test {path}: {exc}")
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hook_id = node.name.removeprefix("test_")
            if hook_id not in ids:
                continue
            marked = any(
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "performance_smoke"
                for decorator in node.decorator_list
            )
            if marked:
                implemented.add(hook_id)
            else:
                details.append(
                    f"{hook_id}: test exists but lacks performance_smoke marker"
                )
    missing_tests = sorted(ids - implemented)
    if missing_tests:
        details.append(
            "missing executable performance tests: "
            + ", ".join(missing_tests)
        )
    return GateResult(
        name="performance-contract",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(details),
        metrics={"hooks": len(ids), "tests": len(implemented)},
    )


RunFunction = Callable[[Sequence[str], Path, Mapping[str, str] | None], int]


def _run_process(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> int:
    completed = subprocess.run(list(command), cwd=cwd, env=env, check=False)
    return completed.returncode


def _generated_snapshot(webui_root: Path) -> tuple[tuple[str, str | None], ...]:
    paths = (
        webui_root / "src" / "api" / "openapi.v3.json",
        webui_root / "src" / "api" / "v3.gen.ts",
    )
    return tuple(
        (
            path.relative_to(webui_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else None,
        )
        for path in paths
    )


def check_generated_client(
    repo_root: Path,
    webui_root: Path,
    *,
    strict: bool,
    run: RunFunction = _run_process,
    env: Mapping[str, str] | None = None,
) -> GateResult:
    package_path = webui_root / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return GateResult(
            name="generated-openapi-client",
            status=GateStatus.FAIL,
            details=(f"cannot read {package_path}: {exc}",),
        )
    scripts = package.get("scripts", {})
    if not isinstance(scripts, Mapping) or "generate:client" not in scripts:
        status = GateStatus.FAIL if strict else GateStatus.SKIP
        return GateResult(
            name="generated-openapi-client",
            status=status,
            details=("package.json has no generate:client script",),
        )

    before = _generated_snapshot(webui_root)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    generate_rc = run([npm, "run", "generate:client"], webui_root, env)
    after = _generated_snapshot(webui_root)
    details: list[str] = []
    if generate_rc:
        details.append(f"generate:client exited {generate_rc}")
    if before != after:
        details.append("generate:client changed generated bytes; commit regenerated output")
    return GateResult(
        name="generated-openapi-client",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(details),
    )


def check_toolchain(config: Mapping[str, object]) -> GateResult:
    details: list[str] = []
    expected_python = tuple(int(part) for part in str(config["python"]).split("."))
    actual_python = sys.version_info[:2]
    if actual_python != expected_python:
        details.append(
            f"Python {expected_python[0]}.{expected_python[1]} required; "
            f"running {actual_python[0]}.{actual_python[1]}"
        )
    node_expected = int(config["node_major"])
    try:
        completed = subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+\s*", completed.stdout)
        if completed.returncode or match is None:
            details.append("node --version failed or returned an invalid version")
        elif int(match.group(1)) != node_expected:
            details.append(
                f"Node {node_expected}.x required; running {completed.stdout.strip()}"
            )
    except OSError as exc:
        details.append(f"Node {node_expected}.x required: {exc}")
    return GateResult(
        name="locked-toolchain",
        status=GateStatus.FAIL if details else GateStatus.PASS,
        details=tuple(details),
    )
