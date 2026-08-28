"""Deterministically recommend on-demand specialist skills for a MADO LOOP task."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = SKILL_ROOT / "skill_registry.yaml"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from classify_task import classify_domains  # noqa: E402
from common.result import EXIT_INTERNAL, EXIT_USAGE_CONFIG  # noqa: E402

ROUTER_SCHEMA_VERSION = "1"


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


def select_skills(
    task: str,
    *,
    domains: Iterable[str] | None = None,
    registry: Mapping[str, Any] | None = None,
    include_manual: bool = False,
) -> list[dict[str, Any]]:
    """Return deterministic skill recommendations with compact routing reasons."""
    loaded = dict(registry or load_registry())
    selected_domains = set(str(value) for value in (domains if domains is not None else classify_domains(task)))
    candidates: list[dict[str, Any]] = []

    for raw_entry in loaded["skills"]:
        entry = dict(raw_entry)
        if entry.get("mode") == "manual_only" and include_manual:
            normalized = _normalize(task)
            if any(_contains(normalized, str(trigger)) for trigger in entry.get("triggers", [])):
                candidates.append({
                    "id": str(entry["id"]),
                    "priority": int(entry.get("priority", 0)),
                    "reason": "explicit_manual_trigger",
                })
            continue

        matched, reason = _matches_entry(task, selected_domains, entry)
        if matched:
            candidates.append({
                "id": str(entry["id"]),
                "priority": int(entry.get("priority", 0)),
                "reason": reason,
            })

    candidates.sort(key=lambda item: (-int(item["priority"]), str(item["id"])))
    max_selected = int(loaded["policy"].get("max_auto_selected", 4))
    return candidates[:max_selected]


def route_task(
    task: str,
    *,
    available: Iterable[str] | None = None,
    include_manual: bool = False,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable routing payload without claiming that a recommended skill was used."""
    loaded = dict(registry or load_registry())
    domains = classify_domains(task)
    selected = select_skills(
        task, domains=domains, registry=loaded, include_manual=include_manual
    )
    recommended = [str(item["id"]) for item in selected]
    available_set = None if available is None else {str(value) for value in available}
    if available_set is None:
        loadable: list[str] = []
        unavailable: list[str] = []
    else:
        loadable = [skill_id for skill_id in recommended if skill_id in available_set]
        unavailable = [skill_id for skill_id in recommended if skill_id not in available_set]

    return {
        "schema_version": ROUTER_SCHEMA_VERSION,
        "task_domains": domains,
        "recommended_skills": recommended,
        "selection": selected,
        "availability_known": available_set is not None,
        "loadable_skills": loadable,
        "unavailable_skills": unavailable,
        "policy": {
            "auto_install": bool(loaded["policy"].get("auto_install", False)),
            "load_only_selected": bool(loaded["policy"].get("load_only_selected", True)),
            "receipt_key": str(loaded["policy"].get("receipt_key", "skills_used")),
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
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        payload = route_task(
            " ".join(args.task), available=args.available, include_manual=args.include_manual
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
