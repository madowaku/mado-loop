"""Record compact specialist-skill outcomes and rebuild router statistics."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

STATUSES = ("PASS", "WARN", "UNKNOWN", "FAIL")
LEDGER_SCHEMA_VERSION = "1"
STATS_SCHEMA_VERSION = "1"
DEFAULT_LEDGER = Path(".mado-loop") / "skill_feedback.jsonl"
DEFAULT_STATS = Path(".mado-loop") / "skill_stats.json"
RECEIPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def canonical_event(
    *,
    receipt_id: str,
    status: str,
    skills_used: Iterable[str],
    repair_cycles: int = 0,
    tokens: int | None = None,
) -> dict[str, Any]:
    """Build one content-free, deterministic feedback event."""
    normalized_id = str(receipt_id).strip()
    if not RECEIPT_ID_RE.fullmatch(normalized_id):
        raise ValueError("receipt_id must be a short opaque identifier")
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    skills = sorted({str(value).strip() for value in skills_used if str(value).strip()})
    if not skills:
        raise ValueError("at least one actually used specialist skill is required")
    if any(not SKILL_ID_RE.fullmatch(skill_id) for skill_id in skills):
        raise ValueError("skills_used must contain canonical skill ids only")
    if repair_cycles < 0:
        raise ValueError("repair_cycles must be >= 0")
    if tokens is not None and tokens < 0:
        raise ValueError("tokens must be >= 0")
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "receipt_id": normalized_id,
        "status": status,
        "skills_used": skills,
        "repair_cycles": int(repair_cycles),
        "tokens": None if tokens is None else int(tokens),
    }


def event_json(event: Mapping[str, Any]) -> str:
    return json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def load_events(path: str | Path) -> list[dict[str, Any]]:
    ledger = Path(path)
    if not ledger.is_file():
        return []
    events: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for line_number, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if payload.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ValueError(f"unsupported feedback schema on line {line_number}")
        event = canonical_event(
            receipt_id=str(payload.get("receipt_id", "")),
            status=str(payload.get("status", "")),
            skills_used=payload.get("skills_used", []),
            repair_cycles=int(payload.get("repair_cycles", 0)),
            tokens=payload.get("tokens"),
        )
        canonical = event_json(event)
        receipt_id = event["receipt_id"]
        previous = seen.get(receipt_id)
        if previous is not None and previous != canonical:
            raise ValueError(f"conflicting duplicate receipt_id: {receipt_id}")
        if previous is None:
            events.append(event)
            seen[receipt_id] = canonical
    return events


def build_stats(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate ledger events into the tiny cache consumed by the selector."""
    by_skill: dict[str, dict[str, Any]] = {}
    receipt_count = 0
    for raw in events:
        receipt_count += 1
        status = str(raw["status"])
        repairs = int(raw.get("repair_cycles", 0))
        tokens = raw.get("tokens")
        for skill_id in raw.get("skills_used", []):
            metrics = by_skill.setdefault(
                str(skill_id),
                {
                    "uses": 0,
                    "pass": 0,
                    "warn": 0,
                    "unknown": 0,
                    "fail": 0,
                    "repair_cycles_total": 0,
                    "token_samples": 0,
                    "tokens_total": 0,
                },
            )
            metrics["uses"] += 1
            metrics[status.casefold()] += 1
            metrics["repair_cycles_total"] += repairs
            if tokens is not None:
                metrics["token_samples"] += 1
                metrics["tokens_total"] += int(tokens)
    return {
        "schema_version": STATS_SCHEMA_VERSION,
        "receipt_count": receipt_count,
        "skills": {skill_id: by_skill[skill_id] for skill_id in sorted(by_skill)},
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def record_event(
    *,
    ledger_path: str | Path,
    stats_path: str | Path,
    event: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Append one idempotent event and atomically rebuild compact statistics."""
    ledger = Path(ledger_path)
    stats = Path(stats_path)
    existing = load_events(ledger)
    canonical = event_json(event)
    by_id = {str(item["receipt_id"]): event_json(item) for item in existing}
    receipt_id = str(event["receipt_id"])
    previous = by_id.get(receipt_id)
    if previous is not None:
        if previous != canonical:
            raise ValueError(f"receipt_id already exists with different feedback: {receipt_id}")
        aggregated = build_stats(existing)
        _atomic_write(stats, json.dumps(aggregated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return aggregated, False

    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical + "\n")
    aggregated = build_stats([*existing, dict(event)])
    _atomic_write(stats, json.dumps(aggregated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return aggregated, True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-id", required=True, help="stable opaque bounded-task receipt id")
    parser.add_argument("--status", required=True, choices=STATUSES)
    parser.add_argument("--skill", action="append", required=True, dest="skills")
    parser.add_argument("--repair-cycles", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=None, help="observed total tokens when available")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        event = canonical_event(
            receipt_id=args.receipt_id,
            status=args.status,
            skills_used=args.skills,
            repair_cycles=args.repair_cycles,
            tokens=args.tokens,
        )
        stats, appended = record_event(
            ledger_path=args.ledger,
            stats_path=args.stats,
            event=event,
        )
        payload = {
            "status": "PASS",
            "appended": appended,
            "receipt_id": event["receipt_id"],
            "skills_used": event["skills_used"],
            "stats_path": str(args.stats),
            "receipt_count": stats["receipt_count"],
        }
        if args.pretty:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        else:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        return 0
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"record_skill_feedback error: {exc}\n")
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
