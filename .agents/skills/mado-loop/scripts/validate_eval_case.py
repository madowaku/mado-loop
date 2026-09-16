"""Validate and digest a MADO EVALS v0.1 case without external dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import CONCRETE_TASK_DOMAINS, EXIT_INTERNAL, EXIT_USAGE_CONFIG  # noqa: E402

SCHEMA_VERSION = "0.1"
PROOF_LEVELS = ("P0", "P1", "P2", "P3", "P4", "P5")
CHECK_KINDS = ("proof", "test", "artifact", "evidence", "invariant")
SENSITIVITY = ("public", "private", "secret")
NETWORK = ("normal", "restricted", "offline")
MUTATION = ("none", "isolated_worktree")
PLATFORMS = ("windows", "linux", "macos")
CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
CHECK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

CASE_KEYS = {
    "schema_version",
    "id",
    "title",
    "domains",
    "task_file",
    "fixture",
    "tags",
    "required_proof",
    "acceptance",
    "policy",
    "expected_paths",
}
REQUIRED_CASE_KEYS = {
    "schema_version",
    "id",
    "title",
    "domains",
    "task_file",
    "required_proof",
    "acceptance",
    "policy",
}
CHECK_KEYS = {"id", "kind", "required", "description"}
POLICY_KEYS = {"sensitivity", "network", "mutation", "timeout_seconds", "allowed_platforms"}
REQUIRED_POLICY_KEYS = {"sensitivity", "network", "mutation", "timeout_seconds"}


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _strict_keys(payload: Mapping[str, Any], *, allowed: set[str], required: set[str], label: str) -> None:
    unknown = sorted(set(payload).difference(allowed))
    missing = sorted(required.difference(payload))
    _expect(not unknown, f"{label} has unknown keys: {unknown}")
    _expect(not missing, f"{label} is missing required keys: {missing}")


def _safe_relative(value: Any, *, label: str) -> Path:
    _expect(isinstance(value, str) and bool(value.strip()), f"{label} must be a non-empty string")
    raw = value.strip()
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    _expect(not posix.is_absolute(), f"{label} must be relative")
    _expect(not windows.is_absolute() and windows.drive == "", f"{label} must be relative")
    _expect(".." not in posix.parts and ".." not in windows.parts, f"{label} must not traverse parents")
    normalized = Path(raw)
    _expect(str(normalized) not in {".", ""}, f"{label} must name a path")
    return normalized


def _inside(base: Path, path: Path, *, label: str) -> Path:
    base_resolved = base.resolve()
    target = (base / path).resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the eval case directory") from exc
    return target


def _canonical_unique(values: Any, *, allowed: Iterable[str], label: str) -> list[str]:
    _expect(isinstance(values, list) and bool(values), f"{label} must be a non-empty array")
    strings = [str(value) for value in values]
    _expect(len(strings) == len(set(strings)), f"{label} must not contain duplicates")
    allowed_order = tuple(allowed)
    invalid = sorted(set(strings).difference(allowed_order))
    _expect(not invalid, f"{label} contains invalid values: {invalid}")
    selected = set(strings)
    return [value for value in allowed_order if value in selected]


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _manifest_entries(case_dir: Path, target: Path) -> list[dict[str, Any]]:
    case_root = case_dir.resolve()
    if target.is_file():
        resolved = target.resolve()
        try:
            relative = resolved.relative_to(case_root)
        except ValueError as exc:
            raise ValueError(f"manifest target escapes the eval case directory: {target}") from exc
        digest, size = _sha256_file(resolved)
        return [{
            "path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": size,
        }]
    _expect(target.is_dir(), f"manifest target does not exist: {target}")
    entries: list[dict[str, Any]] = []
    for child in sorted((item for item in target.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        resolved = child.resolve()
        try:
            relative = resolved.relative_to(case_root)
        except ValueError as exc:
            raise ValueError(f"manifest file escapes the eval case directory: {child}") from exc
        digest, size = _sha256_file(resolved)
        entries.append({
            "path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": size,
        })
    return entries


def _validate_acceptance(raw: Any) -> list[dict[str, Any]]:
    _expect(isinstance(raw, list) and bool(raw), "acceptance must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        _expect(isinstance(value, dict), f"acceptance[{index}] must be an object")
        _strict_keys(value, allowed=CHECK_KEYS, required=CHECK_KEYS, label=f"acceptance[{index}]")
        check_id = str(value["id"])
        _expect(bool(CHECK_ID_RE.fullmatch(check_id)), f"invalid acceptance id: {check_id!r}")
        _expect(check_id not in seen, f"duplicate acceptance id: {check_id}")
        seen.add(check_id)
        kind = str(value["kind"])
        _expect(kind in CHECK_KINDS, f"invalid acceptance kind: {kind!r}")
        _expect(type(value["required"]) is bool, f"acceptance {check_id} required must be boolean")
        description = value["description"]
        _expect(isinstance(description, str) and 3 <= len(description) <= 500, f"acceptance {check_id} description length invalid")
        normalized.append({
            "id": check_id,
            "kind": kind,
            "required": value["required"],
            "description": description,
        })
    return normalized


def _validate_policy(raw: Any) -> dict[str, Any]:
    _expect(isinstance(raw, dict), "policy must be an object")
    _strict_keys(raw, allowed=POLICY_KEYS, required=REQUIRED_POLICY_KEYS, label="policy")
    sensitivity = str(raw["sensitivity"])
    network = str(raw["network"])
    mutation = str(raw["mutation"])
    _expect(sensitivity in SENSITIVITY, f"invalid policy sensitivity: {sensitivity!r}")
    _expect(network in NETWORK, f"invalid policy network: {network!r}")
    _expect(mutation in MUTATION, f"invalid policy mutation: {mutation!r}")
    timeout = raw["timeout_seconds"]
    _expect(type(timeout) is int and 1 <= timeout <= 3600, "policy timeout_seconds must be 1..3600")
    platforms = raw.get("allowed_platforms", ["windows"])
    _expect(isinstance(platforms, list) and bool(platforms), "policy allowed_platforms must be a non-empty array")
    platform_values = [str(value) for value in platforms]
    _expect(len(platform_values) == len(set(platform_values)), "policy allowed_platforms must be unique")
    invalid = sorted(set(platform_values).difference(PLATFORMS))
    _expect(not invalid, f"invalid allowed platforms: {invalid}")
    canonical_platforms = [value for value in PLATFORMS if value in set(platform_values)]
    return {
        "sensitivity": sensitivity,
        "network": network,
        "mutation": mutation,
        "timeout_seconds": timeout,
        "allowed_platforms": canonical_platforms,
    }


def validate_case_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the JSON portion of one eval case."""
    _strict_keys(payload, allowed=CASE_KEYS, required=REQUIRED_CASE_KEYS, label="eval case")
    _expect(payload.get("schema_version") == SCHEMA_VERSION, "unsupported eval case schema_version")

    case_id = payload.get("id")
    _expect(isinstance(case_id, str) and bool(CASE_ID_RE.fullmatch(case_id)), "invalid eval case id")
    title = payload.get("title")
    _expect(isinstance(title, str) and 3 <= len(title) <= 160, "title must be 3..160 characters")

    domains = _canonical_unique(payload.get("domains"), allowed=CONCRETE_TASK_DOMAINS, label="domains")
    required_proof_raw = payload.get("required_proof")
    _expect(isinstance(required_proof_raw, list), "required_proof must be an array")
    proof_values = [str(value) for value in required_proof_raw]
    _expect(len(proof_values) == len(set(proof_values)), "required_proof must not contain duplicates")
    invalid_proof = sorted(set(proof_values).difference(PROOF_LEVELS))
    _expect(not invalid_proof, f"required_proof contains invalid values: {invalid_proof}")
    proof_selected = set(proof_values)
    required_proof = [value for value in PROOF_LEVELS if value in proof_selected]

    task_file = _safe_relative(payload.get("task_file"), label="task_file").as_posix()
    _expect(task_file.endswith(".md"), "task_file must be a markdown file")

    fixture_raw = payload.get("fixture")
    fixture = None if fixture_raw is None else _safe_relative(fixture_raw, label="fixture").as_posix()

    tags_raw = payload.get("tags", [])
    _expect(isinstance(tags_raw, list), "tags must be an array")
    tags = [str(value) for value in tags_raw]
    _expect(len(tags) == len(set(tags)), "tags must be unique")
    _expect(all(TAG_RE.fullmatch(value) for value in tags), "tags must contain canonical ids only")
    tags.sort()

    expected_raw = payload.get("expected_paths", [])
    _expect(isinstance(expected_raw, list), "expected_paths must be an array")
    expected_paths = [_safe_relative(value, label="expected_paths item").as_posix() for value in expected_raw]
    _expect(len(expected_paths) == len(set(expected_paths)), "expected_paths must be unique")
    expected_paths.sort()

    return {
        "schema_version": SCHEMA_VERSION,
        "id": case_id,
        "title": title,
        "domains": domains,
        "task_file": task_file,
        "fixture": fixture,
        "tags": tags,
        "required_proof": required_proof,
        "acceptance": _validate_acceptance(payload.get("acceptance")),
        "policy": _validate_policy(payload.get("policy")),
        "expected_paths": expected_paths,
    }


def load_and_digest_case(case_json: str | Path) -> dict[str, Any]:
    """Load one case, validate referenced inputs, and return a canonical digest manifest."""
    case_path = Path(case_json).resolve()
    _expect(case_path.is_file(), f"eval case file does not exist: {case_path}")
    _expect(case_path.name == "case.json", "eval case file must be named case.json")
    case_dir = case_path.parent.resolve()
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    _expect(isinstance(payload, dict), "case.json root must be an object")
    normalized = validate_case_payload(payload)

    manifest_by_path: dict[str, dict[str, Any]] = {}

    task_target = _inside(case_dir, Path(normalized["task_file"]), label="task_file")
    _expect(task_target.is_file(), f"task_file does not exist: {normalized['task_file']}")
    for entry in _manifest_entries(case_dir, task_target):
        manifest_by_path[entry["path"]] = entry

    if normalized["fixture"] is not None:
        fixture_target = _inside(case_dir, Path(normalized["fixture"]), label="fixture")
        _expect(fixture_target.exists(), f"fixture does not exist: {normalized['fixture']}")
        for entry in _manifest_entries(case_dir, fixture_target):
            manifest_by_path[entry["path"]] = entry

    for expected in normalized["expected_paths"]:
        expected_target = _inside(case_dir, Path(expected), label="expected_path")
        _expect(expected_target.exists(), f"expected path does not exist: {expected}")
        for entry in _manifest_entries(case_dir, expected_target):
            manifest_by_path[entry["path"]] = entry

    files = [manifest_by_path[key] for key in sorted(manifest_by_path)]
    digest_input = {
        "case": normalized,
        "files": files,
    }
    canonical = json.dumps(digest_input, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": normalized["id"],
        "case_digest": digest,
        "case": normalized,
        "files": files,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_json", type=Path, help="path to an eval case case.json")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        manifest = load_and_digest_case(args.case_json)
        output = {
            "status": "PASS",
            **manifest,
        }
        if args.pretty:
            sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"validate_eval_case error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"validate_eval_case internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
