"""Plan and run a subscription-efficient Codex-native MADO LOOP worker team.

The parent Codex session remains the Sol Medium orchestrator. This module only
spawns the smallest useful set of bounded Luna workers through `codex exec`.
It never spawns a reviewer automatically, never applies worker changes, and
never upgrades to Luna max without an explicit separate retry.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
from typing import Callable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import codex_plus_lane  # noqa: E402


SCHEMA_VERSION = "mado-codex-plus-swarm/v1"
MAX_TASK_CHARS = 20_000
MAX_CONTEXT_CHARS = 120_000

# Priority is deliberately about leverage per subscription call, not canonical
# output order. Parent-owned architect/reviewer work is omitted here.
SPAWN_PRIORITY = (
    "recon",
    "gameplay_specialist",
    "ui_specialist",
    "asset_specialist",
    "implementer",
    "release_auditor",
    "test_writer",
)

ROLE_INSTRUCTIONS = {
    "recon": "Identify responsibility boundaries, missing facts, and the smallest next inspectable action.",
    "gameplay_specialist": "Focus on mechanics, state, input, failure modes, and observable gameplay behavior.",
    "ui_specialist": "Focus on UI hierarchy, interaction, responsiveness, accessibility, and Godot integration risk.",
    "asset_specialist": "Focus on asset constraints, imports, animation, resources, and deterministic integration.",
    "implementer": "Propose concrete bounded code/project changes, likely files, assumptions, and checks.",
    "test_writer": "Propose tests, P0-P5 proof gates, edge cases, and explicit failure conditions.",
    "release_auditor": "Audit release readiness, evidence, packaging, export, configuration, and missing proof.",
}


class CodexPlusSwarmConfigError(ValueError):
    """Raised when the subscription-efficient team cannot be planned safely."""


WorkerCaller = Callable[..., codex_plus_lane.CodexCallResult]


def _validate_text(name: str, value: str, limit: int, *, allow_empty: bool = False) -> str:
    text = value.strip()
    if not text and not allow_empty:
        raise CodexPlusSwarmConfigError(f"{name} must not be empty")
    if len(text) > limit:
        raise CodexPlusSwarmConfigError(f"{name} exceeds the {limit}-character bound")
    return text


def max_spawned_for_mode(mode: str) -> int:
    if mode == "normal":
        return 2
    if mode in {"conserve", "critical"}:
        return 1
    raise CodexPlusSwarmConfigError(f"unknown budget mode: {mode}")


def _priority_for_domains(domains: Sequence[str]) -> tuple[str, ...]:
    # Release audits should not spend the only slot on generic test generation.
    if "RELEASE" in domains:
        return (
            "release_auditor",
            "test_writer",
            "recon",
            "gameplay_specialist",
            "ui_specialist",
            "asset_specialist",
            "implementer",
        )
    return SPAWN_PRIORITY


def _select_spawn_roles(
    roles: Sequence[str],
    *,
    domains: Sequence[str],
    max_spawned: int,
) -> tuple[str, ...]:
    candidates = {role for role in roles if role in ROLE_INSTRUCTIONS}
    priority = _priority_for_domains(domains)
    selected = [role for role in priority if role in candidates]
    return tuple(selected[:max_spawned])


def _budget(
    *,
    ledger_path: Path,
    weekly_budget_credits: float | None,
    env: Mapping[str, str],
) -> dict[str, object]:
    configured = codex_plus_lane._weekly_budget(env, weekly_budget_credits)
    return codex_plus_lane.budget_summary(
        ledger=codex_plus_lane.load_ledger(ledger_path),
        weekly_budget_credits=configured,
    )


def plan_swarm(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "private",
    ledger_path: Path = codex_plus_lane.DEFAULT_LEDGER,
    weekly_budget_credits: float | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    _validate_text("context", context, MAX_CONTEXT_CHARS, allow_empty=True)
    if sensitivity not in codex_plus_lane.SENSITIVITIES:
        raise CodexPlusSwarmConfigError(f"unknown sensitivity: {sensitivity}")
    if sensitivity == "secret":
        raise CodexPlusSwarmConfigError("secret tasks remain local-only and may not use ChatGPT-plan workers")

    env_map = os.environ if env is None else env
    domains = adaptive_swarm.classify_domains(task_text)
    roles, review, complexity_score, reasons = adaptive_swarm.choose_roles(task_text, domains)
    budget = _budget(
        ledger_path=ledger_path,
        weekly_budget_credits=weekly_budget_credits,
        env=env_map,
    )
    mode = str(budget["mode"])
    cap = max_spawned_for_mode(mode)
    spawn_roles = _select_spawn_roles(roles, domains=domains, max_spawned=cap)
    assignments = [
        codex_plus_lane.choose_profile(role, budget_mode=mode).public_dict()
        for role in spawn_roles
    ]

    parent_responsibilities = ["orchestrator", "integration", "acceptance", "P0-P5 proof"]
    if "architect" in roles:
        parent_responsibilities.append("architect")
    if review:
        parent_responsibilities.append("reviewer")
    omitted = [role for role in roles if role not in spawn_roles and role != "architect"]

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "sensitivity": sensitivity,
        "domains": list(domains),
        "complexity_score": complexity_score,
        "complexity_reasons": reasons,
        "budget": budget,
        "max_spawned_workers": cap,
        "assignments": assignments,
        "parent": {
            "model": codex_plus_lane.SOL_MODEL,
            "effort": "medium",
            "responsibilities": parent_responsibilities,
        },
        "omitted_worker_roles": omitted,
        "review_required": review,
        "max_is_automatic": False,
        "subscription_auth": "Codex CLI existing ChatGPT sign-in",
        "api_key_required": False,
        "proof_status": "UNPROVEN",
        "integration_required": True,
    }


def _worker_prompt(*, role: str, task: str, context: str) -> str:
    context_text = context or "(No additional bounded repository context supplied.)"
    return (
        f"ROLE-SPECIFIC FOCUS:\n{ROLE_INSTRUCTIONS[role]}\n\n"
        f"TASK:\n{task}\n\n"
        f"BOUNDED CONTEXT:\n{context_text}\n\n"
        "Return a compact proposal for the Sol parent. Separate facts, assumptions, proposal, risks, and checks. "
        "Do not modify files or claim runtime proof."
    )


def run_swarm(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "private",
    cwd: Path = Path("."),
    ledger_path: Path = codex_plus_lane.DEFAULT_LEDGER,
    weekly_budget_credits: float | None = None,
    timeout: float = 300.0,
    env: Mapping[str, str] | None = None,
    caller: WorkerCaller = codex_plus_lane.run_codex_worker,
) -> dict[str, object]:
    task_text = _validate_text("task", task, MAX_TASK_CHARS)
    context_text = _validate_text("context", context, MAX_CONTEXT_CHARS, allow_empty=True)
    plan = plan_swarm(
        task=task_text,
        context=context_text,
        sensitivity=sensitivity,
        ledger_path=ledger_path,
        weekly_budget_credits=weekly_budget_credits,
        env=env,
    )
    mode = str(plan["budget"]["mode"])
    profiles = [
        codex_plus_lane.choose_profile(str(item["role"]), budget_mode=mode)
        for item in plan["assignments"]
    ]
    results_by_role: dict[str, codex_plus_lane.CodexCallResult] = {}

    if profiles:
        with ThreadPoolExecutor(max_workers=len(profiles)) as pool:
            futures = {
                pool.submit(
                    caller,
                    profile,
                    prompt=_worker_prompt(
                        role=profile.role,
                        task=task_text,
                        context=context_text,
                    ),
                    cwd=cwd.resolve(),
                    timeout=timeout,
                ): profile.role
                for profile in profiles
            }
            for future in as_completed(futures):
                role = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # worker failures stay isolated
                    profile = next(profile for profile in profiles if profile.role == role)
                    result = codex_plus_lane.CodexCallResult(
                        status="ERROR",
                        role=role,
                        model=profile.model,
                        effort=profile.effort,
                        duration_ms=0,
                        content=None,
                        usage=codex_plus_lane.Usage(),
                        estimated_credits=0.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                results_by_role[role] = result
                codex_plus_lane.append_ledger(ledger_path, result)

    ordered = [results_by_role[profile.role].public_dict() for profile in profiles]
    passed = sum(1 for item in ordered if item["status"] == "PASS")
    if not ordered:
        transport = "PASS"
    elif passed == len(ordered):
        transport = "PASS"
    elif passed:
        transport = "WARN"
    else:
        transport = "FAIL"

    return {
        **plan,
        "status": transport,
        "results": ordered,
        "parent_handoff": {
            "instruction": "Sol Medium parent must inspect proposals, fill omitted perspectives, integrate deliberately, and run normal P0-P5 proof.",
            "automatic_retry": False,
            "automatic_luna_max": False,
        },
        "proof_status": "UNPROVEN",
        "integration_required": True,
    }


def _read_optional(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--task")
        source.add_argument("--task-file")
        command.add_argument("--context-file")
        command.add_argument("--sensitivity", default="private", choices=codex_plus_lane.SENSITIVITIES)
        command.add_argument("--ledger")
        command.add_argument("--weekly-budget-credits", type=float)
        if name == "run":
            command.add_argument("--cwd", default=".")
            command.add_argument("--timeout", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        task = args.task if args.task is not None else _read_optional(args.task_file)
        context = _read_optional(args.context_file)
        ledger = Path(args.ledger) if args.ledger else codex_plus_lane.DEFAULT_LEDGER
        if args.command == "plan":
            payload = plan_swarm(
                task=task,
                context=context,
                sensitivity=args.sensitivity,
                ledger_path=ledger,
                weekly_budget_credits=args.weekly_budget_credits,
            )
        else:
            payload = run_swarm(
                task=task,
                context=context,
                sensitivity=args.sensitivity,
                cwd=Path(args.cwd),
                ledger_path=ledger,
                weekly_budget_credits=args.weekly_budget_credits,
                timeout=args.timeout,
            )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload["status"] in {"PASS", "WARN"} else 2
    except (CodexPlusSwarmConfigError, codex_plus_lane.CodexPlusConfigError, OSError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
