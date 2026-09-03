"""Dispatch isolated OVP mutation workers through bounded provider adapters."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ovp_runtime as ovp  # noqa: E402

SCHEMA_VERSION = "mado-ovp-dispatch/v1"
HANDOFF_SCHEMA_VERSION = "mado-mutation-handoff/v1"
PROVIDERS = ("codex", "claude", "local")
DEFAULT_TIMEOUT = 900.0
MAX_CAPTURE_CHARS = 1_000_000
MAX_HANDOFF_CHARS = 200_000
SAFE_ENV_KEYS = {
    "PATH", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TMP", "TEMP", "TMPDIR",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
}
SECRET_ENV_RE = re.compile(r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH)", re.I)


class DispatchConfigError(ValueError):
    """Raised when a dispatch request is unsafe or incomplete."""


@dataclass(frozen=True)
class ProviderPlan:
    provider: str
    command: tuple[str, ...]
    output_mode: str
    prompt_transport: str = "stdin"
    redact_command: bool = False

    def public_dict(self) -> dict[str, Any]:
        if self.redact_command and len(self.command) > 1:
            command = [self.command[0], f"<{len(self.command) - 1} custom args redacted>"]
        else:
            command = list(self.command)
        return {
            "provider": self.provider,
            "command": command,
            "output_mode": self.output_mode,
            "prompt_transport": self.prompt_transport,
        }


@dataclass(frozen=True)
class WorkerRun:
    status: str
    returncode: int | None
    duration_ms: int
    stdout: str
    stderr: str
    final_message: str | None
    error: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "final_message_present": bool(self.final_message),
            "stdout_chars": len(self.stdout),
            "stderr_chars": len(self.stderr),
            "error": self.error,
        }


def _clean_capture(text: str | None) -> str:
    value = text if isinstance(text, str) else ""
    if len(value) > MAX_CAPTURE_CHARS:
        return value[:MAX_CAPTURE_CHARS] + "\n...[truncated]\n"
    return value


def _public_env_name(name: str) -> str:
    if not name or "=" in name or "\x00" in name:
        raise DispatchConfigError(f"invalid environment variable name: {name!r}")
    return name


def build_worker_env(
    *,
    source: Mapping[str, str] | None = None,
    pass_env: Sequence[str] = (),
    allow_secret_env: bool = False,
) -> tuple[dict[str, str], list[str]]:
    source = source if source is not None else os.environ
    env: dict[str, str] = {}
    inherited: list[str] = []
    for key in sorted(SAFE_ENV_KEYS):
        value = source.get(key)
        if isinstance(value, str):
            env[key] = value
            inherited.append(key)
    for raw in pass_env:
        key = _public_env_name(raw)
        if SECRET_ENV_RE.search(key) and not allow_secret_env:
            raise DispatchConfigError(
                f"refusing secret-looking environment variable {key}; use --allow-secret-env only when the worker is permitted to receive it"
            )
        value = source.get(key)
        if value is None:
            raise DispatchConfigError(f"requested environment variable is not set: {key}")
        env[key] = value
        if key not in inherited:
            inherited.append(key)
    env["MADO_OVP_MUTATION_WORKER"] = "1"
    return env, sorted(inherited)


def _validate_command_json(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DispatchConfigError("--command-json must be a JSON array of strings") from exc
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, str) and item for item in parsed):
        raise DispatchConfigError("--command-json must be a non-empty JSON array of non-empty strings")
    return tuple(parsed)


def build_provider_plan(
    provider: str,
    *,
    workspace: Path,
    command_json: str | None = None,
    executable: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    keep_user_config: bool = False,
) -> ProviderPlan:
    if provider not in PROVIDERS:
        raise DispatchConfigError(f"unsupported provider: {provider}")
    if command_json:
        return ProviderPlan(provider, _validate_command_json(command_json), "raw", redact_command=True)

    if provider == "codex":
        binary = executable or "codex"
        command = [
            binary, "exec", "--json", "--ephemeral", "--color", "never",
            "--sandbox", "workspace-write", "--cd", str(workspace),
        ]
        if model:
            command.extend(["--model", model])
        if reasoning_effort:
            command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        if not keep_user_config:
            command.append("--ignore-user-config")
        command.append("-")
        return ProviderPlan(provider, tuple(command), "codex-jsonl")

    if provider == "claude":
        binary = executable or "claude"
        command = [binary, "-p", "--output-format", "json", "--permission-mode", "acceptEdits"]
        if model:
            command.extend(["--model", model])
        return ProviderPlan(provider, tuple(command), "claude-json")

    raise DispatchConfigError(
        "local provider requires --command-json because MADO LOOP cannot assume a local agent runtime"
    )


def _extract_codex_message(stdout: str) -> str | None:
    final: str | None = None
    for raw in stdout.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                final = text.strip()
    return final


def _extract_claude_message(stdout: str) -> str | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, str):
        return payload.strip() or None
    if not isinstance(payload, dict):
        return text
    for key in ("result", "content", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    content = payload.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        if chunks:
            return "\n".join(chunks).strip()
    return text


def extract_final_message(plan: ProviderPlan, stdout: str) -> str | None:
    if plan.output_mode == "codex-jsonl":
        return _extract_codex_message(stdout)
    if plan.output_mode == "claude-json":
        return _extract_claude_message(stdout)
    text = stdout.strip()
    return text or None


def _json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    fence_re = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S | re.I)
    candidates.extend(match.group(1).strip() for match in fence_re.finditer(text))
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        candidates.append(text[index:index + end])
    return candidates


def parse_handoff(message: str) -> dict[str, Any]:
    if len(message) > MAX_HANDOFF_CHARS:
        raise DispatchConfigError("worker final message exceeds bounded handoff size")
    payload: dict[str, Any] | None = None
    for candidate in reversed(_json_candidates(message)):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == HANDOFF_SCHEMA_VERSION:
            payload = value
            break
    if payload is None:
        raise DispatchConfigError(f"worker did not return {HANDOFF_SCHEMA_VERSION} JSON")
    summary = payload.get("summary")
    checks = payload.get("checks")
    if not isinstance(summary, str) or not summary.strip():
        raise DispatchConfigError("mutation handoff requires a non-empty summary")
    if not isinstance(checks, dict):
        raise DispatchConfigError("mutation handoff requires a checks object")
    for key, status in checks.items():
        if not isinstance(key, str) or not isinstance(status, str) or status not in ovp.RECEIPT_STATUSES:
            raise DispatchConfigError(f"invalid mutation handoff check: {key!r}={status!r}")
    for key in ("evidence", "artifacts", "risks", "assumptions"):
        value = payload.get(key, {} if key == "evidence" else [])
        if key == "evidence":
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                raise DispatchConfigError("handoff evidence must be an object of check-id to evidence string")
        elif not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise DispatchConfigError(f"handoff {key} must be an array of strings")
    return payload


def render_worker_prompt(manifest: Mapping[str, Any], contract_text: str) -> str:
    acceptance = manifest.get("acceptance", [])
    required = [item["id"] for item in acceptance if item.get("required")]
    optional = [item["id"] for item in acceptance if not item.get("required")]
    check_shape = ", ".join(json.dumps(item) + ': "PASS"' for item in required + optional)
    return (
        "MADO LOOP OVP MUTATION WORKER\n"
        "You are operating inside one isolated Git worktree. You may modify only the assigned repository scope.\n"
        "Do not edit another worktree, the leader checkout, credentials, global configuration, or OVP state.\n"
        "Do not review, merge, integrate, run final P0-P5 acceptance, or claim DONE/PROVEN.\n"
        "Implement the bounded task, run the assigned worker-side checks, commit the change on the current worker branch, and leave the worktree clean.\n"
        "Your final response MUST contain exactly one JSON object using schema mado-mutation-handoff/v1.\n"
        "The orchestrator will independently validate Git identity, scope, checks, and receipt.\n\n"
        "AI CREOLE CONTRACT:\n"
        f"{contract_text.rstrip()}\n\n"
        "HANDOFF JSON SHAPE:\n"
        "{\n"
        '  "schema_version": "mado-mutation-handoff/v1",\n'
        '  "summary": "what you changed",\n'
        f'  "checks": {{{check_shape}}},\n'
        '  "evidence": {"check_id": "command or durable evidence path"},\n'
        '  "artifacts": ["repository-relative artifact path"],\n'
        '  "risks": [],\n'
        '  "assumptions": []\n'
        "}\n"
        f"Required check IDs: {json.dumps(required)}\n"
        f"Optional check IDs: {json.dumps(optional)}\n"
        "Allowed check status values: PASS, FAIL, WARN, UNKNOWN, SKIPPED.\n"
        "If a required check cannot be run, report UNKNOWN or SKIPPED rather than inventing success.\n"
    )


def _validate_workspace(
    leader: Path,
    manifest: Mapping[str, Any],
    *,
    resume: bool,
    timeout: float,
) -> Path:
    if Path(manifest["leader_repo"]).resolve() != leader:
        raise DispatchConfigError("task manifest belongs to a different leader checkout")
    workspace = Path(manifest["workspace"]).resolve()
    if not workspace.is_dir():
        raise DispatchConfigError(f"worker workspace is unavailable: {workspace}")
    actual = ovp._repo_root(workspace, timeout=timeout)
    if actual != workspace:
        raise DispatchConfigError("recorded worker workspace is no longer a Git worktree root")
    if ovp._common_git_dir(leader, timeout=timeout) != ovp._common_git_dir(workspace, timeout=timeout):
        raise DispatchConfigError("worker workspace no longer belongs to the leader repository")
    branch = ovp._current_branch(workspace, timeout=timeout)
    if branch != manifest["worker_branch"]:
        raise DispatchConfigError("worker workspace branch no longer matches the task manifest")
    ancestor = ovp._git(
        workspace,
        ["merge-base", "--is-ancestor", manifest["base_commit"], "HEAD"],
        timeout=timeout,
        check=False,
    )
    if ancestor.returncode != 0:
        raise DispatchConfigError("worker branch no longer descends from the prepared base commit")
    if not resume and not ovp._clean(workspace, timeout=timeout):
        raise DispatchConfigError("fresh dispatch requires a clean worker workspace")
    return workspace


def run_worker(
    plan: ProviderPlan,
    *,
    prompt: str,
    workspace: Path,
    env: Mapping[str, str],
    timeout: float = DEFAULT_TIMEOUT,
    runner=subprocess.run,
) -> WorkerRun:
    binary = plan.command[0]
    if runner is subprocess.run and not shutil.which(binary, path=env.get("PATH")):
        return WorkerRun("FAIL", None, 0, "", "", None, f"provider executable not found: {binary}")
    started = monotonic()
    try:
        completed = runner(
            list(plan.command), cwd=str(workspace), input=prompt, text=True, capture_output=True,
            timeout=timeout, check=False, env=dict(env),
        )
    except subprocess.TimeoutExpired as exc:
        duration = max(0, int((monotonic() - started) * 1000))
        return WorkerRun("FAIL", None, duration, "", "", None, f"TimeoutExpired: {exc}")
    except OSError as exc:
        duration = max(0, int((monotonic() - started) * 1000))
        return WorkerRun("FAIL", None, duration, "", "", None, f"{type(exc).__name__}: {exc}")
    duration = max(0, int((monotonic() - started) * 1000))
    stdout = _clean_capture(completed.stdout)
    stderr = _clean_capture(completed.stderr)
    final = extract_final_message(plan, stdout)
    status = "PASS" if completed.returncode == 0 and final else "FAIL"
    error = None
    if completed.returncode != 0:
        error = f"provider exited {completed.returncode}: {(stderr or stdout).strip()[:1200]}"
    elif not final:
        error = "provider completed without a final worker message"
    return WorkerRun(status, completed.returncode, duration, stdout, stderr, final, error)


def _receipt_args(manifest: Mapping[str, Any], handoff: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    acceptance = {item["id"]: bool(item["required"]) for item in manifest["acceptance"]}
    checks = handoff["checks"]
    if set(checks) != set(acceptance):
        missing = sorted(set(acceptance).difference(checks))
        extra = sorted(set(checks).difference(acceptance))
        raise DispatchConfigError(f"handoff check IDs must exactly match acceptance; missing={missing}, extra={extra}")
    required = [f"{check_id}={checks[check_id]}" for check_id in sorted(checks) if acceptance[check_id]]
    optional = [f"{check_id}={checks[check_id]}" for check_id in sorted(checks) if not acceptance[check_id]]
    evidence_obj = handoff.get("evidence", {})
    evidence = [f"{check_id}={evidence_obj[check_id]}" for check_id in sorted(evidence_obj) if check_id in acceptance]
    unknown_evidence = sorted(set(evidence_obj).difference(acceptance))
    if unknown_evidence:
        raise DispatchConfigError(f"handoff evidence references unknown check IDs: {unknown_evidence}")
    return required, optional, evidence


def dispatch_task(
    *,
    repo: str | Path,
    task_id: str,
    provider: str,
    timeout: float = DEFAULT_TIMEOUT,
    command_json: str | None = None,
    executable: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    keep_user_config: bool = False,
    pass_env: Sequence[str] = (),
    allow_secret_env: bool = False,
    resume: bool = False,
    dry_run: bool = False,
    env_source: Mapping[str, str] | None = None,
    runner=subprocess.run,
) -> dict[str, Any]:
    git_timeout = min(timeout, ovp.DEFAULT_TIMEOUT)
    leader = ovp._repo_root(repo, timeout=git_timeout)
    task_id = ovp._validate_task_id(task_id)
    manifest = ovp._load_manifest(leader, task_id, timeout=git_timeout)
    state = manifest["state"]
    if resume:
        if state != "WORKING":
            raise DispatchConfigError(f"--resume requires WORKING, found {state}")
    elif state not in {"READY", "REWORK"}:
        raise DispatchConfigError(f"dispatch requires READY or REWORK, found {state}; use --resume only for an interrupted WORKING task")
    workspace = _validate_workspace(leader, manifest, resume=resume, timeout=git_timeout)
    task_dir = ovp._task_dir(leader, task_id, timeout=git_timeout)
    contract_path = (task_dir / "AI_CREOLE.txt").resolve()
    if not contract_path.is_file():
        raise DispatchConfigError("AI Creole contract is unavailable")
    contract_text = contract_path.read_text(encoding="utf-8")
    prompt = render_worker_prompt(manifest, contract_text)
    plan = build_provider_plan(
        provider, workspace=workspace, command_json=command_json, executable=executable,
        model=model, reasoning_effort=reasoning_effort, keep_user_config=keep_user_config,
    )
    env, inherited_env = build_worker_env(source=env_source, pass_env=pass_env, allow_secret_env=allow_secret_env)
    executable_name = plan.command[0]
    executable_found = shutil.which(executable_name, path=env.get("PATH")) if runner is subprocess.run else executable_name
    if dry_run:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS" if executable_found else "FAIL",
            "summary": "Dispatch plan validated; worker was not started.",
            "task_id": task_id,
            "ovp_state": state,
            "workspace": str(workspace),
            "provider": plan.public_dict(),
            "executable_found": bool(executable_found),
            "inherited_env_names": inherited_env,
            "prompt_chars": len(prompt),
            "proof_status": "UNPROVEN",
        }
    if not executable_found:
        raise DispatchConfigError(f"provider executable not found: {executable_name}")

    if not resume:
        ovp.mark_task(repo=leader, task_id=task_id, state="DISPATCHED", reason=f"dispatch via {provider}")
        ovp.mark_task(repo=leader, task_id=task_id, state="WORKING", reason=f"{provider} worker started")

    run = run_worker(plan, prompt=prompt, workspace=workspace, env=env, timeout=timeout, runner=runner)
    attempt_dir = task_dir / "dispatch"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    stamp = ovp._now().replace(":", "").replace("-", "")
    stdout_path = attempt_dir / f"{stamp}-{provider}-stdout.txt"
    stderr_path = attempt_dir / f"{stamp}-{provider}-stderr.txt"
    ovp._atomic_text(stdout_path, run.stdout)
    ovp._atomic_text(stderr_path, run.stderr)
    dispatch_record = {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "command": plan.public_dict()["command"],
        "duration_ms": run.duration_ms,
        "returncode": run.returncode,
        "status": run.status,
        "error": run.error,
        "inherited_env_names": inherited_env,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "at": ovp._now(),
    }
    ovp._atomic_json(attempt_dir / "latest.json", dispatch_record)

    if run.status != "PASS" or not run.final_message:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "summary": "Mutation worker did not produce a valid completion message; task remains WORKING for explicit recovery.",
            "task_id": task_id,
            "ovp_state": "WORKING",
            "provider": plan.public_dict(),
            "run": run.public_dict(),
            "artifacts": [str(stdout_path), str(stderr_path)],
            "proof_status": "UNPROVEN",
        }

    try:
        handoff = parse_handoff(run.final_message)
        required, optional, evidence = _receipt_args(manifest, handoff)
    except DispatchConfigError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "summary": "Worker ran but its mutation handoff was invalid; task remains WORKING for explicit recovery.",
            "task_id": task_id,
            "ovp_state": "WORKING",
            "provider": plan.public_dict(),
            "run": run.public_dict(),
            "handoff_error": str(exc),
            "artifacts": [str(stdout_path), str(stderr_path)],
            "proof_status": "UNPROVEN",
        }

    try:
        receipt = ovp.submit_receipt(
            repo=workspace,
            task_id=task_id,
            summary=handoff["summary"],
            checks=required,
            optional_checks=optional,
            evidence=evidence,
            artifacts=handoff.get("artifacts", []),
            risks=handoff.get("risks", []),
            assumptions=handoff.get("assumptions", []),
            timeout=git_timeout,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "summary": "Worker handoff parsed, but the authoritative OVP receipt gate rejected the workspace.",
            "task_id": task_id,
            "ovp_state": "WORKING",
            "provider": plan.public_dict(),
            "run": run.public_dict(),
            "receipt_error": str(exc),
            "artifacts": [str(stdout_path), str(stderr_path)],
            "proof_status": "UNPROVEN",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": receipt["status"],
        "summary": "Mutation worker handoff was validated through the OVP receipt gate.",
        "task_id": task_id,
        "ovp_state": receipt.get("environment", {}).get("ovp_state", "WORKING"),
        "provider": plan.public_dict(),
        "run": run.public_dict(),
        "receipt": receipt,
        "artifacts": [str(stdout_path), str(stderr_path)],
        "proof_status": "UNPROVEN",
        "integration_required": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--provider", required=True, choices=PROVIDERS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--command-json", help="Override provider command with a JSON argv array; required for local")
    parser.add_argument("--executable", help="Override the Codex or Claude executable name/path")
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--keep-user-config", action="store_true")
    parser.add_argument("--pass-env", action="append", default=[])
    parser.add_argument("--allow-secret-env", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Retry an interrupted WORKING task without replaying state transitions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = dispatch_task(
            repo=args.repo, task_id=args.task_id, provider=args.provider, timeout=args.timeout,
            command_json=args.command_json, executable=args.executable, model=args.model,
            reasoning_effort=args.reasoning_effort, keep_user_config=args.keep_user_config,
            pass_env=args.pass_env, allow_secret_env=args.allow_secret_env, resume=args.resume,
            dry_run=args.dry_run,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
        return 0 if payload.get("status") == "PASS" else 2
    except (DispatchConfigError, ValueError, RuntimeError, OSError) as exc:
        payload = {"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
