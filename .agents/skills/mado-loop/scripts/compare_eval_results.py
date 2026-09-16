"""Compare two MADO EVALS v0.1 results without collapsing proof into one score."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common.result import EXIT_INTERNAL, EXIT_USAGE_CONFIG  # noqa: E402

SCHEMA_VERSION = "0.1"
STATUS_RANK = {"FAIL": 0, "UNKNOWN": 1, "WARN": 2, "PASS": 3}
VERDICTS = ("PROMOTE_CANDIDATE", "HOLD", "REJECT", "UNKNOWN")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    _expect(isinstance(payload, dict), "eval result root must be an object")
    _expect(payload.get("schema_version") == SCHEMA_VERSION, "unsupported eval result schema")
    return payload


def _outcomes(result: Mapping[str, Any], key: str) -> dict[str, Mapping[str, Any]]:
    raw = result.get(key, [])
    _expect(isinstance(raw, list), f"{key} must be an array")
    output: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        _expect(isinstance(item, Mapping), f"{key} entries must be objects")
        outcome_id = str(item.get("id", ""))
        status = str(item.get("status", ""))
        _expect(outcome_id and status in STATUS_RANK, f"invalid {key} outcome")
        _expect(outcome_id not in output, f"duplicate {key} outcome id: {outcome_id}")
        output[outcome_id] = item
    return output


def _hard_delta(
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    key: str,
) -> list[dict[str, Any]]:
    left = _outcomes(champion, key)
    right = _outcomes(challenger, key)
    ids = sorted(set(left).union(right))
    deltas: list[dict[str, Any]] = []
    for outcome_id in ids:
        champion_item = left.get(outcome_id)
        challenger_item = right.get(outcome_id)
        required = bool(
            (champion_item or {}).get("required", False)
            or (challenger_item or {}).get("required", False)
        )
        if not required:
            continue
        champion_status = str((champion_item or {}).get("status", "UNKNOWN"))
        challenger_status = str((challenger_item or {}).get("status", "UNKNOWN"))
        delta = STATUS_RANK[challenger_status] - STATUS_RANK[champion_status]
        deltas.append({
            "id": outcome_id,
            "champion": champion_status,
            "challenger": challenger_status,
            "delta": delta,
        })
    return deltas


def _unknown_count(result: Mapping[str, Any]) -> int:
    count = 0
    for key in ("proof", "acceptance", "regressions"):
        for item in _outcomes(result, key).values():
            if bool(item.get("required", False)) and item.get("status") == "UNKNOWN":
                count += 1
    return count


def _metric(result: Mapping[str, Any], key: str) -> int | None:
    metrics = result.get("metrics", {})
    _expect(isinstance(metrics, Mapping), "metrics must be an object")
    value = metrics.get(key)
    if value is None:
        return None
    _expect(type(value) is int and value >= 0, f"metric {key} must be a non-negative integer or null")
    return value


def _compare_lower_is_better(champion_value: int | None, challenger_value: int | None) -> int | None:
    if champion_value is None or challenger_value is None:
        return None
    if challenger_value < champion_value:
        return 1
    if challenger_value > champion_value:
        return -1
    return 0


def compare_results(champion: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    """Return a gate-first comparison and advisory promotion verdict."""
    for label, result in (("champion", champion), ("challenger", challenger)):
        _expect(result.get("schema_version") == SCHEMA_VERSION, f"{label} has unsupported schema")

    champion_case = str(champion.get("case_id", ""))
    challenger_case = str(challenger.get("case_id", ""))
    champion_digest = str(champion.get("case_digest", ""))
    challenger_digest = str(challenger.get("case_digest", ""))
    if not champion_case or champion_case != challenger_case:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "UNKNOWN",
            "reason": "case_id_mismatch",
            "case_id": champion_case or challenger_case,
            "case_digest": None,
            "hard_gates": {},
            "stability": {},
            "efficiency": {},
        }
    if not champion_digest or champion_digest != challenger_digest:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "UNKNOWN",
            "reason": "case_digest_mismatch",
            "case_id": champion_case,
            "case_digest": None,
            "hard_gates": {},
            "stability": {},
            "efficiency": {},
        }

    proof_delta = _hard_delta(champion, challenger, key="proof")
    acceptance_delta = _hard_delta(champion, challenger, key="acceptance")
    regression_delta = _hard_delta(champion, challenger, key="regressions")
    hard = [*proof_delta, *acceptance_delta, *regression_delta]
    hard_regressions = [item for item in hard if item["delta"] < 0]
    hard_improvements = [item for item in hard if item["delta"] > 0]

    champion_unknowns = _unknown_count(champion)
    challenger_unknowns = _unknown_count(challenger)
    unknown_delta = _compare_lower_is_better(champion_unknowns, challenger_unknowns)
    repair_delta = _compare_lower_is_better(
        _metric(champion, "repair_cycles"),
        _metric(challenger, "repair_cycles"),
    )
    champion_failures = len(set(str(item) for item in champion.get("failure_signatures", [])))
    challenger_failures = len(set(str(item) for item in challenger.get("failure_signatures", [])))
    failure_delta = _compare_lower_is_better(champion_failures, challenger_failures)
    stability_values = [unknown_delta, repair_delta, failure_delta]
    stability_known = [value for value in stability_values if value is not None]
    stability_mixed = any(value > 0 for value in stability_known) and any(value < 0 for value in stability_known)
    stability_improves = bool(stability_known) and all(value >= 0 for value in stability_known) and any(value > 0 for value in stability_known)
    stability_regresses = bool(stability_known) and all(value <= 0 for value in stability_known) and any(value < 0 for value in stability_known)

    token_delta = _compare_lower_is_better(_metric(champion, "tokens"), _metric(challenger, "tokens"))
    time_delta = _compare_lower_is_better(_metric(champion, "wall_time_ms"), _metric(challenger, "wall_time_ms"))
    efficiency_known = [value for value in (token_delta, time_delta) if value is not None]
    efficiency_mixed = any(value > 0 for value in efficiency_known) and any(value < 0 for value in efficiency_known)
    efficiency_improves = bool(efficiency_known) and all(value >= 0 for value in efficiency_known) and any(value > 0 for value in efficiency_known)

    if hard_regressions:
        verdict = "REJECT"
        reason = "hard_gate_regression"
    elif hard_improvements:
        verdict = "PROMOTE_CANDIDATE"
        reason = "hard_gate_improvement_without_regression"
    elif stability_mixed or stability_regresses:
        verdict = "HOLD"
        reason = "mixed_or_worse_stability"
    elif stability_improves:
        verdict = "PROMOTE_CANDIDATE"
        reason = "stability_improvement"
    elif efficiency_mixed:
        verdict = "HOLD"
        reason = "mixed_efficiency"
    elif efficiency_improves:
        verdict = "PROMOTE_CANDIDATE"
        reason = "efficiency_improvement_after_equal_gates"
    else:
        verdict = "HOLD"
        reason = "no_clear_improvement"

    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "reason": reason,
        "case_id": champion_case,
        "case_digest": champion_digest,
        "champion": dict(champion.get("candidate", {})),
        "challenger": dict(challenger.get("candidate", {})),
        "hard_gates": {
            "proof": proof_delta,
            "acceptance": acceptance_delta,
            "regressions": regression_delta,
            "regression_count": len(hard_regressions),
            "improvement_count": len(hard_improvements),
        },
        "stability": {
            "champion_unknowns": champion_unknowns,
            "challenger_unknowns": challenger_unknowns,
            "unknown_delta": unknown_delta,
            "repair_cycles_delta": repair_delta,
            "failure_signature_delta": failure_delta,
        },
        "efficiency": {
            "tokens_delta": token_delta,
            "wall_time_delta": time_delta,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("champion", type=Path)
    parser.add_argument("challenger", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return 0 if exc.code == 0 else EXIT_USAGE_CONFIG
    try:
        comparison = compare_results(_load(args.champion), _load(args.challenger))
        if args.pretty:
            sys.stdout.write(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(json.dumps(comparison, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"compare_eval_results error: {exc}\n")
        return EXIT_USAGE_CONFIG
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        sys.stderr.write(f"compare_eval_results internal error: {exc}\n")
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
