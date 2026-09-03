"""Deterministically recommend on-demand specialist skills for a MADO LOOP task."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = SKILL_ROOT / "skill_registry.yaml"
DEFAULT_STATS_PATH = Path(".mado-loop") / "skill_stats.json"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from classify_task import classify_domains  # noqa: E402
from common.result import EXIT_INTERNAL, EXIT_USAGE_CONFIG  # noqa: E402

ROUTER_SCHEMA_VERSION = "1"
STATS_SCHEMA_VERSION = "1"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _contains(text: str, term: str) -> bool:
    normalized_term = term.casefold()
    if normalized_term.isascii() and normalized_term.replace(" ", "").replace("-", "").isalnum():
        return re.search(
            r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])", text
        ) is not None
    return normalized_term in text


def load_registry(path: str | Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load the JSON-compatible YAML registry using only the Python standard library."""
    registry_path = Path(path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("unsupported skill registry version")
    policy = payload.get("policy")
    skills = payload.get("skills")
    if not isinstance(policy, dict) or not isinstance(skills, list):
        raise ValueError("skill registry requires policy and skills")
    ids = [str(item.get("id", "")) for item in skills if isinstance(item, dict)]
    if any(not skill_id for skill_id in ids) or len(ids) != len(skills):
        raise ValueError("every skill registry entry requires an id")
    if len(ids) != len(set(ids)):
        raise ValueError("skill registry ids must be unique")
    return payload


def load_stats(path: str | Path) -> dict[str, Any]:
    """Load a compact content-free feedback cache produced by record_skill_feedback.py."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != STATS_SCHEMA_VERSION:
        raise ValueError("unsupported skill stats schema")
    if not isinstance(payload.get("skills"), dict):
        raise ValueError("skill stats requires a skills mapping")
    return payload


def discover_stats_path() -> Path | None:
    """Find optional project-local stats without creating or scanning history."""
    configured = os.environ.get("MADO_SKILL_STATS")
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    return DEFAULT_STATS_PATH if DEFAULT_STATS_PATH.is_file() else None


def _matches_entry(task: str, domains: set[str], entry: Mapping[str, Any]) -> tuple[bool, str]:
    if entry.get("mode") == "manual_only":
        return False, "manual_only"

    normalized = _normalize(task)
    entry_domains = {str(value) for value in entry.get("domains", [])}
    domain_match = bool(domains.intersection(entry_domains))
    triggers = [str(value) for value in entry.get("triggers", [])]
    trigger_match = any(_contains(normalized, trigger) for trigger in triggers)

    if bool(entry.get("always_for_domains")) and domain_match:
        return True, "domain"
    if trigger_match and (domain_match or bool(entry.get("allow_trigger_without_domain"))):
        return True, "trigger"
    return False, "no_match"


def feedback_adjustment(
    skill_id: str,
    *,
    stats: Mapping[str, Any] | None,
    min_samples: int,
    max_adjustment: float,
) -> tuple[float, int]:
    """Return a bounded empirical nudge; never create semantic candidates."""
    if not stats:
        return 0.0, 0
    metrics = stats.get("skills", {}).get(skill_id)
    if not isinstance(metrics, Mapping):
        return 0.0, 0
    uses = int(metrics.get("uses", 0))
    if uses < min_samples:
        return 0.0, uses

    weighted = (
        int(metrics.get("pass", 0)) * 4.0
        + int(metrics.get("warn", 0)) * 1.0
        - int(metrics.get("unknown", 0)) * 2.0
        - int(metrics.get("fail", 0)) * 4.0
    ) / uses
    average_repairs = float(metrics.get("repair_cycles_total", 0)) / uses
    repair_penalty = min(1.5, average_repairs * 0.5)
    adjustment = weighted - repair_penalty
    adjustment = max(-max_adjustment, min(max_adjustment, adjustment))
    return round(adjustment, 2), uses


def _candidate(
    entry: Mapping[str, Any],
    *,
    reason: str,
    stats: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    base_priority = int(entry.get("priority", 0))
    adjustment, samples = feedback_adjustment(
        str(entry["id"]),
        stats=stats,
        min_samples=int(policy.get("feedback_min_samples", 3)),
        max_adjustment=float(policy.get("feedback_max_adjustment", 4)),
    )
    return {
        "id": str(entry["id"]),
        "priority": base_priority,
        "feedback_adjustment": adjustment,
        "feedback_samples": samples,
        "effective_priority": round(base_priority + adjustment, 2),
        "reason": reason,
    }


def select_skills(
    task: str,
    *,
    domains: Iterable[str] | None = None,
    registry: Mapping[str, Any] | None = None,
    include_manual: bool = False,
    stats: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic skill recommendations with compact routing reasons."""
    loaded = dict(registry or load_registry())
    policy = loaded["policy"]
    selected_domains = set(str(value) for value in (domains if domains is not None else classify_domains(task)))
    candidates: list[dict[str, Any]] = []

    for raw_entry in loaded["skills"]:
        entry = dict(raw_entry)
        if entry.get("mode") == "manual_only" and include_manual:
            normalized = _normalize(task)
            if any(_contains(normalized, str(trigger)) for trigger in entry.get("triggers", [])):
                candidates.append(
                    _candidate(entry, reason="explicit_manual_trigger", stats=stats, policy=policy)
                )
            continue

        matched, reason = _matches_entry(task, selected_domains, entry)
        if matched:
            candidates.append(_candidate(entry, reason=reason, stats=stats, policy=policy))

    candidates.sort(
        key=lambda item: (
            -float(item["effective_priority"]),
            -int(item["priority"]),
            str(item["id"]),
        )
    )
    max_selected = int(policy.get("max_auto_selected", 4))
    return candidates[:max_selected]


def route_task(
    task: str,
    *,
    available: Iterable[str] | None = None,
    include_manual: bool = False,
    registry: Mapping[str, Any] | None = None,
    stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable routing payload without claiming that a recommended skill was used."""
    loaded = dict(registry or load_registry())
    domains = classify_domains(task)
    selected = select_skills(
        task,
        domains=domains,
        registry=loaded,
        include_manual=include_manual,
        stats=stats,
    )
    recommended = [str(item["id"]) for item in selected]
    available_set = None if available is None else {str(value) for value in available}
    if available_set is None:
        loadable: list[str] = []
        unavailable: list[str] = []
    else:
        loadable = [skill_id for skill_id in recommended if skill_id in available_set]
        unavailable = [skill_id for skill_id in recommended if skill_id not in available_set]

    policy = loaded["policy"]
    return {
        "schema_version": ROUTER_SCHEMA_VERSION,
        "task_domains": domains,
        "recommended_skills": recommended,
        "selection": selected,
        "availability_known": available_set is not None,
        "loadable_skills": loadable,
        "unavailable_skills": unavailable,
        "feedback_stats_known": stats is not None,
        "policy": {
            "auto_install": bool(policy.get("auto_install", False)),
            "load_only_selected": bool(policy.get("load_only_selected", True)),
            "receipt_key": str(policy.get("receipt_key", "skills_used")),
            "feedback_min_samples": int(policy.get("feedback_min_samples", 3)),
            "feedback_max_adjustment": float(policy.get("feedback_max_adjustment", 4)),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="+", help="task description to route")
    parser.add_argument(
        "--available",
        action="append",
        default=None,
        help="installed skill id; repeat to enable availability filtering",
    )
    parser.add_argument(
        "--include-manual",
        action="store_true",
        help="allow manual-only skills when the task explicitly names their trigger",
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=None,
        help="optional compact feedback stats; defaults to MADO_SKILL_STATS or .mado-loop/skill_stats.json when present",
    )
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        stats_path = args.stats or discover_stats_path()
        stats = load_stats(stats_path) if stats_path is not None else None
        payload = route_task(
            " ".join(args.task),
            available=args.available,
            include_manual=args.include_manual,
            stats=stats,
        )
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"select_skills internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
