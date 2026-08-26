"""Create a deterministic duration-sampled video proof sheet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import monotonic
from typing import Callable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import (  # noqa: E402
    EXIT_INTERNAL,
    EXIT_USAGE_CONFIG,
    elapsed_ms,
    exit_code_for_status,
    make_artifact,
    make_check,
    make_result,
    result_json,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_timestamps(duration: float, count: int) -> list[float]:
    """Return stable sample midpoints spanning a positive duration."""
    if duration <= 0 or count <= 0:
        raise ValueError("duration and count must be positive")
    return [duration * (index + 0.5) / count for index in range(count)]


def _run(command: list[str], *, timeout: float, runner: Runner) -> subprocess.CompletedProcess[str]:
    return runner(command, capture_output=True, text=True, timeout=timeout, check=False)


def make_proof_sheet(
    source: str | Path,
    output: str | Path,
    *,
    count: int = 12,
    columns: int = 4,
    width: int = 320,
    height: int = 180,
    timeout: float = 30.0,
    ffprobe: str | None = None,
    ffmpeg: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    started = monotonic()
    source_path = Path(source)
    output_path = Path(output)
    environment = {"count": count, "columns": columns, "frame_height": height, "frame_width": width}
    if count <= 0 or columns <= 0 or width <= 0 or height <= 0 or timeout <= 0:
        raise ValueError("count, columns, dimensions, and timeout must be positive")
    if not source_path.is_file():
        return make_result(
            "make_proof_sheet", proof_level="P4", task_domains=["PLAYTEST"],
            summary="Proof sheet input is not a readable file.",
            checks=[make_check("proof_sheet.input", "FAIL", message="Source file does not exist.")],
            errors=[{"id": "input.missing", "path": str(source_path)}], environment=environment,
            duration_ms=elapsed_ms(started),
        )

    probe_exe = ffprobe or shutil.which("ffprobe")
    ffmpeg_exe = ffmpeg or shutil.which("ffmpeg")
    missing = [name for name, value in (("ffprobe", probe_exe), ("ffmpeg", ffmpeg_exe)) if not value]
    if missing:
        unknown = {"id": "dependency.missing", "tools": missing}
        return make_result(
            "make_proof_sheet", proof_level="P4", task_domains=["PLAYTEST"],
            summary="Required media tools are unavailable.",
            checks=[make_check("proof_sheet.tools", "UNKNOWN", message="Required executable was not found.")],
            unknowns=[unknown], environment=environment, duration_ms=elapsed_ms(started),
        )

    before = _sha256(source_path)
    probe_command = [str(probe_exe), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source_path)]
    try:
        probed = _run(probe_command, timeout=timeout, runner=runner)
    except subprocess.TimeoutExpired:
        return _failed("ffprobe timed out.", "probe.timeout", source_path, output_path, before, environment, started)
    except OSError as exc:
        return _unknown_tool(str(exc), source_path, output_path, before, environment, started)
    try:
        duration = float(json.loads(probed.stdout)["format"]["duration"])
        if probed.returncode != 0 or duration <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _failed("ffprobe could not measure a positive duration.", "probe.invalid", source_path, output_path, before, environment, started)

    timestamps = sample_timestamps(duration, count)
    rows = (count + columns - 1) // columns
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".mado-proof-", dir=str(output_path.parent)) as temporary:
            stage = Path(temporary)
            for index, timestamp in enumerate(timestamps):
                frame = stage / f"frame-{index:03d}.png"
                command = [
                    str(ffmpeg_exe), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{timestamp:.6f}", "-i", str(source_path), "-frames:v", "1",
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                    str(frame),
                ]
                completed = _run(command, timeout=timeout, runner=runner)
                if completed.returncode != 0 or not frame.is_file():
                    return _failed("ffmpeg failed while extracting a sample.", "extract.failed", source_path, output_path, before, environment, started)

            staged_output = stage / ("proof-sheet" + (output_path.suffix or ".png"))
            tile = f"tile={columns}x{rows}:nb_frames={count}:padding=0:margin=0"
            assemble = [
                str(ffmpeg_exe), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", "1", "-i", str(stage / "frame-%03d.png"), "-vf", tile,
                "-frames:v", "1", str(staged_output),
            ]
            completed = _run(assemble, timeout=timeout, runner=runner)
            if completed.returncode != 0 or not staged_output.is_file():
                return _failed("ffmpeg failed while assembling the proof sheet.", "assemble.failed", source_path, output_path, before, environment, started)
            if _sha256(source_path) != before:
                return _failed("Source changed while the proof sheet was generated.", "source.changed", source_path, output_path, before, environment, started)
            os.replace(staged_output, output_path)
    except subprocess.TimeoutExpired:
        return _failed("ffmpeg timed out.", "ffmpeg.timeout", source_path, output_path, before, environment, started)
    except OSError as exc:
        return _failed(f"Proof sheet file operation failed: {exc}", "io.failed", source_path, output_path, before, environment, started)

    check = make_check(
        "proof_sheet.generated", "PASS", message="Duration-sampled proof sheet generated.",
        evidence=[str(output_path)], details={"duration_seconds": duration, "rows": rows, "timestamps": [round(value, 6) for value in timestamps]},
    )
    environment["source_sha256"] = before
    return make_result(
        "make_proof_sheet", proof_level="P4", task_domains=["PLAYTEST"],
        summary=f"Generated {count} duration-based samples in a {columns}x{rows} grid.",
        checks=[check], artifacts=[make_artifact(output_path, "proof_sheet")], environment=environment,
        duration_ms=elapsed_ms(started),
    )


def _failed(message: str, error_id: str, source: Path, output: Path, before: str, environment: dict[str, object], started: float) -> dict[str, object]:
    unchanged = source.is_file() and _sha256(source) == before
    return make_result(
        "make_proof_sheet", proof_level="P4", task_domains=["PLAYTEST"], summary=message,
        checks=[make_check("proof_sheet.generation", "FAIL", message=message, details={"source_unchanged": unchanged})],
        errors=[{"id": error_id, "message": message}], artifacts=[make_artifact(output, "proof_sheet")],
        environment=environment, duration_ms=elapsed_ms(started),
    )


def _unknown_tool(message: str, source: Path, output: Path, before: str, environment: dict[str, object], started: float) -> dict[str, object]:
    unknown = {"id": "dependency.unusable", "message": message}
    return make_result(
        "make_proof_sheet", proof_level="P4", task_domains=["PLAYTEST"], summary="Required media tool could not be executed.",
        checks=[make_check("proof_sheet.tools", "UNKNOWN", message=message)], unknowns=[unknown],
        artifacts=[make_artifact(output, "proof_sheet")], environment=environment, duration_ms=elapsed_ms(started),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--ffprobe")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        payload = make_proof_sheet(
            args.source, args.output, count=args.count, columns=args.columns, width=args.width,
            height=args.height, timeout=args.timeout, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg,
        )
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n" if args.pretty else result_json(payload))
        return exit_code_for_status(str(payload["status"]))
    except ValueError as exc:
        sys.stderr.write(f"make_proof_sheet configuration error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"make_proof_sheet internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
