"""Build canonical MADO EVALS v0.1 result records from observed outcomes."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "0.1"
STATUSES = ("PASS", "WARN", "UNKNOWN", "FAIL")
PROOF_LEVELS = ("P0", "P1", "P2", "P3", "P4", "P5")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
FAILURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _status(value: Any) -> str:
    text = str(value)
    _expect(text in STATUSES, f"invalid eval status: {text!r}")
    return text


def make_outcome(
    outcome_id: str,
    status: str,
    *,
    required: bool,
    evidence: Sequence[str] | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    _expect(bool(FAILURE_ID_RE.fullmatch(str(outcome_id))), f"invalid outcome id: {outcome_id!r}")
    normalized_evidence = sorted({str(item) for item in (evidence or ()) if str(item)})
    if detail is not None:
        _expect(len(str(detail)) <= 1000, "outcome detail must be <= 1000 characters")
    return {
        "id": str(outcome_id),
        "status": _status(status),
        "required": bool(required),
        "evidence": normalized_evidence,
        "detail": None if detail is None else str(detail),
    }


def _coerce_observation(raw: Any) -> tuple[str, list[str], str | None]:
    if raw is None:
        return "UNKNOWN", [], None
    if isinstance(raw, str):
        return _status(raw), [], None
    _expect(isinstance(raw, Mapping), "outcome observation must be a status string or object")
    status = _status(raw.get("status", "UNKNOWN"))
    evidence_raw = raw.get("evidence", [])
    _expect(isinstance(evidence_raw, Sequence) and not isinstance(evidence_raw, (str, bytes)), "outcome evidence must be an array")
    detail = raw.get("detail")
    return status, [str(item) for item in evidence_raw], None if detail is None else str(detail)


def _required_status(outcomes: Iterable[Mapping[str, Any]]) -> str:
    items = list(outcomes)
    if any(item["required"] and item["status"] == "FAIL" for item in items):
        return "FAIL"
    if any(item["required"] and item["status"] == "UNKNOWN" for item in items):
        return "UNKNOWN"
    if any(item["status"] == "WARN" for item in items):
        return "WARN"
    if any((not item["required"]) and item["status"] != "PASS" for item in items):
        return "WARN"
    return "PASS"


def _proof_status(proof: Sequence[Mapping[str, Any]]) -> str:
    required = [item for item in proof if item["required"]]
    if not required:
        return "UNPROVEN"
    if any(item["status"] == "FAIL" for item in required):
        return "FAILED"
    passed = sum(1 for item in required if item["status"] == "PASS")
    unknown = sum(1 for item in required if item["status"] == "UNKNOWN")
    warned = sum(1 for item in required if item["status"] == "WARN")
    if passed == len(required):
        return "PROVEN"
    if unknown == len(required):
        return "UNKNOWN"
    if unknown or warned:
        return "PARTIAL"
    return "UNPROVEN"


def _failure_signatures(
    proof: Sequence[Mapping[str, Any]],
    acceptance: Sequence[Mapping[str, Any]],
    regressions: Sequence[Mapping[str, Any]],
    supplied: Iterable[str],
) -> list[str]:
    signatures = {str(item) for item in supplied if str(item)}
    for prefix, outcomes in (("proof", proof), ("acceptance", acceptance), ("regression", regressions)):
        for outcome in outcomes:
            if outcome["required"] and outcome["status"] in {"FAIL", "UNKNOWN"}:
                signatures.add(f"{prefix}:{outcome['id']}:{outcome['status']}")
    _expect(all(FAILURE_ID_RE.fullmatch(item) for item in signatures), "failure signatures must be short opaque ids")
    return sorted(signatures)


def _normalize_evidence(raw: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed_kinds = {"test", "log", "screenshot", "video", "artifact", "receipt", "report", "other"}
    output: list[dict[str, Any]] = []
    for item in raw:
        _expect(isinstance(item, Mapping), "evidence entries must be objects")
        kind = str(item.get("kind", ""))
        raw_path = str(item.get("path", "")).strip()
        _expect(kind in allowed_kinds, f"invalid evidence kind: {kind!r}")
        _expect(bool(raw_path), "evidence path is required")
        posix = PurePosixPath(raw_path)
        windows = PureWindowsPath(raw_path)
        _expect(not posix.is_absolute(), "evidence path must be relative and contained")
        _expect(not windows.is_absolute() and windows.drive == "", "evidence path must be relative and contained")
        _expect(".." not in posix.parts and ".." not in windows.parts, "evidence path must be relative and contained")
        path = raw_path.replace("\\", "/")
        sha256 = item.get("sha256")
        if sha256 is not None:
            _expect(bool(re.fullmatch(r"[a-f0-9]{64}", str(sha256))), "evidence sha256 must be lowercase hex")
        output.append({"kind": kind, "path": path, "sha256": None if sha256 is None else str(sha256)})
    return sorted(output, key=lambda item: (item["path"], item["kind"]))


def build_eval_result(
    *,
    run_id: str,
    case_manifest: Mapping[str, Any],
    candidate_id: str,
    candidate_revision: str | None = None,
    candidate_digest: str | None = None,
    proof_observations: Mapping[str, Any] | None = None,
    acceptance_observations: Mapping[str, Any] | None = None,
    repair_cycles: int = 0,
    tokens: int | None = None,
    wall_time_ms: int | None = None,
    evidence: Iterable[Mapping[str, Any]] = (),
    failure_signatures: Iterable[str] = (),
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a result, materializing missing required observations as UNKNOWN."""
    _expect(bool(RUN_ID_RE.fullmatch(str(run_id))), "run_id must be a short opaque identifier")
    _expect(case_manifest.get("schema_version") == SCHEMA_VERSION, "unsupported eval case manifest version")
    case = case_manifest.get("case")
    _expect(isinstance(case, Mapping), "case_manifest requires normalized case")
    case_id = str(case_manifest.get("case_id", ""))
    case_digest = str(case_manifest.get("case_digest", ""))
    _expect(case_id == str(case.get("id", "")), "case manifest id mismatch")
    _expect(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", case_digest)), "invalid case digest")
    _expect(bool(str(candidate_id)), "candidate_id is required")
    if candidate_digest is not None:
        _expect(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", str(candidate_digest))), "invalid candidate digest")
    _expect(type(repair_cycles) is int and repair_cycles >= 0, "repair_cycles must be >= 0")
    _expect(tokens is None or (type(tokens) is int and tokens >= 0), "tokens must be >= 0 when supplied")
    _expect(wall_time_ms is None or (type(wall_time_ms) is int and wall_time_ms >= 0), "wall_time_ms must be >= 0 when supplied")

    proof_input = dict(proof_observations or {})
    acceptance_input = dict(acceptance_observations or {})

    required_proof = list(case.get("required_proof", []))
    _expect(all(level in PROOF_LEVELS for level in required_proof), "case contains invalid proof levels")
    proof: list[dict[str, Any]] = []
    for level in PROOF_LEVELS:
        if level not in required_proof:
            continue
        status, refs, detail = _coerce_observation(proof_input.get(level))
        proof.append(make_outcome(level, status, required=True, evidence=refs, detail=detail))

    acceptance: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for check in case.get("acceptance", []):
        check_id = str(check["id"])
        status, refs, detail = _coerce_observation(acceptance_input.get(check_id))
        outcome = make_outcome(
            check_id,
            status,
            required=bool(check.get("required", True)),
            evidence=refs,
            detail=detail,
        )
        acceptance.append(outcome)
        if check.get("kind") == "invariant":
            regressions.append(dict(outcome))

    proof_state = _proof_status(proof)
    combined = [*proof, *acceptance]
    status = _required_status(combined)
    if any(item["required"] and item["status"] == "FAIL" for item in regressions):
        status = "FAIL"

    normalized_environment = {
        str(key): value
        for key, value in sorted((environment or {}).items(), key=lambda pair: str(pair[0]))
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(run_id),
        "case_id": case_id,
        "case_digest": case_digest,
        "candidate": {
            "id": str(candidate_id),
            "revision": None if candidate_revision is None else str(candidate_revision),
            "digest": None if candidate_digest is None else str(candidate_digest),
        },
        "status": status,
        "proof_status": proof_state,
        "proof": proof,
        "acceptance": acceptance,
        "regressions": regressions,
        "metrics": {
            "repair_cycles": repair_cycles,
            "tokens": tokens,
            "wall_time_ms": wall_time_ms,
        },
        "failure_signatures": _failure_signatures(proof, acceptance, regressions, failure_signatures),
        "evidence": _normalize_evidence(evidence),
        "environment": normalized_environment,
    }
    return result


def result_json(result: Mapping[str, Any], *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(dict(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return json.dumps(dict(result), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
