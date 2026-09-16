"""Run one MADO EVALS case through a small allowlisted adapter set."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.behavior_proof import run_p3_behavior  # noqa: E402
from common.layout_proof import run_p2_layout  # noqa: E402
from common.result import EXIT_INTERNAL, EXIT_USAGE_CONFIG  # noqa: E402
from eval_result import build_eval_result, result_json  # noqa: E402
from select_skills import route_task  # noqa: E402
from validate_eval_case import load_and_digest_case  # noqa: E402

RUNNER_SCHEMA_VERSION = "0.1"
ADAPTERS = ("skill_router", "godot_layout", "godot_behavior", "external_receipt")
DEFAULT_OUTPUT_ROOT = Path(".mado-loop") / "evals" / "runs"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return {
        "kind": "report",
        "path": path.name if path.parent.name == "evidence" else path.as_posix(),
        "sha256": _sha256(path),
    }


def _eval_status(value: Any) -> str:
    status = str(value)
    if status in {"PASS", "WARN", "UNKNOWN", "FAIL"}:
        return status
    if status == "SKIPPED":
        return "UNKNOWN"
    return "UNKNOWN"


def _canonical_string_list(value: Any, *, label: str, pattern: re.Pattern[str] | None = None) -> list[str]:
    _expect(isinstance(value, list), f"{label} must be an array")
    output = [str(item) for item in value]
    _expect(len(output) == len(set(output)), f"{label} must not contain duplicates")
    if pattern is not None:
        _expect(all(pattern.fullmatch(item) for item in output), f"{label} contains invalid ids")
    return sorted(output)


def _validate_runner_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    _expect(set(payload) == {"schema_version", "adapter", "config"}, "runner.json must contain schema_version, adapter, and config only")
    _expect(payload.get("schema_version") == RUNNER_SCHEMA_VERSION, "unsupported runner schema_version")
    adapter = str(payload.get("adapter", ""))
    _expect(adapter in ADAPTERS, f"unsupported eval adapter: {adapter!r}")
    raw = payload.get("config")
    _expect(isinstance(raw, dict), "runner config must be an object")

    if adapter == "skill_router":
        allowed = {"available", "expected_recommended", "forbidden_recommended", "include_manual"}
        _expect(not set(raw).difference(allowed), "skill_router config contains unknown keys")
        expected = _canonical_string_list(raw.get("expected_recommended", []), label="expected_recommended", pattern=SKILL_ID_RE)
        forbidden = _canonical_string_list(raw.get("forbidden_recommended", []), label="forbidden_recommended", pattern=SKILL_ID_RE)
        available_raw = raw.get("available")
        available = None if available_raw is None else _canonical_string_list(available_raw, label="available", pattern=SKILL_ID_RE)
        _expect(not set(expected).intersection(forbidden), "expected and forbidden skills overlap")
        include_manual = raw.get("include_manual", False)
        _expect(type(include_manual) is bool, "include_manual must be boolean")
        return {
            "schema_version": RUNNER_SCHEMA_VERSION,
            "adapter": adapter,
            "config": {
                "available": available,
                "expected_recommended": expected,
                "forbidden_recommended": forbidden,
                "include_manual": include_manual,
            },
        }

    if adapter == "godot_layout":
        allowed = {"scenarios", "repeat"}
        _expect(not set(raw).difference(allowed), "godot_layout config contains unknown keys")
        scenarios = _canonical_string_list(raw.get("scenarios", []), label="scenarios")
        _expect(bool(scenarios), "godot_layout requires at least one scenario")
        _expect(all(not Path(item).is_absolute() and ".." not in Path(item).parts for item in scenarios), "scenario paths must be contained")
        repeat = raw.get("repeat", 1)
        _expect(type(repeat) is int and 1 <= repeat <= 3, "repeat must be 1..3")
        return {"schema_version": RUNNER_SCHEMA_VERSION, "adapter": adapter, "config": {"scenarios": scenarios, "repeat": repeat}}

    if adapter == "godot_behavior":
        allowed = {"scenario", "repeat"}
        _expect(not set(raw).difference(allowed), "godot_behavior config contains unknown keys")
        scenario = str(raw.get("scenario", ""))
        scenario_path = Path(scenario)
        _expect(bool(scenario) and not scenario_path.is_absolute() and ".." not in scenario_path.parts, "scenario must be a contained relative path")
        repeat = raw.get("repeat", 1)
        _expect(type(repeat) is int and 1 <= repeat <= 3, "repeat must be 1..3")
        return {"schema_version": RUNNER_SCHEMA_VERSION, "adapter": adapter, "config": {"scenario": scenario, "repeat": repeat}}

    allowed = {"required_evidence_kinds"}
    _expect(not set(raw).difference(allowed), "external_receipt config contains unknown keys")
    kinds = _canonical_string_list(raw.get("required_evidence_kinds", []), label="required_evidence_kinds")
    allowed_kinds = {"test", "log", "screenshot", "video", "artifact", "receipt", "report", "other"}
    _expect(not set(kinds).difference(allowed_kinds), "external receipt contains unsupported evidence kind requirement")
    return {"schema_version": RUNNER_SCHEMA_VERSION, "adapter": adapter, "config": {"required_evidence_kinds": kinds}}


def load_runner_config(case_json: str | Path, case_manifest: Mapping[str, Any]) -> dict[str, Any]:
    case_dir = Path(case_json).resolve().parent
    runner_path = case_dir / "runner.json"
    _expect(runner_path.is_file(), "eval case requires runner.json")
    bound_paths = {str(item.get("path", "")) for item in case_manifest.get("files", [])}
    _expect("runner.json" in bound_paths, "runner.json must be listed in expected_paths so it is digest-bound")
    payload = json.loads(runner_path.read_text(encoding="utf-8"))
    _expect(isinstance(payload, dict), "runner.json root must be an object")
    return _validate_runner_config(payload)


def _default_run_id(case_id: str, candidate_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    clean_candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate_id).strip("-") or "candidate"
    clean_candidate = clean_candidate[:32]
    return f"{case_id}:{clean_candidate}:{stamp}"


def _prepare_run_dir(output_root: Path, run_id: str) -> tuple[Path, Path, Path]:
    _expect(bool(RUN_ID_RE.fullmatch(run_id)), "run_id must be a short opaque identifier")
    safe_name = run_id.replace(":", "__").replace("/", "_")
    run_dir = output_root / safe_name
    _expect(not run_dir.exists(), f"run output already exists: {run_dir}")
    evidence_dir = run_dir / "evidence"
    workspace = run_dir / "workspace"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    workspace.mkdir(parents=True, exist_ok=False)
    return run_dir, evidence_dir, workspace


def _materialize_fixture(case_json: Path, case: Mapping[str, Any], workspace: Path) -> Path | None:
    fixture = case.get("fixture")
    if fixture is None:
        return None
    source = (case_json.resolve().parent / str(fixture)).resolve()
    target = workspace / "fixture"
    if source.is_dir():
        shutil.copytree(source, target)
    elif source.is_file():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target / source.name)
    else:
        raise ValueError(f"fixture disappeared before replay: {fixture}")
    return target


def _base_environment(adapter: str) -> dict[str, Any]:
    return {
        "adapter": adapter,
        "platform": platform.system().casefold(),
        "python": platform.python_version(),
    }


def _run_skill_router(
    *,
    task_text: str,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    evidence_dir: Path,
) -> dict[str, Any]:
    kwargs = {
        "available": config.get("available"),
        "include_manual": bool(config.get("include_manual", False)),
    }
    first = route_task(task_text, **kwargs)
    second = route_task(task_text, **kwargs)
    report_path = evidence_dir / "skill-router.json"
    evidence = _write_json(report_path, {"first": first, "second": second})
    evidence["path"] = "evidence/skill-router.json"

    recommended = set(str(item) for item in first.get("recommended_skills", []))
    expected = set(str(item) for item in config.get("expected_recommended", []))
    forbidden = set(str(item) for item in config.get("forbidden_recommended", []))
    missing = sorted(expected.difference(recommended))
    unexpected = sorted(forbidden.intersection(recommended))
    repeatable = first == second

    observations: dict[str, Any] = {}
    for check in case.get("acceptance", []):
        check_id = str(check.get("id", ""))
        if check_id == "routing.expected-skills":
            observations[check_id] = {
                "status": "PASS" if not missing else "FAIL",
                "evidence": ["evidence/skill-router.json"],
                "detail": "all expected skills selected" if not missing else f"missing={','.join(missing)}",
            }
        elif check_id == "routing.no-unrelated-skills":
            observations[check_id] = {
                "status": "PASS" if not unexpected else "FAIL",
                "evidence": ["evidence/skill-router.json"],
                "detail": "no forbidden skill selected" if not unexpected else f"unexpected={','.join(unexpected)}",
            }
        elif check_id == "routing.repeatable":
            observations[check_id] = {
                "status": "PASS" if repeatable else "FAIL",
                "evidence": ["evidence/skill-router.json"],
                "detail": "two identical deterministic routes" if repeatable else "route payload changed between identical calls",
            }

    return {
        "proof_observations": {},
        "acceptance_observations": observations,
        "evidence": [evidence],
        "failure_signatures": [],
        "environment": _base_environment("skill_router"),
    }


def _resolve_godot(godot: str | Path | None) -> Path:
    configured = str(godot or os.environ.get("MADO_GODOT_BIN", "")).strip()
    _expect(bool(configured), "Godot adapter requires --godot or MADO_GODOT_BIN")
    path = Path(configured).resolve()
    _expect(path.is_file(), f"Godot executable is not a file: {path}")
    return path


def _run_godot_layout(
    *,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    fixture: Path | None,
    evidence_dir: Path,
    godot: str | Path | None,
) -> dict[str, Any]:
    _expect(fixture is not None and fixture.is_dir(), "godot_layout requires a directory fixture")
    godot_bin = _resolve_godot(godot)
    scenarios = [fixture / str(item) for item in config.get("scenarios", [])]
    _expect(all(path.is_file() for path in scenarios), "one or more layout scenarios are missing")
    results = [
        run_p2_layout(godot_bin=godot_bin, project_path=fixture, scenario_paths=scenarios)
        for _ in range(int(config.get("repeat", 1)))
    ]
    report_path = evidence_dir / "godot-layout.json"
    evidence = _write_json(report_path, {"runs": results})
    evidence["path"] = "evidence/godot-layout.json"
    statuses = [_eval_status(item.get("status")) for item in results]
    combined = "PASS" if all(item == "PASS" for item in statuses) else ("FAIL" if any(item == "FAIL" for item in statuses) else "UNKNOWN")
    stable = all(item == results[0] for item in results[1:]) if len(results) > 1 else True

    observations: dict[str, Any] = {}
    for check in case.get("acceptance", []):
        check_id = str(check.get("id", ""))
        if check_id in {"ui.layout.two-viewports", "ui.no-overlap"}:
            observations[check_id] = {"status": combined, "evidence": ["evidence/godot-layout.json"]}
        elif check_id == "ui.layout.repeatable":
            observations[check_id] = {"status": "PASS" if stable else "FAIL", "evidence": ["evidence/godot-layout.json"]}

    return {
        "proof_observations": {"P2": {"status": combined, "evidence": ["evidence/godot-layout.json"]}},
        "acceptance_observations": observations,
        "evidence": [evidence],
        "failure_signatures": [],
        "environment": {**_base_environment("godot_layout"), "godot": godot_bin.name},
    }


def _run_godot_behavior(
    *,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    fixture: Path | None,
    evidence_dir: Path,
    godot: str | Path | None,
) -> dict[str, Any]:
    _expect(fixture is not None and fixture.is_dir(), "godot_behavior requires a directory fixture")
    godot_bin = _resolve_godot(godot)
    scenario = fixture / str(config.get("scenario", ""))
    _expect(scenario.is_file(), "behavior scenario is missing")
    results = [
        run_p3_behavior(godot_bin=godot_bin, project_path=fixture, scenario_path=scenario)
        for _ in range(int(config.get("repeat", 1)))
    ]
    report_path = evidence_dir / "godot-behavior.json"
    evidence = _write_json(report_path, {"runs": results})
    evidence["path"] = "evidence/godot-behavior.json"
    statuses = [_eval_status(item.get("status")) for item in results]
    combined = "PASS" if all(item == "PASS" for item in statuses) else ("FAIL" if any(item == "FAIL" for item in statuses) else "UNKNOWN")
    stable = all(item == results[0] for item in results[1:]) if len(results) > 1 else True

    observations: dict[str, Any] = {}
    for check in case.get("acceptance", []):
        check_id = str(check.get("id", ""))
        if check_id == "gameplay.transition-pass":
            observations[check_id] = {"status": combined, "evidence": ["evidence/godot-behavior.json"]}
        elif check_id == "gameplay.repeatable":
            observations[check_id] = {"status": "PASS" if stable else "FAIL", "evidence": ["evidence/godot-behavior.json"]}

    return {
        "proof_observations": {"P3": {"status": combined, "evidence": ["evidence/godot-behavior.json"]}},
        "acceptance_observations": observations,
        "evidence": [evidence],
        "failure_signatures": [],
        "environment": {**_base_environment("godot_behavior"), "godot": godot_bin.name},
    }


def _run_external_receipt(
    *,
    case_manifest: Mapping[str, Any],
    config: Mapping[str, Any],
    evidence_dir: Path,
    receipt: str | Path | None,
) -> dict[str, Any]:
    _expect(receipt is not None, "external_receipt adapter requires --receipt")
    source = Path(receipt).resolve()
    _expect(source.is_file(), f"external receipt is not a file: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    _expect(isinstance(payload, dict), "external receipt root must be an object")
    if payload.get("case_id") is not None:
        _expect(str(payload["case_id"]) == str(case_manifest["case_id"]), "external receipt case_id mismatch")
    if payload.get("case_digest") is not None:
        _expect(str(payload["case_digest"]) == str(case_manifest["case_digest"]), "external receipt case_digest mismatch")

    proof = payload.get("proof_observations", {})
    acceptance = payload.get("acceptance_observations", {})
    evidence = payload.get("evidence", [])
    _expect(isinstance(proof, dict) and isinstance(acceptance, dict), "external observations must be objects")
    _expect(isinstance(evidence, list), "external evidence must be an array")
    present_kinds = {str(item.get("kind", "")) for item in evidence if isinstance(item, dict)}
    missing_kinds = sorted(set(config.get("required_evidence_kinds", [])).difference(present_kinds))
    _expect(not missing_kinds, f"external receipt missing required evidence kinds: {missing_kinds}")

    copied = evidence_dir / "external-receipt.json"
    shutil.copy2(source, copied)
    receipt_evidence = {"kind": "receipt", "path": "evidence/external-receipt.json", "sha256": _sha256(copied)}
    metrics = payload.get("metrics", {})
    _expect(isinstance(metrics, dict), "external metrics must be an object")
    environment = payload.get("environment", {})
    _expect(isinstance(environment, dict), "external environment must be an object")
    signatures = payload.get("failure_signatures", [])
    _expect(isinstance(signatures, list), "external failure_signatures must be an array")

    return {
        "proof_observations": proof,
        "acceptance_observations": acceptance,
        "repair_cycles": metrics.get("repair_cycles", 0),
        "tokens": metrics.get("tokens"),
        "wall_time_ms": metrics.get("wall_time_ms"),
        "evidence": [*evidence, receipt_evidence],
        "failure_signatures": signatures,
        "environment": {**_base_environment("external_receipt"), **environment},
    }


def run_eval_case(
    case_json: str | Path,
    *,
    candidate_id: str,
    candidate_revision: str | None = None,
    candidate_digest: str | None = None,
    run_id: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    godot: str | Path | None = None,
    receipt: str | Path | None = None,
) -> tuple[dict[str, Any], Path]:
    """Replay one case, preserving runner failures as UNKNOWN rather than product FAIL."""
    started = time.monotonic()
    case_path = Path(case_json).resolve()
    case_manifest = load_and_digest_case(case_path)
    runner = load_runner_config(case_path, case_manifest)
    case = case_manifest["case"]
    actual_run_id = run_id or _default_run_id(str(case_manifest["case_id"]), candidate_id)
    run_dir, evidence_dir, workspace = _prepare_run_dir(Path(output_root), actual_run_id)
    fixture = _materialize_fixture(case_path, case, workspace)
    task_text = (case_path.parent / str(case["task_file"])).read_text(encoding="utf-8")

    run_manifest = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_id": actual_run_id,
        "case_id": case_manifest["case_id"],
        "case_digest": case_manifest["case_digest"],
        "candidate": {"id": candidate_id, "revision": candidate_revision, "digest": candidate_digest},
        "adapter": runner["adapter"],
        "input_files": case_manifest["files"],
    }
    (run_dir / "manifest.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    adapter = str(runner["adapter"])
    config = runner["config"]
    try:
        if adapter == "skill_router":
            observed = _run_skill_router(task_text=task_text, case=case, config=config, evidence_dir=evidence_dir)
        elif adapter == "godot_layout":
            observed = _run_godot_layout(case=case, config=config, fixture=fixture, evidence_dir=evidence_dir, godot=godot)
        elif adapter == "godot_behavior":
            observed = _run_godot_behavior(case=case, config=config, fixture=fixture, evidence_dir=evidence_dir, godot=godot)
        else:
            observed = _run_external_receipt(case_manifest=case_manifest, config=config, evidence_dir=evidence_dir, receipt=receipt)
    except Exception as exc:
        error_path = evidence_dir / "runner-error.json"
        error_evidence = _write_json(error_path, {"adapter": adapter, "error_type": type(exc).__name__, "message": str(exc)[:1000]})
        error_evidence["path"] = "evidence/runner-error.json"
        observed = {
            "proof_observations": {},
            "acceptance_observations": {},
            "repair_cycles": 0,
            "tokens": None,
            "evidence": [error_evidence],
            "failure_signatures": [f"runner:{adapter}:ERROR"],
            "environment": _base_environment(adapter),
        }

    measured_ms = max(0, round((time.monotonic() - started) * 1000))
    result = build_eval_result(
        run_id=actual_run_id,
        case_manifest=case_manifest,
        candidate_id=candidate_id,
        candidate_revision=candidate_revision,
        candidate_digest=candidate_digest,
        proof_observations=observed.get("proof_observations"),
        acceptance_observations=observed.get("acceptance_observations"),
        repair_cycles=int(observed.get("repair_cycles", 0)),
        tokens=observed.get("tokens"),
        wall_time_ms=observed.get("wall_time_ms", measured_ms),
        evidence=observed.get("evidence", []),
        failure_signatures=observed.get("failure_signatures", []),
        environment=observed.get("environment", {}),
    )
    (run_dir / "result.json").write_text(result_json(result, pretty=True), encoding="utf-8", newline="\n")
    return result, run_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_json", type=Path)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-revision", default=None)
    parser.add_argument("--candidate-digest", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--godot", type=Path, default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        result, run_dir = run_eval_case(
            args.case_json,
            candidate_id=args.candidate_id,
            candidate_revision=args.candidate_revision,
            candidate_digest=args.candidate_digest,
            run_id=args.run_id,
            output_root=args.output_root,
            godot=args.godot,
            receipt=args.receipt,
        )
        payload = {"status": result["status"], "run_id": result["run_id"], "result": str(run_dir / "result.json")}
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {"PASS": 0, "WARN": 0, "FAIL": 1, "UNKNOWN": 2}[str(result["status"])]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"run_eval_case error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"run_eval_case internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
