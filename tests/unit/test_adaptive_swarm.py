from __future__ import annotations

from pathlib import Path
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm as adaptive  # noqa: E402
import provider_router  # noqa: E402


OPENROUTER_ENV = {
    "OPENROUTER_API_KEY": "test-secret-key",
    "MADO_OPENROUTER_MODEL": "default/model",
}


class AdaptiveSwarmTests(unittest.TestCase):
    def test_ui_task_selects_ui_implementer_and_verification(self) -> None:
        plan = adaptive.plan_adaptive_swarm(
            task="ボス戦HUDのボタン配置を改善して",
            env=OPENROUTER_ENV,
        )
        self.assertEqual(plan["domains"], ["UI"])
        self.assertEqual(
            [item["role"] for item in plan["assignments"]],
            ["ui_specialist", "implementer", "test_writer"],
        )
        self.assertEqual(plan["review_role"], "reviewer")
        self.assertEqual(plan["mutation_authority"], "orchestrator-only")

    def test_mixed_gameplay_ui_adds_architect_and_domain_specialists(self) -> None:
        plan = adaptive.plan_adaptive_swarm(
            task="戦闘gameplayとHUD UIを同時に改善して",
            env=OPENROUTER_ENV,
        )
        self.assertEqual(plan["domains"], ["GAMEPLAY", "UI"])
        self.assertEqual(
            [item["role"] for item in plan["assignments"]],
            ["architect", "gameplay_specialist", "ui_specialist", "implementer", "test_writer"],
        )
        self.assertGreaterEqual(plan["complexity_score"], 2)

    def test_release_is_audit_team_not_implicit_implementer(self) -> None:
        plan = adaptive.plan_adaptive_swarm(
            task="release buildを公開前に監査して",
            env=OPENROUTER_ENV,
        )
        roles = [item["role"] for item in plan["assignments"]]
        self.assertEqual(roles, ["architect", "test_writer", "release_auditor"])
        self.assertNotIn("implementer", roles)

    def test_ambiguous_task_routes_to_recon_only(self) -> None:
        plan = adaptive.plan_adaptive_swarm(
            task="この件を整理して次の一手を考えて",
            env=OPENROUTER_ENV,
        )
        self.assertEqual(plan["domains"], [])
        self.assertEqual([item["role"] for item in plan["assignments"]], ["recon"])
        self.assertIsNone(plan["review_role"])

    def test_tier_model_profiles_route_roles_to_different_models(self) -> None:
        env = {
            **OPENROUTER_ENV,
            "MADO_ADAPTIVE_MODEL_SPECIALIST": "special/model",
            "MADO_ADAPTIVE_MODEL_CODING": "code/model",
            "MADO_ADAPTIVE_MODEL_VERIFICATION": "verify/model",
        }
        plan = adaptive.plan_adaptive_swarm(
            task="HUD UIを改善して",
            env=env,
        )
        by_role = {item["role"]: item for item in plan["assignments"]}
        self.assertEqual(by_role["ui_specialist"]["provider"]["model"], "special/model")
        self.assertEqual(by_role["implementer"]["provider"]["model"], "code/model")
        self.assertEqual(by_role["test_writer"]["provider"]["model"], "verify/model")
        for item in plan["assignments"]:
            self.assertNotIn("api_key", item["provider"])

    def test_role_override_beats_tier_profile(self) -> None:
        env = {
            **OPENROUTER_ENV,
            "MADO_ADAPTIVE_MODEL_CODING": "code/model",
            "MADO_ADAPTIVE_MODEL_IMPLEMENTER": "implementer/model",
        }
        plan = adaptive.plan_adaptive_swarm(task="codeを実装して", env=env)
        by_role = {item["role"]: item for item in plan["assignments"]}
        self.assertEqual(by_role["implementer"]["provider"]["model"], "implementer/model")

    def test_secret_team_uses_local_provider_only(self) -> None:
        env = {
            "OPENROUTER_API_KEY": "must-not-be-used",
            "MADO_OPENROUTER_MODEL": "external/model",
            "MADO_LOCAL_BASE_URL": "http://127.0.0.1:1234/v1",
            "MADO_LOCAL_MODEL": "local-model",
        }
        plan = adaptive.plan_adaptive_swarm(
            task="secret codeを実装して",
            sensitivity="secret",
            env=env,
        )
        self.assertTrue(plan["assignments"])
        for item in plan["assignments"]:
            self.assertEqual(item["provider"]["name"], "local")
            self.assertFalse(item["provider"]["external"])

    def test_primary_workers_fan_out_and_reviewer_runs_after_fan_in(self) -> None:
        barrier = threading.Barrier(2)
        review_seen = []

        def fake_caller(selected, *, prompt, system, **kwargs):
            if "adversarial reviewer" in system:
                self.assertIn("## implementer", prompt)
                self.assertIn("## test_writer", prompt)
                review_seen.append(True)
                return {"content": "reviewed", "usage": None}
            barrier.wait(timeout=2)
            role = prompt.splitlines()[0].split(":", 1)[1].strip()
            return {"content": f"proposal {role}", "usage": None}

        result = adaptive.run_adaptive_swarm(
            task="codeを実装して",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            [item["role"] for item in result["primary_results"]],
            ["implementer", "test_writer"],
        )
        self.assertTrue(review_seen)
        self.assertEqual(result["proof_status"], "UNPROVEN")
        self.assertTrue(result["integration_required"])

    def test_partial_worker_failure_is_warn_and_review_continues(self) -> None:
        def fake_caller(selected, *, prompt, system, **kwargs):
            if "adversarial reviewer" in system:
                self.assertIn("ProviderCallError", prompt)
                return {"content": "review partial", "usage": None}
            role = prompt.splitlines()[0].split(":", 1)[1].strip()
            if role == "implementer":
                raise provider_router.ProviderCallError("quota")
            return {"content": "tests proposal", "usage": None}

        result = adaptive.run_adaptive_swarm(
            task="codeを実装して",
            env=OPENROUTER_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "WARN")
        by_role = {item["role"]: item for item in result["primary_results"]}
        self.assertEqual(by_role["implementer"]["status"], "ERROR")
        self.assertEqual(by_role["test_writer"]["status"], "PASS")
        self.assertEqual(result["review_result"]["status"], "PASS")

    def test_reviewer_can_use_separate_verification_model(self) -> None:
        seen_models = []
        env = {
            **OPENROUTER_ENV,
            "MADO_ADAPTIVE_MODEL_CODING": "code/model",
            "MADO_ADAPTIVE_MODEL_VERIFICATION": "verify/model",
        }

        def fake_caller(selected, *, prompt, system, **kwargs):
            seen_models.append((system, selected.model))
            return {"content": "ok", "usage": None}

        adaptive.run_adaptive_swarm(
            task="codeを実装して",
            env=env,
            caller=fake_caller,
        )
        implementation_models = [model for system, model in seen_models if "implementation worker" in system]
        reviewer_models = [model for system, model in seen_models if "adversarial reviewer" in system]
        self.assertEqual(implementation_models, ["code/model"])
        self.assertEqual(reviewer_models, ["verify/model"])

    def test_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(adaptive.AdaptiveSwarmConfigError, "between 1 and 8"):
            adaptive.plan_adaptive_swarm(task="codeを実装して", max_workers=9, env=OPENROUTER_ENV)
        with self.assertRaisesRegex(adaptive.AdaptiveSwarmConfigError, "context exceeds"):
            adaptive.run_adaptive_swarm(
                task="codeを実装して",
                context="x" * (adaptive.MAX_CONTEXT_CHARS + 1),
                env=OPENROUTER_ENV,
            )


if __name__ == "__main__":
    unittest.main()
