"""Capture deterministic Godot motion and generate a P4 proof sheet."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from make_proof_sheet import make_proof_sheet

from .result import elapsed_ms, make_artifact, make_check, make_result

Runner = Callable[..., subprocess.CompletedProcess[str]]
SOURCE_SUFFIXES = {".gd", ".godot", ".tscn", ".tres", ".cfg", ".json"}


def _source_hash(project_path: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(project_path.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or ".godot" in path.relative_to(project_path).parts:
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES and path.name != "project.godot":
            continue
        relative = path.relative_to(project_path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _unknown(summary: str, check_id: str, *, started: float, environment: dict[str, Any]) -> dict[str, Any]:
    return make_result(
        "godot_motion_proof", proof_level="P4", task_domains=["ANIMATION", "PLAYTEST"],
        summary=summary,
        checks=[make_check(check_id, "UNKNOWN", message=summary)],
        unknowns=[{"id": check_id, "message": summary}], environment=environment,
        duration_ms=elapsed_ms(started),
    )


def _fail(summary: str, check_id: str, *, started: float, environment: dict[str, Any],
          artifacts: list[dict[str, Any]] | None = None, evidence: list[Any] | None = None) -> dict[str, Any]:
    return make_result(
        "godot_motion_proof", proof_level="P4", task_domains=["ANIMATION", "PLAYTEST"],
        summary=summary,
        checks=[make_check(check_id, "FAIL", message=summary, evidence=evidence)],
        errors=[{"id": check_id, "message": summary}], artifacts=artifacts or (),
        environment=environment, duration_ms=elapsed_ms(started),
    )


def run_p4_motion(
    *, godot_bin: str | Path, project_path: str | Path, output_dir: str | Path,
    fps: int = 12, expected_frames: int = 24, timeout: float = 60.0,
    ffmpeg: str | None = None, ffprobe: str | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Run Godot Movie Maker at a fixed rate, inspect the video, and tile proof frames."""
    if fps <= 0 or expected_frames <= 0 or timeout <= 0 or timeout > 600:
        raise ValueError("fps/expected_frames must be positive and timeout must be in (0, 600]")
    started = monotonic()
    project = Path(project_path).resolve()
    destination = Path(output_dir).resolve()
    godot = Path(godot_bin)
    probe_exe = ffprobe or shutil.which("ffprobe")
    ffmpeg_exe = ffmpeg or shutil.which("ffmpeg")
    environment: dict[str, Any] = {
        "expected_frames": expected_frames, "fixed_fps": fps,
        "godot_bin": str(godot), "project_path": str(project),
    }
    missing = [name for name, value in (("godot", str(godot) if godot.is_file() else None),
                                         ("ffmpeg", ffmpeg_exe), ("ffprobe", probe_exe)) if not value]
    if missing:
        environment["missing_tools"] = missing
        return _unknown("Required capture tools are unavailable.", "motion.tools", started=started, environment=environment)
    if not project.is_dir() or not (project / "project.godot").is_file():
        return _unknown("Godot fixture evidence is unavailable.", "motion.project", started=started, environment=environment)

    before = _source_hash(project)
    environment["source_sha256_before"] = before
    destination.mkdir(parents=True, exist_ok=True)
    video = destination / "motion.avi"
    sheet = destination / "motion-proof.png"
    command = [
        str(godot), "--path", str(project), "--write-movie", str(video),
        "--fixed-fps", str(fps), "--resolution", "320x180",
    ]
    environment["capture_argv"] = command
    try:
        completed = runner(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return _unknown("Godot movie capture timed out.", "motion.timeout", started=started, environment=environment)
    except OSError as exc:
        return _unknown(f"Godot could not be executed: {exc}", "motion.tool_unusable", started=started, environment=environment)
    evidence = [{"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}]
    if completed.returncode != 0 or not video.is_file() or video.stat().st_size == 0:
        return _fail("Godot did not produce a motion video.", "motion.capture", started=started,
                     environment=environment, artifacts=[make_artifact(video, "motion_video")], evidence=evidence)

    probe_command = [
        str(probe_exe), "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames,r_frame_rate,width,height", "-of", "json", str(video),
    ]
    try:
        probed = runner(
            probe_command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
        )
        payload = json.loads(probed.stdout) if probed.returncode == 0 else {}
        stream = payload["streams"][0]
        frames = int(stream["nb_read_frames"])
        rate_text = str(stream["r_frame_rate"])
        numerator, denominator = rate_text.split("/", 1)
        measured_fps = float(numerator) / float(denominator)
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return _unknown(f"Captured video metadata is unavailable: {exc}", "motion.metadata", started=started, environment=environment)
    environment.update({"captured_frames": frames, "captured_fps": measured_fps})
    if frames != expected_frames or abs(measured_fps - float(fps)) > 0.001:
        return _fail("Captured motion did not match the fixed frame contract.", "motion.determinism",
                     started=started, environment=environment, artifacts=[make_artifact(video, "motion_video")],
                     evidence=[{"frames": frames, "fps": measured_fps}])

    proof = make_proof_sheet(video, sheet, count=12, columns=4, width=160, height=90,
                             timeout=timeout, ffprobe=str(probe_exe), ffmpeg=str(ffmpeg_exe), runner=runner)
    after = _source_hash(project)
    environment["source_sha256_after"] = after
    if after != before:
        return _fail("Godot source tree changed during motion proof.", "motion.source_hash",
                     started=started, environment=environment,
                     artifacts=[make_artifact(video, "motion_video"), make_artifact(sheet, "proof_sheet")])
    if proof["status"] != "PASS" or not sheet.is_file() or sheet.stat().st_size == 0:
        status = "UNKNOWN" if proof["status"] == "UNKNOWN" else "FAIL"
        if status == "UNKNOWN":
            environment["proof_sheet_result"] = proof
            return _unknown("Proof sheet evidence is unavailable.", "motion.proof_sheet", started=started, environment=environment)
        return _fail("Proof sheet generation failed.", "motion.proof_sheet", started=started,
                     environment=environment, artifacts=[make_artifact(video, "motion_video"), make_artifact(sheet, "proof_sheet")],
                     evidence=[proof])

    checks = [
        make_check("motion.capture", "PASS", message="Godot produced a non-empty movie.", evidence=evidence,
                   details={"frames": frames, "fps": measured_fps}),
        make_check("motion.proof_sheet", "PASS", message="Duration-sampled proof sheet generated.", evidence=[proof]),
        make_check("motion.source_hash", "PASS", message="Fixture source tree remained unchanged.",
                   evidence=[{"before": before, "after": after}]),
    ]
    return make_result(
        "godot_motion_proof", proof_level="P4", task_domains=["ANIMATION", "PLAYTEST"],
        summary=f"Captured {frames} frames at {measured_fps:g} FPS and generated a proof sheet.",
        checks=checks, artifacts=[make_artifact(video, "motion_video"), make_artifact(sheet, "proof_sheet")],
        environment=environment, duration_ms=elapsed_ms(started),
    )
