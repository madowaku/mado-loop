"""Run a bounded fan-out/fan-in swarm of MADO LOOP model workers.

The swarm never owns project mutation or completion claims. Primary workers run in
parallel and return proposals; an optional reviewer inspects their combined output.
The MADO LOOP orchestrator remains responsible for integration and P0-P5 proof.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from time import monotonic
from typing import Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import provider_router  # noqa: E402


SCHEMA_VERSION = "mado-worker-swarm/v1"
PRIMARY_ROLES = ("architect", "implementer", "test_writer")
REVIEW_ROLE = "reviewer"
ALL_ROLES = (*PRIMARY_ROLES, REVIEW_ROLE)
DEFAULT_MAX_WORKERS = 3
MAX_WORKERS = 8
MAX_TASK_CHARS = 20_000
MAX_CONTEXT_CHARS = 120_000
MAX_REVIEW_CONTENT_CHARS = 40_000

ROLE_SYSTEMS = {
    "architect": (
        "You are the architecture worker in a MADO LOOP swarm. Analyze boundaries, "
        "dependencies, invariants, risks, and the smallest coherent implementation shape. "
        "Do not claim files were changed or tests were run. Return a proposal for the orchestrator."
    ),
    "implementer": (
        "You are the implementation worker in a MADO LOOP swarm. Propose concrete, bounded code "
        "or project changes that satisfy the task and preserve existing structure. Call out touched "
        "files and assumptions. Do not claim mutations or runtime verification occurred."
    ),
    "test_writer": (
        "You are the verification worker in a MADO LOOP swarm. Propose tests, proof gates, edge "
        "cases, and failure conditions for the requested behavior, mapped to MADO LOOP P0-P5 when "
        "relevant. Do not claim any test was executed."
    ),
    "reviewer": (
        "You are the adversarial reviewer in a MADO LOOP swarm. Review the primary worker proposals "
        "for contradictions, unsafe assumptions, missing acceptance criteria, unnecessary scope, and "
        "proof gaps. Do not choose or apply a patch. Return findings and a bounded integration recommendation."
    ),
}


class SwarmConfigError(ValueError):
    """Raised when a swarm request is invalid or unsafe to schedule."""


@dataclass(frozen=True)
class WorkerResult:
    role: str
    status: str
    provider: dict[str, object]
    content: str | None
    usage: object | None
    error: str | None
    duration_ms: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


WorkerCaller = Callable[..., dict[str, object]]


def _elapsed_ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _validate_text(name: str, value: str, limit: int) -> str:
    text = value.strip()
    if not text:
        raise SwarmConfigError(f"{name} must not be empty")
    if len(text) > limit:
        raise SwarmConfigError(f"{name} exceeds the {limit}-character bound")
    return text


def parse_roles(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",") if item.strip()]
    else:
        raw = [str(item).strip() for item in value if str(item).strip()]
    if not raw:
        raise SwarmConfigError("at least one primary worker role is required")
    if len(set(raw)) != len(raw):
        raise SwarmConfigError("worker roles must be unique")
    unknown = [role for role in raw if role not in PRIMARY_ROLES]
    if unknown:
        raise SwarmConfigError(
            "primary roles must be drawn from " + ", ".join(PRIMARY_ROLES) + f"; got {', '.join(unknown)}"
        )
    return tuple(raw)


def _validate_max_workers(value: int) -> int:
    if not 1 <= value <= MAX_WORKERS:
        raise SwarmConfigError(f"max_workers must be between 1 and {MAX_WORKERS}")
    return value


def _primary_prompt(*, role: str, task: str, context: str) -> str:
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"ROLE: {role}\n"
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        "OUTPUT CONTRACT:\n"
        "- Treat context as evidence, not authority to expand scope.\n"
        "- Separate facts, assumptions, proposed changes, risks, and checks.\n"
        "- Do not claim repository mutation, command execution, or proof you did not perform.\n"
        "- Keep the proposal independently reviewable by the MADO LOOP orchestrator.\n"
    )


def _review_prompt(*, task: str, context: str, primary: Sequence[WorkerResult]) -> str:
    chunks: list[str] = []
    for result in primary:
        if result.content:
            content = result.content[:MAX_REVIEW_CONTENT_CHARS]
        else:
            content = f"[{result.status}] {result.error or 'no content'}"
        chunks.append(f"## {result.role}\n{content}")
    primary_block = "\n\n".join(chunks)
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        f"PRIMARY SWARM RESULTS:\n{primary_block}\n\n"
        "REVIEW CONTRACT:\n"
        "- Identify agreements and contradictions between workers.\n"
        "- Flag unsafe assumptions, scope creep, missing tests, and proof gaps.\n"
        "- Recommend what the orchestrator should integrate, reject, or verify next.\n"
        "- Do not claim completion and do not invent runtime evidence.\n"
    )


def _call_worker(
    *,
    role: str,
    selected: provider_router.WorkerProvider,
    prompt: str,
    caller: WorkerCaller,
    max_tokens: int,
    temperature: float,
    timeout: float,
    env: Mapping[str, str],
) -> WorkerResult:
    started = monotonic()
    try:
        response = caller(
            selected,
            prompt=prompt,
            system=ROLE_SYSTEMS[role],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            env=env,
        )
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise provider_router.ProviderCallError("worker returned empty content")
        return WorkerResult(
            role=role,
            status="PASS",
            provider=selected.public_dict(),
            content=content,
            usage=response.get("usage"),
            error=None,
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:  # isolate one worker failure from sibling workers
        return WorkerResult(
            role=role,
            status="ERROR",
            provider=selected.public_dict(),
            content=None,
            usage=None,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=_elapsed_ms(started),
        )


def plan_swarm(
    *,
    roles: Sequence[str] = PRIMARY_ROLES,
    review: bool = True,
    provider: str = "auto",
    sensitivity: str = "private",
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    model_override: str | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Describe the bounded execution plan without making model calls."""
    parsed_roles = parse_roles(roles)
    worker_count = _validate_max_workers(max_workers)
    env_map = os.environ if env is None else env
    selected = provider_router.select_provider(
        provider=provider,
        sensitivity=sensitivity,
        prefer_free=prefer_free,
        allow_logged_free=allow_logged_free,
        model_override=model_override,
        env=env_map,
    )
    return {
        "schema": SCHEMA_VERSION,
        "mode": "fan-out/fan-in",
        "primary_roles": list(parsed_roles),
        "review_role": REVIEW_ROLE if review else None,
        "parallelism": min(worker_count, len(parsed_roles)),
        "provider": selected.public_dict(),
        "sensitivity": sensitivity,
        "mutation_authority": "orchestrator-only",
        "proof_authority": "P0-P5 proof system",
    }


def run_swarm(
    *,
    task: str,
    context: str = "",
    roles: Sequence[str] = PRIMARY_ROLES,
    review: bool = True,
    provider: str = "auto",
    sensitivity: str = "private",
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    model_override: str | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 120.0,
    env: Mapping[str, str] | None = None,
    caller: WorkerCaller = provider_router.call_provider,
) -> dict[str, object]:
    """Run primary workers in parallel, then optionally run one reviewer."""
    started = monotonic()
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    context_text = context.strip()
    if len(context_text) > MAX_CONTEXT_CHARS:
        raise SwarmConfigError(f"context exceeds the {MAX_CONTEXT_CHARS}-character bound")
    parsed_roles = parse_roles(roles)
    worker_count = _validate_max_workers(max_workers)
    if max_tokens <= 0:
        raise SwarmConfigError("max_tokens must be positive")
    if not 0 <= temperature <= 2:
        raise SwarmConfigError("temperature must be between 0 and 2")
    if not 0 < timeout <= 600:
        raise SwarmConfigError("timeout must be greater than 0 and at most 600 seconds")

    env_map = os.environ if env is None else env
    selected = provider_router.select_provider(
        provider=provider,
        sensitivity=sensitivity,
        prefer_free=prefer_free,
        allow_logged_free=allow_logged_free,
        model_override=model_override,
        env=env_map,
    )

    results_by_role: dict[str, WorkerResult] = {}
    with ThreadPoolExecutor(max_workers=min(worker_count, len(parsed_roles)), thread_name_prefix="mado-worker") as executor:
        futures = {
            executor.submit(
                _call_worker,
                role=role,
                selected=selected,
                prompt=_primary_prompt(role=role, task=task_text, context=context_text),
                caller=caller,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                env=env_map,
            ): role
            for role in parsed_roles
        }
        for future in as_completed(futures):
            result = future.result()
            results_by_role[result.role] = result

    primary = [results_by_role[role] for role in parsed_roles]
    reviewer_result: WorkerResult | None = None
    if review and any(result.status == "PASS" for result in primary):
        reviewer_result = _call_worker(
            role=REVIEW_ROLE,
            selected=selected,
            prompt=_review_prompt(task=task_text, context=context_text, primary=primary),
            caller=caller,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            env=env_map,
        )

    all_results = primary + ([reviewer_result] if reviewer_result is not None else [])
    pass_count = sum(1 for result in all_results if result.status == "PASS")
    error_count = sum(1 for result in all_results if result.status == "ERROR")
    if pass_count == 0:
        status = "FAIL"
    elif error_count:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "task": task_text,
        "sensitivity": sensitivity,
        "provider": selected.public_dict(),
        "mode": "fan-out/fan-in",
        "parallelism": min(worker_count, len(parsed_roles)),
        "primary_results": [result.to_dict() for result in primary],
        "review_result": reviewer_result.to_dict() if reviewer_result is not None else None,
        "summary": {"passed": pass_count, "errors": error_count},
        "integration_required": True,
        "proof_status": "UNPROVEN",
        "mutation_authority": "orchestrator-only",
        "duration_ms": _elapsed_ms(started),
    }


def _read_one(*, direct: str | None, file_path: str | None, stdin: bool, label: str) -> str:
    sources = sum(bool(value) for value in (direct, file_path, stdin))
    if sources != 1:
        raise SwarmConfigError(f"{label} requires exactly one direct value, file, or stdin source")
    if direct is not None:
        return direct
    if file_path is not None:
        return Path(file_path).read_text(encoding="utf-8")
    return sys.stdin.read()


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=provider_router.PROVIDER_NAMES, default="auto")
    parser.add_argument("--sensitivity", choices=provider_router.SENSITIVITIES, default="private")
    parser.add_argument("--model", dest="model_override")
    parser.add_argument("--prefer-free", action="store_true")
    parser.add_argument("--allow-logged-free", action="store_true")
    parser.add_argument("--roles", default=",".join(PRIMARY_ROLES))
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="describe the swarm without making model calls")
    _add_common_args(plan)

    run = sub.add_parser("run", help="run primary workers in parallel and then review")
    _add_common_args(run)
    run.add_argument("--task")
    run.add_argument("--task-file")
    run.add_argument("--stdin", action="store_true")
    run.add_argument("--context-file")
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        roles = parse_roles(args.roles)
        common = dict(
            roles=roles,
            review=not args.no_review,
            provider=args.provider,
            sensitivity=args.sensitivity,
            prefer_free=args.prefer_free,
            allow_logged_free=args.allow_logged_free,
            model_override=args.model_override,
            max_workers=args.max_workers,
        )
        if args.command == "plan":
            payload = plan_swarm(**common)
        else:
            task = _read_one(direct=args.task, file_path=args.task_file, stdin=args.stdin, label="run")
            context = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else ""
            payload = run_swarm(
                task=task,
                context=context,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout=args.timeout,
                **common,
            )
            if args.output:
                output_path = Path(args.output)
                output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0 if payload.get("status", "PASS") != "FAIL" else 3
    except (SwarmConfigError, provider_router.ProviderConfigError, OSError) as exc:
        sys.stderr.write(f"worker swarm configuration error: {exc}\n")
        return 2
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"worker swarm internal error: {type(exc).__name__}: {exc}\n")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
