from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from capability_snapshot import build_snapshot  # noqa: E402
from strategy_resolver import (  # noqa: E402
    StrategyResolverError,
    build_strategy_candidates,
)


def capability(
    capability_id: str,
    *,
    kind: str,
    domains: list[str],
    features: list[str],
    sensitivity: list[str] | None = None,
    network: str = "none",
    policy_requirements: dict | None = None,
    probe: dict | None = None,
) -> dict:
    availability = {"state": "DECLARED"}
    if probe is not None:
        availability["probe"] = probe
    item = {
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
        "availability": availability,
    }
    if policy_requirements:
        item["policy_requirements"] = policy_requirements
    return item


def base_registry(*extras: dict) -> dict:
    items = [
        capability(
            "runtime.orchestrator",
            kind="agent",
            domains=["ALL"],
            features=["strategy.coordinate"],
            probe={"type": "always"},
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
            probe={"type": "always"},
        ),
        *extras,
    ]
    return {"schema_version": "2.0", "registry_id": "test.g3", "capabilities": items}


def intent(*, work_mode: str = "observe", sensitivity: str = "private", coordination: str = "minimal") -> dict:
    return {
        "schema_version": "1.0",
        "id": "task-001",
        "goal": "Inspect the gameplay behavior",
        "domains": ["GAMEPLAY"],
        "work_mode": work_mode,
        "required_proof": "P3",
        "sensitivity": sensitivity,
        "acceptance": [{"id": "behavior.ok", "required": True, "claim": "behavior is observed"}],
        "preferences": {"coordination": coordination},
    }


def authority(
    *,
    sensitivity_ceiling: str = "secret",
    isolated_write: bool = False,
    delegate: bool = False,
    network: bool = False,
    policy_tokens: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "subject": "runtime.primary-agent",
        "permissions": {
            "read_repo": True,
            "write_isolated_workspace": isolated_write,
            "write_repo": False,
            "execute_tools": True,
            "delegate": delegate,
            "network": network,
            "integrate": False,
            "merge": False,
            "publish": False,
        },
        "sensitivity_ceiling": sensitivity_ceiling,
        "policy_tokens": policy_tokens or [],
        "expires_on": "task_end",
    }


def candidate(payload: dict, strategy: str) -> dict:
    return next(item for item in payload["candidates"] if item["strategy"] == strategy)


class StrategyResolverTests(unittest.TestCase):
    def test_direct_candidate_is_ready_when_required_capabilities_are_probed(self) -> None:
        registry = base_registry()
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(intent(), authority(), snapshot, registry)
        direct = candidate(result, "direct-agent-with-tools")
        self.assertTrue(result["advisory_only"])
        self.assertEqual("READY", direct["state"])
        self.assertEqual("P3", direct["proof_target"])

    def test_modify_prefers_isolated_mutation_shape_and_blocks_direct_mutation(self) -> None:
        ovp = capability(
            "runtime.ovp-mutation",
            kind="adapter",
            domains=["GAMEPLAY"],
            features=["workspace.isolated.mutation", "repo.worktree", "review.boundary"],
            probe={"type": "always"},
        )
        registry = base_registry(ovp)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(
            intent(work_mode="modify"),
            authority(isolated_write=True),
            snapshot,
            registry,
        )
        isolated = candidate(result, "isolated-mutation-agent")
        direct = candidate(result, "direct-agent-with-tools")
        self.assertEqual("READY", isolated["state"])
        self.assertEqual("BLOCKED", direct["state"])
        self.assertIn("modify_requires_isolated_mutation_candidate", direct["reasons"])

    def test_secret_intent_does_not_bind_public_private_external_worker(self) -> None:
        worker = capability(
            "worker.external",
            kind="adapter",
            domains=["ALL"],
            features=["agent.delegate.proposal"],
            sensitivity=["public", "private"],
            network="required",
            probe={"type": "always"},
        )
        registry = base_registry(worker)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(
            intent(work_mode="propose", sensitivity="secret"),
            authority(delegate=True, network=True),
            snapshot,
            registry,
        )
        delegated = candidate(result, "single-delegate-proposal")
        self.assertEqual("BLOCKED", delegated["state"])
        binding = next(item for item in delegated["bindings"] if item["feature"] == "agent.delegate.proposal")
        self.assertEqual([], binding["matches"])

    def test_network_denial_filters_network_required_worker(self) -> None:
        worker = capability(
            "worker.external",
            kind="adapter",
            domains=["ALL"],
            features=["agent.delegate.proposal"],
            sensitivity=["public", "private"],
            network="required",
            probe={"type": "always"},
        )
        registry = base_registry(worker)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(
            intent(work_mode="propose"),
            authority(delegate=True, network=False),
            snapshot,
            registry,
        )
        self.assertEqual("BLOCKED", candidate(result, "single-delegate-proposal")["state"])

    def test_local_secret_worker_can_satisfy_delegate_feature(self) -> None:
        worker = capability(
            "worker.local",
            kind="adapter",
            domains=["ALL"],
            features=["agent.delegate.proposal"],
            network="none",
            probe={"type": "always"},
        )
        registry = base_registry(worker)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(
            intent(work_mode="propose", sensitivity="secret"),
            authority(delegate=True, network=False),
            snapshot,
            registry,
        )
        delegated = candidate(result, "single-delegate-proposal")
        self.assertEqual("READY", delegated["state"])

    def test_policy_tokens_are_required_for_conditional_capability_lane(self) -> None:
        worker = capability(
            "worker.policy",
            kind="adapter",
            domains=["ALL"],
            features=["agent.delegate.proposal"],
            sensitivity=["private"],
            network="required",
            policy_requirements={"private": ["explicit.private_worker"]},
            probe={"type": "always"},
        )
        registry = base_registry(worker)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        blocked = build_strategy_candidates(
            intent(work_mode="propose"),
            authority(delegate=True, network=True),
            snapshot,
            registry,
        )
        allowed = build_strategy_candidates(
            intent(work_mode="propose"),
            authority(
                delegate=True,
                network=True,
                policy_tokens=["explicit.private_worker"],
            ),
            snapshot,
            registry,
        )
        self.assertEqual("BLOCKED", candidate(blocked, "single-delegate-proposal")["state"])
        self.assertEqual("READY", candidate(allowed, "single-delegate-proposal")["state"])

    def test_swarm_stays_conditional_when_parallelism_is_not_preferred(self) -> None:
        worker = capability(
            "worker.local",
            kind="adapter",
            domains=["ALL"],
            features=["agent.delegate.proposal"],
            probe={"type": "always"},
        )
        swarm = capability(
            "adapter.adaptive-swarm",
            kind="adapter",
            domains=["ALL"],
            features=["strategy.multi_agent.adaptive"],
            probe={"type": "always"},
        )
        registry = base_registry(worker, swarm)
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        minimal = build_strategy_candidates(
            intent(work_mode="propose", coordination="minimal"),
            authority(delegate=True),
            snapshot,
            registry,
        )
        parallel = build_strategy_candidates(
            intent(work_mode="propose", coordination="parallel_ok"),
            authority(delegate=True),
            snapshot,
            registry,
        )
        self.assertEqual("CONDITIONAL", candidate(minimal, "adaptive-swarm")["state"])
        self.assertIn("coordination_not_preferred", candidate(minimal, "adaptive-swarm")["reasons"])
        self.assertEqual("READY", candidate(parallel, "adaptive-swarm")["state"])

    def test_sensitivity_ceiling_blocks_all_candidates(self) -> None:
        registry = base_registry()
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(
            intent(sensitivity="secret"),
            authority(sensitivity_ceiling="private"),
            snapshot,
            registry,
        )
        self.assertTrue(all(item["state"] == "BLOCKED" for item in result["candidates"]))

    def test_registry_digest_mismatch_is_rejected(self) -> None:
        registry = base_registry()
        snapshot = build_snapshot(registry, observed_at="2026-09-18T00:00:00Z")
        changed = base_registry(
            capability(
                "tool.extra",
                kind="tool",
                domains=["CODE"],
                features=["extra.feature"],
                probe={"type": "always"},
            )
        )
        with self.assertRaisesRegex(StrategyResolverError, "registry_digest"):
            build_strategy_candidates(intent(), authority(), snapshot, changed)

    def test_declared_only_capability_makes_candidate_conditional_not_ready(self) -> None:
        registry = base_registry()
        snapshot = build_snapshot(registry, probe=False, observed_at="2026-09-18T00:00:00Z")
        result = build_strategy_candidates(intent(), authority(), snapshot, registry)
        direct = candidate(result, "direct-agent-with-tools")
        self.assertEqual("CONDITIONAL", direct["state"])
        self.assertTrue(any(reason.startswith("unprobed_capability:") for reason in direct["reasons"]))


if __name__ == "__main__":
    unittest.main()
