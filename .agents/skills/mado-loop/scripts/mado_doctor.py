"""Discover bounded local capabilities required by MADO LOOP."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import (  # noqa: E402
    EXIT_INTERNAL, EXIT_USAGE_CONFIG, elapsed_ms, exit_code_for_status,
    make_check, make_result, result_json,
)

COMMON_WINDOWS_GODOT_PATHS = (
    Path(r"C:\Program Files\Godot\Godot.exe"),
    Path(r"C:\Program Files\Godot Engine\Godot.exe"),
    Path(r"C:\Godot\Godot.exe"),
)
VERSION_RE = re.compile(r"(?P<version>\d+\.\d+(?:\.\d+)?(?:\.[A-Za-z0-9_-]+)?)")


def _candidate(explicit: str | None) -> tuple[str | None, str]:
    if explicit:
        return explicit, "explicit"
    found = shutil.which("godot") or shutil.which("godot4")
    if found:
        return found, "PATH"
    for path in COMMON_WINDOWS_GODOT_PATHS:
        if path.is_file():
            return str(path), "common_windows_path"
    return None, "not_found"


def _verify(executable: str, timeout: float) -> tuple[str, str | None, str]:
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "UNKNOWN", None, type(exc).__name__
    output = (completed.stdout or completed.stderr).strip()
    match = VERSION_RE.search(output)
    if completed.returncode != 0 or not match:
        return "UNKNOWN", None, output[:200] or f"exit {completed.returncode}"
    return "PASS", match.group("version"), output[:200]


def diagnose(
    *, godot: str | None = None, timeout: float = 3.0,
    declarations: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Inspect a fixed capability set; never scans disks, mutates, or installs."""
    started = monotonic()
    checks = []
    unknowns = []
    warnings = []
    candidate, source = _candidate(godot)
    if candidate is None:
        message = "Godot was not found by explicit argument, PATH, or documented common paths."
        checks.append(make_check("dependency.godot", "SKIPPED", required=True, message=message))
        unknowns.append({"id": "dependency.godot_missing", "message": message})
        godot_version = None
    else:
        status, godot_version, evidence = _verify(candidate, timeout)
        message = "Godot executable verified." if status == "PASS" else "Godot candidate could not be verified."
        checks.append(make_check("dependency.godot", status, required=True, message=message,
                                 evidence=[evidence], details={"path": candidate, "source": source, "version": godot_version}))
        if status != "PASS":
            unknowns.append({"id": "dependency.godot_unverified", "message": message, "path": candidate})

    python_ok = sys.version_info >= (3, 10)
    checks.append(make_check("dependency.python", "PASS" if python_ok else "FAIL", required=True,
                             message="Python 3.10+ is available." if python_ok else "Python 3.10+ is required.",
                             details={"version": ".".join(map(str, sys.version_info[:3]))}))
    for name, available in (
        ("ffmpeg", shutil.which("ffmpeg") is not None),
        ("pillow", importlib.util.find_spec("PIL") is not None),
        ("numpy", importlib.util.find_spec("numpy") is not None),
    ):
        status = "PASS" if available else "SKIPPED"
        checks.append(make_check(f"optional.{name}", status, required=False,
                                 message=f"Optional {name} capability {'is available' if available else 'is not installed'}."))
        if not available:
            warnings.append({"id": f"optional.{name}_missing", "message": f"Optional {name} capability is unavailable."})

    for name, value in sorted((declarations or {}).items()):
        available = bool(value) and Path(value).exists()
        checks.append(make_check(f"routed.{name}", "PASS" if available else "SKIPPED", required=False,
                                 message=f"Declared routed capability {name} {'is available' if available else 'is unavailable'}.",
                                 details={"declaration": value}))
        if not available:
            warnings.append({"id": f"routed.{name}_unavailable", "message": f"Declared capability {name} is unavailable."})

    result = make_result(
        "mado_doctor", proof_level="P0", task_domains=["CODE"],
        summary="Local capability discovery completed.", checks=checks,
        warnings=warnings, unknowns=unknowns,
        environment={"godot_path": candidate, "godot_source": source, "godot_version": godot_version,
                     "platform": sys.platform, "timeout_seconds": timeout},
        duration_ms=elapsed_ms(started),
    )
    return result


def human_output(payload: Mapping[str, object]) -> str:
    lines = [f"MADO Doctor: {payload['status']}", str(payload["summary"])]
    for check in payload["checks"]:  # type: ignore[union-attr]
        lines.append(f"[{check['status']}] {check['id']}: {check['message']}")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", help="explicit Godot executable path")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--declare", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        if not 0 < args.timeout <= 30:
            raise ValueError("timeout must be greater than 0 and at most 30 seconds")
        declarations = {}
        for item in args.declare:
            name, separator, value = item.partition("=")
            if not separator or not name or not value:
                raise ValueError("declarations must use NAME=PATH")
            declarations[name] = value
        payload = diagnose(godot=args.godot, timeout=args.timeout, declarations=declarations)
        if args.human:
            sys.stdout.write(human_output(payload))
        elif args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(result_json(payload))
        return exit_code_for_status(str(payload["status"]))
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    except ValueError as exc:
        sys.stderr.write(f"mado_doctor configuration error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"mado_doctor internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
