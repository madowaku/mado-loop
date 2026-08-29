"""Calibrate MADO LOOP Codex Plus pacing against the next observed reset.

ChatGPT-plan limits are dynamic. This controller therefore does not assume a
seven-day quota or a fixed Luna Max surcharge. It stores coarse `/status`
observations, learns the observed percentage burn rate inside the current reset
window, and recommends a burn state that aims to avoid both early exhaustion
and large unused headroom at reset.

No prompt, response, credential, or API key is persisted here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Sequence


SCHEMA_VERSION = "mado-codex-plus-status/v2"
LEGACY_SCHEMA_VERSION = "mado-codex-plus-status/v1"
OBSERVATION_VERSION = "mado-codex-plus-observation/v1"
DEFAULT_STATUS_PATH = Path(".mado-loop/codex-plus/status.json")
MAX_RESET_HOURS = 24 * 30
MAX_HISTORY = 32
RATE_LOOKBACK_HOURS = 24.0
MIN_RATE_WINDOW_HOURS = 0.25
RESET_TOLERANCE_HOURS = 2.0
RESERVE_PERCENT = 5.0
MODES = ("normal", "conserve", "critical")
BURN_STATES = ("aggressive", "normal", "conserve", "critical")


class CodexPlusBudgetError(ValueError):
    """Raised when an account-status observation or pacing state is invalid."""


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
    if not 0 < hours_until_reset <= MAX_RESET_HOURS:
        raise CodexPlusBudgetError(
            f"hours until reset must be greater than zero and no more than {MAX_RESET_HOURS}"
        )
    observed = now or _utcnow()
    reset_at = observed + timedelta(hours=hours_until_reset)
    return {
        "schema_version": OBSERVATION_VERSION,
        "observed_at": _iso(observed),
        "reset_at": _iso(reset_at),
        "remaining_percent": round(float(remaining_percent), 3),
        "source": "manual observation from Codex /status or ChatGPT usage dashboard",
    }


def _normalise_store(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") == SCHEMA_VERSION:
        observations = value.get("observations")
        if not isinstance(observations, list):
            return None
        clean = [item for item in observations if isinstance(item, dict)]
        return {
            "schema_version": SCHEMA_VERSION,
            "observations": clean[-MAX_HISTORY:],
        }
    if value.get("schema_version") == LEGACY_SCHEMA_VERSION:
        legacy = dict(value)
        legacy["schema_version"] = OBSERVATION_VERSION
        return {
            "schema_version": SCHEMA_VERSION,
            "observations": [legacy],
            "migrated_from": LEGACY_SCHEMA_VERSION,
        }
    if value.get("schema_version") == OBSERVATION_VERSION:
        return {
            "schema_version": SCHEMA_VERSION,
            "observations": [value],
        }
    return None


def save_observation(path: Path, observation: dict[str, object]) -> None:
    existing = load_observation(path)
    history = [] if existing is None else list(existing.get("observations", []))
    history.append(observation)
    history = [item for item in history if isinstance(item, dict)][-MAX_HISTORY:]
    store = {
        "schema_version": SCHEMA_VERSION,
        "observations": history,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_observation(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _normalise_store(value)


def _valid_observations(store: dict[str, object] | None) -> list[dict[str, object]]:
    if not store:
        return []
    raw = store.get("observations")
    if not isinstance(raw, list):
        return []
    rows: list[tuple[datetime, dict[str, object]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        observed_at = _parse_time(item.get("observed_at"))
        reset_at = _parse_time(item.get("reset_at"))
        remaining = item.get("remaining_percent")
        if observed_at is None or reset_at is None or not isinstance(remaining, (int, float)):
            continue
        if not 0 <= float(remaining) <= 100:
            continue
        rows.append((observed_at, item))
    rows.sort(key=lambda pair: pair[0])
    return [item for _, item in rows]


def _same_reset_window(left: dict[str, object], right: dict[str, object]) -> bool:
    left_reset = _parse_time(left.get("reset_at"))
    right_reset = _parse_time(right.get("reset_at"))
    if left_reset is None or right_reset is None:
        return False
    return abs((left_reset - right_reset).total_seconds()) <= RESET_TOLERANCE_HOURS * 3600.0


def _current_window(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not rows:
        return []
    latest = rows[-1]
    window = [row for row in rows if _same_reset_window(row, latest)]
    latest_time = _parse_time(latest.get("observed_at"))
    if latest_time is None:
        return window[-1:]
    cutoff = latest_time - timedelta(hours=RATE_LOOKBACK_HOURS)
    recent = [
        row
        for row in window
        if (_parse_time(row.get("observed_at")) or latest_time) >= cutoff
    ]
    return recent or window[-1:]


def _burn_rate(rows: list[dict[str, object]]) -> tuple[float | None, float | None]:
    if len(rows) < 2:
        return None, None
    first = rows[0]
    latest = rows[-1]
    first_time = _parse_time(first.get("observed_at"))
    latest_time = _parse_time(latest.get("observed_at"))
    if first_time is None or latest_time is None:
        return None, None
    elapsed = (latest_time - first_time).total_seconds() / 3600.0
    if elapsed < MIN_RATE_WINDOW_HOURS:
        return None, elapsed
    first_remaining = float(first.get("remaining_percent", 0.0))
    latest_remaining = float(latest.get("remaining_percent", 0.0))
    burned = max(0.0, first_remaining - latest_remaining)
    return burned / elapsed, elapsed


def calibrated_pressure(
    observation: dict[str, object] | None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or _utcnow()
    store = _normalise_store(observation) if observation else None
    rows = _valid_observations(store)
    if not rows:
        return {
            "mode": "normal",
            "burn_state": "normal",
            "calibrated": False,
            "reason": "no account-status observation; local ledger only",
            "remaining_percent": None,
            "hours_until_reset": None,
            "burn_rate_percent_per_hour": None,
            "sustainable_rate_percent_per_hour": None,
            "projected_remaining_at_reset": None,
            "max_recommended": False,
        }

    latest = rows[-1]
    reset_at = _parse_time(latest.get("reset_at"))
    remaining = float(latest.get("remaining_percent", 0.0))
    if reset_at is None:
        raise CodexPlusBudgetError("latest account-status observation has no valid reset time")
    hours_left = max(0.0, (reset_at - current).total_seconds() / 3600.0)
    if hours_left <= 0:
        return {
            "mode": "normal",
            "burn_state": "normal",
            "calibrated": False,
            "reason": "observed reset window has ended; refresh from /status",
            "remaining_percent": round(remaining, 3),
            "hours_until_reset": 0.0,
            "burn_rate_percent_per_hour": None,
            "sustainable_rate_percent_per_hour": None,
            "projected_remaining_at_reset": None,
            "max_recommended": False,
            "reset_at": _iso(reset_at),
        }

    window = _current_window(rows)
    rate, rate_window = _burn_rate(window)
    spendable = max(0.0, remaining - RESERVE_PERCENT)
    sustainable_rate = spendable / hours_left if hours_left > 0 else 0.0
    projected = None if rate is None else max(0.0, remaining - rate * hours_left)
    ratio = None
    if rate is not None:
        if sustainable_rate <= 0:
            ratio = float("inf") if rate > 0 else 0.0
        else:
            ratio = rate / sustainable_rate

    if remaining <= RESERVE_PERCENT and hours_left > 1.0:
        burn_state = "critical"
        reason = "remaining allowance is at or below the reset reserve"
    elif rate is not None and (projected is not None and projected <= 0.0 or ratio is not None and ratio >= 1.5):
        burn_state = "critical"
        reason = "observed burn rate projects exhaustion before reset"
    elif rate is not None and (
        projected is not None and projected < RESERVE_PERCENT
        or ratio is not None and ratio >= 1.15
    ):
        burn_state = "conserve"
        reason = "observed burn rate is above the sustainable reset pace"
    elif rate is not None and remaining >= 20.0 and (
        projected is not None and projected >= 20.0
        or ratio is not None and ratio <= 0.60
    ):
        burn_state = "aggressive"
        reason = "observed burn rate leaves substantial unused headroom at reset"
    elif rate is None and (
        (hours_left <= 24.0 and remaining >= 35.0)
        or (hours_left <= 6.0 and remaining >= 15.0)
    ):
        burn_state = "aggressive"
        reason = "single status snapshot shows large headroom close to reset"
    else:
        burn_state = "normal"
        reason = "observed burn rate is compatible with the next reset horizon"

    mode = burn_state if burn_state in {"conserve", "critical"} else "normal"
    return {
        "mode": mode,
        "burn_state": burn_state,
        "calibrated": True,
        "reason": reason,
        "remaining_percent": round(remaining, 3),
        "hours_until_reset": round(hours_left, 3),
        "reset_at": _iso(reset_at),
        "observations_in_current_window": len(window),
        "burn_rate_window_hours": round(rate_window, 3) if rate_window is not None else None,
        "burn_rate_percent_per_hour": round(rate, 6) if rate is not None else None,
        "sustainable_rate_percent_per_hour": round(sustainable_rate, 6),
        "burn_to_sustainable_ratio": round(ratio, 4) if ratio is not None and ratio != float("inf") else ("inf" if ratio == float("inf") else None),
        "projected_remaining_at_reset": round(projected, 3) if projected is not None else None,
        "reserve_percent": RESERVE_PERCENT,
        "max_recommended": burn_state == "aggressive" and remaining >= 15.0,
        "max_policy": "headroom-driven; no fixed discount assumption",
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
    sync = sub.add_parser("sync", help="Append a manual account-status observation")
    sync.add_argument("--remaining-percent", required=True, type=float)
    sync.add_argument("--hours-until-reset", required=True, type=float)
    sync.add_argument("--status-file")
    status = sub.add_parser("status", help="Show reset-aware burn pressure")
    status.add_argument("--status-file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = Path(args.status_file) if args.status_file else DEFAULT_STATUS_PATH
    try:
        if args.command == "sync":
            new_observation = make_observation(
                remaining_percent=args.remaining_percent,
                hours_until_reset=args.hours_until_reset,
            )
            save_observation(path, new_observation)
        store = load_observation(path)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "status_file": str(path),
            "observation": store,
            "pressure": calibrated_pressure(store),
            "authority": "Codex /status or ChatGPT usage dashboard",
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except CodexPlusBudgetError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
