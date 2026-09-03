"""Capture Visual Broker evidence, then bind it to an explicit OVP review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from time import monotonic
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ovp_runtime as ovp  # noqa: E402
import visual_broker as visual  # noqa: E402
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

TOOL = "ovp_visual_review"
RECORD_SCHEMA = "mado-ovp-visual-review/v1"


class VisualReviewConfigError(ValueError):
    pass


def _context(repo: str | Path, task_id: str, timeout: float) -> tuple[Path, dict[str, Any], Path, str]:
    leader = ovp._repo_root(repo, timeout=timeout)
    task_id = ovp._validate_task_id(task_id)
    manifest = ovp._load_manifest(leader, task_id, timeout=timeout)
    if manifest["state"] != "REVIEW_READY":
        raise VisualReviewConfigError(f"visual review requires REVIEW_READY, found {manifest['state']}")
    receipt = manifest.get("receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("worker_head"), str):
        raise VisualReviewConfigError("REVIEW_READY task is missing a valid receipt")
    workspace = Path(manifest["workspace"]).resolve()
    head = ovp._commit(workspace, "HEAD", timeout=timeout)
    if head != receipt["worker_head"]:
        raise VisualReviewConfigError("worker HEAD no longer matches the receipt")
    if not ovp._clean(workspace, timeout=timeout):
        raise VisualReviewConfigError("worker workspace must be clean")
    return leader, manifest, workspace, head


def _record_path(leader: Path, task_id: str, timeout: float) -> Path:
    return ovp._task_dir(leader, task_id, timeout=timeout) / "visual-review.json"


def _load_record(leader: Path, task_id: str, timeout: float) -> dict[str, Any]:
    path = _record_path(leader, task_id, timeout)
    if not path.is_file():
        raise VisualReviewConfigError("capture visual evidence before visual review")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualReviewConfigError("visual review record is unreadable") from exc
    if not isinstance(record, dict) or record.get("schema_version") != RECORD_SCHEMA or record.get("task_id") != task_id:
        raise VisualReviewConfigError("visual review record is invalid")
    return record


def _temp_path(workspace: Path, task_id: str) -> Path:
    return workspace / ".mado-loop-visual" / f"{task_id}.png"


def _remove_temp(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    try:
        path.parent.rmdir()
    except OSError:
        pass


def capture_visual_evidence(
    *,
    repo: str | Path,
    task_id: str,
    godot_bin: str | Path,
    project: str | Path | None = None,
    scene: str | None = None,
    session: str | None = None,
    startup_wait: float = visual.DEFAULT_STARTUP_WAIT,
    timeout: float = ovp.DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    leader, manifest, workspace, worker_head = _context(repo, task_id, timeout)
    session = session or f"ovp-{task_id}"
    temp = _temp_path(workspace, task_id)
    _remove_temp(temp)

    launch: dict[str, Any] | None = None
    capture: dict[str, Any] | None = None
    stop: dict[str, Any] | None = None
    operation_error: str | None = None
    try:
        launch = visual.launch_session(
            repo=workspace, session=session, godot_bin=godot_bin,
            project=project, scene=scene, startup_wait=startup_wait,
        )
        if launch["status"] == "PASS":
            capture = visual.capture_session(repo=workspace, session=session, output=temp)
    except (visual.BrokerConfigError, OSError, RuntimeError, ValueError) as exc:
        operation_error = f"{type(exc).__name__}: {exc}"
    finally:
        if launch and launch.get("status") == "PASS":
            try:
                stop = visual.stop_session(repo=workspace, session=session)
            except (visual.BrokerConfigError, OSError, RuntimeError, ValueError) as exc:
                operation_error = operation_error or f"{type(exc).__name__}: {exc}"

    durable: dict[str, Any] | None = None
    if capture and capture.get("status") == "PASS" and temp.is_file():
        destination = ovp._task_dir(leader, task_id, timeout=timeout) / "visual" / f"{worker_head[:16]}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp, destination)
        durable = make_artifact(destination, "visual-review")
    _remove_temp(temp)

    head_stable = ovp._commit(workspace, "HEAD", timeout=timeout) == worker_head
    clean = ovp._clean(workspace, timeout=timeout)
    launch_status = str((launch or {}).get("status", "FAIL"))
    capture_status = str((capture or {}).get("status", "SKIPPED" if launch_status != "PASS" else "FAIL"))
    stop_status = str((stop or {}).get("status", "SKIPPED" if launch_status != "PASS" else "FAIL"))
    artifact_ok = bool(durable and durable.get("exists") and durable.get("size_bytes") and durable.get("sha256"))
    checks = [
        make_check(
            "ovp.visual.launch", launch_status, message="Visual Broker launch result.",
            evidence=[operation_error] if operation_error and not launch else [],
        ),
        make_check(
            "ovp.visual.capture", capture_status, message="Window-scoped Visual Broker capture.",
            evidence=[operation_error] if operation_error and launch_status == "PASS" and not capture else [],
        ),
        make_check(
            "ovp.visual.artifact",
            "PASS" if artifact_ok else ("UNKNOWN" if capture_status == "UNKNOWN" else "FAIL"),
            message="Durable screenshot copied outside tracked source." if artifact_ok else "Durable screenshot is unavailable.",
            evidence=[durable] if durable else [],
        ),
        make_check(
            "ovp.visual.stop",
            stop_status,
            message="Broker-owned Godot process stopped." if stop_status == "PASS" else "Broker stop did not pass.",
        ),
        make_check(
            "ovp.visual.workspace",
            "PASS" if head_stable and clean else "FAIL",
            message="Worker HEAD stayed stable and the worktree stayed clean." if head_stable and clean else "Visual capture changed worker state.",
        ),
    ]
    record = {
        "schema_version": RECORD_SCHEMA,
        "task_id": task_id,
        "worker_head": worker_head,
        "captured_at": ovp._now(),
        "session": session,
        "launch_status": launch_status,
        "capture_status": capture_status,
        "stop_status": stop_status,
        "operation_error": operation_error,
        "artifact": durable,
        "review": None,
    }
    record_path = _record_path(leader, task_id, timeout)
    ovp._atomic_json(record_path, record)
    artifacts = [make_artifact(record_path, "visual-review-record")]
    if durable:
        artifacts.append(durable)
    return make_result(
        TOOL, proof_level="P3", task_domains=manifest["task_domains"],
        summary="Visual evidence is ready for inspection." if artifact_ok else "Visual evidence is not ready for acceptance.",
        checks=checks, artifacts=artifacts,
        environment={"repo": str(leader), "task_id": task_id, "worker_head": worker_head, "ovp_state": "REVIEW_READY"},
        duration_ms=elapsed_ms(started),
    )


def review_with_visual_evidence(
    *,
    repo: str | Path,
    task_id: str,
    decision: str,
    reason: str,
    inspected_diff: bool = False,
    inspected_visual: bool = False,
    timeout: float = ovp.DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    if decision not in {"accept", "rework", "reject"}:
        raise VisualReviewConfigError("decision must be accept, rework, or reject")
    if not reason.strip():
        raise VisualReviewConfigError("review reason is required")

    leader, manifest, workspace, worker_head = _context(repo, task_id, timeout)
    record = _load_record(leader, task_id, timeout)
    stored = record.get("artifact")
    current: dict[str, Any] | None = None
    artifact_ok = False
    if isinstance(stored, Mapping) and stored.get("path"):
        current = make_artifact(str(stored["path"]), "visual-review")
        artifact_ok = bool(
            current.get("exists") and current.get("size_bytes") and current.get("sha256")
            and current.get("sha256") == stored.get("sha256")
        )
    head_bound = record.get("worker_head") == worker_head
    capture_passed = record.get("capture_status") == "PASS"
    stop_passed = record.get("stop_status") == "PASS"
    checks = [
        make_check("ovp.visual.review.head", "PASS" if head_bound else "FAIL", message="Visual evidence matches receipt HEAD." if head_bound else "Visual evidence belongs to another HEAD."),
        make_check(
            "ovp.visual.review.artifact",
            "PASS" if artifact_ok else ("UNKNOWN" if record.get("capture_status") == "UNKNOWN" else "FAIL"),
            required=decision == "accept", message="Visual artifact hash is stable." if artifact_ok else "Visual artifact is missing or changed.",
        ),
        make_check(
            "ovp.visual.review.inspected",
            "PASS" if inspected_visual else "FAIL", required=decision == "accept",
            message="Visual artifact inspection confirmed." if inspected_visual else "Acceptance requires --inspected-visual.",
        ),
        make_check(
            "ovp.visual.review.capture",
            "PASS" if capture_passed else ("UNKNOWN" if record.get("capture_status") == "UNKNOWN" else "FAIL"),
            required=decision == "accept", message="Capture passed." if capture_passed else "Capture did not pass.",
        ),
        make_check(
            "ovp.visual.review.stop", "PASS" if stop_passed else "FAIL", required=decision == "accept",
            message="Broker-owned Godot process stopped." if stop_passed else "Acceptance requires a clean broker stop.",
        ),
    ]
    if decision == "accept" and any(item["required"] and item["status"] != "PASS" for item in checks):
        return make_result(
            TOOL, proof_level="P3", task_domains=manifest["task_domains"],
            summary="Visual gate blocked OVP acceptance; task remains REVIEW_READY.", checks=checks,
            artifacts=[make_artifact(_record_path(leader, task_id, timeout), "visual-review-record")],
            environment={"repo": str(leader), "task_id": task_id, "worker_head": worker_head, "ovp_state": "REVIEW_READY", "review_invoked": False},
            duration_ms=elapsed_ms(started),
        )

    note = f"visual_sha256={current['sha256']} visual_artifact={current['path']}" if artifact_ok and current else f"visual_status={record.get('capture_status', 'UNKNOWN')}"
    review = ovp.review_task(
        repo=leader, task_id=task_id, decision=decision,
        reason=f"{reason.strip()} | {note}", inspected_diff=inspected_diff, timeout=timeout,
    )
    checks.append(make_check("ovp.visual.review.ovp", str(review["status"]), message=str(review["summary"])))
    record["review"] = {
        "at": ovp._now(), "decision": decision, "inspected_diff": bool(inspected_diff),
        "inspected_visual": bool(inspected_visual), "ovp_status": review["status"],
        "ovp_state": review.get("environment", {}).get("ovp_state"),
    }
    record_path = _record_path(leader, task_id, timeout)
    ovp._atomic_json(record_path, record)
    artifacts = [make_artifact(record_path, "visual-review-record")]
    if current and current.get("exists"):
        artifacts.append(current)
    return make_result(
        TOOL, proof_level="P3", task_domains=manifest["task_domains"],
        summary=f"Visual evidence carried into OVP review: {review.get('environment', {}).get('ovp_state', 'REVIEW_READY')}.",
        checks=checks, artifacts=artifacts,
        environment={"repo": str(leader), "task_id": task_id, "workspace": str(workspace), "worker_head": worker_head,
                     "ovp_state": review.get("environment", {}).get("ovp_state", "REVIEW_READY"), "review_invoked": True},
        duration_ms=elapsed_ms(started),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--repo", default=".")
    capture.add_argument("--task-id", required=True)
    capture.add_argument("--godot-bin", required=True)
    capture.add_argument("--project")
    capture.add_argument("--scene")
    capture.add_argument("--session")
    capture.add_argument("--startup-wait", type=float, default=visual.DEFAULT_STARTUP_WAIT)
    capture.add_argument("--timeout", type=float, default=ovp.DEFAULT_TIMEOUT)
    review = sub.add_parser("review")
    review.add_argument("--repo", default=".")
    review.add_argument("--task-id", required=True)
    review.add_argument("--decision", choices=["accept", "rework", "reject"], required=True)
    review.add_argument("--reason", required=True)
    review.add_argument("--inspected-diff", action="store_true")
    review.add_argument("--inspected-visual", action="store_true")
    review.add_argument("--timeout", type=float, default=ovp.DEFAULT_TIMEOUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            result = capture_visual_evidence(
                repo=args.repo, task_id=args.task_id, godot_bin=args.godot_bin,
                project=args.project, scene=args.scene, session=args.session,
                startup_wait=args.startup_wait, timeout=args.timeout,
            )
        else:
            result = review_with_visual_evidence(
                repo=args.repo, task_id=args.task_id, decision=args.decision, reason=args.reason,
                inspected_diff=args.inspected_diff, inspected_visual=args.inspected_visual, timeout=args.timeout,
            )
    except (VisualReviewConfigError, visual.BrokerConfigError, ValueError) as exc:
        parser.error(str(exc))
        return EXIT_USAGE_CONFIG
    except Exception as exc:
        result = make_result(
            TOOL, proof_level=None, domain_neutral=True, summary="OVP visual review internal error.",
            checks=[make_check("ovp.visual.internal", "FAIL", message=f"{type(exc).__name__}: {exc}")],
            errors=[f"{type(exc).__name__}: {exc}"],
        )
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return EXIT_INTERNAL
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.pretty else result_json(result))
    return exit_code_for_status(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
