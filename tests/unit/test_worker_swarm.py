from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import provider_router  # noqa: E402
import worker_swarm as swarm  # noqa: E402


OPENROUTER_ENV = {
    "OPENROUTER_API_KEY": "test-secret-key",
    "MADO_OPENROUTER_MODEL": "example/model",
}


class WorkerSwarmTests(unittest.TestCase):
    def test_plan_redacts_credentials_and_preserves_authority(self) -> None:
        plan = swarm.plan_swarm(env=OPENROUTER_ENV)
        self.assertEqual(plan["schema"], swarm.SCHEMA_VERSION)
        self.assertEqual(plan["primary_roles"], list(swarm.PRIMARY_ROLES))
        self.assertEqual(plan["parallelism"], 3)
        self.assertEqual(plan["provider"]["name"], "openrouter")
        self.assertNotIn("api_key", plan["provider"])
        self.assertEqual(plan["mutation_authority"], "orchestrator-only")
        self.assertEqual(plan["proof_authority"], "P0-P5 proof system")

    def test_primary_workers_really_fan_out_before_review(self) -> None:
        barrier = threading.Barrier(3)
        review_seen = []

        def fake_caller(selected, *, prompt, system, **kwargs):
            if "adversarial reviewer" in system:
                self.assertIn("## architect", prompt)
                self.assertIn("## implementer", prompt)
                self.assertIn("## test_writer", prompt)
                review_seen.append(True)
                return {"content": "reviewed", "usage": {"total_tokens": 7}}
            barrier.wait(timeout=2)
            role = prompt.splitlines()[0].split(":", 1)[1].strip()
            return {"content": f"proposal from {role}", "usage": {"total_tokens": 3}}

        result = swarm.run_swarm(
            task="Add a bounded dash mechanic",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            [item["role"] for item in result["primary_results"]],
            list(swarm.PRIMARY_ROLES),
        )
        self.assertEqual(result["review_result"]["role"], "reviewer")
        self.assertTrue(review_seen)
        self.assertTrue(result["integration_required"])
        self.assertEqual(result["proof_status"], "UNPROVEN")

    def test_result_order_is_deterministic_even_if_completion_order_is_not(self) -> None:
        gates = {
            "architect": threading.Event(),
            "implementer": threading.Event(),
            "test_writer": threading.Event(),
        }
        gates["test_writer"].set()

        def fake_caller(selected, *, prompt, system, **kwargs):
            if "adversarial reviewer" in system:
                return {"content": "review", "usage": None}
            role = prompt.splitlines()[0].split(":", 1)[1].strip()
            if role == "test_writer":
                gates["implementer"].set()
            elif role == "implementer":
                gates["implementer"].wait(timeout=1)
                gates["architect"].set()
            else:
                gates["architect"].wait(timeout=1)
            return {"content": role, "usage": None}

        result = swarm.run_swarm(
            task="Keep output ordering stable",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(
            [item["role"] for item in result["primary_results"]],
            ["architect", "implementer", "test_writer"],
        )

    def test_one_worker_failure_is_isolated_and_review_still_runs(self) -> None:
        def fake_caller(selected, *, prompt, system, **kwargs):
            if "adversarial reviewer" in system:
                self.assertIn("ProviderCallError", prompt)
                return {"content": "reviewed partial swarm", "usage": None}
            role = prompt.splitlines()[0].split(":", 1)[1].strip()
            if role == "implementer":
                raise provider_router.ProviderCallError("quota exhausted")
            return {"content": f"ok {role}", "usage": None}

        result = swarm.run_swarm(
            task="Review partial failures",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "WARN")
        by_role = {item["role"]: item for item in result["primary_results"]}
        self.assertEqual(by_role["implementer"]["status"], "ERROR")
        self.assertEqual(by_role["architect"]["status"], "PASS")
        self.assertEqual(result["review_result"]["status"], "PASS")

    def test_all_primary_fail_skips_reviewer_and_fails_swarm(self) -> None:
        calls = []

        def fake_caller(selected, *, prompt, system, **kwargs):
            calls.append(system)
            raise provider_router.ProviderCallError("offline")

        result = swarm.run_swarm(
            task="All workers unavailable",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["review_result"])
        self.assertEqual(len(calls), 3)

    def test_secret_swarm_requires_and_uses_local_provider(self) -> None:
        local_env = {
            "MADO_LOCAL_BASE_URL": "http://127.0.0.1:1234/v1",
            "MADO_LOCAL_MODEL": "local-model",
        }
        plan = swarm.plan_swarm(sensitivity="secret", env=local_env)
        self.assertEqual(plan["provider"]["name"], "local")
        self.assertFalse(plan["provider"]["external"])

    def test_roles_must_be_unique_and_known(self) -> None:
        with self.assertRaisesRegex(swarm.SwarmConfigError, "unique"):
            swarm.parse_roles("architect,architect")
        with self.assertRaisesRegex(swarm.SwarmConfigError, "must be drawn"):
            swarm.parse_roles("architect,release_manager")

    def test_parallelism_is_bounded(self) -> None:
        with self.assertRaisesRegex(swarm.SwarmConfigError, "between 1 and 8"):
            swarm.plan_swarm(max_workers=9, env=OPENROUTER_ENV)

    def test_task_and_context_are_bounded(self) -> None:
        with self.assertRaisesRegex(swarm.SwarmConfigError, "task exceeds"):
            swarm.run_swarm(task="x" * (swarm.MAX_TASK_CHARS + 1), env=OPENROUTER_ENV)
        with self.assertRaisesRegex(swarm.SwarmConfigError, "context exceeds"):
            swarm.run_swarm(
                task="bounded task",
                context="x" * (swarm.MAX_CONTEXT_CHARS + 1),
                env=OPENROUTER_ENV,
            )

    def test_review_can_be_disabled(self) -> None:
        def fake_caller(selected, *, prompt, system, **kwargs):
            return {"content": "proposal", "usage": None}

        result = swarm.run_swarm(
            task="No review stage",
            review=False,
            roles=("architect",),
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertIsNone(result["review_result"])
        self.assertEqual(result["parallelism"], 1)


if __name__ == "__main__":
    unittest.main()
