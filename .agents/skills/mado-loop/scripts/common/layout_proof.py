"""P2 layout proof assembled from deterministic Godot scenario evidence."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping

from .godot_tool import run_godot_tool
from .result import elapsed_ms, make_check, make_result


def _payload(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    checks = result.get("checks", ())
    if not isinstance(checks, list) or not checks:
        return None
    evidence = checks[0].get("evidence", ())
    return evidence[0] if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping) else None


def run_p2_layout(
    *, godot_bin: str | Path, project_path: str | Path,
    scenario_paths: Iterable[str | Path], timeout: float = 60.0,
) -> dict[str, Any]:
    """Run all required viewport scenarios and promote measured UI evidence to P2."""
    started = monotonic()
    checks: list[dict[str, Any]] = []
    unknowns: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    paths = [Path(value) for value in scenario_paths]
    if not paths:
        unknowns.append("No P2 layout scenarios were supplied.")
    for index, scenario in enumerate(paths):
        result = run_godot_tool(
            "scenario", godot_bin=godot_bin, project_path=project_path,
            scenario_path=scenario, timeout=timeout,
        )
        payload = _payload(result)
        check_status = str(result["status"])
        if check_status == "WARN":
            warnings.extend(str(value) for value in result.get("warnings", ()))
        if check_status not in {"PASS", "WARN", "FAIL"} or payload is None:
            check_status = "UNKNOWN"
            unknowns.append(f"Scenario {scenario} did not provide complete UI evidence.")
        reports = payload.get("ui_reports", ()) if payload else ()
        if not isinstance(reports, list) or not reports:
            check_status = "UNKNOWN"
            unknowns.append(f"Scenario {scenario} emitted no ui_report.")
        elif any(report.get("passed") is not True for report in reports if isinstance(report, Mapping)):
            check_status = "FAIL"
            errors.append(f"Measured UI findings failed in {scenario}.")
        checks.append(make_check(
            f"godot.p2.layout.{index + 1}", check_status,
            message=f"Measured layout scenario: {scenario}", evidence=[payload or result],
            details={"project_path": str(Path(project_path)), "scenario_path": str(scenario)},
        ))
    return make_result(
        "layout_proof", proof_level="P2", task_domains=["UI", "PLAYTEST"],
        summary="P2 layout scenarios completed.", checks=checks, errors=errors,
        warnings=warnings, unknowns=unknowns, environment={"project_path": str(Path(project_path)), "scenario_count": len(paths)},
        duration_ms=elapsed_ms(started),
    )
