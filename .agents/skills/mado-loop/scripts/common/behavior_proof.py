"""P3 deterministic behavior proof from Godot scenario evidence."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, Mapping

from .godot_tool import run_godot_tool
from .result import elapsed_ms, make_check, make_result


def run_p3_behavior(
    *, godot_bin: str | Path, project_path: str | Path,
    scenario_path: str | Path, timeout: float = 60.0,
) -> dict[str, Any]:
    """Require a clean, assertion-backed state transition scenario."""
    started = monotonic()
    scenario = Path(scenario_path)
    result = run_godot_tool(
        "scenario", godot_bin=godot_bin, project_path=project_path,
        scenario_path=scenario, timeout=timeout,
    )
    source_checks = result.get("checks", ())
    evidence = source_checks[0].get("evidence", ()) if isinstance(source_checks, list) and source_checks else ()
    payload = evidence[0] if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping) else None
    status = str(result["status"])
    unknowns: list[str] = []
    errors: list[str] = []
    if payload is None or status not in {"PASS", "FAIL"}:
        status = "UNKNOWN"
        unknowns.append("P3 scenario evidence is missing or incomplete.")
    else:
        assertions = payload.get("assertions", ())
        logs = payload.get("log_assertions", ())
        if not isinstance(assertions, list) or not assertions or not isinstance(logs, list) or not logs:
            status = "UNKNOWN"
            unknowns.append("P3 requires both property and log assertions.")
        elif any(item.get("passed") is not True for item in assertions + logs if isinstance(item, Mapping)):
            status = "FAIL"
            errors.append("Deterministic behavior assertion failed.")
    check = make_check(
        "godot.p3.behavior", status, message=f"Deterministic behavior scenario: {scenario}",
        evidence=[payload or result],
        details={"project_path": str(Path(project_path)), "scenario_path": str(scenario)},
    )
    return make_result(
        "behavior_proof", proof_level="P3", task_domains=["GAMEPLAY", "PLAYTEST"],
        summary="P3 deterministic behavior scenario completed.", checks=[check],
        errors=errors, unknowns=unknowns,
        environment={"project_path": str(Path(project_path)), "scenario_path": str(scenario)},
        duration_ms=elapsed_ms(started),
    )
