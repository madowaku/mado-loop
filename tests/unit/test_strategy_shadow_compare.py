from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from capability_snapshot import build_snapshot  # noqa: E402
from strategy_shadow_compare import compare_shadow  # noqa: E402


def capability(capability_id: str, *, kind: str, domains: list[str], features: list[str]) -> dict:
    return {
        "schema_version": "2.0",
        "id": capability_id,
        "kind": kind,
        "domains": domains,
        "features": features,
        "provenance": {"source": "fixture", "implementation": capability_id},
        "requirements": {
            "network": "none",
            "credentials": "none",
            "executables": [],
            "files": [],
            "env": [],
        },
        "sensitivity_support": ["public", "private", "secret"],
        "evidence_interfaces": ["report"],
        "availability": {"state": "DECLARED", "probe": {"type": "always"}},
    }


def registry() -> dict:
    return {
        "schema_version": "2.0",
        "registry_id": "test.shadow",
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
                ],
            ),
        ],
    }


def intent() -> dict:
    return {
        "schema_version": "1.0",
        "id": "task-shadow",
        "goal": "Fix gameplay enemy behavior bug",
        "domains": ["CODE", "GAMEPLAY"],
        "work_mode": "observe",
        "required_proof": "P3",
        "sensitivity": "private",
        "acceptance": [{"id": "enemy.ok", "required": True, "claim": "enemy behavior is correct"}],
        "preferences": {"coordination": "minimal"},
    }


def authority() -> dict:
    return {
        "schema_version": "1.0",
        "subject": "runtime.primary-agent",
        "permissions": {
            "read_repo": True,
            "write_isolated_workspace": False,
            "write_repo": False,
            "execute_tools": True,
            "delegate": False,
            "network": False,
            "integrate": False,
            "merge": False,
            "publish": False,
        },
        "sensitivity_ceiling": "private",
        "policy_tokens": [],
        "expires_on": "task_end",
    }


class StrategyShadowCompareTests(unittest.TestCase):
    def test_projection_runs_legacy_classifier_and_team_policy_without_execution(self) -> None:
        reg = registry()
        snapshot = build_snapshot(reg, observed_at="2026-09-18T00:00:00Z")
        result = compare_shadow(intent(), authority(), snapshot, reg)
        self.assertTrue(result["shadow_only"])
        self.assertEqual("projection", result["legacy"]["source"])
        self.assertIn("GAMEPLAY", result["legacy"]["domains"])
        self.assertGreaterEqual(result["comparison"]["legacy_role_count"], 1)
        self.assertIn("direct-agent-with-tools", result["comparison"]["ready_strategies"])

    def test_observed_legacy_plan_can_replace_projection(self) -> None:
        reg = registry()
        snapshot = build_snapshot(reg, observed_at="2026-09-18T00:00:00Z")
        observed = {
            "strategy": "legacy-observed-route",
            "domains": ["CODE", "GAMEPLAY"],
            "roles": ["implementer", "test_writer"],
            "review": True,
            "source_ref": "run-123",
        }
        result = compare_shadow(
            intent(),
            authority(),
            snapshot,
            reg,
            legacy_observation=observed,
        )
        self.assertEqual("observed", result["legacy"]["source"])
        self.assertEqual("run-123", result["legacy"]["source_ref"])
        self.assertTrue(result["comparison"]["domain_exact_match"])

    def test_comparison_reports_observations_but_never_declares_a_winner(self) -> None:
        reg = registry()
        snapshot = build_snapshot(reg, observed_at="2026-09-18T00:00:00Z")
        result = compare_shadow(intent(), authority(), snapshot, reg)
        encoded_keys = set(result["comparison"])
        self.assertNotIn("winner", encoded_keys)
        self.assertNotIn("recommended", encoded_keys)
        self.assertIsInstance(result["comparison"]["observations"], list)


if __name__ == "__main__":
    unittest.main()
