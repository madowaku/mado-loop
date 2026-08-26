"""Bounded subprocess adapter for the immutable sprite-tools processor."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic
from typing import Any, Sequence

from .result import exit_code_for_status, make_artifact, make_check, make_result, result_json


REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
PROCESSOR = (
    REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "vendor" /
    "sprite-tools" / "payload" / "generate2dsprite.py"
)
MINIMUM_DEPENDENCIES = {"Pillow": (10, 0), "numpy": (1, 26)}


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def dependency_unknowns() -> list[str]:
    """Return missing/out-of-range runtime requirements without installing them."""
    unknowns = []
    for distribution, minimum in MINIMUM_DEPENDENCIES.items():
        try:
            installed = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            unknowns.append(f"required dependency missing: {distribution}>={'.'.join(map(str, minimum))}")
            continue
        if _version_tuple(installed) < minimum:
            unknowns.append(
                f"required dependency too old: {distribution} {installed}; "
                f"need >={'.'.join(map(str, minimum))}"
            )
    return unknowns


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_sprite(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    rows: int,
    cols: int,
    cell_size: int = 128,
    align: str = "feet",
    duration_ms: int = 200,
    strict_qc: bool = True,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Split and normalize one sheet using the pinned processing surface only."""
    started = monotonic()
    source = Path(input_path).resolve()
    output = Path(output_dir).resolve()
    unknowns = dependency_unknowns()
    if not PROCESSOR.is_file():
        unknowns.append(f"required vendored processor missing: {PROCESSOR}")
    checks = []
    if not source.is_file():
        checks.append(make_check("source", "FAIL", message=f"input is not a file: {source}"))
    if unknowns or checks:
        return make_result(
            "sprite_processor", proof_level="P1", summary="Sprite processing could not start.",
            task_domains=["SPRITE", "PIXEL_ART"], checks=checks, unknowns=unknowns,
            duration_ms=round((monotonic() - started) * 1000),
        )

    before = _sha256(PROCESSOR)
    command = [
        sys.executable, str(PROCESSOR), "process", "--input", str(source),
        "--target", "asset", "--mode", "sheet", "--output-dir", str(output),
        "--rows", str(rows), "--cols", str(cols), "--cell-size", str(cell_size),
        "--align", align, "--shared-scale", "--scale-strategy", "fit",
        "--duration", str(duration_ms), "--label-prefix", "frame",
    ]
    if strict_qc:
        command.extend(["--strict-qc", "--max-body-scale-cv", "0.10", "--max-anchor-y-std", "0.05"])
    command.extend(str(argument) for argument in extra_args)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    after = _sha256(PROCESSOR)
    checks.append(make_check(
        "vendor_immutable", "PASS" if before == after else "FAIL",
        message="vendored processor bytes unchanged" if before == after else "vendored processor changed",
        evidence=[before, after],
    ))
    if completed.returncode != 0:
        checks.append(make_check(
            "processor", "FAIL", message="vendored processor rejected the sheet",
            details={"returncode": completed.returncode, "stderr": completed.stderr.strip()},
        ))
    else:
        checks.append(make_check("processor", "PASS", message="processor completed"))

    metadata_path = output / "pipeline-meta.json"
    artifacts = [
        make_artifact(metadata_path, "sprite-qc"),
        make_artifact(output / "sheet-transparent.png", "sprite-atlas"),
        make_artifact(output / "animation.gif", "sprite-preview"),
    ]
    if completed.returncode == 0:
        metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected_frames = rows * cols
        checks.extend([
            make_check(
                "frame_split", "PASS" if len(metadata_payload.get("frames", [])) == expected_frames else "FAIL",
                message=f"expected {expected_frames} frames",
            ),
            make_check(
                "shared_anchor", "PASS" if metadata_payload.get("align") == align else "FAIL",
                message=f"shared {align} anchor requested",
            ),
            make_check(
                "shared_scale", "PASS" if metadata_payload.get("shared_scale") is True else "FAIL",
                message="shared scale requested",
            ),
            make_check(
                "qc", "PASS", message="strict deterministic QC passed",
                evidence=[metadata_payload.get("qc_summary", {})],
            ),
        ])
    return make_result(
        "sprite_processor", proof_level="P1",
        summary="Sprite sheet processed." if completed.returncode == 0 else "Sprite processing failed.",
        task_domains=["SPRITE", "PIXEL_ART"], checks=checks, artifacts=artifacts,
        environment={"processor_sha256": before, "python": sys.version.split()[0]},
        duration_ms=round((monotonic() - started) * 1000),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--cols", type=int, required=True)
    parser.add_argument("--cell-size", type=int, default=128)
    parser.add_argument("--align", choices=("center", "bottom", "feet"), default="feet")
    parser.add_argument("--duration-ms", type=int, default=200)
    parser.add_argument("--no-strict-qc", action="store_true")
    args = parser.parse_args(argv)
    result = process_sprite(
        args.input, args.output_dir, rows=args.rows, cols=args.cols,
        cell_size=args.cell_size, align=args.align, duration_ms=args.duration_ms,
        strict_qc=not args.no_strict_qc,
    )
    sys.stdout.write(result_json(result))
    return exit_code_for_status(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
