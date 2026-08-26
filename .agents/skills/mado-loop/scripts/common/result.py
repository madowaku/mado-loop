"""Deterministic verification-result contract used by MADO LOOP tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.1"
STATUSES = ("PASS", "FAIL", "WARN", "UNKNOWN", "SKIPPED")
PROOF_LEVELS = ("P0", "P1", "P2", "P3", "P4", "P5")
CONCRETE_TASK_DOMAINS = (
    "CODE", "GAMEPLAY", "UI", "SPRITE", "IMAGE", "ANIMATION",
    "ASSET_INTEGRATION", "REFERENCE_TO_UI", "PIXEL_ART", "PLAYTEST", "RELEASE",
)
TASK_DOMAINS = CONCRETE_TASK_DOMAINS + ("MIXED",)
RESULT_KEYS = (
    "schema_version", "tool", "status", "proof_level", "task_domains", "summary",
    "checks", "errors", "warnings", "unknowns", "artifacts", "environment", "duration_ms",
)
CHECK_KEYS = ("id", "status", "required", "message", "evidence", "details")
ARTIFACT_KEYS = ("path", "kind", "exists", "size_bytes", "sha256")
EXIT_USAGE_CONFIG = 64
EXIT_INTERNAL = 70

_EXIT_CODES = {"PASS": 0, "WARN": 0, "FAIL": 1, "UNKNOWN": 2, "SKIPPED": 3}


def _status(value: str) -> str:
    if value not in STATUSES:
        raise ValueError(f"invalid status: {value!r}")
    return value


def _proof_level(value: str | None) -> str | None:
    if value is not None and value not in PROOF_LEVELS:
        raise ValueError(f"invalid proof level: {value!r}")
    return value


def _ordered_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: value[key] for key in sorted(value or {})}


def canonical_task_domains(
    values: Iterable[str], *, domain_neutral: bool = False,
) -> list[str]:
    """Validate and canonically order concrete domains, deriving MIXED."""
    supplied = [str(value) for value in values]
    if "MIXED" in supplied:
        raise ValueError("MIXED is derived and must not be supplied")
    invalid = sorted(set(supplied).difference(CONCRETE_TASK_DOMAINS))
    if invalid:
        raise ValueError(f"invalid task domains: {invalid!r}")
    if not supplied:
        if not domain_neutral:
            raise ValueError("empty task_domains requires domain_neutral=True")
        return []
    if domain_neutral:
        raise ValueError("domain_neutral=True cannot include task domains")
    selected = set(supplied)
    canonical = [domain for domain in CONCRETE_TASK_DOMAINS if domain in selected]
    if len(canonical) >= 2:
        canonical.append("MIXED")
    return canonical


def make_check(
    check_id: str,
    status: str,
    *,
    required: bool = True,
    message: str = "",
    evidence: Sequence[Any] | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one check in canonical field order."""
    return {
        "id": str(check_id),
        "status": _status(status),
        "required": bool(required),
        "message": str(message),
        "evidence": list(evidence or ()),
        "details": _ordered_mapping(details),
    }


def make_artifact(path: str | Path, kind: str) -> dict[str, Any]:
    """Describe a file artifact, hashing existing regular files."""
    artifact_path = Path(path)
    exists = artifact_path.is_file()
    digest = None
    size = None
    if exists:
        data = artifact_path.read_bytes()
        size = len(data)
        digest = hashlib.sha256(data).hexdigest()
    return {
        "path": str(artifact_path),
        "kind": str(kind),
        "exists": exists,
        "size_bytes": size,
        "sha256": digest,
    }


def aggregate_status(
    checks: Iterable[Mapping[str, Any]],
    *,
    warnings: Sequence[Any] | None = None,
    unknowns: Sequence[Any] | None = None,
) -> str:
    """Aggregate checks according to the shared result precedence rules."""
    items = list(checks)
    for check in items:
        _status(str(check["status"]))
    if any(check.get("required", True) and check["status"] == "FAIL" for check in items):
        return "FAIL"
    if unknowns or any(
        check.get("required", True) and check["status"] in {"UNKNOWN", "SKIPPED"}
        for check in items
    ):
        return "UNKNOWN"
    if warnings or any(
        (not check.get("required", True)) and check["status"] != "PASS"
        for check in items
    ) or any(check["status"] == "WARN" for check in items):
        return "WARN"
    return "PASS"


def make_result(
    tool: str,
    *,
    proof_level: str | None,
    summary: str,
    task_domains: Iterable[str] = (),
    domain_neutral: bool = False,
    checks: Iterable[Mapping[str, Any]] = (),
    errors: Sequence[Any] = (),
    warnings: Sequence[Any] = (),
    unknowns: Sequence[Any] = (),
    artifacts: Iterable[Mapping[str, Any]] = (),
    environment: Mapping[str, Any] | None = None,
    duration_ms: int = 0,
    status: str | None = None,
    operation_skipped: bool = False,
) -> dict[str, Any]:
    """Build a result with canonical top-level and collection ordering."""
    canonical_checks = sorted((dict(item) for item in checks), key=lambda item: str(item["id"]))
    canonical_artifacts = sorted(
        (dict(item) for item in artifacts), key=lambda item: (str(item["path"]), str(item["kind"]))
    )
    domains = canonical_task_domains(task_domains, domain_neutral=domain_neutral)
    aggregate = aggregate_status(canonical_checks, warnings=warnings, unknowns=unknowns)
    if operation_skipped:
        if status != "SKIPPED":
            raise ValueError("operation_skipped=True requires status='SKIPPED'")
        if canonical_checks or errors or warnings or unknowns:
            raise ValueError("a skipped operation cannot contain findings")
        aggregate = "SKIPPED"
    elif status == "SKIPPED":
        raise ValueError("top-level SKIPPED requires operation_skipped=True")
    elif status is not None and _status(status) != aggregate:
        raise ValueError(f"status {status!r} does not match aggregate {aggregate!r}")
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": str(tool),
        "status": aggregate,
        "proof_level": _proof_level(proof_level),
        "task_domains": domains,
        "summary": str(summary),
        "checks": canonical_checks,
        "errors": list(errors),
        "warnings": list(warnings),
        "unknowns": list(unknowns),
        "artifacts": canonical_artifacts,
        "environment": _ordered_mapping(environment),
        "duration_ms": int(duration_ms),
    }


def result_json(result: Mapping[str, Any]) -> str:
    """Serialize a result reproducibly as UTF-8 friendly JSON."""
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"


def exit_code_for_status(status: str) -> int:
    """Return the contract exit code for an aggregate status."""
    return _EXIT_CODES[_status(status)]


def elapsed_ms(started_at: float) -> int:
    """Return monotonic elapsed milliseconds for result producers."""
    return max(0, round((monotonic() - started_at) * 1000))
