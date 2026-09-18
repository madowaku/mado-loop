from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from capability_snapshot import build_snapshot  # noqa: E402
from strategy_shadow_compare import compare_shadow  # noqa: E402
from shadow_evidence import (  # noqa: E402
    ShadowEvidenceError,
    append_event,
    build_capture_event,
    build_outcome_event,
    event_json,
    load_events,
    materialize_receipt,
    normalize_outcome,
    validate_event,
)
from common.result import make_artifact, make_check, make_result  # noqa: E402


def capability(
    capability_id: str,
    *,
    kind: str,
    domains: list[str],
    features: list[str],
    sensitivity: list[str] | None = None,
    network: str = "none",
) -> dict:
    return {
        "schema_version": "2.0",
        "id": capability_id,
        "kind": kind,
        "domains": domains,
        "features": features,
        "provenance": {"source": "fixture", "implementation": capability_id},
        "requirements": {
            "network": network,
            "credentials": "none",
            "executables": [],
            "files": [],
            "env": [],
        },
        "sensitivity_support": sensitivity or ["public", "private", "secret"],
        "evidence_interfaces": ["report"],
        "availability": {"state": "DECLARED", "probe": {"type": "always"}},
    }


def registry() -> dict:
    return {
        "schema_version": "2.0",
        "registry_id": "test.g4",
        "capabilities": [
            capability(
                "runtime.orchestrator",
                kind="agent",
                domains=["ALL"],
                features=["strategy.coordinate"],
            ),
            capability(
                "engine.godot",
                kind="engine",
                domains=["CODE", "GAMEPLAY", "UI", "ANIMATION", "ASSET_INTEGRATION", "PLAYTEST", "RELEASE"],
                features=[
                    "engine.project.inspect",
                    "engine.runtime.execute",
                    "evidence.static",
                    "evidence.layout",
                    "evidence.behavior",
                    "artifact.export",
                ],
            ),
            capability(
                "worker.local",
                kind="adapter",
                domains=["ALL"],
                features=["agent.delegate.proposal"],
            ),
            capability(
                "adapter.adaptive-swarm",
                kind="adapter",
                domains=["ALL"],
                features=["strategy.multi_agent.adaptive"],
            ),
        ],
    }


def intent() -> dict:
    return {
        "schema_version": "1.0",
        "id": "task-g4",
        "goal": "SECRET-GOAL-TEXT fix gameplay code bug",
        "domains": ["CODE", "GAMEPLAY"],
        "work_mode": "propose",
        "required_proof": "P3",
        "sensitivity": "private",
        "acceptance": [
            {
                "id": "behavior.ok",
                "required": True,
                "claim": "SECRET-ACCEPTANCE-TEXT behavior is observed",
            }
        ],
        "preferences": {"coordination": "minimal"},
    }


def authority(*, delegate: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "subject": "runtime.primary-agent",
        "permissions": {
            "read_repo": True,
            "write_isolated_workspace": False,
            "write_repo": False,
            "execute_tools": True,
            "delegate": delegate,
            "network": False,
            "integrate": False,
            "merge": False,
            "publish": False,
        },
        "sensitivity_ceiling": "private",
        "policy_tokens": [],
        "expires_on": "task_end",
    }


def shadow(*, delegate: bool = True) -> dict:
    reg = registry()
    snapshot = build_snapshot(reg, observed_at="2026-09-18T00:00:00Z")
    return compare_shadow(intent(), authority(delegate=delegate), snapshot, reg)


def real_result() -> dict:
    return make_result(
        "fixture_tool",
        proof_level="P3",
        summary="SECRET-SUMMARY-TEXT",
        task_domains=["CODE", "GAMEPLAY"],
        checks=[
            make_check(
                "behavior",
                "PASS",
                message="SECRET-CHECK-MESSAGE",
                evidence=["SECRET-EVIDENCE-CONTENT"],
            )
        ],
        artifacts=[make_artifact("SECRET-PATH/trace.json", "report")],
        duration_ms=321,
    )


def eval_result() -> dict:
    return {
        "schema_version": "0.1",
        "run_id": "run-g4-001",
        "case_id": "case.g4",
        "case_digest": "sha256:" + "1" * 64,
        "candidate": {"id": "legacy", "revision": None, "digest": None},
        "status": "WARN",
        "proof_status": "PARTIAL",
        "proof": [
            {"id": "P0", "status": "PASS", "required": True, "evidence": ["SECRET-EV"], "detail": "SECRET-DETAIL"},
            {"id": "P3", "status": "UNKNOWN", "required": True, "evidence": [], "detail": None},
        ],
        "acceptance": [
            {"id": "behavior", "status": "WARN", "required": True, "evidence": [], "detail": None}
        ],
        "regressions": [],
        "metrics": {"repair_cycles": 2, "tokens": 444, "wall_time_ms": 555},
        "failure_signatures": ["proof:P3:UNKNOWN"],
        "evidence": [{"kind": "log", "path": "SECRET-EVAL-PATH.log", "sha256": None}],
        "environment": {"secretish": "SECRET-ENV-VALUE"},
    }


class ShadowEvidenceTests(unittest.TestCase):
    def test_capture_is_content_free_and_accepts_g3_projection_source_ref(self) -> None:
        event = build_capture_event(
            receipt_id="receipt.g4.001",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        encoded = event_json(event)
        self.assertNotIn("SECRET-GOAL-TEXT", encoded)
        self.assertNotIn("SECRET-ACCEPTANCE-TEXT", encoded)
        self.assertIn("classify_task.py+adaptive_swarm.choose_roles", encoded)
        self.assertEqual("SHADOW_CAPTURED", event["event_type"])
        self.assertTrue(event["payload"]["shadow_digest"].startswith("sha256:"))

    def test_common_result_join_keeps_only_bounded_outcome_summary(self) -> None:
        capture = build_capture_event(
            receipt_id="receipt.g4.002",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        joined = build_outcome_event(
            receipt_id="receipt.g4.002",
            capture_event=capture,
            outcome=real_result(),
            outcome_ref="proof:run-002",
            route_kind="legacy",
            strategy="legacy-live-route",
            execution_ref="route:run-002",
            observed_at="2026-09-18T00:02:00Z",
        )
        encoded = event_json(joined)
        for secret in (
            "SECRET-SUMMARY-TEXT",
            "SECRET-CHECK-MESSAGE",
            "SECRET-EVIDENCE-CONTENT",
            "SECRET-PATH",
        ):
            self.assertNotIn(secret, encoded)
        outcome = joined["payload"]["outcome"]
        self.assertEqual("result-v1.1", outcome["source_kind"])
        self.assertEqual("PASS", outcome["status"])
        self.assertEqual("P3", outcome["proof_level"])
        self.assertEqual(321, outcome["metrics"]["duration_ms"])
        self.assertEqual(1, outcome["counts"]["checks"])

    def test_eval_result_join_does_not_leak_detail_paths_or_environment(self) -> None:
        normalized = normalize_outcome(eval_result())
        encoded = json.dumps(normalized, sort_keys=True)
        self.assertNotIn("SECRET-DETAIL", encoded)
        self.assertNotIn("SECRET-EVAL-PATH", encoded)
        self.assertNotIn("SECRET-ENV-VALUE", encoded)
        self.assertEqual("eval-result-v0.1", normalized["source_kind"])
        self.assertEqual("PARTIAL", normalized["proof_status"])
        self.assertEqual("P0", normalized["proof_level"])
        self.assertEqual(2, normalized["metrics"]["repair_cycles"])
        self.assertEqual(444, normalized["metrics"]["tokens"])

    def test_legacy_outcome_is_never_attributed_to_g3_candidate(self) -> None:
        capture = build_capture_event(
            receipt_id="receipt.g4.003",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        joined = build_outcome_event(
            receipt_id="receipt.g4.003",
            capture_event=capture,
            outcome=real_result(),
            outcome_ref="proof:run-003",
            route_kind="legacy",
            strategy="legacy-live-route",
            execution_ref="route:run-003",
            observed_at="2026-09-18T00:02:00Z",
        )
        self.assertIsNone(joined["payload"]["execution"]["candidate_id"])
        self.assertNotIn("candidate_outcome", joined["payload"])

    def test_g3_candidate_join_requires_captured_nonblocked_candidate(self) -> None:
        ready_capture = build_capture_event(
            receipt_id="receipt.g4.004",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        joined = build_outcome_event(
            receipt_id="receipt.g4.004",
            capture_event=ready_capture,
            outcome=real_result(),
            outcome_ref="proof:run-004",
            route_kind="g3_candidate",
            strategy="direct-agent-with-tools",
            execution_ref="canary:run-004",
            candidate_id="strategy.direct-agent-with-tools",
            observed_at="2026-09-18T00:02:00Z",
        )
        self.assertEqual("strategy.direct-agent-with-tools", joined["payload"]["execution"]["candidate_id"])

        blocked_capture = build_capture_event(
            receipt_id="receipt.g4.005",
            shadow_compare=shadow(delegate=False),
            observed_at="2026-09-18T00:01:00Z",
        )
        with self.assertRaisesRegex(ShadowEvidenceError, "BLOCKED"):
            build_outcome_event(
                receipt_id="receipt.g4.005",
                capture_event=blocked_capture,
                outcome=real_result(),
                outcome_ref="proof:run-005",
                route_kind="g3_candidate",
                strategy="single-delegate-proposal",
                execution_ref="canary:run-005",
                candidate_id="strategy.single-delegate-proposal",
                observed_at="2026-09-18T00:02:00Z",
            )

    def test_append_is_idempotent_and_conflicting_duplicate_is_rejected(self) -> None:
        capture = build_capture_event(
            receipt_id="receipt.g4.006",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "shadow.jsonl"
            first = append_event(ledger, capture)
            second = append_event(ledger, capture)
            self.assertEqual("APPENDED", first["status"])
            self.assertEqual("UNCHANGED", second["status"])
            self.assertEqual(1, len(load_events(ledger)))

            changed = dict(capture)
            changed["observed_at"] = "2026-09-18T00:03:00Z"
            with self.assertRaisesRegex(ShadowEvidenceError, "conflicting duplicate event_id"):
                append_event(ledger, changed)

    def test_materialize_preserves_pending_then_joined_state(self) -> None:
        capture = build_capture_event(
            receipt_id="receipt.g4.007",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        pending = materialize_receipt([capture], "receipt.g4.007")
        self.assertEqual("PENDING", pending["join_state"])
        self.assertIsNone(pending["outcome"])

        joined = build_outcome_event(
            receipt_id="receipt.g4.007",
            capture_event=capture,
            outcome=real_result(),
            outcome_ref="proof:run-007",
            route_kind="legacy",
            strategy="legacy-live-route",
            execution_ref="route:run-007",
            observed_at="2026-09-18T00:02:00Z",
        )
        complete = materialize_receipt([capture, joined], "receipt.g4.007")
        self.assertEqual("JOINED", complete["join_state"])
        self.assertEqual("PASS", complete["outcome"]["status"])

    def test_tampered_shadow_digest_is_rejected_on_read(self) -> None:
        capture = build_capture_event(
            receipt_id="receipt.g4.008",
            shadow_compare=shadow(),
            observed_at="2026-09-18T00:01:00Z",
        )
        capture["payload"]["shadow_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ShadowEvidenceError, "shadow_digest mismatch"):
            validate_event(capture)

    def test_join_to_unknown_receipt_is_rejected_by_materializer(self) -> None:
        with self.assertRaisesRegex(ShadowEvidenceError, "exactly one"):
            materialize_receipt([], "receipt.g4.missing")


if __name__ == "__main__":
    unittest.main()
