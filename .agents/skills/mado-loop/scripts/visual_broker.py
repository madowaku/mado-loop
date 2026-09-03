"""Typed launch/capture/stop broker for delegated visual verification.

The broker owns only processes it launched, writes state outside the tracked
checkout, and never performs arbitrary desktop automation. Window capture is
first-class on native Windows; other platforms report capture as UNKNOWN.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from time import monotonic
from typing import Any, Callable, Mapping

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

TOOL = "visual_broker"
STATE_SCHEMA = "mado-visual-broker/v1"
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_STARTUP_WAIT = 0.75
DEFAULT_STOP_TIMEOUT = 3.0


class BrokerConfigError(ValueError):
    """Raised when a broker request is unsafe or incomplete."""


def _run_git(repo: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if cp.returncode != 0:
        raise BrokerConfigError((cp.stderr or cp.stdout or "git command failed").strip())
    return cp.stdout.strip()


def _repo_root(repo: str | Path) -> Path:
    root = Path(repo).resolve()
    actual = Path(_run_git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root:
        raise BrokerConfigError(f"--repo must be the Git worktree root: {actual}")
    return root


def _git_common_dir(repo: Path) -> Path:
    value = _run_git(repo, "rev-parse", "--git-common-dir")
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _inside(root: Path, value: Path) -> Path:
    resolved = value.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BrokerConfigError(f"path escapes allowed root: {resolved}") from exc
    return resolved


def _project_path(repo: Path, value: str | Path | None) -> Path:
    project = repo if value is None else Path(value)
    if not project.is_absolute():
        project = repo / project
    project = _inside(repo, project)
    if not (project / "project.godot").is_file():
        raise BrokerConfigError(f"Godot project.godot not found: {project}")
    return project


def _scene_arg(project: Path, scene: str | None) -> str | None:
    if not scene:
        return None
    raw = Path(scene)
    scene_path = raw if raw.is_absolute() else project / raw
    scene_path = _inside(project, scene_path)
    if scene_path.suffix.lower() not in {".tscn", ".scn"}:
        raise BrokerConfigError("scene must be a .tscn or .scn file")
    if not scene_path.is_file():
        raise BrokerConfigError(f"scene does not exist: {scene_path}")
    return str(scene_path)


def _resolve_executable(value: str | Path) -> Path:
    raw = str(value)
    found = shutil.which(raw)
    path = Path(found or raw).resolve()
    if not path.is_file():
        raise BrokerConfigError(f"Godot executable not found: {value}")
    return path


def _session_id(value: str) -> str:
    if not SESSION_RE.fullmatch(value):
        raise BrokerConfigError("session must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    return value


def _state_dir(repo: Path) -> Path:
    path = _git_common_dir(repo) / "mado-loop" / "visual-broker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(repo: Path, session: str) -> Path:
    return _state_dir(repo) / f"{_session_id(session)}.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _load_state(repo: Path, session: str) -> dict[str, Any]:
    path = _state_path(repo, session)
    if not path.is_file():
        raise BrokerConfigError(f"visual broker session does not exist: {session}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrokerConfigError(f"visual broker state is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA:
        raise BrokerConfigError("visual broker state schema is invalid")
    return payload


def _process_identity(pid: int, *, host_platform: str | None = None) -> dict[str, Any] | None:
    platform = (host_platform or sys.platform).lower()
    if pid <= 0:
        return None
    if platform.startswith("win"):
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            query = kernel32.QueryFullProcessImageNameW
            query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            query.restype = wintypes.BOOL
            if not query(handle, 0, buffer, ctypes.byref(size)):
                return None
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            get_times = kernel32.GetProcessTimes
            get_times.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            get_times.restype = wintypes.BOOL
            if not get_times(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            token = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return {"exe": str(Path(buffer.value).resolve()), "started": int(token)}
        finally:
            kernel32.CloseHandle(handle)
    if platform.startswith("linux"):
        proc = Path("/proc") / str(pid)
        try:
            exe = str((proc / "exe").resolve(strict=True))
            stat = (proc / "stat").read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, PermissionError, OSError):
            return None
        right = stat.rsplit(")", 1)
        if len(right) != 2:
            return None
        fields = right[1].strip().split()
        if len(fields) < 20:
            return None
        return {"exe": str(Path(exe).resolve()), "started": fields[19]}
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return {"exe": None, "started": None}


def _owned_process(
    state: Mapping[str, Any],
    *,
    identity_reader: Callable[..., dict[str, Any] | None] = _process_identity,
    host_platform: str | None = None,
) -> bool:
    current = identity_reader(int(state["pid"]), host_platform=host_platform)
    recorded = state.get("process_identity")
    return isinstance(recorded, dict) and current == recorded


def _find_windows_window(pid: int) -> int | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    windows: list[tuple[int, int]] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area > 0:
            windows.append((area, int(hwnd)))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    if not windows:
        return None
    return max(windows)[1]


def _capture_windows_window(pid: int, output: Path) -> None:
    hwnd = _find_windows_window(pid)
    if hwnd is None:
        raise RuntimeError("no visible window owned by the launched Godot process")
    from PIL import ImageGrab
    try:
        image = ImageGrab.grab(window=hwnd, include_layered_windows=True)
    except TypeError as exc:
        raise RuntimeError("installed Pillow lacks HWND-only ImageGrab support") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")


def _terminate_owned_process(
    pid: int,
    *,
    host_platform: str | None = None,
    timeout: float = DEFAULT_STOP_TIMEOUT,
) -> bool:
    platform = (host_platform or sys.platform).lower()
    if platform.startswith("win"):
        hwnd = _find_windows_window(pid)
        if hwnd is not None:
            ctypes.WinDLL("user32", use_last_error=True).PostMessageW(hwnd, 0x0010, 0, 0)
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if _process_identity(pid, host_platform=host_platform) is None:
                return True
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return _process_identity(pid, host_platform=host_platform) is None
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return _process_identity(pid, host_platform=host_platform) is None
    deadline = monotonic() + max(1.0, timeout)
    while monotonic() < deadline:
        if _process_identity(pid, host_platform=host_platform) is None:
            return True
        time.sleep(0.1)
    return False


def launch_session(
    *,
    repo: str | Path,
    session: str,
    godot_bin: str | Path,
    project: str | Path | None = None,
    scene: str | None = None,
    startup_wait: float = DEFAULT_STARTUP_WAIT,
    popen: Callable[..., Any] = subprocess.Popen,
    identity_reader: Callable[..., dict[str, Any] | None] = _process_identity,
    sleeper: Callable[[float], None] = time.sleep,
    host_platform: str | None = None,
) -> dict[str, Any]:
    started = monotonic()
    if startup_wait < 0 or startup_wait > 5:
        raise BrokerConfigError("startup_wait must be between 0 and 5 seconds")
    root = _repo_root(repo)
    session = _session_id(session)
    project_path = _project_path(root, project)
    scene_path = _scene_arg(project_path, scene)
    executable = _resolve_executable(godot_bin)
    path = _state_path(root, session)

    if path.exists():
        previous = _load_state(root, session)
        if previous.get("status") == "RUNNING" and _owned_process(
            previous, identity_reader=identity_reader, host_platform=host_platform
        ):
            raise BrokerConfigError(f"session is already running: {session}")

    session_dir = _state_dir(root) / session
    session_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = session_dir / "stdout.log"
    stderr_path = session_dir / "stderr.log"
    command = [str(executable), "--path", str(project_path)]
    if scene_path:
        command.append(scene_path)
    creationflags = 0
    if (host_platform or sys.platform).lower().startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = popen(
            command,
            cwd=str(project_path),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            creationflags=creationflags,
        )
    sleeper(startup_wait)
    if process.poll() is not None:
        detail = ""
        try:
            detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-1200:]
        except OSError:
            pass
        check = make_check(
            "visual.launch",
            "FAIL",
            message="Godot exited during broker startup.",
            evidence=[{"returncode": process.poll(), "stderr_tail": detail}],
        )
        return make_result(
            TOOL,
            proof_level=None,
            task_domains=["PLAYTEST"],
            summary="Visual broker launch failed.",
            checks=[check],
            errors=["Godot exited during broker startup."],
            environment={"repo": str(root), "session": session, "project": str(project_path)},
            duration_ms=elapsed_ms(started),
        )

    identity = identity_reader(int(process.pid), host_platform=host_platform)
    if identity is None:
        try:
            process.terminate()
        except Exception:
            pass
        check = make_check("visual.launch", "FAIL", message="Could not establish process ownership identity.")
        return make_result(
            TOOL,
            proof_level=None,
            task_domains=["PLAYTEST"],
            summary="Visual broker launch could not establish ownership.",
            checks=[check],
            errors=["Process identity is unavailable."],
            environment={"repo": str(root), "session": session},
            duration_ms=elapsed_ms(started),
        )

    state = {
        "schema_version": STATE_SCHEMA,
        "session": session,
        "status": "RUNNING",
        "repo": str(root),
        "project": str(project_path),
        "scene": scene_path,
        "pid": int(process.pid),
        "process_identity": identity,
        "godot_executable": str(executable),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "launched_at": time.time(),
    }
    _atomic_json(path, state)
    check = make_check(
        "visual.launch",
        "PASS",
        message="Godot process launched under broker ownership.",
        evidence=[{"pid": process.pid, "session": session}],
    )
    return make_result(
        TOOL,
        proof_level=None,
        task_domains=["PLAYTEST"],
        summary="Visual broker session is RUNNING.",
        checks=[check],
        environment={"repo": str(root), "session": session, "project": str(project_path), "pid": int(process.pid)},
        duration_ms=elapsed_ms(started),
    )


def capture_session(
    *,
    repo: str | Path,
    session: str,
    output: str | Path,
    identity_reader: Callable[..., dict[str, Any] | None] = _process_identity,
    capture_func: Callable[[int, Path], None] = _capture_windows_window,
    host_platform: str | None = None,
) -> dict[str, Any]:
    started = monotonic()
    root = _repo_root(repo)
    state = _load_state(root, session)
    if state.get("status") != "RUNNING":
        raise BrokerConfigError(f"session is not running: {session}")
    if not _owned_process(state, identity_reader=identity_reader, host_platform=host_platform):
        raise BrokerConfigError("recorded process is no longer the broker-owned Godot process")
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = _inside(root, target)
    if target.suffix.lower() != ".png":
        raise BrokerConfigError("capture output must be a .png inside the repository worktree")

    platform = (host_platform or sys.platform).lower()
    if not platform.startswith("win"):
        message = "Window-only visual capture is currently supported only on native Windows."
        check = make_check("visual.capture", "UNKNOWN", message=message)
        return make_result(
            TOOL,
            proof_level="P3",
            task_domains=["UI", "PLAYTEST"],
            summary=message,
            checks=[check],
            unknowns=[message],
            environment={"repo": str(root), "session": session, "platform": platform},
            duration_ms=elapsed_ms(started),
        )

    try:
        capture_func(int(state["pid"]), target)
    except Exception as exc:
        message = f"Window capture failed: {type(exc).__name__}: {exc}"
        check = make_check("visual.capture", "UNKNOWN", message=message)
        return make_result(
            TOOL,
            proof_level="P3",
            task_domains=["UI", "PLAYTEST"],
            summary="Visual capture is unavailable.",
            checks=[check],
            unknowns=[message],
            environment={"repo": str(root), "session": session},
            duration_ms=elapsed_ms(started),
        )
    artifact = make_artifact(target, "visual-capture")
    status = "PASS" if artifact["exists"] and (artifact["size_bytes"] or 0) > 0 else "FAIL"
    check = make_check(
        "visual.capture",
        status,
        message="Captured the broker-owned Godot window." if status == "PASS" else "Capture artifact is missing or empty.",
        evidence=[artifact],
    )
    return make_result(
        TOOL,
        proof_level="P3",
        task_domains=["UI", "PLAYTEST"],
        summary="Visual capture produced a window-scoped artifact." if status == "PASS" else "Visual capture artifact failed validation.",
        checks=[check],
        errors=[] if status == "PASS" else ["Capture artifact is missing or empty."],
        artifacts=[artifact],
        environment={"repo": str(root), "session": session, "pid": int(state["pid"])},
        duration_ms=elapsed_ms(started),
    )


def stop_session(
    *,
    repo: str | Path,
    session: str,
    identity_reader: Callable[..., dict[str, Any] | None] = _process_identity,
    terminator: Callable[..., bool] = _terminate_owned_process,
    host_platform: str | None = None,
) -> dict[str, Any]:
    started = monotonic()
    root = _repo_root(repo)
    state = _load_state(root, session)
    if state.get("status") != "RUNNING":
        check = make_check("visual.stop", "PASS", message="Session is already stopped.")
        return make_result(
            TOOL,
            proof_level=None,
            task_domains=["PLAYTEST"],
            summary="Visual broker session is already stopped.",
            checks=[check],
            environment={"repo": str(root), "session": session},
            duration_ms=elapsed_ms(started),
        )
    if not _owned_process(state, identity_reader=identity_reader, host_platform=host_platform):
        raise BrokerConfigError("refusing to stop a PID that no longer matches broker ownership")
    stopped = bool(terminator(int(state["pid"]), host_platform=host_platform))
    if stopped:
        state["status"] = "STOPPED"
        state["stopped_at"] = time.time()
        _atomic_json(_state_path(root, session), state)
    check = make_check(
        "visual.stop",
        "PASS" if stopped else "FAIL",
        message="Broker-owned Godot process stopped." if stopped else "Godot process did not stop within the bounded timeout.",
    )
    return make_result(
        TOOL,
        proof_level=None,
        task_domains=["PLAYTEST"],
        summary="Visual broker session stopped." if stopped else "Visual broker could not stop the session.",
        checks=[check],
        errors=[] if stopped else ["Godot process did not stop within the bounded timeout."],
        environment={"repo": str(root), "session": session, "pid": int(state["pid"])},
        duration_ms=elapsed_ms(started),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MADO LOOP typed visual broker")
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    launch = sub.add_parser("launch", help="launch one Godot project/scene")
    launch.add_argument("--repo", default=".")
    launch.add_argument("--session", required=True)
    launch.add_argument("--godot-bin", required=True)
    launch.add_argument("--project")
    launch.add_argument("--scene")
    launch.add_argument("--startup-wait", type=float, default=DEFAULT_STARTUP_WAIT)

    capture = sub.add_parser("capture", help="capture only the broker-owned Godot window")
    capture.add_argument("--repo", default=".")
    capture.add_argument("--session", required=True)
    capture.add_argument("--output", required=True)

    stop = sub.add_parser("stop", help="stop only the broker-owned Godot process")
    stop.add_argument("--repo", default=".")
    stop.add_argument("--session", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "launch":
            result = launch_session(
                repo=args.repo,
                session=args.session,
                godot_bin=args.godot_bin,
                project=args.project,
                scene=args.scene,
                startup_wait=args.startup_wait,
            )
        elif args.command == "capture":
            result = capture_session(repo=args.repo, session=args.session, output=args.output)
        else:
            result = stop_session(repo=args.repo, session=args.session)
    except BrokerConfigError as exc:
        parser.error(str(exc))
        return EXIT_USAGE_CONFIG
    except Exception as exc:
        payload = make_result(
            TOOL,
            proof_level=None,
            domain_neutral=True,
            summary="Visual broker internal error.",
            checks=[make_check("visual.internal", "FAIL", message=f"{type(exc).__name__}: {exc}")],
            errors=[f"{type(exc).__name__}: {exc}"],
        )
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return EXIT_INTERNAL
    if args.pretty:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(result_json(result))
    return exit_code_for_status(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
