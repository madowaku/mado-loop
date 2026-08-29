from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import adaptive_swarm  # noqa: E402
import nvidia_fleet  # noqa: E402


NVIDIA_ENV = {"NVIDIA_API_KEY": "test-nvidia-key"}


class NvidiaFleetTests(unittest.TestCase):
    def test_profile_routes_code_team_to_curated_models(self) -> None:
        plan = nvidia_fleet.plan_fleet(task="codeを実装して", env=NVIDIA_ENV)
        self.assertEqual(plan["profile"], nvidia_fleet.PROFILE_NAME)
        self.assertEqual(plan["request_profile_adapter"], "nvidia-request-profiles/v1")
        by_role = {item["role"]: item for item in plan["assignments"]}
        self.assertEqual(by_role["implementer"]["provider"]["name"], "nvidia")
        self.assertEqual(
            by_role["implementer"]["provider"]["model"],
            "deepseek-ai/deepseek-v4-pro-0813",
        )
        self.assertEqual(
            by_role["test_writer"]["provider"]["model"],
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        )

    def test_complex_ui_task_uses_kimi_for_reasoning_and_specialist(self) -> None:
        plan = nvidia_fleet.plan_fleet(
            task="HUD UIのarchitectureを整理して実装と検証まで設計して",
            env=NVIDIA_ENV,
        )
        by_role = {item["role"]: item for item in plan["assignments"]}
        self.assertEqual(by_role["architect"]["provider"]["model"], "moonshotai/kimi-k3")
        self.assertEqual(by_role["ui_specialist"]["provider"]["model"], "moonshotai/kimi-k3")

    def test_recon_uses_lightning(self) -> None:
        plan = nvidia_fleet.plan_fleet(task="この件を整理して次の一手を考えて", env=NVIDIA_ENV)
        self.assertEqual(plan["assignments"][0]["role"], "recon")
        self.assertEqual(
            plan["assignments"][0]["provider"]["model"],
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        )

    def test_reviewer_uses_ultra_after_fan_in(self) -> None:
        seen: list[tuple[str, str, int, float]] = []

        def fake_caller(selected, *, prompt, system, max_tokens, temperature, **kwargs):
            seen.append((system, selected.model, max_tokens, temperature))
            return {"content": "proposal", "usage": None}

        result = nvidia_fleet.run_fleet(
            task="codeを実装して",
            env=NVIDIA_ENV,
            caller=fake_caller,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["request_profile_adapter"], "nvidia-request-profiles/v1")
        reviewer_models = [model for system, model, _, _ in seen if "adversarial reviewer" in system]
        self.assertEqual(reviewer_models, ["nvidia/nemotron-3-ultra-550b-a55b"])
        self.assertTrue(all(max_tokens == 8192 for _, _, max_tokens, _ in seen))
        self.assertTrue(all(temperature == 1.0 for _, _, _, temperature in seen))
        self.assertEqual(result["proof_status"], "UNPROVEN")

    def test_profile_command_exposes_request_profiles_without_credentials(self) -> None:
        profile = nvidia_fleet.profile_public_dict()
        self.assertEqual(profile["request_profile_adapter"], "nvidia-request-profiles/v1")
        self.assertIn("kimi-k3-architect-max", profile["request_profiles"])
        self.assertNotIn("api_key", str(profile))

    def test_private_requires_explicit_opt_in(self) -> None:
        with self.assertRaisesRegex(adaptive_swarm.AdaptiveSwarmConfigError, "private tasks require"):
            nvidia_fleet.plan_fleet(
                task="codeを実装して",
                sensitivity="private",
                env=NVIDIA_ENV,
            )

        plan = nvidia_fleet.plan_fleet(
            task="codeを実装して",
            sensitivity="private",
            allow_nvidia_private=True,
            env=NVIDIA_ENV,
        )
        self.assertTrue(plan["assignments"])
        for item in plan["assignments"]:
            self.assertEqual(item["provider"]["name"], "nvidia")

    def test_secret_never_uses_hosted_nvidia(self) -> None:
        with self.assertRaisesRegex(adaptive_swarm.AdaptiveSwarmConfigError, "external providers"):
            nvidia_fleet.plan_fleet(
                task="secret codeを実装して",
                sensitivity="secret",
                env=NVIDIA_ENV,
            )

    def test_profile_never_exposes_api_key(self) -> None:
        plan = nvidia_fleet.plan_fleet(task="codeを実装して", env=NVIDIA_ENV)
        serialized = str(plan)
        self.assertNotIn("test-nvidia-key", serialized)
        self.assertNotIn("api_key", serialized)


if __name__ == "__main__":
    unittest.main()
