"""Compose static (P0) and boot (P1) Godot proof with fail-fast gating."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any, Callable

from .godot_tool import run_godot_tool
from .result import elapsed_ms, make_check, make_result

GodotTool = Callable[..., dict[str, Any]]


def run_p0_p1(
    *,
    godot_bin: str | Path,
    project_path: str | Path,
    validate_timeout: float = 120.0,
    boot_timeout: float = 30.0,
    tool_runner: GodotTool = run_godot_tool,
) -> dict[str, Any]:
    """Validate a project and boot it only after a clean P0 result."""
    if not str(godot_bin) or not str(project_path):
        raise ValueError("godot_bin and project_path must be explicit")
    if validate_timeout <= 0 or boot_timeout <= 0:
        raise ValueError("timeouts must be greater than zero")

    started = monotonic()
    resolved_project = Path(project_path).resolve()
    p0 = tool_runner(
        "validate",
        godot_bin=godot_bin,
        project_path=resolved_project,
        timeout=validate_timeout,
    )
    checks = [
        make_check(
            "godot.p0.validate",
            str(p0["status"]),
            message=str(p0["summary"]),
            evidence=[p0],
            details={"invoked": True, "proof_level": "P0"},
        )
    ]
    errors = list(p0.get("errors", ()))
    warnings = list(p0.get("warnings", ()))
    unknowns = list(p0.get("unknowns", ()))

    if p0["status"] != "PASS":
        checks.append(
            make_check(
                "godot.p1.boot",
                "SKIPPED",
                message="P1 was not invoked because P0 did not pass.",
                evidence=[{"invoked": False, "blocked_by": "godot.p0.validate"}],
                details={"invoked": False, "proof_level": "P1"},
            )
        )
        return make_result(
            "godot_runner",
            proof_level="P1",
            task_domains=["CODE", "GAMEPLAY"],
            summary="P0 did not pass; P1 was not invoked.",
            checks=checks,
            errors=errors,
            warnings=warnings,
            unknowns=unknowns,
            environment={
                "godot_bin": str(Path(godot_bin)),
                "p1_invoked": False,
                "project_path": str(resolved_project),
            },
            duration_ms=elapsed_ms(started),
        )

    p1 = tool_runner(
        "run",
        godot_bin=godot_bin,
        project_path=resolved_project,
        timeout=boot_timeout,
    )
    checks.append(
        make_check(
            "godot.p1.boot",
            str(p1["status"]),
            message=str(p1["summary"]),
            evidence=[p1],
            details={"invoked": True, "proof_level": "P1"},
        )
    )
    errors.extend(p1.get("errors", ()))
    warnings.extend(p1.get("warnings", ()))
    unknowns.extend(p1.get("unknowns", ()))
    clean = p1["status"] == "PASS"
    return make_result(
        "godot_runner",
        proof_level="P1",
        task_domains=["CODE", "GAMEPLAY"],
        summary="P0 and P1 passed." if clean else "P0 passed, but P1 did not pass.",
        checks=checks,
        errors=errors,
        warnings=warnings,
        unknowns=unknowns,
        environment={
            "godot_bin": str(Path(godot_bin)),
            "p1_invoked": True,
            "project_path": str(resolved_project),
        },
        duration_ms=elapsed_ms(started),
    )
