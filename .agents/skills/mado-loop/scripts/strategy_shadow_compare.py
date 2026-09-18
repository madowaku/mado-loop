"""Compare current deterministic routing policy with G3 advisory candidates.

This is a shadow comparison only. The legacy side is either an explicitly
supplied observation or a deterministic projection using the current domain
classifier and adaptive team policy. No provider/model is called and no route
is executed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import classify_task  # noqa: E402
from capability_manifest import DEFAULT_REGISTRY, load_registry  # noqa: E402
from strategy_resolver import (  # noqa: E402
    StrategyResolverError,
    _read_json,
    build_strategy_candidates,
    validate_intent,
)

SCHEMA_VERSION = "1.0"


class ShadowCompareError(ValueError):
    """Raised when a shadow comparison input is invalid."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ShadowCompareError(message)


def validate_legacy_observation(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, dict), "legacy observation must be an object")
    required = {"strategy", "domains", "roles", "review", "source_ref"}
    _expect(set(value) == required, "legacy observation keys are invalid")
    strategy = value.get("strategy")
    domains = value.get("domains")
    roles = value.get("roles")
    review = value.get("review")
    source_ref = value.get("source_ref")
    _expect(isinstance(strategy, str) and bool(strategy.strip()), "legacy.strategy is invalid")
    _expect(isinstance(domains, list) and all(isinstance(item, str) for item in domains), "legacy.domains is invalid")
    _expect(isinstance(roles, list) and all(isinstance(item, str) for item in roles), "legacy.roles is invalid")
    _expect(isinstance(review, bool), "legacy.review is invalid")
    _expect(isinstance(source_ref, str) and bool(source_ref.strip()), "legacy.source_ref is invalid")
    return {
        "source": "observed",
        "strategy": strategy.strip(),
        "domains": list(domains),
        "roles": list(roles),
        "review": review,
        "source_ref": source_ref.strip(),
    }


def project_legacy_policy(intent: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_intent(dict(intent))
    domains = list(classify_task.classify_domains(normalized["goal"]))
    roles, review, score, reasons = adaptive_swarm.choose_roles(normalized["goal"], domains)
    return {
        "source": "projection",
        "strategy": "legacy-domain-plus-adaptive-team-policy",
        "domains": domains,
        "roles": list(roles),
        "review": review,
        "source_ref": "classify_task.py+adaptive_swarm.choose_roles",
        "complexity_score": score,
        "complexity_reasons": reasons,
    }


def compare_shadow(
    intent: Mapping[str, Any],
    authority: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    legacy_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_intent = validate_intent(dict(intent))
    legacy = (
        validate_legacy_observation(dict(legacy_observation))
        if legacy_observation is not None
        else project_legacy_policy(normalized_intent)
    )
    advisory = build_strategy_candidates(normalized_intent, authority, snapshot, registry)

    intent_domains = list(normalized_intent["domains"])
    legacy_domains = list(legacy["domains"])
    ready = [
        candidate["strategy"]
        for candidate in advisory["candidates"]
        if candidate["state"] == "READY"
    ]
    conditional = [
        candidate["strategy"]
        for candidate in advisory["candidates"]
        if candidate["state"] == "CONDITIONAL"
    ]
    blocked = [
        candidate["strategy"]
        for candidate in advisory["candidates"]
        if candidate["state"] == "BLOCKED"
    ]
    single_ready = [
        candidate["strategy"]
        for candidate in advisory["candidates"]
        if candidate["state"] == "READY" and candidate["coordination"] in {"single", "single+delegate"}
    ]

    observations: list[str] = []
    if legacy_domains != intent_domains:
        observations.append("legacy_domain_projection_differs_from_intent_domains")
    if len(legacy["roles"]) >= 2:
        observations.append("legacy_projection_contains_parallel_roles")
    if single_ready:
        observations.append("g3_has_ready_single_coordination_candidate")
    if "adaptive-swarm" in ready:
        observations.append("g3_adaptive_swarm_is_ready")
    elif "adaptive-swarm" in conditional:
        observations.append("g3_adaptive_swarm_is_conditional")
    if not ready:
        observations.append("g3_has_no_ready_candidate")

    return {
        "schema_version": SCHEMA_VERSION,
        "shadow_only": True,
        "intent_id": normalized_intent["id"],
        "legacy": legacy,
        "g3": advisory,
        "comparison": {
            "domain_exact_match": legacy_domains == intent_domains,
            "intent_domains": intent_domains,
            "legacy_domains": legacy_domains,
            "ready_strategies": ready,
            "conditional_strategies": conditional,
            "blocked_strategies": blocked,
            "legacy_role_count": len(legacy["roles"]),
            "observations": observations,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--legacy-plan", help="optional observed legacy plan JSON")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        intent = _read_json(args.intent, label="intent")
        authority = _read_json(args.authority, label="authority")
        snapshot = _read_json(args.snapshot, label="snapshot")
        registry = load_registry(args.registry)
        legacy = _read_json(args.legacy_plan, label="legacy plan") if args.legacy_plan else None
        payload = compare_shadow(
            intent,
            authority,
            snapshot,
            registry,
            legacy_observation=legacy,
        )
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except (ShadowCompareError, StrategyResolverError, OSError, ValueError) as exc:
        sys.stderr.write(f"strategy_shadow_compare configuration error: {exc}\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
