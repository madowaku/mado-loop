"""Calibrate MADO LOOP's seven-day Codex Plus pacing from an observed account status.

Codex account limits are dynamic and are not exposed as a stable local quota API.
This module therefore accepts a manual observation from Codex `/status` or the
ChatGPT usage dashboard: remaining weekly percent plus time until reset. It
persists only those coarse pacing values, never credentials or conversation data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Sequence


SCHEMA_VERSION = "mado-codex-plus-status/v1"
DEFAULT_STATUS_PATH = Path(".mado-loop/codex-plus/status.json")
WEEK_HOURS = 7 * 24
MODES = ("normal", "conserve", "critical")


class CodexPlusBudgetError(ValueError):
    """Raised when a manual usage observation is invalid."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def make_observation(
    *,
    remaining_percent: float,
    hours_until_reset: float,
    now: datetime | None = None,
) -> dict[str, object]:
    if not 0 <= remaining_percent <= 100:
        raise CodexPlusBudgetError("remaining percent must be between 0 and 100")
    if not 0 < hours_until_reset <= WEEK_HOURS * 1.25:
        raise CodexPlusBudgetError("hours until reset must be greater than zero and plausibly weekly")
    observed = now or _utcnow()
    reset_at = observed + timedelta(hours=hours_until_reset)
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": _iso(observed),
        "reset_at": _iso(reset_at),
        "remaining_percent": round(float(remaining_percent), 3),
        "source": "manual observation from Codex /status or ChatGPT usage dashboard",
    }


def save_observation(path: Path, observation: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_observation(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return None
    return value


def calibrated_pressure(
    observation: dict[str, object] | None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or _utcnow()
    if not observation:
        return {
            "mode": "normal",
            "calibrated": False,
            "reason": "no account-status observation; local ledger only",
            "remaining_percent": None,
            "hours_until_reset": None,
            "pace_ratio": None,
        }
    reset_at = _parse_time(observation.get("reset_at"))
    remaining = observation.get("remaining_percent")
    if reset_at is None or not isinstance(remaining, (int, float)):
        return {
            "mode": "normal",
            "calibrated": False,
            "reason": "invalid account-status observation",
            "remaining_percent": None,
            "hours_until_reset": None,
            "pace_ratio": None,
        }
    hours_left = max(0.0, (reset_at - current).total_seconds() / 3600.0)
    if hours_left <= 0:
        return {
            "mode": "normal",
            "calibrated": False,
            "reason": "observed weekly window has reset; refresh from /status",
            "remaining_percent": float(remaining),
            "hours_until_reset": 0.0,
            "pace_ratio": None,
        }

    expected_remaining = min(1.0, hours_left / WEEK_HOURS)
    actual_remaining = max(0.0, min(1.0, float(remaining) / 100.0))
    pace_ratio = actual_remaining / expected_remaining if expected_remaining > 0 else 1.0
    if pace_ratio < 0.70:
        mode = "critical"
    elif pace_ratio < 0.90:
        mode = "conserve"
    else:
        mode = "normal"
    return {
        "mode": mode,
        "calibrated": True,
        "reason": "actual weekly remaining compared with remaining-time fraction",
        "remaining_percent": round(actual_remaining * 100.0, 3),
        "hours_until_reset": round(hours_left, 3),
        "expected_remaining_percent_for_even_pace": round(expected_remaining * 100.0, 3),
        "pace_ratio": round(pace_ratio, 4),
        "reset_at": _iso(reset_at),
    }


def stricter_mode(*modes: str) -> str:
    rank = {"normal": 0, "conserve": 1, "critical": 2}
    unknown = [mode for mode in modes if mode not in rank]
    if unknown:
        raise CodexPlusBudgetError(f"unknown budget mode: {unknown[0]}")
    return max(modes, key=lambda mode: rank[mode], default="normal")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="Store a manual weekly account-status observation")
    sync.add_argument("--remaining-percent", required=True, type=float)
    sync.add_argument("--hours-until-reset", required=True, type=float)
    sync.add_argument("--status-file")
    status = sub.add_parser("status", help="Show the calibrated seven-day pressure")
    status.add_argument("--status-file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = Path(args.status_file) if args.status_file else DEFAULT_STATUS_PATH
    try:
        if args.command == "sync":
            observation = make_observation(
                remaining_percent=args.remaining_percent,
                hours_until_reset=args.hours_until_reset,
            )
            save_observation(path, observation)
        else:
            observation = load_observation(path)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "status_file": str(path),
            "observation": observation,
            "pressure": calibrated_pressure(observation),
            "authority": "Codex /status or ChatGPT usage dashboard",
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except CodexPlusBudgetError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
