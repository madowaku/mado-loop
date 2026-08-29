from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".agents" / "skills" / "mado-loop" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import nvidia_request_profiles as profiles  # noqa: E402
import provider_router  # noqa: E402


class NvidiaRequestProfileTests(unittest.TestCase):
    def provider(self, model: str) -> provider_router.WorkerProvider:
        return provider_router.WorkerProvider(
            name="nvidia",
            base_url="https://integrate.api.nvidia.com/v1",
            model=model,
            api_key="secret",
            external=True,
            logs_content=False,
            privacy_mode="hosted-external;private-requires-explicit-consent",
        )

    def test_kimi_architect_uses_max_reasoning(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("moonshotai/kimi-k3"),
            prompt="Design the architecture",
            system="You are the architecture worker in a MADO LOOP adaptive swarm.",
            max_tokens=8192,
            temperature=None,
        )
        self.assertEqual(profile.name, "kimi-k3-architect-max")
        self.assertEqual(payload["temperature"], 1.0)
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertNotIn("reasoning_budget", payload)

    def test_kimi_specialist_uses_high_reasoning(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("moonshotai/kimi-k3"),
            prompt="Review UI layout",
            system="You are the game UI specialist in a MADO LOOP adaptive swarm.",
        )
        self.assertEqual(profile.name, "kimi-k3-specialist-high")
        self.assertEqual(payload["reasoning_effort"], "high")

    def test_deepseek_implementer_uses_max_reasoning_and_cap(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("deepseek-ai/deepseek-v4-pro-0813"),
            prompt="Propose the patch",
            system="You are the implementation worker in a MADO LOOP adaptive swarm.",
            max_tokens=50000,
        )
        self.assertEqual(profile.name, "deepseek-v4-pro-coding-max")
        self.assertEqual(payload["max_tokens"], 16384)
        self.assertEqual(payload["reasoning_effort"], "max")

    def test_lightning_recon_uses_small_bounded_reasoning_budget(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("nvidia/nemotron-3.5-lightning-30b-a3b"),
            prompt="Find likely responsibility boundaries",
            system="You are the reconnaissance worker in a MADO LOOP adaptive swarm.",
            max_tokens=8000,
        )
        self.assertEqual(profile.name, "nemotron-lightning-recon-fast")
        self.assertEqual(payload["reasoning_budget"], 2000)
        self.assertLessEqual(payload["reasoning_budget"], payload["max_tokens"] // 2)

    def test_lightning_verification_gets_more_budget_than_recon(self) -> None:
        selected = self.provider("nvidia/nemotron-3.5-lightning-30b-a3b")
        recon, _ = profiles.build_profiled_request(
            selected,
            prompt="Recon",
            system="You are the reconnaissance worker in a MADO LOOP adaptive swarm.",
            max_tokens=8000,
        )
        verify, _ = profiles.build_profiled_request(
            selected,
            prompt="Tests",
            system="You are the verification worker in a MADO LOOP adaptive swarm.",
            max_tokens=8000,
        )
        self.assertGreater(verify["reasoning_budget"], recon["reasoning_budget"])

    def test_ultra_reviewer_uses_high_reasoning_with_half_budget(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("nvidia/nemotron-3-ultra-550b-a55b"),
            prompt="Review proposals",
            system="You are the adversarial reviewer in a MADO LOOP adaptive swarm.",
            max_tokens=12000,
        )
        self.assertEqual(profile.name, "nemotron-ultra-review-high")
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["reasoning_budget"], 6000)

    def test_explicit_temperature_override_wins(self) -> None:
        payload, _ = profiles.build_profiled_request(
            self.provider("moonshotai/kimi-k3"),
            prompt="Do it",
            system="You are the architecture worker in a MADO LOOP adaptive swarm.",
            temperature=0.6,
        )
        self.assertEqual(payload["temperature"], 0.6)

    def test_nvidia_rejects_temperature_above_api_limit(self) -> None:
        with self.assertRaisesRegex(profiles.NvidiaRequestProfileError, "between 0 and 1"):
            profiles.build_profiled_request(
                self.provider("moonshotai/kimi-k3"),
                prompt="Do it",
                temperature=1.2,
            )

    def test_unknown_nvidia_model_falls_back_without_reasoning_fields(self) -> None:
        payload, profile = profiles.build_profiled_request(
            self.provider("vendor/future-model"),
            prompt="Do it",
            max_tokens=2048,
            temperature=None,
        )
        self.assertIsNone(profile)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("reasoning_budget", payload)

    def test_non_nvidia_provider_is_rejected(self) -> None:
        selected = provider_router.WorkerProvider(
            name="local",
            base_url="http://127.0.0.1:1234/v1",
            model="local",
            api_key="local",
            external=False,
            logs_content=False,
            privacy_mode="local-only",
        )
        with self.assertRaisesRegex(profiles.NvidiaRequestProfileError, "require the nvidia provider"):
            profiles.build_profiled_request(selected, prompt="Do it")


if __name__ == "__main__":
    unittest.main()
