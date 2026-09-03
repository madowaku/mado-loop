"""Run MADO LOOP Orchestration & Verification Protocol mutation work safely."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from time import monotonic, sleep, time
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

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

OVP_SCHEMA_VERSION = "1.0"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CHECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
STATES = (
    "PLANNED", "PREFLIGHT", "READY", "DISPATCHED", "WORKING", "REVIEW_READY",
    "ACCEPTED", "REWORK", "REJECTED", "INTEGRATED", "PROVEN", "FAILED", "UNKNOWN",
)
FINAL_STATES = {"PROVEN", "FAILED", "UNKNOWN", "REJECTED"}
RECEIPT_STATUSES = {"PASS", "FAIL", "WARN", "UNKNOWN", "SKIPPED"}
LOCK_STALE_SECONDS = 300.0
LOCK_WAIT_SECONDS = 5.0
DEFAULT_TIMEOUT = 15.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("task id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    return task_id


def _validate_check_id(check_id: str) -> str:
    if not CHECK_ID_RE.fullmatch(check_id):
        raise ValueError(f"invalid check id: {check_id!r}")
    return check_id


def _run(
    args: Sequence[str], *, cwd: Path | None = None, timeout: float = DEFAULT_TIMEOUT,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        cp = subprocess.run(
            list(args), cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"command failed to start: {args[0]}: {type(exc).__name__}") from exc
    if check and cp.returncode != 0:
        detail = (cp.stderr or cp.stdout).strip()[:1000]
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}: {detail}")
    return cp


def _git(repo: Path, args: Sequence[str], *, timeout: float = DEFAULT_TIMEOUT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo), *args], timeout=timeout, check=check)


def _repo_root(path: str | Path, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ValueError(f"repository path does not exist: {candidate}")
    cp = _git(candidate, ["rev-parse", "--show-toplevel"], timeout=timeout)
    root = Path(cp.stdout.strip()).resolve()
    if not root.is_dir():
        raise ValueError("git repository root is not a directory")
    bare = _git(root, ["rev-parse", "--is-bare-repository"], timeout=timeout).stdout.strip()
    if bare == "true":
        raise ValueError("OVP mutation runtime requires a non-bare repository")
    return root


def _common_git_dir(repo: Path, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    text = _git(repo, ["rev-parse", "--git-common-dir"], timeout=timeout).stdout.strip()
    path = Path(text)
    if not path.is_absolute():
        path = (repo / path).resolve()
    else:
        path = path.resolve()
    if not path.is_dir():
        raise RuntimeError(f"git common dir is unavailable: {path}")
    return path


def _state_root(repo: Path, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    return _common_git_dir(repo, timeout=timeout) / "mado-loop" / "ovp"


def _task_dir(repo: Path, task_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    _validate_task_id(task_id)
    return _state_root(repo, timeout=timeout) / "tasks" / task_id


def _manifest_path(repo: Path, task_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    return _task_dir(repo, task_id, timeout=timeout) / "manifest.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def _task_lock(repo: Path, task_id: str, *, timeout: float = DEFAULT_TIMEOUT):
    root = _state_root(repo, timeout=timeout) / "locks"
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / f"{task_id}.lock"
    deadline = time() + LOCK_WAIT_SECONDS
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, f"pid={os.getpid()} created={_now()}\n".encode("utf-8"))
            break
        except FileExistsError:
            try:
                age = time() - lock_path.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time() >= deadline:
                raise RuntimeError(f"OVP task is locked: {task_id}")
            sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _load_manifest(repo: Path, task_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    path = _manifest_path(repo, task_id, timeout=timeout)
    if not path.is_file():
        raise ValueError(f"OVP task manifest not found: {task_id}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OVP task manifest is unreadable: {path}") from exc
    if payload.get("ovp_schema_version") != OVP_SCHEMA_VERSION:
        raise RuntimeError("unsupported OVP manifest schema")
    if payload.get("task_id") != task_id:
        raise RuntimeError("OVP manifest task id mismatch")
    if payload.get("state") not in STATES:
        raise RuntimeError("OVP manifest contains an invalid state")
    return payload


def _save_manifest(repo: Path, task_id: str, manifest: Mapping[str, Any], *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    path = _manifest_path(repo, task_id, timeout=timeout)
    _atomic_json(path, manifest)
    return path


def _clean(repo: Path, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
    return not _git(repo, ["status", "--porcelain=v1", "--untracked-files=normal"], timeout=timeout).stdout.strip()


def _current_branch(repo: Path, *, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    cp = _git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"], timeout=timeout, check=False)
    return cp.stdout.strip() if cp.returncode == 0 and cp.stdout.strip() else None


def _commit(repo: Path, ref: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    cp = _git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"], timeout=timeout, check=False)
    if cp.returncode != 0 or not cp.stdout.strip():
        raise ValueError(f"git ref is not a commit: {ref}")
    return cp.stdout.strip()


def _default_workspace_root(repo: Path) -> Path:
    return (repo.parent / ".mado-loop-worktrees" / repo.name).resolve()


def _safe_pattern(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if not text or text.startswith("/"):
        raise ValueError(f"scope pattern must be repository-relative: {value!r}")
    parts = PurePosixPath(text).parts
    if any(part == ".." for part in parts):
        raise ValueError(f"scope pattern cannot contain '..': {value!r}")
    return text.lstrip("./")


def _path_matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    pattern = _safe_pattern(pattern)
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    prefix = pattern.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _scope_violations(paths: Iterable[str], include: Sequence[str], exclude: Sequence[str]) -> list[str]:
    violations = []
    for path in sorted(set(paths)):
        allowed = any(_path_matches(path, pattern) for pattern in include)
        blocked = any(_path_matches(path, pattern) for pattern in exclude)
        if not allowed or blocked:
            violations.append(path)
    return violations


def _parse_assignment(items: Sequence[str], *, kind: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise ValueError(f"{kind} entries must use ID=VALUE")
        _validate_check_id(key)
        if key in parsed:
            raise ValueError(f"duplicate {kind} id: {key}")
        parsed[key] = value
    return parsed


def _render_contract(manifest: Mapping[str, Any]) -> str:
    contract = manifest["contract"]
    acceptance = manifest["acceptance"]
    checks = "; ".join(f"{item['id']}: {item['description']}" for item in acceptance)
    target = ", ".join(manifest["scope"]["include"])

    def join(name: str, fallback: str = "none") -> str:
        values = contract.get(name) or []
        return "; ".join(values) if values else fallback

    lines = [
        f"TASK {manifest['task_id']}",
        f"GOAL {contract['goal']}",
        f"STATE {manifest['state']}",
        f"TARGET {target}",
        f"DO {join('do')}",
        f"KEEP {join('keep')}",
        f"NO {join('no')}",
        f"OUT {join('out', 'committed change; mutation receipt; evidence bundle')}",
        f"CHECK {checks}",
        f"RISK {join('risk')}",
        "NEXT REVIEW_READY",
    ]
    return "\n".join(lines) + "\n"


def _result(
    tool: str, *, summary: str, domains: Sequence[str], checks: Sequence[Mapping[str, Any]],
    warnings: Sequence[Any] = (), unknowns: Sequence[Any] = (), environment: Mapping[str, Any] | None = None,
    started: float | None = None, artifacts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return make_result(
        tool, proof_level="P0", task_domains=domains, summary=summary, checks=checks,
        warnings=warnings, unknowns=unknowns, environment=environment,
        duration_ms=elapsed_ms(started) if started is not None else 0, artifacts=artifacts,
    )


def preflight(
    *, repo: str | Path, base_ref: str = "HEAD", workspace_root: str | Path | None = None,
    allow_dirty: bool = False, require_commit: bool = True, required_tools: Sequence[str] = (),
    timeout: float = DEFAULT_TIMEOUT, domains: Sequence[str] = ("CODE",),
) -> dict[str, Any]:
    started = monotonic()
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []
    root = _repo_root(repo, timeout=timeout)
    base_commit = _commit(root, base_ref, timeout=timeout)
    work_root = Path(workspace_root).expanduser().resolve() if workspace_root else _default_workspace_root(root)

    git_path = shutil.which("git")
    checks.append(make_check("ovp.git", "PASS" if git_path else "FAIL", required=True,
                             message="Git executable is available." if git_path else "Git executable is unavailable.",
                             details={"path": git_path or ""}))
    clean = _clean(root, timeout=timeout)
    if clean:
        checks.append(make_check("ovp.repo_clean", "PASS", required=True, message="Leader checkout is clean."))
    elif allow_dirty:
        checks.append(make_check("ovp.repo_clean", "WARN", required=False,
                                 message="Leader checkout is dirty; explicit allow-dirty was supplied."))
        warnings.append({"id": "ovp.repo_dirty", "message": "Leader checkout contains existing changes."})
    else:
        checks.append(make_check("ovp.repo_clean", "FAIL", required=True,
                                 message="Leader checkout must be clean before mutation fan-out."))

    state_root = _state_root(root, timeout=timeout)
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        marker = state_root / f".preflight-write-{uuid4().hex}.tmp"
        marker.write_text("ok\n", encoding="utf-8")
        marker.unlink()
        checks.append(make_check("ovp.state_write", "PASS", required=True,
                                 message="OVP state storage is writable.", details={"path": str(state_root)}))
    except OSError as exc:
        checks.append(make_check("ovp.state_write", "FAIL", required=True,
                                 message="OVP state storage is not writable.", evidence=[type(exc).__name__]))

    for tool in sorted(set(required_tools)):
        if not tool or os.path.basename(tool) != tool:
            raise ValueError("required tools must be executable names without path separators")
        found = shutil.which(tool)
        checks.append(make_check(f"ovp.tool.{tool}", "PASS" if found else "FAIL", required=True,
                                 message=f"Required tool {tool} {'is available' if found else 'is unavailable'}.",
                                 details={"path": found or ""}))

    disposable = work_root / f".preflight-{uuid4().hex[:12]}"
    added = False
    try:
        work_root.mkdir(parents=True, exist_ok=True)
        if disposable.exists():
            raise RuntimeError("preflight workspace collision")
        cp = _git(root, ["worktree", "add", "--detach", str(disposable), base_commit], timeout=timeout, check=False)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout).strip()[:500]
            checks.append(make_check("ovp.worktree_roundtrip", "FAIL", required=True,
                                     message="Disposable worktree could not be created.", evidence=[detail]))
        else:
            added = True
            probe = disposable / ".mado-ovp-write-probe"
            probe.write_text("ok\n", encoding="utf-8")
            probe.unlink()
            checks.append(make_check("ovp.worktree_write", "PASS", required=True,
                                     message="Disposable worker workspace is writable."))
            if require_commit:
                ident = _git(disposable, ["var", "GIT_AUTHOR_IDENT"], timeout=timeout, check=False)
                ident_ok = ident.returncode == 0 and bool(ident.stdout.strip())
                checks.append(make_check("ovp.commit_identity", "PASS" if ident_ok else "FAIL", required=True,
                                         message="Git commit identity is configured." if ident_ok else "Git commit identity is not configured.",
                                         evidence=[(ident.stderr or ident.stdout).strip()[:300]] if not ident_ok else []))
                if ident_ok:
                    commit = _git(disposable, ["commit", "--allow-empty", "-m", "mado-loop ovp preflight"], timeout=timeout, check=False)
                    commit_ok = commit.returncode == 0
                    checks.append(make_check("ovp.commit_roundtrip", "PASS" if commit_ok else "FAIL", required=True,
                                             message="Disposable worker commit succeeded." if commit_ok else "Disposable worker commit failed.",
                                             evidence=[(commit.stderr or commit.stdout).strip()[:500]] if not commit_ok else []))
            checks.append(make_check("ovp.worktree_roundtrip", "PASS", required=True,
                                     message="Disposable worktree was created successfully."))
    except OSError as exc:
        checks.append(make_check("ovp.worktree_write", "FAIL", required=True,
                                 message="Disposable workspace is not writable.", evidence=[type(exc).__name__]))
    finally:
        if added:
            rm = _git(root, ["worktree", "remove", "--force", str(disposable)], timeout=timeout, check=False)
            if rm.returncode != 0:
                warnings.append({"id": "ovp.preflight_cleanup", "message": "Disposable worktree cleanup failed."})
                _git(root, ["worktree", "prune"], timeout=timeout, check=False)
        if disposable.exists():
            try:
                shutil.rmtree(disposable)
            except OSError:
                warnings.append({"id": "ovp.preflight_path_cleanup", "message": "Disposable workspace path remains on disk."})

    return _result(
        "ovp_preflight", summary="OVP mutation preflight completed.", domains=list(domains), checks=checks,
        warnings=warnings, unknowns=unknowns,
        environment={"repo": str(root), "base_ref": base_ref, "base_commit": base_commit,
                     "workspace_root": str(work_root), "require_commit": require_commit}, started=started,
    )


def prepare_task(
    *, repo: str | Path, task_id: str, goal: str, include: Sequence[str], acceptance: Sequence[str],
    optional_acceptance: Sequence[str] = (), exclude: Sequence[str] = (), base_ref: str = "HEAD",
    workspace_root: str | Path | None = None, branch: str | None = None,
    domains: Sequence[str] = ("CODE",), do: Sequence[str] = (), keep: Sequence[str] = (),
    no: Sequence[str] = (), out: Sequence[str] = (), risk: Sequence[str] = (),
    required_tools: Sequence[str] = (), allow_dirty: bool = False, timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    task_id = _validate_task_id(task_id)
    if not goal.strip():
        raise ValueError("goal is required")
    include_patterns = [_safe_pattern(x) for x in include]
    exclude_patterns = [_safe_pattern(x) for x in exclude]
    if not include_patterns:
        raise ValueError("at least one --include scope is required")
    required_accept = _parse_assignment(acceptance, kind="acceptance")
    optional_accept = _parse_assignment(optional_acceptance, kind="optional acceptance")
    overlap = sorted(set(required_accept).intersection(optional_accept))
    if overlap:
        raise ValueError(f"acceptance ids cannot be both required and optional: {overlap}")
    if not required_accept:
        raise ValueError("at least one required acceptance criterion is required")

    root = _repo_root(repo, timeout=timeout)
    check = preflight(repo=root, base_ref=base_ref, workspace_root=workspace_root, allow_dirty=allow_dirty,
                      require_commit=True, required_tools=required_tools, timeout=timeout, domains=domains)
    if check["status"] not in {"PASS", "WARN"}:
        return check
    base_commit = str(check["environment"]["base_commit"])
    work_root = Path(str(check["environment"]["workspace_root"])).resolve()
    workspace = (work_root / task_id).resolve()
    try:
        workspace.relative_to(work_root)
    except ValueError as exc:
        raise ValueError("workspace escaped configured workspace root") from exc
    branch_name = branch or f"mado/ovp/{task_id}"
    if not branch_name or any(ch.isspace() for ch in branch_name):
        raise ValueError("branch name must be non-empty and contain no whitespace")
    branch_check = _git(root, ["check-ref-format", "--branch", branch_name], timeout=timeout, check=False)
    if branch_check.returncode != 0:
        raise ValueError(f"invalid git branch name: {branch_name}")

    with _task_lock(root, task_id, timeout=timeout):
        manifest_path = _manifest_path(root, task_id, timeout=timeout)
        if manifest_path.exists():
            raise ValueError(f"OVP task id already exists: {task_id}")
        if workspace.exists():
            raise ValueError(f"worker workspace already exists: {workspace}")
        ref_check = _git(root, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"], timeout=timeout, check=False)
        if ref_check.returncode == 0:
            raise ValueError(f"worker branch already exists: {branch_name}")

        cp = _git(root, ["worktree", "add", "-b", branch_name, str(workspace), base_commit], timeout=timeout, check=False)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout).strip()[:800]
            return _result(
                "ovp_prepare", summary="OVP task workspace creation failed.", domains=list(domains),
                checks=[make_check("ovp.workspace_create", "FAIL", required=True,
                                   message="Worker worktree could not be created.", evidence=[detail])],
                environment={"repo": str(root), "task_id": task_id, "workspace": str(workspace)}, started=started,
            )

        acceptance_items = [
            {"id": key, "description": required_accept[key], "required": True}
            for key in sorted(required_accept)
        ] + [
            {"id": key, "description": optional_accept[key], "required": False}
            for key in sorted(optional_accept)
        ]
        manifest: dict[str, Any] = {
            "ovp_schema_version": OVP_SCHEMA_VERSION,
            "task_id": task_id,
            "state": "READY",
            "created_at": _now(),
            "updated_at": _now(),
            "leader_repo": str(root),
            "base_ref": base_ref,
            "base_commit": base_commit,
            "worker_branch": branch_name,
            "workspace_root": str(work_root),
            "workspace": str(workspace),
            "task_domains": list(domains),
            "scope": {"include": include_patterns, "exclude": exclude_patterns},
            "acceptance": acceptance_items,
            "contract": {
                "goal": goal.strip(), "do": list(do), "keep": list(keep), "no": list(no),
                "out": list(out), "risk": list(risk),
            },
            "history": [{"state": "READY", "at": _now(), "actor": "orchestrator", "reason": "workspace prepared"}],
            "receipt": None,
            "review": None,
            "integration": None,
            "proof": None,
            "cleanup": None,
        }
        path = _save_manifest(root, task_id, manifest, timeout=timeout)
        contract_path = path.parent / "AI_CREOLE.txt"
        _atomic_text(contract_path, _render_contract(manifest))

    return _result(
        "ovp_prepare", summary="OVP mutation workspace is READY.", domains=list(domains),
        checks=[make_check("ovp.workspace_create", "PASS", required=True,
                           message="Worker worktree and branch were created."),
                make_check("ovp.contract", "PASS", required=True,
                           message="AI Creole worker contract was written.")],
        artifacts=[make_artifact(contract_path, "ai_creole_contract"), make_artifact(path, "ovp_manifest")],
        environment={"repo": str(root), "task_id": task_id, "ovp_state": "READY",
                     "workspace": str(workspace), "worker_branch": branch_name,
                     "base_commit": base_commit, "contract_path": str(contract_path)}, started=started,
    )


def mark_task(*, repo: str | Path, task_id: str, state: str, reason: str = "", timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    started = monotonic()
    root = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    allowed = {"DISPATCHED": {"READY", "REWORK"}, "WORKING": {"DISPATCHED", "REWORK"}}
    if state not in allowed:
        raise ValueError("mark only supports DISPATCHED or WORKING")
    with _task_lock(root, task_id, timeout=timeout):
        manifest = _load_manifest(root, task_id, timeout=timeout)
        if manifest["state"] not in allowed[state]:
            raise ValueError(f"invalid OVP transition: {manifest['state']} -> {state}")
        manifest["state"] = state
        manifest["updated_at"] = _now()
        manifest["history"].append({"state": state, "at": _now(), "actor": "orchestrator", "reason": reason or "state advanced"})
        _save_manifest(root, task_id, manifest, timeout=timeout)
    return _result("ovp_mark", summary=f"OVP task moved to {state}.", domains=manifest["task_domains"],
                   checks=[make_check("ovp.transition", "PASS", required=True, message="State transition is valid.")],
                   environment={"repo": str(root), "task_id": task_id, "ovp_state": state}, started=started)


def _changed_paths(workspace: Path, base_commit: str, *, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    committed = _git(workspace, ["diff", "--name-only", f"{base_commit}..HEAD"], timeout=timeout).stdout.splitlines()
    status = _git(workspace, ["status", "--porcelain=v1", "--untracked-files=all"], timeout=timeout).stdout.splitlines()
    uncommitted: list[str] = []
    for line in status:
        if len(line) >= 4:
            value = line[3:]
            if " -> " in value:
                value = value.split(" -> ", 1)[1]
            uncommitted.append(value.strip().replace("\\", "/"))
    return sorted(set(x.strip().replace("\\", "/") for x in committed + uncommitted if x.strip()))


def submit_receipt(
    *, repo: str | Path, task_id: str, summary: str, checks: Sequence[str], optional_checks: Sequence[str] = (),
    evidence: Sequence[str] = (), artifacts: Sequence[str] = (), risks: Sequence[str] = (),
    assumptions: Sequence[str] = (), timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    root = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    if not summary.strip():
        raise ValueError("receipt summary is required")
    required_status = _parse_assignment(checks, kind="check")
    optional_status = _parse_assignment(optional_checks, kind="optional check")
    evidence_map = _parse_assignment(evidence, kind="evidence") if evidence else {}
    overlap = sorted(set(required_status).intersection(optional_status))
    if overlap:
        raise ValueError(f"check ids cannot be both required and optional: {overlap}")
    for value in list(required_status.values()) + list(optional_status.values()):
        if value not in RECEIPT_STATUSES:
            raise ValueError(f"invalid receipt check status: {value}")

    with _task_lock(root, task_id, timeout=timeout):
        manifest = _load_manifest(root, task_id, timeout=timeout)
        if manifest["state"] not in {"READY", "DISPATCHED", "WORKING", "REWORK"}:
            raise ValueError(f"receipt cannot be submitted from state {manifest['state']}")
        workspace = Path(manifest["workspace"]).resolve()
        if root != workspace:
            supplied_common = _common_git_dir(root, timeout=timeout)
            workspace_common = _common_git_dir(workspace, timeout=timeout)
            if supplied_common != workspace_common:
                raise ValueError("receipt repository does not belong to the task repository")
        actual_workspace = _repo_root(workspace, timeout=timeout)
        if actual_workspace != workspace:
            raise RuntimeError("recorded worker workspace is no longer a git worktree root")
        branch = _current_branch(workspace, timeout=timeout)
        if branch != manifest["worker_branch"]:
            raise RuntimeError("worker workspace branch no longer matches the task manifest")
        head = _commit(workspace, "HEAD", timeout=timeout)
        if head == manifest["base_commit"]:
            raise ValueError("mutation worker has no committed change to review")
        if not _clean(workspace, timeout=timeout):
            raise ValueError("worker workspace must be clean before REVIEW_READY")
        changed = _changed_paths(workspace, manifest["base_commit"], timeout=timeout)
        if not changed:
            raise ValueError("mutation worker commit does not change repository files")
        violations = _scope_violations(changed, manifest["scope"]["include"], manifest["scope"]["exclude"])
        if violations:
            return _result(
                "ovp_receipt", summary="Mutation receipt rejected because changes escaped scope.", domains=manifest["task_domains"],
                checks=[make_check("ovp.scope", "FAIL", required=True, message="Worker changed files outside assigned scope.", evidence=violations)],
                environment={"repo": str(Path(manifest["leader_repo"])), "task_id": task_id,
                             "workspace": str(workspace), "ovp_state": manifest["state"]}, started=started,
            )

        acceptance_by_id = {item["id"]: item for item in manifest["acceptance"]}
        reported_ids = set(required_status) | set(optional_status)
        missing = sorted(set(acceptance_by_id).difference(reported_ids))
        extra = sorted(reported_ids.difference(acceptance_by_id))
        if missing or extra:
            raise ValueError(f"receipt checks must match acceptance ids; missing={missing}, extra={extra}")
        receipt_checks = []
        for check_id in sorted(acceptance_by_id):
            expected = acceptance_by_id[check_id]
            if expected["required"]:
                if check_id not in required_status:
                    raise ValueError(f"required acceptance must be reported with --check: {check_id}")
                status = required_status[check_id]
            else:
                if check_id not in optional_status:
                    raise ValueError(f"optional acceptance must be reported with --optional-check: {check_id}")
                status = optional_status[check_id]
            receipt_checks.append({
                "id": check_id, "status": status, "required": bool(expected["required"]),
                "description": expected["description"], "evidence": [evidence_map[check_id]] if check_id in evidence_map else [],
            })

        artifact_items: list[dict[str, Any]] = []
        for item in artifacts:
            p = Path(item)
            if not p.is_absolute():
                p = (workspace / p).resolve()
            artifact_items.append(make_artifact(p, "worker_evidence"))
        receipt = {
            "submitted_at": _now(), "summary": summary.strip(), "worker_head": head,
            "worker_branch": branch, "changed_files": changed, "checks": receipt_checks,
            "artifacts": artifact_items, "risks": list(risks), "assumptions": list(assumptions),
            "authority": "final acceptance and integration remain with the orchestrator",
        }
        receipt_path = _task_dir(Path(manifest["leader_repo"]), task_id, timeout=timeout) / "receipt.json"
        _atomic_json(receipt_path, receipt)
        manifest["receipt"] = receipt
        manifest["state"] = "REVIEW_READY"
        manifest["updated_at"] = _now()
        manifest["history"].append({"state": "REVIEW_READY", "at": _now(), "actor": "mutation_worker", "reason": "evidence receipt submitted"})
        leader = Path(manifest["leader_repo"])
        _save_manifest(leader, task_id, manifest, timeout=timeout)

    warnings = []
    for item in receipt_checks:
        if not item["required"] and item["status"] != "PASS":
            warnings.append({"id": f"ovp.optional_check.{item['id']}", "message": f"Optional check {item['id']} is {item['status']}."})
    result_checks = [make_check("ovp.scope", "PASS", required=True, message="All changed files are inside assigned scope.")]
    result_checks.extend(make_check(f"ovp.worker_check.{item['id']}", item["status"], required=item["required"],
                                    message=item["description"], evidence=item["evidence"]) for item in receipt_checks)
    return _result(
        "ovp_receipt", summary="Mutation worker reached REVIEW_READY.", domains=manifest["task_domains"], checks=result_checks,
        warnings=warnings, artifacts=[make_artifact(receipt_path, "mutation_receipt")],
        environment={"repo": str(leader), "task_id": task_id, "workspace": str(workspace),
                     "worker_branch": branch, "worker_head": head, "ovp_state": "REVIEW_READY"}, started=started,
    )


def review_task(
    *, repo: str | Path, task_id: str, decision: str, reason: str, inspected_diff: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    leader = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    if decision not in {"accept", "rework", "reject"}:
        raise ValueError("decision must be accept, rework, or reject")
    if not reason.strip():
        raise ValueError("review reason is required")
    with _task_lock(leader, task_id, timeout=timeout):
        manifest = _load_manifest(leader, task_id, timeout=timeout)
        if Path(manifest["leader_repo"]).resolve() != leader:
            raise ValueError("review must run from the recorded leader checkout")
        if manifest["state"] != "REVIEW_READY":
            raise ValueError(f"review requires REVIEW_READY, found {manifest['state']}")
        receipt = manifest.get("receipt")
        if not isinstance(receipt, dict):
            raise RuntimeError("REVIEW_READY task is missing a receipt")
        workspace = Path(manifest["workspace"]).resolve()
        current_head = _commit(workspace, "HEAD", timeout=timeout)
        current_branch = _current_branch(workspace, timeout=timeout)
        changed = _changed_paths(workspace, manifest["base_commit"], timeout=timeout)
        violations = _scope_violations(changed, manifest["scope"]["include"], manifest["scope"]["exclude"])
        diff_check = _git(workspace, ["diff", "--check", f"{manifest['base_commit']}..{current_head}"], timeout=timeout, check=False)
        workspace_clean = _clean(workspace, timeout=timeout)

        checks = [
            make_check("ovp.review.workspace_clean", "PASS" if workspace_clean else "FAIL", required=True,
                       message="Worker workspace is clean." if workspace_clean else "Worker workspace changed after receipt."),
            make_check("ovp.review.head_stable", "PASS" if current_head == receipt.get("worker_head") else "FAIL", required=True,
                       message="Worker HEAD matches the submitted receipt." if current_head == receipt.get("worker_head") else "Worker HEAD changed after receipt."),
            make_check("ovp.review.branch_stable", "PASS" if current_branch == manifest["worker_branch"] else "FAIL", required=True,
                       message="Worker branch identity is stable." if current_branch == manifest["worker_branch"] else "Worker branch identity changed."),
            make_check("ovp.review.scope", "PASS" if not violations else "FAIL", required=True,
                       message="Worker changes remain inside assigned scope." if not violations else "Worker changes escaped assigned scope.", evidence=violations),
            make_check("ovp.review.diff_check", "PASS" if diff_check.returncode == 0 else "FAIL", required=True,
                       message="git diff --check passed." if diff_check.returncode == 0 else "git diff --check found patch errors.",
                       evidence=[(diff_check.stdout or diff_check.stderr).strip()[:1000]] if diff_check.returncode else []),
            make_check("ovp.review.diff_inspected", "PASS" if inspected_diff else "FAIL", required=True,
                       message="Orchestrator confirmed diff inspection." if inspected_diff else "Acceptance requires explicit diff inspection."),
        ]
        for item in receipt["checks"]:
            checks.append(make_check(f"ovp.review.worker_check.{item['id']}", item["status"], required=bool(item["required"]),
                                     message=item["description"], evidence=item.get("evidence", [])))

        blocking = any(c["required"] and c["status"] != "PASS" for c in checks)
        if decision == "accept" and blocking:
            return _result(
                "ovp_review", summary="OVP acceptance blocked by review gate.", domains=manifest["task_domains"], checks=checks,
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "REVIEW_READY"}, started=started,
            )
        target_state = {"accept": "ACCEPTED", "rework": "REWORK", "reject": "REJECTED"}[decision]
        manifest["state"] = target_state
        manifest["updated_at"] = _now()
        manifest["review"] = {"decision": decision, "reason": reason.strip(), "at": _now(),
                              "inspected_diff": bool(inspected_diff), "worker_head": current_head}
        manifest["history"].append({"state": target_state, "at": _now(), "actor": "orchestrator", "reason": reason.strip()})
        _save_manifest(leader, task_id, manifest, timeout=timeout)

    if decision != "accept":
        checks = [make_check("ovp.review.decision", "PASS", required=True,
                             message=f"Orchestrator recorded decision {decision}.")]
    return _result(
        "ovp_review", summary=f"OVP review decision recorded: {target_state}.", domains=manifest["task_domains"], checks=checks,
        environment={"repo": str(leader), "task_id": task_id, "ovp_state": target_state,
                     "worker_head": current_head}, started=started,
    )


def integrate_task(
    *, repo: str | Path, task_id: str, strategy: str = "merge", timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    leader = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    if strategy not in {"merge", "cherry-pick"}:
        raise ValueError("strategy must be merge or cherry-pick")
    with _task_lock(leader, task_id, timeout=timeout):
        manifest = _load_manifest(leader, task_id, timeout=timeout)
        if Path(manifest["leader_repo"]).resolve() != leader:
            raise ValueError("integration must run from the recorded leader checkout")
        if manifest["state"] != "ACCEPTED":
            raise ValueError(f"integration requires ACCEPTED, found {manifest['state']}")
        if not _clean(leader, timeout=timeout):
            return _result(
                "ovp_integrate", summary="Integration blocked because leader checkout is dirty.", domains=manifest["task_domains"],
                checks=[make_check("ovp.integrate.repo_clean", "FAIL", required=True,
                                   message="Leader checkout must be clean before integration.")],
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "ACCEPTED"}, started=started,
            )
        leader_branch = _current_branch(leader, timeout=timeout)
        if leader_branch is None:
            raise ValueError("leader checkout must be on a branch")
        if leader_branch == manifest["worker_branch"]:
            raise ValueError("leader checkout cannot be the worker branch")
        worker_head = _commit(leader, manifest["worker_branch"], timeout=timeout)
        receipt_head = manifest["receipt"]["worker_head"]
        if worker_head != receipt_head:
            return _result(
                "ovp_integrate", summary="Integration blocked because worker branch moved after review.", domains=manifest["task_domains"],
                checks=[make_check("ovp.integrate.worker_head_stable", "FAIL", required=True,
                                   message="Worker branch HEAD no longer matches the accepted receipt.")],
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "ACCEPTED"}, started=started,
            )
        ancestor = _git(leader, ["merge-base", "--is-ancestor", manifest["base_commit"], "HEAD"], timeout=timeout, check=False)
        if ancestor.returncode != 0:
            return _result(
                "ovp_integrate", summary="Integration blocked because leader history no longer contains the task base.", domains=manifest["task_domains"],
                checks=[make_check("ovp.integrate.base_ancestor", "FAIL", required=True,
                                   message="Task base commit is not an ancestor of current leader HEAD.")],
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "ACCEPTED"}, started=started,
            )
        before = _commit(leader, "HEAD", timeout=timeout)
        if strategy == "merge":
            cp = _git(leader, ["merge", "--no-ff", "--no-edit", manifest["worker_branch"]], timeout=timeout, check=False)
            if cp.returncode != 0:
                _git(leader, ["merge", "--abort"], timeout=timeout, check=False)
        else:
            revs = _git(leader, ["rev-list", "--reverse", f"{manifest['base_commit']}..{worker_head}"], timeout=timeout).stdout.split()
            if not revs:
                raise RuntimeError("accepted worker branch contains no commits to integrate")
            cp = _git(leader, ["cherry-pick", *revs], timeout=timeout, check=False)
            if cp.returncode != 0:
                _git(leader, ["cherry-pick", "--abort"], timeout=timeout, check=False)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout).strip()[:1200]
            return _result(
                "ovp_integrate", summary="Integration failed and was aborted.", domains=manifest["task_domains"],
                checks=[make_check("ovp.integrate.apply", "FAIL", required=True,
                                   message="Accepted worker change could not be integrated cleanly.", evidence=[detail])],
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "ACCEPTED",
                             "strategy": strategy, "leader_head_before": before}, started=started,
            )
        after = _commit(leader, "HEAD", timeout=timeout)
        manifest["state"] = "INTEGRATED"
        manifest["updated_at"] = _now()
        manifest["integration"] = {"strategy": strategy, "at": _now(), "leader_branch": leader_branch,
                                   "leader_head_before": before, "leader_head_after": after,
                                   "worker_head": worker_head}
        manifest["history"].append({"state": "INTEGRATED", "at": _now(), "actor": "orchestrator",
                                    "reason": f"integrated with {strategy}"})
        _save_manifest(leader, task_id, manifest, timeout=timeout)
    return _result(
        "ovp_integrate", summary="Accepted worker change was integrated; P0-P5 proof is still required.",
        domains=manifest["task_domains"],
        checks=[make_check("ovp.integrate.apply", "PASS", required=True, message="Integration completed successfully.")],
        environment={"repo": str(leader), "task_id": task_id, "ovp_state": "INTEGRATED", "strategy": strategy,
                     "leader_head_before": before, "leader_head_after": after}, started=started,
    )


def record_proof(
    *, repo: str | Path, task_id: str, result_path: str | Path, timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    leader = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    proof_path = Path(result_path).expanduser().resolve()
    if not proof_path.is_file():
        raise ValueError(f"proof result does not exist: {proof_path}")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("proof result is not valid JSON") from exc
    if proof.get("schema_version") != "1.1":
        raise ValueError("proof result must use MADO LOOP schema_version 1.1")
    status = proof.get("status")
    if status not in {"PASS", "WARN", "FAIL", "UNKNOWN", "SKIPPED"}:
        raise ValueError("proof result contains an invalid status")
    proof_level = proof.get("proof_level")
    if proof_level not in {"P0", "P1", "P2", "P3", "P4", "P5"}:
        raise ValueError("proof result must contain a P0-P5 proof_level")
    data = proof_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    target_state = "PROVEN" if status in {"PASS", "WARN"} else "FAILED" if status == "FAIL" else "UNKNOWN"
    with _task_lock(leader, task_id, timeout=timeout):
        manifest = _load_manifest(leader, task_id, timeout=timeout)
        if manifest["state"] != "INTEGRATED":
            raise ValueError(f"proof can only be recorded from INTEGRATED, found {manifest['state']}")
        current_head = _commit(leader, "HEAD", timeout=timeout)
        if current_head != manifest["integration"]["leader_head_after"]:
            return _result(
                "ovp_proof", summary="Proof recording blocked because leader HEAD moved after integration.", domains=manifest["task_domains"],
                checks=[make_check("ovp.proof.head_stable", "FAIL", required=True,
                                   message="Leader HEAD no longer matches the integrated task state.")],
                environment={"repo": str(leader), "task_id": task_id, "ovp_state": "INTEGRATED"}, started=started,
            )
        manifest["state"] = target_state
        manifest["updated_at"] = _now()
        manifest["proof"] = {"at": _now(), "result_path": str(proof_path), "sha256": digest,
                             "result_status": status, "proof_level": proof_level,
                             "leader_head": current_head, "final_state": target_state}
        manifest["history"].append({"state": target_state, "at": _now(), "actor": "proof_system",
                                    "reason": f"schema-v1.1 result {status} at {proof_level}"})
        _save_manifest(leader, task_id, manifest, timeout=timeout)
    proof_warnings = ([{"id": "ovp.proof.warn", "message": "Proof supports the outcome with warnings."}]
                      if status == "WARN" else [])
    return _result(
        "ovp_proof", summary=f"Integrated task proof recorded as {target_state}.", domains=manifest["task_domains"],
        checks=[make_check("ovp.proof.result", "PASS" if status in {"PASS", "WARN"} else status, required=True,
                           message=f"Recorded schema-v1.1 proof result {status} at {proof_level}.")],
        warnings=proof_warnings, artifacts=[make_artifact(proof_path, "proof_result")],
        environment={"repo": str(leader), "task_id": task_id, "ovp_state": target_state,
                     "proof_level": proof_level, "proof_result_status": status}, started=started,
    )


def cleanup_task(
    *, repo: str | Path, task_id: str, delete_branch: bool = False, timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    started = monotonic()
    leader = _repo_root(repo, timeout=timeout)
    task_id = _validate_task_id(task_id)
    warnings: list[dict[str, Any]] = []
    with _task_lock(leader, task_id, timeout=timeout):
        manifest = _load_manifest(leader, task_id, timeout=timeout)
        if manifest["state"] not in FINAL_STATES:
            raise ValueError(f"cleanup requires a final or rejected state, found {manifest['state']}")
        workspace = Path(manifest["workspace"]).resolve()
        work_root = Path(manifest["workspace_root"]).resolve()
        try:
            workspace.relative_to(work_root)
        except ValueError as exc:
            raise RuntimeError("recorded workspace escaped its ownership root; refusing cleanup") from exc
        if workspace == work_root:
            raise RuntimeError("recorded workspace equals ownership root; refusing cleanup")
        checks = []
        if workspace.exists():
            if not _clean(workspace, timeout=timeout):
                return _result(
                    "ovp_cleanup", summary="Cleanup blocked because worker workspace is dirty.", domains=manifest["task_domains"],
                    checks=[make_check("ovp.cleanup.workspace_clean", "FAIL", required=True,
                                       message="Worker workspace contains uncommitted changes; refusing removal.")],
                    environment={"repo": str(leader), "task_id": task_id, "ovp_state": manifest["state"],
                                 "workspace": str(workspace)}, started=started,
                )
            rm = _git(leader, ["worktree", "remove", str(workspace)], timeout=timeout, check=False)
            ok = rm.returncode == 0
            checks.append(make_check("ovp.cleanup.worktree", "PASS" if ok else "FAIL", required=True,
                                     message="Worker worktree was removed." if ok else "Worker worktree removal failed.",
                                     evidence=[(rm.stderr or rm.stdout).strip()[:800]] if not ok else []))
            if not ok:
                return _result("ovp_cleanup", summary="Worker worktree cleanup failed.", domains=manifest["task_domains"],
                               checks=checks, environment={"repo": str(leader), "task_id": task_id,
                                                           "ovp_state": manifest["state"]}, started=started)
        else:
            checks.append(make_check("ovp.cleanup.worktree", "PASS", required=True,
                                     message="Worker worktree is already absent."))
        branch_deleted = False
        if delete_branch:
            cp = _git(leader, ["branch", "-d", manifest["worker_branch"]], timeout=timeout, check=False)
            branch_deleted = cp.returncode == 0
            if branch_deleted:
                checks.append(make_check("ovp.cleanup.branch", "PASS", required=False,
                                         message="Merged worker branch was deleted."))
            else:
                checks.append(make_check("ovp.cleanup.branch", "SKIPPED", required=False,
                                         message="Worker branch was preserved because safe deletion was not possible.",
                                         evidence=[(cp.stderr or cp.stdout).strip()[:600]]))
                warnings.append({"id": "ovp.branch_preserved", "message": "Worker branch was not safely deletable and remains available."})
        manifest["updated_at"] = _now()
        manifest["cleanup"] = {"at": _now(), "workspace_removed": not workspace.exists(),
                               "branch_delete_requested": delete_branch, "branch_deleted": branch_deleted}
        _save_manifest(leader, task_id, manifest, timeout=timeout)
    return _result(
        "ovp_cleanup", summary="OVP worker workspace cleanup completed.", domains=manifest["task_domains"], checks=checks,
        warnings=warnings, environment={"repo": str(leader), "task_id": task_id, "ovp_state": manifest["state"],
                                       "workspace": str(workspace), "branch_deleted": branch_deleted}, started=started,
    )


def task_status(*, repo: str | Path, task_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    started = monotonic()
    root = _repo_root(repo, timeout=timeout)
    manifest = _load_manifest(root, _validate_task_id(task_id), timeout=timeout)
    return _result(
        "ovp_status", summary=f"OVP task is {manifest['state']}.", domains=manifest["task_domains"],
        checks=[make_check("ovp.manifest", "PASS", required=True, message="OVP manifest is valid and readable.")],
        artifacts=[make_artifact(_manifest_path(root, task_id, timeout=timeout), "ovp_manifest")],
        environment={"repo": str(Path(manifest["leader_repo"])), "task_id": task_id,
                     "ovp_state": manifest["state"], "workspace": manifest["workspace"],
                     "worker_branch": manifest["worker_branch"], "base_commit": manifest["base_commit"]}, started=started,
    )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository or worktree path")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--pretty", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight", help="validate worker-equivalent mutation prerequisites")
    _add_common(p)
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--workspace-root")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--require-tool", action="append", default=[])
    p.add_argument("--domain", action="append", default=[])

    p = sub.add_parser("prepare", help="create an isolated mutation worktree and AI Creole contract")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--exclude", action="append", default=[])
    p.add_argument("--acceptance", action="append", default=[])
    p.add_argument("--optional-acceptance", action="append", default=[])
    p.add_argument("--base-ref", default="HEAD")
    p.add_argument("--workspace-root")
    p.add_argument("--branch")
    p.add_argument("--domain", action="append", default=[])
    p.add_argument("--do", action="append", default=[])
    p.add_argument("--keep", action="append", default=[])
    p.add_argument("--no", action="append", default=[])
    p.add_argument("--out", action="append", default=[])
    p.add_argument("--risk", action="append", default=[])
    p.add_argument("--require-tool", action="append", default=[])
    p.add_argument("--allow-dirty", action="store_true")

    p = sub.add_parser("mark", help="record DISPATCHED or WORKING state")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--reason", default="")

    p = sub.add_parser("receipt", help="submit committed worker evidence and stop at REVIEW_READY")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--check", action="append", default=[])
    p.add_argument("--optional-check", action="append", default=[])
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument("--artifact", action="append", default=[])
    p.add_argument("--risk", action="append", default=[])
    p.add_argument("--assumption", action="append", default=[])

    p = sub.add_parser("review", help="run structural review gate and record orchestrator decision")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--inspected-diff", action="store_true")

    p = sub.add_parser("integrate", help="merge or cherry-pick an ACCEPTED worker branch")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--strategy", choices=("merge", "cherry-pick"), default="merge")

    p = sub.add_parser("proof", help="record schema-v1.1 P0-P5 proof for the integrated state")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--result", required=True)

    p = sub.add_parser("cleanup", help="remove an owned worker worktree after a final decision")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    p.add_argument("--delete-branch", action="store_true")

    p = sub.add_parser("status", help="read current OVP task state")
    _add_common(p)
    p.add_argument("--task-id", required=True)
    return parser


def human_output(payload: Mapping[str, Any]) -> str:
    env = payload.get("environment", {})
    lines = [f"{payload['tool']}: {payload['status']}", str(payload["summary"])]
    if env.get("task_id"):
        lines.append(f"task={env['task_id']} state={env.get('ovp_state', 'n/a')}")
    for check in payload.get("checks", []):
        lines.append(f"[{check['status']}] {check['id']}: {check['message']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        if not 0 < args.timeout <= 120:
            raise ValueError("timeout must be greater than 0 and at most 120 seconds")
        common = {"repo": args.repo, "timeout": args.timeout}
        if args.command == "preflight":
            payload = preflight(**common, base_ref=args.base_ref, workspace_root=args.workspace_root,
                                allow_dirty=args.allow_dirty, required_tools=args.require_tool, domains=args.domain or ["CODE"])
        elif args.command == "prepare":
            payload = prepare_task(**common, task_id=args.task_id, goal=args.goal, include=args.include,
                                   exclude=args.exclude, acceptance=args.acceptance, optional_acceptance=args.optional_acceptance,
                                   base_ref=args.base_ref, workspace_root=args.workspace_root, branch=args.branch,
                                   domains=args.domain or ["CODE"], do=args.do, keep=args.keep, no=args.no, out=args.out, risk=args.risk,
                                   required_tools=args.require_tool, allow_dirty=args.allow_dirty)
        elif args.command == "mark":
            payload = mark_task(**common, task_id=args.task_id, state=args.state, reason=args.reason)
        elif args.command == "receipt":
            payload = submit_receipt(**common, task_id=args.task_id, summary=args.summary, checks=args.check,
                                     optional_checks=args.optional_check, evidence=args.evidence, artifacts=args.artifact,
                                     risks=args.risk, assumptions=args.assumption)
        elif args.command == "review":
            payload = review_task(**common, task_id=args.task_id, decision=args.decision, reason=args.reason,
                                  inspected_diff=args.inspected_diff)
        elif args.command == "integrate":
            payload = integrate_task(**common, task_id=args.task_id, strategy=args.strategy)
        elif args.command == "proof":
            payload = record_proof(**common, task_id=args.task_id, result_path=args.result)
        elif args.command == "cleanup":
            payload = cleanup_task(**common, task_id=args.task_id, delete_branch=args.delete_branch)
        elif args.command == "status":
            payload = task_status(**common, task_id=args.task_id)
        else:
            raise ValueError("unsupported command")
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
        sys.stderr.write(f"ovp_runtime configuration error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:
        sys.stderr.write(f"ovp_runtime internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
