"""Plan and run a deterministic adaptive MADO LOOP worker swarm.

The adaptive layer chooses a bounded team from deterministic task domains and
complexity signals, then routes each role through the existing provider policy.
It never grants workers mutation or proof authority.
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

import classify_task  # noqa: E402
import provider_router  # noqa: E402


SCHEMA_VERSION = "mado-adaptive-swarm/v1"
ROLE_ORDER = (
    "architect",
    "recon",
    "gameplay_specialist",
    "ui_specialist",
    "asset_specialist",
    "implementer",
    "test_writer",
    "release_auditor",
)
REVIEW_ROLE = "reviewer"
ALL_ROLES = (*ROLE_ORDER, REVIEW_ROLE)
DEFAULT_MAX_WORKERS = 4
MAX_WORKERS = 8
MAX_TASK_CHARS = 20_000
MAX_CONTEXT_CHARS = 120_000
MAX_REVIEW_CONTENT_CHARS = 40_000

ROLE_TIERS = {
    "architect": "reasoning",
    "recon": "reasoning",
    "gameplay_specialist": "specialist",
    "ui_specialist": "specialist",
    "asset_specialist": "specialist",
    "implementer": "coding",
    "test_writer": "verification",
    "release_auditor": "verification",
    "reviewer": "verification",
}

ROLE_SYSTEMS = {
    "architect": (
        "You are the architecture worker in a MADO LOOP adaptive swarm. Analyze boundaries, "
        "dependencies, invariants, risks, and the smallest coherent implementation shape. "
        "Do not claim repository mutation or proof."
    ),
    "recon": (
        "You are the reconnaissance worker in a MADO LOOP adaptive swarm. Use only the supplied "
        "bounded context to identify likely responsibility boundaries, missing facts, and the next "
        "smallest inspectable action. Do not invent repository state."
    ),
    "gameplay_specialist": (
        "You are the gameplay specialist in a MADO LOOP adaptive swarm. Focus on mechanics, state, "
        "input, failure modes, game feel implications, and observable behavior. Return a bounded "
        "proposal, not a completion claim."
    ),
    "ui_specialist": (
        "You are the game UI specialist in a MADO LOOP adaptive swarm. Focus on hierarchy, layout, "
        "interaction, legibility, responsive constraints, and Godot integration risks. Return a "
        "bounded proposal, not a completion claim."
    ),
    "asset_specialist": (
        "You are the asset specialist in a MADO LOOP adaptive swarm. Focus on sprites, imagery, "
        "animation, pixel-safe constraints, imports, resource wiring, and deterministic asset "
        "integration. Return a bounded proposal, not a completion claim."
    ),
    "implementer": (
        "You are the implementation worker in a MADO LOOP adaptive swarm. Propose concrete, bounded "
        "code or project changes that preserve existing structure. Name likely touched files and "
        "assumptions. Do not claim files were changed or commands were run."
    ),
    "test_writer": (
        "You are the verification worker in a MADO LOOP adaptive swarm. Propose tests, proof gates, "
        "edge cases, and failure conditions, mapped to P0-P5 when relevant. Do not claim tests ran."
    ),
    "release_auditor": (
        "You are the release audit worker in a MADO LOOP adaptive swarm. Focus on release readiness, "
        "required evidence, packaging, export, configuration, and missing P0-P5 proof. Do not add "
        "features or claim release readiness."
    ),
    "reviewer": (
        "You are the adversarial reviewer in a MADO LOOP adaptive swarm. Compare the primary worker "
        "proposals, identify contradictions, unsafe assumptions, unnecessary scope, and proof gaps, "
        "then recommend what the orchestrator should integrate, reject, or verify next."
    ),
}

DOMAIN_ROLE_MAP = {
    "CODE": ("implementer", "test_writer"),
    "GAMEPLAY": ("gameplay_specialist", "implementer", "test_writer"),
    "UI": ("ui_specialist", "implementer", "test_writer"),
    "SPRITE": ("asset_specialist", "implementer", "test_writer"),
    "IMAGE": ("asset_specialist", "test_writer"),
    "ANIMATION": ("asset_specialist", "implementer", "test_writer"),
    "ASSET_INTEGRATION": ("asset_specialist", "implementer", "test_writer"),
    "REFERENCE_TO_UI": ("ui_specialist", "asset_specialist", "implementer", "test_writer"),
    "PIXEL_ART": ("asset_specialist", "test_writer"),
    "PLAYTEST": ("gameplay_specialist", "test_writer"),
    "RELEASE": ("release_auditor", "test_writer"),
}

ARCHITECTURE_TERMS = (
    "architecture", "architect", "system", "migration", "cross-cutting", "refactor",
    "設計", "アーキテクチャ", "全体", "移行", "横断", "リファクタ",
)


class AdaptiveSwarmConfigError(ValueError):
    """Raised when an adaptive swarm request cannot be planned safely."""


@dataclass(frozen=True)
class WorkerAssignment:
    role: str
    tier: str
    rationale: str
    provider: provider_router.WorkerProvider

    def public_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "tier": self.tier,
            "rationale": self.rationale,
            "provider": self.provider.public_dict(),
        }


@dataclass(frozen=True)
class AdaptiveWorkerResult:
    role: str
    tier: str
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


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _env_suffix(value: str) -> str:
    return value.upper().replace("-", "_")


def _validate_text(name: str, value: str, limit: int) -> str:
    text = value.strip()
    if not text:
        raise AdaptiveSwarmConfigError(f"{name} must not be empty")
    if len(text) > limit:
        raise AdaptiveSwarmConfigError(f"{name} exceeds the {limit}-character bound")
    return text


def _validate_max_workers(value: int) -> int:
    if not 1 <= value <= MAX_WORKERS:
        raise AdaptiveSwarmConfigError(f"max_workers must be between 1 and {MAX_WORKERS}")
    return value


def classify_domains(task: str) -> tuple[str, ...]:
    return tuple(classify_task.classify_domains(task))


def complexity_for(task: str, domains: Sequence[str]) -> tuple[int, list[str]]:
    normalized = " ".join(task.casefold().split())
    score = len(domains)
    reasons: list[str] = [f"domain_count={len(domains)}"]
    if "RELEASE" in domains:
        score += 2
        reasons.append("release_requires_broad_evidence")
    if any(domain in domains for domain in ("ASSET_INTEGRATION", "REFERENCE_TO_UI")):
        score += 1
        reasons.append("integration_boundary")
    if len(task) > 1000:
        score += 1
        reasons.append("long_task_description")
    if any(term in normalized for term in ARCHITECTURE_TERMS):
        score += 1
        reasons.append("architecture_signal")
    return score, reasons


def choose_roles(task: str, domains: Sequence[str]) -> tuple[tuple[str, ...], bool, int, list[str]]:
    score, reasons = complexity_for(task, domains)
    selected: set[str] = set()
    if not domains:
        selected.add("recon")
        reasons.append("no_domain_match_recon")
    for domain in domains:
        selected.update(DOMAIN_ROLE_MAP.get(domain, ()))
    if score >= 3 or len(domains) >= 2:
        selected.add("architect")
        reasons.append("architect_for_complexity")
    if "RELEASE" in domains:
        selected.discard("implementer")
        reasons.append("release_is_audit_not_implicit_implementation")
    roles = tuple(role for role in ROLE_ORDER if role in selected)
    if not roles:
        roles = ("recon",)
    review = len(roles) >= 2 or "RELEASE" in domains or len(domains) >= 2
    return roles, review, score, reasons


def _configured_route(
    *,
    role: str,
    tier: str,
    sensitivity: str,
    default_provider: str,
    default_model: str | None,
    prefer_free: bool,
    allow_logged_free: bool,
    env: Mapping[str, str],
) -> provider_router.WorkerProvider:
    role_suffix = _env_suffix(role)
    tier_suffix = _env_suffix(tier)
    provider_name = (
        _env_value(env, f"MADO_ADAPTIVE_PROVIDER_{role_suffix}")
        or _env_value(env, f"MADO_ADAPTIVE_PROVIDER_{tier_suffix}")
        or default_provider
    )
    model_override = (
        _env_value(env, f"MADO_ADAPTIVE_MODEL_{role_suffix}")
        or _env_value(env, f"MADO_ADAPTIVE_MODEL_{tier_suffix}")
        or default_model
    )
    if provider_name == "auto" and model_override:
        configured_default = _env_value(env, "MADO_ADAPTIVE_DEFAULT_PROVIDER")
        if configured_default:
            provider_name = configured_default
        elif sensitivity == "secret":
            provider_name = "local"
        elif _env_value(env, "OPENROUTER_API_KEY"):
            provider_name = "openrouter"
        elif _env_value(env, "MADO_LOCAL_BASE_URL") and _env_value(env, "MADO_LOCAL_MODEL"):
            provider_name = "local"
        else:
            raise AdaptiveSwarmConfigError(
                f"role {role} has a model override but no explicit/default provider can be resolved"
            )
    try:
        return provider_router.select_provider(
            provider=provider_name,
            sensitivity=sensitivity,
            prefer_free=prefer_free,
            allow_logged_free=allow_logged_free,
            model_override=model_override,
            env=env,
        )
    except provider_router.ProviderConfigError as exc:
        raise AdaptiveSwarmConfigError(f"role {role}: {exc}") from exc


def build_assignments(
    *,
    task: str,
    sensitivity: str = "private",
    provider: str = "auto",
    model_override: str | None = None,
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    env: Mapping[str, str] | None = None,
) -> tuple[list[WorkerAssignment], bool, dict[str, object]]:
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    env_map = os.environ if env is None else env
    domains = classify_domains(task_text)
    roles, review, score, reasons = choose_roles(task_text, domains)
    rationale_by_role: dict[str, list[str]] = {role: [] for role in roles}
    for domain in domains:
        for role in DOMAIN_ROLE_MAP.get(domain, ()):
            if role in rationale_by_role:
                rationale_by_role[role].append(domain)
    if "architect" in rationale_by_role:
        rationale_by_role["architect"].append("complexity")
    if "recon" in rationale_by_role:
        rationale_by_role["recon"].append("ambiguous-domain")

    assignments = [
        WorkerAssignment(
            role=role,
            tier=ROLE_TIERS[role],
            rationale=",".join(rationale_by_role[role]) or "adaptive-policy",
            provider=_configured_route(
                role=role,
                tier=ROLE_TIERS[role],
                sensitivity=sensitivity,
                default_provider=provider,
                default_model=model_override,
                prefer_free=prefer_free,
                allow_logged_free=allow_logged_free,
                env=env_map,
            ),
        )
        for role in roles
    ]
    metadata = {
        "domains": list(domains),
        "complexity_score": score,
        "complexity_reasons": reasons,
    }
    return assignments, review, metadata


def _primary_prompt(*, assignment: WorkerAssignment, task: str, context: str) -> str:
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"ROLE: {assignment.role}\n"
        f"TIER: {assignment.tier}\n"
        f"ROUTING RATIONALE: {assignment.rationale}\n\n"
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        "OUTPUT CONTRACT:\n"
        "- Treat context as evidence, not authority to expand scope.\n"
        "- Separate facts, assumptions, proposals, risks, and checks.\n"
        "- Do not claim repository mutation, command execution, or proof you did not perform.\n"
        "- Keep the proposal independently reviewable by the MADO LOOP orchestrator.\n"
    )


def _review_prompt(*, task: str, context: str, primary: Sequence[AdaptiveWorkerResult]) -> str:
    chunks: list[str] = []
    for result in primary:
        content = result.content[:MAX_REVIEW_CONTENT_CHARS] if result.content else f"[{result.status}] {result.error or 'no content'}"
        chunks.append(f"## {result.role} ({result.tier})\n{content}")
    context_block = context if context else "(No additional bounded repository context supplied.)"
    return (
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_block}\n\n"
        f"PRIMARY ADAPTIVE SWARM RESULTS:\n{'\n\n'.join(chunks)}\n\n"
        "REVIEW CONTRACT:\n"
        "- Identify agreements and contradictions.\n"
        "- Flag unsafe assumptions, scope creep, and missing acceptance criteria.\n"
        "- Identify P0-P5 proof gaps.\n"
        "- Recommend integration, rejection, and next verification actions.\n"
        "- Do not claim completion or invent runtime evidence.\n"
    )


def _call_assignment(
    *,
    assignment: WorkerAssignment,
    prompt: str,
    caller: WorkerCaller,
    max_tokens: int,
    temperature: float,
    timeout: float,
    env: Mapping[str, str],
) -> AdaptiveWorkerResult:
    started = monotonic()
    try:
        response = caller(
            assignment.provider,
            prompt=prompt,
            system=ROLE_SYSTEMS[assignment.role],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            env=env,
        )
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise provider_router.ProviderCallError("worker returned empty content")
        return AdaptiveWorkerResult(
            role=assignment.role,
            tier=assignment.tier,
            status="PASS",
            provider=assignment.provider.public_dict(),
            content=content,
            usage=response.get("usage"),
            error=None,
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        return AdaptiveWorkerResult(
            role=assignment.role,
            tier=assignment.tier,
            status="ERROR",
            provider=assignment.provider.public_dict(),
            content=None,
            usage=None,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=_elapsed_ms(started),
        )


def plan_adaptive_swarm(
    *,
    task: str,
    sensitivity: str = "private",
    provider: str = "auto",
    model_override: str | None = None,
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
    review: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    worker_count = _validate_max_workers(max_workers)
    assignments, adaptive_review, metadata = build_assignments(
        task=task,
        sensitivity=sensitivity,
        provider=provider,
        model_override=model_override,
        prefer_free=prefer_free,
        allow_logged_free=allow_logged_free,
        env=env,
    )
    use_review = adaptive_review if review is None else review
    return {
        "schema": SCHEMA_VERSION,
        "mode": "adaptive-fan-out/fan-in",
        "task": task.strip(),
        "sensitivity": sensitivity,
        **metadata,
        "assignments": [assignment.public_dict() for assignment in assignments],
        "review_role": REVIEW_ROLE if use_review else None,
        "parallelism": min(worker_count, len(assignments)),
        "mutation_authority": "orchestrator-only",
        "proof_authority": "P0-P5 proof system",
    }


def run_adaptive_swarm(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "private",
    provider: str = "auto",
    model_override: str | None = None,
    prefer_free: bool = False,
    allow_logged_free: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
    review: bool | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 120.0,
    env: Mapping[str, str] | None = None,
    caller: WorkerCaller = provider_router.call_provider,
) -> dict[str, object]:
    started = monotonic()
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    context_text = context.strip()
    if len(context_text) > MAX_CONTEXT_CHARS:
        raise AdaptiveSwarmConfigError(f"context exceeds the {MAX_CONTEXT_CHARS}-character bound")
    worker_count = _validate_max_workers(max_workers)
    if max_tokens <= 0:
        raise AdaptiveSwarmConfigError("max_tokens must be positive")
    if not 0 <= temperature <= 2:
        raise AdaptiveSwarmConfigError("temperature must be between 0 and 2")
    if not 0 < timeout <= 600:
        raise AdaptiveSwarmConfigError("timeout must be greater than 0 and at most 600 seconds")
    env_map = os.environ if env is None else env
    assignments, adaptive_review, metadata = build_assignments(
        task=task_text,
        sensitivity=sensitivity,
        provider=provider,
        model_override=model_override,
        prefer_free=prefer_free,
        allow_logged_free=allow_logged_free,
        env=env_map,
    )
    use_review = adaptive_review if review is None else review

    results_by_role: dict[str, AdaptiveWorkerResult] = {}
    with ThreadPoolExecutor(max_workers=min(worker_count, len(assignments)), thread_name_prefix="mado-adaptive") as executor:
        futures = {
            executor.submit(
                _call_assignment,
                assignment=assignment,
                prompt=_primary_prompt(assignment=assignment, task=task_text, context=context_text),
                caller=caller,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                env=env_map,
            ): assignment.role
            for assignment in assignments
        }
        for future in as_completed(futures):
            result = future.result()
            results_by_role[result.role] = result

    primary = [results_by_role[assignment.role] for assignment in assignments]
    reviewer_result: AdaptiveWorkerResult | None = None
    if use_review and any(result.status == "PASS" for result in primary):
        reviewer_provider = _configured_route(
            role=REVIEW_ROLE,
            tier=ROLE_TIERS[REVIEW_ROLE],
            sensitivity=sensitivity,
            default_provider=provider,
            default_model=model_override,
            prefer_free=prefer_free,
            allow_logged_free=allow_logged_free,
            env=env_map,
        )
        reviewer_assignment = WorkerAssignment(
            role=REVIEW_ROLE,
            tier=ROLE_TIERS[REVIEW_ROLE],
            rationale="fan-in-adversarial-review",
            provider=reviewer_provider,
        )
        reviewer_result = _call_assignment(
            assignment=reviewer_assignment,
            prompt=_review_prompt(task=task_text, context=context_text, primary=primary),
            caller=caller,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            env=env_map,
        )

    all_results = primary + ([reviewer_result] if reviewer_result else [])
    pass_count = sum(1 for result in all_results if result.status == "PASS")
    error_count = sum(1 for result in all_results if result.status == "ERROR")
    status = "FAIL" if pass_count == 0 else "WARN" if error_count else "PASS"
    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "mode": "adaptive-fan-out/fan-in",
        "task": task_text,
        "sensitivity": sensitivity,
        **metadata,
        "assignments": [assignment.public_dict() for assignment in assignments],
        "parallelism": min(worker_count, len(assignments)),
        "primary_results": [result.to_dict() for result in primary],
        "review_result": reviewer_result.to_dict() if reviewer_result else None,
        "summary": {"passed": pass_count, "errors": error_count},
        "integration_required": True,
        "proof_status": "UNPROVEN",
        "mutation_authority": "orchestrator-only",
        "duration_ms": _elapsed_ms(started),
    }


def _read_one(*, direct: str | None, file_path: str | None, stdin: bool) -> str:
    sources = sum(bool(value) for value in (direct, file_path, stdin))
    if sources != 1:
        raise AdaptiveSwarmConfigError("requires exactly one of --task, --task-file, or --stdin")
    if direct is not None:
        return direct
    if file_path is not None:
        return Path(file_path).read_text(encoding="utf-8")
    return sys.stdin.read()


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--provider", choices=provider_router.PROVIDER_NAMES, default="auto")
    parser.add_argument("--sensitivity", choices=provider_router.SENSITIVITIES, default="private")
    parser.add_argument("--model", dest="model_override")
    parser.add_argument("--prefer-free", action="store_true")
    parser.add_argument("--allow-logged-free", action="store_true")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    review_group = parser.add_mutually_exclusive_group()
    review_group.add_argument("--review", action="store_true")
    review_group.add_argument("--no-review", action="store_true")


def _review_override(args: argparse.Namespace) -> bool | None:
    if args.review:
        return True
    if args.no_review:
        return False
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="classify, compose, and route the adaptive team without model calls")
    _add_common_args(plan)
    run = sub.add_parser("run", help="run the adaptively composed worker team and optional reviewer")
    _add_common_args(run)
    run.add_argument("--context-file")
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        task = _read_one(direct=args.task, file_path=args.task_file, stdin=args.stdin)
        common = dict(
            task=task,
            sensitivity=args.sensitivity,
            provider=args.provider,
            model_override=args.model_override,
            prefer_free=args.prefer_free,
            allow_logged_free=args.allow_logged_free,
            max_workers=args.max_workers,
            review=_review_override(args),
        )
        if args.command == "plan":
            payload = plan_adaptive_swarm(**common)
        else:
            context = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else ""
            payload = run_adaptive_swarm(
                context=context,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                timeout=args.timeout,
                **common,
            )
            if args.output:
                Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0 if payload.get("status", "PASS") != "FAIL" else 3
    except (AdaptiveSwarmConfigError, OSError) as exc:
        sys.stderr.write(f"adaptive swarm configuration error: {exc}\n")
        return 2
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"adaptive swarm internal error: {type(exc).__name__}: {exc}\n")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
