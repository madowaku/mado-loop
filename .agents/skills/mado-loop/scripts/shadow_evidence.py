"""Record G3 shadow comparisons and join them to real execution outcomes.

G4 is an append-only semantic ledger. It stores bounded, content-free shadow
context and a later observed outcome as separate immutable events, then
materializes them into one inspectable receipt.

It never executes a strategy, ranks candidates, attributes a legacy outcome to
an unexecuted G3 candidate, grants authority, or changes live routing.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from strategy_resolver import StrategyResolverError  # noqa: E402

SCHEMA_VERSION = "1.0"
EVENT_TYPES = ("SHADOW_CAPTURED", "OUTCOME_JOINED")
ROUTE_KINDS = ("legacy", "g3_candidate")
JOIN_STATES = ("PENDING", "JOINED")
RESULT_STATUSES = ("PASS", "WARN", "UNKNOWN", "FAIL", "SKIPPED")
EVAL_STATUSES = ("PASS", "WARN", "UNKNOWN", "FAIL")
PROOF_LEVELS = ("P0", "P1", "P2", "P3", "P4", "P5")
CANDIDATE_STATES = ("READY", "CONDITIONAL", "BLOCKED")
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DEFAULT_LEDGER = Path(".mado-loop") / "shadow_evidence.jsonl"


class ShadowEvidenceError(ValueError):
    """Raised when a G4 event or join violates the shadow evidence contract."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ShadowEvidenceError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _normalize_time(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowEvidenceError("timestamp must be an ISO-8601 date-time") from exc
    _expect(parsed.tzinfo is not None, "timestamp must include a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def _opaque(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    _expect(OPAQUE_ID_RE.fullmatch(text) is not None, f"{label} must be a short opaque identifier")
    return text


def _digest_value(value: Any, *, label: str) -> str:
    text = str(value or "")
    _expect(DIGEST_RE.fullmatch(text) is not None, f"{label} is invalid")
    return text


def _string_list(value: Any, *, label: str) -> list[str]:
    _expect(isinstance(value, list), f"{label} must be an array")
    items = [str(item) for item in value]
    _expect(all(item for item in items), f"{label} contains empty values")
    _expect(len(items) == len(set(items)), f"{label} must not contain duplicates")
    return items


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ShadowEvidenceError(f"{label} is not valid JSON: {exc}") from exc
    _expect(isinstance(payload, dict), f"{label} must be an object")
    return payload


def _candidate_summary(raw: Any) -> dict[str, Any]:
    _expect(isinstance(raw, Mapping), "G3 candidate must be an object")
    required = {
        "id",
        "strategy",
        "state",
        "coordination",
        "required_features",
        "bindings",
        "authority_checks",
        "proof_target",
        "reasons",
    }
    _expect(set(raw) == required, "G3 candidate keys are invalid")
    candidate_id = _opaque(raw.get("id"), label="candidate.id")
    strategy = _opaque(raw.get("strategy"), label="candidate.strategy")
    state = str(raw.get("state"))
    _expect(state in CANDIDATE_STATES, "candidate.state is invalid")
    coordination = str(raw.get("coordination"))
    _expect(coordination in {"single", "single+delegate", "multi"}, "candidate.coordination is invalid")
    proof_target = str(raw.get("proof_target"))
    _expect(proof_target in PROOF_LEVELS, "candidate.proof_target is invalid")
    required_features = _string_list(raw.get("required_features"), label="candidate.required_features")
    reasons = _string_list(raw.get("reasons"), label="candidate.reasons")

    capability_ids: set[str] = set()
    bindings = raw.get("bindings")
    _expect(isinstance(bindings, list), "candidate.bindings must be an array")
    for binding in bindings:
        _expect(isinstance(binding, Mapping), "candidate binding must be an object")
        matches = binding.get("matches")
        _expect(isinstance(matches, list), "candidate binding matches must be an array")
        for match in matches:
            _expect(isinstance(match, Mapping), "candidate match must be an object")
            capability_ids.add(_opaque(match.get("capability_id"), label="candidate capability_id"))

    return {
        "id": candidate_id,
        "strategy": strategy,
        "state": state,
        "coordination": coordination,
        "proof_target": proof_target,
        "required_features": required_features,
        "capability_ids": sorted(capability_ids),
        "reasons": reasons,
    }


def normalize_shadow_compare(value: Any) -> dict[str, Any]:
    """Reduce a G3 shadow comparison to bounded, content-free evidence."""
    _expect(isinstance(value, Mapping), "shadow comparison must be an object")
    _expect(value.get("schema_version") == "1.0", "unsupported shadow comparison schema_version")
    _expect(value.get("shadow_only") is True, "shadow comparison must be shadow_only")

    intent_id = _opaque(value.get("intent_id"), label="shadow.intent_id")
    legacy_raw = value.get("legacy")
    g3_raw = value.get("g3")
    comparison_raw = value.get("comparison")
    _expect(isinstance(legacy_raw, Mapping), "shadow.legacy must be an object")
    _expect(isinstance(g3_raw, Mapping), "shadow.g3 must be an object")
    _expect(isinstance(comparison_raw, Mapping), "shadow.comparison must be an object")
    _expect(g3_raw.get("schema_version") == "1.0", "unsupported G3 schema_version")
    _expect(g3_raw.get("advisory_only") is True, "G3 candidate set must be advisory_only")
    _expect(str(g3_raw.get("intent_id")) == intent_id, "shadow and G3 intent_id mismatch")

    legacy_source = str(legacy_raw.get("source"))
    _expect(legacy_source in {"projection", "observed"}, "legacy source is invalid")
    legacy = {
        "source": legacy_source,
        "strategy": _opaque(legacy_raw.get("strategy"), label="legacy.strategy"),
        "domains": _string_list(legacy_raw.get("domains"), label="legacy.domains"),
        "roles": _string_list(legacy_raw.get("roles"), label="legacy.roles"),
        "review": bool(legacy_raw.get("review")),
        "source_ref": _opaque(legacy_raw.get("source_ref"), label="legacy.source_ref"),
    }

    raw_candidates = g3_raw.get("candidates")
    _expect(isinstance(raw_candidates, list), "G3 candidates must be an array")
    candidates = [_candidate_summary(item) for item in raw_candidates]
    candidate_ids = [item["id"] for item in candidates]
    _expect(len(candidate_ids) == len(set(candidate_ids)), "G3 candidate ids must be unique")
    candidates.sort(key=lambda item: item["id"])

    comparison_required = {
        "domain_exact_match",
        "intent_domains",
        "legacy_domains",
        "ready_strategies",
        "conditional_strategies",
        "blocked_strategies",
        "legacy_role_count",
        "observations",
    }
    _expect(set(comparison_raw) == comparison_required, "shadow comparison summary keys are invalid")
    legacy_role_count = comparison_raw.get("legacy_role_count")
    _expect(type(legacy_role_count) is int and legacy_role_count >= 0, "legacy_role_count is invalid")

    context = {
        "intent_id": intent_id,
        "intent_digest": _digest_value(g3_raw.get("intent_digest"), label="intent_digest"),
        "authority_digest": _digest_value(g3_raw.get("authority_digest"), label="authority_digest"),
        "snapshot_state_digest": _digest_value(g3_raw.get("snapshot_state_digest"), label="snapshot_state_digest"),
        "registry_digest": _digest_value(g3_raw.get("registry_digest"), label="registry_digest"),
    }
    comparison = {
        "domain_exact_match": bool(comparison_raw.get("domain_exact_match")),
        "intent_domains": _string_list(comparison_raw.get("intent_domains"), label="comparison.intent_domains"),
        "legacy_domains": _string_list(comparison_raw.get("legacy_domains"), label="comparison.legacy_domains"),
        "ready_strategies": _string_list(comparison_raw.get("ready_strategies"), label="comparison.ready_strategies"),
        "conditional_strategies": _string_list(comparison_raw.get("conditional_strategies"), label="comparison.conditional_strategies"),
        "blocked_strategies": _string_list(comparison_raw.get("blocked_strategies"), label="comparison.blocked_strategies"),
        "legacy_role_count": legacy_role_count,
        "observations": _string_list(comparison_raw.get("observations"), label="comparison.observations"),
    }
    return {
        "context": context,
        "legacy": legacy,
        "g3_candidates": candidates,
        "comparison": comparison,
    }


def build_capture_event(
    *,
    receipt_id: str,
    shadow_compare: Mapping[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_receipt = _opaque(receipt_id, label="receipt_id")
    shadow = normalize_shadow_compare(shadow_compare)
    payload = {
        **shadow,
        "shadow_digest": _digest(shadow),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"capture:{normalized_receipt}",
        "event_type": "SHADOW_CAPTURED",
        "receipt_id": normalized_receipt,
        "observed_at": _normalize_time(observed_at),
        "payload": payload,
    }


def _status_counts(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        status = str(item.get("status", ""))
        if status:
            counts[status] += 1
    return {key: counts[key] for key in sorted(counts)}


def normalize_outcome(value: Any) -> dict[str, Any]:
    """Project supported real result contracts into a bounded outcome summary."""
    _expect(isinstance(value, Mapping), "outcome must be an object")
    source_digest = _digest(dict(value))

    if value.get("schema_version") == "1.1" and "tool" in value:
        status = str(value.get("status"))
        _expect(status in RESULT_STATUSES, "result-v1.1 status is invalid")
        proof_level = value.get("proof_level")
        _expect(proof_level is None or proof_level in PROOF_LEVELS, "result-v1.1 proof_level is invalid")
        duration_ms = value.get("duration_ms")
        _expect(type(duration_ms) is int and duration_ms >= 0, "result-v1.1 duration_ms is invalid")
        checks = value.get("checks")
        artifacts = value.get("artifacts")
        errors = value.get("errors")
        warnings = value.get("warnings")
        unknowns = value.get("unknowns")
        task_domains = value.get("task_domains")
        _expect(isinstance(checks, list), "result-v1.1 checks must be an array")
        _expect(isinstance(artifacts, list), "result-v1.1 artifacts must be an array")
        _expect(isinstance(errors, list) and isinstance(warnings, list) and isinstance(unknowns, list), "result-v1.1 findings must be arrays")
        _expect(isinstance(task_domains, list), "result-v1.1 task_domains must be an array")
        return {
            "source_kind": "result-v1.1",
            "source_digest": source_digest,
            "status": status,
            "proof_level": proof_level,
            "proof_status": None,
            "task_domains": [str(item) for item in task_domains],
            "status_counts": _status_counts(checks),
            "metrics": {
                "duration_ms": duration_ms,
                "repair_cycles": None,
                "tokens": None,
                "wall_time_ms": None,
            },
            "counts": {
                "checks": len(checks),
                "artifacts": len(artifacts),
                "errors": len(errors),
                "warnings": len(warnings),
                "unknowns": len(unknowns),
            },
        }

    if value.get("schema_version") == "0.1" and "case_id" in value and "proof_status" in value:
        status = str(value.get("status"))
        _expect(status in EVAL_STATUSES, "eval-result-v0.1 status is invalid")
        proof_status = str(value.get("proof_status"))
        _expect(proof_status in {"PROVEN", "PARTIAL", "UNPROVEN", "UNKNOWN", "FAILED"}, "eval proof_status is invalid")
        proof = value.get("proof")
        acceptance = value.get("acceptance")
        regressions = value.get("regressions")
        metrics = value.get("metrics")
        evidence = value.get("evidence")
        _expect(isinstance(proof, list) and isinstance(acceptance, list) and isinstance(regressions, list), "eval outcomes must be arrays")
        _expect(isinstance(metrics, Mapping), "eval metrics must be an object")
        _expect(isinstance(evidence, list), "eval evidence must be an array")
        proof_levels = [str(item.get("id")) for item in proof if item.get("status") == "PASS" and str(item.get("id")) in PROOF_LEVELS]
        proof_level = max(proof_levels, key=PROOF_LEVELS.index) if proof_levels else None
        return {
            "source_kind": "eval-result-v0.1",
            "source_digest": source_digest,
            "status": status,
            "proof_level": proof_level,
            "proof_status": proof_status,
            "task_domains": [],
            "status_counts": {
                "proof": _status_counts(proof),
                "acceptance": _status_counts(acceptance),
                "regressions": _status_counts(regressions),
            },
            "metrics": {
                "duration_ms": None,
                "repair_cycles": metrics.get("repair_cycles"),
                "tokens": metrics.get("tokens"),
                "wall_time_ms": metrics.get("wall_time_ms"),
            },
            "counts": {
                "checks": len(proof) + len(acceptance),
                "artifacts": len(evidence),
                "errors": 0,
                "warnings": 0,
                "unknowns": sum(1 for item in [*proof, *acceptance] if item.get("status") == "UNKNOWN"),
            },
        }

    raise ShadowEvidenceError("unsupported outcome contract; expected result-v1.1 or eval-result-v0.1")


def validate_event(value: Any) -> dict[str, Any]:
    _expect(isinstance(value, Mapping), "shadow evidence event must be an object")
    required = {"schema_version", "event_id", "event_type", "receipt_id", "observed_at", "payload"}
    _expect(set(value) == required, "shadow evidence event keys are invalid")
    _expect(value.get("schema_version") == SCHEMA_VERSION, "unsupported shadow evidence schema_version")
    event_id = _opaque(value.get("event_id"), label="event_id")
    event_type = str(value.get("event_type"))
    _expect(event_type in EVENT_TYPES, "event_type is invalid")
    receipt_id = _opaque(value.get("receipt_id"), label="receipt_id")
    observed_at = _normalize_time(str(value.get("observed_at")))
    payload = value.get("payload")
    _expect(isinstance(payload, Mapping), "event payload must be an object")

    if event_type == "SHADOW_CAPTURED":
        _expect(event_id == f"capture:{receipt_id}", "capture event_id must be deterministic")
        required_payload = {"context", "legacy", "g3_candidates", "comparison", "shadow_digest"}
        _expect(set(payload) == required_payload, "capture payload keys are invalid")
        shadow_without_digest = {
            "context": payload["context"],
            "legacy": payload["legacy"],
            "g3_candidates": payload["g3_candidates"],
            "comparison": payload["comparison"],
        }
        expected_digest = _digest(shadow_without_digest)
        _expect(payload.get("shadow_digest") == expected_digest, "capture shadow_digest mismatch")
    else:
        _expect(event_id == f"outcome:{receipt_id}", "outcome event_id must be deterministic")
        required_payload = {"shadow_digest", "execution", "outcome"}
        _expect(set(payload) == required_payload, "outcome payload keys are invalid")

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "receipt_id": receipt_id,
        "observed_at": observed_at,
        "payload": dict(payload),
    }


def event_json(event: Mapping[str, Any]) -> str:
    return json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_events(path: str | Path) -> list[dict[str, Any]]:
    ledger = Path(path)
    if not ledger.is_file():
        return []
    events: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for line_number, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ShadowEvidenceError(f"invalid JSON on ledger line {line_number}: {exc}") from exc
        event = validate_event(payload)
        canonical = event_json(event)
        previous = seen.get(event["event_id"])
        if previous is not None and previous != canonical:
            raise ShadowEvidenceError(f"conflicting duplicate event_id: {event['event_id']}")
        if previous is None:
            seen[event["event_id"]] = canonical
            events.append(event)
    return events


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def append_event(path: str | Path, event: Mapping[str, Any]) -> dict[str, Any]:
    ledger = Path(path)
    normalized = validate_event(event)
    canonical = event_json(normalized)
    events = load_events(ledger)
    for existing in events:
        if existing["event_id"] != normalized["event_id"]:
            continue
        if event_json(existing) == canonical:
            return {"status": "UNCHANGED", "event": normalized}
        raise ShadowEvidenceError(f"conflicting duplicate event_id: {normalized['event_id']}")
    lines = [event_json(item) for item in events]
    lines.append(canonical)
    _atomic_write(ledger, "\n".join(lines) + "\n")
    return {"status": "APPENDED", "event": normalized}


def _events_for_receipt(events: Sequence[Mapping[str, Any]], receipt_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    normalized_receipt = _opaque(receipt_id, label="receipt_id")
    captures = [dict(item) for item in events if item["receipt_id"] == normalized_receipt and item["event_type"] == "SHADOW_CAPTURED"]
    joins = [dict(item) for item in events if item["receipt_id"] == normalized_receipt and item["event_type"] == "OUTCOME_JOINED"]
    _expect(len(captures) == 1, f"receipt requires exactly one SHADOW_CAPTURED event: {normalized_receipt}")
    _expect(len(joins) <= 1, f"receipt has conflicting OUTCOME_JOINED events: {normalized_receipt}")
    return captures[0], joins[0] if joins else None


def build_outcome_event(
    *,
    receipt_id: str,
    capture_event: Mapping[str, Any],
    outcome: Mapping[str, Any],
    outcome_ref: str,
    route_kind: str,
    strategy: str,
    execution_ref: str,
    candidate_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_receipt = _opaque(receipt_id, label="receipt_id")
    capture = validate_event(capture_event)
    _expect(capture["event_type"] == "SHADOW_CAPTURED", "capture_event is not SHADOW_CAPTURED")
    _expect(capture["receipt_id"] == normalized_receipt, "capture receipt_id mismatch")
    _expect(route_kind in ROUTE_KINDS, "route_kind is invalid")
    normalized_strategy = _opaque(strategy, label="strategy")
    normalized_execution_ref = _opaque(execution_ref, label="execution_ref")
    normalized_outcome_ref = _opaque(outcome_ref, label="outcome_ref")
    normalized_candidate_id = None if candidate_id is None else _opaque(candidate_id, label="candidate_id")

    candidates = {item["id"]: item for item in capture["payload"]["g3_candidates"]}
    if route_kind == "legacy":
        _expect(normalized_candidate_id is None, "legacy outcome must not name a G3 candidate")
    else:
        _expect(normalized_candidate_id is not None, "g3_candidate route requires candidate_id")
        _expect(normalized_candidate_id in candidates, "executed G3 candidate was not present in captured candidate set")
        selected = candidates[normalized_candidate_id]
        _expect(selected["strategy"] == normalized_strategy, "executed strategy does not match captured G3 candidate")
        _expect(selected["state"] != "BLOCKED", "cannot join an outcome to a G3 candidate that was BLOCKED at capture time")

    normalized_outcome = normalize_outcome(outcome)
    normalized_outcome["source_ref"] = normalized_outcome_ref
    payload = {
        "shadow_digest": capture["payload"]["shadow_digest"],
        "execution": {
            "route_kind": route_kind,
            "strategy": normalized_strategy,
            "source_ref": normalized_execution_ref,
            "candidate_id": normalized_candidate_id,
        },
        "outcome": normalized_outcome,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"outcome:{normalized_receipt}",
        "event_type": "OUTCOME_JOINED",
        "receipt_id": normalized_receipt,
        "observed_at": _normalize_time(observed_at),
        "payload": payload,
    }


def materialize_receipt(events: Sequence[Mapping[str, Any]], receipt_id: str) -> dict[str, Any]:
    capture, joined = _events_for_receipt(events, receipt_id)
    if joined is not None:
        _expect(
            joined["payload"]["shadow_digest"] == capture["payload"]["shadow_digest"],
            "joined outcome is bound to a different shadow digest",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": capture["receipt_id"],
        "captured_at": capture["observed_at"],
        "shadow_digest": capture["payload"]["shadow_digest"],
        "context": capture["payload"]["context"],
        "legacy": capture["payload"]["legacy"],
        "g3_candidates": capture["payload"]["g3_candidates"],
        "comparison": capture["payload"]["comparison"],
        "join_state": "JOINED" if joined is not None else "PENDING",
        "outcome_joined_at": None if joined is None else joined["observed_at"],
        "execution": None if joined is None else joined["payload"]["execution"],
        "outcome": None if joined is None else joined["payload"]["outcome"],
    }


def materialize_all(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    receipt_ids = sorted({str(item["receipt_id"]) for item in events if item["event_type"] == "SHADOW_CAPTURED"})
    return [materialize_receipt(events, receipt_id) for receipt_id in receipt_ids]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="record one bounded G3 shadow comparison")
    capture.add_argument("--receipt-id", required=True)
    capture.add_argument("--shadow", required=True)
    capture.add_argument("--observed-at")

    join = sub.add_parser("join", help="join one real execution outcome to an existing shadow capture")
    join.add_argument("--receipt-id", required=True)
    join.add_argument("--outcome", required=True)
    join.add_argument("--outcome-ref", required=True)
    join.add_argument("--route-kind", choices=ROUTE_KINDS, required=True)
    join.add_argument("--strategy", required=True)
    join.add_argument("--execution-ref", required=True)
    join.add_argument("--candidate-id")
    join.add_argument("--observed-at")

    materialize = sub.add_parser("materialize", help="materialize joined shadow receipts")
    materialize.add_argument("--receipt-id")

    return parser


def _write_payload(payload: Any, *, pretty: bool) -> None:
    if pretty:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
        ledger = Path(args.ledger)

        if args.command == "capture":
            shadow = _read_json(args.shadow, label="shadow comparison")
            event = build_capture_event(
                receipt_id=args.receipt_id,
                shadow_compare=shadow,
                observed_at=args.observed_at,
            )
            result = append_event(ledger, event)
            _write_payload(result, pretty=args.pretty)
            return 0

        if args.command == "join":
            events = load_events(ledger)
            capture, existing_join = _events_for_receipt(events, args.receipt_id)
            outcome = _read_json(args.outcome, label="real outcome")
            event = build_outcome_event(
                receipt_id=args.receipt_id,
                capture_event=capture,
                outcome=outcome,
                outcome_ref=args.outcome_ref,
                route_kind=args.route_kind,
                strategy=args.strategy,
                execution_ref=args.execution_ref,
                candidate_id=args.candidate_id,
                observed_at=args.observed_at,
            )
            if existing_join is not None and event_json(existing_join) != event_json(event):
                raise ShadowEvidenceError(f"receipt already has a different joined outcome: {args.receipt_id}")
            result = append_event(ledger, event)
            _write_payload(result, pretty=args.pretty)
            return 0

        events = load_events(ledger)
        if args.receipt_id:
            payload: Any = materialize_receipt(events, args.receipt_id)
        else:
            payload = materialize_all(events)
        _write_payload(payload, pretty=args.pretty)
        return 0

    except (ShadowEvidenceError, StrategyResolverError, OSError, ValueError) as exc:
        sys.stderr.write(f"shadow_evidence configuration error: {exc}\n")
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
