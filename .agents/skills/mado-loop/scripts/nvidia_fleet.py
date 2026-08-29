"""Run the MADO LOOP adaptive swarm with a curated NVIDIA NIM model fleet.

This wrapper keeps the core adaptive-routing contract provider/model agnostic while
providing an explicit, versioned recipe for NVIDIA Build's hosted free endpoints.
The profile is opt-in and can be replaced without changing proof or mutation authority.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import nvidia_request_profiles  # noqa: E402


PROFILE_NAME = "nvidia-balanced-2026-08"
PROFILE_UPDATED = "2026-08-29"
REQUEST_PROFILE_ADAPTER = "nvidia-request-profiles/v1"

TIER_MODELS = {
    "reasoning": "moonshotai/kimi-k3",
    "specialist": "moonshotai/kimi-k3",
    "coding": "deepseek-ai/deepseek-v4-pro-0813",
    "verification": "nvidia/nemotron-3.5-lightning-30b-a3b",
}

ROLE_MODELS = {
    "recon": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "reviewer": "nvidia/nemotron-3-ultra-550b-a55b",
    "release_auditor": "nvidia/nemotron-3-ultra-550b-a55b",
}

MODEL_RATIONALE = {
    "moonshotai/kimi-k3": "long-horizon coding, multimodal specialist work, architecture and agentic reasoning",
    "deepseek-ai/deepseek-v4-pro-0813": "coding-heavy implementation proposals and code reasoning",
    "nvidia/nemotron-3.5-lightning-30b-a3b": "fast reconnaissance and routine verification proposals",
    "nvidia/nemotron-3-ultra-550b-a55b": "deep adversarial review, release audit and high-complexity reasoning",
}


class NvidiaFleetConfigError(ValueError):
    """Raised when the NVIDIA fleet cannot be configured safely."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def profile_env(
    env: Mapping[str, str] | None = None,
    *,
    allow_nvidia_private: bool = False,
) -> dict[str, str]:
    """Return an environment copy with deterministic adaptive-role model routing."""
    result = dict(os.environ if env is None else env)
    api_key = (result.get("NVIDIA_API_KEY") or result.get("MADO_NVIDIA_API_KEY") or "").strip()
    if not api_key:
        raise NvidiaFleetConfigError("NVIDIA fleet requires NVIDIA_API_KEY or MADO_NVIDIA_API_KEY")

    result["MADO_ADAPTIVE_DEFAULT_PROVIDER"] = "nvidia"
    for tier, model in TIER_MODELS.items():
        result[f"MADO_ADAPTIVE_MODEL_{tier.upper()}"] = model
    for role, model in ROLE_MODELS.items():
        result[f"MADO_ADAPTIVE_MODEL_{role.upper()}"] = model

    if allow_nvidia_private:
        result["MADO_ALLOW_NVIDIA_PRIVATE"] = "1"
    elif not _truthy(result.get("MADO_ALLOW_NVIDIA_PRIVATE")):
        result.pop("MADO_ALLOW_NVIDIA_PRIVATE", None)
    return result


def profile_public_dict() -> dict[str, object]:
    request_profiles = sorted(
        {profile.name for profile in nvidia_request_profiles.PROFILES.values()}
        | {profile.name for profile in nvidia_request_profiles.MODEL_DEFAULTS.values()}
    )
    return {
        "profile": PROFILE_NAME,
        "updated": PROFILE_UPDATED,
        "provider": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_sensitivity": "public",
        "tier_models": dict(TIER_MODELS),
        "role_overrides": dict(ROLE_MODELS),
        "model_rationale": dict(MODEL_RATIONALE),
        "request_profile_adapter": REQUEST_PROFILE_ADAPTER,
        "request_profiles": request_profiles,
        "mutation_authority": "orchestrator-only",
        "proof_authority": "P0-P5 proof system",
    }


def plan_fleet(
    *,
    task: str,
    sensitivity: str = "public",
    allow_nvidia_private: bool = False,
    max_workers: int = adaptive_swarm.DEFAULT_MAX_WORKERS,
    review: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    routed_env = profile_env(env, allow_nvidia_private=allow_nvidia_private)
    plan = adaptive_swarm.plan_adaptive_swarm(
        task=task,
        sensitivity=sensitivity,
        provider="auto",
        max_workers=max_workers,
        review=review,
        env=routed_env,
    )
    return {"profile": PROFILE_NAME, "request_profile_adapter": REQUEST_PROFILE_ADAPTER, **plan}


def run_fleet(
    *,
    task: str,
    context: str = "",
    sensitivity: str = "public",
    allow_nvidia_private: bool = False,
    max_workers: int = adaptive_swarm.DEFAULT_MAX_WORKERS,
    review: bool | None = None,
    max_tokens: int = 8192,
    temperature: float = 1.0,
    timeout: float = 120.0,
    env: Mapping[str, str] | None = None,
    caller=nvidia_request_profiles.call_profiled,
) -> dict[str, object]:
    routed_env = profile_env(env, allow_nvidia_private=allow_nvidia_private)
    result = adaptive_swarm.run_adaptive_swarm(
        task=task,
        context=context,
        sensitivity=sensitivity,
        provider="auto",
        max_workers=max_workers,
        review=review,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        env=routed_env,
        caller=caller,
    )
    return {"profile": PROFILE_NAME, "request_profile_adapter": REQUEST_PROFILE_ADAPTER, **result}


def _read_task(args: argparse.Namespace) -> str:
    sources = sum(bool(value) for value in (args.task, args.task_file, args.stdin))
    if sources != 1:
        raise NvidiaFleetConfigError("requires exactly one of --task, --task-file, or --stdin")
    if args.task is not None:
        return args.task
    if args.task_file is not None:
        return Path(args.task_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _review_override(args: argparse.Namespace) -> bool | None:
    if args.review:
        return True
    if args.no_review:
        return False
    return None


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--sensitivity", choices=adaptive_swarm.provider_router.SENSITIVITIES, default="public")
    parser.add_argument("--allow-nvidia-private", action="store_true")
    parser.add_argument("--max-workers", type=int, default=adaptive_swarm.DEFAULT_MAX_WORKERS)
    review_group = parser.add_mutually_exclusive_group()
    review_group.add_argument("--review", action="store_true")
    review_group.add_argument("--no-review", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profile", help="show the curated NVIDIA model fleet without making a model call")

    plan = sub.add_parser("plan", help="plan an adaptive swarm using the NVIDIA fleet")
    _add_common_args(plan)

    run = sub.add_parser("run", help="run an adaptive swarm using the NVIDIA fleet")
    _add_common_args(run)
    run.add_argument("--context-file")
    run.add_argument("--max-tokens", type=int, default=8192)
    run.add_argument("--temperature", type=float, default=1.0)
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        if args.command == "profile":
            payload = {"status": "PASS", **profile_public_dict()}
        else:
            task = _read_task(args)
            common = dict(
                task=task,
                sensitivity=args.sensitivity,
                allow_nvidia_private=args.allow_nvidia_private,
                max_workers=args.max_workers,
                review=_review_override(args),
            )
            if args.command == "plan":
                payload = plan_fleet(**common)
            else:
                context = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else ""
                payload = run_fleet(
                    context=context,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    timeout=args.timeout,
                    **common,
                )
                if args.output:
                    Path(args.output).write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0 if payload.get("status", "PASS") != "FAIL" else 3
    except (
        NvidiaFleetConfigError,
        nvidia_request_profiles.NvidiaRequestProfileError,
        adaptive_swarm.AdaptiveSwarmConfigError,
        OSError,
    ) as exc:
        sys.stderr.write(f"nvidia fleet configuration error: {exc}\n")
        return 2
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"nvidia fleet internal error: {type(exc).__name__}: {exc}\n")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
