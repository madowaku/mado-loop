"""Schema-v1.1 adapter for the pinned Godot skill command wrappers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Any, Mapping, Sequence

from .result import elapsed_ms, make_artifact, make_check, make_result

_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "godot-skill" / "payload" / "scripts"
_WRAPPERS = {
    "validate": _VENDOR / "debug" / "validate_project.py",
    "run": _VENDOR / "debug" / "run_project.py",
    "scenario": _VENDOR / "debug" / "run_scenario.py",
    "export": _VENDOR / "export" / "export_project.py",
}
_PROOFS = {"validate": "P0", "run": "P1", "scenario": "P4", "export": "P5"}
_DOMAINS = {
    "validate": ("CODE",),
    "run": ("GAMEPLAY",),
    "scenario": ("GAMEPLAY", "UI", "PLAYTEST"),
    "export": ("RELEASE",),
}


def vendor_wrapper(operation: str) -> Path:
    """Return the pinned wrapper for a supported operation."""
    try:
        return _WRAPPERS[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported Godot operation: {operation!r}") from exc


def _last_json(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _completed(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command, capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace", timeout=timeout,
        stdin=subprocess.DEVNULL, env=environment,
    )


def _unknown(operation: str, started: float, message: str, command: Sequence[str]) -> dict[str, Any]:
    check = make_check("godot.evidence", "UNKNOWN", message=message, evidence=[list(command)])
    return make_result(
        "godot_tool", proof_level=_PROOFS[operation], task_domains=_DOMAINS[operation],
        summary=message, checks=[check], unknowns=[message],
        environment={"operation": operation}, duration_ms=elapsed_ms(started),
    )


def _payload_findings(operation: str, payload: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Return measured failures and warnings from a wrapper payload."""
    failures: list[str] = []
    warnings: list[str] = []
    if payload.get("ok") is not True:
        failures.append("wrapper reported ok=false")
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        failures.append(f"Godot payload reported exit_code={exit_code}")
    counts = payload.get("counts")
    if isinstance(counts, Mapping):
        if int(counts.get("errors", 0) or 0) or int(counts.get("parse_errors", 0) or 0):
            failures.append("Godot diagnostics contain errors")
        if int(counts.get("warnings", 0) or 0):
            warnings.append("Godot diagnostics contain warnings")
    static = payload.get("static")
    if operation == "validate" and isinstance(static, Mapping) and int(static.get("failed_count", 0) or 0):
        failures.append("static validation contains failures")
    if operation == "scenario":
        for key in ("assertions", "log_assertions", "performance_assertions"):
            values = payload.get(key, ())
            if isinstance(values, list) and any(item.get("passed") is not True for item in values if isinstance(item, Mapping)):
                failures.append(f"{key} contains failed assertions")
        if payload.get("errors"):
            failures.append("scenario reported errors")
    return sorted(set(failures)), sorted(set(warnings))


def run_godot_tool(
    operation: str,
    *,
    godot_bin: str | Path,
    project_path: str | Path,
    scenario_path: str | Path | None = None,
    output_path: str | Path | None = None,
    preset_name: str | None = None,
    mode: str = "release",
    timeout: float = 120.0,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Run one pinned wrapper and translate its evidence into the common result."""
    if timeout <= 0 or timeout > 600:
        raise ValueError("timeout must be greater than zero and at most 600 seconds")
    if not str(godot_bin) or not str(project_path):
        raise ValueError("godot_bin and project_path must be explicit")
    wrapper = vendor_wrapper(operation)
    started = monotonic()
    command = [sys.executable, "-B", str(wrapper), str(Path(project_path)), "--godot-bin", str(godot_bin)]
    if operation == "scenario":
        if scenario_path is None:
            raise ValueError("scenario_path is required for scenario")
        command.insert(4, str(Path(scenario_path)))
    elif operation == "export":
        if not preset_name or output_path is None:
            raise ValueError("preset_name and output_path are required for export")
        command = [sys.executable, "-B", str(wrapper), str(Path(project_path)), preset_name, str(Path(output_path)),
                   "--mode", mode, "--godot-bin", str(godot_bin)]
    command.extend(["--timeout", str(timeout)] if operation != "export" else [])
    command.extend(str(value) for value in extra_args)

    try:
        if operation == "export":
            preflight_command = command + ["--preflight-only"]
            preflight_run = _completed(preflight_command, timeout)
            preflight = _last_json(preflight_run.stdout)
            if preflight is None:
                return _unknown(operation, started, "Export preflight emitted malformed or missing JSON.", preflight_command)
            if preflight_run.returncode != 0:
                message = f"Export preflight wrapper exited with code {preflight_run.returncode}."
                check = make_check("godot.export", "FAIL", message=message, evidence=[preflight])
                return make_result(
                    "godot_tool", proof_level="P5", task_domains=["RELEASE"], summary=message,
                    checks=[check], errors=[message], environment={"operation": operation},
                    duration_ms=elapsed_ms(started),
                )
            preflight_exit = preflight.get("exit_code")
            if isinstance(preflight_exit, int) and preflight_exit != 0:
                message = f"Export preflight payload reported exit_code={preflight_exit}."
                check = make_check("godot.export", "FAIL", message=message, evidence=[preflight])
                return make_result(
                    "godot_tool", proof_level="P5", task_domains=["RELEASE"], summary=message,
                    checks=[check], errors=[message], environment={"operation": operation},
                    duration_ms=elapsed_ms(started),
                )
            report = preflight.get("preflight")
            if not isinstance(report, Mapping):
                return _unknown(operation, started, "Export preflight evidence is incomplete.", preflight_command)
            if report.get("ok") is not True:
                failures = list(report.get("errors") or ["export preflight failed"])
                check = make_check("godot.export", "FAIL", message="; ".join(map(str, failures)), evidence=[preflight])
                return make_result(
                    "godot_tool", proof_level="P5", task_domains=["RELEASE"], summary="Export preflight failed.",
                    checks=[check], errors=failures, environment={"operation": operation}, duration_ms=elapsed_ms(started),
                )
            preflight_warnings = [str(value) for value in report.get("warnings", ())]
            ignored_pack_warning = "Matching Godot export templates were not found (not required for pack/patch data exports)"
            if mode in {"pack", "patch"}:
                # The pinned wrapper emits this exact informational message when templates
                # are irrelevant to a data-only export. No other warning is normalized.
                preflight_warnings = [value for value in preflight_warnings if value != ignored_pack_warning]
            completed = _completed(command, timeout)
            artifact = make_artifact(Path(output_path), "godot-export")
            failed = completed.returncode != 0 or not artifact["exists"] or not artifact["size_bytes"]
            payload = _last_json(completed.stdout)
            payload_exit = payload.get("exit_code") if isinstance(payload, Mapping) else None
            if isinstance(payload_exit, int) and payload_exit != 0:
                failed = True
            status = "FAIL" if failed else ("WARN" if preflight_warnings else "PASS")
            message = ("Export failed or produced no artifact." if failed else
                       (preflight_warnings[0] if preflight_warnings else "Export produced a verified artifact."))
            check = make_check("godot.export", status, message=message,
                               evidence=[preflight, {"returncode": completed.returncode}, artifact])
            return make_result(
                "godot_tool", proof_level="P5", task_domains=["RELEASE"], summary=message, checks=[check],
                errors=[message] if failed else [], warnings=preflight_warnings, artifacts=[artifact], environment={"operation": operation},
                duration_ms=elapsed_ms(started),
            )
        completed = _completed(command, timeout)
    except (FileNotFoundError, PermissionError) as exc:
        return _unknown(operation, started, f"Required executable or wrapper is unavailable: {exc}", command)
    except subprocess.TimeoutExpired:
        return _unknown(operation, started, f"Godot wrapper timed out after {timeout:g}s.", command)

    payload = _last_json(completed.stdout)
    if payload is None:
        return _unknown(operation, started, "Godot wrapper emitted malformed or missing JSON.", command)
    if payload.get("timed_out") is True:
        return _unknown(operation, started, "Godot wrapper reported a timeout.", command)
    failures, warnings = _payload_findings(operation, payload)
    if completed.returncode != 0:
        failures.append(f"Godot wrapper exited with code {completed.returncode}")
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    message = failures[0] if failures else (warnings[0] if warnings else "Godot evidence is clean.")
    check = make_check("godot.evidence", status, message=message, evidence=[payload])
    artifacts = []
    if operation == "scenario":
        for value in payload.get("screenshots", ()) if isinstance(payload.get("screenshots", ()), list) else ():
            path = value.get("path") if isinstance(value, Mapping) else value
            if path:
                artifacts.append(make_artifact(str(path), "screenshot"))
        if any(not item["exists"] for item in artifacts):
            missing = "Scenario reported a screenshot that is absent."
            return _unknown(operation, started, missing, command)
    return make_result(
        "godot_tool", proof_level=_PROOFS[operation], task_domains=_DOMAINS[operation], summary=message,
        checks=[check], errors=failures, warnings=warnings, artifacts=artifacts,
        environment={"operation": operation}, duration_ms=elapsed_ms(started),
    )
